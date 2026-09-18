"""Entry point: python -m deskbot"""

from __future__ import annotations

import signal
import sys

from PyQt6.QtCore import QTimer
from PyQt6.QtWidgets import QApplication

from .config import Config
from .expressions import VectorRenderer
from .pet import PetWindow


def main() -> int:
    cfg = Config.load()

    app = QApplication(sys.argv)
    app.setApplicationName("deskbot")
    app.setQuitOnLastWindowClosed(True)

    renderer = VectorRenderer(cfg)   # swap for SpriteRenderer once art exists
    pet = PetWindow(cfg, renderer)
    pet.show()

    # let Ctrl+C in the terminal kill it
    signal.signal(signal.SIGINT, signal.SIG_DFL)
    heartbeat = QTimer()
    heartbeat.start(300)
    heartbeat.timeout.connect(lambda: None)

    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
