"""Loaded, typed world model over data/compiled/world.sqlite (DESIGN §4, §5.3).

Read-only: the engine never writes here. All game facts (quests, objectives, mobs, areas, POIs,
items, XP table, provider annotations) come from the compiled DB with provenance — nothing is
fabricated (CLAUDE.md rule 1). Lookups raise KeyError on an unknown id so the DSL validator and
engine fail loudly rather than silently approximating.
"""

from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from pathlib import Path

from sim.state import Vec2

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_DB = ROOT / "data" / "compiled" / "world.sqlite"


@dataclass(frozen=True)
class Objective:
    quest_id: int
    idx: int
    kind: str                    # KILL | COLLECT | OBJECT | EXPLORE | ESCORT
    target_id: int | None
    count: int
    drop_chance: float | None    # 0..1 for COLLECT; None -> provider via annotation
    source_id: int | None        # lootable COLLECT: source creature/GO entry (None if unlocated)
    source_kind: str | None      # CREATURE | OBJECT
    area_id: int | None
    out_of_zone: bool


@dataclass(frozen=True)
class Quest:
    id: int
    name: str
    min_level: int
    quest_level: int
    giver_kind: str | None
    giver_id: int | None
    turnin_kind: str | None
    turnin_id: int | None
    prev_quest: int | None
    exclusive_group: int | None
    required_classes: int
    required_races: int
    event_id: int | None
    xp: int
    money: int
    reward_choices: list[dict[str, int]]
    objectives: tuple[Objective, ...]


@dataclass(frozen=True)
class Mob:
    id: int
    name: str
    lvl_min: int
    lvl_max: int
    hp_min: float | None
    hp_max: float | None
    armor: float | None
    dps_est: float | None
    elite: bool


@dataclass(frozen=True)
class Area:
    id: int
    target_entry: int
    target_kind: str
    centroid: Vec2
    radius: float
    n_spawns: int
    density: float


@dataclass(frozen=True)
class Item:
    id: int
    name: str
    slot: int | None
    weapon_dps: float | None
    armor: int | None
    stats: dict[str, int]


@dataclass(frozen=True)
class Annotation:
    quest_id: int
    obj_idx: int
    provider_kind: str           # QUEST_PROVIDED | FILL_OBJECT
    provider_id: int | None
    provider_spell: int | None
    provider_pos: Vec2 | None
    source: str
    note: str | None


class World:
    """In-memory index over the compiled world DB."""

    def __init__(self, db_path: Path | str = DEFAULT_DB) -> None:
        self.db_path = Path(db_path)
        if not self.db_path.exists():
            raise SystemExit(f"world: {self.db_path} not found — run `make etl` first.")
        c = sqlite3.connect(f"file:{self.db_path}?mode=ro", uri=True)
        try:
            self._load(c)
        finally:
            c.close()

    def _load(self, c: sqlite3.Connection) -> None:
        self.meta: dict[str, str] = {
            str(k): str(v) for k, v in c.execute("SELECT key, value FROM meta")
        }
        self.xp_to_next: dict[int, int] = {
            int(lvl): int(xp) for lvl, xp in c.execute("SELECT level, xp_to_next FROM xp_levels")
        }
        self.mobs: dict[int, Mob] = {}
        for r in c.execute(
            "SELECT id,name,lvl_min,lvl_max,hp_min,hp_max,armor,dps_est,elite FROM mobs"
        ):
            self.mobs[int(r[0])] = Mob(
                int(r[0]), str(r[1]), int(r[2]), int(r[3]),
                _f(r[4]), _f(r[5]), _f(r[6]), _f(r[7]), bool(r[8]),
            )
        self.areas: dict[int, Area] = {}
        for r in c.execute(
            "SELECT id,target_entry,target_kind,centroid_x,centroid_y,radius,n_spawns,density FROM areas"
        ):
            self.areas[int(r[0])] = Area(
                int(r[0]), int(r[1]), str(r[2]), Vec2(float(r[3]), float(r[4])),
                float(r[5]), int(r[6]), float(r[7]),
            )
        self.items: dict[int, Item] = {}
        for r in c.execute("SELECT id,name,slot,weapon_dps,armor,stats FROM items"):
            self.items[int(r[0])] = Item(
                int(r[0]), str(r[1]), _i(r[2]), _f(r[3]), _i(r[4]),
                json.loads(r[5]) if r[5] else {},
            )
        # POIs: (kind, ref_id) -> Vec2. A quest giver/turn-in has one representative POI.
        self.pois: dict[tuple[str, int], Vec2] = {}
        for kind, ref_id, x, y in c.execute("SELECT kind, ref_id, x, y FROM pois"):
            self.pois[(str(kind), int(ref_id))] = Vec2(float(x), float(y))
        # Provider annotations for NULL-drop COLLECT (ETL step 0b).
        self.annotations: dict[tuple[int, int], Annotation] = {}
        for r in c.execute(
            "SELECT quest_id,obj_idx,provider_kind,provider_id,provider_spell,"
            "provider_x,provider_y,source,note FROM manual_annotations"
        ):
            pos = Vec2(float(r[5]), float(r[6])) if r[5] is not None and r[6] is not None else None
            self.annotations[(int(r[0]), int(r[1]))] = Annotation(
                int(r[0]), int(r[1]), str(r[2]), _i(r[3]), _i(r[4]), pos, str(r[7]),
                str(r[8]) if r[8] is not None else None,
            )
        # Objectives grouped by quest.
        objs: dict[int, list[Objective]] = {}
        for r in c.execute(
            "SELECT quest_id,idx,kind,target_id,count,drop_chance,source_id,source_kind,"
            "area_id,out_of_zone FROM objectives"
        ):
            objs.setdefault(int(r[0]), []).append(Objective(
                int(r[0]), int(r[1]), str(r[2]), _i(r[3]), int(r[4]),
                _f(r[5]), _i(r[6]), _s(r[7]), _i(r[8]), bool(r[9]),
            ))
        # Quests.
        self.quests: dict[int, Quest] = {}
        for r in c.execute(
            "SELECT id,name,min_level,quest_level,giver_kind,giver_id,turnin_kind,turnin_id,"
            "prev_quest,exclusive_group,required_classes,required_races,event_id,xp,money,"
            "reward_choices FROM quests"
        ):
            qid = int(r[0])
            self.quests[qid] = Quest(
                qid, str(r[1]), int(r[2]), int(r[3]), _s(r[4]), _i(r[5]), _s(r[6]), _i(r[7]),
                _i(r[8]), _i(r[9]), int(r[10]), int(r[11]), _i(r[12]), int(r[13]), int(r[14]),
                json.loads(r[15]) if r[15] else [],
                tuple(sorted(objs.get(qid, []), key=lambda o: o.idx)),
            )

    # --- lookups (raise on unknown id) --------------------------------------------------
    def quest(self, qid: int) -> Quest:
        return self.quests[qid]

    def mob(self, mob_id: int) -> Mob:
        return self.mobs[mob_id]

    def area(self, area_id: int) -> Area:
        return self.areas[area_id]

    def item(self, item_id: int) -> Item:
        return self.items[item_id]

    def annotation(self, quest_id: int, obj_idx: int) -> Annotation | None:
        return self.annotations.get((quest_id, obj_idx))

    def poi_pos(self, kind: str, ref_id: int) -> Vec2:
        return self.pois[(kind, ref_id)]

    def poi_pos_opt(self, kind: str, ref_id: int) -> Vec2 | None:
        """POI position, or None if absent (e.g. a giver-less auto/item-started quest)."""
        return self.pois.get((kind, ref_id))

    def xp_for_level(self, level: int) -> int:
        return self.xp_to_next[level]


def _f(v: object) -> float | None:
    return float(v) if v is not None else None  # type: ignore[arg-type]


def _i(v: object) -> int | None:
    return int(v) if v is not None else None  # type: ignore[arg-type]


def _s(v: object) -> str | None:
    return str(v) if v is not None else None
