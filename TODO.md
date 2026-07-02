# TODO — XPWhat milestones

Milestone definitions and acceptance criteria: DESIGN.md §12. Scope: Teldrassil vertical
slice (levels 1–11, Shadowglen included), single class, no addon/LLM/multi-zone.

| M | Deliverable | Accept when | Status |
|---|-------------|-------------|--------|
| **M0** | ETL → `world.sqlite` + validation report + spawn/POI map plot | quest count sane (~35–45 incl. Shadowglen); zero orphan objectives/areas; every giver & turn-in has a POI; plot looks like Teldrassil | **DONE** (acceptance PASS) |
| M1 | Engine + hand-written Shadowglen route (1–~6) in DSL | timeline renders end-to-end; predicted duration within ±30% of a reference timing | **FROZEN** — sim built + reviewed; route runs end-to-end; prediction on record in `eval/PREDICTIONS.md`; awaiting real-run timing for ±30% |

**M1 scope note:** the reference route is **Shadowglen + the first Dolanaar tier** (26 quests,
1→7, ~110 min predicted). DESIGN §12 says "1–~6"; reaching L7 by clearing that natural quest set
is intentional (more turn-ins for the M5 fit; the Dolanaar tier is the only part that exercises
travel over real distances). Endpoint = whatever the route says, since the reference timing is a
real playthrough of this exact route. DESIGN.md §12 left as-is with a deviation note.
| M2 | Combat model v1 + sensitivity report | predicted zone-time vs starting weapon DPS is smooth & monotone; TRAIN and reward-choice bumps visible as EDPS steps in timeline | not started |
| M3 | Task compiler + greedy seed, full zone | feasible 1→11 route end-to-end; total time in a plausible band vs references | not started |
| M4 | SA router | ≥10% better than best greedy seed per sim; route overlay has no visual ping-ponging | not started |
| M5 | Ground-truth calibration run | post-fit sim error ≤15% median per segment | not started |
| M6 | Objective knobs | "fast" vs "HC-safe" produce visibly different routes; hand-written route-diff explanation | not started |
| M7 | Vendor economy & upgrade detours (Teldrassil exit gate) | zero-hint "fast to 11" route buys the vendor ranged upgrade (feasible vs gold curve); ablating BUY is slower; predicted Δtime consistent with calibration pre/post kill-timing | not started |

**M7 note — ammo (hunter):** ranged damage is weapon **+ ammo** dps, and ammo is a *recurring*
consumable, not a one-off. The economy model must debit arrows over time (not just the bow at point
of sale), and `ranged_dps` should become a function of (weapon, ammo). See DESIGN §13. The M1
kill-timing experiment already holds ammo constant across arms so the ranged-upgrade delta isn't
confounded (`eval/playsheet.py` epilogue controls).

M1 comes before any router work deliberately (DESIGN §12): hand-encoding a known route
forces schema gaps and missing action models to surface early.

## Unblock task — world→zone-map transform via Questie (TomTom `/way`)

TomTom `/way` output is gated: the world→zone-map affine transform is **BLOCKED** because
classic.wowhead.com renders NPC map coords in JavaScript (unreachable via WebFetch). Browser
scraping is **declined**. Instead, anchor the transform from **Questie's spawn data**, which stores
NPC spawns in zone-map percent coords keyed by NPC entry id:

- [ ] **Verify the coord convention** on 2–3 landmark NPCs first (e.g. Conservator Ilthalaine 2079,
  Jeena Featherbow 3610) — confirm Questie's values are 0–100 zone-map %, axis orientation, and that
  the key is the NPC entry id. **Cite the exact Questie source file** (repo + path + version/commit).
- [ ] Join Questie map coords against our POI world coords by entry id (≥5 in-zone anchors).
- [ ] Fit affine `map = A·world + b` (reuse `eval/mapproj.py`); **report the residual distribution
  and worst outliers**. The **1%-of-extent gate stands** — if the worst residual exceeds it, stay
  BLOCKED and surface the report (do not emit `/way` from a bad fit).
- [ ] Record provenance in `eval/teldrassil_mapproj.json`: **Questie version/commit**, source file,
  per-anchor (entry, world xy, Questie map xy). No transform constants from memory (CLAUDE.md rule 1).
- [ ] On a passing fit, `--with-tomtom` auto-ungates (`eval/playsheet.py` already emits `/way` only
  when the record's `status == OK`).

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
