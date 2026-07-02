"""Per-step action models: where a step happens (`resolve_location`) and its local duration +
state delta (`apply`). The engine handles travel between steps; these functions assume the
character is already at the step's location and return only the non-travel duration.

Durations and XP are expectations (DESIGN §8). A WORK objective is evaluated in one lump at the
character's entry-level stats (EDPS, kill XP) — a v0 approximation noted here; per-kill re-leveling
is a M2 refinement. All time/XP constants come from sim.params and sim.combat (no magic numbers).
"""

from __future__ import annotations

from dataclasses import dataclass

from sim import combat, xp
from sim.dsl import (
    Accept,
    Buy,
    Goto,
    Grind,
    Hearth,
    SetHearth,
    Step,
    Train,
    Turnin,
    Work,
)
from sim.dsl import AreaRef, Coord
from sim.params import HUNTER_BUMPS, Params
from sim.state import CharacterState, Vec2
from sim.world import World


class Infeasible(Exception):
    """Raised when a step violates a level gate or precondition (DESIGN §10). The engine converts
    this into (infeasible, first_violating_index) for the router's repair moves."""

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


@dataclass
class ActionResult:
    duration: float
    xp_gained: int
    note: str
    # Time decomposition (sums to `duration`; travel is tracked separately by the engine).
    combat_s: float = 0.0        # TTK + acquire + loot
    interaction_s: float = 0.0   # accept/turnin/train/provider/gather/object/hearth
    downtime_s: float = 0.0      # eat/drink/bandage overhead folded into kill cycles

    def __post_init__(self) -> None:
        # Default: attribute an otherwise-uncategorized duration to interaction.
        if self.combat_s == 0.0 and self.interaction_s == 0.0 and self.downtime_s == 0.0:
            self.interaction_s = self.duration


def resolve_location(step: Step, state: CharacterState, world: World) -> Vec2 | None:
    """Where the character must be to perform `step`. None => stationary (no travel)."""
    if isinstance(step, Accept):
        return world.poi_pos_opt("GIVER", step.quest_id)   # None => auto/item-started, in place
    if isinstance(step, Turnin):
        return world.poi_pos_opt("TURNIN", step.quest_id)
    if isinstance(step, Work):
        if step.area_id is not None:
            return world.area(step.area_id).centroid
        ann = world.annotation(step.quest_id, step.obj_idx)
        return ann.provider_pos if ann else None  # QUEST_PROVIDED -> None (in bags)
    if isinstance(step, SetHearth):
        return world.poi_pos("HEARTH", step.poi_entry)
    if isinstance(step, Grind):
        return world.area(step.area_id).centroid
    if isinstance(step, Goto):
        t = step.target
        if isinstance(t, Coord):
            return Vec2(t.x, t.y)
        if isinstance(t, AreaRef):
            return world.area(t.area_id).centroid
        return world.poi_pos(t.kind, t.ref_id)  # PoiRef
    return None  # Train, Buy, Hearth (cast): stationary


def apply(step: Step, state: CharacterState, world: World, params: Params) -> ActionResult:
    """Mutate `state` for `step` (already at its location); return duration + XP + a note."""
    if isinstance(step, Goto):
        return ActionResult(0.0, 0, "travel")
    if isinstance(step, Accept):
        return _accept(step, state, world, params)
    if isinstance(step, Work):
        return _work(step, state, world, params)
    if isinstance(step, Turnin):
        return _turnin(step, state, world, params)
    if isinstance(step, Train):
        return _train(step, state, params)
    if isinstance(step, Buy):
        return _buy(step, state, world, params)
    if isinstance(step, SetHearth):
        state.hearth_poi = step.poi_entry
        return ActionResult(params.t_sethearth, 0, f"set hearth at {step.poi_entry}")
    if isinstance(step, Hearth):
        return ActionResult(params.t_hearth_cast, 0, "hearth")
    return _grind(step, state, world, params)  # Grind


# --- individual actions -----------------------------------------------------------------
def _accept(step: Accept, state: CharacterState, world: World, params: Params) -> ActionResult:
    q = world.quest(step.quest_id)
    if state.level < q.min_level:
        raise Infeasible(f"quest {q.id} requires level {q.min_level}, char is {state.level}")
    if q.required_classes and not (q.required_classes & (1 << (state.clazz - 1))):
        raise Infeasible(f"quest {q.id} class-restricted (mask {q.required_classes})")
    state.quest_log.setdefault(q.id, [0] * len(q.objectives))
    return ActionResult(params.t_accept, 0, f"accept {q.name!r}")


def _work(step: Work, state: CharacterState, world: World, params: Params) -> ActionResult:
    q = world.quest(step.quest_id)
    if q.id not in state.quest_log:
        raise Infeasible(f"WORK on quest {q.id} not in quest log (accept first)")
    obj = q.objectives[step.obj_idx]

    # Provider-based COLLECT (NULL drop_chance): item is quest-provided or filled at an object.
    if obj.kind == "COLLECT" and obj.drop_chance is None:
        ann = world.annotation(q.id, step.obj_idx)
        if ann is None:
            raise Infeasible(f"COLLECT {q.id}/{obj.idx} has NULL drop and no provider annotation")
        state.quest_log[q.id][obj.idx] = obj.count
        if ann.provider_kind == "QUEST_PROVIDED":
            return ActionResult(0.0, 0, f"{obj.kind}: quest-provided item (in bags)")
        return ActionResult(params.t_provider, 0, f"{obj.kind}: use provider {ann.provider_id}")

    # OBJECT: use N world objects (no kill XP).
    if obj.kind == "OBJECT":
        n = max(1, round(obj.count * step.frac))
        state.quest_log[q.id][obj.idx] = min(obj.count, state.quest_log[q.id][obj.idx] + n)
        dur = n * (params.t_provider + params.t_acquire_base)
        return ActionResult(dur, 0, f"OBJECT: use {n} object(s)")

    if obj.kind in ("ESCORT", "EXPLORE"):
        # Fixed-duration bucket (DESIGN §5.2); modeled as a flat provider-like interaction.
        return ActionResult(params.t_provider, 0, f"{obj.kind}: fixed-duration event")

    area = world.area(step.area_id) if step.area_id is not None else None
    _mark_progress(state, q.id, obj.idx, obj.count, step.frac)

    # Lootable COLLECT gathered from a world object (source_kind OBJECT, or an unlocated source
    # the compiled DB has no static spawn for): model as gather interactions, no kill XP.
    if obj.kind == "COLLECT" and (obj.source_kind != "CREATURE" or obj.source_id is None):
        opens = combat.expected_kills(obj.count, obj.drop_chance) * step.frac
        dur = opens * (params.t_provider + params.t_acquire_base)
        return ActionResult(dur, 0, f"COLLECT gather x{opens:.1f} (object source)")

    # KILL, or lootable COLLECT dropped by a creature: kill mobs. KILL uses count directly
    # (drop_chance is a COLLECT-only column, NULL for KILL); COLLECT uses count / drop_chance and
    # kills the source creature (source_id), not the item (target_id).
    mob_id = obj.target_id if obj.kind == "KILL" else obj.source_id
    if mob_id is None:
        raise Infeasible(f"objective {q.id}/{obj.idx} kind {obj.kind} has no combat source")
    mob = world.mob(mob_id)
    base_kills = float(obj.count) if obj.kind == "KILL" \
        else combat.expected_kills(obj.count, obj.drop_chance)
    exp_kills = base_kills * step.frac
    cycle, _var = combat.kill_cycle(state, params, mob, area)
    duration = cycle * exp_kills
    # Decompose: fighting (TTK+acquire+loot) vs downtime overhead (the multiplicative factor).
    from sim.params import band_for_level
    df = params.downtime_factor[band_for_level(state.level)]
    combat_s = duration / df
    per_kill = xp.kill_xp(state.level, mob.lvl_max, mob.elite)
    gained = int(round(per_kill * exp_kills))
    note = f"{obj.kind} {mob.name!r} x{exp_kills:.1f} (TTK-based; {per_kill} xp/kill)"
    return ActionResult(duration, gained, note, combat_s=combat_s, downtime_s=duration - combat_s)


def _mark_progress(state: CharacterState, qid: int, idx: int, count: int, frac: float) -> None:
    step_progress = count if frac >= 1.0 else max(1, round(count * frac))
    state.quest_log[qid][idx] = min(count, state.quest_log[qid][idx] + step_progress)


def _turnin(step: Turnin, state: CharacterState, world: World, params: Params) -> ActionResult:
    q = world.quest(step.quest_id)
    if q.id not in state.quest_log:
        raise Infeasible(f"TURNIN quest {q.id} not in quest log")
    progress = state.quest_log[q.id]
    for obj in q.objectives:
        if progress[obj.idx] < obj.count:
            raise Infeasible(f"TURNIN quest {q.id} objective {obj.idx} incomplete "
                             f"({progress[obj.idx]}/{obj.count})")
    # Reward choice: explicit item, else argmax slot-aware reward score (DESIGN §8.4). A weapon
    # candidate competes only against the incumbent in its OWN slot (ranged vs melee), because a
    # hunter carries both simultaneously — they never displace each other.
    chosen = _pick_reward(q, step.choice_item, world, state, params)
    note = f"turn in {q.name!r} (+{q.xp} xp)"
    if chosen is not None:
        item = world.item(chosen)
        slot = weapon_slot(item, params)
        if slot == "ranged" and item.weapon_dps is not None and item.weapon_dps > state.ranged_dps:
            note += f"; equip ranged {item.name!r} {state.ranged_dps:.2f}->{item.weapon_dps:.2f}"
            state.ranged_dps = item.weapon_dps
        elif slot == "melee" and item.weapon_dps is not None and item.weapon_dps > state.melee_dps:
            note += f"; equip melee {item.name!r} {state.melee_dps:.2f}->{item.weapon_dps:.2f}"
            state.melee_dps = item.weapon_dps
    state.gold_c += q.money
    del state.quest_log[q.id]
    state.completed.add(q.id)
    return ActionResult(params.t_turnin, q.xp, note)


def weapon_slot(item, params: Params) -> str | None:  # type: ignore[no-untyped-def]
    """Classify a reward item's weapon slot from inventory_type: 'ranged', 'melee', or None
    (not a weapon). Lets a candidate compete only within its own slot."""
    if item.slot is None:
        return None
    if item.slot in params_ranged(params):
        return "ranged"
    if item.slot in params_melee(params):
        return "melee"
    return None


def params_ranged(params: Params):  # type: ignore[no-untyped-def]
    from sim.params import RANGED_INV_TYPES
    return RANGED_INV_TYPES


def params_melee(params: Params):  # type: ignore[no-untyped-def]
    from sim.params import MELEE_INV_TYPES
    return MELEE_INV_TYPES


def _pick_reward(q, choice_item: int | None, world: World,  # type: ignore[no-untyped-def]
                 state: CharacterState, params: Params) -> int | None:
    if choice_item is not None:
        return choice_item
    if not q.reward_choices:
        return None
    best_id: int | None = None
    best_score = float("-inf")
    for c in q.reward_choices:
        item = world.items.get(c["item"])
        if item is None:
            continue
        # Weapon score = improvement over the incumbent in this item's OWN slot (0 if no gain);
        # non-weapons score on armor. This is what makes a staff compete with the melee slot only.
        slot = weapon_slot(item, params)
        gain = 0.0
        if slot == "ranged":
            gain = max(0.0, (item.weapon_dps or 0.0) - state.ranged_dps)
        elif slot == "melee":
            gain = max(0.0, (item.weapon_dps or 0.0) - state.melee_dps)
        score = params.reward_weapon_dps_weight * gain + params.reward_armor_weight * (item.armor or 0)
        if score > best_score:
            best_score, best_id = score, c["item"]
    return best_id


def _train(step: Train, state: CharacterState, params: Params) -> ActionResult:
    trained: list[str] = []
    for b in HUNTER_BUMPS:
        want = step.all or b.taught_spell in step.targets
        if want and b.active and b.level <= state.level and b.bump_id not in state.known_spell_bumps:
            state.known_spell_bumps.add(b.bump_id)
            trained.append(b.bump_id)
    if not trained:
        return ActionResult(0.0, 0, "train: nothing new")
    return ActionResult(params.t_train, 0, "train: " + ", ".join(trained))


def _buy(step: Buy, state: CharacterState, world: World, params: Params) -> ActionResult:
    item = world.item(step.item_id)
    state.supplies[item.name] = state.supplies.get(item.name, 0) + step.n
    return ActionResult(params.t_buy, 0, f"buy {step.n}x {item.name!r}")


def _grind(step: Grind, state: CharacterState, world: World, params: Params) -> ActionResult:
    mob = world.mob(step.mob_id)
    area = world.area(step.area_id)
    per_kill = xp.kill_xp(state.level, mob.lvl_max, mob.elite)
    if per_kill <= 0:
        raise Infeasible(f"GRIND target {mob.id} is gray (0 xp) at level {state.level}")
    cycle, _var = combat.kill_cycle(state, params, mob, area)
    kills = max(1, -(-step.xp_target // per_kill))  # ceil
    return ActionResult(cycle * kills, per_kill * kills, f"grind {mob.name!r} x{kills}")
