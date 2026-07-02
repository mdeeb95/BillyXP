"""M0 smoke tests over the compiled world.sqlite.

These assert the M0 acceptance invariants directly (DESIGN §12) so `make test` fails loudly
if a rebuild regresses the compiled DB. They require `make etl` to have run first; if the
compiled DB is absent the tests skip (CI/M0 gate runs etl -> validate -> test).
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

DB = Path(__file__).resolve().parent.parent / "data" / "compiled" / "world.sqlite"


@pytest.fixture(scope="module")
def conn() -> sqlite3.Connection:
    if not DB.exists():
        pytest.skip(f"{DB} not built; run `make etl` first")
    return sqlite3.connect(DB)


def _n(c: sqlite3.Connection, sql: str) -> int:
    r = c.execute(sql).fetchone()
    return int(r[0]) if r and r[0] is not None else 0


def test_xp_anchor_1_to_2_is_400(conn: sqlite3.Connection) -> None:
    # Verified anchor (CLAUDE.md): XP 1 -> 2 is 400.
    assert _n(conn, "SELECT xp_to_next FROM xp_levels WHERE level = 1") == 400


def test_shadowglen_quests_present(conn: sqlite3.Connection) -> None:
    assert _n(conn, "SELECT COUNT(*) FROM quests WHERE zone_or_sort = 188") >= 10


def test_quest_count_sane(conn: sqlite3.Connection) -> None:
    # Full Teldrassil set incl. Rut'theran harbor + Shadowglen; sanity upper bound.
    total = _n(conn, "SELECT COUNT(*) FROM quests")
    assert 35 <= total <= 60


def test_no_orphan_objectives(conn: sqlite3.Connection) -> None:
    assert _n(
        conn,
        "SELECT COUNT(*) FROM objectives o LEFT JOIN quests q ON q.id=o.quest_id "
        "WHERE q.id IS NULL",
    ) == 0


def test_no_orphan_areas(conn: sqlite3.Connection) -> None:
    assert _n(
        conn,
        "SELECT COUNT(*) FROM areas a WHERE a.target_entry NOT IN "
        "(SELECT DISTINCT target_id FROM objectives WHERE target_id IS NOT NULL)",
    ) == 0


def test_every_giver_and_turnin_has_poi(conn: sqlite3.Connection) -> None:
    givers_missing = _n(
        conn,
        "SELECT COUNT(*) FROM quests q WHERE q.giver_id IS NOT NULL AND NOT EXISTS "
        "(SELECT 1 FROM pois p WHERE p.kind='GIVER' AND p.ref_id=q.id)",
    )
    turnins_missing = _n(
        conn,
        "SELECT COUNT(*) FROM quests q WHERE q.turnin_id IS NOT NULL AND NOT EXISTS "
        "(SELECT 1 FROM pois p WHERE p.kind='TURNIN' AND p.ref_id=q.id)",
    )
    assert givers_missing == 0
    assert turnins_missing == 0


def test_kill_objectives_resolve_to_mobs(conn: sqlite3.Connection) -> None:
    assert _n(
        conn,
        "SELECT COUNT(*) FROM objectives WHERE kind='KILL' "
        "AND target_id NOT IN (SELECT id FROM mobs)",
    ) == 0


def test_provenance_columns_populated(conn: sqlite3.Connection) -> None:
    for table in ("quests", "mobs", "spawns", "items"):
        assert _n(conn, f"SELECT COUNT(*) FROM {table} WHERE src_table IS NULL") == 0
