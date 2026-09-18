"""Every face the bot can pull, drawn procedurally with QPainter.

No image assets needed to run. When you draw real sprite sheets later,
implement SpriteRenderer with the same draw() signature and swap it in
main.py -- nothing else has to change.
"""

from __future__ import annotations

import math
import random
from enum import Enum

from PyQt6.QtCore import QPointF, QRectF, Qt
from PyQt6.QtGui import (
    QBrush,
    QColor,
    QFont,
    QLinearGradient,
    QPainter,
    QPainterPath,
    QPen,
    QPolygonF,
)


class Expression(Enum):
    NEUTRAL = "neutral"
    HAPPY = "happy"
    LAUGHING = "laughing"
    THINKING = "thinking"
    SAD = "sad"
    CRYING = "crying"
    ANGRY = "angry"
    CHEERING = "cheering"
    SURPRISED = "surprised"
    SLEEPING = "sleeping"
    LOVE = "love"

    @property
    def label(self) -> str:
        return self.value.capitalize()


class VectorRenderer:
    """Draws the bot as vector art. Stateless apart from colours."""

    def __init__(self, cfg):
        self.cfg = cfg
        self.body_light = QColor(cfg.body_light)
        self.body_dark = QColor(cfg.body_dark)
        self.accent = QColor(cfg.accent)
        self.visor = QColor(cfg.visor)
        self.glow = QColor(cfg.glow)

    # -- public ---------------------------------------------------------
    def draw(
        self,
        p: QPainter,
        box: QRectF,
        expr: Expression,
        t: float,
        walking: bool,
        facing: int,
        blink: float,
    ) -> None:
        """box is the square the bot occupies; t is elapsed seconds."""
        p.save()
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)

        bob = math.sin(t * (7.0 if walking else 2.2)) * (3.0 if walking else 1.6)
        if expr is Expression.LAUGHING:
            bob += math.sin(t * 18) * 2.5
        if expr is Expression.ANGRY:
            bob += math.sin(t * 26) * 1.5
        if expr is Expression.SLEEPING:
            bob = math.sin(t * 1.1) * 2.0

        self._shadow(p, box, walking, t)

        p.translate(0, bob)
        # Mirror so the bot faces its direction of travel.
        if facing < 0:
            p.translate(box.center().x() * 2, 0)
            p.scale(-1, 1)

        self._legs(p, box, walking, t, expr)
        self._body(p, box, expr, t)
        self._antenna(p, box, expr, t)
        self._face(p, box, expr, t, blink)
        self._arms(p, box, expr, t, walking)
        self._effects(p, box, expr, t)
        p.restore()

    # -- pieces ---------------------------------------------------------
    def _shadow(self, p: QPainter, box: QRectF, walking: bool, t: float) -> None:
        squash = 1.0 + (math.sin(t * 7.0) * 0.08 if walking else 0.0)
        w = box.width() * 0.52 * squash
        rect = QRectF(0, 0, w, box.height() * 0.09)
        rect.moveCenter(QPointF(box.center().x(), box.bottom() - 2))
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(0, 0, 0, 70))
        p.drawEllipse(rect)

    def _legs(self, p: QPainter, box: QRectF, walking: bool, t: float, expr) -> None:
        s = box.width()
        swing = math.sin(t * 9.0) * (s * 0.07) if walking else 0.0
        if expr is Expression.CHEERING:
            swing = abs(math.sin(t * 6.0)) * s * 0.05
        leg_w, leg_h = s * 0.11, s * 0.16
        base_y = box.bottom() - leg_h - 4
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(self.body_dark)
        for sign in (-1, 1):
            x = box.center().x() + sign * s * 0.15 - leg_w / 2 + sign * swing
            p.drawRoundedRect(QRectF(x, base_y, leg_w, leg_h), leg_w / 2, leg_w / 2)

    def _body(self, p: QPainter, box: QRectF, expr: Expression, t: float) -> None:
        s = box.width()
        body = QRectF(
            box.left() + s * 0.14,
            box.top() + s * 0.20,
            s * 0.72,
            s * 0.62,
        )
        grad = QLinearGradient(body.topLeft(), body.bottomRight())
        grad.setColorAt(0.0, self.body_light.lighter(115))
        grad.setColorAt(1.0, self.body_dark)
        p.setBrush(QBrush(grad))
        p.setPen(QPen(QColor(0, 0, 0, 120), 1.5))
        p.drawRoundedRect(body, s * 0.22, s * 0.22)

        # accent belly light, pulses gently
        pulse = 0.55 + 0.45 * (math.sin(t * 2.4) * 0.5 + 0.5)
        if expr is Expression.SLEEPING:
            pulse = 0.25 + 0.2 * (math.sin(t * 1.1) * 0.5 + 0.5)
        col = QColor(self.accent)
        col.setAlphaF(min(1.0, pulse))
        dot = QRectF(0, 0, s * 0.09, s * 0.09)
        dot.moveCenter(QPointF(body.center().x(), body.bottom() - s * 0.10))
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(col)
        p.drawEllipse(dot)

    def _antenna(self, p: QPainter, box: QRectF, expr: Expression, t: float) -> None:
        s = box.width()
        sway = math.sin(t * 3.0) * s * 0.03
        if expr in (Expression.LAUGHING, Expression.CHEERING):
            sway = math.sin(t * 12.0) * s * 0.05
        top = box.top() + s * 0.20
        start = QPointF(box.center().x(), top + s * 0.02)
        tip = QPointF(box.center().x() + sway, top - s * 0.16)
        path = QPainterPath(start)
        path.quadTo(QPointF(start.x(), top - s * 0.09), tip)
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.setPen(QPen(self.body_dark, s * 0.035, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
        p.drawPath(path)

        ball = QRectF(0, 0, s * 0.10, s * 0.10)
        ball.moveCenter(tip)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(self.accent if expr is not Expression.SLEEPING else self.body_light)
        p.drawEllipse(ball)

    def _face(self, p: QPainter, box: QRectF, expr: Expression, t: float, blink: float) -> None:
        s = box.width()
        visor = QRectF(box.left() + s * 0.20, box.top() + s * 0.28, s * 0.60, s * 0.34)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(self.visor)
        p.drawRoundedRect(visor, s * 0.15, s * 0.15)

        cx, cy = visor.center().x(), visor.center().y()
        eye_dx = s * 0.13
        left = QPointF(cx - eye_dx, cy - s * 0.01)
        right = QPointF(cx + eye_dx, cy - s * 0.01)
        pen = QPen(self.glow, s * 0.035, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap)
        p.setPen(pen)
        p.setBrush(self.glow)

        closed = blink < 0.12 and expr not in (
            Expression.SLEEPING,
            Expression.HAPPY,
            Expression.LAUGHING,
        )

        if expr is Expression.SLEEPING or closed:
            for c in (left, right):
                p.setBrush(Qt.BrushStyle.NoBrush)
                p.drawArc(QRectF(c.x() - s * 0.06, c.y() - s * 0.05, s * 0.12, s * 0.09),
                          200 * 16, 140 * 16)
        elif expr in (Expression.HAPPY, Expression.LAUGHING):
            p.setBrush(Qt.BrushStyle.NoBrush)
            for c in (left, right):
                p.drawArc(QRectF(c.x() - s * 0.06, c.y() - s * 0.03, s * 0.12, s * 0.10),
                          20 * 16, 140 * 16)
        elif expr is Expression.SURPRISED:
            for c in (left, right):
                p.setBrush(self.glow)
                p.drawEllipse(c, s * 0.055, s * 0.055)
        elif expr is Expression.ANGRY:
            for c, sign in ((left, -1), (right, 1)):
                p.setBrush(self.glow)
                p.drawEllipse(c, s * 0.045, s * 0.030)
            p.setPen(QPen(QColor("#ff5a4d"), s * 0.030, Qt.PenStyle.SolidLine,
                          Qt.PenCapStyle.RoundCap))
            p.drawLine(QPointF(left.x() - s * 0.06, cy - s * 0.09),
                       QPointF(left.x() + s * 0.04, cy - s * 0.045))
            p.drawLine(QPointF(right.x() + s * 0.06, cy - s * 0.09),
                       QPointF(right.x() - s * 0.04, cy - s * 0.045))
        elif expr in (Expression.SAD, Expression.CRYING):
            p.setBrush(self.glow)
            for c in (left, right):
                p.drawEllipse(c, s * 0.045, s * 0.048)
            p.setPen(QPen(QColor(self.glow).darker(160), s * 0.025,
                          Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
            p.drawLine(QPointF(left.x() - s * 0.06, cy - s * 0.075),
                       QPointF(left.x() + s * 0.03, cy - s * 0.095))
            p.drawLine(QPointF(right.x() + s * 0.06, cy - s * 0.075),
                       QPointF(right.x() - s * 0.03, cy - s * 0.095))
        elif expr is Expression.THINKING:
            look = QPointF(-s * 0.02, -s * 0.02)
            p.setBrush(self.glow)
            p.drawEllipse(left + look, s * 0.045, s * 0.045)
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.setPen(QPen(self.glow, s * 0.032, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
            p.drawLine(QPointF(right.x() - s * 0.05, cy), QPointF(right.x() + s * 0.05, cy))
        elif expr is Expression.LOVE:
            p.setBrush(QColor("#ff6f91"))
            p.setPen(Qt.PenStyle.NoPen)
            for c in (left, right):
                self._heart(p, c, s * 0.055)
        elif expr is Expression.CHEERING:
            p.setBrush(self.accent)
            p.setPen(Qt.PenStyle.NoPen)
            for c in (left, right):
                self._star(p, c, s * 0.055)
        else:  # NEUTRAL
            p.setBrush(self.glow)
            p.setPen(Qt.PenStyle.NoPen)
            for c in (left, right):
                p.drawEllipse(c, s * 0.042, s * 0.048)

        self._mouth(p, box, visor, expr, t)

    def _mouth(self, p: QPainter, box: QRectF, visor: QRectF, expr: Expression, t: float) -> None:
        s = box.width()
        cx = visor.center().x()
        my = visor.bottom() - s * 0.045
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.setPen(QPen(self.glow, s * 0.028, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))

        if expr is Expression.LAUGHING:
            h = s * 0.055 + math.sin(t * 16) * s * 0.012
            r = QRectF(cx - s * 0.075, my - h / 2, s * 0.15, h)
            p.setBrush(self.glow)
            p.setPen(Qt.PenStyle.NoPen)
            p.drawRoundedRect(r, s * 0.02, s * 0.02)
        elif expr in (Expression.HAPPY, Expression.CHEERING, Expression.LOVE):
            p.drawArc(QRectF(cx - s * 0.07, my - s * 0.05, s * 0.14, s * 0.07),
                      200 * 16, 140 * 16)
        elif expr in (Expression.SAD, Expression.CRYING):
            p.drawArc(QRectF(cx - s * 0.07, my - s * 0.01, s * 0.14, s * 0.07),
                      20 * 16, 140 * 16)
        elif expr is Expression.SURPRISED:
            p.setBrush(self.glow)
            p.setPen(Qt.PenStyle.NoPen)
            p.drawEllipse(QPointF(cx, my), s * 0.030, s * 0.036)
        elif expr is Expression.ANGRY:
            poly = QPolygonF([
                QPointF(cx - s * 0.07, my),
                QPointF(cx - s * 0.035, my - s * 0.03),
                QPointF(cx, my),
                QPointF(cx + s * 0.035, my - s * 0.03),
                QPointF(cx + s * 0.07, my),
            ])
            p.drawPolyline(poly)
        elif expr is Expression.SLEEPING:
            p.drawArc(QRectF(cx - s * 0.05, my - s * 0.03, s * 0.10, s * 0.05),
                      200 * 16, 140 * 16)
        elif expr is Expression.THINKING:
            p.drawLine(QPointF(cx - s * 0.05, my), QPointF(cx + s * 0.02, my - s * 0.012))
        else:
            p.drawLine(QPointF(cx - s * 0.045, my), QPointF(cx + s * 0.045, my))

    def _arms(self, p: QPainter, box: QRectF, expr: Expression, t: float, walking: bool) -> None:
        s = box.width()
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.setPen(QPen(self.body_dark, s * 0.055, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
        shoulder_y = box.top() + s * 0.46
        lx = box.left() + s * 0.16
        rx = box.right() - s * 0.16

        if expr is Expression.CHEERING:
            lift = abs(math.sin(t * 6.0)) * s * 0.12
            p.drawLine(QPointF(lx, shoulder_y),
                       QPointF(lx - s * 0.10, shoulder_y - s * 0.14 - lift))
            p.drawLine(QPointF(rx, shoulder_y),
                       QPointF(rx + s * 0.10, shoulder_y - s * 0.14 - lift))
        elif expr is Expression.THINKING:
            p.drawLine(QPointF(lx, shoulder_y), QPointF(lx - s * 0.07, shoulder_y + s * 0.10))
            p.drawLine(QPointF(rx, shoulder_y), QPointF(rx - s * 0.05, box.top() + s * 0.58))
        elif expr is Expression.CRYING:
            p.drawLine(QPointF(lx, shoulder_y), QPointF(lx + s * 0.03, box.top() + s * 0.38))
            p.drawLine(QPointF(rx, shoulder_y), QPointF(rx - s * 0.03, box.top() + s * 0.38))
        else:
            swing = math.sin(t * 9.0) * s * 0.06 if walking else math.sin(t * 2.0) * s * 0.015
            p.drawLine(QPointF(lx, shoulder_y),
                       QPointF(lx - s * 0.06, shoulder_y + s * 0.12 - swing))
            p.drawLine(QPointF(rx, shoulder_y),
                       QPointF(rx + s * 0.06, shoulder_y + s * 0.12 + swing))

    def _effects(self, p: QPainter, box: QRectF, expr: Expression, t: float) -> None:
        s = box.width()
        if expr is Expression.CRYING:
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QColor("#6fd0ff"))
            for i, sign in enumerate((-1, 1)):
                phase = (t * 1.6 + i * 0.5) % 1.0
                x = box.center().x() + sign * s * 0.13
                y = box.top() + s * 0.44 + phase * s * 0.30
                drop = QRectF(0, 0, s * 0.045, s * 0.062)
                drop.moveCenter(QPointF(x, y))
                p.setOpacity(1.0 - phase * 0.8)
                p.drawEllipse(drop)
            p.setOpacity(1.0)

        elif expr is Expression.THINKING:
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QColor(255, 255, 255, 210))
            base = QPointF(box.right() - s * 0.10, box.top() + s * 0.16)
            for i in range(3):
                on = (int(t * 2.0) % 3) >= i
                r = s * (0.020 + i * 0.008)
                p.setOpacity(0.95 if on else 0.25)
                p.drawEllipse(QPointF(base.x() + i * s * 0.075,
                                      base.y() - i * s * 0.055), r, r)
            p.setOpacity(1.0)

        elif expr is Expression.ANGRY:
            p.setPen(QPen(QColor("#ff5a4d"), s * 0.022, Qt.PenStyle.SolidLine,
                          Qt.PenCapStyle.RoundCap))
            c = QPointF(box.right() - s * 0.16, box.top() + s * 0.20)
            for a in range(4):
                ang = math.radians(a * 45 + math.sin(t * 12) * 10)
                p.drawLine(
                    QPointF(c.x() + math.cos(ang) * s * 0.03,
                            c.y() + math.sin(ang) * s * 0.03),
                    QPointF(c.x() + math.cos(ang) * s * 0.065,
                            c.y() + math.sin(ang) * s * 0.065),
                )

        elif expr is Expression.SLEEPING:
            p.setPen(QPen(QColor(255, 255, 255, 200)))
            f = QFont()
            for i in range(3):
                phase = (t * 0.55 + i * 0.33) % 1.0
                f.setPointSizeF(max(6.0, s * (0.09 + phase * 0.06)))
                p.setFont(f)
                p.setOpacity(max(0.0, 1.0 - phase))
                p.drawText(
                    QPointF(box.right() - s * 0.20 + phase * s * 0.18,
                            box.top() + s * 0.20 - phase * s * 0.20),
                    "z",
                )
            p.setOpacity(1.0)

        elif expr is Expression.LAUGHING:
            p.setPen(QPen(QColor(255, 255, 255, 180), s * 0.020,
                          Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
            for sign in (-1, 1):
                x = box.center().x() + sign * s * 0.34
                y = box.top() + s * 0.34 + math.sin(t * 10 + sign) * s * 0.02
                p.drawLine(QPointF(x, y), QPointF(x + sign * s * 0.05, y - s * 0.03))

    # -- tiny shapes ----------------------------------------------------
    def _heart(self, p: QPainter, c: QPointF, r: float) -> None:
        path = QPainterPath()
        path.moveTo(c.x(), c.y() + r * 0.9)
        path.cubicTo(c.x() - r * 1.6, c.y() - r * 0.2,
                     c.x() - r * 0.5, c.y() - r * 1.3, c.x(), c.y() - r * 0.35)
        path.cubicTo(c.x() + r * 0.5, c.y() - r * 1.3,
                     c.x() + r * 1.6, c.y() - r * 0.2, c.x(), c.y() + r * 0.9)
        p.drawPath(path)

    def _star(self, p: QPainter, c: QPointF, r: float) -> None:
        pts = []
        for i in range(10):
            rad = r if i % 2 == 0 else r * 0.45
            ang = math.radians(-90 + i * 36)
            pts.append(QPointF(c.x() + math.cos(ang) * rad, c.y() + math.sin(ang) * rad))
        p.drawPolygon(QPolygonF(pts))


class SpriteRenderer:
    """Placeholder for when you have real sprite sheets.

    Expected layout: assets/<expression>/<frame>.png, all the same size.
    Implement draw() with the same signature as VectorRenderer.draw and
    pass an instance to PetWindow -- nothing else in the app changes.
    """

    def __init__(self, cfg, asset_dir):
        raise NotImplementedError("Sprite mode comes in phase 1.5")
