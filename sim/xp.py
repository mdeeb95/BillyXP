"""XP model: kill XP formula, level-up application, quest XP, rested (DESIGN §8.3).

Kill XP is the standard vanilla formula from a community reference (URL below), NOT reconstructed
from memory (CLAUDE.md rule 1). Quest XP comes from the compiled DB (quests.xp = quest_template
RewXP, verified in etl/NOTES.md §3). The level table comes from world.xp_to_next
(player_xp_for_level; 1->2 = 400, verified anchor).

Kill XP reference (constants + piecewise conditions reproduced verbatim):
  https://warcraft.wiki.gg/wiki/Mob_experience   (classic mob experience formula)
  - Base XP        = CharLevel * 5 + 45          (char-level base; matches DESIGN §8.3)
  - Mob >= char    : XP = Base * (1 + 0.05*(MobLevel - CharLevel)), MobLevel capped at CharLevel+4
  - Mob <  char    : XP = Base * (1 - (CharLevel - MobLevel)/ZD),   0 if MobLevel <= GrayLevel
  - ZD table, GrayLevel brackets, Elite x2: encoded below.
Note: some cores base the constant on MOB level instead of CHAR level; DESIGN §8.3 and the cited
higher-level formula both use CHAR level, so we use char level and flag the ambiguity here.
"""

from __future__ import annotations

from sim.world import World

# Zero-difference denominator by character level (cited table above). Encoded 1..60; the M1
# slice only exercises levels 1..~11 (ZD 5..7).
_ZD_TABLE: tuple[tuple[int, int, int], ...] = (
    (1, 7, 5), (8, 9, 6), (10, 11, 7), (12, 15, 8), (16, 19, 9), (20, 29, 11),
    (30, 39, 12), (40, 44, 13), (45, 49, 14), (50, 54, 15), (55, 59, 16), (60, 84, 17),
)


def zd(char_level: int) -> int:
    for lo, hi, val in _ZD_TABLE:
        if lo <= char_level <= hi:
            return val
    raise ValueError(f"kill_xp: no ZD value for char level {char_level}")


def gray_level(char_level: int) -> int:
    """Mob levels at or below this give 0 XP (cited brackets)."""
    if char_level <= 5:
        return 0
    if char_level <= 39:
        return char_level - char_level // 10 - 5
    if char_level <= 59:
        return char_level - char_level // 5 - 1
    return char_level - 9


def kill_xp(char_level: int, mob_level: int, elite: bool = False) -> int:
    """Vanilla kill XP for one mob (cited formula). Floored to an integer as in-game."""
    base = char_level * 5 + 45
    if mob_level >= char_level:
        capped = min(mob_level, char_level + 4)  # red mobs cap at orange XP
        xp = base * (1.0 + 0.05 * (capped - char_level))
    elif mob_level <= gray_level(char_level):
        return 0
    else:
        xp = base * (1.0 - (char_level - mob_level) / zd(char_level))
    if elite:
        xp *= 2.0
    return int(xp)  # floor


def apply_xp(world: World, level: int, xp_into_level: int, gained: int) -> tuple[int, int, int]:
    """Add `gained` XP; roll over level-ups. Returns (new_level, new_xp_into_level, levels_gained).

    Level is capped at the top level present in the XP table (no further roll-over)."""
    levels_gained = 0
    xp_into_level += gained
    top = max(world.xp_to_next)
    while level < top:
        need = world.xp_to_next.get(level)
        if need is None or xp_into_level < need:
            break
        xp_into_level -= need
        level += 1
        levels_gained += 1
    return level, xp_into_level, levels_gained


def kill_xp_with_rested(
    char_level: int, mob_level: int, rested_pool: int, rested_mult: float, elite: bool = False
) -> tuple[int, int]:
    """Kill XP with rested bonus applied to the portion covered by the rested pool.

    Returns (xp_gained, rested_pool_consumed). Rested doubles kill XP (DESIGN §8.3) until the
    pool is drained; the pool is measured in bonus XP granted. For a fresh character rested_pool
    is 0 so this reduces to plain kill_xp.
    """
    base = kill_xp(char_level, mob_level, elite)
    if rested_pool <= 0 or rested_mult <= 1.0:
        return base, 0
    bonus = min(base * (rested_mult - 1.0), float(rested_pool))
    consumed = int(bonus)
    return base + consumed, consumed
