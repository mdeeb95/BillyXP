"""Table-driven combat tests (DESIGN §8.2), anchored to the params.py grounding: a fresh hunter
(weapon_dps 1.52, band 1-4 a=2.0 b=1.0) kills an equal-level L1 mob (hp 42, armor 0) in ~12 s.
"""

from __future__ import annotations

import pytest

from sim import combat
from sim.params import Params
from sim.state import CharacterState, Class, Vec2
from sim.world import Mob


def _mob(lvl: int, hp: float, armor: float = 0.0, elite: bool = False) -> Mob:
    return Mob(id=1, name="Test", lvl_min=lvl, lvl_max=lvl, hp_min=hp, hp_max=hp,
              armor=armor, dps_est=1.0, elite=elite)


def _hunter(level: int = 1, ranged: float = 1.52, melee: float = 0.94) -> CharacterState:
    return CharacterState(clazz=Class.HUNTER, level=level, xp=0, pos=Vec2(0, 0),
                         gold_c=0, ranged_dps=ranged, melee_dps=melee)


def test_edps_grounding() -> None:
    p = Params()
    # band 1: a=1.5, b_r=0.8, b_m=0.9 -> 1.5 + 0.8*1.52 + 0.9*0.94 = 3.562
    assert combat.edps(_hunter(), p) == pytest.approx(1.5 + 0.8 * 1.52 + 0.9 * 0.94)


def test_edps_bumps_multiply() -> None:
    p = Params()
    st = _hunter()
    base = combat.edps(st, p)
    st.known_spell_bumps.add("Arcane Shot")   # mult 1.12
    assert combat.edps(st, p) == pytest.approx(base * 1.12)


@pytest.mark.parametrize("delta, expected", [
    (0, 1.0),
    (2, 0.88),      # 1 - 0.06*2
    (-2, 1.12),     # 1 + 0.12, under the 1.15 cap
    (10, 0.4),      # clamped to min
])
def test_delta_penalty(delta: int, expected: float) -> None:
    assert combat.delta_penalty(delta, Params()) == pytest.approx(expected)


def test_ttk_band_is_plausible() -> None:
    p = Params()
    edps = combat.edps(_hunter(), p)                          # 3.562
    ttk_mean, var = combat.ttk(_hunter(), p, _mob(1, 42.0))
    assert ttk_mean == pytest.approx(42.0 / edps, rel=1e-6)   # ~11.8 s
    assert 8.0 <= ttk_mean <= 15.0                            # stated plausible band
    assert var == 0.0                                         # v0 stub


def test_kill_cycle_folds_overhead() -> None:
    p = Params()
    cycle, _ = combat.kill_cycle(_hunter(), p, _mob(1, 42.0), None)
    ttk_mean, _ = combat.ttk(_hunter(), p, _mob(1, 42.0))
    assert cycle == pytest.approx((ttk_mean + p.t_acquire_base + p.t_loot) * p.downtime_factor[1])


def test_two_slot_reward_is_slot_aware() -> None:
    # A melee weapon upgrades melee_dps only; the ranged slot (bow) is untouched.
    from sim.actions import weapon_slot
    from sim.world import Item
    staff = Item(id=1, name="Staff", slot=17, weapon_dps=2.58, armor=0, stats={})  # 2H melee
    bow = Item(id=2, name="Bow", slot=15, weapon_dps=3.0, armor=0, stats={})       # ranged
    assert weapon_slot(staff, Params()) == "melee"
    assert weapon_slot(bow, Params()) == "ranged"


def test_edps_uses_both_weapon_slots() -> None:
    p = Params()
    st = _hunter(ranged=1.52, melee=0.94)
    base = combat.edps(st, p)
    st.melee_dps = 2.58                      # equip a better melee weapon
    assert combat.edps(st, p) > base         # melee slot contributes (b_m not small)


def test_expected_kills() -> None:
    assert combat.expected_kills(1, 0.5) == 2.0
    assert combat.expected_kills(7, 1.0) == 7.0
    with pytest.raises(ValueError):
        combat.expected_kills(1, None)     # NULL drop must route through a provider
