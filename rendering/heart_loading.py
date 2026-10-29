# -*- coding: utf-8 -*-
"""Hard-coded solid 11x9 heart in the accepted idle palette."""

from PySide6.QtCore import QRectF
from PySide6.QtGui import QColor

HEART_MAX_OPACITY = 0.70
RESULT_CROSSFADE_SECONDS = 0.5
HEART_GRID_WIDTH = 11
HEART_GRID_HEIGHT = 9
HEART_CELL_SIZE = 19.0 * 0.75 * 0.70
HEART_DISPLAY_WIDTH = HEART_GRID_WIDTH * HEART_CELL_SIZE
HEART_DISPLAY_HEIGHT = HEART_GRID_HEIGHT * HEART_CELL_SIZE

# Match the three source pinks by brightness: dark outline, middle shade,
# then light body. The same palette is used at rest and during motion.
HEART_IDLE_RGB_BY_SOURCE = {
    (254, 37, 122): (201, 181, 156),
    (251, 126, 185): (217, 207, 199),
    (254, 157, 203): (239, 233, 227),
}
HEART_HIGHLIGHT_SOURCE_RGB = (254, 230, 244)
HEART_HIGHLIGHT_RGB = (255, 255, 255)

# Exact opaque pixels from heart-export.png. Coordinates are zero-based (x, y);
# the other 34 cells in the 11x9 grid are fully transparent.
# Each tuple is (x, y, red, green, blue).
HEART_PIXEL_RGB = (
    # y = 0
    (2, 0, 254, 37, 122), (3, 0, 254, 37, 122),
    (7, 0, 254, 37, 122), (8, 0, 254, 37, 122),
    # y = 1
    (1, 1, 254, 37, 122), (2, 1, 254, 157, 203),
    (3, 1, 254, 157, 203), (4, 1, 254, 37, 122),
    (6, 1, 254, 37, 122), (7, 1, 254, 157, 203),
    (8, 1, 254, 157, 203), (9, 1, 254, 37, 122),
    # y = 2
    (0, 2, 254, 37, 122), (1, 2, 254, 157, 203),
    (2, 2, 254, 157, 203), (3, 2, 254, 230, 244),
    (4, 2, 254, 157, 203), (5, 2, 254, 37, 122),
    (6, 2, 254, 157, 203), (7, 2, 254, 157, 203),
    (8, 2, 254, 157, 203), (9, 2, 254, 157, 203),
    (10, 2, 254, 37, 122),
    # y = 3
    (0, 3, 254, 37, 122), (1, 3, 254, 157, 203),
    (2, 3, 254, 230, 244), (3, 3, 254, 157, 203),
    (4, 3, 254, 157, 203), (5, 3, 254, 157, 203),
    (6, 3, 254, 157, 203), (7, 3, 254, 157, 203),
    (8, 3, 254, 157, 203), (9, 3, 251, 126, 185),
    (10, 3, 254, 37, 122),
    # y = 4
    (0, 4, 254, 37, 122), (1, 4, 254, 157, 203),
    (2, 4, 254, 157, 203), (3, 4, 254, 157, 203),
    (4, 4, 254, 157, 203), (5, 4, 254, 157, 203),
    (6, 4, 254, 157, 203), (7, 4, 254, 157, 203),
    (8, 4, 254, 157, 203), (9, 4, 251, 126, 185),
    (10, 4, 254, 37, 122),
    # y = 5
    (1, 5, 254, 37, 122), (2, 5, 254, 157, 203),
    (3, 5, 254, 157, 203), (4, 5, 254, 157, 203),
    (5, 5, 254, 157, 203), (6, 5, 254, 157, 203),
    (7, 5, 251, 126, 185), (8, 5, 251, 126, 185),
    (9, 5, 254, 37, 122),
    # y = 6
    (2, 6, 254, 37, 122), (3, 6, 254, 37, 122),
    (4, 6, 254, 157, 203), (5, 6, 254, 157, 203),
    (6, 6, 251, 126, 185), (7, 6, 254, 37, 122),
    (8, 6, 254, 37, 122),
    # y = 7
    (4, 7, 254, 37, 122), (5, 7, 251, 126, 185),
    (6, 7, 254, 37, 122),
    # y = 8
    (5, 8, 254, 37, 122),
)

def _pixel_rgb(pixel):
    source_rgb = tuple(pixel[2:])
    if source_rgb == HEART_HIGHLIGHT_SOURCE_RGB:
        return HEART_HIGHLIGHT_RGB
    return HEART_IDLE_RGB_BY_SOURCE[source_rgb]


def _draw_pixel(painter, pixel, left, top, cell_size):
    x, y = pixel[0], pixel[1]
    x0 = left + round(x * cell_size)
    x1 = left + round((x + 1) * cell_size)
    y0 = top + round(y * cell_size)
    y1 = top + round((y + 1) * cell_size)
    if x1 <= x0 or y1 <= y0:
        return
    red, green, blue = _pixel_rgb(pixel)
    painter.fillRect(
        QRectF(x0, y0, x1 - x0, y1 - y0),
        QColor(red, green, blue),
    )


def draw_heart_loading(painter, center_x, center_y, scale, opacity=1.0):
    """Draw the unchanged solid heart under the result-layer crossfade."""
    opacity = min(1.0, max(0.0, float(opacity)))
    if opacity <= 0.0:
        return

    cell_size = HEART_CELL_SIZE * scale
    width = HEART_GRID_WIDTH * cell_size
    height = HEART_GRID_HEIGHT * cell_size
    left = round(center_x - width / 2)
    top = round(center_y - height / 2)
    painter.save()
    # The palette and alpha stay fixed; opacity is only modulated by the
    # existing 0.5s cross-fade when the numeric result enters or leaves.
    painter.setOpacity(HEART_MAX_OPACITY * opacity)
    for pixel in HEART_PIXEL_RGB:
        _draw_pixel(painter, pixel, left, top, cell_size)
    painter.restore()
