"""Freeze-integrity gate: prove the committed sim still reproduces the frozen prediction.

    uv run python -m eval.verify_freeze

While the m1-freeze is active this MUST pass at session start and before every commit (CLAUDE.md).
It is read-only — it never rewrites PREDICTIONS.md; it re-simulates the frozen route through the
CURRENTLY COMMITTED sim and diffs the result against the on-record numbers.

Two independent kinds of check, deliberately complementary:
  * GIT EQUALITY pins the CODE. Frozen code (sim/**, the route DSL) must be (a) free of uncommitted
    changes and (b) content-identical at HEAD to the `m1-freeze` tag — a committed edit that still
    reproduces the numbers by luck (or a refactor) is caught here even though reproduction passes.
  * REPRODUCTION pins the gitignored DATA. data/compiled/world.sqlite is not in git, so git equality
    is blind to it; re-simulating and matching the recorded numbers is the only thing that pins it.
  Each covers the other's blind spot; both are permanent while the freeze is active.

Checks (nonzero exit on any failure):
  1a. no uncommitted changes to frozen CODE (sim/**, the route DSL) — runnable before a commit
      (a whole-tree-clean assert can never pass at the moment you commit); non-frozen edits allowed.
  1b. frozen CODE at HEAD is byte-identical to the `m1-freeze` tag (committed-drift guard).
  2.  route file sha256 == the frozen value;
  3.  total duration == the frozen total (exact seconds);
  4.  every turn-in row (t in min, level, xp-into-level) matches PREDICTIONS.md within tolerance.
PREDICTIONS.md is a living, append-only ledger during the freeze: it is EXEMPT from git equality
(1a/1b). Its frozen NUMBERS stay pinned by the reproduction match (3/4), not by its bytes.
"""

from __future__ import annotations

import hashlib
import re
import subprocess
import sys
from pathlib import Path

from sim import engine
from sim.dsl import parse_route
from sim.params import Params
from sim.world import World

ROOT = Path(__file__).resolve().parent.parent
ROUTE = ROOT / "eval" / "routes" / "shadowglen_hunter.dsl"
PRED = ROOT / "eval" / "PREDICTIONS.md"
FROZEN_ROUTE_SHA = "321e3c3547a3e545c45d6d670fd249906a9201d36f87279e2a09b9accdbb78ab"
FREEZE_TAG = "m1-freeze"
T_MIN_TOL = 0.05  # minutes: table is rounded to 0.1 min, so half a rounding step
# Frozen CODE paths — git equality (clean working tree + byte-identical to the tag) applies here.
# PREDICTIONS.md is intentionally ABSENT: it is an append-only ledger during the freeze, pinned by
# reproduction (checks 3/4), not by its bytes.
FROZEN_CODE = ("sim/", "eval/routes/shadowglen_hunter.dsl")


def _git(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(["git", *args], cwd=ROOT, capture_output=True, text=True)


def _fresh_hunter(world: World):  # type: ignore[no-untyped-def]
    from eval.run_route import fresh_hunter
    return fresh_hunter(world)


def _frozen_total_seconds() -> int:
    m = re.search(r"total duration:\s*([\d,]+)\s*s", PRED.read_text(encoding="utf-8"))
    if not m:
        raise SystemExit("verify-freeze: could not find frozen total in PREDICTIONS.md")
    return int(m.group(1).replace(",", ""))


def _frozen_turnins() -> list[tuple[float, int, int, str]]:
    """Parse the '| t (min) | level | xp into | quest |' table -> (t_min, level, xp, quest)."""
    rows: list[tuple[float, int, int, str]] = []
    in_table = False
    for ln in PRED.read_text(encoding="utf-8").splitlines():
        if ln.startswith("| t (min)"):
            in_table = True
            continue
        if in_table:
            if not ln.startswith("|") or ln.startswith("|---"):
                if rows:
                    break
                continue
            cells = [c.strip() for c in ln.strip().strip("|").split("|")]
            if len(cells) == 4 and cells[0].replace(".", "").isdigit():
                rows.append((float(cells[0]), int(cells[1]), int(cells[2]), cells[3]))
    return rows


def main() -> None:
    fails: list[str] = []

    # 1a. no uncommitted changes to frozen CODE (scoped clean-tree; see module docstring)
    porcelain = _git("status", "--porcelain").stdout.strip()
    tree_clean = porcelain == ""
    frozen_dirty = [ln for ln in porcelain.splitlines()
                    if ln[3:].strip().startswith(FROZEN_CODE)]
    if frozen_dirty:
        fails.append("uncommitted changes to frozen CODE (re-freeze required):\n"
                     + "\n".join(frozen_dirty))

    # 1b. frozen CODE at HEAD is byte-identical to the freeze tag (committed-drift guard). Git
    #     equality pins the code; reproduction (3/4) pins the gitignored data/compiled path.
    tags = _git("tag").stdout.split()
    if FREEZE_TAG not in tags:
        fails.append(f"freeze tag `{FREEZE_TAG}` not found — a freeze must be pinned to a tag")
    else:
        drift = _git("diff", "--name-only", FREEZE_TAG, "HEAD", "--", *FROZEN_CODE).stdout.strip()
        if drift:
            fails.append(f"frozen CODE at HEAD differs from tag `{FREEZE_TAG}` (committed drift):\n"
                         + drift)

    # 2. route sha
    sha = hashlib.sha256(ROUTE.read_bytes()).hexdigest()
    if sha != FROZEN_ROUTE_SHA:
        fails.append(f"route sha {sha} != frozen {FROZEN_ROUTE_SHA}")

    # 3-4. re-simulate and diff
    world = World()
    route = parse_route(ROUTE.read_text(encoding="utf-8"), world)
    result = engine.execute(world, _fresh_hunter(world), route, Params())
    assert result.metrics is not None
    total = round(result.metrics.total_seconds)
    frozen_total = _frozen_total_seconds()
    if total != frozen_total:
        fails.append(f"total {total} s != frozen {frozen_total} s (Δ {total - frozen_total})")

    frozen = _frozen_turnins()
    got = [(round(e.t1 / 60.0, 1), e.level, e.xp) for e in result.timeline
           if e.step.startswith("TURNIN")]
    if len(got) != len(frozen):
        fails.append(f"turn-in count {len(got)} != frozen {len(frozen)}")
    else:
        for i, ((ft, fl, fx, q), (gt, gl, gx)) in enumerate(zip(frozen, got)):
            if abs(gt - ft) > T_MIN_TOL or gl != fl or gx != fx:
                fails.append(f"turn-in {i} ({q}): frozen (t={ft},lvl={fl},xp={fx}) "
                             f"!= got (t={gt},lvl={gl},xp={gx})")

    if fails:
        print("VERIFY-FREEZE: FAIL")
        for f in fails:
            print("  - " + f)
        sys.exit(1)
    tree_note = "whole tree clean" if tree_clean else "frozen artifacts clean (non-frozen edits present)"
    print(f"VERIFY-FREEZE: PASS — total {total} s, {len(got)} turn-ins match PREDICTIONS.md; "
          f"route sha {sha[:12]}; {tree_note}.")


if __name__ == "__main__":
    main()
