-- Compiled world schema (DESIGN §5.3). Every row carries provenance (src_table, src_pk).
-- Rebuilt from scratch by etl/build.py on every `make etl`.

PRAGMA foreign_keys = ON;

DROP TABLE IF EXISTS meta;
DROP TABLE IF EXISTS quests;
DROP TABLE IF EXISTS objectives;
DROP TABLE IF EXISTS mobs;
DROP TABLE IF EXISTS spawns;
DROP TABLE IF EXISTS areas;
DROP TABLE IF EXISTS pois;
DROP TABLE IF EXISTS items;
DROP TABLE IF EXISTS xp_levels;
DROP TABLE IF EXISTS manual_annotations;

-- Build metadata / provenance for the whole compiled DB.
CREATE TABLE meta (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

CREATE TABLE quests (
    id              INTEGER PRIMARY KEY,
    name            TEXT NOT NULL,
    min_level       INTEGER NOT NULL,
    quest_level     INTEGER NOT NULL,
    giver_kind      TEXT,               -- CREATURE | OBJECT | NULL (item/other-started)
    giver_id        INTEGER,            -- source entry of the giver
    turnin_kind     TEXT,
    turnin_id       INTEGER,
    prev_quest      INTEGER,
    exclusive_group INTEGER,
    required_classes INTEGER NOT NULL DEFAULT 0,  -- RequiredClasses bitmask (0 = any); see NOTES.md §12
    required_races   INTEGER NOT NULL DEFAULT 0,  -- RequiredRaces bitmask (0 = any); NightElf = bit 8
    event_id         INTEGER,           -- game_event.entry if event/holiday-gated, else NULL
    event_holiday    INTEGER,           -- game_event.holiday id if gated, else NULL
    xp              INTEGER NOT NULL,   -- quest_template.RewXP (see etl/NOTES.md §3)
    money           INTEGER NOT NULL,   -- copper; RewOrReqMoney when > 0
    reward_choices  TEXT,               -- JSON [{item, count}]
    zone_or_sort    INTEGER NOT NULL,
    out_of_zone     INTEGER NOT NULL DEFAULT 0,  -- giver/turn-in falls outside the box
    src_table       TEXT NOT NULL,
    src_pk          INTEGER NOT NULL
);

CREATE TABLE objectives (
    quest_id    INTEGER NOT NULL REFERENCES quests(id),
    idx         INTEGER NOT NULL,
    kind        TEXT NOT NULL,          -- KILL | COLLECT | OBJECT | EXPLORE | ESCORT
    target_id   INTEGER,                -- creature/gameobject/item entry (NULL for ESCORT/EXPLORE)
    count       INTEGER NOT NULL DEFAULT 1,
    drop_chance REAL,                   -- for COLLECT; 0..1 (NULL if no loot row found)
    source_id   INTEGER,                -- lootable COLLECT: representative source creature/GO entry
    source_kind TEXT,                   -- CREATURE | OBJECT (source of a lootable COLLECT item)
    area_id     INTEGER REFERENCES areas(id),
    out_of_zone INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (quest_id, idx)
);

CREATE TABLE mobs (
    id        INTEGER PRIMARY KEY,
    name      TEXT NOT NULL,
    lvl_min   INTEGER NOT NULL,
    lvl_max   INTEGER NOT NULL,
    hp_min    REAL,
    hp_max    REAL,
    armor     REAL,
    dps_est   REAL,                     -- derived estimate; combat refined in M2
    elite     INTEGER NOT NULL DEFAULT 0,
    archetype TEXT,                     -- NULL in M0 (HC classification is M6)
    src_table TEXT NOT NULL,
    src_pk    INTEGER NOT NULL
);

CREATE TABLE spawns (
    guid      INTEGER NOT NULL,
    kind      TEXT NOT NULL,            -- CREATURE | OBJECT
    entry     INTEGER NOT NULL,
    x         REAL NOT NULL,
    y         REAL NOT NULL,
    z         REAL NOT NULL,
    respawn_s INTEGER,
    src_table TEXT NOT NULL,
    src_pk    INTEGER NOT NULL,
    PRIMARY KEY (kind, guid)
);

CREATE TABLE areas (
    id           INTEGER PRIMARY KEY,
    target_entry INTEGER NOT NULL,      -- objective target this cluster serves
    target_kind  TEXT NOT NULL,         -- CREATURE | OBJECT
    centroid_x   REAL NOT NULL,
    centroid_y   REAL NOT NULL,
    radius       REAL NOT NULL,
    n_spawns     INTEGER NOT NULL,
    density      REAL NOT NULL
);

CREATE TABLE pois (
    id     INTEGER PRIMARY KEY,
    kind   TEXT NOT NULL,               -- GIVER | TURNIN | TRAINER | VENDOR | HEARTH | WAYPOINT
    ref_id INTEGER NOT NULL,            -- quest_id (GIVER/TURNIN) or creature entry (others)
    x      REAL NOT NULL,
    y      REAL NOT NULL
);

CREATE TABLE items (
    id         INTEGER PRIMARY KEY,
    name       TEXT NOT NULL,
    slot       INTEGER,                 -- inventory_type
    weapon_dps REAL,
    armor      INTEGER,
    stats      TEXT,                    -- JSON {stat_type: value}
    src_table  TEXT NOT NULL,
    src_pk     INTEGER NOT NULL
);

CREATE TABLE xp_levels (
    level      INTEGER PRIMARY KEY,
    xp_to_next INTEGER NOT NULL
);

-- Provider linkage for COLLECT objectives whose item has no loot-table row (drop_chance NULL):
-- the item is quest-provided (in bags on accept) or created by using a world object (moonwell
-- fill). References DB entity IDs only. `source`: 'derived' (from SrcItemId / a create-item
-- spell in the dump) or 'manual' (human-supplied linkage the dump does not encode; see NOTES §12).
-- The sim must never evaluate count / NULL; every NULL-drop COLLECT resolves through a row here.
CREATE TABLE manual_annotations (
    quest_id      INTEGER NOT NULL REFERENCES quests(id),
    obj_idx       INTEGER NOT NULL,
    provider_kind TEXT NOT NULL,        -- QUEST_PROVIDED | FILL_OBJECT
    provider_id   INTEGER,              -- QUEST_PROVIDED: giver npc entry; FILL_OBJECT: moonwell GO entry
    provider_spell INTEGER,             -- FILL_OBJECT: the create-item spell (DB fact), else NULL
    provider_x    REAL,                 -- provider world coords (for GOTO), NULL if no travel
    provider_y    REAL,
    source        TEXT NOT NULL,        -- derived | manual
    note          TEXT,
    PRIMARY KEY (quest_id, obj_idx)
);

CREATE INDEX idx_obj_quest ON objectives(quest_id);
CREATE INDEX idx_spawn_entry ON spawns(entry);
CREATE INDEX idx_poi_ref ON pois(kind, ref_id);
CREATE INDEX idx_area_target ON areas(target_entry);
