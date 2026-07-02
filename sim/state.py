"""CharacterState and the small value types the engine threads through every step (DESIGN §6).

State is a plain dataclass; the engine copies-and-mutates it per step so a timeline is a
sequence of immutable snapshots. Talents are omitted entirely (they begin at level 10, the very
end of this slice — DESIGN §6).
"""

from __future__ import annotations

import copy
from dataclasses import dataclass, field
from enum import IntEnum
from typing import NamedTuple


class Vec2(NamedTuple):
    """2D world position (world_x, world_y). vmangos coords; +x north, +y west (see viz)."""
    x: float
    y: float


class Class(IntEnum):
    """WoW class ids as used by the source dump (playercreateinfo_item.class). Only HUNTER is
    modeled in this slice (M5 calibration class); the enum exists so class-dependent params key
    off a real id, not a string."""
    WARRIOR = 1
    PALADIN = 2
    HUNTER = 3
    ROGUE = 4
    PRIEST = 5
    SHAMAN = 7
    MAGE = 8
    WARLOCK = 9
    DRUID = 11


@dataclass
class CharacterState:
    """Mutable character snapshot (DESIGN §6). `quest_log` maps quest_id -> per-objective
    progress counts (index-aligned to objectives.idx). `known_spell_bumps` holds applied trained
    breakpoints (bump_id). `t` is sim seconds since start (deterministic clock)."""
    clazz: Class
    level: int
    xp: int
    pos: Vec2
    gold_c: int                              # copper
    # A hunter holds a ranged AND a melee weapon simultaneously — two independent slots, not one
    # weapon. One field structurally cannot represent the character, so EDPS carries both terms
    # (DESIGN §8.2 / M1 review). Pre-pet hunters melee a meaningful fraction of each kill.
    ranged_dps: float
    melee_dps: float
    quest_log: dict[int, list[int]] = field(default_factory=dict)
    completed: set[int] = field(default_factory=set)
    known_spell_bumps: set[str] = field(default_factory=set)
    hearth_poi: int = 0
    rested_pool: int = 0                      # XP worth of rested; default 0 (fresh char)
    supplies: dict[str, int] = field(default_factory=dict)
    t: float = 0.0

    def copy(self) -> "CharacterState":
        """Deep copy for checkpointing (engine evaluate_from) and per-step snapshots."""
        return copy.deepcopy(self)
