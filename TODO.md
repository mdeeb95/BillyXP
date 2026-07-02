# TODO — XPWhat milestones

Milestone definitions and acceptance criteria: DESIGN.md §12. Scope: Teldrassil vertical
slice (levels 1–11, Shadowglen included), single class, no addon/LLM/multi-zone.

| M | Deliverable | Accept when | Status |
|---|-------------|-------------|--------|
| **M0** | ETL → `world.sqlite` + validation report + spawn/POI map plot | quest count sane (~35–45 incl. Shadowglen); zero orphan objectives/areas; every giver & turn-in has a POI; plot looks like Teldrassil | **in progress** |
| M1 | Engine + hand-written Shadowglen route (1–~6) in DSL | timeline renders end-to-end; predicted duration within ±30% of a reference timing | not started |
| M2 | Combat model v1 + sensitivity report | predicted zone-time vs starting weapon DPS is smooth & monotone; TRAIN and reward-choice bumps visible as EDPS steps in timeline | not started |
| M3 | Task compiler + greedy seed, full zone | feasible 1→11 route end-to-end; total time in a plausible band vs references | not started |
| M4 | SA router | ≥10% better than best greedy seed per sim; route overlay has no visual ping-ponging | not started |
| M5 | Ground-truth calibration run | post-fit sim error ≤15% median per segment | not started |
| M6 | Objective knobs | "fast" vs "HC-safe" produce visibly different routes; hand-written route-diff explanation | not started |

M1 comes before any router work deliberately (DESIGN §12): hand-encoding a known route
forces schema gaps and missing action models to surface early.

## M0 checklist (current)

- [ ] Scaffold: uv project, deps, pyright strict, .gitignore, Makefile, layout — **git commit**
- [ ] Acquire VMaNGOS SQLite world DB → `data/raw/`, write `data/raw/PROVENANCE.md` (URL, tag, commit, date, sha256)
- [ ] Inspect real source schema; record confirmed column mapping in `etl/NOTES.md`
- [ ] ETL → `data/compiled/world.sqlite` per DESIGN §5.2–5.3, provenance columns
  - [ ] Teldrassil bounding box (derive from data + iterate against plot; `out_of_zone` flag)
  - [ ] Quest XP derivation (mangos formula) + Wowhead spot-check of 2–3 Shadowglen quests
  - [ ] Quest-drop chance decoding
  - [ ] Quest chains (prev/next + exclusive groups)
  - [ ] Escort/event flagging
  - [ ] `areas` via DBSCAN over spawns per objective target
  - [ ] `items` weapon_dps; `pois` for givers/turnins/trainers/vendors
- [ ] Validation report (M0 acceptance criteria)
- [ ] Spawn/POI plot → `out/`, colored by kind, quest-giver POIs labeled
- [ ] Present validation report + plot + `etl/NOTES.md`; **stop after M0**
