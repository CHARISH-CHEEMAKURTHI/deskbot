"""Entry point: python -m deskbot"""

from __future__ import annotations

import os
import signal
import sys

from PyQt6.QtCore import QTimer
from PyQt6.QtWidgets import QApplication

from .activity import ActivityWatcher
from .config import Config
from .expressions import VectorRenderer
from .pet import PetWindow


def _ensure_xwayland_backend() -> None:
    """Cursor polling and window positioning are unreliable on native
    Wayland (QCursor.pos() goes stale and windows can't reposition
    themselves), which breaks cursor-following, always-on-top, and
    dragging alike. XWayland (Qt's "xcb" platform plugin) fixes all three,
    so default to it on a Wayland session unless the user picked a
    platform themselves.
    """
    if os.environ.get("QT_QPA_PLATFORM"):
        return
    if os.environ.get("WAYLAND_DISPLAY") or os.environ.get("XDG_SESSION_TYPE") == "wayland":
        os.environ["QT_QPA_PLATFORM"] = "xcb"
        print(
            "[deskbot] Wayland session detected -- running under XWayland "
            "(QT_QPA_PLATFORM=xcb) so cursor-following, always-on-top, and "
            "dragging all work. Export QT_QPA_PLATFORM=wayland yourself to "
            "opt back into native Wayland."
        )


def main() -> int:
    _ensure_xwayland_backend()
    cfg = Config.load()

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

    # let Ctrl+C in the terminal kill it
    signal.signal(signal.SIGINT, signal.SIG_DFL)
    heartbeat = QTimer()
    heartbeat.start(300)
    heartbeat.timeout.connect(lambda: None)

    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
