"""Table-driven tests for the kill-XP formula and level-up roll-over (DESIGN §8.3).

Expected values are computed by hand from the cited formula (sim/xp.py header):
Base = CL*5+45; mob>=char -> Base*(1+0.05*(min(ML,CL+4)-CL)); mob<char -> Base*(1-(CL-ML)/ZD),
0 if ML<=gray; elite x2; floored to int.
"""

from __future__ import annotations

import pytest

from sim import xp
from sim.world import World


@pytest.mark.parametrize("cl, ml, elite, expected", [
    (1, 1, False, 50),      # equal level: 5*1+45 = 50
    (1, 2, False, 52),      # +1: 50*(1+0.05) = 52.5 -> 52
    (1, 3, False, 55),      # +2: 50*1.10 = 55
    (1, 5, False, 60),      # +4 (orange): 50*1.20 = 60
    (1, 8, False, 60),      # +7 capped at +4 (red caps at orange): 60
    (1, 1, True, 100),      # elite doubles: 50*2
    (10, 10, False, 95),    # equal: 5*10+45 = 95
    (10, 8, False, 67),     # -2, ZD=7: 95*(1-2/7)=67.857 -> 67
    (10, 5, False, 27),     # -5, gray(10)=4 so 5>gray: 95*(1-5/7)=27.14 -> 27
    (10, 4, False, 0),      # mob at gray level(10)=4 -> 0
    (6, 1, False, 0),       # gray(6)=1, mob 1<=1 -> 0
])
def test_kill_xp(cl: int, ml: int, elite: bool, expected: int) -> None:
    assert xp.kill_xp(cl, ml, elite) == expected


def test_gray_level_brackets() -> None:
    assert xp.gray_level(5) == 0        # <=5: no gray
    assert xp.gray_level(6) == 1        # 6 - 0 - 5
    assert xp.gray_level(10) == 4       # 10 - 1 - 5
    assert xp.gray_level(20) == 13      # 20 - 2 - 5


def test_zd_table() -> None:
    assert xp.zd(1) == 5 and xp.zd(7) == 5
    assert xp.zd(8) == 6 and xp.zd(10) == 7


def test_apply_xp_rollover() -> None:
    w = World()
    need = w.xp_for_level(1)             # 1->2 = 400 (verified anchor)
    assert need == 400
    lvl, into, gained = xp.apply_xp(w, 1, 0, 400)
    assert (lvl, into, gained) == (2, 0, 1)
    lvl, into, gained = xp.apply_xp(w, 1, 0, 450)
    assert (lvl, into, gained) == (2, 50, 1)
    # Multiple level-ups in one lump.
    big = w.xp_for_level(1) + w.xp_for_level(2)
    lvl, into, gained = xp.apply_xp(w, 1, 0, big)
    assert (lvl, gained) == (3, 2)


def test_rested_reduces_to_plain_when_unrested() -> None:
    base = xp.kill_xp(1, 1)
    got, consumed = xp.kill_xp_with_rested(1, 1, rested_pool=0, rested_mult=2.0)
    assert got == base and consumed == 0
