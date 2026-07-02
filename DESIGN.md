# XPWhat — Simulator + Router MVP (Teldrassil Vertical Slice)

## 1. Purpose

Forward simulator for WoW Classic Era leveling plus a within-zone route optimizer, validated on Teldrassil (levels 1–11, Shadowglen included). This is phases 1–2 of the larger planning system: no addon, no LLM, no multi-zone travel, no AH. Deliverable: a route for a fresh night elf that the simulator scores accurately, a human can follow, and that morphs sensibly when the objective shifts from "level fast" to "HC-safe".

This document is authoritative. If code and this doc disagree, flag it — don't silently pick one.

## 2. Non-goals (this slice)

- Addon I/O — simulator consumes synthetic `CharacterState` only
- LLM goal compiler / critic / explainer
- Multi-zone macro planning, flight paths, AH, professions, dungeons
- Player-competition modeling (single-player world assumption; see §13)

## 3. Architecture

```
raw dumps (vmangos SQL)
      │  etl/
      ▼
world.sqlite  (typed, versioned, provenance-tagged)
      │
      ▼
sim/   engine: (world, CharacterState, plan) → timeline + metrics   [pure, deterministic]
      ▲
      │  evaluator (prefix-cached)
router/  SA over task sequences, sim as objective
      │
      ▼
eval/ + viz/   backtests, route map overlays, sensitivity reports
```

## 4. Repo layout

```
xpwhat/
├── data/
│   ├── raw/            # vmangos dump, extracts (gitignored)
│   └── compiled/       # world.sqlite (gitignored; rebuild via make etl)
├── etl/                # SQL dump → world.sqlite + validation report
├── sim/
│   ├── world.py        # loaded world model, spatial index over spawns/POIs
│   ├── state.py        # CharacterState
│   ├── dsl.py          # step types, parse/serialize
│   ├── actions.py      # duration + state-delta per step type
│   ├── combat.py       # kill-rate model
│   ├── travel.py       # TravelModel interface + EuclideanK impl
│   ├── xp.py           # kill XP formula, level table, rested
│   ├── engine.py       # plan executor, checkpointing, timeline emit
│   └── params.py       # ALL tunables, with source comments
├── router/
│   ├── tasks.py        # quests → atoms + precedence graph
│   ├── seeds.py        # greedy constructive seeds
│   └── anneal.py       # SA: moves, repair, cooling
├── eval/
│   ├── routes/         # reference + generated routes in DSL
│   └── backtest.py
├── viz/                # spawn maps, route overlays, XP curves → out/
├── out/                # generated artifacts (gitignored)
├── DESIGN.md
├── CLAUDE.md
└── Makefile            # etl / validate / backtest / route / viz targets
```

## 5. Data

### 5.1 Source

vmangos world database (targets patch 1.12; Era is 1.12-derived — acceptable fidelity for this zone). Alternative if needed: cmangos `classic-db`. Raw dumps and compiled outputs stay out of git. Mangos-lineage data is GPL — compiled DB is for personal use in this phase.

Tables of interest (verify exact names/columns against the actual dump before writing ETL): `quest_template`, `creature_template`, `creature` (spawn rows: map, x, y, z, spawntime), `gameobject_template`, `gameobject`, `creature_loot_template` / `gameobject_loot_template` (quest-drop chances; mangos encodes quest drops as negative chance values — verify), `npc_trainer`, `npc_vendor`, `item_template` (weapon damage/delay → DPS).

### 5.2 ETL wrinkles — resolve, don't guess

- **Zone filtering:** spawn rows carry map + world coords, not a zone id. Filter Teldrassil via bounding box on Kalimdor (map 1); validate with the spawn plot (M0), tighten the box by eye.
- **Quest XP:** vanilla cores don't store flat quest XP; it derives from quest_template fields (the max-level money conversion). Implement the standard mangos derivation and verify against 2–3 quests with independently known XP values before trusting it anywhere.
- **Quest chains:** prev/next quest fields + exclusive groups → precedence edges.
- **Escort/event quests:** mark `kind=ESCORT`, fixed duration param, don't model the event.
- **Provenance:** every compiled row keeps `src_table`, `src_pk`.

### 5.3 Compiled schema (world.sqlite)

```sql
quests(id, name, min_level, quest_level, giver_kind, giver_id,
       turnin_kind, turnin_id, prev_quest, exclusive_group,
       xp, money, reward_choices JSON, src_table, src_pk)

objectives(quest_id, idx, kind,          -- KILL|COLLECT|OBJECT|EXPLORE|ESCORT
           target_id, count, drop_chance, area_id)

mobs(id, name, lvl_min, lvl_max, hp_min, hp_max, armor,
     dps_est, elite, archetype)          -- archetype: melee|caster|ranged, for HC hazard later

spawns(guid, kind,                        -- CREATURE|OBJECT
       entry, x, y, z, respawn_s)

areas(id, target_entry, centroid_x, centroid_y, radius,
      n_spawns, density)                  -- DBSCAN over spawns per objective target

pois(id, kind,                            -- GIVER|TURNIN|TRAINER|VENDOR|HEARTH|WAYPOINT
     ref_id, x, y)

items(id, name, slot, weapon_dps, armor, stats JSON)

xp_levels(level, xp_to_next)              -- vanilla constants; 1→2 = 400
```

`areas` is the routing substrate: objective work happens at areas, everything else at POIs.

## 6. Character state

```python
@dataclass
class CharacterState:
    clazz: Class                 # one class for this slice — the M5 calibration class
    level: int
    xp: int
    pos: Vec2
    gold_c: int                  # copper
    weapon_dps: float
    quest_log: dict[int, list[int]]   # quest_id → per-objective progress
    completed: set[int]
    known_spell_bumps: set[str]  # trained breakpoints applied (see §8.2)
    hearth_poi: int
    rested_pool: int             # default 0 for fresh char; flag exists
    supplies: dict[str, int]     # food/water counts
    t: float                     # sim seconds
```

Talents are omitted entirely: they begin at level 10, the very end of this slice.

## 7. Action DSL

```
GOTO   <poi|x,y>
ACCEPT <quest>
WORK   <quest> <obj_idx> <area> [frac=1.0]   # kill/collect until objective fraction reached
TURNIN <quest> [choice_item]
TRAIN  <ALL|bump_id...>
BUY    <item> <n>
SETHEARTH <poi>
HEARTH
GRIND  <mob> <area> <xp_target>              # filler, inserted by repair when level-gated
```

The router mutates **task sequences**; the engine compiles a sequence into an **itinerary** — a timestamped list of DSL steps — plus a timeline. Timeline JSON per step: `{t0, t1, step, xp, level, gold_c, pos, notes}`. The timeline is a first-class artifact: it feeds viz, backtest diffing, calibration fitting, and later the LLM explainer.

## 8. Models

### 8.1 Travel

`time = euclid(a, b) × k_zone / speed`, `speed = 7.0 yd/s` (base run). `k_zone` init 1.3, calibrated in M5. `TravelModel` is an interface — a waypoint-graph or navmesh (mmap) implementation replaces EuclideanK later without touching the engine.

### 8.2 Combat / kill rate

```
EDPS(class, level, weapon_dps) = a[class, band] + b[class, band] * weapon_dps
    band ∈ {1–4, 5–8, 9–12}
    trained breakpoints multiply: EDPS *= Π bump_mult for applied bumps

TTK       = EHP / (EDPS * delta_penalty(mob_lvl − char_lvl))
EHP       = hp * (1 + armor_factor)            # physical classes
kill_cycle = TTK + acquire(density, respawn floor) + t_loot + downtime
    downtime: multiplicative overhead factor per (class, band)  # eat/drink/bandage
COLLECT    : expected_kills = count / drop_chance
```

Trained-ability breakpoints: a small per-class table in `params.py` of `(level, bump_id, mult)` rows — filled by hand for the one chosen class from trainer data in the DB, verified manually. Do not enumerate spells from memory.

All stochastic quantities are expectations in v0. Combat functions return `(mean, var)` so HC hazard / Monte Carlo slots in later without interface churn.

### 8.3 XP

Kill XP: standard vanilla formula — base `(char_lvl × 5 + 45)` with level-delta multipliers and gray cutoffs. Implement from the known reference formula; unit-test at several (char, mob) level pairs. Quest XP from compiled DB (§5.2). Rested: 2× kill XP against pool, toggleable, default off (fresh character).

### 8.4 Reward choice

On `TURNIN` with choices: pick argmax item score (weapon DPS dominates at this bracket; simple slot-aware score), update state. This is where "gear and speed are one objective" is visible inside a single zone — reward picks should show up as EDPS steps in the timeline.

### 8.5 Deaths

Non-HC v0: ignored. HC (M6): hazard per kill cycle `= f(level_delta, adds_prob(local density), mob archetype)`; itinerary constraint `P(death) ≤ ε` plus a cap on max single-step hazard. Consumes the `var`/hazard outputs stubbed in §8.2.

## 9. Params & calibration

Every coefficient lives in `sim/params.py` with a source comment: `k_zone`, EDPS `a/b` tables, downtime multipliers, delta penalties, interaction times (`t_accept ≈ 4s`, `t_turnin ≈ 5s`, `t_loot ≈ 2.5s` — initial guesses, calibrated later).

M5 protocol: play the M4 route on a fresh character; log `/played` at every turn-in (macro or manual), plus deaths and drink counts. Fit `k_zone`, downtime, and `a/b` by least squares on segment times. Params changes require a backtest re-run and a changelog entry.

## 10. Engine

Pure function: `(world, state, sequence | itinerary) → (timeline, metrics, final_state)`. Deterministic given params.

**Prefix caching is a core requirement:** the engine supports `evaluate_from(checkpoint_state, suffix)`. SA mutations re-simulate only from the mutation point. Target ≤ 5 ms per suffix eval so a 50k-move anneal completes in minutes. This same mechanism is the future receding-horizon replanner — a real mid-route state sync is just a checkpoint.

Level-ups recompute derived stats; trainer bumps at eligible levels are flagged pending until a `TRAIN` step applies them. Invariants asserted every step: monotonic time, non-negative gold, objective progress within bounds, level gates respected. Gate violations return `(infeasible, first_violating_index)` for the router's repair moves.

## 11. Router

### 11.1 Task compilation

Quests → atoms:
- `PICKUP(poi, quest_set)` — co-located givers merged
- `WORK(quest, obj, area, frac)` — splittable
- `TURNIN(poi, quest_set)` — co-located turn-ins merged

Precedence edges: chain prev→next, PICKUP→WORK→TURNIN per quest, exclusive groups. Level gates are not edges — they're feasibility checks inside the sim.

### 11.2 Seed

Greedy nearest-feasible-neighbor with one-step lookahead and a sweep bias along the zone's main road axis. Generate a few randomized seeds.

### 11.3 Simulated annealing

State: ordered atom sequence + WORK fractions. Moves: swap, relocate-block, split WORK, merge WORK, flip reward choice, insert/remove GRIND filler. Infeasible sequences: repair-first (move violator after its prerequisite; insert GRIND at nearest efficient area when level-gated), else penalty. Objective: total time to terminal condition — default **reach level 11, all picked-up quests turned in, end at Darnassus** — plus soft penalties (hazard, for HC mode). Geometric cooling, restarts from incumbent best, budget ~50k evals.

## 12. Milestones & acceptance criteria

| M | Deliverable | Accept when |
|---|---|---|
| M0 | ETL → world.sqlite + validation report + spawn/POI map plot | quest count sane (~35–45 incl. Shadowglen); zero orphan objectives/areas; every giver & turn-in has a POI; plot looks like Teldrassil |
| M1 | Engine + **hand-written Shadowglen route (1–~6) in DSL** | timeline renders end-to-end; predicted duration within ±30% of a reference timing (VOD or own run) |
<!-- M1 deviation (approved): the reference route runs Shadowglen + the first Dolanaar tier and
     reaches ~L7, not L6. "1–~6" was scope shorthand; the endpoint is whatever the route covers,
     since the reference timing is a real playthrough of that exact route. See TODO.md M1 scope
     note and eval/PREDICTIONS.md. -->

| M2 | Combat model v1 + sensitivity report | plot of predicted zone time vs starting weapon DPS is smooth and monotone; TRAIN and reward-choice bumps visible as EDPS steps in timeline |
| M3 | Task compiler + greedy seed, full zone | feasible 1→11 route end-to-end; total time in a plausible band vs references |
| M4 | SA router | ≥10% better than best greedy seed per sim; route overlay has no visual ping-ponging |
| M5 | Ground-truth calibration run | post-fit sim error ≤15% median per segment |
| M6 | Objective knobs | "fast" vs "HC-safe" produce visibly different routes (high-delta/high-density areas and caves avoided); write the route-diff explanation by hand — that text is the job spec for the future LLM explainer |
| M7 | Vendor economy & upgrade detours (Teldrassil exit gate) | zero-hint "fast to 11" route buys the vendor ranged-weapon upgrade, timed feasibly against the simulated gold curve; ablating the BUY and re-simulating is slower; the sim's predicted Δtime from the purchase is consistent with the measured pre/post kill-timing experiment from the calibration run |

M1 before any router work, deliberately: hand-encoding a known route forces every schema gap and missing action model to surface on a 30-minute scope.

**M7 — Vendor economy & upgrade detours (exit gate for the Teldrassil slice).**
Scope:
- **Gold income:** quest money from the DB; expected copper/kill = coin drops + Σ(sell_price × drop_chance) over the mob's loot table, accrued at kills.
- **Gold expenses:** training costs (trainer tables) and purchases.
- **`BUY_UPGRADE` candidate atoms** generated from `npc_vendor × item_template` (in-zone vendor POIs, slot-upgrade filter vs projected gear, `level_req` respected).
- **Router:** SA optional-atom include/exclude moves; gold-gate repair (insert grind-for-gold or reposition the purchase after quest income lands).
Acceptance is **zero-hint**: the planner input is a fresh hunter + the objective "fast to 11" with no hints. PASS iff (1) the emitted route buys the vendor ranged-weapon upgrade, timed feasibly against the simulated gold curve; (2) ablating the BUY and re-simulating is slower; and (3) the sim's predicted Δtime from the purchase is consistent with the measured pre/post kill-timing experiment from the calibration run (tolerance set once that data exists).
Known optimism: no bag-space or vendoring-loop modeling at this bracket.

## 13. Risks / known optimism

- **Travel realism:** Euclidean×k breaks on Teldrassil's verticality and water. If M5 residuals concentrate on travel segments, promote to a hand-laid waypoint graph before touching combat params.
- **Uncontested world:** no competition for spawns; respawn floors in `acquire()` partially cover it. Real-server times will run worse than sim on contested layers — acceptable for now, note it in outputs.
- **Class variance:** one class only for this slice — the class that gets replayed in M5.
- **vmangos (1.12) vs Era deltas:** assumed negligible for Teldrassil; spot-check any suspicious quest against the Era client or Wowhead Classic.
- **License:** GPL-lineage data; compiled DB private, no redistribution in this phase.
- **Candidate explosion (M7+):** `BUY_UPGRADE` and other optional atoms multiply the search space. Dominance filtering — prune candidates dominated per slot / level-band — is required before multi-zone scale, else the SA state space blows up.
- **Ranged damage = weapon + ammo (hunter):** `ranged_dps` currently models the bow/gun alone. A hunter's actual ranged output is weapon dps **plus** the equipped ammo's dps, so the combat model should eventually make `ranged_dps` a function of (weapon, ammo). This matters twice: (1) calibration — the M1 kill-timing experiment must hold ammo constant across arms (see `eval/playsheet.py` epilogue controls) or the ranged-upgrade delta is confounded; (2) the M7 economy model — ammo is a **recurring consumable expense** (unlike the one-off weapon purchase), so a correct gold curve must debit arrows over time, not just the bow at point of sale. Deferred until real ammo dps values are pulled from the DB (no ammo facts from memory).

## 14. Later phases (context only — do not build)

Macro planner across zones, AH/detour NPV, LLM goal compiler + plan critic + explainer, addon export/import, fleet telemetry fitting. The sequence/itinerary split, the timeline artifact, `(mean, var)` interfaces, and `evaluate_from` checkpointing all exist to serve these — don't optimize them away.
