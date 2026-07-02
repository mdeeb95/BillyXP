"""Engine end-to-end tests: a small quest cycle renders a monotonic timeline, level-gates return
infeasible (not raise), and evaluate_from(suffix) matches a full run (prefix-cache parity, §10).
"""

from __future__ import annotations

from sim import engine
from sim.dsl import Accept, Route, Step, Turnin, Work
from sim.params import Params
from sim.state import CharacterState, Class
from sim.world import World


def _fresh(world: World) -> CharacterState:
    pos = world.poi_pos("GIVER", 456)
    return CharacterState(clazz=Class.HUNTER, level=1, xp=0, pos=pos, gold_c=0,
                         ranged_dps=1.52, melee_dps=0.94)


def _kill_areas(world: World, quest_id: int) -> list[int | None]:
    return [o.area_id for o in world.quest(quest_id).objectives]


def test_quest_cycle_feasible_and_monotonic() -> None:
    w = World()
    areas = _kill_areas(w, 456)          # two KILL objectives
    steps: list[Step] = [
        Accept(456),
        Work(456, 0, areas[0]),
        Work(456, 1, areas[1]),
        Turnin(456),
    ]
    r = engine.execute(w, _fresh(w), Route(steps=steps), Params())
    assert r.feasible and r.metrics is not None and r.final_state is not None
    assert len(r.timeline) == 4
    # Monotonic time.
    for a, b in zip(r.timeline, r.timeline[1:]):
        assert b.t0 >= a.t1 - 1e-9 and b.t1 >= b.t0
    # Turn-in awarded the quest XP (456 RewXP = 170) on top of kill XP.
    assert r.metrics.total_xp_gained >= 170
    assert 456 in r.final_state.completed
    assert r.metrics.total_seconds > 0


def test_level_gate_returns_infeasible() -> None:
    w = World()
    # Quest 937 requires level 6; a level-1 accept must be infeasible at index 0 (not raise).
    assert w.quest(937).min_level >= 6
    r = engine.execute(w, _fresh(w), Route(steps=[Accept(937)]), Params())
    assert not r.feasible and r.first_violating_index == 0 and r.reason is not None


def test_evaluate_from_matches_full_run() -> None:
    w = World()
    areas = _kill_areas(w, 456)
    steps: list[Step] = [Accept(456), Work(456, 0, areas[0]), Work(456, 1, areas[1]), Turnin(456)]
    p = Params()
    full = engine.execute(w, _fresh(w), Route(steps=steps), p)
    assert full.feasible

    # Run a prefix, checkpoint, then evaluate_from the suffix.
    split = 2
    prefix = engine.execute(w, _fresh(w), Route(steps=steps[:split]), p)
    assert prefix.final_state is not None
    ck = engine.checkpoint(prefix.final_state)
    suffix = engine.evaluate_from(w, ck, Route(steps=steps[split:]), p)
    assert suffix.feasible and suffix.metrics is not None and full.metrics is not None
    # Final wall-clock and level match the full run to the microsecond (determinism).
    assert suffix.metrics.total_seconds == full.metrics.total_seconds
    assert suffix.final_state is not None and full.final_state is not None
    assert suffix.final_state.level == full.final_state.level
    assert suffix.final_state.xp == full.final_state.xp


def test_determinism_repeat_run() -> None:
    w = World()
    areas = _kill_areas(w, 456)
    steps: list[Step] = [Accept(456), Work(456, 0, areas[0]), Work(456, 1, areas[1]), Turnin(456)]
    route = Route(steps=steps)
    p = Params()
    a = engine.execute(w, _fresh(w), route, p)
    b = engine.execute(w, _fresh(w), route, p)
    assert a.metrics == b.metrics
