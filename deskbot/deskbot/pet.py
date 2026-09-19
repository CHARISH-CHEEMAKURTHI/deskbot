"""The always-on-top, transparent window the bot lives in.

It's a small frameless window that repositions itself every frame, rather
than a fullscreen overlay -- that keeps clicks on the rest of your desktop
working normally, and the bot stays draggable.
"""

from __future__ import annotations

import math
import random
import threading
import time

from PyQt6.QtCore import QObject, QPoint, QPointF, QRectF, Qt, QThread, QTimer, pyqtSignal
from PyQt6.QtGui import (
    QAction,
    QColor,
    QCursor,
    QFont,
    QGuiApplication,
    QPainter,
    QPainterPath,
    QPen,
)
from PyQt6.QtWidgets import QApplication, QInputDialog, QMenu, QMessageBox, QWidget

from .behavior import Brain, Mode
from .commands import CommandResult
from .expressions import Expression


class _ClassifyWorker(QThread):
    """Runs Phase 3's intent classification off the GUI thread -- the
    Ollama call is a blocking network request, and this keeps the bot
    animating while it waits. Deliberately classification-only: anything
    that actually *acts* (including whether to ask for confirmation first)
    happens back on the GUI thread in PetWindow._on_classified, since a
    confirmation dialog has to run there."""

    classified = pyqtSignal(object, object)  # (Intent | None, Exception | None)

    def __init__(self, cfg, text: str, parent=None):
        super().__init__(parent)
        self.cfg = cfg
        self.text = text

    def run(self) -> None:
        from . import intent as intent_mod

        try:
            parsed = intent_mod.classify(self.cfg, self.text)
            self.classified.emit(parsed, None)
        except Exception as exc:
            self.classified.emit(None, exc)


class _AgentBridge(QObject):
    """Thread-safe hand-off from any off-GUI-thread channel (whatsapp.py's
    webhook server, voice.py's wake-word listener) into the GUI thread --
    for anything that needs Qt: a confirmation dialog, or the desktop
    bot's own mood/speech.

    Qt signals are safe to emit from any thread; the connected slot still
    runs on whichever thread owns this object, which is the GUI thread
    since PetWindow creates it with itself as parent."""

    _run_action_signal = pyqtSignal(object, str, dict)
    _say_signal = pyqtSignal(str)

    def __init__(self, pet_window: "PetWindow"):
        super().__init__(pet_window)
        self.pet_window = pet_window
        self._run_action_signal.connect(self._on_run_action)
        self._say_signal.connect(self._on_say)

    def run_action_blocking(self, parsed, via: str = "chat", timeout: float = 120.0) -> str:
        """Call from a non-GUI thread. Blocks until the GUI thread has
        confirmed (if needed) and executed the action; returns the
        resulting message to speak/send back."""
        box: dict = {"event": threading.Event(), "result": "took too long, try again"}
        self._run_action_signal.emit(parsed, via, box)
        box["event"].wait(timeout=timeout)
        return box["result"]

    def say_async(self, text: str) -> None:
        """Fire-and-forget: makes the desktop bot itself react/speak."""
        self._say_signal.emit(text)

    def _on_run_action(self, parsed, via: str, box: dict) -> None:
        from . import intent as intent_mod

        pw = self.pet_window
        if intent_mod.needs_confirmation(parsed):
            question = intent_mod.confirmation_text(pw.cfg, parsed) + f"\n\n(requested via {via})"
            choice = QMessageBox.question(
                pw,
                "deskbot: confirm",
                question,
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No,
            )
            if choice != QMessageBox.StandardButton.Yes:
                pw._on_command_result(CommandResult("okay, not doing that.", ok=True))
                box["result"] = "okay, not doing that."
                box["event"].set()
                return

        try:
            result = intent_mod.run(pw.cfg, parsed)
        except Exception as exc:
            result = CommandResult(f"something went wrong: {exc}", ok=False)
        pw._on_command_result(result)
        box["result"] = result.message
        box["event"].set()

    def _on_say(self, text: str) -> None:
        self.pet_window.brain.set_mood(Expression.HAPPY, 4.0, say=text)


class PetWindow(QWidget):
    def __init__(self, cfg, renderer):
        super().__init__()
        self.cfg = cfg
        self.renderer = renderer
        self.brain = Brain(cfg)

        flags = Qt.WindowType.FramelessWindowHint | Qt.WindowType.Tool
        if cfg.always_on_top:
            flags |= Qt.WindowType.WindowStaysOnTopHint
        if cfg.bypass_wm:
            flags |= Qt.WindowType.X11BypassWindowManagerHint
        self.setWindowFlags(flags)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating, True)
        self.setWindowTitle("deskbot")
        self.resize(cfg.window_w, cfg.window_h)

        screen = QGuiApplication.primaryScreen().availableGeometry()
        self.bounds = screen
        self.pos_f = [screen.center().x(), screen.center().y() + 150]
        self.vel = [0.0, 0.0]
        self.facing = 1

        self.t0 = time.monotonic()
        self.last_tick = self.t0
        self.next_blink = self.t0 + cfg.blink_interval
        self.blink_phase = 1.0
        self.expression = Expression.NEUTRAL
        self.walking = False
        self.speech: str | None = None

        self._dragging = False
        self._drag_offset = QPoint()
        self._intent_worker: _ClassifyWorker | None = None
        self.agent_bridge = _AgentBridge(self)
        self.voice_listener = None  # set by main.py once voice.start() has run

        self.timer = QTimer(self)
        self.timer.timeout.connect(self.tick)
        self.timer.start(max(8, int(1000 / cfg.fps)))
        self._sync_window()

    # -- geometry helpers ----------------------------------------------
    @property
    def anchor(self) -> QPoint:
        """Point inside the window where the bot's feet sit."""
        return QPoint(self.width() // 2, self.height() - 18)

    def _sync_window(self) -> None:
        self.move(int(self.pos_f[0]) - self.anchor.x(),
                  int(self.pos_f[1]) - self.anchor.y())

    # -- main loop -------------------------------------------------------
    def tick(self) -> None:
        now = time.monotonic()
        dt = min(0.1, now - self.last_tick)
        self.last_tick = now
        if dt <= 0:
            return

        # A mouse-release can go missing (a lost grab, a click that ends over
        # another window), which would otherwise leave the bot pinned in
        # DRAGGED mode forever, never moving again.
        if self._dragging and QApplication.mouseButtons() == Qt.MouseButton.NoButton:
            self._dragging = False
            self.brain.mode = Mode.REST

        cursor = QCursor.pos()
        decision = self.brain.update(
            dt, (cursor.x(), cursor.y()), tuple(self.pos_f), self.bounds
        )
        self.expression = decision.expression
        self.speech = decision.speech

        if not self._dragging:
            self._move_towards(decision.target, dt)
            self.walking = decision.walking and abs(self.vel[0]) + abs(self.vel[1]) > 12
        else:
            self.walking = False

        if now > self.next_blink:
            self.blink_phase = 0.0
            self.next_blink = now + random.uniform(
                self.cfg.blink_interval * 0.5, self.cfg.blink_interval * 1.8
            )
        self.blink_phase = min(1.0, self.blink_phase + dt * 6.0)

        self._sync_window()
        self.update()

    def _move_towards(self, target, dt: float) -> None:
        tx, ty = target
        dx, dy = tx - self.pos_f[0], ty - self.pos_f[1]
        dist = math.hypot(dx, dy)

        if dist < self.cfg.stop_distance * 0.3:
            self.vel[0] *= 0.80
            self.vel[1] *= 0.80
        else:
            # ease in proportionally, capped -- gives a nice trot
            speed = min(self.cfg.max_speed, dist * self.cfg.follow_speed)
            self.vel[0] += ((dx / dist) * speed - self.vel[0]) * min(1.0, dt * 6.0)
            self.vel[1] += ((dy / dist) * speed - self.vel[1]) * min(1.0, dt * 6.0)

        self.pos_f[0] += self.vel[0] * dt
        self.pos_f[1] += self.vel[1] * dt

        self.pos_f[0] = min(max(self.pos_f[0], self.bounds.left() + 40),
                            self.bounds.right() - 40)
        self.pos_f[1] = min(max(self.pos_f[1], self.bounds.top() + 90),
                            self.bounds.bottom() - 20)

        if abs(self.vel[0]) > 25:
            self.facing = 1 if self.vel[0] > 0 else -1

    # -- painting ---------------------------------------------------------
    def paintEvent(self, event) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        size = self.cfg.bot_size
        box = QRectF((self.width() - size) / 2, self.height() - size - 6, size, size)

        if self.speech:
            self._paint_bubble(p, self.speech, box)

        self.renderer.draw(
            p, box, self.expression, time.monotonic() - self.t0,
            self.walking, self.facing, self.blink_phase,
        )

    def _paint_bubble(self, p: QPainter, text: str, box: QRectF) -> None:
        font = QFont()
        font.setPointSize(9)
        font.setBold(True)
        p.setFont(font)
        metrics = p.fontMetrics()
        tw = min(metrics.horizontalAdvance(text) + 22, self.width() - 12)
        th = metrics.height() + 14

        rect = QRectF(0, 0, tw, th)
        rect.moveCenter(QPointF(self.width() / 2, box.top() - th / 2 + 4))
        if rect.top() < 2:
            rect.moveTop(2)

        path = QPainterPath()
        path.addRoundedRect(rect, 10, 10)
        tail_x = rect.center().x()
        path.moveTo(tail_x - 7, rect.bottom() - 1)
        path.lineTo(tail_x + 1, rect.bottom() + 9)
        path.lineTo(tail_x + 8, rect.bottom() - 1)
        path.closeSubpath()

        p.setPen(QPen(QColor(0, 0, 0, 60), 1))
        p.setBrush(QColor(250, 250, 252, 235))
        p.drawPath(path)
        p.setPen(QColor("#20242a"))
        p.drawText(rect, int(Qt.AlignmentFlag.AlignCenter), text)

    # -- interaction -------------------------------------------------------
    def mousePressEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self._dragging = True
            self.brain.mode = Mode.DRAGGED
            self._drag_offset = event.globalPosition().toPoint() - self.frameGeometry().topLeft()
            self.brain.set_mood(Expression.SURPRISED, 1.2, say="whoa!")
        elif event.button() == Qt.MouseButton.RightButton:
            self._show_menu(event.globalPosition().toPoint())

    def mouseMoveEvent(self, event) -> None:
        if self._dragging:
            top_left = event.globalPosition().toPoint() - self._drag_offset
            self.move(top_left)
            self.pos_f = [top_left.x() + self.anchor.x(), top_left.y() + self.anchor.y()]
            self.vel = [0.0, 0.0]

    def mouseReleaseEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.LeftButton and self._dragging:
            self._dragging = False
            self.brain.mode = Mode.REST
            self.brain.set_mood(Expression.HAPPY, 1.5)

    def mouseDoubleClickEvent(self, event) -> None:
        self.brain.set_mood(Expression.LAUGHING, 2.5, say="hehehe")

    def _show_menu(self, at: QPoint) -> None:
        menu = QMenu(self)

        follow = QAction("Follow cursor", menu, checkable=True)
        follow.setChecked(self.cfg.follow_cursor)
        follow.toggled.connect(self._toggle_follow)
        menu.addAction(follow)

        chatty = QAction("Chatty", menu, checkable=True)
        chatty.setChecked(self.cfg.chatty)
        chatty.toggled.connect(lambda v: setattr(self.cfg, "chatty", v))
        menu.addAction(chatty)

        activity_aware = QAction("Notice what I'm doing", menu, checkable=True)
        activity_aware.setChecked(self.cfg.activity_aware)
        activity_aware.toggled.connect(lambda v: setattr(self.cfg, "activity_aware", v))
        menu.addAction(activity_aware)

        listening = QAction('Listen for "hey celebi"', menu, checkable=True)
        listening.setChecked(getattr(self.cfg, "voice_enabled", False))
        listening.toggled.connect(self._toggle_voice)
        menu.addAction(listening)

        moods = menu.addMenu("Mood")
        for expr in Expression:
            act = QAction(expr.label, moods)
            act.triggered.connect(
                lambda _checked=False, e=expr: self.brain.set_mood(e, 6.0)
            )
            moods.addAction(act)

        menu.addSeparator()
        ask = QAction("Ask deskbot…", menu)
        ask.triggered.connect(self._ask_dialog)
        menu.addAction(ask)

        menu.addSeparator()
        save = QAction("Save settings", menu)
        save.triggered.connect(self.cfg.save)
        menu.addAction(save)

        quit_act = QAction("Quit", menu)
        quit_act.triggered.connect(QApplication.instance().quit)
        menu.addAction(quit_act)

        menu.exec(at)

    def _toggle_follow(self, value: bool) -> None:
        self.cfg.follow_cursor = value
        self.brain.say("following you" if value else "doing my own thing")

    def _toggle_voice(self, value: bool) -> None:
        """Mutes/unmutes wake-word detection live. The listener thread reads
        cfg.voice_enabled every loop, so this takes effect immediately -- but
        only if the thread started at launch, which needs voice_enabled true
        in the config plus the voice extras installed."""
        self.cfg.voice_enabled = value
        if not value:
            self.brain.say("not listening")
            return
        from . import voice

        if self.voice_listener is None or not self.voice_listener.is_alive():
            self.voice_listener = voice.start(self.cfg, self.agent_bridge)
        self.brain.say(
            'listening for "hey celebi"'
            if self.voice_listener is not None
            else "voice extras aren't installed"
        )

    def _ask_dialog(self) -> None:
        text, ok = QInputDialog.getText(self, "Ask deskbot", "What do you need?")
        if not ok or not text.strip():
            return
        self.brain.set_mood(Expression.THINKING, 30.0, say="on it...")
        worker = _ClassifyWorker(self.cfg, text.strip(), self)
        worker.classified.connect(self._on_classified)
        worker.finished.connect(worker.deleteLater)
        self._intent_worker = worker  # keep a reference so it isn't GC'd mid-flight
        worker.start()

    def _on_classified(self, parsed, error: Exception | None) -> None:
        from . import intent as intent_mod

        if error is not None:
            self._on_command_result(CommandResult(f"something went wrong: {error}", ok=False))
            return
        if parsed is None:
            self._on_command_result(CommandResult("didn't understand that.", ok=False))
            return

        if intent_mod.needs_confirmation(parsed):
            question = intent_mod.confirmation_text(self.cfg, parsed)
            choice = QMessageBox.question(
                self,
                "deskbot: confirm",
                question,
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No,
            )
            if choice != QMessageBox.StandardButton.Yes:
                self._on_command_result(CommandResult("okay, not doing that.", ok=True))
                return

        try:
            result = intent_mod.run(self.cfg, parsed)
        except Exception as exc:
            result = CommandResult(f"something went wrong: {exc}", ok=False)
        self._on_command_result(result)

    def _on_command_result(self, result: CommandResult) -> None:
        expr = Expression.HAPPY if result.ok else Expression.SAD
        self.brain.set_mood(expr, 4.0, say=result.message)
