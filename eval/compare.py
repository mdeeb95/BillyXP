"""Segment-grained comparator: aggregate the frozen timeline to the playsheet's segments and
(optionally) line up a real calibration run against it.

    uv run python -m eval.compare [eval/runs/<your-run>.csv]

Grain: one segment per playsheet turn-in cluster (identical clustering to eval/playsheet.py, which
this module imports so the two can never drift). Each quest is keyed to the segment it is TURNED IN,
so the union of per-segment quest sets is exactly the route's full quest set — asserted on BOTH
sides (the frozen-timeline aggregation AND the DSL's own accept/turn-in set). Anchor hygiene: the
per-segment predicted seconds and predicted xp-into-level live here (a comparison tool), never in
the capture CSV or default playsheet.
"""

from __future__ import annotations

import csv
import sys
from pathlib import Path

from eval.playsheet import ROUTE, TIMELINE, cluster_timeline
from sim.dsl import parse_route
from sim.world import World

import json


def _segment_aggregation(world: World) -> list[dict[str, object]]:
    """Aggregate the frozen timeline into segments (turn-in clusters). Returns, per segment:
    {seg, quest_ids, level_after, pred_seconds, pred_xp_into}."""
    data = json.loads(TIMELINE.read_text(encoding="utf-8"))
    clusters = cluster_timeline(data["timeline"])
    segs: list[dict[str, object]] = []
    seg = 0
    bucket = 0.0
    for cl in clusters:
        bucket += sum(float(e["travel_s"]) + float(e["combat_s"]) + float(e["interaction_s"])
                      + float(e["downtime_s"]) for e in cl.entries)
        if cl.has_turnin:
            seg += 1
            qids = [int(str(e["step"]).split()[1]) for e in cl.entries
                    if str(e["step"]).startswith("TURNIN")]
            pred_xp = int(cl.entries[-1]["xp"])
            segs.append({"seg": seg, "quest_ids": qids, "level_after": cl.level_after,
                         "pred_seconds": round(bucket, 1), "pred_xp_into": pred_xp})
            bucket = 0.0
    return segs


def _route_quest_set() -> tuple[set[int], set[int]]:
    """(accepted, turned-in) quest-id sets straight from the DSL — the authoritative full set."""
    world = World()
    route = parse_route(ROUTE.read_text(encoding="utf-8"), world)
    accepted: set[int] = set()
    turnedin: set[int] = set()
    for s in route.steps:
        name = type(s).__name__
        if name == "Accept":
            accepted.add(int(getattr(s, "quest_id")))
        elif name == "Turnin":
            turnedin.add(int(getattr(s, "quest_id")))
    return accepted, turnedin


def _load_run_csv(path: Path) -> tuple[dict[int, str], dict[int, int]]:
    """Return (segment -> played_hms, segment -> observed xp_into_level)."""
    played: dict[int, str] = {}
    xp: dict[int, int] = {}
    with path.open(encoding="utf-8") as fh:
        for row in csv.DictReader(r for r in fh if not r.startswith("#")):
            seg = int(row["segment"])
            if row.get("played_hms"):
                played[seg] = row["played_hms"]
            raw = (row.get("xp_into_level") or "").strip()
            if raw:
                xp[seg] = int(raw)
    return played, xp


def main() -> None:
    world = World()
    segs = _segment_aggregation(world)
    accepted, turnedin = _route_quest_set()
    agg_union = {q for s in segs for q in s["quest_ids"]}  # type: ignore[union-attr]

    # BOTH sides must sum to the route's full quest set — else segmentation dropped/dup'd a quest.
    assert agg_union == turnedin, f"timeline agg {agg_union ^ turnedin} != route turn-ins"
    assert accepted == turnedin, f"route accepts {accepted ^ turnedin} it never turns in"
    print(f"OK: {len(segs)} segments; {len(agg_union)} quests; "
          "timeline-aggregation union == route turn-in set == route accept set.")

    run_path = Path(sys.argv[1]) if len(sys.argv) > 1 else None
    actual_time: dict[int, str] = {}
    actual_xp: dict[int, int] = {}
    if run_path and run_path.exists():
        actual_time, actual_xp = _load_run_csv(run_path)

    has_time = bool(actual_time)
    has_xp = bool(actual_xp)
    hdr = f"{'seg':>3} {'lvl':>3} {'pred_s':>8}"
    if has_xp:
        hdr += f" {'pred_xp':>7} {'obs_xp':>7} {'Δxp':>5}"
    if has_time:
        hdr += f" {'actual':>9}"
    hdr += "  quests"
    print(hdr)
    print("-" * len(hdr))
    for s in segs:
        qnames = ", ".join(world.quest(q).name for q in s["quest_ids"])  # type: ignore[union-attr]
        seg_n = int(str(s["seg"]))
        pred_xp = int(str(s["pred_xp_into"]))
        line = f"{s['seg']:>3} {s['level_after']:>3} {s['pred_seconds']:>8}"
        if has_xp:
            obs = actual_xp.get(seg_n)
            if obs is not None:
                delta = obs - pred_xp
                line += f" {pred_xp:>7} {obs:>7} {delta:>+5}"
            else:
                line += f" {pred_xp:>7} {'-':>7} {'-':>5}"
        if has_time:
            line += f" {actual_time.get(seg_n, '-'):>9}"
        print(f"{line}  {qnames}")


if __name__ == "__main__":
    main()
