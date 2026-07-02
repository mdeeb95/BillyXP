"""Run a route DSL file through the simulator and emit the M1 deliverables (DESIGN §12):
a per-segment table, level/XP-over-time plot, timeline JSON, and the predicted total duration.

Run:  uv run python -m eval.run_route [eval/routes/shadowglen_hunter.dsl]

Starting character: fresh Night Elf HUNTER, level 1, starting ranged weapon (Worn Shortbow,
weapon_dps 1.52 — DB fact), 0 gold, positioned at the Shadowglen entrance (quest 456 giver POI).
"""

from __future__ import annotations

import hashlib
import subprocess
import sys
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

from sim import engine  # noqa: E402
from sim.dsl import parse_route  # noqa: E402
from sim.params import Params  # noqa: E402
from sim.state import CharacterState, Class  # noqa: E402
from sim.world import World  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_ROUTE = ROOT / "eval" / "routes" / "shadowglen_hunter.dsl"
OUT = ROOT / "out"

START_RANGED_DPS = 1.52   # Worn Shortbow (item 2504): (2+5)/2 / 2.3 s  [DB fact, item_template]
START_MELEE_DPS = 0.94    # Worn Dagger  (item 2092): (1+2)/2 / 1.6 s  [DB fact, item_template]


def fresh_hunter(world: World) -> CharacterState:
    return CharacterState(
        clazz=Class.HUNTER, level=1, xp=0, pos=world.poi_pos("GIVER", 456), gold_c=0,
        ranged_dps=START_RANGED_DPS, melee_dps=START_MELEE_DPS,
    )


def main() -> None:
    route_path = Path(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT_ROUTE
    world = World()
    route = parse_route(route_path.read_text(encoding="utf-8"), world)  # validates every id
    result = engine.execute(world, fresh_hunter(world), route, Params())

    if not result.feasible:
        i = result.first_violating_index
        step = route.steps[i] if i is not None else None
        raise SystemExit(f"route INFEASIBLE at step {i} ({step}): {result.reason}")

    assert result.metrics is not None and result.final_state is not None
    OUT.mkdir(parents=True, exist_ok=True)

    _print_segment_table(route, result)
    m = result.metrics
    mins = m.total_seconds / 60.0
    dec = _decomposition(result)
    print("\n" + "=" * 64)
    print(f"  PREDICTED TOTAL DURATION: {m.total_seconds:,.0f} s  =  {mins:.1f} min")
    print(f"  final level {m.final_level} ({m.final_xp_into_level} xp into level), "
          f"{m.quests_completed} quests, {m.n_levelups} level-ups")
    print("  time decomposition:")
    for name in ("travel", "combat", "interaction", "downtime"):
        s = dec[name]
        print(f"    {name:<12} {s:>7.0f} s  {100 * s / m.total_seconds:>5.1f} %")
    print("  (M1 sim number ON THE RECORD — reference timing measured separately for ±30%)")
    print("=" * 64)

    (OUT / "shadowglen_hunter_timeline.json").write_text(
        engine.timeline_to_json(result), encoding="utf-8")
    _plot_xp(result, OUT / "shadowglen_hunter_xp.png")
    _write_predictions(result, route_path)
    print(f"\nwrote {OUT / 'shadowglen_hunter_timeline.json'}")
    print(f"wrote {OUT / 'shadowglen_hunter_xp.png'}")
    print(f"wrote {ROOT / 'eval' / 'PREDICTIONS.md'}")


def _git(*args: str) -> str:
    try:
        return subprocess.run(["git", *args], cwd=ROOT, capture_output=True, text=True,
                              check=True).stdout.strip()
    except (subprocess.CalledProcessError, FileNotFoundError):
        return "?"


def _write_predictions(result: engine.EngineResult, route_path: Path) -> None:
    """Freeze the on-record M1 prediction (M1 review). No param/model changes after this file is
    written until real-run data lands."""
    m = result.metrics
    assert m is not None
    route_bytes = route_path.read_bytes()
    route_sha = hashlib.sha256(route_bytes).hexdigest()
    head = _git("rev-parse", "HEAD")
    dirty = _git("status", "--porcelain") != ""
    dec = _decomposition(result)
    lines = [
        "# M1 on-record prediction — Shadowglen→Dolanaar Night Elf hunter route", "",
        "Frozen per the M1 review freeze protocol. **No param or model changes after this file is "
        "written until real-run timing data lands.** Regenerate with `uv run python -m eval.run_route`.",
        "",
        "## Provenance", "",
        f"- git commit: `{head}`" + ("  **(working tree DIRTY at generation — commit to pin)**" if dirty else ""),
        f"- route file: `{route_path.relative_to(ROOT).as_posix()}`",
        f"- route sha256: `{route_sha}`",
        f"- world DB: {World().meta.get('source_db', '?')}",
        "",
        "## Predicted totals", "",
        f"- **total duration: {m.total_seconds:,.0f} s = {m.total_seconds / 60:.1f} min**",
        f"- final level: {m.final_level} ({m.final_xp_into_level} xp into level)",
        f"- quests completed: {m.quests_completed}; level-ups: {m.n_levelups}",
        "",
        "## Time decomposition", "",
        "| bucket | seconds | % |", "|---|---:|---:|",
    ]
    for name in ("travel", "combat", "interaction", "downtime"):
        lines.append(f"| {name} | {dec[name]:,.0f} | {100 * dec[name] / m.total_seconds:.1f}% |")
    lines += ["", "## Predicted level at each turn-in", "",
              "| t (min) | level | xp into | quest |", "|---:|---:|---:|---|"]
    for e in result.timeline:
        if e.step.startswith("TURNIN"):
            q = e.note.split(" (")[0].replace("turn in ", "")
            lines.append(f"| {e.t1 / 60:.1f} | {e.level} | {e.xp} | {q} |")
    body = "\n".join(lines) + "\n"
    # Everything below this sentinel is hand-maintained provenance (forecasts, model-critic
    # hypotheses, grading notes) recorded outside the sim; preserve it across regenerations.
    marker = "<!-- HAND-MAINTAINED BELOW: forecasts & provenance (preserved across regen) -->"
    pred = ROOT / "eval" / "PREDICTIONS.md"
    if pred.exists() and marker in pred.read_text(encoding="utf-8"):
        body += "\n" + marker + pred.read_text(encoding="utf-8").split(marker, 1)[1]
    pred.write_text(body, encoding="utf-8")


def _decomposition(result: engine.EngineResult) -> dict[str, float]:
    return {
        "travel": sum(e.travel_s for e in result.timeline),
        "combat": sum(e.combat_s for e in result.timeline),
        "interaction": sum(e.interaction_s for e in result.timeline),
        "downtime": sum(e.downtime_s for e in result.timeline),
    }


def _print_segment_table(route, result: engine.EngineResult) -> None:  # type: ignore[no-untyped-def]
    print(f"{'#':>3} {'t0(s)':>7} {'trv':>5} {'cmb':>5} {'int':>4} {'dwn':>4} "
          f"{'xp':>5} {'lvl':>3} {'into':>5}  step / note")
    print("-" * 108)
    for e in result.timeline:
        lvl = f"{e.level}" + ("*" if e.levels_gained else "")
        print(f"{e.idx:>3} {e.t0:>7.0f} {e.travel_s:>5.0f} {e.combat_s:>5.0f} "
              f"{e.interaction_s:>4.0f} {e.downtime_s:>4.0f} {e.xp_gained:>5} {lvl:>3} "
              f"{e.xp:>5}  {e.step:<22} {e.note}")


def _plot_xp(result: engine.EngineResult, path: Path) -> None:
    ts = [e.t1 / 60.0 for e in result.timeline]
    lvl_only = [e.level for e in result.timeline]
    fig, ax1 = plt.subplots(figsize=(11, 6))
    ax1.plot(ts, lvl_only, drawstyle="steps-post", color="#3b7a57", lw=2, label="level")
    ax1.set_xlabel("sim time (min)")
    ax1.set_ylabel("level", color="#3b7a57")
    ax1.set_ylim(1, max(lvl_only) + 1)
    ax2 = ax1.twinx()
    cum = 0
    cxp: list[int] = []
    for e in result.timeline:
        cum += e.xp_gained
        cxp.append(cum)
    ax2.plot(ts, cxp, color="#7aa6c2", lw=1.5, alpha=0.8, label="cumulative XP")
    ax2.set_ylabel("cumulative XP", color="#7aa6c2")
    ax1.set_title("Shadowglen hunter route — level & XP over sim time (M1)")
    ax1.grid(True, alpha=0.2)
    fig.tight_layout()
    fig.savefig(path, dpi=130)


if __name__ == "__main__":
    main()
