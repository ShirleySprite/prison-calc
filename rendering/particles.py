# -*- coding: utf-8 -*-

import colorsys
import math
import random
from functools import lru_cache

from PySide6.QtCore import QRectF
from PySide6.QtGui import QColor, QImage, QPainter

from .background import C_BG
from .layout import ART_TO_VIEW, VW, VH

# Sampled from the reference image's blue/cyan family: hues span deep cobalt
# through azure into cyan, with saturation and value varied independently.
PARTICLE_HUE_MIN_DEG = 187.0
PARTICLE_HUE_MODE_DEG = 202.0
PARTICLE_HUE_MAX_DEG = 214.0
PARTICLE_SATURATION_RANGE = (0.82, 1.0)
PARTICLE_VALUE_RANGE = (0.68, 1.0)
PARTICLE_VALUE_MODE = 0.90
PARTICLE_SIZE = 2 * ART_TO_VIEW
# Keep the random 40%-100% spread while raising the base so its mean matches
# the former fixed nominal length rather than shrinking to 70% of it.
TRAIL_LENGTH_REFERENCE_VIEW = 4 * (3 * ART_TO_VIEW)
TRAIL_LENGTH_FACTOR_RANGE = (0.4, 1.0)
TRAIL_LENGTH_MEAN_FACTOR = sum(TRAIL_LENGTH_FACTOR_RANGE) / 2.0
TRAIL_LENGTH_VIEW = TRAIL_LENGTH_REFERENCE_VIEW / TRAIL_LENGTH_MEAN_FACTOR
TRAIL_FADE_RATE_FACTOR = 0.56
PARTICLE_BEAD_SPACING_VIEW = PARTICLE_SIZE * 0.9
MAX_TRAIL_HISTORY = 64
# The existing path buffer already caps history at 64 samples; matching that
# as a bead ceiling keeps even unusually stretched trails bounded.
MAX_PARTICLE_BEADS = MAX_TRAIL_HISTORY
PARTICLE_STAR_SIZE = 5
# Same 5x5 pixel-art silhouette as the back engraving, with a softly brighter
# middle and core. Each bead is rendered from one cached sprite image.
PARTICLE_STAR_PIXELS = (
    (2, 0, 0.45),
    (1, 1, 0.45), (2, 1, 0.72),
    (3, 1, 0.45),
    (0, 2, 0.45), (1, 2, 0.72), (2, 2, 1.0),
    (3, 2, 0.72), (4, 2, 0.45),
    (1, 3, 0.45), (2, 3, 0.72), (3, 3, 0.45),
    (2, 4, 0.45),
)
PARTICLE_SPEED = 0.5
PARTICLE_START_Y = 14.0 * ART_TO_VIEW
PARTICLE_END_Y = VH - 27 * ART_TO_VIEW
PARTICLE_LEFT = 8 * ART_TO_VIEW
PARTICLE_RIGHT = VW - PARTICLE_SIZE - 8 * ART_TO_VIEW

# Preserve the former visible particle bounds as a fixed inset safety region.
# Right/bottom are exclusive edges including the full head sprite.
PARTICLE_SAFE_LEFT = PARTICLE_LEFT
PARTICLE_SAFE_TOP = PARTICLE_START_Y
PARTICLE_SAFE_RIGHT = PARTICLE_RIGHT + PARTICLE_SIZE
PARTICLE_SAFE_BOTTOM = PARTICLE_END_Y + PARTICLE_SIZE
PARTICLE_SAFE_RECT = (
    PARTICLE_SAFE_LEFT, PARTICLE_SAFE_TOP,
    PARTICLE_SAFE_RIGHT, PARTICLE_SAFE_BOTTOM,
)

# Keep the three-width field; this trial is 0.8x the previous 0.8x density.
BASE_PARTICLE_RATE = 37.5
PARTICLE_FIELD_WIDTH_MULTIPLIER = 3.0
PREVIOUS_DENSITY_MULTIPLIER = 0.8
DENSITY_STEP_MULTIPLIER = 0.8
PARTICLE_DENSITY_MULTIPLIER = (
    PREVIOUS_DENSITY_MULTIPLIER * DENSITY_STEP_MULTIPLIER)
PARTICLE_RATE = (
    BASE_PARTICLE_RATE
    * PARTICLE_FIELD_WIDTH_MULTIPLIER
    * PARTICLE_DENSITY_MULTIPLIER
)
# Preserve the existing fade curve for particle heads.
PARTICLE_FADE_SPEED_MULTIPLIER = 1.2

# Effective gravity is expressed in view-units/s^2, then converted to logical
# screen pixels at spawn. Drag coefficients are derived from the old terminal
# fall speeds, so still-window motion remains exactly the familiar rain speed.
GRAVITY_VIEW = 900.0
MAX_PHYSICS_STEP = 1.0 / 480.0


def random_particle_color(rng):
    """Choose a blue/cyan source color with varied hue, saturation, and value."""
    hue = rng.triangular(
        PARTICLE_HUE_MIN_DEG,
        PARTICLE_HUE_MAX_DEG,
        PARTICLE_HUE_MODE_DEG,
    ) / 360.0
    saturation = rng.uniform(*PARTICLE_SATURATION_RANGE)
    value = rng.triangular(
        PARTICLE_VALUE_RANGE[0],
        PARTICLE_VALUE_RANGE[1],
        PARTICLE_VALUE_MODE,
    )
    red, green, blue = colorsys.hsv_to_rgb(hue, saturation, value)
    return QColor(round(red * 255), round(green * 255), round(blue * 255))


@lru_cache(maxsize=512)
def _particle_star_sprite(red, green, blue):
    """Cache a tiny pre-tinted 5x5 engraving-shaped bead sprite."""
    image = QImage(
        PARTICLE_STAR_SIZE, PARTICLE_STAR_SIZE,
        QImage.Format_ARGB32_Premultiplied,
    )
    image.fill(0)
    for x, y, weight in PARTICLE_STAR_PIXELS:
        alpha = round(255 * weight)
        red_p = (int(red) * alpha + 127) // 255
        green_p = (int(green) * alpha + 127) // 255
        blue_p = (int(blue) * alpha + 127) // 255
        image.setPixel(
            x, y,
            (alpha << 24) | (red_p << 16) | (green_p << 8) | blue_p,
        )
    return image


def particle_opacity(progress):
    """Return the original head/trail fade as a QPainter opacity."""
    fade_progress = min(
        1.0, max(0.0, float(progress)) * PARTICLE_FADE_SPEED_MULTIPLIER)
    return 1.0 - fade_progress ** 1.45


def particle_color(source, progress):
    """Keep the original visual fade helper for color-based callers/tests."""
    opacity = particle_opacity(progress)
    fade = 1.0 - opacity
    return QColor(
        round(source.red() * opacity + C_BG.red() * fade),
        round(source.green() * opacity + C_BG.green() * fade),
        round(source.blue() * opacity + C_BG.blue() * fade),
    )


def _trail_progress(head_progress, knot_age, trail_lifetime):
    age_fade = min(1.0, max(0.0, knot_age / trail_lifetime))
    return (
        1.0 - (1.0 - head_progress) * (1.0 - age_fade)
    ) ** (1.0 / TRAIL_FADE_RATE_FACTOR)


def _intersects_safe_rect(x, y):
    return (
        x + PARTICLE_SIZE > PARTICLE_SAFE_LEFT
        and x < PARTICLE_SAFE_RIGHT
        and y + PARTICLE_SIZE > PARTICLE_SAFE_TOP
        and y < PARTICLE_SAFE_BOTTOM
    )


def draw_particles(painter, particles, scale_x=1, scale_y=None):
    """Draw cached engraving-shaped beads along straight, fading chains."""
    scale_y = scale_x if scale_y is None else scale_y
    size_x = max(1, round(PARTICLE_SIZE * scale_x))
    size_y = max(1, round(PARTICLE_SIZE * scale_y))
    source_rect = QRectF(0, 0, PARTICLE_STAR_SIZE, PARTICLE_STAR_SIZE)

    painter.save()
    painter.setRenderHint(QPainter.SmoothPixmapTransform, False)
    for _, _, _, _, beads, sprite in particles:
        for center_x, center_y, progress in beads:
            opacity = particle_opacity(progress)
            if opacity <= 0.0:
                continue
            left_view = center_x - PARTICLE_SIZE / 2.0
            top_view = center_y - PARTICLE_SIZE / 2.0
            if not _intersects_safe_rect(left_view, top_view):
                continue
            left = round(center_x * scale_x - size_x / 2.0)
            top = round(center_y * scale_y - size_y / 2.0)
            painter.setOpacity(opacity)
            painter.drawImage(
                QRectF(left, top, size_x, size_y), sprite, source_rect)
    painter.restore()


def _xy(point):
    if hasattr(point, "x"):
        return float(point.x()), float(point.y())
    return float(point[0]), float(point[1])


class ParticleSystem:
    """Quadratic-drag heads in a rolling world-space field with visual trails."""

    def __init__(self):
        self._rng = random.Random()
        self._particles = []
        # Lane IDs live on a world-space grid; the map is pruned as the field
        # rolls so the safety-margin buffer does not accumulate stale entries.
        self._lane_base_life = {}
        self._spawn_credit = 0.0

    def _lane_range(self, window_x, scale):
        """World-grid lane IDs across the visible safe width plus both margins."""
        spacing = PARTICLE_SIZE * scale
        safe_left = window_x + PARTICLE_SAFE_LEFT * scale
        safe_right = window_x + PARTICLE_SAFE_RIGHT * scale
        visible_width = safe_right - safe_left
        margin = visible_width * (PARTICLE_FIELD_WIDTH_MULTIPLIER - 1.0) / 2.0
        field_left = safe_left - margin
        field_right = safe_right + margin
        epsilon = 1e-9
        first_lane = math.ceil(field_left / spacing - epsilon)
        last_lane = math.floor(
            (field_right - PARTICLE_SIZE * scale) / spacing + epsilon)
        return first_lane, last_lane

    def _lane_for_x(self, x, scale):
        return int(round(x / (PARTICLE_SIZE * scale)))

    def _base_life_for_lane(self, lane):
        base_life = self._lane_base_life.get(lane)
        if base_life is None:
            base_life = self._rng.uniform(1.5, 3.0)
            self._lane_base_life[lane] = base_life
        return base_life

    def _prune_lane_lives(self, first_lane, last_lane):
        active_lanes = {particle["lane"] for particle in self._particles}
        for lane in tuple(self._lane_base_life):
            if (lane < first_lane or lane > last_lane) and lane not in active_lanes:
                del self._lane_base_life[lane]

    def advance(self, dt, window_velocity=(0.0, 0.0), window_pos=(0.0, 0.0),
                scale=1.0):
        """Integrate world-space heads; newborns never inherit window speed."""
        dt = max(0.0, float(dt))
        if not dt:
            return

        scale = max(0.01, float(scale))
        window_x, window_y = _xy(window_pos)
        flow_x, flow_y = _xy(window_velocity)

        self._spawn_credit += dt * PARTICLE_RATE
        births = int(self._spawn_credit)
        self._spawn_credit -= births

        alive = []
        for particle in self._particles:
            head_was_alive = particle["age"] < particle["life"]
            move_dt = min(dt, max(0.0, particle["life"] - particle["age"]))

            # Keep a short, time-stamped history of the head path. These knots
            # are rendering geometry, not force-bearing trail particles.
            for knot in particle["trail"]:
                knot[2] += dt
            particle["trail"] = [
                knot for knot in particle["trail"]
                if knot[2] < particle["trail_lifetime"]
            ]

            if head_was_alive and move_dt > 0.0:
                start_x, start_y = particle["x"], particle["y"]
                steps = max(1, math.ceil(move_dt / MAX_PHYSICS_STEP))
                h = move_dt / steps
                for _ in range(steps):
                    rel_x = flow_x - particle["vx"]
                    rel_y = flow_y - particle["vy"]
                    relative_speed = math.hypot(rel_x, rel_y)
                    drag = particle["k"] * relative_speed
                    ax = drag * rel_x
                    ay = particle["gravity"] + drag * rel_y

                    # Semi-implicit Euler at a small fixed substep; all values
                    # use seconds and logical screen pixels.
                    particle["vx"] += ax * h
                    particle["vy"] += ay * h
                    particle["x"] += particle["vx"] * h
                    particle["y"] += particle["vy"] * h

                if (dt < particle["trail_lifetime"]
                        and math.hypot(particle["x"] - start_x,
                                       particle["y"] - start_y) > 1e-9):
                    # This was the head position at the start of the frame;
                    # by the frame end it has been on the path for dt seconds.
                    particle["trail"].append([start_x, start_y, dt])

                if particle["age"] + dt >= particle["life"]:
                    # Preserve the death point as the newest point on the path.
                    death_point_age = max(0.0, dt - move_dt)
                    if death_point_age < particle["trail_lifetime"]:
                        particle["trail"].append([
                            particle["x"], particle["y"], death_point_age])

                if len(particle["trail"]) > MAX_TRAIL_HISTORY:
                    del particle["trail"][:-MAX_TRAIL_HISTORY]

            particle["age"] += dt
            if particle["age"] < particle["life"] or particle["trail"]:
                alive.append(particle)
        self._particles = alive

        if not births:
            return

        first_lane, last_lane = self._lane_range(window_x, scale)
        if first_lane > last_lane:
            return

        spawn_limit = (
            PARTICLE_START_Y + TRAIL_LENGTH_REFERENCE_VIEW + PARTICLE_SIZE)
        blocked = set()
        for particle in self._particles:
            if particle["age"] >= particle["life"]:
                continue
            local_y = (particle["y"] - window_y) / scale
            if local_y < spawn_limit:
                blocked.add(self._lane_for_x(particle["x"], scale))
        available_lanes = [lane for lane in range(first_lane, last_lane + 1)
                           if lane not in blocked]
        for _ in range(births):
            if available_lanes:
                lane = self._rng.choice(available_lanes)
                available_lanes.remove(lane)
            else:
                lane = self._rng.randint(first_lane, last_lane)
            self._spawn(lane, window_y, scale)

        self._prune_lane_lives(first_lane, last_lane)

    def _spawn(self, lane, window_y, scale):
        base_life = self._base_life_for_lane(lane)
        terminal_view_speed = (
            (PARTICLE_END_Y - PARTICLE_START_Y)
            * PARTICLE_SPEED / base_life)
        terminal_screen_speed = terminal_view_speed * scale
        gravity = GRAVITY_VIEW * scale
        # With u=(0,0), g=k*v_terminal^2; this exactly balances drag at
        # the original downward terminal speed.
        drag_coefficient = gravity / (terminal_screen_speed ** 2)
        trail_length_factor = self._rng.uniform(*TRAIL_LENGTH_FACTOR_RANGE)
        trail_lifetime = (
            TRAIL_LENGTH_VIEW * trail_length_factor
            / max(terminal_view_speed, 1e-6))
        color = random_particle_color(self._rng)
        sprite = _particle_star_sprite(
            color.red(), color.green(), color.blue())

        self._particles.append({
            "lane": lane,
            # The field is a world-space grid. Only the emitter y follows the
            # APP; newborn velocity deliberately excludes its motion.
            "x": lane * PARTICLE_SIZE * scale,
            "y": window_y + PARTICLE_START_Y * scale,
            "vx": 0.0,
            "vy": terminal_screen_speed,
            "gravity": gravity,
            "k": drag_coefficient,
            "age": 0.0,
            "life": base_life / PARTICLE_SPEED,
            "color": color,
            "sprite": sprite,
            "trail": [],
            "trail_lifetime": trail_lifetime,
        })

    def snapshot(self, window_pos=(0.0, 0.0), scale=1.0):
        """Build evenly spaced beads on a taut line, retaining the old fade."""
        scale = max(0.01, float(scale))
        window_x, window_y = _xy(window_pos)
        result = []
        for particle in self._particles:
            head_progress = min(1.0, particle["age"] / particle["life"])
            head_alive = particle["age"] < particle["life"]
            history = particle["trail"]
            if not head_alive and not history:
                continue

            if history:
                oldest = history[0]
                start_x = (oldest[0] - window_x) / scale + PARTICLE_SIZE / 2
                start_y = (oldest[1] - window_y) / scale + PARTICLE_SIZE / 2
                start_age = oldest[2]
                if head_alive:
                    end_x = (particle["x"] - window_x) / scale \
                        + PARTICLE_SIZE / 2
                    end_y = (particle["y"] - window_y) / scale \
                        + PARTICLE_SIZE / 2
                    end_age = 0.0
                else:
                    newest = history[-1]
                    end_x = (newest[0] - window_x) / scale \
                        + PARTICLE_SIZE / 2
                    end_y = (newest[1] - window_y) / scale \
                        + PARTICLE_SIZE / 2
                    end_age = newest[2]
            else:
                end_x = (particle["x"] - window_x) / scale \
                    + PARTICLE_SIZE / 2
                end_y = (particle["y"] - window_y) / scale \
                    + PARTICLE_SIZE / 2
                start_x, start_y = end_x, end_y
                start_age = end_age = 0.0

            distance = math.hypot(end_x - start_x, end_y - start_y)
            if distance <= 1e-9:
                progress = (
                    head_progress if head_alive else _trail_progress(
                        head_progress, end_age, particle["trail_lifetime"])
                )
                beads = ((end_x, end_y, progress),)
            else:
                count = min(
                    MAX_PARTICLE_BEADS,
                    max(2, math.ceil(
                        distance / PARTICLE_BEAD_SPACING_VIEW) + 1),
                )
                bead_list = []
                for index in range(count):
                    t = index / (count - 1)
                    knot_age = start_age + (end_age - start_age) * t
                    progress = (
                        head_progress if head_alive and index == count - 1
                        else _trail_progress(
                            head_progress, knot_age,
                            particle["trail_lifetime"],
                        )
                    )
                    bead_list.append((
                        start_x + (end_x - start_x) * t,
                        start_y + (end_y - start_y) * t,
                        progress,
                    ))
                beads = tuple(bead_list)

            if head_alive or history:
                result.append((
                    (particle["x"] - window_x) / scale,
                    (particle["y"] - window_y) / scale,
                    particle["color"], head_progress, beads,
                    particle["sprite"],
                ))
        return tuple(result)
