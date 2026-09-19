"""The bot's brain: decides where to walk and which face to wear.

Phase 2 (activity detection) plugs in here -- call brain.set_mood() from
whatever watcher notices you're compiling, or Chrome is stalling, etc.
The brain treats those as suggestions and blends them with what it's
already doing.
"""

from __future__ import annotations

import math
import random
import time
from dataclasses import dataclass
from enum import Enum, auto

from .expressions import Expression


class Mode(Enum):
    FOLLOW = auto()     # walking after the cursor
    WANDER = auto()     # cursor is idle, bot mooches about
    REST = auto()       # standing still near the cursor
    SLEEP = auto()      # nobody's home
    DRAGGED = auto()    # user is holding it


@dataclass
class Decision:
    target: tuple[float, float]
    expression: Expression
    walking: bool
    speech: str | None = None


IDLE_LINES = [
    "just vibing",
    "what are we building?",
    "psst... take a break?",
    "still here!",
]
CATCH_UP_LINES = ["wait for me!", "hey! slow down", "on my way"]
WAKE_LINES = ["oh! you're back", "morning!", "*yawn*"]


class Brain:
    def __init__(self, cfg):
        self.cfg = cfg
        self.mode = Mode.REST
        self.expression = Expression.NEUTRAL

        # None, not (0, 0) -- a zero sentinel makes the first real sample
        # look like a huge jump, which would mark the cursor as "moving"
        # before we've seen it move at all.
        self._cursor_last: tuple[float, float] | None = None
        self._cursor_speed = 0.0
        self._cursor_still_for = 0.0
        self._cursor_ever_moved = False
        self._blind_warned = False
        self._wander_target: tuple[float, float] | None = None
        self._next_wander = 0.0
        self._next_chat = time.monotonic() + random.uniform(25, 60)

        # temporary override, e.g. set by a context watcher or the menu
        self._forced: Expression | None = None
        self._forced_until = 0.0
        self._speech: str | None = None
        self._speech_until = 0.0

    # -- external hooks --------------------------------------------------
    def set_mood(self, expr: Expression, seconds: float = 4.0, say: str | None = None) -> None:
        """Force an expression for a while. Phase 2 watchers call this."""
        self._forced = expr
        self._forced_until = time.monotonic() + seconds
        if say:
            self.say(say)

    def say(self, text: str, seconds: float | None = None) -> None:
        self._speech = text
        self._speech_until = time.monotonic() + (seconds or self.cfg.speech_duration)

    @property
    def speech(self) -> str | None:
        return self._speech if time.monotonic() < self._speech_until else None

    # -- main tick -------------------------------------------------------
    def update(self, dt: float, cursor: tuple[float, float],
               pos: tuple[float, float], bounds) -> Decision:
        now = time.monotonic()
        self._track_cursor(dt, cursor)
        self._pick_mode(dt, cursor, bounds, now)

        target = self._pick_target(cursor, pos, bounds, now)
        dist = math.dist(pos, target)
        walking = dist > self.cfg.stop_distance * 0.35 and self.mode is not Mode.DRAGGED

        expr = self._pick_expression(dist, walking, now)
        self._maybe_chat(now, walking)
        return Decision(target, expr, walking, self.speech)

    # -- internals -------------------------------------------------------
    def _track_cursor(self, dt: float, cursor) -> None:
        if self._cursor_last is None:
            self._cursor_last = cursor
            self._cursor_speed = 0.0
            return
        moved = math.dist(cursor, self._cursor_last)
        self._cursor_speed = moved / dt if dt > 0 else 0.0
        if moved > 3:
            self._cursor_still_for = 0.0
            self._cursor_ever_moved = True
        else:
            self._cursor_still_for += dt
        self._cursor_last = cursor

    def _cursor_is_blind(self) -> bool:
        """True once it's clear we're getting no cursor data at all, rather
        than watching an idle user. On Wayland, XWayland only sees the
        pointer while it's over one of our own windows, so QCursor.pos()
        freezes the moment the cursor moves anywhere else -- which would
        otherwise look like "user went away" and put the bot to sleep
        forever, standing still. Roam instead."""
        if self._cursor_ever_moved or not getattr(self.cfg, "wayland_session", False):
            return False
        return self._cursor_still_for > max(8.0, self.cfg.cursor_idle_before_wander)

    def _pick_mode(self, dt: float, cursor, bounds, now: float) -> None:
        if self.mode is Mode.DRAGGED:
            return

        blind = self._cursor_is_blind()
        if not self.cfg.follow_cursor or blind:
            if blind and not self._blind_warned:
                self._blind_warned = True
                self.say("can't see your cursor on Wayland -- roaming instead", 8.0)
                print(
                    "[deskbot] No cursor movement is reaching us -- on Wayland, "
                    "XWayland can only see the pointer over our own windows, so "
                    "cursor-following can't work. Roaming the desktop instead. "
                    "Run `python -m deskbot --doctor` for the details and the fix."
                )
            # Blind means never sleep: that "idle" timer is measuring stale data.
            if blind or self.mode not in (Mode.WANDER, Mode.SLEEP):
                self.mode = Mode.WANDER
            return

        still = self._cursor_still_for
        if still < 0.6:
            if self.mode is Mode.SLEEP:
                self.say(random.choice(WAKE_LINES))
                self.set_mood(Expression.SURPRISED, 1.5)
            self.mode = Mode.FOLLOW
            self._wander_target = None
        elif still > self.cfg.cursor_idle_before_sleep:
            self.mode = Mode.SLEEP
        elif still > self.cfg.cursor_idle_before_wander:
            self.mode = Mode.WANDER
        elif self.mode is Mode.FOLLOW:
            self.mode = Mode.REST

    def _pick_target(self, cursor, pos, bounds, now: float):
        if self.mode is Mode.DRAGGED:
            return pos

        if self.mode in (Mode.WANDER, Mode.SLEEP):
            if self._wander_target is None or now > self._next_wander:
                self._next_wander = now + random.uniform(
                    self.cfg.wander_interval * 0.6, self.cfg.wander_interval * 1.6
                )
                if self.mode is Mode.SLEEP:
                    self._wander_target = pos
                else:
                    self._wander_target = (
                        random.uniform(bounds.left() + 80, bounds.right() - 80),
                        random.uniform(bounds.top() + 120, bounds.bottom() - 80),
                    )
            return self._wander_target

        # FOLLOW / REST: stand a step behind the cursor, on the side it came from
        dx = pos[0] - cursor[0]
        side = 1.0 if dx >= 0 else -1.0
        tx = cursor[0] + side * self.cfg.trail_distance
        ty = cursor[1] + self.cfg.trail_distance * 0.25
        tx = min(max(tx, bounds.left() + 60), bounds.right() - 60)
        ty = min(max(ty, bounds.top() + 100), bounds.bottom() - 60)
        return (tx, ty)

    def _pick_expression(self, dist: float, walking: bool, now: float) -> Expression:
        if self._forced and now < self._forced_until:
            return self._forced
        self._forced = None

        if self.mode is Mode.DRAGGED:
            return Expression.SURPRISED
        if self.mode is Mode.SLEEP:
            return Expression.SLEEPING
        if self._cursor_speed > self.cfg.fast_cursor_speed and self.cfg.follow_cursor:
            if random.random() < 0.02:
                self.say(random.choice(CATCH_UP_LINES))
            return Expression.SURPRISED
        if walking and dist > self.cfg.stop_distance * 3.5:
            return Expression.CHEERING       # long sprint = hype mode
        if walking:
            return Expression.HAPPY
        if self.mode is Mode.WANDER:
            return Expression.THINKING
        return Expression.NEUTRAL

    def _maybe_chat(self, now: float, walking: bool) -> None:
        if not self.cfg.chatty or walking or self.speech:
            return
        if now >= self._next_chat:
            self._next_chat = now + random.uniform(45, 120)
            self.say(random.choice(IDLE_LINES))
