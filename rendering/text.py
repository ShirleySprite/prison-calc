# -*- coding: utf-8 -*-
"""Draw pixel text and compose result/status text layers."""

from PySide6.QtCore import Qt
from PySide6.QtGui import QBrush, QColor, QGradient, QImage, QLinearGradient, QPainter

from pixel_font import ADVANCE, GLYPH_H, GLYPH_W, GLYPHS, text_width
from .background import C_VOID
from .layout import (
    ART_TO_VIEW, RESULT_ART_RECT, RESULT_CENTER_Y_OFFSET,
)

RAINBOW_STOPS = (
    (0.00, "#4dff7a"),
    (0.25, "#3a8cff"),
    (0.50, "#b966ff"),
    (0.75, "#3a8cff"),
    (1.00, "#4dff7a"),
)
ERROR_RAINBOW_STOPS = (
    (0.00, "#ff3b4f"),  # red
    (0.20, "#ff6fae"),  # pink
    (0.40, "#c04a9b"),  # reddish purple
    (0.60, "#ff8c42"),  # orange
    (0.80, "#ffd84d"),  # yellow
    (0.90, "#ff8c42"),  # return through orange
    (1.00, "#ff3b4f"),  # seamless cycle
)
ERROR_RESULT_TEXT = "666666"
RESULT_MAX_FONT_SCALE = 6.5
RESULT_WIDTH_MARGIN_ART = 28
RESULT_HEIGHT_MARGIN_ART = 12
RAINBOW_SECONDS_PER_DIGIT = 1.0


def draw_text_at(painter, text, x, y, cell_x, cell_y, font_scale=1,
                 color=None, brush=None):
    """Draw bitmap glyphs onto an integer-aligned pixel grid without filtering."""
    text = str(text).upper()
    if not text:
        return 0, 0

    painter.setPen(Qt.NoPen)
    for row in range(GLYPH_H):
        painter.setBrush(brush if brush is not None else color)
        top = y + round(row * font_scale * cell_y)
        bottom = y + round((row + 1) * font_scale * cell_y)
        for index, char in enumerate(text):
            glyph = GLYPHS.get(char, GLYPHS["?"])
            for col in range(GLYPH_W):
                if glyph[row][col] != "#":
                    continue
                left = x + round((index * ADVANCE + col) * font_scale * cell_x)
                right = x + round(
                    (index * ADVANCE + col + 1) * font_scale * cell_x)
                if right > left and bottom > top:
                    painter.drawRect(left, top, right - left, bottom - top)
    return (max(1, round(text_width(text, font_scale) * cell_x)),
            max(1, round(GLYPH_H * font_scale * cell_y)))


def draw_centered_text(painter, text, center_x, center_y, cell_x, cell_y,
                       font_scale=1, color=None, brush=None):
    width = max(1, round(text_width(str(text), font_scale) * cell_x))
    height = max(1, round(GLYPH_H * font_scale * cell_y))
    x = round(center_x - width / 2)
    y = round(center_y - height / 2)
    draw_text_at(painter, text, x, y, cell_x, cell_y, font_scale,
                 color, brush)
    return x, y, width, height


def _rainbow_brush(left, right, phase=0.0, stops=RAINBOW_STOPS):
    period = max(1.0, right - left)
    shift = (float(phase) % 1.0) * period
    start = left + shift + 0.5
    gradient = QLinearGradient(start, 0, start + period, 0)
    gradient.setSpread(QGradient.Spread.RepeatSpread)
    for position, color in stops:
        gradient.setColorAt(position, QColor(color))
    return QBrush(gradient)


def _result_font_scale(text, width, height, cell_x, cell_y):
    available_width = width - round(
        RESULT_WIDTH_MARGIN_ART * width / RESULT_ART_RECT.width())
    available_height = height - round(
        RESULT_HEIGHT_MARGIN_ART * height / RESULT_ART_RECT.height())
    width_scale = available_width / max(1, text_width(text, 1) * cell_x)
    height_scale = available_height / max(1, GLYPH_H * cell_y)
    return max(1.0, min(RESULT_MAX_FONT_SCALE, width_scale, height_scale))


def paint_result_layer(state, width, height, scale, dpr):
    """Render the prominent result and its status text at the shared scale."""
    image = QImage(width, height, QImage.Format_ARGB32_Premultiplied)
    image.fill(C_VOID)
    painter = QPainter(image)
    painter.setPen(Qt.NoPen)

    cell_x = ART_TO_VIEW * scale * dpr
    cell_y = ART_TO_VIEW * scale * dpr
    center_x = width / 2
    center_y = height / 2 + RESULT_CENTER_Y_OFFSET * scale * dpr
    status = state["status"]

    if status in ("done", "error"):
        text = (
            str(state["result"])
            if status == "done" else ERROR_RESULT_TEXT)
        font_scale = _result_font_scale(
            text, width, height, cell_x, cell_y)
        number_w = max(1, round(text_width(text, font_scale) * cell_x))
        number_h = max(1, round(GLYPH_H * font_scale * cell_y))
        number_x = round(center_x - number_w / 2)
        number_y = round(center_y - number_h / 2)
        palette = (
            ERROR_RAINBOW_STOPS if status == "error" else RAINBOW_STOPS)
        rainbow = _rainbow_brush(
            number_x, number_x + number_w,
            state.get("rainbow_phase", 0.0), stops=palette)
        draw_text_at(painter, text, number_x, number_y, cell_x, cell_y,
                     font_scale=font_scale, brush=rainbow)
    # Idle/computing states remain transparent here; the heart/loading artwork
    # is rendered on an independent layer by Renderer.
    painter.end()
    return image
