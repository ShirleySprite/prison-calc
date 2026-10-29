# -*- coding: utf-8 -*-

import math
import time

from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import (
    QColor, QImage, QLinearGradient, QPainter, QPainterPath, QPixmap,
)

from .background import APP_CORNER_RADIUS, BORDER_WIDTH_PX, C_VOID, paint_background
from .etch_canvas import draw_eraser_cursor, draw_etch_canvas
from .input_fields import draw_date_cells, draw_date_text
from .layout import (
    ART_TO_VIEW, RESULT_CENTER_Y_OFFSET, RESULT_RECT, VH, VW,
)
from .flame import FLAME_COLOR_TRANSITION_SECONDS, FlameEffect
from .icons import draw_life_symbols, draw_pinned_indicator
from .particles import (
    PARTICLE_SAFE_RECT, ParticleSystem, draw_particles,
)
from .life_symbol_spring import LifeSymbolSpring
from .heart_loading import (
    HEART_DISPLAY_WIDTH, HEART_DISPLAY_HEIGHT, HEART_CELL_SIZE,
    HEART_PIXEL_RGB, RESULT_CROSSFADE_SECONDS,
    draw_heart_loading,
)
from .heart_motion import HeartMotion, heart_tank_rect
from .heart_hold import HEART_GAME_HOLD_SECONDS, HeartHold
from .text import ERROR_RESULT_TEXT, RAINBOW_SECONDS_PER_DIGIT, paint_result_layer

PAINT_RATE = 60.0
WINDOW_VELOCITY_FILTER_SECONDS = 0.045
WINDOW_SPEED_LIMIT = 1200.0


def _paint_foreground(state, width, height, scale, dpr):
    image = QImage(width, height, QImage.Format_ARGB32_Premultiplied)
    image.fill(C_VOID)
    painter = QPainter(image)

    draw_date_text(painter, state, width, height, scale, dpr)

    painter.end()
    return image


def _paint_particle_margin_feather(painter, scale_x, scale_y):
    """Fade the black inset mask inward over the same physical width as the edge."""
    left, top, right, bottom = PARTICLE_SAFE_RECT
    x0, y0 = left * scale_x, top * scale_y
    x1, y1 = right * scale_x, bottom * scale_y
    feather = float(BORDER_WIDTH_PX)
    opaque_black = QColor(0, 0, 0, 255)
    transparent_black = QColor(0, 0, 0, 0)

    # The blank margin side is fully black; the mask fades to clear toward the
    # particle field. Each band uses the same device-pixel thickness as the
    # app's existing outer feather. The outer rounded clip remains in force.
    gradients = (
        (QRectF(x0, y0, x1 - x0, feather),
         QLinearGradient(x0, y0, x0, y0 + feather)),
        (QRectF(x0, y1 - feather, x1 - x0, feather),
         QLinearGradient(x0, y1, x0, y1 - feather)),
        (QRectF(x0, y0, feather, y1 - y0),
         QLinearGradient(x0, y0, x0 + feather, y0)),
        (QRectF(x1 - feather, y0, feather, y1 - y0),
         QLinearGradient(x1, y0, x1 - feather, y0)),
    )
    for rect, gradient in gradients:
        gradient.setColorAt(0.0, opaque_black)
        gradient.setColorAt(1.0, transparent_black)
        painter.fillRect(rect, gradient)


class Renderer:
    """Coordinate the background, particle, input, text, and icon painters."""

    def __init__(self):
        self._particles = ParticleSystem()
        self._flame = FlameEffect(seed=12)
        self._life_springs = {
            "cross": LifeSymbolSpring(),
            "star": LifeSymbolSpring(),
        }
        self._paint_credit = 0.0
        self._last_time = time.perf_counter()
        self._last_window_pos = None
        self._window_velocity = (0.0, 0.0)
        self._rainbow_phase = 0.0
        self._heart_motion = HeartMotion(HEART_DISPLAY_WIDTH, HEART_DISPLAY_HEIGHT)
        self._heart_hold = HeartHold()
        self._heart_game_active = False
        self._heart_hold_mode = None
        self._heart_exit_start = None
        self._last_status = "idle"
        self._result_opacity = 0.0
        self._result_display_status = None
        self._result_display_value = None
        self._background_key = None
        self._foreground_key = None
        self._result_key = None
        self._background_pm = None
        self._foreground_pm = None
        self._result_pm = None

    def invalidate(self):
        self._foreground_key = None
        self._result_key = None

    def reset_animation(self):
        self._rainbow_phase = 0.0
        self._result_key = None

    def life_symbol_offset(self, name):
        return self._life_springs[name].offset

    def life_symbol_offsets(self):
        return {name: spring.offset
                for name, spring in self._life_springs.items()}

    def begin_life_symbol_drag(self, name, now):
        self._life_springs[name].begin_drag(now)

    def drag_life_symbol(self, name, offset_x, offset_y, now):
        self._life_springs[name].drag_to(offset_x, offset_y, now)

    def release_life_symbol(self, name):
        self._life_springs[name].release()

    def heart_contains(self, logical_x, logical_y, scale):
        """Hit-test stable heart pixels; tremor never jitters the hold target."""
        if self._result_opacity >= 1.0:
            return False
        dx, dy = self._heart_motion.offset
        center_x = (RESULT_RECT.x() + RESULT_RECT.width() / 2 + dx) * scale
        center_y = (RESULT_RECT.y() + RESULT_RECT.height() / 2
                    + RESULT_CENTER_Y_OFFSET + dy) * scale
        cell = HEART_CELL_SIZE * scale
        left = round(center_x - HEART_DISPLAY_WIDTH * scale / 2)
        top = round(center_y - HEART_DISPLAY_HEIGHT * scale / 2)
        for x, y, *_ in HEART_PIXEL_RGB:
            if (left + round(x * cell) <= logical_x < left + round((x + 1) * cell)
                    and top + round(y * cell) <= logical_y < top + round((y + 1) * cell)):
                return True
        return False

    def begin_heart_hold(self, logical_x, logical_y, scale, status):
        if (status != "idle" or self._heart_motion.active
                or self._result_opacity > 0.0
                or not self.heart_contains(logical_x, logical_y, scale)):
            return False
        self._heart_hold_mode = "enter"
        self._heart_hold.begin()
        return True

    @property
    def heart_exit_pending(self):
        return self._heart_hold.active and self._heart_hold_mode == "exit"

    def begin_heart_exit(self, status):
        if (status != "idle" or not self._heart_game_active
                or not self._heart_motion.active):
            return False
        self._heart_exit_start = (self._heart_motion.x, self._heart_motion.y)
        self._heart_motion.sleeping = False
        self._heart_hold_mode = "exit"
        self._heart_hold.begin()
        return True

    def cancel_heart_hold(self):
        # Return motion stops where it is; the retained physical velocity
        # resumes there if an exit hold is released/cancelled early.
        self._heart_hold.cancel()
        self._heart_hold_mode = None
        self._heart_exit_start = None

    def poke_heart(self, logical_x, logical_y, scale):
        if (not self._heart_motion.active
                or not self.heart_contains(logical_x, logical_y, scale)):
            return False
        return self._heart_motion.poke(logical_x / scale, logical_y / scale)

    def reset_window_motion(self, window_pos):
        if window_pos is None:
            self._last_window_pos = None
        else:
            self._last_window_pos = (
                float(window_pos.x()), float(window_pos.y()))
        self._window_velocity = (0.0, 0.0)

    def reset_clock(self, window_pos=None):
        self._last_time = time.perf_counter()
        self._paint_credit = 0.0
        self.reset_window_motion(window_pos)

    def _sample_window_velocity(self, window_pos, elapsed, dt):
        if window_pos is None:
            return self._window_velocity
        current = (float(window_pos.x()), float(window_pos.y()))
        if self._last_window_pos is None:
            self._last_window_pos = current
            self._window_velocity = (0.0, 0.0)
            return self._window_velocity

        sample_dt = max(float(elapsed), 1e-4)
        dx = current[0] - self._last_window_pos[0]
        dy = current[1] - self._last_window_pos[1]
        raw_vx, raw_vy = dx / sample_dt, dy / sample_dt
        raw_speed = math.hypot(raw_vx, raw_vy)
        if raw_speed > WINDOW_SPEED_LIMIT:
            limit = WINDOW_SPEED_LIMIT / raw_speed
            raw_vx *= limit
            raw_vy *= limit

        old_vx, old_vy = self._window_velocity
        blend = 1.0 - math.exp(-dt / WINDOW_VELOCITY_FILTER_SECONDS)
        self._window_velocity = (
            old_vx + (raw_vx - old_vx) * blend,
            old_vy + (raw_vy - old_vy) * blend,
        )
        self._last_window_pos = current
        return self._window_velocity

    def tick(self, result=None, window_pos=None, scale=1.0,
             flame_palette="orange",
             flame_transition_seconds=FLAME_COLOR_TRANSITION_SECONDS,
             flame_transition_linear=False, flame_flip_progress=None,
             chisel_mode=False, status=None, dpr=1.0):
        """Advance visible effects, heart motion, result cross-fade, and physics."""
        self._heart_motion.set_tank_rect(heart_tank_rect(
            BORDER_WIDTH_PX / max(0.001, scale * dpr), PARTICLE_SAFE_RECT))
        now = time.perf_counter()
        elapsed = max(now - self._last_time, 0.0)
        dt = min(elapsed, 0.05)
        self._last_time = now
        if not dt:
            return False

        visual_status = status
        if visual_status is None:
            visual_status = (
                "error" if isinstance(result, str)
                and result == ERROR_RESULT_TEXT
                else "done" if result is not None else "idle")
        if visual_status != "idle":
            self.cancel_heart_hold()
        if visual_status in ("done", "error"):
            self._heart_game_active = False
        if visual_status == "computing" and self._last_status != "computing":
            # Continue an already-running idle game without teleporting or
            # resetting its velocity. Ordinary calculations still release it.
            if not self._heart_motion.active:
                self._heart_motion.launch()
        elif visual_status == "idle":
            if self.heart_exit_pending:
                progress = min(1.0, (self._heart_hold.elapsed + elapsed)
                               / HEART_GAME_HOLD_SECONDS)
                blend = progress * progress * (3.0 - 2.0 * progress)
                start_x, start_y = self._heart_exit_start
                center_x = RESULT_RECT.x() + RESULT_RECT.width() / 2
                center_y = (RESULT_RECT.y() + RESULT_RECT.height() / 2
                            + RESULT_CENTER_Y_OFFSET)
                self._heart_motion.x = start_x + (center_x - start_x) * blend
                self._heart_motion.y = start_y + (center_y - start_y) * blend
                if self._heart_hold.advance(elapsed):
                    self._heart_game_active = False
                    self._heart_motion.reset()
                    self.cancel_heart_hold()
            elif not self._heart_game_active:
                self._heart_motion.reset()
                if self._heart_hold.advance(elapsed):
                    self._heart_game_active = True
                    self._heart_motion.launch()
                    self.cancel_heart_hold()
        self._last_status = visual_status

        result_target = (
            1.0 if visual_status in ("done", "error") else 0.0)
        # Move throughout the outgoing crossfade, including its final visible
        # fraction of a tick. Never update the heart's physics after it vanishes.
        if self._heart_motion.active and not self.heart_exit_pending:
            visible_dt = dt
            if result_target == 1.0:
                visible_dt = min(
                    dt, (1.0 - self._result_opacity) * RESULT_CROSSFADE_SECONDS)
            if visible_dt > 0.0:
                self._heart_motion.advance(visible_dt)

        opacity_step = dt / RESULT_CROSSFADE_SECONDS
        if result_target > self._result_opacity:
            self._result_opacity = min(
                result_target, self._result_opacity + opacity_step)
        else:
            self._result_opacity = max(
                result_target, self._result_opacity - opacity_step)

        if self._result_opacity >= 1.0:
            self._heart_motion.stop()

        if visual_status in ("done", "error"):
            self._result_display_status = visual_status
            self._result_display_value = result
        elif self._result_opacity <= 0.0:
            self._result_display_status = None
            self._result_display_value = None

        window_velocity = self._sample_window_velocity(window_pos, elapsed, dt)
        particle_window_pos = window_pos if window_pos is not None else (0, 0)
        self._particles.advance(
            dt, window_velocity, particle_window_pos, scale)
        flame_was_hidden = (
            chisel_mode and self._flame.is_fully_transparent)
        self._flame.update(
            dt, color_target=flame_palette,
            color_transition_seconds=flame_transition_seconds,
            color_transition_linear=flame_transition_linear,
            flip_progress=flame_flip_progress,
            chisel_mode=chisel_mode,
        )
        for spring in self._life_springs.values():
            spring.advance(dt)
        if result is not None:
            duration = RAINBOW_SECONDS_PER_DIGIT * max(1, len(str(result)))
            self._rainbow_phase = (self._rainbow_phase + dt / duration) % 1.0

        flame_hidden = chisel_mode and self._flame.is_fully_transparent
        if flame_hidden:
            self._paint_credit = 0.0
            # Repaint once at full transparency, then let input events paint
            # the static back face without a continuous animation repaint.
            return not flame_was_hidden

        self._paint_credit += dt * PAINT_RATE
        if self._paint_credit >= 1.0:
            self._paint_credit -= 1.0
            return True
        return False

    def paint(self, widget, state, scale):
        dpr = widget.devicePixelRatioF()
        pixel_w = max(1, round(widget.width() * dpr))
        pixel_h = max(1, round(widget.height() * dpr))
        pixel_scale_x = pixel_w / VW
        pixel_scale_y = pixel_h / VH
        back_face = state.get("flame_flipped", False)

        background_key = (pixel_w, pixel_h)
        if background_key != self._background_key:
            self._background_pm = QPixmap.fromImage(
                paint_background(pixel_w, pixel_h))
            self._background_key = background_key

        if not back_face:
            foreground_key = (
                state["start"], state["end"], state["focus_row"],
                state["focus"], state.get("focus_active", True),
                scale, pixel_w, pixel_h, dpr,
            )
            if foreground_key != self._foreground_key:
                self._foreground_pm = QPixmap.fromImage(
                    _paint_foreground(state, pixel_w, pixel_h, scale, dpr))
                self._foreground_key = foreground_key

            result_size = (
                max(1, round(RESULT_RECT.width() * pixel_scale_x)),
                max(1, round(RESULT_RECT.height() * pixel_scale_y)),
            )
            display_status = self._result_display_status or "idle"
            result_key = (
                display_status, self._result_display_value,
                round(self._rainbow_phase, 5)
                if display_status in ("done", "error") else None,
                scale, result_size, dpr,
            )
            if result_key != self._result_key:
                result_state = {
                    "status": display_status,
                    "result": self._result_display_value,
                    "rainbow_phase": self._rainbow_phase,
                }
                self._result_pm = QPixmap.fromImage(paint_result_layer(
                    result_state, result_size[0], result_size[1], scale, dpr))
                self._result_key = result_key

        painter = QPainter(widget)
        painter.setRenderHint(QPainter.SmoothPixmapTransform, False)
        # The card/background is common to both sides and stays in place.
        painter.drawPixmap(widget.rect(), self._background_pm)

        if back_face:
            draw_etch_canvas(
                painter, state.get("etch_canvas"), scale)

        if not back_face:
            painter.save()
            painter.setRenderHint(QPainter.Antialiasing, True)
            painter.scale(1.0 / dpr, 1.0 / dpr)
            border = BORDER_WIDTH_PX
            radius_x = APP_CORNER_RADIUS * ART_TO_VIEW * pixel_scale_x
            radius_y = APP_CORNER_RADIUS * ART_TO_VIEW * pixel_scale_y
            clip = QPainterPath()
            clip.addRoundedRect(
                QRectF(border, border, pixel_w - 2 * border,
                       pixel_h - 2 * border),
                max(0.0, radius_x - border), max(0.0, radius_y - border))
            painter.setClipPath(clip)
            safe_left, safe_top, safe_right, safe_bottom = PARTICLE_SAFE_RECT
            painter.setClipRect(
                QRectF(
                    safe_left * pixel_scale_x,
                    safe_top * pixel_scale_y,
                    (safe_right - safe_left) * pixel_scale_x,
                    (safe_bottom - safe_top) * pixel_scale_y,
                ),
                Qt.ClipOperation.IntersectClip,
            )
            draw_particles(
                painter,
                self._particles.snapshot(
                    widget.frameGeometry().topLeft(), scale),
                pixel_scale_x, pixel_scale_y)
            _paint_particle_margin_feather(
                painter, pixel_scale_x, pixel_scale_y)
            painter.restore()

            draw_date_cells(painter, state, scale)
            painter.drawPixmap(widget.rect(), self._foreground_pm)
            painter.save()
            painter.scale(1.0 / dpr, 1.0 / dpr)
            draw_life_symbols(
                painter, pixel_w, pixel_h, scale, dpr,
                offsets=self.life_symbol_offsets())
            painter.restore()

        # The pin indicator remains visible on either face. Chisel mode hides
        # the flame while preserving its animation state for when it returns.
        if state.get("pinned", False):
            painter.save()
            painter.scale(1.0 / dpr, 1.0 / dpr)
            draw_pinned_indicator(painter, pixel_w, pixel_h, scale, dpr)
            painter.restore()

        self._flame.draw(
            painter, self._flame.target_rect(scale),
            hovered=state.get("hover_flame", False),
            hold_elapsed=state.get("flame_hold_elapsed"),
        )

        if not back_face:
            result_center_x = (
                RESULT_RECT.x() + RESULT_RECT.width() / 2) * scale
            result_center_y = (
                RESULT_RECT.y() + RESULT_RECT.height() / 2
                + RESULT_CENTER_Y_OFFSET) * scale
            heart_dx, heart_dy = self._heart_motion.offset
            # Entry trembles in place; exit only returns smoothly to center.
            if not self.heart_exit_pending:
                tremor_x, tremor_y = self._heart_hold.offset
                heart_dx += tremor_x
                heart_dy += tremor_y
            draw_heart_loading(
                painter, result_center_x + heart_dx * scale,
                result_center_y + heart_dy * scale, scale,
                opacity=1.0 - self._result_opacity,
            )
            if self._result_opacity > 0.0 and self._result_pm is not None:
                result_rect = QRectF(
                    RESULT_RECT.x() * scale, RESULT_RECT.y() * scale,
                    RESULT_RECT.width() * scale,
                    RESULT_RECT.height() * scale)
                painter.save()
                painter.setOpacity(self._result_opacity)
                painter.drawPixmap(
                    result_rect, self._result_pm,
                    QRectF(self._result_pm.rect()),
                )
                painter.restore()

        if state.get("eraser_cursor_visible"):
            draw_eraser_cursor(
                painter, state.get("eraser_cursor_view"), scale)
        painter.end()
