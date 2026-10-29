# -*- coding: utf-8 -*-
"""Small visual-only tremor for two-second game entry and exit holds."""

import math

HEART_GAME_HOLD_SECONDS = 2.0
HEART_TREMOR_MIN_AMPLITUDE = 0.25
HEART_TREMOR_MAX_AMPLITUDE = 1.25  # View units, before the shared UI scale.


class HeartHold:
    def __init__(self):
        self.cancel()

    def begin(self):
        self.elapsed = 0.0
        self.active = True

    def cancel(self):
        self.elapsed = 0.0
        self.active = False

    @property
    def offset(self):
        if not self.active:
            return 0.0, 0.0
        t = self.elapsed
        progress = min(1.0, t / HEART_GAME_HOLD_SECONDS)
        amplitude = (HEART_TREMOR_MIN_AMPLITUDE
                     + (HEART_TREMOR_MAX_AMPLITUDE
                        - HEART_TREMOR_MIN_AMPLITUDE) * progress)
        # Bounded mixed frequencies avoid a mechanical left/right wobble.
        return (
            amplitude * (0.7 * math.sin(math.tau * 19 * t)
                         + 0.3 * math.sin(math.tau * 31 * t)),
            amplitude * (0.65 * math.sin(math.tau * 23 * t)
                         + 0.35 * math.sin(math.tau * 37 * t)),
        )

    def advance(self, elapsed):
        """Return True exactly once when a continuous hold reaches two seconds."""
        if not self.active:
            return False
        self.elapsed += max(0.0, elapsed)
        if self.elapsed >= HEART_GAME_HOLD_SECONDS:
            self.cancel()
            return True
        return False
