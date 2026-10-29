# -*- coding: utf-8 -*-

from PySide6.QtCore import Qt, QRectF
from PySide6.QtGui import QColor, QPainter

from .drawing_utils import draw_art_rect
from .layout import (
    ART_H,
    ART_TO_VIEW,
    ART_W,
    CONTENT_SHIFT_ART_Y,
    BOX_GAP,
    BOX_H,
    BOX_W,
    DATE_GROUP_LEFT,
    ROW_Y,
    SEP_W,
    digit_box_rect,
)
from .text import draw_centered_text

DATE_BOX_RADIUS = 2.5
BOX_FACE = QColor(255, 250, 240, 128)  # Warm white, 50% opacity.
BOX_FOCUS = QColor(255, 255, 255, 180)  # Clearer active field.
C_DATE_TEXT = QColor("#11161b")
C_DATE_TEXT_FOCUS = QColor("#05090d")


def draw_date_cells(painter, state, scale):
    painter.save()
    painter.setRenderHint(QPainter.Antialiasing, True)
    painter.scale(ART_TO_VIEW * scale, ART_TO_VIEW * scale)
    painter.setPen(Qt.NoPen)

    for row in range(2):
        focused = (
            state.get("focus")
            if state.get("focus_active", True)
            and state.get("focus_row") == row else None)
        for index in range(8):
            rect = digit_box_rect(row, index)
            painter.setBrush(BOX_FOCUS if focused == index else BOX_FACE)
            painter.drawRoundedRect(
                QRectF(rect.x(), rect.y(), rect.width(), rect.height()),
                DATE_BOX_RADIUS, DATE_BOX_RADIUS)
    painter.restore()


def _draw_date_row(painter, digits, row, focused,
                   position_scale_x, position_scale_y, cell_x, cell_y):
    if isinstance(digits, (list, tuple)):
        cells = list(digits)
    else:
        cells = [char if char != " " else "" for char in str(digits or "")]
    cells = (cells + [""] * 8)[:8]
    x = DATE_GROUP_LEFT
    y = ROW_Y[row] + CONTENT_SHIFT_ART_Y

    for index in range(8):
        if index in (4, 6):
            dash_x = x - BOX_GAP + (SEP_W - 3) // 2
            draw_art_rect(
                painter, dash_x, y + BOX_H // 2, 3, 1,
                position_scale_x, position_scale_y, cell_x, cell_y,
                BOX_FACE)
            x += SEP_W - BOX_GAP

        is_focused = focused == index
        char = cells[index]
        center_x = (x + BOX_W / 2) * position_scale_x
        center_y = (y + BOX_H / 2) * position_scale_y
        if char:
            draw_centered_text(
                painter, char, center_x, center_y, cell_x, cell_y,
                color=C_DATE_TEXT_FOCUS if is_focused else C_DATE_TEXT)
        elif is_focused:
            draw_art_rect(
                painter, x + BOX_W // 2 - 1, y + BOX_H - 5, 2, 1,
                position_scale_x, position_scale_y,
                cell_x, cell_y, C_DATE_TEXT_FOCUS)
        x += BOX_W + BOX_GAP


def draw_date_text(painter, state, width, height, scale, dpr):
    position_scale_x = width / ART_W
    position_scale_y = height / ART_H
    cell_x = ART_TO_VIEW * scale * dpr
    cell_y = ART_TO_VIEW * scale * dpr

    _draw_date_row(
        painter, state["start"], 0,
        state.get("focus")
        if state.get("focus_active", True) and state.get("focus_row") == 0
        else None,
        position_scale_x, position_scale_y, cell_x, cell_y)
    _draw_date_row(
        painter, state["end"], 1,
        state.get("focus")
        if state.get("focus_active", True) and state.get("focus_row") == 1
        else None,
        position_scale_x, position_scale_y, cell_x, cell_y)
