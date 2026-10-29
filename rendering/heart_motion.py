# -*- coding: utf-8 -*-
"""Damped heart motion and click impulses in view-space pixels."""

import math

# Tank walls align with the CONTENT side of the inset particle-field feather,
# not the outer 5-physical-pixel window frame. Renderer supplies the actual
# PARTICLE_SAFE_RECT and scale/DPR-adjusted feather thickness at runtime.
# First parameter row starts at y=256; floor y=236 leaves a 20-view-unit gap.
HEART_TANK_INPUT_GAP = 20.0
HEART_TANK_BOTTOM = 256.0 - HEART_TANK_INPUT_GAP
HEART_BOUNCE_RECT = (21.0, 33.0, 299.0, HEART_TANK_BOTTOM)
HEART_IDLE_CENTER = (160.0, 140.5)  # Preserve the accepted idle position.
HEART_GRAVITY = 500.0  # View pixels / second squared; positive y is downward.
HEART_DRAG = 4.5  # Linear velocity damping, per second.
HEART_RESTITUTION = 0.22  # Small, dissipative collision rebound.
HEART_FLOOR_FRICTION = 5.0  # Additional horizontal damping when on the floor.
HEART_REST_SPEED = 12.0  # Suppress tiny bounces and numerical floor jitter.
HEART_CLICK_IMPULSE = 520.0  # Fixed velocity impulse per press (unit mass).
HEART_MAX_SPEED = 700.0  # Keep repeated clicks controllable.
HEART_MAX_PHYSICS_STEP = 1.0 / 240.0


def heart_tank_rect(feather_inset=5.0, safe_rect=(16.0, 28.0, 304.0, 440.0)):
    left, top, right, _ = safe_rect
    return (left + feather_inset, top + feather_inset,
            right - feather_inset, HEART_TANK_BOTTOM)


def point_in_heart_tank(x, y, feather_inset=5.0,
                        safe_rect=(16.0, 28.0, 304.0, 440.0)):
    left, top, right, bottom = heart_tank_rect(feather_inset, safe_rect)
    return left <= x <= right and top <= y <= bottom


class HeartMotion:
    """Translating rigid heart with gravity, drag and inelastic wall collisions."""

    def __init__(self, width, height):
        self._width, self._height = width, height
        self._center = HEART_IDLE_CENTER
        self._bounds = None
        self.reset()
        self.set_tank_rect(HEART_BOUNCE_RECT)

    def set_tank_rect(self, rect):
        left, top, right, bottom = rect
        bounds = (left + self._width / 2.0, top + self._height / 2.0,
                  right - self._width / 2.0, bottom - self._height / 2.0)
        if bounds == self._bounds:
            return
        self._bounds = bounds
        # A UI scale/DPR change may move a wall slightly; stay inside without
        # restarting the simulation or waking a settled heart.
        self.x = min(max(self.x, bounds[0]), bounds[2])
        self.y = min(max(self.y, bounds[1]), bounds[3])

    @property
    def offset(self):
        return self.x - self._center[0], self.y - self._center[1]

    def reset(self):
        self.x, self.y = self._center
        self.vx = self.vy = 0.0
        self.active = False
        self.sleeping = False

    def launch(self):
        # Release from rest, with no random initial kick.
        self.reset()
        self.active = True

    def stop(self):
        # Keep the last invisible position until the next reset/launch.
        self.active = False

    def poke(self, click_x, click_y):
        if not self.active:
            return False
        dx, dy = self.x - click_x, self.y - click_y
        distance = math.hypot(dx, dy)
        if distance < 1.0:
            dx, dy = 0.0, -1.0
        else:
            dx, dy = dx / distance, dy / distance
        self.vx += dx * HEART_CLICK_IMPULSE
        self.vy += dy * HEART_CLICK_IMPULSE
        speed = math.hypot(self.vx, self.vy)
        if speed > HEART_MAX_SPEED:
            self.vx *= HEART_MAX_SPEED / speed
            self.vy *= HEART_MAX_SPEED / speed
        self.sleeping = False
        return True

    def advance(self, elapsed):
        if not self.active or self.sleeping or elapsed <= 0.0:
            return
        left, top, right, bottom = self._bounds
        steps = max(1, math.ceil(elapsed / HEART_MAX_PHYSICS_STEP))
        dt = elapsed / steps
        decay = math.exp(-HEART_DRAG * dt)
        terminal_speed = HEART_GRAVITY / HEART_DRAG
        for _ in range(steps):
            # Exact free-flight solution for constant gravity and linear drag.
            self.x += self.vx * (1.0 - decay) / HEART_DRAG
            self.y += (terminal_speed * dt
                       + (self.vy - terminal_speed) * (1.0 - decay) / HEART_DRAG)
            self.vx *= decay
            self.vy = terminal_speed + (self.vy - terminal_speed) * decay
            if self.x < left:
                self.x = left
                self.vx = abs(self.vx) * HEART_RESTITUTION
            elif self.x > right:
                self.x = right
                self.vx = -abs(self.vx) * HEART_RESTITUTION
            if self.y < top:
                self.y = top
                self.vy = abs(self.vy) * HEART_RESTITUTION
            elif self.y >= bottom:
                self.y = bottom
                rebound = abs(self.vy) * HEART_RESTITUTION
                self.vy = -rebound if rebound >= HEART_REST_SPEED else 0.0
                self.vx *= math.exp(-HEART_FLOOR_FRICTION * dt)
                if self.vy == 0.0 and abs(self.vx) < 1.0:
                    self.vx = self.vy = 0.0
                    self.sleeping = True
                    break
