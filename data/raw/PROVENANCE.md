# Raw data provenance

Source lineage for the VMaNGOS world database used to build `data/compiled/world.sqlite`.
Do not build the compiled DB from a source whose lineage is not stated here (CLAUDE.md
rule 1; DESIGN §5.2 "Provenance", §13 license).

## Distribution

- **Project:** VMaNGOS — Progressive Vanilla Core (targets patch 1.12).
- **Repo:** https://github.com/vmangos/core
- **Release tag:** `db_latest` — "Development Database Snapshot (2026-06-30)"
- **Release page:** https://github.com/vmangos/core/releases/tag/db_latest
- **Source commit:** `b40576b` (branch `development`), release published `2026-06-30T19:39:46Z`.

## Asset downloaded

- **File:** `db-sqlite-b40576b.zip`
- **URL:** https://github.com/vmangos/core/releases/download/db_latest/db-sqlite-b40576b.zip
- **Download date:** 2026-07-02
- **Size:** 42,237,645 bytes
- **sha256 (zip):** `5bb7459384d15faa624987a634daf3c5305ebf7d444284101efbda591ff50789`

### Extracted contents (`data/raw/sqlite-dump/`)

`characters.sqlite`, `logon.sqlite`, `logs.sqlite`, **`mangos.sqlite`** (the world DB — the
only one used by ETL).

- **World DB:** `sqlite-dump/mangos.sqlite`
- **Size:** 145,235,968 bytes
- **sha256:** `f40d77943e72cea486d8fc6cb8de36d109f497e6c68ac3faea8293097782394f`
- **Table count:** 174 (includes all tables of interest: quest_template, creature_template,
  creature, gameobject_template, gameobject, creature_loot_template,
  gameobject_loot_template, item_template, npc_trainer, npc_vendor).

## Notes on choice of format (divergence from DESIGN §5.1, user-approved)

DESIGN §5.1/§5.3 assume a MySQL dump loaded via dockerized MariaDB. VMaNGOS ships an
**official upstream-built SQLite** copy of the same world DB (asset `db-sqlite-b40576b.zip`)
at the same commit as the MySQL dump (`db-b40576b.zip`). We read from the SQLite build
directly: it is upstream-generated (not text-parsed), removes the MySQL/Docker dependency
(Docker daemon was unavailable on the build host), and carries identical schema and data.
The ETL derivation logic (DESIGN §5.2) is format-independent. The MySQL dump + MariaDB
path remains the documented fallback if a future snapshot lacks the SQLite variant.

## Fidelity / license

- Patch 1.12; WoW Classic Era is 1.12-derived — accepted fidelity for Teldrassil
  (DESIGN §5.1, §13). Spot-check any suspicious quest against the Era client / Wowhead Classic.
- GPL-lineage (mangos). Compiled DB is for personal use in this phase; raw dumps and
  compiled outputs are gitignored and not redistributed (DESIGN §13).
