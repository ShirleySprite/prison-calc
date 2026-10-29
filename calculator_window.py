# -*- coding: utf-8 -*-

import sys
import time
from datetime import date

from PySide6.QtCore import QPoint, Qt, QSettings, QTimer
from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import QWidget

from calculator_worker import CalculatorWorker
from rendering import (
    ART_TO_VIEW,
    ASSET_SCALE_ANCHORS,
    FLAME_COLOR_TRANSITION_SECONDS,
    FLAME_DISPLAY_RECT,
    FLAME_FLIP_HOLD_SECONDS,
    FLAME_HOLD_SECONDS,
    LIFE_MARK_CENTER_X,
    LIFE_MARK_CENTER_Y,
    VH,
    VW,
    Renderer,
    digit_box_rect,
    life_symbol_hit_rect,
)
from rendering.etch_canvas import (
    ETCH_MARK_SAFE_CLEARANCE_ART,
    EtchCanvasStore,
    point_in_etch_surface,
)

from rendering.background import BORDER_WIDTH_PX
from rendering.heart_motion import point_in_heart_tank
from rendering.particles import PARTICLE_SAFE_RECT
from rendering.icons import make_pin_cursor
from rendering.text import ERROR_RESULT_TEXT
from window_platform import set_native_topmost

WHEEL_ANGLE_PER_NOTCH = 120
TRACKPAD_PIXELS_PER_NOTCH = 60
DEFAULT_SCALE = 1.2  # Former 1.3 default floors to the 1.2 anchor.
TOP_EDGE_SNAP_DISTANCE = 18


class CalculatorWindow(QWidget):
    """Top-level window: owns input, persistence, and window interaction."""

    def __init__(self):
        super().__init__()
        self.setWindowFlags(Qt.Window | Qt.FramelessWindowHint)
        self.setAttribute(Qt.WA_TranslucentBackground, True)
        self.setMouseTracking(True)
        self._settings = QSettings("PrisonCalc", "WorkdayCalculator")
        self.scale_index = self._load_window_scale_index()
        saved_end = str(self._settings.value("end_date", "") or "")
        try:
            if len(saved_end) != 8 or not saved_end.isdigit():
                raise ValueError
            date(int(saved_end[:4]), int(saved_end[4:6]), int(saved_end[6:8]))
        except ValueError:
            saved_end = ""
            self._settings.remove("end_date")
            self._settings.sync()
        self.digits = [
            list(date.today().strftime("%Y%m%d")),
            list(saved_end) if saved_end else [""] * 8,
        ]
        self.focus_row = 0
        self.focus = 4
        self.focus_active = True
        self.status = "idle"
        self.result = None
        self.hover_flame = False
        self._flame_hover_entry_consumed = False
        self.flame_flipped = False
        self._flame_flip_pressed_at = None
        self._flame_flip_hold_completed = False
        self._shift_down = False
        self._chisel_mode = False
        self._etch_canvas = EtchCanvasStore(
            self._settings.value("back_surface/etch_canvas_v2", ""),
            legacy_serialized=self._settings.value(
                "back_surface/etch_marks_v1", ""),
        )
        if self._etch_canvas.migrated_legacy:
            self._settings.setValue(
                "back_surface/etch_canvas_v2", self._etch_canvas.serialize())
            self._settings.remove("back_surface/etch_marks_v1")
            self._settings.sync()
        self._chisel_gesture = None
        self._left_button_down = False
        self._last_pointer_pos = None
        self._pointer_inside = False
        self.pinned = False
        self.setCursor(make_pin_cursor())
        self._drag = None
        self._life_symbol_drag = None
        self._pressed_control = None
        self._flame_pressed_at = None
        self._flame_press_cancelled = False
        self._wheel_angle_remainder = 0
        self._wheel_pixel_remainder = 0
        self._thread = None
        self._close_pending = False
        self._renderer = Renderer()
        self._effect_timer = QTimer(self)
        self._effect_timer.setTimerType(Qt.TimerType.PreciseTimer)
        self._effect_timer.timeout.connect(self._effect_tick)
        self._apply_scale()

    @property
    def scale(self):
        return ASSET_SCALE_ANCHORS[self.scale_index]

    def _load_window_scale_index(self):
        default_index = ASSET_SCALE_ANCHORS.index(DEFAULT_SCALE)
        try:
            saved_scale = float(
                self._settings.value("window_scale", DEFAULT_SCALE))
        except (TypeError, ValueError, OverflowError):
            return default_index
        if not (ASSET_SCALE_ANCHORS[0] <= saved_scale
                <= ASSET_SCALE_ANCHORS[-1]):
            return default_index
        return min(
            range(len(ASSET_SCALE_ANCHORS)),
            key=lambda index: abs(ASSET_SCALE_ANCHORS[index] - saved_scale),
        )

    def _apply_scale(self):
        self._renderer.invalidate()
        self.resize(round(VW * self.scale), round(VH * self.scale))
        self._renderer.reset_window_motion(self.frameGeometry().topLeft())
        if getattr(self, "pinned", False):
            self._set_topmost(True)
        self.update()

    def _effect_tick(self):
        flame_held = (
            self._pressed_control == "flame"
            and self._flame_pressed_at is not None
            and not self._flame_press_cancelled
        )
        elapsed = (time.monotonic() - self._flame_pressed_at
                   if flame_held else 0.0)
        if flame_held and elapsed >= FLAME_HOLD_SECONDS:
            self._pressed_control = None
            self._flame_pressed_at = None
            self._flame_press_cancelled = False
            self.close()
            return

        if (self._flame_flip_pressed_at is not None
                and time.monotonic() - self._flame_flip_pressed_at
                >= FLAME_FLIP_HOLD_SECONDS):
            self.flame_flipped = not self.flame_flipped
            self._flame_flip_pressed_at = None
            self._flame_flip_hold_completed = True
            self._flame_hover_entry_consumed = True

        flip_held = (
            self._flame_flip_pressed_at is not None
            or self._flame_flip_hold_completed
        )

        if self.status == "done":
            result = self.result
        elif self.status == "error":
            result = ERROR_RESULT_TEXT
        else:
            result = None
        flip_progress = self._flame_flip_progress()
        palette, palette_seconds, palette_linear = (
            self._flame_palette_transition(flip_progress))
        paint_due = self._renderer.tick(
            result, self.frameGeometry().topLeft(), self.scale,
            flame_palette=palette,
            flame_transition_seconds=palette_seconds,
            flame_transition_linear=palette_linear,
            flame_flip_progress=flip_progress,
            chisel_mode=self._chisel_mode,
            status=self.status,
            dpr=self.devicePixelRatioF(),
        )
        if paint_due or ((flame_held or flip_held) and not self._chisel_mode):
            self.update()

    def _state(self):
        hold_elapsed = None
        if (self._pressed_control == "flame"
                and self._flame_pressed_at is not None
                and not self._flame_press_cancelled):
            hold_elapsed = min(
                FLAME_HOLD_SECONDS,
                max(0.0, time.monotonic() - self._flame_pressed_at))
        eraser_cursor_view = None
        if self._pointer_inside and self._last_pointer_pos is not None:
            eraser_cursor_view = (
                self._last_pointer_pos.x() / self.scale,
                self._last_pointer_pos.y() / self.scale,
            )
        eraser_cursor_visible = bool(
            self.flame_flipped and self._chisel_mode
            and self._shift_down and eraser_cursor_view is not None
        )
        return {
            "start": tuple(self.digits[0]),
            "end": tuple(self.digits[1]),
            "focus_row": self.focus_row,
            "focus": self.focus,
            "focus_active": self.focus_active,
            "status": self.status,
            "result": self.result,
            "hover_flame": self.hover_flame,
            "pinned": self.pinned,
            "flame_flipped": self.flame_flipped,
            "chisel_mode": self._chisel_mode,
            "etch_canvas": self._etch_canvas.image,
            "eraser_cursor_visible": eraser_cursor_visible,
            "eraser_cursor_view": eraser_cursor_view,
            "flame_hold_elapsed": hold_elapsed,
        }

    def _set_flame_hover(self, hovering):
        """Track one hover-color check per entry into the flame hit area."""
        hovering = bool(hovering)
        if not hovering:
            self._flame_hover_entry_consumed = False
        if hovering == self.hover_flame:
            return False
        self.hover_flame = hovering
        self._flame_hover_entry_consumed = False
        return True

    def _flame_flip_progress(self):
        if self._flame_flip_pressed_at is not None:
            elapsed = max(0.0, time.monotonic() - self._flame_flip_pressed_at)
            return min(1.0, elapsed / FLAME_FLIP_HOLD_SECONDS)
        if self._flame_flip_hold_completed:
            return 1.0
        return None

    def _flame_palette_transition(self, flip_progress):
        if flip_progress is not None:
            if self._flame_flip_pressed_at is not None:
                target = "orange" if self.flame_flipped else "green"
            else:
                target = "green" if self.flame_flipped else "orange"
            return target, FLAME_FLIP_HOLD_SECONDS, True
        hover_blue = (
            self.hover_flame and not self._flame_hover_entry_consumed)
        if self.flame_flipped:
            target = "blue" if hover_blue else "green"
            return target, FLAME_COLOR_TRANSITION_SECONDS, False
        target = "blue" if hover_blue else "orange"
        return target, FLAME_COLOR_TRANSITION_SECONDS, False

    def _virt(self, pos):
        factor = ART_TO_VIEW * self.scale
        return QPoint(int(pos.x() // factor), int(pos.y() // factor))

    def _art_xy(self, pos):
        factor = ART_TO_VIEW * self.scale
        return float(pos.x()) / factor, float(pos.y()) / factor

    def _track_pointer_position(self, position):
        self._last_pointer_pos = position
        self._pointer_inside = (
            0 <= position.x() < self.width()
            and 0 <= position.y() < self.height()
        )

    def _shift_active(self, event=None):
        return bool(
            self._shift_down
            or (event is not None
                and event.modifiers() & Qt.ShiftModifier)
        )

    def _inside_etch_surface(self, position, clearance_art=0.0):
        art_x, art_y = self._art_xy(position)
        return point_in_etch_surface(art_x, art_y, clearance_art)

    def _persist_etch_canvas(self):
        self._settings.setValue(
            "back_surface/etch_canvas_v2", self._etch_canvas.serialize())
        self._settings.sync()

    def _finish_chisel_gesture(self):
        gesture = self._chisel_gesture
        self._chisel_gesture = None
        if gesture and gesture.get("kind") == "erase":
            if self._etch_canvas.commit_erase(gesture["changes"]):
                self._persist_etch_canvas()
                self.update()

    def _erase_etch_segment(self, start, end):
        gesture = self._chisel_gesture
        if not gesture or gesture.get("kind") != "erase":
            return False
        changes = self._etch_canvas.erase_segment(
            start[0], start[1], end[0], end[1])
        if not changes:
            return False
        for index, old_rgb in changes.items():
            gesture["changes"].setdefault(index, old_rgb)
        self.update()
        return True

    def _begin_chisel_gesture(self, position, shift_held):
        art_x, art_y = self._art_xy(position)
        if shift_held:
            self._chisel_gesture = {
                "kind": "erase",
                "last_art": (art_x, art_y),
                "changes": {},
            }
            self._erase_etch_segment((art_x, art_y), (art_x, art_y))
            return True
        if not self._inside_etch_surface(
                position, clearance_art=ETCH_MARK_SAFE_CLEARANCE_ART):
            return False
        if self._etch_canvas.paint_stamp(art_x, art_y):
            self._persist_etch_canvas()
            self.update()
        return True

    def _toggle_chisel_mode(self):
        if not self.flame_flipped:
            return False
        self._finish_chisel_gesture()
        self._left_button_down = False
        self._drag = None
        self._chisel_mode = not self._chisel_mode
        self._pressed_control = None
        self._flame_pressed_at = None
        self._flame_press_cancelled = False
        self._flame_flip_pressed_at = None
        self._flame_flip_hold_completed = False
        self.update()
        return True

    def _undo_etch_action(self):
        self._finish_chisel_gesture()
        if self._etch_canvas.undo():
            self._persist_etch_canvas()
            self.update()

    def _life_symbol_at(self, x, y):
        for name, row in (("cross", 0), ("star", 1)):
            offset_x, offset_y = self._renderer.life_symbol_offset(name)
            hit_rect = life_symbol_hit_rect(row, offset_x, offset_y)
            if (hit_rect.left() <= x <= hit_rect.right()
                    and hit_rect.top() <= y <= hit_rect.bottom()):
                return name, row
        return None

    def _interactive_target_at(self, position):
        """Return whether the pointer is over a control, not display-only output."""
        virtual = self._virt(position.toPoint())
        if FLAME_DISPLAY_RECT.contains(virtual):
            return True
        # The hidden calculator controls no longer receive input; remaining
        # blank surface is available for window management.
        if self.flame_flipped:
            return False

        art_x, art_y = self._art_xy(position)
        if self._life_symbol_at(art_x, art_y) is not None:
            return True

        return any(
            digit_box_rect(row, index).contains(virtual)
            for row in range(2) for index in range(8)
        )

    def paintEvent(self, _):
        self._renderer.paint(self, self._state(), self.scale)

    def _set_topmost(self, on):
        return set_native_topmost(int(self.winId()), on)

    def _toggle_pin(self):
        on = not self.pinned
        if self._set_topmost(on):
            self.pinned = on
            self.update()
            return
        if sys.platform == "win32":
            return
        self.pinned = on
        geo = self.geometry()
        flags = self.windowFlags()
        if self.pinned:
            flags |= Qt.WindowStaysOnTopHint
        else:
            flags &= ~Qt.WindowStaysOnTopHint
        self.setWindowFlags(flags)
        self.show()
        self.setGeometry(geo)
        self.raise_()
        self.update()

    def _reset_result(self):
        if self.status in ("done", "error"):
            self.status = "idle"
            self.result = None

    def _remember_end_date(self):
        cells = self.digits[1]
        if not any(cells):
            if self._settings.contains("end_date"):
                self._settings.remove("end_date")
                self._settings.sync()
            return
        if len(cells) != 8 or any(
                len(ch) != 1 or not ch.isdigit() for ch in cells):
            return
        value = "".join(cells)
        try:
            date(int(value[:4]), int(value[4:6]), int(value[6:8]))
        except ValueError:
            return
        if self._settings.value("end_date", "") != value:
            self._settings.setValue("end_date", value)
            self._settings.sync()

    def _type_digit(self, ch):
        if self.status == "computing":
            return
        self.focus_active = True
        row, i = self.focus_row, self.focus
        if self.digits[row][i] != ch:
            self.digits[row][i] = ch
            if row == 1:
                self._remember_end_date()
            self._reset_result()
        if i < 7:
            self.focus = i + 1
        self.update()

    def _backspace(self):
        if self.status == "computing":
            return
        self.focus_active = True
        row, i = self.focus_row, self.focus
        if self.digits[row][i]:
            self.digits[row][i] = ""
            if row == 1:
                self._remember_end_date()
            self._reset_result()
        elif i > 0:
            self.focus = i - 1
        self.update()

    def _paste(self, text):
        if self.status == "computing":
            return
        ds = "".join(c for c in text if c.isdigit())[:8]
        if not ds:
            return
        self.focus_active = True
        row = self.focus_row
        self.digits[row] = list(ds) + [""] * (8 - len(ds))
        if row == 1:
            self._remember_end_date()
        self.focus = min(len(ds), 7)
        self._reset_result()
        self.update()

    def _read(self, row):
        s = "".join(self.digits[row])
        if len(s) != 8 or not s.isdigit():
            raise ValueError
        return date(int(s[:4]), int(s[4:6]), int(s[6:8]))

    def _calc(self):
        if self.status == "computing" or self._thread is not None:
            return
        try:
            begin = self._read(0)
            end = self._read(1)
        except ValueError:
            self.status = "error"
            self.update()
            return
        if begin > end:
            self.status = "error"
            self.update()
            return
        self._remember_end_date()
        self.status = "computing"
        self.focus_active = False
        self.result = None
        self.update()
        self._thread = CalculatorWorker(begin, end, parent=self)
        self._thread.finished_ok.connect(self._on_done)
        self._thread.failed.connect(self._on_fail)
        self._thread.finished.connect(self._on_thread_finished)
        self._thread.start()

    def _on_done(self, days):
        self.result = days
        self._renderer.reset_animation()
        self.status = "done"
        self.update()

    def _on_fail(self):
        self.status = "error"
        self.update()

    def _on_thread_finished(self):
        thread = self.sender()
        if thread is not None:
            thread.wait()
            if thread is self._thread:
                self._thread = None
            thread.deleteLater()
        if self._close_pending:
            self.close()

    def keyPressEvent(self, e):
        k = e.key()
        if k == Qt.Key_Shift:
            if not self._shift_down:
                self._shift_down = True
                if (self.flame_flipped and self._chisel_mode
                        and self._left_button_down
                        and not (self._chisel_gesture
                                 and self._chisel_gesture.get("kind") == "erase")):
                    position = self._last_pointer_pos
                    if position is not None:
                        self._chisel_gesture = None
                        self._drag = None
                        self._begin_chisel_gesture(position, True)
                self.update()
            e.accept()
            return
        if (self.flame_flipped and self._chisel_mode
                and (e.modifiers() & Qt.ControlModifier)
                and k == Qt.Key_Z):
            self._undo_etch_action()
            e.accept()
            return
        if self.flame_flipped:
            if k == Qt.Key_Escape:
                self.close()
            else:
                e.ignore()
            return
        if self.status == "computing":
            if k == Qt.Key_Escape:
                self.close()
            else:
                e.ignore()
            return
        if Qt.Key_0 <= k <= Qt.Key_9:
            self._type_digit(chr(k))
        elif e.text().isdigit() and len(e.text()) == 1:
            self._type_digit(e.text())
        elif k == Qt.Key_Backspace:
            self._backspace()
        elif k == Qt.Key_Left:
            self.focus_active = True
            self.focus = max(0, self.focus - 1)
            self.update()
        elif k == Qt.Key_Right:
            self.focus_active = True
            self.focus = min(7, self.focus + 1)
            self.update()
        elif k in (Qt.Key_Up, Qt.Key_Down):
            self.focus_active = True
            self.focus_row = 1 - self.focus_row
            self.update()
        elif k in (Qt.Key_Return, Qt.Key_Enter):
            return
        elif k == Qt.Key_Escape:
            self.close()
        elif (e.modifiers() & Qt.ControlModifier) and k == Qt.Key_V:
            self._paste(QGuiApplication.clipboard().text())
        else:
            super().keyPressEvent(e)

    def keyReleaseEvent(self, e):
        if e.key() == Qt.Key_Shift:
            if (self._chisel_gesture
                    and self._chisel_gesture.get("kind") == "erase"):
                self._finish_chisel_gesture()
            if self._shift_down:
                self._shift_down = False
                self.update()
            e.accept()
            return
        super().keyReleaseEvent(e)

    def focusOutEvent(self, e):
        self._renderer.cancel_heart_hold()
        if self._pressed_control == "heart":
            self._pressed_control = None
        if (self._chisel_gesture
                and self._chisel_gesture.get("kind") == "erase"):
            self._finish_chisel_gesture()
        self._left_button_down = False
        if self._shift_down:
            self._shift_down = False
            self.update()
        super().focusOutEvent(e)

    def _in_heart_tank(self, pos):
        feather_inset = BORDER_WIDTH_PX / (self.scale * self.devicePixelRatioF())
        return point_in_heart_tank(
            pos.x() / self.scale, pos.y() / self.scale,
            feather_inset, PARTICLE_SAFE_RECT)

    def _press_heart(self, e):
        # Keep the immediate click impulse; holding anywhere in the idle game's
        # tank additionally begins a cancellable, two-second return/exit.
        poked = self._renderer.poke_heart(
            e.position().x(), e.position().y(), self.scale)
        if (self._in_heart_tank(e.position())
                and self._renderer.begin_heart_exit(self.status)):
            self._pressed_control = "heart"
            return True
        if poked:
            return True
        if self._renderer.begin_heart_hold(
                e.position().x(), e.position().y(), self.scale, self.status):
            self._pressed_control = "heart"
            return True
        return False

    def mousePressEvent(self, e):
        pos = e.position().toPoint()
        self._track_pointer_position(pos)
        if e.button() == Qt.RightButton:
            if (self._pressed_control is not None
                    or self._life_symbol_drag is not None
                    or self._drag is not None):
                return
            # In chisel mode the flame is hidden and right-click is reserved
            # for the double-click mode toggle; it must not start a flip hold.
            if self.flame_flipped and self._chisel_mode:
                if self._shift_active(e):
                    self.update()
                return
            v = self._virt(pos)
            if FLAME_DISPLAY_RECT.contains(v):
                self._flame_flip_hold_completed = False
                self._flame_flip_pressed_at = time.monotonic()
                self._set_flame_hover(True)
                self.update()
            return
        if (e.button() != Qt.LeftButton
                or self._flame_flip_pressed_at is not None
                or self._flame_flip_hold_completed):
            return

        self._left_button_down = True
        self._pressed_control = None
        self._flame_pressed_at = None
        self._flame_press_cancelled = False
        self._drag = None
        self._life_symbol_drag = None
        v = self._virt(pos)

        if self.flame_flipped and self._chisel_mode:
            self.focus_active = False
            self._begin_chisel_gesture(pos, self._shift_active(e))
            self.update()
            return

        if FLAME_DISPLAY_RECT.contains(v):
            self.focus_active = False
            self._pressed_control = "flame"
            self._flame_pressed_at = time.monotonic()
            self._set_flame_hover(True)
            self.update()
            return

        if self.flame_flipped:
            self.focus_active = False
            self._drag = (
                "move", e.globalPosition().toPoint()
                - self.frameGeometry().topLeft())
            self.update()
            return

        if self._press_heart(e):
            self.focus_active = False
            self.update()
            e.accept()
            return

        art_x, art_y = self._art_xy(e.position())
        life_hit = self._life_symbol_at(art_x, art_y)
        if life_hit is not None:
            name, row = life_hit
            offset_x, offset_y = self._renderer.life_symbol_offset(name)
            center_x = LIFE_MARK_CENTER_X + offset_x
            center_y = LIFE_MARK_CENTER_Y[row] + offset_y
            self._life_symbol_drag = (
                name, row, center_x - art_x, center_y - art_y)
            now = time.monotonic()
            self._renderer.begin_life_symbol_drag(name, now)
            self.focus_active = False
            self.update()
            return

        for row in range(2):
            for idx in range(8):
                if digit_box_rect(row, idx).contains(v):
                    if self.status == "computing":
                        return
                    self.focus_row, self.focus = row, idx
                    self.focus_active = True
                    self.update()
                    return
        self.focus_active = False
        self._drag = (
            "move", e.globalPosition().toPoint()
            - self.frameGeometry().topLeft())
        self.update()

    def mouseMoveEvent(self, e):
        pos = e.position().toPoint()
        self._track_pointer_position(pos)
        v = self._virt(pos)

        if self._pressed_control == "heart":
            if self._renderer.heart_exit_pending:
                inside = self._in_heart_tank(e.position())
            else:
                inside = self._renderer.heart_contains(
                    e.position().x(), e.position().y(), self.scale)
            if self.flame_flipped or not inside:
                self._renderer.cancel_heart_hold()
            self.update()
            return

        if self.flame_flipped and self._chisel_mode:
            if self._set_flame_hover(FLAME_DISPLAY_RECT.contains(v)):
                self.update()
            gesture = self._chisel_gesture
            if gesture and gesture.get("kind") == "erase":
                if not self._shift_active(e):
                    self._finish_chisel_gesture()
                    return
                current_art = self._art_xy(pos)
                self._erase_etch_segment(
                    gesture["last_art"], current_art)
                gesture["last_art"] = current_art
            if self._shift_active(e):
                self.update()
            # Window movement and freehand marking are both disabled while
            # chisel mode is active; only an explicit Shift eraser can drag.
            return

        if (self._flame_flip_pressed_at is not None
                and not FLAME_DISPLAY_RECT.contains(v)):
            self._flame_flip_pressed_at = None
            self.update()
        if self.flame_flipped:
            if (self._pressed_control == "flame"
                    and self._flame_pressed_at is not None
                    and not FLAME_DISPLAY_RECT.contains(v)):
                self._flame_pressed_at = None
                self._flame_press_cancelled = True
            if self._drag and self._drag[0] == "move":
                self.move(e.globalPosition().toPoint() - self._drag[1])
                return
            hf = FLAME_DISPLAY_RECT.contains(v)
            if self._set_flame_hover(hf):
                self.update()
            return
        if self._life_symbol_drag is not None:
            name, row, grab_x, grab_y = self._life_symbol_drag
            art_x, art_y = self._art_xy(e.position())
            self._renderer.drag_life_symbol(
                name,
                art_x + grab_x - LIFE_MARK_CENTER_X,
                art_y + grab_y - LIFE_MARK_CENTER_Y[row],
                time.monotonic(),
            )
            self.update()
            return
        if self._drag and self._drag[0] == "move":
            self.move(e.globalPosition().toPoint() - self._drag[1])
            return
        if (self._pressed_control == "flame"
                and self._flame_pressed_at is not None
                and not FLAME_DISPLAY_RECT.contains(v)):
            self._flame_pressed_at = None
            self._flame_press_cancelled = True
        hf = FLAME_DISPLAY_RECT.contains(v)
        if self._set_flame_hover(hf):
            self.update()

    def mouseReleaseEvent(self, e):
        if e.button() == Qt.RightButton:
            pos = e.position().toPoint()
            self._track_pointer_position(pos)
            v = self._virt(pos)
            over_flame = FLAME_DISPLAY_RECT.contains(v)
            if self.flame_flipped and self._chisel_mode:
                self._flame_flip_pressed_at = None
                self._flame_flip_hold_completed = False
                self._set_flame_hover(over_flame)
                self.update()
                return
            flip_completed = False
            if (self._flame_flip_pressed_at is not None and over_flame
                    and time.monotonic() - self._flame_flip_pressed_at
                    >= FLAME_FLIP_HOLD_SECONDS):
                self.flame_flipped = not self.flame_flipped
                flip_completed = True
            self._flame_flip_pressed_at = None
            self._flame_flip_hold_completed = False
            self._set_flame_hover(over_flame)
            if flip_completed and over_flame:
                self._flame_hover_entry_consumed = True
            self.update()
            return
        if e.button() != Qt.LeftButton:
            return

        pos = e.position().toPoint()
        self._track_pointer_position(pos)
        self._left_button_down = False
        if self._pressed_control == "heart":
            self._renderer.cancel_heart_hold()
            self._pressed_control = None
            self._drag = None
            self.update()
            e.accept()
            return
        if (self._flame_flip_pressed_at is not None
                or self._flame_flip_hold_completed):
            return

        if self.flame_flipped and self._chisel_mode:
            gesture = self._chisel_gesture
            if gesture and gesture.get("kind") == "erase":
                release_art = self._art_xy(pos)
                self._erase_etch_segment(
                    gesture["last_art"], release_art)
                self._finish_chisel_gesture()
            self.update()
            return

        if self._life_symbol_drag is not None:
            name, _, _, _ = self._life_symbol_drag
            self._renderer.release_life_symbol(name)
            self._life_symbol_drag = None
            self.update()
            return

        control = self._pressed_control
        self._pressed_control = None
        v = self._virt(pos)
        self._set_flame_hover(FLAME_DISPLAY_RECT.contains(v))

        if control == "flame":
            pressed_at = self._flame_pressed_at
            cancelled = self._flame_press_cancelled
            elapsed = (time.monotonic() - pressed_at
                       if pressed_at is not None else 0.0)
            self._flame_pressed_at = None
            self._flame_press_cancelled = False
            self._drag = None
            if not cancelled and self.hover_flame:
                if elapsed >= FLAME_HOLD_SECONDS:
                    self.close()
                    return
                if not self.flame_flipped:
                    self._calc()
            self.update()
            return

        self._flame_pressed_at = None
        self._flame_press_cancelled = False
        if self._drag and self._drag[0] == "move":
            self._snap_to_top(e.globalPosition().toPoint())
        self._drag = None
        self.update()

    def mouseDoubleClickEvent(self, e):
        pos = e.position().toPoint()
        self._track_pointer_position(pos)

        if e.button() == Qt.RightButton:
            if self.flame_flipped:
                self._toggle_chisel_mode()
                e.accept()
            else:
                super().mouseDoubleClickEvent(e)
            return

        if (e.button() == Qt.LeftButton
                and self.flame_flipped and self._chisel_mode):
            self._left_button_down = True
            self._pressed_control = None
            self._flame_pressed_at = None
            self._flame_press_cancelled = False
            self._drag = None
            self._life_symbol_drag = None
            self.focus_active = False
            self._begin_chisel_gesture(pos, self._shift_active(e))
            self.update()
            e.accept()
            return

        if e.button() == Qt.LeftButton and self._in_heart_tank(e.position()):
            self._drag = None
            # Qt delivers the second press as a double-click event rather than
            # mousePressEvent: count it once so rapid pokes remain responsive.
            if (not self.flame_flipped
                    and self._flame_flip_pressed_at is None
                    and not self._flame_flip_hold_completed):
                self._press_heart(e)
            self.update()
            e.accept()
            return

        if (self._shift_down
                or (e.modifiers() & Qt.ShiftModifier)
                or self._flame_flip_pressed_at is not None
                or self._flame_flip_hold_completed
                or e.button() != Qt.LeftButton
                or self._interactive_target_at(e.position())):
            super().mouseDoubleClickEvent(e)
            return

        if self._life_symbol_drag is not None:
            name, _, _, _ = self._life_symbol_drag
            self._renderer.release_life_symbol(name)
            self._life_symbol_drag = None
        self._pressed_control = None
        self._flame_pressed_at = None
        self._flame_press_cancelled = False
        self._drag = None
        self._toggle_pin()
        e.accept()

    def leaveEvent(self, e):
        self._renderer.cancel_heart_hold()
        eraser_cursor_was_visible = (
            self._pointer_inside and self.flame_flipped
            and self._chisel_mode and self._shift_down)
        self._pointer_inside = False
        if self._flame_flip_pressed_at is not None:
            self._flame_flip_pressed_at = None
        if (self._pressed_control == "flame"
                and self._flame_pressed_at is not None):
            self._flame_pressed_at = None
            self._flame_press_cancelled = True
        if (self._set_flame_hover(False) or eraser_cursor_was_visible):
            self.update()
        super().leaveEvent(e)

    def _snap_to_top(self, global_pos):
        screen = QGuiApplication.screenAt(global_pos)
        if screen is None:
            handle = self.windowHandle()
            screen = handle.screen() if handle is not None else None
        if screen is None:
            screen = QGuiApplication.primaryScreen()
        if screen is None:
            return

        screen_top = screen.geometry().top()
        if self.frameGeometry().top() <= screen_top + TOP_EDGE_SNAP_DISTANCE:
            self.move(self.x(), screen_top)
            self._renderer.reset_window_motion(self.frameGeometry().topLeft())

    def _step_scale(self, steps):
        target_index = max(
            0, min(len(ASSET_SCALE_ANCHORS) - 1, self.scale_index + steps))
        if target_index != self.scale_index:
            self.scale_index = target_index
            self._apply_scale()

    def wheelEvent(self, e):
        angle_delta = e.angleDelta().y()
        pixel_delta = e.pixelDelta().y()
        if angle_delta:
            total = self._wheel_angle_remainder + angle_delta
            steps = int(total / WHEEL_ANGLE_PER_NOTCH)
            self._wheel_angle_remainder = total - steps * WHEEL_ANGLE_PER_NOTCH
        elif pixel_delta:
            total = self._wheel_pixel_remainder + pixel_delta
            steps = int(total / TRACKPAD_PIXELS_PER_NOTCH)
            self._wheel_pixel_remainder = total - steps * TRACKPAD_PIXELS_PER_NOTCH
        else:
            super().wheelEvent(e)
            return

        if steps:
            self._step_scale(steps)
        e.accept()

    def showEvent(self, e):
        super().showEvent(e)
        if not self._effect_timer.isActive():
            self._renderer.reset_clock(self.frameGeometry().topLeft())
            self._effect_timer.start(16)

    def hideEvent(self, e):
        self._renderer.cancel_heart_hold()
        if self._pressed_control == "heart":
            self._pressed_control = None
        if self._effect_timer.isActive():
            self._effect_timer.stop()
        super().hideEvent(e)

    def closeEvent(self, e):
        if self._thread is not None:
            if self._thread.isRunning():
                if not self._close_pending:
                    self._close_pending = True
                    self.setEnabled(False)
                    if self._effect_timer.isActive():
                        self._effect_timer.stop()
                e.ignore()
                return
            self._thread.wait()

        self._finish_chisel_gesture()
        self._remember_end_date()
        self._settings.setValue("window_scale", self.scale)
        self._settings.sync()
        if self._effect_timer.isActive():
            self._effect_timer.stop()
        e.accept()
