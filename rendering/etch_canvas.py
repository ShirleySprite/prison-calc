# -*- coding: utf-8 -*-

import base64
import binascii
import json
import math
import struct
import zlib

from PySide6.QtCore import Qt, QRectF
from PySide6.QtGui import QColor, QImage, QPainter

from .background import C_BG
from .layout import ART_TO_VIEW, ART_H, ART_W, VH, VW
from .particles import PARTICLE_SAFE_RECT

# Each click paints an enlarged 10x10 pixel-art circle onto the RGB canvas.
# The original 5x5 stamp is nearest-neighbor scaled 2x in both dimensions.
ETCH_STAMP_BASE_SIZE = 5
ETCH_STAMP_SCALE = 2
ETCH_MARK_PIXEL_SIZE = ETCH_STAMP_BASE_SIZE * ETCH_STAMP_SCALE
ETCH_MARK_PIXEL_CELL_VIEW = 1.6
ETCH_MARK_RADIUS_ART = (
    ETCH_MARK_PIXEL_SIZE * ETCH_MARK_PIXEL_CELL_VIEW / (2.0 * ART_TO_VIEW))
ETCH_MARK_SAFE_CLEARANCE_ART = ETCH_MARK_RADIUS_ART + 0.25
# Single-hit edge/mid values preserve the former alpha-blended look over C_BG.
ETCH_EDGE_RGB = (11, 28, 50)
ETCH_MID_RGB = (21, 59, 107)
ETCH_CORE_RGB = (48, 101, 164)
_ETCH_STAMP_BASE_PIXELS = (
    (2, 0, ETCH_EDGE_RGB),
    (1, 1, ETCH_EDGE_RGB), (2, 1, ETCH_MID_RGB),
    (3, 1, ETCH_EDGE_RGB),
    (0, 2, ETCH_EDGE_RGB), (1, 2, ETCH_MID_RGB),
    (2, 2, ETCH_CORE_RGB), (3, 2, ETCH_MID_RGB),
    (4, 2, ETCH_EDGE_RGB),
    (1, 3, ETCH_EDGE_RGB), (2, 3, ETCH_MID_RGB),
    (3, 3, ETCH_EDGE_RGB),
    (2, 4, ETCH_EDGE_RGB),
)
ETCH_STAMP_PIXELS = tuple(
    (col * ETCH_STAMP_SCALE + offset_x,
     row * ETCH_STAMP_SCALE + offset_y, color)
    for col, row, color in _ETCH_STAMP_BASE_PIXELS
    for offset_y in range(ETCH_STAMP_SCALE)
    for offset_x in range(ETCH_STAMP_SCALE)
)
# Eraser is now half the enlarged engraving's width and height.
ETCH_ERASER_SCALE = 1
ETCH_ERASER_PIXEL_SIZE = ETCH_STAMP_BASE_SIZE * ETCH_ERASER_SCALE
ETCH_ERASER_PIXELS = tuple(
    (col * ETCH_ERASER_SCALE + offset_x,
     row * ETCH_ERASER_SCALE + offset_y, color)
    for col, row, color in _ETCH_STAMP_BASE_PIXELS
    for offset_y in range(ETCH_ERASER_SCALE)
    for offset_x in range(ETCH_ERASER_SCALE)
)

# The canvas starts at the card's near-black background RGB. Paint adds only
# positive RGB increments and saturates at the stamp's core color.
ETCH_CANVAS_BASE_RGB = (C_BG.red(), C_BG.green(), C_BG.blue())
ETCH_CANVAS_MAX_RGB = ETCH_CORE_RGB
MAX_UNDO_STEPS = 100
ERASER_SAMPLE_SPACING_VIEW = ETCH_MARK_PIXEL_CELL_VIEW / 2.0
ERASER_CURSOR_COLOR = QColor(255, 250, 240, 179)  # 70% opacity.

CANVAS_VERSION = 2
CANVAS_PREFIX = "etch-canvas-v2:"
_CANVAS_PIXEL_COUNT = VW * VH
_PIXEL_RECORD = struct.Struct("<I3B")
_ACTION_COUNT = struct.Struct("<I")


def point_in_etch_surface(x, y, clearance_art=0.0):
    """Whether an art-space stamp fits inside the particle safety rectangle."""
    try:
        x, y = float(x), float(y)
        clearance = max(0.0, float(clearance_art))
    except (TypeError, ValueError, OverflowError):
        return False
    if not math.isfinite(x) or not math.isfinite(y) or not math.isfinite(clearance):
        return False

    safe_left, safe_top, safe_right, safe_bottom = PARTICLE_SAFE_RECT
    left = safe_left / ART_TO_VIEW + clearance
    top = safe_top / ART_TO_VIEW + clearance
    right = safe_right / ART_TO_VIEW - clearance
    bottom = safe_bottom / ART_TO_VIEW - clearance
    return left <= x <= right and top <= y <= bottom


def _serialized_text(value):
    if isinstance(value, bytes):
        try:
            return value.decode("utf-8")
        except UnicodeDecodeError:
            return ""
    if value is None:
        return ""
    return str(value)


def _stamp_cell_rects(center_x_view, center_y_view, erase=False):
    pixel_size = (
        ETCH_ERASER_PIXEL_SIZE if erase else ETCH_MARK_PIXEL_SIZE)
    pixels = ETCH_ERASER_PIXELS if erase else ETCH_STAMP_PIXELS
    pixel_width = max(1, round(pixel_size * ETCH_MARK_PIXEL_CELL_VIEW))
    left = round(center_x_view - pixel_width / 2)
    top = round(center_y_view - pixel_width / 2)
    for col, row, color in pixels:
        x0 = left + round(col * ETCH_MARK_PIXEL_CELL_VIEW)
        x1 = left + round((col + 1) * ETCH_MARK_PIXEL_CELL_VIEW)
        y0 = top + round(row * ETCH_MARK_PIXEL_CELL_VIEW)
        y1 = top + round((row + 1) * ETCH_MARK_PIXEL_CELL_VIEW)
        yield x0, y0, x1, y1, color


class EtchCanvasStore:
    """RGB pixel canvas with additive engraving, pixel erasing, and undo."""

    VERSION = CANVAS_VERSION

    def __init__(self, serialized=None, legacy_serialized=None):
        self._pixels = bytearray(ETCH_CANVAS_BASE_RGB) * _CANVAS_PIXEL_COUNT
        self._image = QImage(VW, VH, QImage.Format_RGB32)
        self._image.fill(self._rgb_to_qrgb(ETCH_CANVAS_BASE_RGB))
        self.history = []
        self.migrated_legacy = False

        if not self._load(serialized):
            self.migrated_legacy = self._load_legacy_marks(legacy_serialized)

    @property
    def image(self):
        """RGB canvas image with unetched pixels at the black base color."""
        return self._image

    @staticmethod
    def _rgb_to_qrgb(rgb):
        red, green, blue = rgb
        return 0xFF000000 | (red << 16) | (green << 8) | blue

    def _write_pixel(self, index, rgb):
        offset = index * 3
        red, green, blue = rgb
        self._pixels[offset] = red
        self._pixels[offset + 1] = green
        self._pixels[offset + 2] = blue
        self._image.setPixel(
            index % VW, index // VW, self._rgb_to_qrgb(rgb))

    def _sync_image(self):
        self._image.fill(self._rgb_to_qrgb(ETCH_CANVAS_BASE_RGB))
        for index in range(_CANVAS_PIXEL_COUNT):
            offset = index * 3
            rgb = (
                self._pixels[offset],
                self._pixels[offset + 1],
                self._pixels[offset + 2],
            )
            if rgb != ETCH_CANVAS_BASE_RGB:
                self._image.setPixel(
                    index % VW, index // VW, self._rgb_to_qrgb(rgb))

    def _push_history(self, changes):
        if not changes:
            return
        self.history.append(tuple(changes))
        if len(self.history) > MAX_UNDO_STEPS:
            del self.history[:-MAX_UNDO_STEPS]

    def _record_changes(self, changes):
        if not changes:
            return False
        ordered = tuple(
            (index, *rgb) for index, rgb in sorted(changes.items()))
        self._push_history(ordered)
        return True

    def _point_is_valid(self, x_art, y_art):
        return (
            math.isfinite(x_art) and math.isfinite(y_art)
            and 0.0 <= x_art <= ART_W and 0.0 <= y_art <= ART_H
            and point_in_etch_surface(
                x_art, y_art, ETCH_MARK_SAFE_CLEARANCE_ART)
        )

    def _apply_stamp(self, center_x_view, center_y_view, changes, erase=False):
        safe_left, safe_top, safe_right, safe_bottom = PARTICLE_SAFE_RECT
        base = ETCH_CANVAS_BASE_RGB
        maximum = ETCH_CANVAS_MAX_RGB

        for x0, y0, x1, y1, target_rgb in _stamp_cell_rects(
                center_x_view, center_y_view, erase=erase):
            for y in range(max(y0, safe_top), min(y1, safe_bottom)):
                row_start = y * VW
                for x in range(max(x0, safe_left), min(x1, safe_right)):
                    index = row_start + x
                    offset = index * 3
                    old_rgb = (
                        self._pixels[offset],
                        self._pixels[offset + 1],
                        self._pixels[offset + 2],
                    )
                    if erase:
                        if old_rgb == base:
                            continue
                        changes.setdefault(index, old_rgb)
                        self._write_pixel(index, base)
                        continue

                    # Each stroke adds its depth to the existing RGB value.
                    # A darker rim can only brighten an older pixel; it can
                    # never overwrite or dim a brighter engraving.
                    delta = tuple(
                        max(0, target_rgb[channel] - base[channel])
                        for channel in range(3)
                    )
                    new_rgb = tuple(
                        min(maximum[channel], old_rgb[channel] + delta[channel])
                        for channel in range(3)
                    )
                    if new_rgb == old_rgb:
                        continue
                    changes.setdefault(index, old_rgb)
                    self._write_pixel(index, new_rgb)

    def paint_stamp(self, x_art, y_art):
        """Add one 5x5 pixel-art stamp to the canvas as one undo action."""
        try:
            x_art, y_art = float(x_art), float(y_art)
        except (TypeError, ValueError, OverflowError):
            return False
        if not self._point_is_valid(x_art, y_art):
            return False

        changes = {}
        self._apply_stamp(
            x_art * ART_TO_VIEW, y_art * ART_TO_VIEW, changes)
        return self._record_changes(changes)

    def erase_segment(self, x0_art, y0_art, x1_art, y1_art):
        """Erase canvas pixels under a solid stamp-shaped brush sweep."""
        try:
            x0, y0, x1, y1 = map(
                float, (x0_art, y0_art, x1_art, y1_art))
        except (TypeError, ValueError, OverflowError):
            return {}
        if not all(math.isfinite(value) for value in (x0, y0, x1, y1)):
            return {}

        x0 *= ART_TO_VIEW
        y0 *= ART_TO_VIEW
        x1 *= ART_TO_VIEW
        y1 *= ART_TO_VIEW
        dx, dy = x1 - x0, y1 - y0
        distance = math.hypot(dx, dy)
        sample_count = max(
            1, math.ceil(distance / ERASER_SAMPLE_SPACING_VIEW))
        changes = {}
        for sample in range(sample_count + 1):
            t = sample / sample_count
            self._apply_stamp(
                x0 + dx * t, y0 + dy * t, changes, erase=True)
        return changes

    def commit_erase(self, changes):
        """Commit one whole pixel-erasing gesture as one undo step."""
        return self._record_changes(changes)

    def undo(self):
        if not self.history:
            return False
        changes = self.history.pop()
        for index, red, green, blue in changes:
            self._write_pixel(index, (red, green, blue))
        return True

    def _decode_history(self, packed_history):
        self.history = []
        offset = 0
        while offset < len(packed_history):
            if len(packed_history) - offset < _ACTION_COUNT.size:
                raise ValueError("truncated etch undo history")
            (count,) = _ACTION_COUNT.unpack_from(packed_history, offset)
            offset += _ACTION_COUNT.size
            if (count > _CANVAS_PIXEL_COUNT
                    or len(packed_history) - offset
                    < count * _PIXEL_RECORD.size):
                raise ValueError("invalid etch undo action")
            changes = []
            seen = set()
            for _ in range(count):
                index, red, green, blue = _PIXEL_RECORD.unpack_from(
                    packed_history, offset)
                offset += _PIXEL_RECORD.size
                if index >= _CANVAS_PIXEL_COUNT:
                    raise ValueError("invalid etch pixel index")
                if index in seen:
                    continue
                seen.add(index)
                changes.append((index, red, green, blue))
            if changes:
                self._push_history(changes)

    def _load(self, serialized):
        text = _serialized_text(serialized)
        if not text.startswith(CANVAS_PREFIX):
            return False
        try:
            packed = base64.b64decode(
                text[len(CANVAS_PREFIX):], validate=True)
            payload_bytes = zlib.decompress(packed)
            payload = json.loads(payload_bytes.decode("utf-8"))
            if (not isinstance(payload, dict)
                    or payload.get("version") != CANVAS_VERSION
                    or payload.get("width") != VW
                    or payload.get("height") != VH):
                return False
            pixels = base64.b64decode(payload.get("pixels", ""), validate=True)
            if len(pixels) != len(self._pixels):
                return False
            packed_history = base64.b64decode(
                payload.get("history", ""), validate=True)
        except (binascii.Error, zlib.error, UnicodeDecodeError,
                json.JSONDecodeError, TypeError, ValueError, KeyError):
            return False

        self._pixels = bytearray(pixels)
        self._sanitize_pixels()
        try:
            self._decode_history(packed_history)
        except (struct.error, ValueError):
            self.history = []
        self._sync_image()
        return True

    def _sanitize_pixels(self):
        safe_left, safe_top, safe_right, safe_bottom = PARTICLE_SAFE_RECT
        base, maximum = ETCH_CANVAS_BASE_RGB, ETCH_CANVAS_MAX_RGB
        base_bytes = bytes(base)
        for y in range(VH):
            for x in range(VW):
                offset = (y * VW + x) * 3
                if not (safe_left <= x < safe_right
                        and safe_top <= y < safe_bottom):
                    self._pixels[offset:offset + 3] = base_bytes
                    continue
                for channel in range(3):
                    self._pixels[offset + channel] = min(
                        maximum[channel],
                        max(base[channel], self._pixels[offset + channel]))

    def _load_legacy_marks(self, serialized):
        text = _serialized_text(serialized)
        if not text:
            return False
        try:
            payload = json.loads(text)
        except (TypeError, ValueError, json.JSONDecodeError):
            return False
        if not isinstance(payload, dict) or payload.get("version") != 1:
            return False
        raw_marks = payload.get("marks", [])
        if not isinstance(raw_marks, list):
            return False

        marks = []
        seen_ids = set()
        for value in raw_marks:
            if not isinstance(value, dict) or isinstance(value.get("id"), bool):
                continue
            try:
                mark_id = int(value.get("id"))
                x, y = float(value.get("x")), float(value.get("y"))
            except (TypeError, ValueError, OverflowError):
                continue
            if (mark_id < 1 or mark_id in seen_ids
                    or not math.isfinite(x) or not math.isfinite(y)
                    or not self._point_is_valid(x, y)):
                continue
            seen_ids.add(mark_id)
            marks.append((mark_id, x, y))

        for _, x, y in sorted(marks):
            self._apply_stamp(x * ART_TO_VIEW, y * ART_TO_VIEW, {})
        self.history = []
        self._sync_image()
        return True

    def serialize(self):
        history = bytearray()
        for action in self.history:
            history.extend(_ACTION_COUNT.pack(len(action)))
            for index, red, green, blue in action:
                history.extend(_PIXEL_RECORD.pack(index, red, green, blue))

        payload = {
            "version": CANVAS_VERSION,
            "width": VW,
            "height": VH,
            "pixels": base64.b64encode(bytes(self._pixels)).decode("ascii"),
            "history": base64.b64encode(bytes(history)).decode("ascii"),
        }
        raw = json.dumps(
            payload, ensure_ascii=True, separators=(",", ":")
        ).encode("utf-8")
        return CANVAS_PREFIX + base64.b64encode(
            zlib.compress(raw, level=6)).decode("ascii")


def draw_eraser_cursor(painter, center_view, scale):
    """Show the solid eraser footprint without modifying the RGB canvas."""
    if center_view is None:
        return
    scale = max(float(scale), 1e-9)
    center_x_view, center_y_view = map(float, center_view)
    safe_left, safe_top, safe_right, safe_bottom = PARTICLE_SAFE_RECT

    painter.save()
    painter.setRenderHint(QPainter.Antialiasing, False)
    painter.setPen(Qt.NoPen)
    painter.setBrush(ERASER_CURSOR_COLOR)
    painter.setClipRect(
        QRectF(
            safe_left * scale,
            safe_top * scale,
            (safe_right - safe_left) * scale,
            (safe_bottom - safe_top) * scale,
        ),
        Qt.ClipOperation.IntersectClip,
    )
    painter.scale(scale, scale)
    for x0, y0, x1, y1, _ in _stamp_cell_rects(
            center_x_view, center_y_view, erase=True):
        x0, y0 = max(x0, safe_left), max(y0, safe_top)
        x1, y1 = min(x1, safe_right), min(y1, safe_bottom)
        if x1 > x0 and y1 > y0:
            painter.drawRect(x0, y0, x1 - x0, y1 - y0)
    painter.restore()


def draw_etch_canvas(painter, image, scale):
    if image is None or image.isNull():
        return
    scale = max(float(scale), 1e-9)
    safe_left, safe_top, safe_right, safe_bottom = PARTICLE_SAFE_RECT

    painter.save()
    painter.setRenderHint(QPainter.SmoothPixmapTransform, False)
    painter.setClipRect(
        QRectF(
            safe_left * scale,
            safe_top * scale,
            (safe_right - safe_left) * scale,
            (safe_bottom - safe_top) * scale,
        ),
        Qt.ClipOperation.IntersectClip,
    )
    painter.drawImage(
        QRectF(0, 0, VW * scale, VH * scale),
        image,
        QRectF(0, 0, VW, VH),
    )
    painter.restore()
