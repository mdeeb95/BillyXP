# ETL notes — source schema mapping & §5.2 wrinkle resolutions

Source: `data/raw/sqlite-dump/mangos.sqlite` (VMaNGOS, commit `b40576b`; see
`data/raw/PROVENANCE.md`). Compiled target: `data/compiled/world.sqlite` (schema per
DESIGN §5.3). Everything below was confirmed against the actual dump — DESIGN §5.1 names
were treated as expectations, not facts.

## 0. Confirmed source schema (real column names)

| Concept | DESIGN expectation | **Actual in dump** |
|---|---|---|
| Quests | `quest_template` | `quest_template` — `entry, Title, MinLevel, QuestLevel, ZoneOrSort, RewXP, RewOrReqMoney, PrevQuestId, NextQuestId, ExclusiveGroup, SpecialFlags, ReqCreatureOrGOId1..4 (+Count), ReqItemId1..4 (+Count), ReqSourceId1..4, RewChoiceItemId1..6 (+Count), RewItemId1..4, patch` |
| Quest giver / turn-in | (implied in quest_template) | **relation tables**: `creature_questrelation(id,quest)` = giver, `creature_involvedrelation(id,quest)` = turn-in; `gameobject_questrelation` / `gameobject_involvedrelation` for object givers/turn-ins |
| Creature spawns | `creature(map,x,y,z,spawntime)` | `creature(guid, id, map, position_x, position_y, position_z, spawntimesecsmin, spawntimesecsmax, patch_min, patch_max)` (entry column is `id`) |
| Creature stats | `creature_template(... hp, armor)` | `creature_template` has **no** direct hp/armor — `level_min, level_max, unit_class, health_multiplier, armor_multiplier, damage_multiplier, base_attack_time, rank, loot_id`; hp/armor come from `creature_classlevelstats(class, level, health, armor, melee_damage)` |
| Object spawns / templates | `gameobject(_template)` | `gameobject(guid,id,map,position_x/y/z,spawntimesecs*,patch_*)`, `gameobject_template(entry,type,name,...)` |
| Loot / quest-drop | `*_loot_template` | `creature_loot_template` / `gameobject_loot_template(entry,item,ChanceOrQuestChance,mincountOrRef,maxcount)` |
| Items | `item_template` | `item_template(entry,name,class,subclass,inventory_type,armor,dmg_min1,dmg_max1,delay,stat_type1..10,stat_value1..10,...)` |
| Trainers / vendors | `npc_trainer`, `npc_vendor` | `npc_trainer(entry,spell,...)`, `npc_vendor(entry,item,...)` — membership by `entry` |
| XP table | `xp_levels` (populate from constants) | **`player_xp_for_level(lvl, xp_for_next_level)` exists in the dump** — used directly |
| Zone identity | (bounding box only) | **`area_template(entry, map_id, zone_id, name)` exists** — Teldrassil found by name, not from memory |

## 1. Zone identity — Teldrassil id from the DB (not memory)

`area_template` where `name` matches:
- **Teldrassil = entry 141**, `map_id=1` (matches the verified anchor "Kalimdor is map 1").
- Sub-areas with `zone_id=141`: **Shadowglen (188)**, Dolanaar (186), Aldrassil (256),
  Pools of Arlithrien (478). Darnassus = **1657** (separate zone, the route end-point).

Quest set for the slice = quests whose `ZoneOrSort` is Teldrassil (141) or any `area_template`
sub-area with `zone_id = 141`. Only three such sorts actually carry quests (found from the
data, not assumed):

- **Teldrassil (141)** → 35 quests
- **Shadowglen (188)** → 14 quests
- **Rut'theran Village (702)** → 4 quests (the harbor at the base of the tree — the
  boat/flight hub to Darnassus; legitimately Teldrassil)

Deduped by `entry` keeping the max `patch` ≤ 10 (1.12 revision): **53 distinct quests**. This
runs slightly above the DESIGN §12 "~35–45 incl. Shadowglen" sanity band because it includes
the Rut'theran harbor quests, one level-60 Lunar Festival quest (8734, giver in Moonglade →
flagged `out_of_zone`), and one `<UNUSED>` row (490). Net in-zone leveling quests ≈ 50. Per
CLAUDE.md rule 1, real quests are kept and flagged, never dropped to hit a target; the
validation report prints the full breakdown. Self-consistent cross-check: the giver/turn-in
spawns of this set form a single isolated NW-Kalimdor cluster (below), confirming the zone.

## 2. §5.2 wrinkle — Teldrassil bounding box (data-driven, no hardcoded coords)

Method:
1. Collect giver + turn-in **creature spawns** (map 1) of all zone quests.
2. DBSCAN them; take the **largest cluster** as Teldrassil core. This rejects the lone
   outlier **Keeper Remulos** (x≈7848, y≈−2216, in Moonglade) — the "giver" of the level-60
   Lunar Festival quest **8734 "Tyrande and Remulos"**. That quest is **kept** but flagged
   `out_of_zone` (DESIGN: never silently drop).
3. Box = bbox(core ∪ zone objective-target spawns within a generous expand margin) + a
   final margin. Core giver/turn-in cluster measured at x[9507..10758], y[441..2570].
4. Anything (turn-in / objective spawn) outside the final box → `out_of_zone` flag on the
   affected row.
5. Iterate against `out/teldrassil_spawns.png` and record the **final box** here.

Final bounding box (map 1), after plot inspection:
**x[8101 .. 11455], y[-159 .. 3170]** (giver-cluster bbox + 600 yd margin). Echoed in the
validation report (`meta.bounding_box`).

Note: the box necessarily includes **Darnassus** (top of the tree) because zone quests
"The Road to Darnassus" (487) and "Teldrassil" (940) turn in there; hence some level-55–63
city NPCs (guards, Arch Druid Fandral lvl 63) appear in `spawns`. That is correct, not
mainland bleed.

## 3. §5.2 wrinkle — Quest XP (divergence from DESIGN, verified)

DESIGN §5.2 assumed vanilla cores don't store flat quest XP and it must be derived from the
max-level money conversion. **This VMaNGOS dump stores it directly:** `quest_template.RewXP`
is populated for 3804/4727 quests. We use `RewXP` as `quests.xp` (a DB fact with provenance),
which is more accurate than re-deriving. `RewMoneyMaxLevel` is the money given *instead of*
XP at max level and is not the leveling XP.

Wowhead spot-check (www.wowhead.com/classic, XP read from the page's embedded quest data)
— all three match the DB `RewXP` exactly:
- quest **456** "The Balance of Nature": DB RewXP **170** = Wowhead `"xp":170` ✓
- quest **920** "Tenaron's Summons": DB RewXP **45** = Wowhead `"xp":45` ✓
- quest **3521** "Iverron's Antidote": DB RewXP **355** = Wowhead `"xp":355` ✓

XP-to-level table taken directly from `player_xp_for_level`; lvl 1→2 = **400**, matching the
verified anchor. Copied into `xp_levels(level, xp_to_next)` for levels 1..≈15.

## 4. §5.2 wrinkle — Quest-drop chance encoding

Confirmed mangos convention in `creature_loot_template.ChanceOrQuestChance`: negative =
quest-item drop, chance = `abs(value)` percent (2597 negative rows in the dump); positive =
normal drop %. For a COLLECT objective (`ReqItemId`), `drop_chance` is looked up as the
(abs) chance of that item on its source mob's loot table (creature or gameobject). Items
supplied by the quest itself (`ReqSourceId`) get `drop_chance = 1.0`. Items with no loot
row found → `drop_chance = NULL`, flagged in the validation report. Result on this dump:
27/42 COLLECT objectives resolve a chance; the 15 NULLs are genuine — those items are not
looted but *created by using a world object* (e.g. "Filled Crystal Phial" for the "Crown of
the Earth" chain, filled at a moonwell), so they correctly have no loot-table row. This is a
soft WARN, not a failure.

## 5. §5.2 wrinkle — Quest chains

`PrevQuestId` → `quests.prev_quest`; `ExclusiveGroup` → `quests.exclusive_group`. (These
plus `NextQuestId`/`NextQuestInChain` become router precedence edges in M3 — out of M0 scope.)

## 6. §5.2 wrinkle — Escort / event quests

`SpecialFlags` bit 0x2 (EXPLORATION_OR_EVENT) with no kill/collect objectives → objective
`kind = ESCORT` (DESIGN's fixed-duration bucket). In-zone matches: **938 "Mist"** (the
frostsaber-cub escort) and **2561 "Druid of the Claw"** (event). Event duration is a param
handled in M1, not modelled here.

## 7. Compiled `mobs` derivation

- `hp_min = classlevelstats[unit_class, level_min].health * health_multiplier`;
  `hp_max` at `level_max`.
- `armor = classlevelstats[unit_class, level_max].armor * armor_multiplier`.
- `dps_est = classlevelstats[unit_class, level_max].melee_damage * damage_multiplier /
  (base_attack_time/1000)` — **derived estimate; combat model is refined in M2 (DESIGN §8.2)**.
- `elite = rank > 0` (rank 1 elite / 2 rare-elite / 3 boss).
- `archetype`: left **NULL** for M0 — melee/caster/ranged classification for HC hazard is a
  M6 concern (DESIGN §8.2/§8.5) needing spell-list analysis; not fabricated here.

## 8. `pois`, `areas`, `items`

- `pois`: GIVER/TURNIN from the relation tables (one row per giver/turn-in spawn, coords
  from `creature`/`gameobject`); TRAINER/VENDOR from `npc_trainer`/`npc_vendor` membership
  for spawns in-box; HEARTH via `creature_template.name LIKE 'Innkeeper%'` (npc_flags does
  not carry a distinct innkeeper bit in this dump — documented heuristic).
- `areas`: DBSCAN over `spawns` per objective target entry → one row per cluster (centroid,
  radius, n_spawns, density). Each objective's `area_id` = its target's densest in-box cluster.
- `items`: for quest reward/reward-choice items of zone quests. `weapon_dps =
  (dmg_min1+dmg_max1)/2 / (delay/1000)`; `slot = inventory_type`; `stats` JSON from
  `stat_type*/stat_value*` pairs.

## 9. Patch filtering

`quest_template` deduped per `entry` to max `patch ≤ 10`. Spawns (`creature`/`gameobject`)
filtered to rows valid at 1.12: `patch_min <= 10 <= patch_max`.

## 10. Provenance

Every compiled row carries `src_table` + `src_pk` (the source PK: quest/creature/etc.
`entry` or spawn `guid`).

## 11. Tooling note — Pyright strict

`pyrightconfig.json` runs `typeCheckingMode: strict` (CLAUDE.md rule 4) but disables the
`reportUnknown*` family. Those diagnostics fire only at untyped third-party boundaries
(`numpy`/`scipy`/`matplotlib` incomplete stubs, `sqlite3` rows typed `Any`), not on our own
code. All substantive strict checks (`reportArgumentType`, `reportGeneralTypeIssues`,
`reportOptional*`, `reportUnusedImport`, …) stay ON. `make typecheck` → 0 errors.

## 12. M0-review amendment (M1 step 0a) — class / race / event gating

Added `quests.required_classes`, `required_races`, `event_id`, `event_holiday` sourced directly
from `quest_template.RequiredClasses` / `RequiredRaces` and the `game_event_quest(quest,event)`
→ `game_event(entry,holiday)` join. Bitmask semantics were **derived empirically, not from
memory**, and only two bits are actually relied on for this slice:

- **RequiredRaces bit 8 = Night Elf.** Cross-check: the only race-restricted zone quest is
  927 "The Moss-twined Heart", `RequiredRaces = 77 = 1+4+8+64` — the four Alliance races
  (Human/Dwarf/NightElf/Gnome), the mask an Alliance-wide quest carries; and the Night-Elf
  variant of the Hunter class quest "Taming the Beast" (6064/6084) carries the single bit for
  the NE starting race. Both are consistent only with NightElf = 8. So a NE hunter **can** take
  927 (bit 8 set).
- **RequiredClasses bit 4 = Hunter.** Cross-check: every "Taming the Beast" / "The Hunter's
  Path" row (the hunter class questline) has `RequiredClasses = 4`.

Findings on the 53-quest zone set (in the validation report):
- **0 class-restricted** quests. The hunter class questline is **not** in the zone set — it
  sorts under `ZoneOrSort = -261` (the Hunter QuestSort, negative = class/profession sort, not a
  zone) and is `MinLevel = 10`, i.e. out of both the zone filter and the 1→6 M1 slice.
- **0 event/holiday-gated** quests (`game_event_quest` has no intersection with the zone set).
- **1 race-restricted**: quest 927 (Alliance mask, NE included).

## 13. M0-review amendment (M1 step 0b) — NULL-drop COLLECT provider linkage

The 15 COLLECT objectives with NULL `drop_chance` (§4: items not on any loot table) are now each
linked to a provider in the new `manual_annotations` table (DB entity IDs only). Two mechanisms,
both read from the dump:

- **QUEST_PROVIDED (11 objectives):** `quest_template.SrcItemId` equals the required item, so the
  item is in the player's bags on quest accept — no acquisition work, no travel. `source='derived'`.
  Exception: 2459/obj1 "Tallonkai's Jewel" (8050) is handed over by the giver (Tallonkai Swiftroot
  3567) but is not listed in `SrcItemId` and has no loot row → `source='manual'`.
- **FILL_OBJECT (4 objectives):** the four Crown-of-the-Earth phials are *created by using a
  moonwell*. The create-item **spell** is a DB fact (`spell_template.effectItemType* = the phial`):
  5184←4976, 5639←6609, 5645←6610, 18151←22562. Four named moonwell gameobjects exist as in-box
  OBJECT spawns (GO 19549 Shadowglen / 19550 Starbreeze / 19551 Pools of Arlithrien / 19552 Oracle
  Glade). The phial→moonwell pairing is **derived from the quest text** (M1 review): vanilla
  `quest_template.Details` names the location outright — "the moonwell north of Aldrassil"
  (Shadowglen), "outside of Starbreeze Village", "on the shores of the Pools of Arlithrien", "in
  the Oracle Glade". `build.py::_moonwell_phrase` parses it and sets `source='derived-from-text'`
  with the quoted phrase; **all 4 pairings derive from text, zero manual residue.**

Invariant enforced by `validate.py`: zero NULL-drop COLLECT objectives without a
`manual_annotations` row — the sim never evaluates `count / NULL`.

## 15. M1 review amendment — located-less gathers must have a location

The 11 gameobject-gathered lootable COLLECTs (§14) whose source GO has **no map-1 static spawn**
were re-checked against `pool_gameobject`, `pool_template`, and the `game_event` tables: still no
in-zone spawn (script-placed). Because the sim must never cost a WORK step against a location-less
target, each such objective (that has an in-box giver/turn-in) now gets an `OBJECT_GATHER`
`manual_annotations` row anchored to the quest giver POI (a real DB coordinate), `source='manual'`,
noting the source GO id and the checks performed. The DSL validator rejects a `WORK … -` whose
objective has neither a DB area nor an annotation — so the reference route can never silently cost
a gather at no location.

## 14. M1 schema-gap amendment — lootable COLLECT source & area

Surfaced while hand-authoring the M1 route (DESIGN §12's intent): `areas` are keyed by objective
*target*, but a lootable COLLECT's target is an *item*, which has no spawns — so those objectives
had no area and the engine could not locate/measure the work. Fixed by deriving each lootable
COLLECT's **source entity** from the loot tables (`_drop_chance` now returns the source
creature/GO entries) and adding `objectives.source_id` / `source_kind`:

- **16/27** lootable COLLECTs resolve to a **creature** source with in-box spawns → the objective
  gets that creature's densest area (linked by `(quest_id, idx)`) and the engine kills the source
  creature for the drops (kill XP applies).
- **11/27** are **gameobject-gathered** items whose source GO has **no static spawn** in this dump
  (egg, dreamcatcher, sprouts, relics — placed by scripts/dynamically, not in `gameobject`). These
  keep `source_id = NULL, area_id = NULL`; the sim models them as located-less object gathers
  (`count/drop_chance` interactions, no kill XP). A DB limitation, not fabricated coordinates.

KILL objectives are unchanged (target creature already had an area). `validate.py` /
`test_compiled_world.py` orphan-area checks now accept an area that serves a COLLECT `source_id`.
