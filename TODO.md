# TODO — XPWhat milestones

Milestone definitions and acceptance criteria: DESIGN.md §12. Scope: Teldrassil vertical
slice (levels 1–11, Shadowglen included), single class, no addon/LLM/multi-zone.

| M | Deliverable | Accept when | Status |
|---|-------------|-------------|--------|
| **M0** | ETL → `world.sqlite` + validation report + spawn/POI map plot | quest count sane (~35–45 incl. Shadowglen); zero orphan objectives/areas; every giver & turn-in has a POI; plot looks like Teldrassil | **DONE** (acceptance PASS) |
| M1 | Engine + hand-written Shadowglen route (1–~6) in DSL | timeline renders end-to-end; predicted duration within ±30% of a reference timing | not started |
| M2 | Combat model v1 + sensitivity report | predicted zone-time vs starting weapon DPS is smooth & monotone; TRAIN and reward-choice bumps visible as EDPS steps in timeline | not started |
| M3 | Task compiler + greedy seed, full zone | feasible 1→11 route end-to-end; total time in a plausible band vs references | not started |
| M4 | SA router | ≥10% better than best greedy seed per sim; route overlay has no visual ping-ponging | not started |
| M5 | Ground-truth calibration run | post-fit sim error ≤15% median per segment | not started |
| M6 | Objective knobs | "fast" vs "HC-safe" produce visibly different routes; hand-written route-diff explanation | not started |

M1 comes before any router work deliberately (DESIGN §12): hand-encoding a known route
forces schema gaps and missing action models to surface early.

## M0 checklist (complete)

- [x] Scaffold: uv project, deps, pyright strict, .gitignore, Makefile, layout — committed
- [x] Acquire VMaNGOS SQLite world DB → `data/raw/`, `data/raw/PROVENANCE.md` (URL, tag, commit, date, sha256)
- [x] Inspect real source schema; confirmed column mapping in `etl/NOTES.md` §0
- [x] ETL → `data/compiled/world.sqlite` per DESIGN §5.2–5.3, provenance columns
  - [x] Teldrassil bounding box (derived via DBSCAN largest cluster + margin; `out_of_zone` flag; iterated against plot)
  - [x] Quest XP: uses stored `RewXP` (divergence from "derive" — documented) + Wowhead spot-check of 3 quests (all match)
  - [x] Quest-drop chance decoding (mangos negative-chance convention)
  - [x] Quest chains (prev_quest + exclusive_group)
  - [x] Escort/event flagging (SpecialFlags EXPLORATION_OR_EVENT → ESCORT: Mist, Druid of the Claw)
  - [x] `areas` via DBSCAN over spawns per objective target
  - [x] `items` weapon_dps; `pois` for givers/turnins/trainers/vendors/hearth
- [x] Validation report (M0 acceptance criteria) → `out/validation.md` (PASS)
- [x] Spawn/POI plot → `out/teldrassil_spawns.png`, colored by kind, quest-giver POIs labeled
- [x] Smoke tests (`tests/test_compiled_world.py`), pyright strict clean
- [ ] **Present to user; stop after M0. Do not start M1.**

## Next (M1 — do NOT start without go-ahead)

Engine + hand-written Shadowglen route (1–~6) in DSL. Plan mode required (touches
`sim/engine.py` interfaces per CLAUDE.md workflow).
