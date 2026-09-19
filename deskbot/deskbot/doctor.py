"""`python -m deskbot --doctor` -- checks the things that actually break.

Every "the bot isn't doing anything" report so far has come down to one of
a handful of environment problems (no cursor data under Wayland, a model
that was never pulled, a missing X11 connection), none of which the bot
itself can tell you about while it's busy looking broken. This prints all
of them at once.
"""

from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.request


def _line(label: str, value: object) -> None:
    print(f"  {label:<22}: {value}")


def _section(name: str) -> None:
    print(f"\n{name}")


def _check_session(cfg) -> bool:
    """Returns True if this looks like a Wayland session."""
    _section("session")
    session_type = os.environ.get("XDG_SESSION_TYPE", "(unset)")
    wayland_display = os.environ.get("WAYLAND_DISPLAY", "(unset)")
    wayland = bool(os.environ.get("WAYLAND_DISPLAY")) or session_type == "wayland"

    _line("XDG_SESSION_TYPE", session_type)
    _line("WAYLAND_DISPLAY", wayland_display)
    _line("DISPLAY", os.environ.get("DISPLAY", "(unset)"))
    _line("QT_QPA_PLATFORM", os.environ.get("QT_QPA_PLATFORM", "(unset)"))
    _line("desktop", os.environ.get("XDG_CURRENT_DESKTOP", "(unset)"))
    _line("verdict", "Wayland session" if wayland else "X11 session")
    return wayland


def _check_cursor(wayland: bool, seconds: float = 4.0) -> None:
    _section("cursor tracking (phase 1)")
    from PyQt6.QtGui import QCursor, QGuiApplication

    screen = QGuiApplication.primaryScreen()
    _line("qt platform", QGuiApplication.platformName())
    if screen is not None:
        geo = screen.availableGeometry()
        _line("primary screen", f"{geo.width()}x{geo.height()} at ({geo.x()},{geo.y()})")
    _line("screens", len(QGuiApplication.screens()))

    print(f"\n  >>> move your mouse around for the next {seconds:.0f} seconds <<<\n")
    seen = set()
    first = last = None
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        pos = QCursor.pos()
        point = (pos.x(), pos.y())
        seen.add(point)
        if first is None:
            first = point
        last = point
        time.sleep(0.05)

    _line("first sample", first)
    _line("last sample", last)
    _line("distinct positions", len(seen))

    if len(seen) > 3:
        _line("verdict", "OK -- cursor position updates, following will work")
        return

    _line("verdict", "FROZEN -- cursor position never changed")
    if wayland:
        print(
            "\n  Cause: on Wayland, XWayland only sees the pointer while it is over\n"
            "  an XWayland window, so QCursor.pos() goes stale as soon as your\n"
            "  cursor moves over anything else. Wayland has no protocol for a\n"
            "  client to ask where the global pointer is -- that is by design.\n"
            "\n"
            "  Fix: log out, and at the login screen click the gear icon and pick\n"
            "  the Xorg / X11 session, then start deskbot again. Cursor-following,\n"
            "  always-on-top and dragging all work properly there.\n"
            "\n"
            "  Until then deskbot notices the frozen cursor and roams the desktop\n"
            "  on its own instead of standing still or falling asleep."
        )
    else:
        print(
            "\n  You are on X11, where this should work -- if you genuinely did move\n"
            "  the mouse during the sampling window, that is a real bug: please\n"
            "  report this output."
        )


def _check_active_window() -> None:
    _section("foreground-window detection (phase 2)")
    try:
        from Xlib import display  # noqa: F401
    except ImportError:
        _line("python-xlib", "NOT INSTALLED -- pip install -r requirements.txt")
        return
    _line("python-xlib", "installed")

    from .activity import _ActiveWindow

    name, pid = _ActiveWindow().info()
    if pid is None:
        _line("active window", "unavailable -- busy-app detection will stay quiet")
    else:
        _line("active window", f"{name} (pid {pid})")


def _check_ollama(cfg) -> None:
    _section("ollama (phase 3: actions + chat)")
    _line("url", cfg.ollama_url)
    url = cfg.ollama_url.rstrip("/") + "/api/tags"
    try:
        with urllib.request.urlopen(url, timeout=5) as resp:
            data = json.loads(resp.read())
    except (urllib.error.URLError, OSError, json.JSONDecodeError) as exc:
        _line("reachable", f"NO -- {exc}")
        print(
            "\n  Fix: start it with `ollama serve`. If that says 'address already\n"
            "  in use', it is already running as a service and this is a different\n"
            "  problem -- check `curl http://localhost:11434/api/tags`."
        )
        return

    models = [m.get("name", "") for m in data.get("models", []) if m.get("name")]
    _line("reachable", "yes")
    _line("models pulled", ", ".join(models) if models else "NONE")
    _line("configured model", cfg.ollama_model)

    if not models:
        print(f"\n  Fix: nothing is pulled yet. Run:  ollama pull {cfg.ollama_model}")
        return
    if cfg.ollama_model in models:
        _line("verdict", "OK")
        return

    from .intent import resolve_model

    try:
        chosen = resolve_model(cfg)
    except Exception as exc:  # pragma: no cover - defensive
        chosen = f"(could not resolve: {exc})"
    _line("verdict", f"configured model NOT pulled -- falling back to {chosen}")
    print(
        f"\n  deskbot will use {chosen} automatically, so things work either way.\n"
        f"  To use the configured one instead:  ollama pull {cfg.ollama_model}\n"
        f'  Or make the fallback permanent:  set "ollama_model": "{chosen}" in\n'
        f"  ~/.config/deskbot/config.json"
    )


def _check_actions(cfg) -> None:
    _section("actions + messaging (phase 3)")
    smtp_user = getattr(cfg, "smtp_user", "") or os.environ.get("DESKBOT_SMTP_USER", "")
    smtp_pass = getattr(cfg, "smtp_password", "") or os.environ.get(
        "DESKBOT_SMTP_PASSWORD", ""
    )
    _line("email (smtp)", "configured" if smtp_user and smtp_pass else "not configured")
    contacts = getattr(cfg, "whatsapp_contacts", {}) or {}
    _line("whatsapp contacts", ", ".join(sorted(contacts)) if contacts else "none")
    enabled = getattr(cfg, "whatsapp_business_enabled", False)
    _line("whatsapp two-way chat", "enabled" if enabled else "disabled")
    if enabled:
        _line("  webhook port", getattr(cfg, "whatsapp_webhook_port", 8765))
        allowed = getattr(cfg, "whatsapp_allowed_numbers", []) or []
        _line("  allowed senders", ", ".join(allowed) if allowed else "NONE SET (nobody can chat)")


def _check_voice() -> None:
    _section("voice")
    _line("wake word / STT / TTS", "NOT IMPLEMENTED YET")
    print(
        '\n  "hey celebi" does nothing in deskbot -- voice was never built here.\n'
        "  It exists as a prototype in the separate celebi repo; porting it in is\n"
        "  the remaining roadmap item."
    )


def run(cfg) -> int:
    print("deskbot doctor")
    print("==============")
    wayland = _check_session(cfg)
    _check_cursor(wayland)
    _check_active_window()
    _check_ollama(cfg)
    _check_actions(cfg)
    _check_voice()
    print("\ndone -- paste this whole output if you're asking for help.\n")
    return 0
