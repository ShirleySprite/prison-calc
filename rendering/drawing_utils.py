# -*- coding: utf-8 -*-

from PySide6.QtCore import Qt


def draw_rect(painter, x, y, width, height, color):
    painter.setPen(Qt.NoPen)
    painter.setBrush(color)
    painter.drawRect(x, y, width, height)


def draw_art_rect(painter, x, y, width, height,
                  position_scale_x, position_scale_y, cell_x, cell_y, color):
    left = round(x * position_scale_x)
    top = round(y * position_scale_y)
    pixel_w = max(1, round(width * cell_x))
    pixel_h = max(1, round(height * cell_y))
    draw_rect(painter, left, top, pixel_w, pixel_h, color)


def draw_centered_sprite(painter, pixels, sprite_w, sprite_h,
                         center_x, center_y, cell_x, cell_y):
    pixel_w = max(1, round(sprite_w * cell_x))
    pixel_h = max(1, round(sprite_h * cell_y))
    left = round(center_x - pixel_w / 2)
    top = round(center_y - pixel_h / 2)
    painter.setPen(Qt.NoPen)
    for col, row, color in pixels:
        x0 = left + round(col * cell_x)
        x1 = left + round((col + 1) * cell_x)
        y0 = top + round(row * cell_y)
        y1 = top + round((row + 1) * cell_y)
        if x1 > x0 and y1 > y0:
            draw_rect(painter, x0, y0, x1 - x0, y1 - y0, color)


_FIXED_ROUNDED_OFFSETS = {
    2: (1, 0),
    3: (2, 1, 0),
    4: (3, 2, 1, 0),
    5: (4, 3, 2, 1, 0),
}


def _rounded_offsets(radius):
    offsets = _FIXED_ROUNDED_OFFSETS.get(radius)
    if offsets is not None:
        return offsets
    return tuple(range(radius - 1, -1, -1))


def fill_pixel_rounded_rect(painter, x, y, width, height, color, radius=3):
    offsets = _rounded_offsets(radius)
    painter.setPen(Qt.NoPen)
    painter.setBrush(color)
    for row, inset in enumerate(offsets):
        painter.drawRect(x + inset, y + row, width - 2 * inset, 1)
        painter.drawRect(x + inset, y + height - 1 - row,
                         width - 2 * inset, 1)
    painter.drawRect(x, y + radius, width, height - 2 * radius)
