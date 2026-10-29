# -*- coding: utf-8 -*-

import json
import math

from PySide6.QtCore import Qt, QRectF
from PySide6.QtGui import QColor, QPainter

from .drawing_utils import draw_centered_sprite
from .layout import ART_TO_VIEW, ART_H, ART_W
from .particles import PARTICLE_SAFE_RECT

# Each click stores one center point and renders this single 5x5 pixel-art stamp.
ETCH_MARK_PIXEL_SIZE = 5
ETCH_MARK_PIXEL_CELL_VIEW = 1.6
ETCH_MARK_RADIUS_ART = (
    ETCH_MARK_PIXEL_SIZE * ETCH_MARK_PIXEL_CELL_VIEW / (2.0 * ART_TO_VIEW))
ETCH_MARK_SAFE_CLEARANCE_ART = ETCH_MARK_RADIUS_ART + 0.25
ETCH_MARK_EDGE_COLOR = QColor(17, 47, 87, 132)
ETCH_MARK_MID_COLOR = QColor(24, 67, 122, 220)
ETCH_MARK_CORE_COLOR = QColor(48, 101, 164, 255)
ETCH_MARK_PIXELS = (
    (2, 0, ETCH_MARK_EDGE_COLOR),
    (1, 1, ETCH_MARK_EDGE_COLOR), (2, 1, ETCH_MARK_MID_COLOR),
    (3, 1, ETCH_MARK_EDGE_COLOR),
    (0, 2, ETCH_MARK_EDGE_COLOR), (1, 2, ETCH_MARK_MID_COLOR),
    (2, 2, ETCH_MARK_CORE_COLOR), (3, 2, ETCH_MARK_MID_COLOR),
    (4, 2, ETCH_MARK_EDGE_COLOR),
    (1, 3, ETCH_MARK_EDGE_COLOR), (2, 3, ETCH_MARK_MID_COLOR),
    (3, 3, ETCH_MARK_EDGE_COLOR),
    (2, 4, ETCH_MARK_EDGE_COLOR),
)
# The eraser's hit radius matches one etched stamp; it does not add the
# stamp radius a second time, which would make the effective area twice as big.
ERASER_RADIUS_ART = ETCH_MARK_RADIUS_ART
MAX_UNDO_STEPS = 100


class EtchMarkStore:
    """Persistent, ordered back-surface marks with a compact undo history."""

    VERSION = 1

    def __init__(self, serialized=None):
        self.marks = []
        self.history = []
        self._next_id = 1
        self._load(serialized)

    def _push_history(self, action):
        self.history.append(action)
        if len(self.history) > MAX_UNDO_STEPS:
            del self.history[:-MAX_UNDO_STEPS]

    @staticmethod
    def _clean_mark(value):
        if not isinstance(value, dict):
            return None
        raw_id = value.get("id")
        if isinstance(raw_id, bool):
            return None
        try:
            mark_id = int(raw_id)
            x = float(value.get("x"))
            y = float(value.get("y"))
        except (TypeError, ValueError, OverflowError):
            return None
        if (mark_id < 1 or not math.isfinite(x) or not math.isfinite(y)
                or x < 0.0 or x > ART_W or y < 0.0 or y > ART_H
                or not point_in_etch_surface(x, y, ETCH_MARK_SAFE_CLEARANCE_ART)):
            return None
        return {"id": mark_id, "x": x, "y": y}

    def _load(self, serialized):
        if not serialized:
            return
        if isinstance(serialized, bytes):
            try:
                serialized = serialized.decode("utf-8")
            except UnicodeDecodeError:
                return
        try:
            payload = json.loads(str(serialized))
        except (TypeError, ValueError, json.JSONDecodeError):
            return
        if not isinstance(payload, dict) or payload.get("version") != self.VERSION:
            return

        seen_ids = set()
        raw_marks = payload.get("marks", [])
        if not isinstance(raw_marks, list):
            raw_marks = []
        for raw_mark in raw_marks:
            mark = self._clean_mark(raw_mark)
            if mark is None or mark["id"] in seen_ids:
                continue
            seen_ids.add(mark["id"])
            self.marks.append(mark)
        self.marks.sort(key=lambda mark: mark["id"])

        max_seen_id = max(seen_ids, default=0)
        raw_history = payload.get("history", [])
        if isinstance(raw_history, list):
            for raw_action in raw_history:
                if not isinstance(raw_action, dict):
                    continue
                kind = raw_action.get("kind")
                if kind == "add":
                    raw_id = raw_action.get("id")
                    if isinstance(raw_id, bool):
                        continue
                    try:
                        mark_id = int(raw_id)
                    except (TypeError, ValueError, OverflowError):
                        continue
                    if mark_id < 1:
                        continue
                    self._push_history({"kind": "add", "id": mark_id})
                    max_seen_id = max(max_seen_id, mark_id)
                elif kind == "erase":
                    erased = []
                    erased_ids = set()
                    raw_erased = raw_action.get("marks", [])
                    if not isinstance(raw_erased, list):
                        continue
                    for raw_mark in raw_erased:
                        mark = self._clean_mark(raw_mark)
                        if mark is None or mark["id"] in erased_ids:
                            continue
                        erased.append(mark)
                        erased_ids.add(mark["id"])
                        max_seen_id = max(max_seen_id, mark["id"])
                    if erased:
                        erased.sort(key=lambda mark: mark["id"])
                        self._push_history({"kind": "erase", "marks": erased})

        try:
            requested_next_id = int(payload.get("next_id", 1))
        except (TypeError, ValueError, OverflowError):
            requested_next_id = 1
        self._next_id = max(1, requested_next_id, max_seen_id + 1)

    def add(self, x, y):
        x, y = float(x), float(y)
        if (not math.isfinite(x) or not math.isfinite(y)
                or x < 0.0 or x > ART_W or y < 0.0 or y > ART_H
                or not point_in_etch_surface(x, y, ETCH_MARK_SAFE_CLEARANCE_ART)):
            return False
        mark = {"id": self._next_id, "x": x, "y": y}
        self._next_id += 1
        self.marks.append(mark)
        self._push_history({"kind": "add", "id": mark["id"]})
        return True

    @staticmethod
    def _distance_to_segment_squared(px, py, x0, y0, x1, y1):
        dx, dy = x1 - x0, y1 - y0
        length_squared = dx * dx + dy * dy
        if length_squared <= 1e-12:
            return (px - x0) ** 2 + (py - y0) ** 2
        projection = ((px - x0) * dx + (py - y0) * dy) / length_squared
        projection = min(1.0, max(0.0, projection))
        nearest_x = x0 + projection * dx
        nearest_y = y0 + projection * dy
        return (px - nearest_x) ** 2 + (py - nearest_y) ** 2

    def erase_segment(self, x0, y0, x1, y1, radius=ERASER_RADIUS_ART):
        """Erase whole marks whose centers fall within the swept eraser area."""
        x0, y0, x1, y1 = map(float, (x0, y0, x1, y1))
        # Compare mark centers directly to the stamp-sized eraser radius. Do
        # not add another mark radius: that doubled the effective hit area.
        radius = max(0.0, float(radius))
        radius_squared = radius * radius
        removed = []
        kept = []
        for mark in self.marks:
            if self._distance_to_segment_squared(
                    mark["x"], mark["y"], x0, y0, x1, y1
            ) <= radius_squared:
                removed.append(dict(mark))
            else:
                kept.append(mark)
        if removed:
            self.marks = kept
        return removed

    def commit_erase(self, removed_marks):
        marks = [dict(mark) for mark in removed_marks]
        if not marks:
            return False
        marks.sort(key=lambda mark: mark["id"])
        self._push_history({"kind": "erase", "marks": marks})
        return True

    def undo(self):
        if not self.history:
            return False
        action = self.history.pop()
        if action["kind"] == "add":
            mark_id = action["id"]
            self.marks = [mark for mark in self.marks
                          if mark["id"] != mark_id]
        elif action["kind"] == "erase":
            present = {mark["id"] for mark in self.marks}
            self.marks.extend(
                dict(mark) for mark in action["marks"]
                if mark["id"] not in present
            )
            self.marks.sort(key=lambda mark: mark["id"])
        else:
            return False
        return True

    def serialize(self):
        payload = {
            "version": self.VERSION,
            "next_id": self._next_id,
            "marks": self.marks,
            "history": self.history,
        }
        return json.dumps(payload, ensure_ascii=True, separators=(",", ":"))


def point_in_etch_surface(x, y, clearance_art=0.0):
    """Whether an art-space mark fits inside the same safe inset as particles."""
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


def draw_etch_marks(painter, marks, scale):
    if not marks:
        return
    scale = max(float(scale), 1e-9)
    safe_left, safe_top, safe_right, safe_bottom = PARTICLE_SAFE_RECT

    painter.save()
    painter.setRenderHint(QPainter.Antialiasing, False)
    # Match the front-face particle safety rectangle exactly; these are view
    # coordinates, scaled into logical widget coordinates.
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
    for mark in marks:
        draw_centered_sprite(
            painter, ETCH_MARK_PIXELS,
            ETCH_MARK_PIXEL_SIZE, ETCH_MARK_PIXEL_SIZE,
            float(mark["x"]) * ART_TO_VIEW,
            float(mark["y"]) * ART_TO_VIEW,
            ETCH_MARK_PIXEL_CELL_VIEW,
            ETCH_MARK_PIXEL_CELL_VIEW,
        )
    painter.restore()
