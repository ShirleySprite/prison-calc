# -*- coding: utf-8 -*-

from PySide6.QtGui import QColor, QCursor, QImage, QPainter, QPixmap

from .drawing_utils import draw_centered_sprite
from .layout import (
    ART_H,
    ART_TO_VIEW,
    ART_W,
    LIFE_MARK_CENTER_X,
    LIFE_MARK_CENTER_Y,
)
STEEL_HIGHLIGHT = QColor("#ffffff")
STEEL_SILVER = QColor("#dfdfdf")
STEEL_SHADE = QColor("#b8b8b8")

PIN_ICON_W, PIN_ICON_H = 5, 7
PIN_CONE_PIXELS = (
    (3, 0, STEEL_HIGHLIGHT), (4, 0, STEEL_SILVER),
    (2, 1, STEEL_HIGHLIGHT), (3, 1, STEEL_SILVER),
    (4, 1, STEEL_SHADE),
    (2, 2, STEEL_SILVER),
    (3, 2, STEEL_HIGHLIGHT), (4, 2, STEEL_SHADE),
    (2, 3, STEEL_SILVER), (3, 3, STEEL_SHADE),
    (1, 4, STEEL_HIGHLIGHT), (2, 4, STEEL_SHADE),
    (1, 5, STEEL_SILVER),
    (0, 6, STEEL_SHADE),
)
PIN_CURSOR_CELL_SCALE = 3  # 15×21 px cursor.
PIN_DOT_SIZE = 5
PIN_DOT_PIXELS = (
    (2, 0, STEEL_HIGHLIGHT),
    (1, 1, STEEL_HIGHLIGHT), (2, 1, STEEL_SILVER),
    (3, 1, STEEL_SHADE),
    (0, 2, STEEL_SILVER), (1, 2, STEEL_SILVER),
    (2, 2, STEEL_SILVER), (3, 2, STEEL_SHADE),
    (4, 2, STEEL_SHADE),
    (1, 3, STEEL_SILVER), (2, 3, STEEL_SHADE),
    (3, 3, STEEL_SHADE),
    (2, 4, STEEL_SHADE),
)
PIN_INDICATOR_CENTER_Y = 10.0  # Shifted upward from the former top-right position.


def make_pin_cursor():
    """Build the 15×21 px cursor from the former top-right pin sprite."""
    width = PIN_ICON_W * PIN_CURSOR_CELL_SCALE
    height = PIN_ICON_H * PIN_CURSOR_CELL_SCALE
    image = QImage(width, height, QImage.Format_ARGB32_Premultiplied)
    image.fill(QColor(0, 0, 0, 0))
    painter = QPainter(image)
    draw_centered_sprite(
        painter, PIN_CONE_PIXELS, PIN_ICON_W, PIN_ICON_H,
        width / 2, height / 2,
        PIN_CURSOR_CELL_SCALE, PIN_CURSOR_CELL_SCALE)
    painter.end()
    pixmap = QPixmap.fromImage(image)
    return QCursor(pixmap, 0, height - PIN_CURSOR_CELL_SCALE)


def draw_pinned_indicator(painter, width, height, scale, dpr):
    """Draw the former pinned-state sparkle at the center of the top band."""
    cell = ART_TO_VIEW * scale * dpr
    center_y = PIN_INDICATOR_CENTER_Y * (height / ART_H)
    draw_centered_sprite(
        painter, PIN_DOT_PIXELS, PIN_DOT_SIZE, PIN_DOT_SIZE,
        width / 2, center_y, cell, cell)


LIFE_MARK_COLOR = QColor("#ffffff")
GLITCH_PURPLE = QColor(231, 91, 239)
GLITCH_CYAN = QColor(25, 244, 238)
GLITCH_OFFSET_CELL_FRACTION = 0.8

# Latin cross with a two-row beam to keep its horizontal stroke visually balanced.
DEATH_CROSS_BITMAP = (
    "...#...",
    "...#...",
    "...#...",
    "#######",
    "#######",
    "...#...",
    "...#...",
    "...#...",
    "...#...",
    "...#...",
    "...#...",
    "...#...",
)
DEATH_CROSS_W, DEATH_CROSS_H = len(DEATH_CROSS_BITMAP[0]), len(DEATH_CROSS_BITMAP)
DEATH_CROSS_PIXELS = tuple(
    (x, y, LIFE_MARK_COLOR) for y, row in enumerate(DEATH_CROSS_BITMAP)
    for x, bit in enumerate(row) if bit == "#"
)

# Slim, connected 11x11 four-point star with a solid center and no detached tips.
LIFE_STAR_BITMAP = (
    ".....#.....",
    ".....#.....",
    ".....#.....",
    "....###....",
    "...#####...",
    "###########",
    "...#####...",
    "....###....",
    ".....#.....",
    ".....#.....",
    ".....#.....",
)
LIFE_STAR_W, LIFE_STAR_H = len(LIFE_STAR_BITMAP[0]), len(LIFE_STAR_BITMAP)
LIFE_STAR_PIXELS = tuple(
    (x, y, LIFE_MARK_COLOR) for y, row in enumerate(LIFE_STAR_BITMAP)
    for x, bit in enumerate(row) if bit == "#"
)


def _tint_pixels(pixels, color):
    return tuple((x, y, color) for x, y, _ in pixels)


def _draw_glitch_sprite(painter, pixels, sprite_w, sprite_h,
                        center_x, center_y, cell_x, cell_y):
    """Layer purple-left, cyan-right offsets under the original white sprite."""
    offset_x = cell_x * GLITCH_OFFSET_CELL_FRACTION
    draw_centered_sprite(
        painter, _tint_pixels(pixels, GLITCH_PURPLE), sprite_w, sprite_h,
        center_x - offset_x, center_y, cell_x, cell_y)
    draw_centered_sprite(
        painter, _tint_pixels(pixels, GLITCH_CYAN), sprite_w, sprite_h,
        center_x + offset_x, center_y, cell_x, cell_y)
    draw_centered_sprite(
        painter, pixels, sprite_w, sprite_h,
        center_x, center_y, cell_x, cell_y)


def draw_life_symbols(painter, width, height, scale, dpr, offsets=None):
    """Draw the cross and star with subtle RGB offsets and optional spring offsets."""
    position_scale_x = width / ART_W
    position_scale_y = height / ART_H
    cell_x = ART_TO_VIEW * scale * dpr
    cell_y = ART_TO_VIEW * scale * dpr
    offsets = offsets or {}
    cross_x, cross_y = offsets.get("cross", (0.0, 0.0))
    star_x, star_y = offsets.get("star", (0.0, 0.0))

    _draw_glitch_sprite(
        painter, DEATH_CROSS_PIXELS, DEATH_CROSS_W, DEATH_CROSS_H,
        (LIFE_MARK_CENTER_X + cross_x) * position_scale_x,
        (LIFE_MARK_CENTER_Y[0] + cross_y) * position_scale_y,
        cell_x, cell_y)
    _draw_glitch_sprite(
        painter, LIFE_STAR_PIXELS, LIFE_STAR_W, LIFE_STAR_H,
        (LIFE_MARK_CENTER_X + star_x) * position_scale_x,
        (LIFE_MARK_CENTER_Y[1] + star_y) * position_scale_y,
        cell_x, cell_y)
