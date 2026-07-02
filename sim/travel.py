"""Travel model (DESIGN §8.1, §13). `TravelModel` is an interface so a waypoint graph or navmesh
(mmap) can replace the Euclidean approximation later without touching the engine. Euclidean×k is
known-optimistic on Teldrassil's verticality/water — if M5 residuals concentrate on travel, the
plan is to promote to a hand-laid waypoint graph (DESIGN §13), not to re-tune k blindly.
"""

from __future__ import annotations

import math
from typing import Protocol

from sim.state import Vec2


class TravelModel(Protocol):
    def time(self, a: Vec2, b: Vec2) -> float:
        """Seconds to travel from a to b."""
        ...

    def distance(self, a: Vec2, b: Vec2) -> float:
        """Path distance in yards (pre-speed)."""
        ...


class EuclideanK:
    """time = euclid(a,b) * k_zone / speed  (DESIGN §8.1)."""

    def __init__(self, k_zone: float, speed: float) -> None:
        if speed <= 0:
            raise ValueError("EuclideanK: speed must be positive")
        self.k_zone = k_zone
        self.speed = speed

    def distance(self, a: Vec2, b: Vec2) -> float:
        return math.hypot(a.x - b.x, a.y - b.y) * self.k_zone

    def time(self, a: Vec2, b: Vec2) -> float:
        return self.distance(a, b) / self.speed
