"""Entry point: python -m deskbot"""

from __future__ import annotations

import os
import signal
import sys

from PyQt6.QtCore import QTimer
from PyQt6.QtWidgets import QApplication

from . import whatsapp
from .activity import ActivityWatcher
from .config import Config
from .expressions import VectorRenderer
from .pet import PetWindow


def _ensure_xwayland_backend() -> bool:
    """Window positioning doesn't work at all on native Wayland (windows
    can't place themselves), so default to XWayland (Qt's "xcb" plugin) on
    a Wayland session unless the user picked a platform themselves. That
    fixes always-on-top and dragging.

    It does NOT fix cursor-following: XWayland only sees the pointer while
    it's over one of our own windows, and Wayland has no protocol for
    asking where the global pointer is. behavior.py detects the resulting
    frozen cursor and roams instead; --doctor explains it.

    Returns True if this is a Wayland session.
    """
    wayland = bool(os.environ.get("WAYLAND_DISPLAY")) or (
        os.environ.get("XDG_SESSION_TYPE") == "wayland"
    )
    if not wayland or os.environ.get("QT_QPA_PLATFORM"):
        return wayland

    os.environ["QT_QPA_PLATFORM"] = "xcb"
    print(
        "[deskbot] Wayland session detected -- running under XWayland "
        "(QT_QPA_PLATFORM=xcb) so always-on-top and dragging work. Note that "
        "cursor-following cannot work on Wayland; log in to an Xorg/X11 "
        "session for that. Run `python -m deskbot --doctor` for details."
    )
    return wayland


def main() -> int:
    wayland = _ensure_xwayland_backend()
    cfg = Config.load()
    cfg.wayland_session = wayland  # runtime-only; not persisted by cfg.save()

    if "--doctor" in sys.argv:
        from PyQt6.QtGui import QGuiApplication

        from .doctor import run as run_doctor

        # Held in a local, not discarded -- a collected QGuiApplication takes
        # the screen list and QCursor.pos() down with it.
        doctor_app = QGuiApplication(sys.argv)
        code = run_doctor(cfg)
        del doctor_app
        return code

    app = QApplication(sys.argv)
    app.setApplicationName("deskbot")
    app.setQuitOnLastWindowClosed(True)

    renderer = VectorRenderer(cfg)   # swap for SpriteRenderer once art exists
    pet = PetWindow(cfg, renderer)
    pet.show()

    watcher = ActivityWatcher(cfg)
    activity_timer = QTimer()
    activity_timer.setInterval(max(500, int(cfg.activity_poll_interval * 1000)))
    activity_timer.timeout.connect(lambda: watcher.poll(pet.brain))
    activity_timer.start()

    whatsapp_server = whatsapp.start(cfg, pet.whatsapp_bridge)
    if whatsapp_server is not None:
        app.aboutToQuit.connect(whatsapp_server.shutdown)

    # let Ctrl+C in the terminal kill it
    signal.signal(signal.SIGINT, signal.SIG_DFL)
    heartbeat = QTimer()
    heartbeat.start(300)
    heartbeat.timeout.connect(lambda: None)

    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
