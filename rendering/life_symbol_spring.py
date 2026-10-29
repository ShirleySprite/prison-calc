# -*- coding: utf-8 -*-

import math

MAX_SYMBOL_DRAG_RADIUS = 4.0  # Art units; a circular limit allows a full 360° pull.
SPRING_ANGULAR_FREQUENCY = 18.0  # radians/second; higher means faster oscillations.
SPRING_DAMPING_RATIO = 0.09  # Lower means more visible bounces before settling.
MAX_DRAG_SPEED = 48.0  # Art units per second, limiting release flicks.
DRAG_VELOCITY_FILTER_SECONDS = 0.045
MAX_INTEGRATION_STEP = 1.0 / 240.0
BOUNDARY_RESTITUTION = 0.08
REST_POSITION_EPSILON = 0.02
REST_SPEED_EPSILON = 0.08


class LifeSymbolSpring:
    """Constrain life-symbol dragging and spring the symbols back on release."""

    def __init__(self):
        self.x = 0.0
        self.y = 0.0
        self.vx = 0.0
        self.vy = 0.0
        self.dragging = False
        self._last_drag_time = None

    @property
    def offset(self):
        return self.x, self.y

    def begin_drag(self, now):
        self.dragging = True
        self.vx = 0.0
        self.vy = 0.0
        self._last_drag_time = float(now)

    def drag_to(self, x, y, now):
        """Follow the pointer within the circular travel limit and sample flick speed."""
        if not self.dragging:
            return

        now = float(now)
        dt = max(1e-4, now - self._last_drag_time)
        x, y = self._clamp_position(float(x), float(y))
        raw_vx = (x - self.x) / dt
        raw_vy = (y - self.y) / dt
        speed = math.hypot(raw_vx, raw_vy)
        if speed > MAX_DRAG_SPEED:
            factor = MAX_DRAG_SPEED / speed
            raw_vx *= factor
            raw_vy *= factor

        blend = 1.0 - math.exp(-dt / DRAG_VELOCITY_FILTER_SECONDS)
        self.vx += (raw_vx - self.vx) * blend
        self.vy += (raw_vy - self.vy) * blend
        self.x, self.y = x, y
        self._last_drag_time = now

    def release(self):
        self.dragging = False
        self._last_drag_time = None

    def advance(self, dt_seconds):
        """Integrate m*x'' + c*x' + k*x = 0 with stable small substeps."""
        if self.dragging:
            return False

        dt = max(0.0, float(dt_seconds))
        if not dt:
            return False
        old_x, old_y = self.x, self.y
        steps = max(1, math.ceil(dt / MAX_INTEGRATION_STEP))
        step_dt = dt / steps
        omega = SPRING_ANGULAR_FREQUENCY
        damping = 2.0 * SPRING_DAMPING_RATIO * omega

        for _ in range(steps):
            ax = -(omega * omega) * self.x - damping * self.vx
            ay = -(omega * omega) * self.y - damping * self.vy
            self.vx += ax * step_dt
            self.vy += ay * step_dt
            self.x += self.vx * step_dt
            self.y += self.vy * step_dt
            self._resolve_boundary()

        if (math.hypot(self.x, self.y) < REST_POSITION_EPSILON
                and math.hypot(self.vx, self.vy) < REST_SPEED_EPSILON):
            self.x = self.y = self.vx = self.vy = 0.0

        return self.x != old_x or self.y != old_y

    @staticmethod
    def _clamp_position(x, y):
        distance = math.hypot(x, y)
        if distance <= MAX_SYMBOL_DRAG_RADIUS:
            return x, y
        factor = MAX_SYMBOL_DRAG_RADIUS / distance
        return x * factor, y * factor

    def _resolve_boundary(self):
        distance = math.hypot(self.x, self.y)
        if distance <= MAX_SYMBOL_DRAG_RADIUS:
            return

        nx, ny = self.x / distance, self.y / distance
        self.x = nx * MAX_SYMBOL_DRAG_RADIUS
        self.y = ny * MAX_SYMBOL_DRAG_RADIUS
        outward_speed = self.vx * nx + self.vy * ny
        if outward_speed > 0.0:
            impulse = (1.0 + BOUNDARY_RESTITUTION) * outward_speed
            self.vx -= impulse * nx
            self.vy -= impulse * ny
