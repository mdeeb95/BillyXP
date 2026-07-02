# XPWhat

Forward simulator + within-zone route optimizer for WoW Classic Era leveling, scoped to a
Teldrassil vertical slice (levels 1–11, Shadowglen included).

**Read `DESIGN.md` first — it is authoritative.** Project rules live in `CLAUDE.md`.
Milestones and current status: `TODO.md`.

## Setup

```sh
uv sync            # create .venv and install the pinned dependency set
```

## Build (Makefile targets)

On a box with GNU `make`:

```sh
make etl        # raw dump -> data/compiled/world.sqlite + validation report
make validate   # check compiled DB against M0 acceptance criteria
make viz        # Teldrassil spawn/POI map -> out/
make backtest   # stub until M1+
```

On Windows without `make`, use the shim:

```powershell
./make.ps1 etl
./make.ps1 validate
./make.ps1 viz
```

## Data

The compiled `data/compiled/world.sqlite` is built from a VMaNGOS world DB dump. Raw dumps
and compiled outputs are GPL-lineage and stay out of git (`data/`, `out/` are gitignored).
Source lineage is recorded in `data/raw/PROVENANCE.md`; ETL decisions in `etl/NOTES.md`.

## Layout

```
etl/      raw dump -> world.sqlite + validation report
sim/      world, state, dsl, actions, combat, travel, xp, engine, params   (M1+)
router/   tasks, seeds, anneal                                             (M3+)
eval/     reference + generated routes (DSL), backtest
viz/      spawn maps, route overlays, XP curves -> out/
```
