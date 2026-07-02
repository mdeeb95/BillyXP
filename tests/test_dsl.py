"""DSL parse/validate/serialize tests. The validator's contract (M1 brief): an unknown
quest/item/area/POI id is a HARD ERROR, not a warning.
"""

from __future__ import annotations

import pytest

from sim import dsl
from sim.dsl import Accept, DslError, Turnin, Work, parse_route, serialize, serialize_step
from sim.world import World


def test_parse_basic_and_comments() -> None:
    route = parse_route(
        "# a comment line\n"
        "ACCEPT 456   # accept balance of nature\n"
        "\n"
        "WORK 456 0 - \n"
        "TURNIN 456\n"
    )
    assert [type(s).__name__ for s in route.steps] == ["Accept", "Work", "Turnin"]
    assert route.comments[0] == "accept balance of nature"
    assert isinstance(route.steps[0], Accept) and route.steps[0].quest_id == 456


def test_unknown_quest_is_hard_error() -> None:
    w = World()
    with pytest.raises(DslError, match="unknown quest 99999999"):
        parse_route("ACCEPT 99999999", w)


def test_work_provider_area_dash_ok_but_kill_needs_area() -> None:
    w = World()
    # 921 obj 0 is a NULL-drop COLLECT with no located area (provider fill): '-' area is valid.
    parse_route("WORK 921 0 -", w)
    # 456 obj 0 is a KILL with a real area in the DB: '-' must fail (use the area).
    with pytest.raises(DslError, match="has area .* in the DB"):
        parse_route("WORK 456 0 -", w)


def test_bad_choice_item_rejected() -> None:
    w = World()
    with pytest.raises(DslError, match="not a reward choice"):
        parse_route("TURNIN 456 111111", w)


def test_serialize_roundtrip() -> None:
    text = "ACCEPT 456\nWORK 456 0 5 0.5\nTURNIN 456 12345\nTRAIN ALL\nHEARTH\n"
    route = parse_route(text)
    again = parse_route(serialize(route))
    assert serialize(route) == serialize(again)


def test_serialize_step_public_alias() -> None:
    assert serialize_step(Accept(456)) == "ACCEPT 456"
    assert serialize_step(Work(456, 0, None)) == "WORK 456 0 -"
    assert serialize_step(Turnin(456)) == "TURNIN 456"
    assert dsl.serialize_step(Turnin(456, 999)) == "TURNIN 456 999"
