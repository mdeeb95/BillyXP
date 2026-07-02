"""Action DSL (DESIGN §7): step types, parse/serialize, and a validator that cross-checks every
quest/item/area/POI/mob id against world.sqlite. An unknown id is a HARD ERROR, not a warning
(CLAUDE.md rule 1 / the M1 brief) — the engine must never run a route that references a game
entity the compiled world does not contain.

Grammar (one step per line; `#` starts a comment; blank lines ignored):

    GOTO   <target>                      # target: xy:X:Y | poi:KIND:ID | area:ID
    ACCEPT <quest>                       # auto-travels to the quest giver POI
    WORK   <quest> <obj_idx> <area|-> [frac]   # kill/collect; '-' area for provider-based COLLECT
    TURNIN <quest> [choice_item]         # auto-travels to the turn-in POI
    TRAIN  <ALL | taught_spell_id...>    # apply trained EDPS breakpoints at a trainer
    BUY    <item> <n>
    SETHEARTH <poi_entry>                # bind at an innkeeper (POI kind HEARTH)
    HEARTH
    GRIND  <mob> <area> <xp_target>      # filler grind to an XP target

Steps that reference a world location (ACCEPT/WORK/TURNIN/TRAIN/BUY/SETHEARTH) are self-locating:
the engine travels from the current position to that step's location as part of the step, so a
hand-written route stays compact. GOTO is for explicit repositioning.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Union

from sim.world import World


# --- GOTO targets -----------------------------------------------------------------------
@dataclass(frozen=True)
class Coord:
    x: float
    y: float


@dataclass(frozen=True)
class PoiRef:
    kind: str            # GIVER | TURNIN | TRAINER | VENDOR | HEARTH | WAYPOINT
    ref_id: int


@dataclass(frozen=True)
class AreaRef:
    area_id: int


GotoTarget = Union[Coord, PoiRef, AreaRef]


# --- Steps ------------------------------------------------------------------------------
@dataclass(frozen=True)
class Goto:
    target: GotoTarget


@dataclass(frozen=True)
class Accept:
    quest_id: int


@dataclass(frozen=True)
class Work:
    quest_id: int
    obj_idx: int
    area_id: int | None          # None => provider-based COLLECT (annotation), no area
    frac: float = 1.0


@dataclass(frozen=True)
class Turnin:
    quest_id: int
    choice_item: int | None = None


@dataclass(frozen=True)
class Train:
    targets: tuple[int, ...] = ()    # taught_spell ids; empty + all=True means ALL
    all: bool = False


@dataclass(frozen=True)
class Buy:
    item_id: int
    n: int


@dataclass(frozen=True)
class SetHearth:
    poi_entry: int                   # innkeeper creature entry (POI kind HEARTH)


@dataclass(frozen=True)
class Hearth:
    pass


@dataclass(frozen=True)
class Grind:
    mob_id: int
    area_id: int
    xp_target: int


Step = Union[Goto, Accept, Work, Turnin, Train, Buy, SetHearth, Hearth, Grind]


@dataclass
class Route:
    steps: list[Step] = field(default_factory=list)
    comments: dict[int, str] = field(default_factory=dict)  # step index -> trailing comment


# --- Parse ------------------------------------------------------------------------------
class DslError(ValueError):
    """Raised on a malformed step or (during validation) an unknown world id."""


def parse_route(text: str, world: World | None = None) -> Route:
    """Parse route DSL text. If `world` is given, validate every id (unknown id -> DslError)."""
    route = Route()
    for lineno, raw in enumerate(text.splitlines(), start=1):
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        code, _, comment = line.partition("#")
        code = code.strip()
        if not code:
            continue
        try:
            step = _parse_step(code)
        except DslError as e:
            raise DslError(f"line {lineno}: {e}  [{raw!r}]") from None
        if comment.strip():
            route.comments[len(route.steps)] = comment.strip()
        route.steps.append(step)
    if world is not None:
        validate(route, world)
    return route


def _parse_step(code: str) -> Step:
    tok = code.split()
    op = tok[0].upper()
    args = tok[1:]
    if op == "GOTO":
        return Goto(_parse_goto_target(_need(args, 1, op)[0]))
    if op == "ACCEPT":
        return Accept(_int(_need(args, 1, op)[0], "quest"))
    if op == "WORK":
        a = _need(args, 3, op)
        area = None if a[2] == "-" else _int(a[2], "area")
        frac = float(a[3]) if len(a) >= 4 else 1.0
        return Work(_int(a[0], "quest"), _int(a[1], "obj_idx"), area, frac)
    if op == "TURNIN":
        a = _need(args, 1, op)
        choice = _int(a[1], "choice_item") if len(a) >= 2 else None
        return Turnin(_int(a[0], "quest"), choice)
    if op == "TRAIN":
        a = _need(args, 1, op)
        if len(a) == 1 and a[0].upper() == "ALL":
            return Train(all=True)
        return Train(targets=tuple(_int(x, "taught_spell") for x in a))
    if op == "BUY":
        a = _need(args, 2, op)
        return Buy(_int(a[0], "item"), _int(a[1], "n"))
    if op == "SETHEARTH":
        return SetHearth(_int(_need(args, 1, op)[0], "poi_entry"))
    if op == "HEARTH":
        return Hearth()
    if op == "GRIND":
        a = _need(args, 3, op)
        return Grind(_int(a[0], "mob"), _int(a[1], "area"), _int(a[2], "xp_target"))
    raise DslError(f"unknown op {op!r}")


def _parse_goto_target(token: str) -> GotoTarget:
    scheme, _, rest = token.partition(":")
    if scheme == "xy":
        xs, _, ys = rest.partition(":")
        return Coord(float(xs), float(ys))
    if scheme == "poi":
        kind, _, rid = rest.partition(":")
        return PoiRef(kind.upper(), _int(rid, "poi ref"))
    if scheme == "area":
        return AreaRef(_int(rest, "area"))
    raise DslError(f"bad GOTO target {token!r} (use xy:X:Y | poi:KIND:ID | area:ID)")


def _need(args: list[str], n: int, op: str) -> list[str]:
    if len(args) < n:
        raise DslError(f"{op} needs >= {n} arg(s), got {len(args)}")
    return args


def _int(s: str, what: str) -> int:
    try:
        return int(s)
    except ValueError:
        raise DslError(f"expected integer for {what}, got {s!r}") from None


# --- Validate (unknown id => hard error) ------------------------------------------------
def validate(route: Route, world: World) -> None:
    for i, step in enumerate(route.steps):
        try:
            _validate_step(step, world)
        except DslError as e:
            raise DslError(f"step {i} ({type(step).__name__}): {e}") from None


def _validate_step(step: Step, world: World) -> None:
    if isinstance(step, Accept):
        _check_quest(step.quest_id, world)
    elif isinstance(step, Turnin):
        q = _check_quest(step.quest_id, world)
        if step.choice_item is not None:
            valid = {c["item"] for c in q.reward_choices}
            if step.choice_item not in valid:
                raise DslError(f"choice_item {step.choice_item} not a reward choice of quest "
                               f"{q.id} (choices: {sorted(valid)})")
    elif isinstance(step, Work):
        q = _check_quest(step.quest_id, world)
        if not 0 <= step.obj_idx < len(q.objectives):
            raise DslError(f"obj_idx {step.obj_idx} out of range for quest {q.id} "
                           f"({len(q.objectives)} objectives)")
        if not 0.0 < step.frac <= 1.0:
            raise DslError(f"frac {step.frac} must be in (0, 1]")
        if step.area_id is not None and step.area_id not in world.areas:
            raise DslError(f"unknown area {step.area_id}")
        # A '-' area is valid only when the objective has no located area in the DB (a provider
        # COLLECT or an object-gather) AND a provider/gather annotation supplies a location — the
        # sim must never cost WORK against a location-less target (M1 review).
        obj = q.objectives[step.obj_idx]
        if step.area_id is None:
            if obj.area_id is not None:
                raise DslError(f"WORK {q.id} obj {step.obj_idx} has area {obj.area_id} in the DB — "
                               f"specify it instead of '-'")
            if world.annotation(q.id, step.obj_idx) is None:
                raise DslError(f"WORK {q.id} obj {step.obj_idx} has no area and no provider/gather "
                               f"annotation — cannot resolve where the work happens")
    elif isinstance(step, Train):
        for tid in step.targets:
            if tid not in {b.taught_spell for b in _HUNTER_BUMPS()}:
                raise DslError(f"taught_spell {tid} is not a known hunter breakpoint")
    elif isinstance(step, Buy):
        if step.item_id not in world.items:
            raise DslError(f"unknown item {step.item_id}")
        if step.n <= 0:
            raise DslError(f"BUY n must be positive, got {step.n}")
    elif isinstance(step, Grind):
        if step.mob_id not in world.mobs:
            raise DslError(f"unknown mob {step.mob_id}")
        if step.area_id not in world.areas:
            raise DslError(f"unknown area {step.area_id}")
    elif isinstance(step, Goto):
        t = step.target
        if isinstance(t, AreaRef) and t.area_id not in world.areas:
            raise DslError(f"unknown area {t.area_id}")
        if isinstance(t, PoiRef) and (t.kind, t.ref_id) not in world.pois:
            raise DslError(f"unknown POI {t.kind}:{t.ref_id}")
    elif isinstance(step, SetHearth):
        if ("HEARTH", step.poi_entry) not in world.pois:
            raise DslError(f"unknown HEARTH POI entry {step.poi_entry}")
    # Hearth: no ids to check.


def _check_quest(qid: int, world: World):  # type: ignore[no-untyped-def]
    if qid not in world.quests:
        raise DslError(f"unknown quest {qid}")
    return world.quests[qid]


def _HUNTER_BUMPS():  # type: ignore[no-untyped-def]
    from sim.params import HUNTER_BUMPS
    return HUNTER_BUMPS


# --- Serialize --------------------------------------------------------------------------
def serialize(route: Route) -> str:
    out: list[str] = []
    for i, step in enumerate(route.steps):
        line = _serialize_step(step)
        if i in route.comments:
            line += f"  # {route.comments[i]}"
        out.append(line)
    return "\n".join(out) + "\n"


def _serialize_step(step: Step) -> str:
    if isinstance(step, Goto):
        t = step.target
        if isinstance(t, Coord):
            return f"GOTO xy:{t.x}:{t.y}"
        if isinstance(t, PoiRef):
            return f"GOTO poi:{t.kind}:{t.ref_id}"
        return f"GOTO area:{t.area_id}"
    if isinstance(step, Accept):
        return f"ACCEPT {step.quest_id}"
    if isinstance(step, Work):
        area = "-" if step.area_id is None else str(step.area_id)
        frac = "" if step.frac == 1.0 else f" {step.frac}"
        return f"WORK {step.quest_id} {step.obj_idx} {area}{frac}"
    if isinstance(step, Turnin):
        return f"TURNIN {step.quest_id}" + (f" {step.choice_item}" if step.choice_item else "")
    if isinstance(step, Train):
        return "TRAIN ALL" if step.all else "TRAIN " + " ".join(str(t) for t in step.targets)
    if isinstance(step, Buy):
        return f"BUY {step.item_id} {step.n}"
    if isinstance(step, SetHearth):
        return f"SETHEARTH {step.poi_entry}"
    if isinstance(step, Hearth):
        return "HEARTH"
    return f"GRIND {step.mob_id} {step.area_id} {step.xp_target}"  # Grind


# Public alias so other modules (engine timeline labels) don't reach into a private name.
def serialize_step(step: Step) -> str:
    return _serialize_step(step)
