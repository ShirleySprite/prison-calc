# -*- coding: utf-8 -*-

from PySide6.QtCore import Qt, QRectF
from PySide6.QtGui import QColor, QImage, QPainter, QPainterPath, QPen

from .layout import ART_TO_VIEW, VW, VH

C_BG = QColor("#05070a")
C_VOID = QColor(0, 0, 0, 0)
APP_CORNER_RADIUS = 5.5  # Original art units.
BORDER_WIDTH_PX = 5  # Fixed physical-pixel border band.
BORDER_ALPHA_STEPS = (
    0, 17, 34, 51, 68, 85, 102, 119,
    136, 153, 170, 187, 204, 221, 238, 255,
)


def paint_background(width, height):
    """Render the card and its border directly at device-pixel resolution."""
    image = QImage(width, height, QImage.Format_ARGB32_Premultiplied)
    image.fill(C_VOID)
    painter = QPainter(image)
    painter.setRenderHint(QPainter.Antialiasing, True)
    painter.setPen(Qt.NoPen)

    scale_x = width / VW
    scale_y = height / VH
    radius_x = APP_CORNER_RADIUS * ART_TO_VIEW * scale_x
    radius_y = APP_CORNER_RADIUS * ART_TO_VIEW * scale_y
    border = min(float(BORDER_WIDTH_PX), width / 2, height / 2)

    body = QPainterPath()
    body.addRoundedRect(
        QRectF(border, border, width - 2 * border, height - 2 * border),
        max(0.0, radius_x - border), max(0.0, radius_y - border))
    painter.fillPath(body, C_BG)

    band_width = border / len(BORDER_ALPHA_STEPS)
    for index, alpha in enumerate(BORDER_ALPHA_STEPS):
        inset = (index + 0.5) * band_width
        band = QPainterPath()
        band.addRoundedRect(
            QRectF(inset, inset, width - 2 * inset, height - 2 * inset),
            max(0.0, radius_x - inset), max(0.0, radius_y - inset))
        pen = QPen(QColor(0, 0, 0, alpha))
        pen.setWidthF(band_width)
        painter.setPen(pen)
        painter.setBrush(Qt.NoBrush)
        painter.drawPath(band)

    painter.end()
    return image
