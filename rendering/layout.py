# -*- coding: utf-8 -*-

from PySide6.QtCore import QRect, QRectF

VW, VH = 320, 490
ART_W, ART_H = 160, 245
ART_TO_VIEW = 2

# Compact the artwork while leaving room for the taller restored flame.
CONTENT_SHIFT_ART_Y = -20

# The only supported application scales; UI and artwork share one scale.
ASSET_SCALE_ANCHORS = tuple(step / 5 for step in range(5, 11))

ROW_Y = (148, 176)
BOX_W, BOX_H, BOX_GAP, SEP_W = 10, 15, 3, 9
DATE_TOTAL_WIDTH = 8 * BOX_W + 5 * BOX_GAP + 2 * SEP_W
DATE_MARK_LANE_WIDTH = 11
DATE_MARK_GAP = 7
DATE_GROUP_WIDTH = DATE_MARK_LANE_WIDTH + DATE_MARK_GAP + DATE_TOTAL_WIDTH
DATE_GROUP_LEFT = round(
    (ART_W - DATE_GROUP_WIDTH) / 2 + DATE_MARK_LANE_WIDTH + DATE_MARK_GAP)
LIFE_MARK_CENTER_X = DATE_GROUP_LEFT - DATE_MARK_GAP - DATE_MARK_LANE_WIDTH / 2
LIFE_MARK_CENTER_Y = tuple(
    ROW_Y[row] + CONTENT_SHIFT_ART_Y + BOX_H / 2 for row in range(2))
LIFE_MARK_HITBOX_WIDTH = 13.0
LIFE_MARK_HITBOX_HEIGHT = 14.0
FLAME_WIDTH_ART, FLAME_HEIGHT_ART = 22, 40
FLAME_RECT = QRect(
    (ART_W - FLAME_WIDTH_ART) // 2, 208,
    FLAME_WIDTH_ART, FLAME_HEIGHT_ART)
FLAME_DISPLAY_RECT = QRect(
    FLAME_RECT.x(), FLAME_RECT.y() + CONTENT_SHIFT_ART_Y,
    FLAME_WIDTH_ART, FLAME_HEIGHT_ART)
# Reserve the top half for the result, but sit its heart and digits lower in
# that space to give the visual more breathing room from the window top.
RESULT_CENTER_Y_OFFSET = 18.0  # View pixels before the shared window scale.
RESULT_ART_RECT = QRectF(5, 0, 150, ART_H / 2)
RESULT_RECT = QRectF(
    RESULT_ART_RECT.x() * ART_TO_VIEW,
    RESULT_ART_RECT.y() * ART_TO_VIEW,
    RESULT_ART_RECT.width() * ART_TO_VIEW,
    RESULT_ART_RECT.height() * ART_TO_VIEW,
)

def digit_box_rect(row, index):
    x = DATE_GROUP_LEFT
    for i in range(index):
        x += BOX_W + BOX_GAP
        if i in (3, 5):
            x += SEP_W - BOX_GAP
    return QRect(
        x, ROW_Y[row] + CONTENT_SHIFT_ART_Y, BOX_W, BOX_H)


def life_symbol_hit_rect(row, offset_x=0.0, offset_y=0.0):
    center_x = LIFE_MARK_CENTER_X + float(offset_x)
    center_y = LIFE_MARK_CENTER_Y[row] + float(offset_y)
    return QRectF(
        center_x - LIFE_MARK_HITBOX_WIDTH / 2,
        center_y - LIFE_MARK_HITBOX_HEIGHT / 2,
        LIFE_MARK_HITBOX_WIDTH,
        LIFE_MARK_HITBOX_HEIGHT,
    )
