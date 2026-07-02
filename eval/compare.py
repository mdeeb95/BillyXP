"""Segment-grained comparator: aggregate the frozen timeline to the playsheet's segments and
(optionally) line up a real calibration run against it.

    uv run python -m eval.compare [eval/runs/<your-run>.csv]

Grain: one segment per playsheet turn-in cluster (identical clustering to eval/playsheet.py, which
this module imports so the two can never drift). Each quest is keyed to the segment it is TURNED IN,
so the union of per-segment quest sets is exactly the route's full quest set — asserted on BOTH
sides (the frozen-timeline aggregation AND the DSL's own accept/turn-in set). Anchor hygiene: the
per-segment predicted seconds live here (a comparison tool), never in the default playsheet.
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
    {seg, quest_ids (turned in), level_after, pred_seconds (bucketed sum over the segment)}."""
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
            segs.append({"seg": seg, "quest_ids": qids, "level_after": cl.level_after,
                         "pred_seconds": round(bucket, 1)})
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
    actual: dict[int, str] = {}
    if run_path and run_path.exists():
        with run_path.open(encoding="utf-8") as fh:
            for row in csv.DictReader(r for r in fh if not r.startswith("#")):
                if row.get("played_hms"):
                    actual[int(row["segment"])] = row["played_hms"]

    hdr = f"{'seg':>3} {'lvl':>3} {'pred_s':>8}  quests"
    if actual:
        hdr = f"{'seg':>3} {'lvl':>3} {'pred_s':>8} {'actual':>9}  quests"
    print(hdr)
    print("-" * len(hdr))
    for s in segs:
        qnames = ", ".join(world.quest(q).name for q in s["quest_ids"])  # type: ignore[union-attr]
        line = f"{s['seg']:>3} {s['level_after']:>3} {s['pred_seconds']:>8}"
        if actual:
            line += f" {actual.get(int(str(s['seg'])), '-'):>9}"
        print(f"{line}  {qnames}")


if __name__ == "__main__":
    main()
