# -*- coding: utf-8 -*-

import random
from pathlib import Path

from PySide6.QtCore import QRectF
from PySide6.QtGui import QColor, QImage, QPainter

from .layout import (
    ART_TO_VIEW,
    FLAME_DISPLAY_RECT,
    FLAME_HEIGHT_ART,
    FLAME_WIDTH_ART,
)

FRAME_WIDTH = 44
FRAME_HEIGHT = 80
FRAME_COLUMNS = 8
FRAME_COUNT = 8  # First repeated loop segment from the uploaded GIF.
FRAME_DURATION = 0.1  # Keep the source GIF's 100 ms frame timing.
HOVER_ATLAS_ROWS = (FRAME_COUNT + FRAME_COLUMNS - 1) // FRAME_COLUMNS
NORMAL_OPACITY = 1.0
HOVER_HALO_OPACITY = 0.12

# Left-click and right-click holds both use two seconds, but have different effects.
FLAME_HOLD_SECONDS = 2.0
FLAME_FLIP_HOLD_SECONDS = 2.0
FLAME_COLOR_TRANSITION_SECONDS = 0.3  # Orange/blue hover transition.
CHISEL_FLAME_TRANSITION_SECONDS = 0.3
FLAME_HOLD_FINAL_OPACITY = 0.2

# Offset each orange pixel's RGB channels toward a vivid ghost green, without
# repainting or smoothing the original flame texture.
FLAME_GREEN_RGB_OFFSET = (-100, 90, 5)
_FLAME_PALETTES = ("orange", "blue", "green")


class FlameEffect:
    """Animate the source flame and blend smoothly between its color palettes."""

    def __init__(self, seed=12):
        atlas_path = Path(__file__).resolve().parent / "assets" / "flame_atlas.png"
        self.atlas = QImage(str(atlas_path))
        required_rows = HOVER_ATLAS_ROWS * 2
        if (self.atlas.isNull()
                or self.atlas.width() < FRAME_COLUMNS * FRAME_WIDTH
                or self.atlas.height() < required_rows * FRAME_HEIGHT):
            self.atlas = QImage()
            self.frame_count = 0
            self._palette_frames = {}
        else:
            self.frame_count = FRAME_COUNT
            self._palette_frames = self._build_palette_frames()

        self.frame_index = random.Random(seed).randrange(
            max(1, self.frame_count))
        self._frame_elapsed = 0.0
        self._color_target = "orange"
        self._color_weights = {name: float(name == "orange")
                               for name in _FLAME_PALETTES}
        self._color_transition_start = dict(self._color_weights)
        self._color_transition_duration = FLAME_COLOR_TRANSITION_SECONDS
        self._color_transition_linear = False
        self._color_transition_elapsed = FLAME_COLOR_TRANSITION_SECONDS
        self._chisel_opacity = 1.0
        self._chisel_opacity_start = 1.0
        self._chisel_opacity_target = 1.0
        self._chisel_opacity_elapsed = CHISEL_FLAME_TRANSITION_SECONDS
        self._flip_color_active = False
        self._last_flip_progress = None

    @property
    def is_fully_transparent(self):
        return self._chisel_opacity <= 0.0

    def _advance_chisel_opacity(self, dt, chisel_mode):
        target = 0.0 if chisel_mode else 1.0
        if target != self._chisel_opacity_target:
            self._chisel_opacity_start = self._chisel_opacity
            self._chisel_opacity_target = target
            self._chisel_opacity_elapsed = 0.0

        duration = CHISEL_FLAME_TRANSITION_SECONDS
        if duration <= 0.0:
            self._chisel_opacity = target
            self._chisel_opacity_elapsed = duration
            return
        if self._chisel_opacity_elapsed >= duration:
            self._chisel_opacity = target
            return

        self._chisel_opacity_elapsed = min(
            duration, self._chisel_opacity_elapsed + dt)
        progress = self._chisel_opacity_elapsed / duration
        eased = progress * progress * (3.0 - 2.0 * progress)
        self._chisel_opacity = (
            self._chisel_opacity_start
            + (target - self._chisel_opacity_start) * eased)
        if progress >= 1.0:
            self._chisel_opacity = target

    @staticmethod
    def _shift_rgb(source):
        """Apply one clamped RGB offset to opaque pixels, retaining alpha and shape."""
        shifted = source.copy()
        offset_r, offset_g, offset_b = FLAME_GREEN_RGB_OFFSET
        color_cache = {}
        for y in range(source.height()):
            for x in range(source.width()):
                original = source.pixelColor(x, y)
                alpha = original.alpha()
                if not alpha:
                    continue
                key = (original.red(), original.green(), original.blue(), alpha)
                color = color_cache.get(key)
                if color is None:
                    color = QColor(
                        max(0, min(255, key[0] + offset_r)),
                        max(0, min(255, key[1] + offset_g)),
                        max(0, min(255, key[2] + offset_b)),
                        alpha,
                    )
                    color_cache[key] = color
                shifted.setPixelColor(x, y, color)
        return shifted

    def _build_palette_frames(self):
        frames = {name: [] for name in _FLAME_PALETTES}
        blue_row_y = HOVER_ATLAS_ROWS * FRAME_HEIGHT
        for index in range(self.frame_count):
            frame_x = (index % FRAME_COLUMNS) * FRAME_WIDTH
            frame_y = (index // FRAME_COLUMNS) * FRAME_HEIGHT
            orange = self.atlas.copy(
                frame_x, frame_y, FRAME_WIDTH, FRAME_HEIGHT)
            blue = self.atlas.copy(
                frame_x, blue_row_y + frame_y, FRAME_WIDTH, FRAME_HEIGHT)
            frames["orange"].append(orange)
            frames["blue"].append(blue)
            frames["green"].append(self._shift_rgb(orange))
        return frames

    def _set_color_target(self, target, duration, linear):
        if target not in _FLAME_PALETTES or target == self._color_target:
            return
        self._color_transition_start = dict(self._color_weights)
        self._color_target = target
        self._color_transition_duration = max(0.0, float(duration))
        self._color_transition_linear = bool(linear)
        self._color_transition_elapsed = 0.0
        if self._color_transition_duration == 0.0:
            self._color_weights = {
                name: float(name == self._color_target)
                for name in _FLAME_PALETTES
            }

    def _advance_color_transition(self, dt):
        duration = self._color_transition_duration
        if (duration <= 0.0 or self._color_transition_elapsed >= duration):
            return
        self._color_transition_elapsed = min(
            duration, self._color_transition_elapsed + dt)
        linear = self._color_transition_elapsed / duration
        mix = linear if self._color_transition_linear else (
            linear * linear * (3.0 - 2.0 * linear))
        self._color_weights = {
            name: self._color_transition_start[name] * (1.0 - mix)
            + (1.0 if name == self._color_target else 0.0) * mix
            for name in _FLAME_PALETTES
        }
        if linear >= 1.0:
            self._color_weights = {
                name: float(name == self._color_target)
                for name in _FLAME_PALETTES
            }

    def update(self, dt_seconds, color_target=None,
               color_transition_seconds=FLAME_COLOR_TRANSITION_SECONDS,
               color_transition_linear=False, flip_progress=None,
               advance_animation=True, chisel_mode=False):
        if color_target is not None:
            self._set_color_target(
                color_target, color_transition_seconds,
                color_transition_linear)

        dt = min(0.1, max(0.0, float(dt_seconds)))
        self._advance_chisel_opacity(dt, chisel_mode)
        if not self.frame_count:
            return

        if advance_animation and not self.is_fully_transparent:
            self._frame_elapsed += dt
            steps = int(self._frame_elapsed / FRAME_DURATION)
            if steps:
                self._frame_elapsed -= steps * FRAME_DURATION
                self.frame_index = (self.frame_index + steps) % self.frame_count

        if flip_progress is not None:
            progress = min(1.0, max(0.0, float(flip_progress)))
            new_flip_hold = (
                not self._flip_color_active
                or (self._last_flip_progress is not None
                    and progress < self._last_flip_progress)
            )
            if new_flip_hold:
                self._color_transition_start = dict(self._color_weights)
                self._color_transition_duration = max(
                    0.0, float(color_transition_seconds))
                self._color_transition_linear = True
            self._flip_color_active = True
            self._last_flip_progress = progress
            target_weights = {
                name: float(name == self._color_target)
                for name in _FLAME_PALETTES
            }
            self._color_weights = {
                name: self._color_transition_start[name] * (1.0 - progress)
                + target_weights[name] * progress
                for name in _FLAME_PALETTES
            }
            self._color_transition_elapsed = (
                self._color_transition_duration * progress)
            if progress >= 1.0:
                self._color_weights = target_weights
                self._color_transition_elapsed = self._color_transition_duration
        else:
            self._flip_color_active = False
            self._last_flip_progress = None
            self._advance_color_transition(dt)

    def target_rect(self, scale):
        factor = ART_TO_VIEW * scale
        return QRectF(
            FLAME_DISPLAY_RECT.x() * factor,
            FLAME_DISPLAY_RECT.y() * factor,
            FLAME_WIDTH_ART * factor,
            FLAME_HEIGHT_ART * factor,
        )

    @staticmethod
    def _hold_progress(hold_elapsed):
        if hold_elapsed is None or FLAME_HOLD_SECONDS <= 0:
            return 0.0
        return min(1.0, max(0.0, float(hold_elapsed) / FLAME_HOLD_SECONDS))

    def _blended_frame(self):
        image = QImage(
            FRAME_WIDTH, FRAME_HEIGHT, QImage.Format_ARGB32_Premultiplied)
        image.fill(QColor(0, 0, 0, 0))
        painter = QPainter(image)
        painter.setCompositionMode(QPainter.CompositionMode_Plus)
        for palette in _FLAME_PALETTES:
            weight = self._color_weights[palette]
            if weight <= 0.0:
                continue
            painter.setOpacity(weight)
            painter.drawImage(
                0, 0, self._palette_frames[palette][self.frame_index])
        painter.end()
        return image

    def draw(self, painter, target, hovered=False, hold_elapsed=None):
        """Draw the crisp flame with a smooth palette blend and close-hold fade."""
        target = QRectF(target)
        if (target.isEmpty() or not self.frame_count
                or self.is_fully_transparent):
            return

        progress = self._hold_progress(hold_elapsed)
        hold_opacity = 1.0 - (1.0 - FLAME_HOLD_FINAL_OPACITY) * progress
        combined_opacity = hold_opacity * self._chisel_opacity
        draw_target = target
        frame = self._blended_frame()

        painter.save()
        # No resizing during the hold: preserve the original pixel edges.
        painter.setRenderHint(QPainter.SmoothPixmapTransform, False)
        painter.setOpacity(NORMAL_OPACITY * combined_opacity)
        if hovered:
            pad_x = draw_target.width() / FLAME_WIDTH_ART
            pad_y = draw_target.height() / FLAME_HEIGHT_ART
            halo = QRectF(
                draw_target.x() - pad_x,
                draw_target.y() - pad_y,
                draw_target.width() + 2 * pad_x,
                draw_target.height() + 2 * pad_y,
            )
            painter.setOpacity(HOVER_HALO_OPACITY * combined_opacity)
            painter.drawImage(halo, frame)
            painter.setOpacity(NORMAL_OPACITY * combined_opacity)
        painter.drawImage(draw_target, frame)
        painter.restore()
