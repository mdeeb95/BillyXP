"""Render the frozen M1 timeline into a human-followable calibration playsheet.

    uv run python -m eval.playsheet [--with-times] [--with-tomtom]
      -> out/playsheet_shadowglen_hunter.md  (+ regenerates eval/runs/template.csv)

This is a PURE RENDERING of the frozen route (m1-freeze): it asserts the route file's sha256
matches the frozen value and hard-fails otherwise. No param/model/route changes. Every NPC,
object, mob, item, vendor, and price is read live from the DBs (compiled world.sqlite + the raw
vmangos dump for names) — never from memory (CLAUDE.md rule 1).

Anchor hygiene: the DEFAULT output contains no predicted times or durations anywhere (levels are
not times and stay). `--with-times` reveals the sim's predicted times for a future retail edition.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import sqlite3
from dataclasses import dataclass
from typing import Any
from pathlib import Path

from sim.world import World

ROOT = Path(__file__).resolve().parent.parent
TIMELINE = ROOT / "out" / "shadowglen_hunter_timeline.json"
ROUTE = ROOT / "eval" / "routes" / "shadowglen_hunter.dsl"
RAW_DB = ROOT / "data" / "raw" / "sqlite-dump" / "mangos.sqlite"
OUT_MD = ROOT / "out" / "playsheet_shadowglen_hunter.md"
CSV = ROOT / "eval" / "runs" / "template.csv"
EPILOGUE_CSV = ROOT / "eval" / "runs" / "epilogue_template.csv"
MAPPROJ = ROOT / "eval" / "teldrassil_mapproj.json"

# Epilogue (bow-experiment) capture fields — the single source of truth shared by the CSV template
# and the playsheet's epilogue LOG prompts, so the sheet can never ask for a field the log lacks.
EP_ARM1 = [f"arm1_kill{i:02d}_s" for i in range(1, 11)]
EP_ARM2 = [f"arm2_kill{i:02d}_s" for i in range(1, 11)]
EP_BASELINE = ["arrow_type", "baseline_played_hms", "gold_before_copper"]
EP_BUY = ["price_paid_copper"]
EP_AFTER = ["gold_after_copper", "after_played_hms"]
EPILOGUE_FIELDS = EP_BASELINE + EP_ARM1 + EP_BUY + EP_ARM2 + EP_AFTER

# The frozen M1 route (eval/PREDICTIONS.md). The playsheet only renders THIS route.
FROZEN_ROUTE_SHA = "321e3c3547a3e545c45d6d670fd249906a9201d36f87279e2a09b9accdbb78ab"

COMPASS = ["N", "NE", "E", "SE", "S", "SW", "W", "NW"]


def compass(ax: float, ay: float, bx: float, by: float) -> str:
    """8-point compass bearing A->B. World +X = north, +Y = west (empirical, viz/spawn_map.py),
    so east = -Δy. Bearing 0=N, 90=E."""
    north, east = bx - ax, -(by - ay)
    ang = math.degrees(math.atan2(east, north)) % 360.0
    return COMPASS[round(ang / 45.0) % 8]


class Names:
    """Entity-name resolver reading the raw vmangos dump read-only (names aren't in the compiled
    DB). Cached; falls back to a stable '<kind> #id' label if a row is missing."""

    def __init__(self) -> None:
        self.c = sqlite3.connect(f"file:{RAW_DB}?mode=ro", uri=True)

    def creature(self, entry: int | None) -> str:
        return self._one("creature_template", entry, f"NPC #{entry}")

    def gobject(self, entry: int | None) -> str:
        return self._one("gameobject_template", entry, f"object #{entry}")

    def item(self, entry: int | None) -> str:
        return self._one("item_template", entry, f"item #{entry}")

    def _one(self, table: str, entry: int | None, fallback: str) -> str:
        if entry is None:
            return fallback
        r = self.c.execute(f"SELECT name FROM {table} WHERE entry=? LIMIT 1", (entry,)).fetchone()
        return str(r[0]) if r and r[0] else fallback

    def nearest_creature(self, x: float, y: float, max_yd: float = 25.0) -> str | None:
        """Name the creature spawned closest to (x,y) on map 1 — used to label a GOTO xy target
        (e.g. the class trainer) from the DB rather than from memory."""
        best: tuple[float, str] | None = None
        for cid, cx, cy in self.c.execute(
            "SELECT id, position_x, position_y FROM creature WHERE map=1 "
            "AND position_x BETWEEN ? AND ? AND position_y BETWEEN ? AND ?",
            (x - max_yd, x + max_yd, y - max_yd, y + max_yd),
        ):
            d = math.hypot(cx - x, cy - y)
            if d <= max_yd and (best is None or d < best[0]):
                best = (d, self.creature(int(cid)))
        return best[1] if best else None


@dataclass
class Cluster:
    entries: list[dict[str, Any]]      # timeline entries at one location
    pos: tuple[float, float]

    @property
    def has_turnin(self) -> bool:
        return any(str(e["step"]).startswith("TURNIN") for e in self.entries)

    @property
    def level_after(self) -> int:
        return int(self.entries[-1]["level"])


def cluster_timeline(timeline: list[dict[str, Any]]) -> list[Cluster]:
    """Group consecutive steps that resolve to the same location (rounded pos)."""
    clusters: list[Cluster] = []
    for e in timeline:
        key = (round(float(e["pos_x"])), round(float(e["pos_y"])))
        if clusters and (round(clusters[-1].pos[0]), round(clusters[-1].pos[1])) == key:
            clusters[-1].entries.append(e)
        else:
            clusters.append(Cluster([e], (float(e["pos_x"]), float(e["pos_y"]))))
    return clusters


# --- step rendering ---------------------------------------------------------------------
def _toks(step: str) -> list[str]:
    return step.split()


def loc_name(cl: Cluster, world: World, names: Names) -> str:
    """Human name for a cluster's location (destination of the 'Head ...' line)."""
    for e in cl.entries:
        t = _toks(str(e["step"]))
        if t[0] in ("ACCEPT", "TURNIN"):
            q = world.quest(int(t[1]))
            kind, eid = (q.giver_kind, q.giver_id) if t[0] == "ACCEPT" else (q.turnin_kind, q.turnin_id)
            if eid is None:
                continue
            return names.gobject(eid) if kind == "OBJECT" else names.creature(eid)
    for e in cl.entries:
        t = _toks(str(e["step"]))
        if t[0] == "WORK":
            o = world.quest(int(t[1])).objectives[int(t[2])]
            if o.kind == "KILL" and o.target_id is not None:
                return f"the {names.creature(o.target_id)} area"
            if o.source_id is not None:
                return f"the {names.creature(o.source_id)} area"
            # quest-provided / provider-gather WORK has no place of its own; skip it here.
        if t[0] == "SETHEARTH":
            return names.creature(int(t[1]))
        if t[0] in ("GOTO", "TRAIN"):
            n = names.nearest_creature(*cl.pos)
            if n:
                return n
    return "your starting spot"


def render_step(e: dict[str, Any], world: World, names: Names) -> str | None:
    step, note = str(e["step"]), str(e["note"])
    t = _toks(step)
    op = t[0]
    if op == "GOTO":
        return None  # movement is rendered as the cluster's 'Head ...' line
    if op == "ACCEPT":
        q = world.quest(int(t[1]))
        extra = " *(auto-granted / starts here)*" if q.giver_id is None else ""
        return f"Accept **{q.name}** ({q.id}){extra}"
    if op == "TURNIN":
        q = world.quest(int(t[1]))
        equip = ""
        if "equip" in note:
            equip = " — " + note.split("; ", 1)[1] if "; " in note else ""
        return f"Turn in **{q.name}** ({q.id}){equip}"
    if op == "TRAIN":
        trained = note.replace("train: ", "") if note.startswith("train:") else "new skills"
        return f"Train ({trained})"
    if op == "SETHEARTH":
        return f"Set your hearthstone here ({names.creature(int(t[1]))})"
    if op == "WORK":
        return _render_work(int(t[1]), int(t[2]), world, names)
    return step


def _render_work(qid: int, oidx: int, world: World, names: Names) -> str:
    o = world.quest(qid).objectives[oidx]
    if o.kind == "KILL" and o.target_id is not None:
        return f"Kill {o.count}× **{names.creature(o.target_id)}**"
    if o.kind == "OBJECT" and o.target_id is not None:
        return f"Use {o.count}× **{names.gobject(o.target_id)}**"
    if o.kind in ("ESCORT", "EXPLORE"):
        return f"Do the event step for **{world.quest(qid).name}**"
    if o.kind == "COLLECT":
        item = names.item(o.target_id)
        ann = world.annotation(qid, oidx)
        if o.drop_chance is None and ann is not None:
            if ann.provider_kind == "QUEST_PROVIDED":
                return f"You already carry **{item}** (in bags)"
            if ann.provider_kind == "FILL_OBJECT":
                return f"Fill **{item}** at the **{names.gobject(ann.provider_id)}**"
        if o.source_kind == "CREATURE" and o.source_id is not None:
            return f"Collect {o.count}× **{item}** from **{names.creature(o.source_id)}**"
        return f"Gather {o.count}× **{item}**"
    return f"{o.kind} {world.quest(qid).name}"


def dominant_mob(cl: Cluster, world: World, names: Names) -> str | None:
    """Name a mob to grind here if under-leveled (the cluster's combat target)."""
    for e in cl.entries:
        t = _toks(str(e["step"]))
        if t[0] == "WORK":
            o = world.quest(int(t[1])).objectives[int(t[2])]
            mid = o.target_id if o.kind == "KILL" else o.source_id
            if mid is not None:
                return names.creature(mid)
    return None


# --- epilogue data picks (DB-derived, never from memory) --------------------------------
def pick_vendor_bow(names: Names, world: World, end_level: int,
                    end_pos: tuple[float, float]) -> dict[str, Any] | None:
    """In-zone vendor selling a ranged bow usable at end_level; best (highest-dps) upgrade, tie
    broken by proximity to the route's end (minimise backtracking). Returns item/vendor/price/req/
    location with entity ids, or None if none in zone."""
    best: dict[str, Any] | None = None
    for kind, ref in world.pois:
        if kind != "VENDOR":
            continue
        vpos = world.pois[(kind, ref)]
        dist = math.hypot(vpos.x - end_pos[0], vpos.y - end_pos[1])
        for (item,) in names.c.execute("SELECT item FROM npc_vendor WHERE entry=?", (ref,)):
            row = names.c.execute(
                "SELECT entry,name,dmg_min1,dmg_max1,delay,required_level,buy_price "
                "FROM item_template WHERE entry=? AND class=2 AND subclass IN (2,3,18)", (item,)
            ).fetchone()
            if not row or row[4] == 0 or int(row[5]) > end_level:
                continue
            dps = (row[2] + row[3]) / 2 / (row[4] / 1000.0)
            better = best is None or dps > float(best["dps"]) + 1e-6 or (
                abs(dps - float(best["dps"])) <= 1e-6 and dist < float(best["dist"]))
            if better:
                best = {"item_id": int(row[0]), "item": str(row[1]), "dps": dps,
                        "req": int(row[5]), "price_c": int(row[6]), "vendor_id": int(ref),
                        "vendor": names.creature(int(ref)), "x": vpos.x, "y": vpos.y, "dist": dist}
    return best


def pick_test_mob(names: Names, world: World, vx: float, vy: float, level: int) -> dict[str, Any] | None:
    """Nearest area to the vendor whose target mob is within +-1 of `level` — the timed-kill mob."""
    best: dict[str, Any] | None = None
    for a in world.areas.values():
        mob = world.mobs.get(a.target_entry)
        if mob is None or not (level - 1 <= mob.lvl_max <= level + 1):
            continue
        d = math.hypot(a.centroid.x - vx, a.centroid.y - vy)
        if best is None or d < float(best["dist"]):
            best = {"mob": names.creature(mob.id), "mob_id": mob.id, "lvl": mob.lvl_max,
                    "area": a.id, "dist": d}
    return best


def price_str(c: int) -> str:
    g, s, cp = c // 10000, (c % 10000) // 100, c % 100
    parts = [p for p in (f"{g}g" if g else "", f"{s}s" if s else "", f"{cp}c" if cp else "") if p]
    return " ".join(parts) or "0c"


# --- render -----------------------------------------------------------------------------
def render(timeline: list[dict[str, Any]], world: World, names: Names, with_times: bool,
           with_tomtom: bool, route_sha: str,
           meta_src: str) -> tuple[str, list[list[str]], list[tuple[int, list[int]]]]:
    clusters = cluster_timeline(timeline)
    end_level = int(timeline[-1]["level"])
    out: list[str] = [
        "# Playsheet - Shadowglen -> Dolanaar, Night Elf Hunter (1 -> ~7)", "",
        "Human-followable render of the **frozen M1 route**. Follow top to bottom.",
        "", "## Provenance", "",
        f"- route file sha256: `{route_sha}` (frozen - asserted at render)",
        f"- world DB: {meta_src}",
        "- times/durations: " + ("SHOWN (--with-times)" if with_times
                                  else "hidden by default (anchor hygiene)"),
        "", "---", "", "## Route", "",
    ]
    csv_rows: list[list[str]] = []
    seg_quests: list[tuple[int, list[int]]] = []  # segment -> quest ids turned in there
    waypoints: list[tuple[str, float, float]] = []  # (label, world_x, world_y) for TomTom
    seg = 0
    prev_pos: tuple[float, float] | None = None
    last_mob: str | None = None
    for cl in clusters:
        actions = [ln for ln in (render_step(e, world, names) for e in cl.entries) if ln]
        if not actions:
            prev_pos = cl.pos
            continue
        dest = loc_name(cl, world, names)
        waypoints.append((dest, cl.pos[0], cl.pos[1]))
        moved = prev_pos is not None and (
            (round(prev_pos[0]), round(prev_pos[1])) != (round(cl.pos[0]), round(cl.pos[1])))
        if moved and prev_pos is not None:
            out.append(f"**-> Head {compass(prev_pos[0], prev_pos[1], cl.pos[0], cl.pos[1])} "
                       f"to {dest}.**")
        else:
            out.append(f"**At {dest}:**")
        out += [f"- {ln}" for ln in actions]
        m = dominant_mob(cl, world, names)
        last_mob = m or last_mob
        if cl.has_turnin:
            seg += 1
            contingency = (f"  _If under {cl.level_after}: grind **{last_mob}** nearby first "
                           f"(advisory)._" if last_mob else "")
            out.append(f"- **Expected level here: {cl.level_after}.**{contingency}")
            out.append(f"- `LOG: screenshot /played - segment {seg}`")
            qids = [int(_toks(str(e["step"]))[1]) for e in cl.entries
                    if str(e["step"]).startswith("TURNIN")]
            quests = ", ".join(world.quest(q).name for q in qids)
            seg_quests.append((seg, qids))
            csv_rows.append([str(seg), quests, str(cl.level_after), "", "", "", "", ""])
        if with_times:
            end_min = float(cl.entries[-1]["t1"]) / 60.0
            out.append(f"  <sub>predicted cumulative: {end_min:.0f} min</sub>")
        out.append("")
        prev_pos = cl.pos

    end_pos = (float(timeline[-1]["pos_x"]), float(timeline[-1]["pos_y"]))
    out += _epilogue(names, world, end_level, end_pos)
    out += _tomtom_block(with_tomtom, waypoints)
    return "\n".join(out) + "\n", csv_rows, seg_quests


def _epilogue(names: Names, world: World, end_level: int,
              end_pos: tuple[float, float]) -> list[str]:
    bow = pick_vendor_bow(names, world, end_level, end_pos)
    out = ["---", "", "## Epilogue - ranged-upgrade kill-timing experiment", "",
           "Isolates the change in kill time from a ranged-weapon purchase (M7 / calibration).", ""]
    if bow is None:
        out += ["> **No in-zone vendor stocks a usable ranged weapon at this level - STOP and ask.**", ""]
        return out
    mob = pick_test_mob(names, world, float(bow["x"]), float(bow["y"]), end_level)
    mob_txt = (f"**{mob['mob']}** (lvl {mob['lvl']}, id {mob['mob_id']}, area {mob['area']})"
               if mob else "a dense equal-level mob near the vendor")
    out += [
        "**Controls** (a hunter's ranged damage = weapon dps **+ ammo dps**, so ammo must be held "
        "constant or the two arms aren't comparable):",
        "- **Restock arrows BEFORE the baseline arm** — start with a full stack so you never run dry "
        "mid-experiment.",
        "- Use the **same arrow type for both arms**, and **record the arrow type** (its dps is part "
        "of the measured ranged damage).",
        "- Begin **each arm at full health and mana** (drink/bandage up first).",
        "- **Single pulls only.** A kill that gets adds does **not** count toward the 10 — reset and "
        "redo it.",
        "- Each `/played` + gold screenshot must **include the open bag UI** (so ammo count and gold "
        "are both legible).",
        "",
        "1. **Baseline:** screenshot `/played` and your gold (bags open).",
        f"   - `LOG -> eval/runs/epilogue_template.csv: {', '.join(EP_BASELINE)}`",
        f"2. **10 timed kills** on {mob_txt}, single pulls only. Record each kill time.",
        f"   - `LOG -> epilogue_template.csv: {EP_ARM1[0]} .. {EP_ARM1[-1]}`",
        f"3. **Buy** the **{bow['item']}** (item {bow['item_id']}) from **{bow['vendor']}** "
        f"(NPC {bow['vendor_id']}, world {float(bow['x']):.0f},{float(bow['y']):.0f}) - "
        f"{price_str(int(bow['price_c']))}, requires level {bow['req']}, "
        f"~{float(bow['dps']):.2f} weapon dps. Equip it.",
        f"   - `LOG -> epilogue_template.csv: {', '.join(EP_BUY)}`",
        f"4. **10 timed kills** on the same {mob_txt}, single pulls only, same arrow type. Record "
        "each kill time.",
        f"   - `LOG -> epilogue_template.csv: {EP_ARM2[0]} .. {EP_ARM2[-1]}`",
        "5. **After:** screenshot `/played` and your gold (bags open).",
        f"   - `LOG -> epilogue_template.csv: {', '.join(EP_AFTER)}`",
        "", "_Deferred bigger jump: Laminated Recurve Bow (item 2507) is level-11 gated._", "",
    ]
    return out


def _load_transform() -> dict[str, Any] | None:
    """Return the affine transform ONLY if the fit exists and cleared the residual gate
    (status OK). A BLOCKED/absent record ungates nothing — /way stays off (CLAUDE.md rule 1)."""
    if not MAPPROJ.exists():
        return None
    rec = json.loads(MAPPROJ.read_text(encoding="utf-8"))
    if rec.get("status") != "OK" or not rec.get("transform"):
        return None
    return rec


def _tomtom_block(with_tomtom: bool, waypoints: list[tuple[str, float, float]]) -> list[str]:
    if not with_tomtom:
        return ["---", "", "## TomTom `/way` block", "",
                "_Not requested (pass `--with-tomtom`)._", ""]
    rec = _load_transform()
    if rec is None:
        return ["---", "", "## TomTom `/way` block", "",
                "> **BLOCKED.** No world->zone-map transform has cleared the 1%-of-extent residual "
                "gate (`eval/teldrassil_mapproj.json` is absent or `status != OK`). No transform "
                "constants are taken from memory (CLAUDE.md rule 1), so `/way` lines are withheld "
                "rather than guessed. Unblock: derive the affine (see `eval/mapproj.py`), pass the "
                "gate, then re-run with `--with-tomtom`.", ""]
    (a00, a01), (a10, a11) = rec["transform"]["A"]
    b0, b1 = rec["transform"]["b"]
    src = rec.get("provenance", {}).get("map_coords", "map fit")
    out = ["---", "", "## TomTom `/way` block", "",
           f"_Transform: {src}; worst residual {rec.get('worst_residual_pct', 0):.2f}% of extent._",
           "", "```"]
    for label, wx, wy in waypoints:
        mx = a00 * wx + a01 * wy + b0
        my = a10 * wx + a11 * wy + b1
        out.append(f"/way Teldrassil {mx:.1f} {my:.1f} {label}")
    out += ["```", ""]
    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--with-times", action="store_true")
    ap.add_argument("--with-tomtom", action="store_true")
    args = ap.parse_args()

    route_sha = hashlib.sha256(ROUTE.read_bytes()).hexdigest()
    if route_sha != FROZEN_ROUTE_SHA:
        raise SystemExit(f"playsheet: route sha {route_sha} != frozen {FROZEN_ROUTE_SHA} - "
                         "the frozen route changed; refusing to render (m1-freeze).")

    data = json.loads(TIMELINE.read_text(encoding="utf-8"))
    world = World()
    names = Names()
    md, csv_rows, seg_quests = render(data["timeline"], world, names, args.with_times,
                                      args.with_tomtom, route_sha,
                                      world.meta.get("source_db", "?"))
    OUT_MD.parent.mkdir(parents=True, exist_ok=True)
    OUT_MD.write_text(md, encoding="utf-8")
    CSV.parent.mkdir(parents=True, exist_ok=True)
    # Header comments document the segment -> quest-id mapping so the comparator (eval/compare.py)
    # can aggregate the frozen timeline to the SAME 24 segments. Each quest is keyed to the segment
    # it is TURNED IN, so the union across segments is exactly the route's full quest set.
    all_qids = sorted(q for _, qs in seg_quests for q in qs)
    comment = [
        "# XPWhat calibration run log — one row per playsheet segment (turn-in cluster).",
        f"# route sha256: {FROZEN_ROUTE_SHA}",
        f"# segments: {len(seg_quests)}; quests (turn-ins): {len(all_qids)}",
        "# segment -> quest_ids (each quest keyed to its turn-in segment; union = full route set):",
    ]
    comment += [f"#   seg {seg:>2}: {','.join(str(q) for q in qs)}" for seg, qs in seg_quests]
    header = "segment,quests,expected_level,played_hms,gold_copper,deaths,drinks,notes"
    body = "\n".join(",".join(_csv(c) for c in row) for row in csv_rows)
    CSV.write_text("\n".join(comment) + "\n" + header + "\n" + body + "\n", encoding="utf-8")
    # Epilogue capture template (bow experiment) — key/value, one field per row, blank to fill.
    # Field list is EPILOGUE_FIELDS, the same source the playsheet's epilogue LOG prompts cite.
    ep = ["# Bow-experiment capture — fill 'value'. Fields cited by the playsheet epilogue LOG "
          "prompts (single source of truth).", "field,value"]
    ep += [f"{f}," for f in EPILOGUE_FIELDS]
    EPILOGUE_CSV.write_text("\n".join(ep) + "\n", encoding="utf-8")
    print(f"playsheet: wrote {OUT_MD} ({len(csv_rows)} segments)")
    print(f"playsheet: wrote {CSV}")
    print(f"playsheet: wrote {EPILOGUE_CSV} ({len(EPILOGUE_FIELDS)} fields)")


def _csv(cell: str) -> str:
    return '"' + cell + '"' if ("," in cell or '"' in cell) else cell


if __name__ == "__main__":
    main()
