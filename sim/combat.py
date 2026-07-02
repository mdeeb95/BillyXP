"""Combat / kill-rate model (DESIGN §8.2). Expectations only in v0; every function returns
(mean, var) so HC hazard / Monte-Carlo (M6) slot in without interface churn — var is a stub 0.0
here (deterministic v0) with the hook in place.

EDPS(class, level, weapon_dps) = a[band] + b[band]*weapon_dps, times applied trained-breakpoint
mults. TTK = EHP / (EDPS * delta_penalty). kill_cycle folds acquire + loot + downtime. All
constants come from sim.params (no magic numbers here, CLAUDE.md rule 3).
"""

from __future__ import annotations

from sim.params import Params, band_for_level
from sim.state import CharacterState
from sim.world import Area, Mob

MeanVar = tuple[float, float]


def edps(state: CharacterState, params: Params) -> float:
    """Effective DPS from the ranged + melee weapon slots and applied trained bumps (DESIGN §8.2).
    EDPS = a + b_ranged*ranged_dps + b_melee*melee_dps, then × Π active bump mults."""
    band = band_for_level(state.level)
    val = (params.edps_a[band]
           + params.edps_b_ranged[band] * state.ranged_dps
           + params.edps_b_melee[band] * state.melee_dps)
    for bump_id in state.known_spell_bumps:
        val *= params.bump_mult.get(bump_id, 1.0)
    return val


def delta_penalty(delta: int, params: Params) -> float:
    """EDPS multiplier for fighting a mob `delta = mob_lvl - char_lvl` levels away. <1 vs
    up-level mobs, >1 (capped) vs down-level; clamped to [min, max] (DESIGN §8.2)."""
    factor = 1.0 - params.delta_penalty_per_level * delta
    return max(params.delta_penalty_min, min(params.delta_penalty_max, factor))


def ehp(mob: Mob, params: Params) -> float:
    """Effective HP including physical mitigation (DESIGN §8.2)."""
    hp = mob.hp_max if mob.hp_max is not None else mob.hp_min
    if hp is None:
        raise ValueError(f"combat: mob {mob.id} {mob.name!r} has no HP in the compiled DB")
    armor = mob.armor or 0.0
    return hp * (1.0 + params.armor_factor_per_armor * armor)


def ttk(state: CharacterState, params: Params, mob: Mob) -> MeanVar:
    """Time-to-kill one mob (seconds). Uses the mob's max level for the delta penalty."""
    dps = edps(state, params) * delta_penalty(mob.lvl_max - state.level, params)
    if dps <= 0:
        raise ValueError("combat: non-positive effective DPS")
    return ehp(mob, params) / dps, 0.0


def kill_cycle(state: CharacterState, params: Params, mob: Mob, area: Area | None) -> MeanVar:
    """Full per-kill wall-clock: (TTK + acquire + loot) * downtime overhead (DESIGN §8.2).

    acquire is the travel-to-next-mob within an area; density refinement and respawn floors are a
    M2 concern (DESIGN §8.2) — kept as a flat base here. `area` is accepted for that future use.
    """
    _ = area  # density/respawn refinement deferred to M2
    band = band_for_level(state.level)
    ttk_mean, _var = ttk(state, params, mob)
    cycle = (ttk_mean + params.t_acquire_base + params.t_loot) * params.downtime_factor[band]
    return cycle, 0.0


def expected_kills(count: int, drop_chance: float | None) -> float:
    """Expected kills to satisfy an objective. KILL: `count`. COLLECT: count / drop_chance
    (DESIGN §8.2). drop_chance None is a caller error — NULL-drop COLLECTs must route through a
    provider annotation (ETL step 0b), never count / NULL (CLAUDE.md rule 1)."""
    if drop_chance is None:
        raise ValueError("combat: expected_kills called with NULL drop_chance — use provider path")
    if not 0.0 < drop_chance <= 1.0:
        raise ValueError(f"combat: drop_chance out of range: {drop_chance}")
    return count / drop_chance
