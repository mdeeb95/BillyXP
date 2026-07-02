"""Derive the Teldrassil world -> zone-map affine transform used for TomTom /way output.

EMPIRICAL ONLY — no constants from memory (playsheet brief; CLAUDE.md rule 1). The fit needs, for
each anchor NPC, a pair (world_xy from the DB spawn, map_xy in 0-100 zone-map %). World coords are
read live from the raw dump here. The 0-100 map coords are the *only* input this module cannot
obtain itself.

Source for the map coords: **Questie's spawn data** (NPC spawns keyed by entry id in zone-map %).
classic.wowhead.com was ruled out — it renders NPC map coords in JavaScript, absent from served HTML
and unreachable via WebFetch; browser scraping was declined. See the "Unblock task" in TODO.md:
verify Questie's coord convention on 2-3 landmark NPCs, cite the Questie source file + version, fill
MAP_COORDS below, then rerun. Until then this module writes a BLOCKED record and fits nothing.

To unblock:
    uv run python -m eval.mapproj
least-squares fits  map = A . world + b, reports residuals in map% units, and refuses the fit
(status BLOCKED, TomTom stays gated) if any residual exceeds RESIDUAL_GATE_PCT % of the map extent.
"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any

import numpy as np

ROOT = Path(__file__).resolve().parent.parent
RAW_DB = ROOT / "data" / "raw" / "sqlite-dump" / "mangos.sqlite"
OUT_JSON = ROOT / "eval" / "teldrassil_mapproj.json"

RESIDUAL_GATE_PCT = 1.0  # brief: any anchor residual > 1% of map extent -> stop, TomTom BLOCKED

# Anchor NPCs (in-zone landmarks). World coords are pulled from the DB below; >=5 required for a
# trustworthy affine fit. The reference is the NPC entry id — the key Questie also uses.
ANCHORS: list[int] = [2079, 2082, 3589, 3596, 3610, 4173, 6736]

# map (x, y) in 0-100 zone-map units for each anchor entry, from Questie's spawn data (cite the
# Questie source file + version when filling). EMPTY = not yet supplied -> module stays BLOCKED.
# Do NOT fill from memory; only from the cited Questie source (CLAUDE.md rule 1).
MAP_COORDS: dict[int, tuple[float, float]] = {}
QUESTIE_SOURCE: str | None = None  # e.g. "Questie <ver> Database/classicSpawns.lua" — cite on unblock


def _world_xy(src: sqlite3.Connection, entry: int) -> tuple[float, float] | None:
    """First map-1 spawn for this creature (world x, y) from the raw dump, or None."""
    row = src.execute(
        "SELECT position_x, position_y FROM creature WHERE id=? AND map=1 LIMIT 1", (entry,)
    ).fetchone()
    return (float(row[0]), float(row[1])) if row else None


def _fit(world: np.ndarray, mapc: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Least-squares affine map = A . world + b. Returns (A 2x2, b 2)."""
    n = world.shape[0]
    design = np.hstack([world, np.ones((n, 1))])  # [x, y, 1]
    coef, *_ = np.linalg.lstsq(design, mapc, rcond=None)  # (3, 2)
    return coef[:2, :].T, coef[2, :]


def main() -> None:
    src = sqlite3.connect(f"file:{RAW_DB.as_posix()}?mode=ro", uri=True)
    anchors: list[dict[str, Any]] = []
    for entry in ANCHORS:
        wxy = _world_xy(src, entry)
        name_row = src.execute(
            "SELECT name FROM creature_template WHERE entry=?", (entry,)
        ).fetchone()
        anchors.append({
            "entry": entry,
            "name": name_row[0] if name_row else None,
            "world_xy": list(wxy) if wxy else None,
            "map_xy": list(MAP_COORDS[entry]) if entry in MAP_COORDS else None,
        })
    src.close()

    usable = [a for a in anchors if a["world_xy"] and a["map_xy"]]
    record: dict[str, Any] = {
        "purpose": "Teldrassil world->zone-map affine transform for TomTom /way output",
        "residual_gate_pct": RESIDUAL_GATE_PCT,
        "anchors": anchors,
        "provenance": {
            "world_coords": "data/raw/sqlite-dump/mangos.sqlite creature.position_x/_y (map=1)",
            "map_coords": QUESTIE_SOURCE or "Questie spawn data (source file + version — cite on unblock)",
        },
    }

    if len(usable) < 5:
        record["status"] = "BLOCKED"
        record["reason"] = (
            f"{len(usable)}/5 anchors have zone-map coords. Source is Questie spawn data (wowhead "
            "ruled out: JS-rendered coords unreachable via WebFetch; browser scraping declined). "
            "Fill MAP_COORDS + QUESTIE_SOURCE in eval/mapproj.py from the cited Questie file, then "
            "rerun. TomTom /way stays gated until the fit clears the residual gate. See TODO.md."
        )
        record["transform"] = None
        OUT_JSON.write_text(json.dumps(record, indent=2) + "\n", encoding="utf-8")
        print(f"BLOCKED: {record['reason']}")
        print(f"wrote {OUT_JSON} (status BLOCKED, {len(usable)}/{len(anchors)} anchors ready)")
        return

    world = np.array([a["world_xy"] for a in usable], dtype=float)
    mapc = np.array([a["map_xy"] for a in usable], dtype=float)
    A, b = _fit(world, mapc)
    pred = world @ A.T + b
    resid = np.abs(pred - mapc)
    extent = mapc.max(axis=0) - mapc.min(axis=0)
    resid_pct = 100.0 * resid / extent  # per-anchor, per-axis residual in map% units
    worst = float(resid_pct.max())

    for a, rp in zip(usable, resid_pct):
        a["residual_pct"] = [float(rp[0]), float(rp[1])]
    record["transform"] = {"A": A.tolist(), "b": b.tolist()}
    record["worst_residual_pct"] = worst

    if worst > RESIDUAL_GATE_PCT:
        record["status"] = "BLOCKED"
        record["reason"] = (
            f"worst anchor residual {worst:.2f}% > gate {RESIDUAL_GATE_PCT}%; affine fit rejected. "
            "TomTom /way stays gated (a bad transform would send the runner to the wrong pin)."
        )
    else:
        record["status"] = "OK"
    OUT_JSON.write_text(json.dumps(record, indent=2) + "\n", encoding="utf-8")
    print(f"status {record['status']}: worst residual {worst:.2f}% (gate {RESIDUAL_GATE_PCT}%)")
    print(f"wrote {OUT_JSON}")


if __name__ == "__main__":
    main()
