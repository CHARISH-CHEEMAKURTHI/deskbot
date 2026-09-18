"""Phase 2: notices what your machine is doing and nudges the brain's mood.

Polled on a slow timer (a few seconds -- this isn't the render loop) from
main.py. Every check just calls brain.set_mood(), the same hook the
right-click menu and any future voice/AI watcher use, so the brain treats
it as a suggestion and keeps doing its own thing in between.

Foreground-window info needs an X11 connection (python-xlib), which is
why deskbot forces XWayland -- see main.py's _ensure_xwayland_backend.
Without it (or without the optional dependency installed), that one
signal quietly drops out and the CPU/memory/battery checks keep working.
"""

from __future__ import annotations

import random
import time
from dataclasses import dataclass, field

import psutil

from .expressions import Expression

try:
    from Xlib import X
    from Xlib import display as xdisplay
except ImportError:  # pragma: no cover - optional dependency
    xdisplay = None


LOADING_LINES = ["hmm, loading...", "come on, come on", "almost there?", "any day now"]
STUCK_LINES = ["still going??", "is this thing stuck?", "we could be here a while"]
LOW_BATTERY_LINES = ["battery's getting low...", "might wanna plug in soon"]
LOW_MEMORY_LINES = ["things are getting tight in there", "maybe close a few tabs?"]


class _ActiveWindow:
    """Best-effort _NET_ACTIVE_WINDOW lookup. Silently inert if X11 isn't reachable."""

    def __init__(self) -> None:
        self._display = None
        if xdisplay is not None:
            try:
                self._display = xdisplay.Display()
            except Exception:
                self._display = None

    def info(self) -> tuple[str | None, int | None]:
        """Returns (process name, pid) of the foreground window, or (None, None)."""
        if self._display is None:
            return None, None
        try:
            root = self._display.screen().root
            prop = root.get_full_property(
                self._display.intern_atom("_NET_ACTIVE_WINDOW"), X.AnyPropertyType
            )
            win_id = prop.value[0] if prop else None
            if not win_id:
                return None, None
            window = self._display.create_resource_object("window", win_id)
            pid_prop = window.get_full_property(
                self._display.intern_atom("_NET_WM_PID"), X.AnyPropertyType
            )
            pid = int(pid_prop.value[0]) if pid_prop else None
            wm_class = window.get_wm_class()
            name = wm_class[1] if wm_class else None
            return name, pid
        except Exception:
            return None, None


@dataclass
class ActivityWatcher:
    cfg: object
    _active_win: _ActiveWindow = field(default_factory=_ActiveWindow)
    _procs: dict = field(default_factory=dict)
    _busy_app_name: str | None = None
    _busy_app_since: float | None = None
    _stuck_said: bool = False
    _system_busy_since: float | None = None
    _low_battery_said: bool = False
    _low_memory_said: bool = False

    def __post_init__(self) -> None:
        psutil.cpu_percent(interval=None)  # first call has no baseline -- discard it
        self._poll_count = 0

    # -- entry point -------------------------------------------------
    def poll(self, brain) -> None:
        if not getattr(self.cfg, "activity_aware", True):
            return
        now = time.monotonic()
        self._check_busy_foreground_app(now, brain)
        self._check_system_load(now, brain)
        self._check_battery(brain)
        self._check_memory(brain)

        self._poll_count += 1
        if self._poll_count % 40 == 0:  # every couple of minutes, at the default rate
            self._prune_dead_procs()

    def _tracked(self, pid: int) -> "psutil.Process | None":
        """A cached psutil.Process for pid, so cpu_percent(None) has a
        baseline to diff against -- process.children() hands back a fresh,
        unprimed Process object every call, which would otherwise always
        read back the meaningless "first call" value of 0.0."""
        proc = self._procs.get(pid)
        if proc is not None:
            return proc
        try:
            proc = psutil.Process(pid)
            proc.cpu_percent(interval=None)  # prime it, this first reading is bogus
        except psutil.Error:
            return None
        self._procs[pid] = proc
        return proc

    def _prune_dead_procs(self) -> None:
        for pid in [pid for pid in self._procs if not psutil.pid_exists(pid)]:
            del self._procs[pid]

    # -- signals ------------------------------------------------------
    def _check_busy_foreground_app(self, now: float, brain) -> None:
        name, pid = self._active_win.info()
        if pid is None:
            self._busy_app_name = None
            self._busy_app_since = None
            self._stuck_said = False
            return

        root = self._tracked(pid)
        if root is None:
            return

        # The heavy lifting behind a focused window is often a child process
        # (a shell running `make`/`npm install` inside a terminal, a
        # browser's renderer) rather than the window's own PID, so sum the
        # whole tree. A brand-new child reads 0.0 on the poll it first
        # appears -- harmless, it corrects itself next tick.
        try:
            cpu = root.cpu_percent(interval=None)
            for child in root.children(recursive=True):
                child_proc = self._tracked(child.pid)
                if child_proc is not None:
                    try:
                        cpu += child_proc.cpu_percent(interval=None)
                    except psutil.Error:
                        continue
        except psutil.Error:
            self._procs.pop(pid, None)
            return

        if cpu < self.cfg.busy_cpu_percent:
            self._busy_app_name = None
            self._busy_app_since = None
            self._stuck_said = False
            return

        if self._busy_app_name != name:
            self._busy_app_name = name
            self._busy_app_since = now
            self._stuck_said = False
            return

        elapsed = now - self._busy_app_since
        if elapsed > self.cfg.stuck_after_seconds:
            # Keep reinforcing ANGRY for as long as it's stuck -- the app
            # being frozen doesn't stop just because we already complained
            # once -- but only repeat the line occasionally.
            say = None
            if not self._stuck_said or random.random() < 0.05:
                self._stuck_said = True
                say = random.choice(STUCK_LINES)
            brain.set_mood(Expression.ANGRY, self._mood_hold(), say=say)
        elif elapsed > self.cfg.loading_after_seconds:
            say = random.choice(LOADING_LINES) if random.random() < 0.15 else None
            brain.set_mood(Expression.THINKING, self._mood_hold(), say=say)

    def _check_system_load(self, now: float, brain) -> None:
        cpu = psutil.cpu_percent(interval=None)
        if cpu < self.cfg.system_busy_percent:
            self._system_busy_since = None
            return
        if self._system_busy_since is None:
            self._system_busy_since = now
            return
        elapsed = now - self._system_busy_since
        if elapsed > self.cfg.loading_after_seconds:
            say = random.choice(LOADING_LINES) if random.random() < 0.10 else None
            brain.set_mood(Expression.THINKING, self._mood_hold(), say=say)

    def _mood_hold(self) -> float:
        """A forced-mood duration that always outlasts the next poll, so
        the mood doesn't flicker back to normal in between checks."""
        return max(4.0, self.cfg.activity_poll_interval * 2)

    def _check_battery(self, brain) -> None:
        try:
            batt = psutil.sensors_battery()
        except Exception:
            return
        if batt is None or batt.power_plugged:
            self._low_battery_said = False
            return
        if batt.percent <= self.cfg.low_battery_percent and not self._low_battery_said:
            self._low_battery_said = True
            brain.set_mood(Expression.SAD, 6.0, say=random.choice(LOW_BATTERY_LINES))

    def _check_memory(self, brain) -> None:
        mem = psutil.virtual_memory()
        if mem.percent >= self.cfg.low_memory_percent:
            if not self._low_memory_said:
                self._low_memory_said = True
                brain.set_mood(Expression.SURPRISED, 5.0, say=random.choice(LOW_MEMORY_LINES))
        else:
            self._low_memory_said = False
