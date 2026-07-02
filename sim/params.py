"""ALL simulator tunables (CLAUDE.md rule 3). Every value carries a source comment or the
tag "initial guess, calibrate M5". No magic numbers live in model code — models import from
here. Determinism (rule 2): nothing here reads wall-clock or RNG.

Calibration protocol is DESIGN §9 (M5): play the route on a fresh NE hunter, log /played at
each turn-in, fit k_zone / downtime / EDPS a,b by least squares. Until then the EDPS and time
constants are deliberately coarse first guesses with the reasoning stated inline.
"""

from __future__ import annotations

from dataclasses import dataclass, field

# --- Travel (DESIGN §8.1) ---------------------------------------------------------------
BASE_RUN_SPEED = 7.0        # yd/s — verified anchor (CLAUDE.md); vanilla base run speed.
K_ZONE = 1.3               # path-vs-euclid detour factor. initial guess, calibrate M5 (DESIGN §8.1).

# --- Interaction times (DESIGN §9) ------------------------------------------------------
T_ACCEPT = 4.0             # s to accept a quest (gossip + accept). initial guess, calibrate M5.
T_TURNIN = 5.0             # s to turn in (gossip + reward pick). initial guess, calibrate M5.
T_LOOT = 2.5               # s per loot (open corpse + take). initial guess, calibrate M5.
T_PROVIDER = 4.0           # s to use a provider object, e.g. fill a phial at a moonwell (0b).
                           #   initial guess, calibrate M5.
T_TRAIN = 6.0             # s to train an ability at a trainer. initial guess, calibrate M5.
T_BUY = 3.0               # s per vendor purchase. initial guess, calibrate M5.
T_SETHEARTH = 4.0         # s to bind at an innkeeper. initial guess, calibrate M5.
T_HEARTH_CAST = 10.0      # s hearthstone channel. initial guess, calibrate M5 (vanilla ~10s).

# --- Combat / kill rate (DESIGN §8.2) ---------------------------------------------------
# EDPS(level) = EDPS_A[band] + EDPS_B_RANGED[band]*ranged_dps + EDPS_B_MELEE[band]*melee_dps,
# then × Π bump mults. Bands over level: 1 -> (1..4), 5 -> (5..8), 9 -> (9..12).
#
# TWO weapon terms, not one (M1 review): a hunter fights with a ranged AND a melee weapon, and a
# pre-pet low-level hunter melees a meaningful fraction of each kill (mobs close before they die),
# so b_m is NOT small — it is comparable to b_r here. With a single playthrough (M5) b_r and b_m
# will be near-colinear in the fit, so these guesses carry most of the weight for a while — tagged.
#
# Anchoring of the band 1-4 coefficients (CLASS = hunter; DB facts):
#   Ranged start = Worn Shortbow (item 2504): (2+5)/2 / 2.3 s = 1.52 ranged_dps.
#   Melee  start = Worn Dagger  (item 2092): (1+2)/2 / 1.6 s = 0.94 melee_dps.
#   Baseline abilities at L1 include Auto Shot (spell 75) and Raptor Strike rank 1 (spell 2973),
#   both from playercreateinfo_spell — folded into a/b, not separate bumps.
#   Target: TTK on an equal-level L1 mob (Young Nightsaber hp 42, armor 0 [DB]) ~12 s.
#   a=1.5, b_r=0.8, b_m=0.9 -> EDPS = 1.5 + 0.8*1.52 + 0.9*0.94 = 3.56 -> TTK = 42/3.56 = 11.8 s.
# Bands 5-8 / 9-12 scale a and both b's up modestly; equal-level mob HP grows faster than a
# white-weapon hunter's damage early, keeping TTK flat-to-rising. All numbers: initial guess, M5.
EDPS_A: dict[int, float] = {1: 1.5, 5: 2.0, 9: 2.5}        # initial guess, calibrate M5
EDPS_B_RANGED: dict[int, float] = {1: 0.8, 5: 0.9, 9: 1.0}  # initial guess, calibrate M5
EDPS_B_MELEE: dict[int, float] = {1: 0.9, 5: 1.0, 9: 1.1}   # initial guess (NOT small), calibrate M5

# Physical mitigation: EHP = hp * (1 + ARMOR_FACTOR_PER_ARMOR * armor). Low-level Teldrassil
# beasts are near-0 armor so this barely bites here; kept explicit for M2. initial guess, calibrate M5.
ARMOR_FACTOR_PER_ARMOR = 0.0001

# Level-delta penalty on EDPS: fighting up-level mobs is slower (miss/glancing/level-based).
# delta = mob_lvl - char_lvl. Piecewise-linear around 0; clamped. initial guess, calibrate M5.
DELTA_PENALTY_PER_LEVEL = 0.06   # each mob level above you cuts effective dps ~6%
DELTA_PENALTY_MIN = 0.4          # never worse than 40% effectiveness in-band
DELTA_PENALTY_MAX = 1.15         # small bonus vs lower-level mobs, capped

# Acquire + downtime (DESIGN §8.2). acquire = travel between mobs in an area given density &
# respawn floor; downtime = eat/drink/bandage overhead as a multiplicative factor on kill_cycle.
T_ACQUIRE_BASE = 3.0             # s to path to the next mob at nominal density. initial guess, calibrate M5.
DOWNTIME_FACTOR: dict[int, float] = {1: 1.10, 5: 1.15, 9: 1.20}  # per band. initial guess, calibrate M5.

# --- Reward-choice scoring (DESIGN §8.4) ------------------------------------------------
# Simple slot-aware score; weapon DPS dominates at this bracket. initial guess, calibrate M5.
REWARD_WEAPON_DPS_WEIGHT = 10.0  # weight on a reward weapon's dps in the argmax score.
REWARD_ARMOR_WEIGHT = 0.02       # weight on armor value.

# --- Rested XP (DESIGN §8.3) ------------------------------------------------------------
RESTED_MULT = 2.0                # kill XP ×2 against the rested pool. vanilla constant.
RESTED_DEFAULT_ON = False        # fresh character starts unrested.


def band_for_level(level: int) -> int:
    """Return the band key (1, 5, or 9) for a character level (DESIGN §8.2)."""
    if level >= 9:
        return 9
    if level >= 5:
        return 5
    return 1


@dataclass(frozen=True)
class Bump:
    """A trained-ability EDPS breakpoint (DESIGN §8.2). `mult` multiplies EDPS once applied via a
    TRAIN step. `bump_id` is the taught-spell name (DB fact); `learn_spell`/`taught_spell` are the
    DB spell IDs for provenance. `affects` records which EDPS term the ability conceptually
    modifies (ranged | melee | both) for the M5 fit — the flat Π-mult mechanics are unchanged for
    now. `active=False` means the bump is declared but wired to nothing (a placeholder gate).
    `mult` values are guess-tagged pending M5."""
    level: int
    bump_id: str
    mult: float
    learn_spell: int
    taught_spell: int
    affects: str          # ranged | melee | both | pet
    note: str
    active: bool = True


# Hunter breakpoint table — trainable abilities with reqlevel <= 10 from the in-box NE hunter
# trainer (Jeen'ra Nightrunner 4138 / Dorion 4205, trainer_id 20; npc_trainer_template). Spell
# IDs and names are DB facts (spell_template). Only damage-affecting abilities carry a mult > 1;
# utility/defensive abilities are listed with mult 1.0 so TRAIN ALL is representable but they do
# not inflate EDPS. **All mults are "initial guess, calibrate M5" and were shown for review
# before wiring (M1 step 1b).** Levels 8/10 sit at/after the 1->~6 slice edge.
HUNTER_BUMPS: tuple[Bump, ...] = (
    Bump(1,  "Track Beasts",         1.00, 1547, 1494,  "both",   "utility (tracking); no EDPS effect"),
    Bump(4,  "Serpent Sting",        1.10, 2003, 1978,  "ranged", "ranged DoT added to rotation; guess +10%"),
    Bump(4,  "Aspect of the Monkey", 1.00, 13164, 13163, "melee",  "defensive dodge aspect; no EDPS effect"),
    Bump(6,  "Arcane Shot",          1.12, 3048, 3044,  "ranged", "instant ranged nuke; guess +12%"),
    Bump(6,  "Hunter's Mark",        1.03, 5298, 1130,  "ranged", "+ranged AP on target; guess +3%"),
    Bump(8,  "Parry",                1.00, 3128, 3127,  "melee",  "defensive; no EDPS effect"),
    Bump(8,  "Concussive Shot",      1.00, 5117, 5116,  "ranged", "slow/utility; no EDPS effect"),
    Bump(8,  "Raptor Strike (r2)",   1.02, 14332, 14260, "melee",
         "rank-2 melee upgrade; rank 1 (spell 2973) is in the L1 baseline (playercreateinfo_spell), "
         "so this +2% is measured against that base"),
    Bump(10, "Aspect of the Hawk",   1.15, 6385, 13165, "ranged", "ranged AP/haste aspect; guess +15% (slice edge)"),
    Bump(10, "Serpent Sting (r2)",   1.03, 13556, 13549, "ranged", "DoT rank up; guess +3%"),
    Bump(10, "Track Humanoids",      1.00, 20160, 19883, "both",   "utility; no EDPS effect"),
    # Inactive placeholder: a hunter tames a pet at level 10. It is wired to NOTHING (active=False,
    # mult 1.0) so it never affects EDPS now, but it exists so M3 cannot silently simulate a
    # petless 10-11 hunter — the pet DPS term is a known M3 gap, declared here. guess-tagged.
    Bump(10, "Pet (tamed)",          1.00, 0,    0,     "pet",
         "INACTIVE placeholder; pet DPS unmodeled until M3", active=False),
)

# Map bump_id -> mult for quick lookup by the combat model (active bumps only).
BUMP_MULT: dict[str, float] = {b.bump_id: b.mult for b in HUNTER_BUMPS if b.active}

# Weapon-slot classification by item inventory_type (items.slot). Used for slot-aware reward
# scoring (a bow competes only with the ranged slot, a staff/dagger only with the melee slot).
# inventory_type values are the WoW client constants (DB-consistent; verified: Worn Shortbow=15,
# Worn Dagger=13, 2H staff=17). initial mapping, extend with a source.
RANGED_INV_TYPES = frozenset({15, 25, 26})            # bow, thrown, gun/crossbow
MELEE_INV_TYPES = frozenset({13, 17, 21, 22, 23})     # 1H, 2H, main-hand, off-hand, holdable


@dataclass(frozen=True)
class Params:
    """Bundle passed to the engine so (world, state, plan, params, seed) fully determines output
    (DESIGN §10). Defaults read the module constants above; tests/calibration can override."""
    base_run_speed: float = BASE_RUN_SPEED
    k_zone: float = K_ZONE
    t_accept: float = T_ACCEPT
    t_turnin: float = T_TURNIN
    t_loot: float = T_LOOT
    t_provider: float = T_PROVIDER
    t_train: float = T_TRAIN
    t_buy: float = T_BUY
    t_sethearth: float = T_SETHEARTH
    t_hearth_cast: float = T_HEARTH_CAST
    edps_a: dict[int, float] = field(default_factory=lambda: dict(EDPS_A))
    edps_b_ranged: dict[int, float] = field(default_factory=lambda: dict(EDPS_B_RANGED))
    edps_b_melee: dict[int, float] = field(default_factory=lambda: dict(EDPS_B_MELEE))
    armor_factor_per_armor: float = ARMOR_FACTOR_PER_ARMOR
    delta_penalty_per_level: float = DELTA_PENALTY_PER_LEVEL
    delta_penalty_min: float = DELTA_PENALTY_MIN
    delta_penalty_max: float = DELTA_PENALTY_MAX
    t_acquire_base: float = T_ACQUIRE_BASE
    downtime_factor: dict[int, float] = field(default_factory=lambda: dict(DOWNTIME_FACTOR))
    reward_weapon_dps_weight: float = REWARD_WEAPON_DPS_WEIGHT
    reward_armor_weight: float = REWARD_ARMOR_WEIGHT
    rested_mult: float = RESTED_MULT
    bump_mult: dict[str, float] = field(default_factory=lambda: dict(BUMP_MULT))
