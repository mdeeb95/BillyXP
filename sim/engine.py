"""Plan executor (DESIGN §10). Pure & deterministic: output depends only on
(world, state, route, params) — no wall-clock, no RNG (CLAUDE.md rule 2).

    execute(world, state, route, params) -> EngineResult
        timeline (per-step snapshots), metrics, final_state; or (infeasible, first_violating_index).

Prefix caching (DESIGN §10) is a first-class requirement: `checkpoint` snapshots state at a step
boundary and `evaluate_from(world, checkpoint_state, suffix, params)` re-simulates only the suffix.
The 5 ms/suffix budget is enforced at M4 (CLAUDE.md rule 7); the interface ships now so the router
and the future receding-horizon replanner attach without engine changes.

Invariants asserted every step: monotonic time, non-negative gold, objective progress within
bounds, level within the XP table. A level/precondition gate violation returns
(feasible=False, first_violating_index) rather than raising past the engine boundary.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field

from sim import xp
from sim.actions import Infeasible, apply, resolve_location
from sim.dsl import Route, serialize_step
from sim.params import Params
from sim.state import CharacterState
from sim.travel import EuclideanK, TravelModel


@dataclass
class TimelineEntry:
    idx: int
    step: str
    t0: float
    t1: float
    travel_s: float
    action_s: float
    combat_s: float
    interaction_s: float
    downtime_s: float
    xp_gained: int
    level: int
    xp: int
    levels_gained: int
    gold_c: int
    pos_x: float
    pos_y: float
    note: str


@dataclass
class Metrics:
    total_seconds: float
    final_level: int
    final_xp_into_level: int
    total_xp_gained: int
    quests_completed: int
    n_steps: int
    n_levelups: int


@dataclass
class EngineResult:
    feasible: bool
    timeline: list[TimelineEntry] = field(default_factory=list)
    final_state: CharacterState | None = None
    metrics: Metrics | None = None
    first_violating_index: int | None = None
    reason: str | None = None


def execute(
    world,  # type: ignore[no-untyped-def]  # sim.world.World (avoid import cycle in annotations)
    state: CharacterState,
    route: Route,
    params: Params,
    travel_model: TravelModel | None = None,
) -> EngineResult:
    tm = travel_model or EuclideanK(params.k_zone, params.base_run_speed)
    st = state.copy()
    timeline: list[TimelineEntry] = []
    total_xp = 0
    total_levelups = 0

    for i, step in enumerate(route.steps):
        t0 = st.t
        try:
            loc = resolve_location(step, st, world)
            travel_s = tm.time(st.pos, loc) if loc is not None else 0.0
            if loc is not None:
                st.pos = loc
            res = apply(step, st, world, params)
        except Infeasible as e:
            return EngineResult(feasible=False, timeline=timeline,
                                first_violating_index=i, reason=e.reason)

        levels_gained = 0
        if res.xp_gained:
            st.level, st.xp, levels_gained = xp.apply_xp(world, st.level, st.xp, res.xp_gained)
        total_xp += res.xp_gained
        total_levelups += levels_gained

        action_s = res.duration
        st.t = t0 + travel_s + action_s
        timeline.append(TimelineEntry(
            idx=i, step=serialize_step(step), t0=t0, t1=st.t,
            travel_s=travel_s, action_s=action_s, combat_s=res.combat_s,
            interaction_s=res.interaction_s, downtime_s=res.downtime_s,
            xp_gained=res.xp_gained, level=st.level, xp=st.xp,
            levels_gained=levels_gained, gold_c=st.gold_c,
            pos_x=st.pos.x, pos_y=st.pos.y, note=res.note,
        ))
        _assert_invariants(st, t0, world)

    metrics = Metrics(
        total_seconds=st.t, final_level=st.level, final_xp_into_level=st.xp,
        total_xp_gained=total_xp, quests_completed=len(st.completed),
        n_steps=len(route.steps), n_levelups=total_levelups,
    )
    return EngineResult(feasible=True, timeline=timeline, final_state=st, metrics=metrics)


def checkpoint(state: CharacterState) -> CharacterState:
    """Snapshot state at a step boundary for prefix caching (DESIGN §10)."""
    return state.copy()


def evaluate_from(
    world,  # type: ignore[no-untyped-def]
    checkpoint_state: CharacterState,
    suffix: Route,
    params: Params,
    travel_model: TravelModel | None = None,
) -> EngineResult:
    """Re-simulate only a suffix from a checkpoint (DESIGN §10). Same result type as execute; a
    50k-move anneal re-runs just the mutated tail. Correctness parity with a full run over the
    same suffix is covered by tests; the 5 ms budget is a M4 concern."""
    return execute(world, checkpoint_state, suffix, params, travel_model)


def _assert_invariants(st: CharacterState, prev_t: float, world) -> None:  # type: ignore[no-untyped-def]
    assert st.t >= prev_t - 1e-9, f"time went backwards: {st.t} < {prev_t}"
    assert st.gold_c >= 0, f"negative gold: {st.gold_c}"
    assert st.level >= 1, f"level below 1: {st.level}"
    assert st.level <= max(world.xp_to_next) + 1, f"level {st.level} above XP table"
    for qid, progress in st.quest_log.items():
        q = world.quests[qid]
        for obj in q.objectives:
            assert 0 <= progress[obj.idx] <= obj.count, \
                f"quest {qid} obj {obj.idx} progress out of bounds: {progress[obj.idx]}"


def timeline_to_json(result: EngineResult) -> str:
    """Serialize the timeline + metrics to JSON (DESIGN §7 artifact)."""
    return json.dumps({
        "feasible": result.feasible,
        "first_violating_index": result.first_violating_index,
        "reason": result.reason,
        "metrics": asdict(result.metrics) if result.metrics else None,
        "timeline": [asdict(e) for e in result.timeline],
    }, indent=2)
