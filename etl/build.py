"""Build data/compiled/world.sqlite from the raw VMaNGOS SQLite world DB.

Deterministic: same source dump -> same compiled DB. All game facts come from the source
dump (with src_table/src_pk provenance); nothing is fabricated. See etl/NOTES.md for the
confirmed source-schema mapping and the DESIGN §5.2 wrinkle resolutions, and
data/raw/PROVENANCE.md for source lineage.

Run:  make etl   (or  uv run python -m etl.build)
"""

from __future__ import annotations

import json
import re
import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np
from scipy.spatial import cKDTree  # type: ignore[import-untyped]

# --- Paths ------------------------------------------------------------------------------
ROOT = Path(__file__).resolve().parent.parent
SRC_DB = ROOT / "data" / "raw" / "sqlite-dump" / "mangos.sqlite"
OUT_DB = ROOT / "data" / "compiled" / "world.sqlite"
SCHEMA_SQL = ROOT / "etl" / "schema.sql"

# --- ETL tunables (bounding box; ETL-side, not sim params). See etl/NOTES.md §2. --------
KALIMDOR_MAP = 1               # verified anchor: Kalimdor is map 1
SEED_DBSCAN_EPS = 1500.0       # yd; groups the ~two dozen Teldrassil givers into one cluster,
SEED_DBSCAN_MIN = 2            #     isolates the lone Moonglade outlier (Keeper Remulos)
BOX_MARGIN_YD = 600.0          # pad the giver-cluster bbox to capture surrounding spawns
AREA_DBSCAN_EPS = 60.0         # yd; spatial clustering of spawns into routing "areas"
AREA_DBSCAN_MIN = 3
PATCH_ERA = 10                 # 1.12 content level in this dump's patch encoding

# Quests to spot-check quest XP against classic.wowhead.com (etl/NOTES.md §3).
WOWHEAD_XP_CHECK = (456, 3521, 920)


def dbscan(points: np.ndarray, eps: float, min_samples: int) -> np.ndarray:
    """Minimal DBSCAN over 2D points using a KD-tree. Returns cluster labels (-1 = noise).

    Deterministic: labels are assigned in ascending point-index order.
    """
    n = len(points)
    labels = np.full(n, -1, dtype=np.int64)
    if n == 0:
        return labels
    tree = cKDTree(points)
    neighbors: list[list[int]] = tree.query_ball_point(points, r=eps)  # type: ignore[assignment]
    core = np.array([len(neighbors[i]) >= min_samples for i in range(n)], dtype=bool)
    cluster = 0
    for i in range(n):
        if labels[i] != -1 or not core[i]:
            continue
        labels[i] = cluster
        stack = [i]
        while stack:
            p = stack.pop()
            if not core[p]:
                continue
            for q in neighbors[p]:
                if labels[q] == -1:
                    labels[q] = cluster
                    stack.append(q)
        cluster += 1
    return labels


@dataclass(frozen=True)
class Box:
    x0: float
    x1: float
    y0: float
    y1: float

    def contains(self, x: float, y: float) -> bool:
        return self.x0 <= x <= self.x1 and self.y0 <= y <= self.y1


def resolve_teldrassil(src: sqlite3.Connection) -> tuple[int, list[int]]:
    """Find Teldrassil's zone id and sort ids from area_template BY NAME (not from memory)."""
    row = src.execute(
        "SELECT entry, map_id FROM area_template WHERE lower(name) = 'teldrassil'"
    ).fetchone()
    if row is None:
        raise SystemExit("ETL: could not find area 'Teldrassil' in area_template — stop.")
    zone_id, map_id = int(row[0]), int(row[1])
    if map_id != KALIMDOR_MAP:
        raise SystemExit(f"ETL: Teldrassil map_id={map_id}, expected {KALIMDOR_MAP} — stop.")
    # Sub-sorts of the zone (Shadowglen etc.) — quests sort under these ids too.
    subs = [
        int(r[0])
        for r in src.execute(
            "SELECT entry FROM area_template WHERE zone_id = ?", (zone_id,)
        )
    ]
    return zone_id, sorted({zone_id, *subs})


def zone_quest_ids(src: sqlite3.Connection, sort_ids: list[int]) -> list[int]:
    """Distinct quest entries sorted to the zone (ZoneOrSort in the given ids)."""
    ph = ",".join("?" * len(sort_ids))
    rows = src.execute(
        f"SELECT DISTINCT entry FROM quest_template WHERE ZoneOrSort IN ({ph})", sort_ids
    ).fetchall()
    return sorted(int(r[0]) for r in rows)


def quest_relations(
    src: sqlite3.Connection, quest_ids: list[int]
) -> tuple[dict[int, list[tuple[str, int]]], dict[int, list[tuple[str, int]]]]:
    """Return giver and turn-in (kind, entry) lists per quest from the relation tables."""
    givers: dict[int, list[tuple[str, int]]] = {q: [] for q in quest_ids}
    turnins: dict[int, list[tuple[str, int]]] = {q: [] for q in quest_ids}
    qset = set(quest_ids)
    specs = [
        ("creature_questrelation", "CREATURE", givers),
        ("gameobject_questrelation", "OBJECT", givers),
        ("creature_involvedrelation", "CREATURE", turnins),
        ("gameobject_involvedrelation", "OBJECT", turnins),
    ]
    for table, kind, target in specs:
        for npc_id, quest in src.execute(f"SELECT id, quest FROM {table}"):
            if int(quest) in qset:
                target[int(quest)].append((kind, int(npc_id)))
    return givers, turnins


def load_spawn_positions(
    src: sqlite3.Connection,
) -> tuple[dict[int, list[tuple[int, float, float, float, int]]], dict[int, list[tuple[int, float, float, float, int]]]]:
    """entry -> [(guid, x, y, z, respawn_s)] for creatures and gameobjects, patch-valid, map 1."""

    def load(table: str) -> dict[int, list[tuple[int, float, float, float, int]]]:
        out: dict[int, list[tuple[int, float, float, float, int]]] = {}
        rows = src.execute(
            f"""SELECT guid, id, position_x, position_y, position_z, spawntimesecsmin
                FROM {table}
                WHERE map = ? AND patch_min <= ? AND patch_max >= ?""",
            (KALIMDOR_MAP, PATCH_ERA, PATCH_ERA),
        ).fetchall()
        for guid, entry, x, y, z, resp in rows:
            out.setdefault(int(entry), []).append(
                (int(guid), float(x), float(y), float(z), int(resp))
            )
        return out

    return load("creature"), load("gameobject")


def derive_box(
    givers: dict[int, list[tuple[str, int]]],
    creature_spawns: dict[int, list[tuple[int, float, float, float, int]]],
    gameobject_spawns: dict[int, list[tuple[int, float, float, float, int]]],
    turnins: dict[int, list[tuple[str, int]]],
) -> Box:
    """Seed the box from giver/turn-in spawns via DBSCAN largest cluster, then pad.

    DBSCAN isolates the Moonglade outlier (Keeper Remulos) as noise so it does not
    inflate the box (etl/NOTES.md §2).
    """
    pts: list[tuple[float, float]] = []
    for rel in (givers, turnins):
        for entries in rel.values():
            for kind, entry in entries:
                spawns = creature_spawns if kind == "CREATURE" else gameobject_spawns
                for _guid, x, y, _z, _r in spawns.get(entry, []):
                    pts.append((x, y))
    if not pts:
        raise SystemExit("ETL: no giver/turn-in spawns found — cannot seed bounding box.")
    arr = np.array(sorted(pts))
    labels = dbscan(arr, SEED_DBSCAN_EPS, SEED_DBSCAN_MIN)
    valid = labels[labels >= 0]
    if len(valid) == 0:
        raise SystemExit("ETL: giver/turn-in DBSCAN produced no cluster — widen SEED eps.")
    counts = np.bincount(valid)
    main = int(np.argmax(counts))
    core = arr[labels == main]
    return Box(
        x0=float(core[:, 0].min()) - BOX_MARGIN_YD,
        x1=float(core[:, 0].max()) + BOX_MARGIN_YD,
        y0=float(core[:, 1].min()) - BOX_MARGIN_YD,
        y1=float(core[:, 1].max()) + BOX_MARGIN_YD,
    )


def main() -> None:
    if not SRC_DB.exists():
        raise SystemExit(f"ETL: source dump not found at {SRC_DB} (see data/raw/PROVENANCE.md).")
    OUT_DB.parent.mkdir(parents=True, exist_ok=True)

    src = sqlite3.connect(f"file:{SRC_DB}?mode=ro", uri=True)
    src.row_factory = None

    zone_id, sort_ids = resolve_teldrassil(src)
    quest_ids = zone_quest_ids(src, sort_ids)
    givers, turnins = quest_relations(src, quest_ids)
    creature_spawns, gameobject_spawns = load_spawn_positions(src)
    box = derive_box(givers, creature_spawns, gameobject_spawns, turnins)
    print(f"ETL: Teldrassil zone_id={zone_id}, sort_ids={sort_ids}")
    print(f"ETL: {len(quest_ids)} zone quests; box "
          f"x[{box.x0:.0f}..{box.x1:.0f}] y[{box.y0:.0f}..{box.y1:.0f}]")

    if OUT_DB.exists():
        OUT_DB.unlink()
    out = sqlite3.connect(OUT_DB)
    out.executescript(SCHEMA_SQL.read_text())

    _write_meta(out, src, zone_id, sort_ids, box, quest_ids)
    _write_xp_levels(out, src)
    spawn_entries = _write_spawns(out, creature_spawns, gameobject_spawns, box)
    obj_targets, collect_src = _write_quests_and_objectives(
        out, src, quest_ids, givers, turnins, creature_spawns, gameobject_spawns, box
    )
    _write_mobs(out, src, spawn_entries["CREATURE"] | obj_targets)
    _write_areas_and_link(out, src, obj_targets, collect_src, box)
    _write_pois(out, src, quest_ids, givers, turnins, creature_spawns, gameobject_spawns, box)
    _write_items(out, src, quest_ids)
    _write_manual_annotations(out, src)

    out.commit()
    _wowhead_note(out)
    out.close()
    src.close()
    print(f"ETL: wrote {OUT_DB}")


# --- writers ----------------------------------------------------------------------------

def _write_meta(
    out: sqlite3.Connection, src: sqlite3.Connection, zone_id: int,
    sort_ids: list[int], box: Box, quest_ids: list[int],
) -> None:
    ver = src.execute(
        "SELECT value FROM meta WHERE key IN ('DB_version','version') LIMIT 1"
    ).fetchone() if _has_table(src, "meta") else None
    items = {
        "source_db": "vmangos mangos.sqlite (commit b40576b, see data/raw/PROVENANCE.md)",
        "source_version": str(ver[0]) if ver else "see PROVENANCE.md",
        "teldrassil_zone_id": str(zone_id),
        "zone_sort_ids": json.dumps(sort_ids),
        "bounding_box": json.dumps({"x0": box.x0, "x1": box.x1, "y0": box.y0, "y1": box.y1}),
        "n_zone_quests": str(len(quest_ids)),
        "patch_era": str(PATCH_ERA),
    }
    out.executemany("INSERT INTO meta(key, value) VALUES (?, ?)", sorted(items.items()))


def _has_table(conn: sqlite3.Connection, name: str) -> bool:
    return conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (name,)
    ).fetchone() is not None


def _write_xp_levels(out: sqlite3.Connection, src: sqlite3.Connection) -> None:
    rows = src.execute(
        "SELECT lvl, xp_for_next_level FROM player_xp_for_level WHERE lvl <= 15 ORDER BY lvl"
    ).fetchall()
    out.executemany(
        "INSERT INTO xp_levels(level, xp_to_next) VALUES (?, ?)",
        [(int(l), int(x)) for l, x in rows],
    )
    anchor = out.execute("SELECT xp_to_next FROM xp_levels WHERE level = 1").fetchone()
    if anchor is None or int(anchor[0]) != 400:
        raise SystemExit(f"ETL: XP anchor check failed (1->2 should be 400, got {anchor}).")


def _write_spawns(
    out: sqlite3.Connection,
    creature_spawns: dict[int, list[tuple[int, float, float, float, int]]],
    gameobject_spawns: dict[int, list[tuple[int, float, float, float, int]]],
    box: Box,
) -> dict[str, set[int]]:
    entries: dict[str, set[int]] = {"CREATURE": set(), "OBJECT": set()}
    rows: list[tuple[int, str, int, float, float, float, int, str, int]] = []
    for kind, src_table, spawns in (
        ("CREATURE", "creature", creature_spawns),
        ("OBJECT", "gameobject", gameobject_spawns),
    ):
        for entry, plist in spawns.items():
            for guid, x, y, z, resp in plist:
                if box.contains(x, y):
                    rows.append((guid, kind, entry, x, y, z, resp, src_table, guid))
                    entries[kind].add(entry)
    rows.sort(key=lambda r: (r[1], r[0]))
    out.executemany(
        "INSERT INTO spawns(guid, kind, entry, x, y, z, respawn_s, src_table, src_pk)"
        " VALUES (?,?,?,?,?,?,?,?,?)",
        rows,
    )
    return entries


def _pick_poi(
    entries: list[tuple[str, int]],
    creature_spawns: dict[int, list[tuple[int, float, float, float, int]]],
    gameobject_spawns: dict[int, list[tuple[int, float, float, float, int]]],
    box: Box,
) -> tuple[str, int, float, float, bool] | None:
    """Pick a representative (kind, entry, x, y, in_box) for a giver/turn-in set.

    Prefer an in-box spawn; fall back to any spawn (flagged out-of-box).
    """
    fallback: tuple[str, int, float, float, bool] | None = None
    for kind, entry in sorted(entries):
        spawns = creature_spawns if kind == "CREATURE" else gameobject_spawns
        for _guid, x, y, _z, _r in sorted(spawns.get(entry, [])):
            if box.contains(x, y):
                return (kind, entry, x, y, True)
            if fallback is None:
                fallback = (kind, entry, x, y, False)
    return fallback


def _write_quests_and_objectives(
    out: sqlite3.Connection, src: sqlite3.Connection, quest_ids: list[int],
    givers: dict[int, list[tuple[str, int]]], turnins: dict[int, list[tuple[str, int]]],
    creature_spawns: dict[int, list[tuple[int, float, float, float, int]]],
    gameobject_spawns: dict[int, list[tuple[int, float, float, float, int]]],
    box: Box,
) -> tuple[set[int], dict[tuple[int, int], tuple[str, int]]]:
    """Write quests + objectives. Returns (obj_targets, collect_src): the set of area target
    entries (KILL/OBJECT targets + lootable-COLLECT sources) and the per-COLLECT source map."""
    obj_targets: set[int] = set()
    collect_src: dict[tuple[int, int], tuple[str, int]] = {}
    ph = ",".join("?" * len(quest_ids))
    # New columns (RequiredClasses, RequiredRaces, SrcItemId) are appended AFTER the existing
    # selection so downstream positional indices (r[0]..r[42]) are unchanged. See NOTES.md §12.
    qrows = src.execute(
        f"""SELECT entry, patch, Title, MinLevel, QuestLevel, ZoneOrSort, RewXP,
                   RewOrReqMoney, PrevQuestId, ExclusiveGroup, SpecialFlags,
                   ReqCreatureOrGOId1, ReqCreatureOrGOId2, ReqCreatureOrGOId3, ReqCreatureOrGOId4,
                   ReqCreatureOrGOCount1, ReqCreatureOrGOCount2, ReqCreatureOrGOCount3, ReqCreatureOrGOCount4,
                   ReqItemId1, ReqItemId2, ReqItemId3, ReqItemId4,
                   ReqItemCount1, ReqItemCount2, ReqItemCount3, ReqItemCount4,
                   ReqSourceId1, ReqSourceId2, ReqSourceId3, ReqSourceId4,
                   RewChoiceItemId1, RewChoiceItemId2, RewChoiceItemId3,
                   RewChoiceItemId4, RewChoiceItemId5, RewChoiceItemId6,
                   RewChoiceItemCount1, RewChoiceItemCount2, RewChoiceItemCount3,
                   RewChoiceItemCount4, RewChoiceItemCount5, RewChoiceItemCount6,
                   RequiredClasses, RequiredRaces, SrcItemId
            FROM quest_template
            WHERE entry IN ({ph}) AND patch <= ?
            ORDER BY entry, patch""",
        (*quest_ids, PATCH_ERA),
    ).fetchall()
    best: dict[int, tuple[Any, ...]] = {}  # sqlite rows (mixed types) -> Any elements
    for r in qrows:
        best[int(r[0])] = r  # later (higher patch) overwrites -> max patch kept

    # Event/holiday gating: game_event_quest(quest, event) -> game_event(entry, holiday).
    events: dict[int, tuple[int, int | None]] = {}  # quest_id -> (event_id, holiday)
    ev_holiday = {int(e): (int(h) if h is not None else None)
                  for e, h in src.execute("SELECT entry, holiday FROM game_event")}
    for q, ev in src.execute("SELECT quest, event FROM game_event_quest"):
        if int(q) in best:
            events[int(q)] = (int(ev), ev_holiday.get(int(ev)))

    q_out: list[tuple[object, ...]] = []
    o_out: list[tuple[object, ...]] = []
    for entry in quest_ids:
        r = best.get(entry)
        if r is None:
            continue
        giver = _pick_poi(givers[entry], creature_spawns, gameobject_spawns, box)
        turnin = _pick_poi(turnins[entry], creature_spawns, gameobject_spawns, box)
        gk, gid = (giver[0], giver[1]) if giver else (None, None)
        tk, tid = (turnin[0], turnin[1]) if turnin else (None, None)
        out_of_zone = int(
            (giver is not None and not giver[4]) or (turnin is not None and not turnin[4])
        )
        choices = [
            {"item": int(r[31 + i]), "count": int(r[37 + i])}
            for i in range(6)
            if int(r[31 + i]) != 0
        ]
        ev = events.get(entry)
        q_out.append((
            entry, r[2], int(r[3]), int(r[4]), gk, gid, tk, tid,
            int(r[8]) or None, int(r[9]) or None,
            int(r[43]), int(r[44]),                       # required_classes, required_races
            ev[0] if ev else None, ev[1] if ev else None,  # event_id, event_holiday
            int(r[6]), max(int(r[7]), 0),
            json.dumps(choices) if choices else None, int(r[5]), out_of_zone,
            "quest_template", entry,
        ))

        special = int(r[10])
        idx = 0
        has_target = False
        # KILL / OBJECT objectives (ReqCreatureOrGOId: >0 creature, <0 gameobject)
        for j in range(4):
            cid = int(r[11 + j])
            cnt = int(r[15 + j])
            if cid == 0:
                continue
            has_target = True
            kind = "KILL" if cid > 0 else "OBJECT"
            target = abs(cid)
            obj_targets.add(target)
            in_box = _target_in_box(target, kind, creature_spawns, gameobject_spawns, box)
            o_out.append((entry, idx, kind, target, cnt or 1, None, None, None, None,
                          int(not in_box)))
            idx += 1
        # COLLECT objectives (ReqItemId). A lootable COLLECT (drop_chance found) is linked to a
        # representative source entity so it gets an area & a combat/gather source; a NULL-drop
        # COLLECT routes through a provider annotation (ETL step 0b) instead.
        for j in range(4):
            iid = int(r[19 + j])
            cnt = int(r[23 + j])
            if iid == 0:
                continue
            has_target = True
            src_ids = {int(r[27 + k]) for k in range(4)}
            source_kind: str | None = None
            source_id: int | None = None
            if iid in src_ids:
                drop = 1.0  # quest-provided source item (ReqSourceId); in bags, no kills
            else:
                drop, sources = _drop_chance(src, iid)
                if drop is not None:
                    rep = _pick_source(sources, creature_spawns, gameobject_spawns, box)
                    if rep is not None:
                        source_kind, source_id = rep
                        obj_targets.add(source_id)
                        collect_src[(entry, idx)] = (source_kind, source_id)
            o_out.append((entry, idx, "COLLECT", iid, cnt or 1, drop, source_id, source_kind,
                          None, 0))
            idx += 1
        # Escort / event (SpecialFlags EXPLORATION_OR_EVENT, no kill/collect) -> ESCORT
        if not has_target and (special & 0x2):
            o_out.append((entry, idx, "ESCORT", None, 1, None, None, None, None, 0))

    out.executemany(
        "INSERT INTO quests(id,name,min_level,quest_level,giver_kind,giver_id,turnin_kind,"
        "turnin_id,prev_quest,exclusive_group,required_classes,required_races,event_id,"
        "event_holiday,xp,money,reward_choices,zone_or_sort,out_of_zone,src_table,src_pk)"
        " VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        q_out,
    )
    out.executemany(
        "INSERT INTO objectives(quest_id,idx,kind,target_id,count,drop_chance,source_id,"
        "source_kind,area_id,out_of_zone) VALUES (?,?,?,?,?,?,?,?,?,?)",
        o_out,
    )
    return obj_targets, collect_src


def _target_in_box(
    target: int, kind: str,
    creature_spawns: dict[int, list[tuple[int, float, float, float, int]]],
    gameobject_spawns: dict[int, list[tuple[int, float, float, float, int]]],
    box: Box,
) -> bool:
    spawns = creature_spawns if kind == "KILL" else gameobject_spawns
    return any(box.contains(x, y) for _g, x, y, _z, _r in spawns.get(target, []))


def _drop_chance(
    src: sqlite3.Connection, item_id: int
) -> tuple[float | None, list[tuple[str, int]]]:
    """Look up a quest item's drop chance + its source entities from loot tables (mangos:
    negative = quest drop). Returns (chance, sources) where sources is [(kind, entry)] over
    creature and gameobject loot tables — used to give a lootable COLLECT an area & combat source.
    """
    sources: list[tuple[str, int]] = []
    best_abs = 0.0
    for kind, table in (("CREATURE", "creature_loot_template"),
                        ("OBJECT", "gameobject_loot_template")):
        for entry, chance in src.execute(
            f"SELECT entry, ChanceOrQuestChance FROM {table} WHERE item = ?", (item_id,)
        ):
            sources.append((kind, int(entry)))
            best_abs = max(best_abs, abs(float(chance)))
    if not sources or best_abs == 0.0:
        return None, sources
    return min(best_abs / 100.0, 1.0), sources


def _pick_source(
    sources: list[tuple[str, int]],
    creature_spawns: dict[int, list[tuple[int, float, float, float, int]]],
    gameobject_spawns: dict[int, list[tuple[int, float, float, float, int]]],
    box: Box,
) -> tuple[str, int] | None:
    """Representative source for a lootable COLLECT: the source entity with the most in-box
    spawns (tie-break lowest entry). Deterministic."""
    best: tuple[int, str, int] | None = None  # (-n_inbox, kind, entry) for min()
    for kind, entry in sources:
        spawns = creature_spawns if kind == "CREATURE" else gameobject_spawns
        n = sum(1 for _g, x, y, _z, _r in spawns.get(entry, []) if box.contains(x, y))
        key = (-n, kind, entry)
        if n > 0 and (best is None or key < best):
            best = key
    return (best[1], best[2]) if best else None


def _write_mobs(out: sqlite3.Connection, src: sqlite3.Connection, entries: set[int]) -> None:
    if not entries:
        return
    # class/level stats lookup
    stats: dict[tuple[int, int], tuple[float, float, float]] = {}
    for cls, lvl, hp, armor, dmg in src.execute(
        "SELECT class, level, health, armor, melee_damage FROM creature_classlevelstats"
    ):
        stats[(int(cls), int(lvl))] = (float(hp), float(armor), float(dmg))

    rows: list[tuple[object, ...]] = []
    ph = ",".join("?" * len(entries))
    ent = sorted(entries)
    # Prefer the highest-patch template row per entry.
    tmpl: dict[int, tuple[Any, ...]] = {}  # sqlite rows -> Any elements
    for r in src.execute(
        f"""SELECT entry, patch, name, level_min, level_max, unit_class, health_multiplier,
                   armor_multiplier, damage_multiplier, base_attack_time, rank
            FROM creature_template WHERE entry IN ({ph}) ORDER BY entry, patch""",
        ent,
    ):
        tmpl[int(r[0])] = r
    for entry in ent:
        r = tmpl.get(entry)
        if r is None:
            continue
        name = str(r[2])
        lmin, lmax, ucls = int(r[3]), int(r[4]), int(r[5])
        hmul, amul, dmul = float(r[6]), float(r[7]), float(r[8])
        bat = int(r[9]) or 2000
        rank = int(r[10])
        s_min = stats.get((ucls, lmin))
        s_max = stats.get((ucls, lmax))
        hp_min = s_min[0] * hmul if s_min else None
        hp_max = s_max[0] * hmul if s_max else None
        armor = s_max[1] * amul if s_max else None
        dps = (s_max[2] * dmul / (bat / 1000.0)) if s_max else None
        rows.append((
            entry, name, lmin, lmax, hp_min, hp_max, armor, dps,
            int(rank > 0), None, "creature_template", entry,
        ))
    out.executemany(
        "INSERT INTO mobs(id,name,lvl_min,lvl_max,hp_min,hp_max,armor,dps_est,elite,"
        "archetype,src_table,src_pk) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
        rows,
    )


def _write_areas_and_link(
    out: sqlite3.Connection, src: sqlite3.Connection, obj_targets: set[int],
    collect_src: dict[tuple[int, int], tuple[str, int]], box: Box,
) -> None:
    """DBSCAN spawns of each objective target into areas; link objectives to their densest area.
    KILL/OBJECT link by target entry; lootable COLLECT links by (quest_id, idx) to its source
    entity's area (collect_src)."""
    _ = box  # spawns already box-filtered upstream; kept for signature parity
    area_rows: list[tuple[object, ...]] = []
    area_id = 1
    target_to_area: dict[tuple[int, str], int] = {}
    entry_to_area: dict[int, int] = {}
    # Read in-box spawns straight from the compiled table (already filtered).
    spawns_by_entry: dict[int, list[tuple[str, float, float]]] = {}
    for kind, entry, x, y in out.execute("SELECT kind, entry, x, y FROM spawns"):
        spawns_by_entry.setdefault(int(entry), []).append((str(kind), float(x), float(y)))

    for target in sorted(obj_targets):
        pts_all = spawns_by_entry.get(target, [])
        if not pts_all:
            continue
        kind = pts_all[0][0]
        arr = np.array([[p[1], p[2]] for p in pts_all])
        labels = dbscan(arr, AREA_DBSCAN_EPS, AREA_DBSCAN_MIN)
        best_area_for_target: tuple[int, int] | None = None  # (area_id, n_spawns)
        for cl in sorted(set(int(v) for v in labels if v >= 0)):
            pts = arr[labels == cl]
            cx, cy = float(pts[:, 0].mean()), float(pts[:, 1].mean())
            radius = float(np.sqrt(((pts - [cx, cy]) ** 2).sum(axis=1)).max())
            n = len(pts)
            density = n / (np.pi * radius**2) if radius > 0 else float(n)
            area_rows.append((area_id, target, kind, cx, cy, radius, n, density))
            if best_area_for_target is None or n > best_area_for_target[1]:
                best_area_for_target = (area_id, n)
            area_id += 1
        # Fallback: no dense cluster -> single area covering all spawns.
        if best_area_for_target is None:
            cx, cy = float(arr[:, 0].mean()), float(arr[:, 1].mean())
            radius = float(np.sqrt(((arr - [cx, cy]) ** 2).sum(axis=1)).max()) if len(arr) > 1 else 0.0
            n = len(arr)
            density = n / (np.pi * radius**2) if radius > 0 else float(n)
            area_rows.append((area_id, target, kind, cx, cy, radius, n, density))
            best_area_for_target = (area_id, n)
            area_id += 1
        target_to_area[(target, kind)] = best_area_for_target[0]
        entry_to_area[target] = best_area_for_target[0]

    out.executemany(
        "INSERT INTO areas(id,target_entry,target_kind,centroid_x,centroid_y,radius,"
        "n_spawns,density) VALUES (?,?,?,?,?,?,?,?)",
        area_rows,
    )
    # Link objectives (KILL->CREATURE, OBJECT->OBJECT) to their densest area.
    for (target, kind), aid in target_to_area.items():
        okind = "KILL" if kind == "CREATURE" else "OBJECT"
        out.execute(
            "UPDATE objectives SET area_id = ? WHERE target_id = ? AND kind = ?",
            (aid, target, okind),
        )
    # Link lootable COLLECT objectives to their source entity's densest area (by quest_id, idx).
    for (qid, idx), (_skind, source_entry) in collect_src.items():
        aid = entry_to_area.get(source_entry)
        if aid is not None:
            out.execute(
                "UPDATE objectives SET area_id = ? WHERE quest_id = ? AND idx = ?", (aid, qid, idx)
            )


def _write_pois(
    out: sqlite3.Connection, src: sqlite3.Connection, quest_ids: list[int],
    givers: dict[int, list[tuple[str, int]]], turnins: dict[int, list[tuple[str, int]]],
    creature_spawns: dict[int, list[tuple[int, float, float, float, int]]],
    gameobject_spawns: dict[int, list[tuple[int, float, float, float, int]]],
    box: Box,
) -> None:
    rows: list[tuple[object, ...]] = []
    pid = 1
    # GIVER / TURNIN pois: one representative per quest.
    for kind_name, rel in (("GIVER", givers), ("TURNIN", turnins)):
        for entry in quest_ids:
            pick = _pick_poi(rel[entry], creature_spawns, gameobject_spawns, box)
            if pick is not None:
                rows.append((pid, kind_name, entry, pick[2], pick[3]))
                pid += 1
    # TRAINER / VENDOR / HEARTH pois for in-box creatures.
    trainers = {int(r[0]) for r in src.execute("SELECT DISTINCT entry FROM npc_trainer")}
    vendors = {int(r[0]) for r in src.execute("SELECT DISTINCT entry FROM npc_vendor")}
    innkeepers = {
        int(r[0]) for r in src.execute(
            "SELECT entry FROM creature_template WHERE name LIKE 'Innkeeper%'"
        )
    }
    for entry, plist in sorted(creature_spawns.items()):
        in_box_pt = next(((x, y) for _g, x, y, _z, _r in plist if box.contains(x, y)), None)
        if in_box_pt is None:
            continue
        for kind_name, membership in (
            ("TRAINER", trainers), ("VENDOR", vendors), ("HEARTH", innkeepers)
        ):
            if entry in membership:
                rows.append((pid, kind_name, entry, in_box_pt[0], in_box_pt[1]))
                pid += 1
    out.executemany(
        "INSERT INTO pois(id, kind, ref_id, x, y) VALUES (?,?,?,?,?)", rows
    )


def _write_items(out: sqlite3.Connection, src: sqlite3.Connection, quest_ids: list[int]) -> None:
    ph = ",".join("?" * len(quest_ids))
    ids: set[int] = set()
    for r in src.execute(
        f"""SELECT RewChoiceItemId1,RewChoiceItemId2,RewChoiceItemId3,RewChoiceItemId4,
                   RewChoiceItemId5,RewChoiceItemId6,RewItemId1,RewItemId2,RewItemId3,RewItemId4
            FROM quest_template WHERE entry IN ({ph})""",
        quest_ids,
    ):
        ids.update(int(v) for v in r if v)
    if not ids:
        return
    iph = ",".join("?" * len(ids))
    rows: list[tuple[object, ...]] = []
    tmpl: dict[int, tuple[Any, ...]] = {}  # sqlite rows -> Any elements
    for r in src.execute(
        f"""SELECT entry, patch, name, inventory_type, dmg_min1, dmg_max1, delay, armor,
                   stat_type1,stat_value1,stat_type2,stat_value2,stat_type3,stat_value3,
                   stat_type4,stat_value4,stat_type5,stat_value5
            FROM item_template WHERE entry IN ({iph}) ORDER BY entry, patch""",
        sorted(ids),
    ):
        tmpl[int(r[0])] = r
    for entry in sorted(ids):
        r = tmpl.get(entry)
        if r is None:
            continue
        delay = int(r[6])
        dmg = (float(r[4]) + float(r[5])) / 2.0
        wdps = (dmg / (delay / 1000.0)) if delay > 0 and dmg > 0 else None
        stats = {
            int(r[8 + 2 * k]): int(r[9 + 2 * k])
            for k in range(5)
            if int(r[8 + 2 * k]) != 0
        }
        rows.append((
            entry, str(r[2]), int(r[3]), wdps, int(r[7]),
            json.dumps(stats) if stats else None, "item_template", entry,
        ))
    out.executemany(
        "INSERT INTO items(id,name,slot,weapon_dps,armor,stats,src_table,src_pk)"
        " VALUES (?,?,?,?,?,?,?,?)",
        rows,
    )


# Fill-at-moonwell linkage for the Crown of the Earth phials (DESIGN 0b). Each filled phial is
# created by a create-item spell found in the dump (spell_template.effectItemType* -> the item);
# these spell IDs are DB facts. Named moonwell gameobjects (GO 19549-19552) exist as in-box OBJECT
# spawns. The phial->moonwell pairing is NOT in a data field, but the vanilla quest TEXT names the
# moonwell outright (quest_template.Details); `_moonwell_phrase` parses it and downgrades the row
# to source='derived-from-text' quoting the phrase. Only rows where SrcItemId != required item are
# fills; the rest are quest-provided. Named moonwell -> GO entry (from gameobject_template names):
FILL_MAP: dict[int, tuple[int, int, str]] = {
    #  required_item: (create_spell, moonwell_go_entry, expected-location keyword in quest text)
    5184: (4976, 19549, "aldrassil"),       # Filled Crystal Phial  (q921)  Shadowglen Moonwell
    5639: (6609, 19550, "starbreeze"),      # Filled Jade Phial      (q929)  Starbreeze Moonwell
    5645: (6610, 19551, "arlithrien"),      # Filled Tourmaline Phial(q933)  Pools of Arlithrien
    18151: (22562, 19552, "oracle glade"),  # Filled Amethyst Phial  (q7383) Oracle Glade Moonwell
}


def _moonwell_phrase(src: sqlite3.Connection, quest_id: int, keyword: str) -> str | None:
    """Return the sentence in the quest's Details/Objectives that names the moonwell location
    (contains 'moonwell' and the expected location keyword), else None. Used to promote a FILL
    pairing from manual to derived-from-text."""
    row = src.execute(
        "SELECT Objectives, Details FROM quest_template WHERE entry=? AND patch<=? "
        "ORDER BY patch DESC LIMIT 1", (quest_id, PATCH_ERA)
    ).fetchone()
    if row is None:
        return None
    text = " ".join(str(t) for t in row if t)
    for sentence in re.split(r"(?<=[.!])\s+", text):
        low = sentence.lower()
        if "moonwell" in low and keyword in low:
            return " ".join(sentence.split())[:200]
    return None


def _write_manual_annotations(out: sqlite3.Connection, src: sqlite3.Connection) -> None:
    """Resolve a provider for every NULL-drop COLLECT objective (DESIGN 0b).

    QUEST_PROVIDED: the item is granted by the quest (SrcItemId == required item, or the
      giver hands it over) -> in bags on accept, no travel. source='derived' (or 'manual' where
      the dump does not list it in SrcItemId).
    FILL_OBJECT: the item is created by using a moonwell (FILL_MAP) -> GOTO the moonwell +
      interaction time. Pairing is source='manual' (see FILL_MAP comment).
    """
    nulls = out.execute(
        "SELECT quest_id, idx, target_id FROM objectives "
        "WHERE kind='COLLECT' AND drop_chance IS NULL ORDER BY quest_id, idx"
    ).fetchall()
    # Moonwell coords from the compiled (in-box) spawns table.
    go_xy: dict[int, tuple[float, float]] = {
        int(e): (float(x), float(y))
        for e, x, y in out.execute("SELECT entry, x, y FROM spawns WHERE kind='OBJECT'")
    }
    # Giver/turn-in POI coords (for anchoring gather annotations to a real location).
    giver_poi: dict[int, tuple[float, float]] = {
        int(r) : (float(x), float(y))
        for r, x, y in out.execute("SELECT ref_id, x, y FROM pois WHERE kind='GIVER'")
    }
    turnin_poi: dict[int, tuple[float, float]] = {
        int(r): (float(x), float(y))
        for r, x, y in out.execute("SELECT ref_id, x, y FROM pois WHERE kind='TURNIN'")
    }
    rows: list[tuple[object, ...]] = []
    for quest_id, idx, item in nulls:
        srow = src.execute(
            "SELECT SrcItemId FROM quest_template WHERE entry=? AND patch<=? ORDER BY patch DESC LIMIT 1",
            (quest_id, PATCH_ERA),
        ).fetchone()
        src_item = int(srow[0]) if srow and srow[0] is not None else 0
        giver = out.execute("SELECT giver_id FROM quests WHERE id=?", (quest_id,)).fetchone()
        giver_id = int(giver[0]) if giver and giver[0] is not None else None
        if item in FILL_MAP:
            spell, go_entry, keyword = FILL_MAP[item]
            xy = go_xy.get(go_entry)
            phrase = _moonwell_phrase(src, quest_id, keyword)
            if phrase is not None:
                source, note = "derived-from-text", f'quest text: "{phrase}" -> moonwell GO {go_entry}'
            else:
                source, note = "manual", f"phial filled by spell {spell} at GO {go_entry} (pairing manual)"
            rows.append((quest_id, idx, "FILL_OBJECT", go_entry, spell,
                         xy[0] if xy else None, xy[1] if xy else None, source, note))
        else:
            derived = item == src_item
            rows.append((
                quest_id, idx, "QUEST_PROVIDED", giver_id, None, None, None,
                "derived" if derived else "manual",
                "item in bags on accept (SrcItemId match)" if derived
                else "item granted by giver; not in SrcItemId (manual)",
            ))

    # Located-less lootable gathers: COLLECT with a drop_chance but no area and no creature source
    # (item comes from a gameobject that has NO static map-1 spawn — checked gameobject / pool_
    # gameobject / game_event; script/pool placed). Anchor to the giver (else turn-in) POI so the
    # sim never costs WORK against a location-less target (M1 review). source='manual'.
    gathers = out.execute(
        "SELECT quest_id, idx, target_id FROM objectives WHERE kind='COLLECT' "
        "AND drop_chance IS NOT NULL AND area_id IS NULL AND source_id IS NULL "
        "ORDER BY quest_id, idx"
    ).fetchall()
    n_gather = 0
    for quest_id, idx, item in gathers:
        anchor = giver_poi.get(quest_id) or turnin_poi.get(quest_id)
        if anchor is None:
            continue  # out-of-slice quest with no in-box giver/turn-in; not route-reachable
        go = src.execute(
            "SELECT entry FROM gameobject_loot_template WHERE item=? LIMIT 1", (item,)
        ).fetchone()
        go_id = int(go[0]) if go else None
        rows.append((
            quest_id, idx, "OBJECT_GATHER", go_id, None, anchor[0], anchor[1], "manual",
            f"item {item} from GO {go_id} has no map-1 static spawn "
            f"(checked gameobject/pool_gameobject/game_event); located at quest giver as proxy",
        ))
        n_gather += 1

    out.executemany(
        "INSERT INTO manual_annotations(quest_id,obj_idx,provider_kind,provider_id,"
        "provider_spell,provider_x,provider_y,source,note) VALUES (?,?,?,?,?,?,?,?,?)",
        rows,
    )
    n_fill = sum(1 for r in rows if r[2] == "FILL_OBJECT")
    n_manual = sum(1 for r in rows if r[7] == "manual")
    n_text = sum(1 for r in rows if r[7] == "derived-from-text")
    print(f"ETL: manual_annotations: {len(rows)} rows "
          f"({n_fill} fill-object [{n_text} derived-from-text], {n_gather} object-gather, "
          f"{len(rows) - n_fill - n_gather} quest-provided; {n_manual} source=manual).")


def _wowhead_note(out: sqlite3.Connection) -> None:
    print("ETL: quest XP for Wowhead spot-check (DB RewXP -> verify at classic.wowhead.com):")
    ph = ",".join("?" * len(WOWHEAD_XP_CHECK))
    for qid, name, xp in out.execute(
        f"SELECT id, name, xp FROM quests WHERE id IN ({ph}) ORDER BY id", WOWHEAD_XP_CHECK
    ):
        print(f"       quest {qid} {name!r}: RewXP={xp}")


if __name__ == "__main__":
    main()
