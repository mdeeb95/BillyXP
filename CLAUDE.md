# CLAUDE.md

## Project

XPWhat: a forward simulator + route optimizer for WoW Classic Era leveling, currently scoped to a Teldrassil vertical slice. **Read DESIGN.md first — it is authoritative.** If an implementation choice conflicts with DESIGN.md, stop and flag it rather than picking silently.

## Hard rules

1. **No fabricated game data.** Every quest, mob, spawn, item, and XP fact must come from `data/compiled/world.sqlite` (with provenance columns) or from `sim/params.py` with a source comment. If data is missing or ambiguous: stop and surface it. Never approximate a game fact from memory — not quest XP values, not spell names, not mob levels.
2. **Determinism.** Engine output depends only on `(world, state, plan, params, seed)`. No wall-clock, no hidden randomness.
3. **All tunables in `sim/params.py`.** No magic numbers inside model code. Every param has a comment: source or "initial guess, calibrate M5".
4. **Types.** Pyright strict. Dataclasses/pydantic for all schemas crossing module boundaries.
5. **Tests.** Every action model gets hand-verifiable unit tests against the anchors below. Combat and XP functions get table-driven tests.
6. **Before committing model or param changes:** run `make validate && make backtest`, include the summary in the commit message.
7. **Performance budget lives in one place:** `evaluate_from` suffix evals ≤ 5 ms. Do not prematurely optimize anything else.
8. **Freeze protocol.** While a freeze is active (an annotated tag like `m1-freeze` exists), run `make verify-freeze` (`./make.ps1 verify-freeze` on Windows) **at session start and before every commit**; it must exit 0. The gate asserts: no uncommitted changes to **frozen artifacts** (`sim/**`, the route DSL, `PREDICTIONS.md`), route sha256 unchanged, and exact reproduction of `PREDICTIONS.md` (total + every turn-in). The clean-tree check is scoped to frozen paths so it is runnable *before* a commit — modifying frozen code without re-freezing is a hard fail; non-frozen edits (tooling, docs) are fine. A red gate blocks the commit — investigate, never rationalize. **Declaring a freeze or applying a freeze tag requires pasted git receipts in the report** (`git log --oneline`, `git tag`, the reproduction diff) — never a prose assertion that something is "frozen." A freeze that isn't pinned to a committed hash + tag is not frozen. The integrity ledger (`PREDICTIONS.md` → Freeze integrity) records its own failures; do not rewrite history to hide a gap.

## Verified anchors (extend only with a source)

- XP to go from level 1 → 2: **400** (vanilla table)
- Base run speed: **7.0 yd/s**
- Talents begin at **level 10** (out of scope for this slice)
- Kalimdor is **map 1** in spawn coordinates

## Workflow

- Plan mode for schema changes, DSL changes, or anything touching `engine.py` interfaces.
- Every router change regenerates the route overlay to `out/` — visual inspection is part of review.
- Dependencies: numpy, scipy, pandas, networkx, matplotlib, pydantic, pytest. Ask before adding anything else.
- ETL wrinkles listed in DESIGN.md §5.2 are known unknowns: resolve them against the actual dump, don't guess column names.

## Layout

```
etl/      raw SQL dump → world.sqlite + validation report
sim/      world, state, dsl, actions, combat, travel, xp, engine, params
router/   tasks (quest → atom graph), seeds, anneal
eval/     reference + generated routes (DSL), backtest
viz/      spawn maps, route overlays, XP curves → out/
```

## Current milestone

Track in TODO.md. Milestone definitions and acceptance criteria: DESIGN.md §12.
