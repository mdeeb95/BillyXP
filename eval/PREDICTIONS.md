# M1 on-record prediction — Shadowglen→Dolanaar Night Elf hunter route

Frozen per the M1 review freeze protocol. **No param or model changes after this file is written until real-run timing data lands.** Regenerate with `uv run python -m eval.run_route`.

## Provenance

- git commit: `1dea5f9e288cf2de4d900aa6d639be2bbcdc9086`  **(working tree DIRTY at generation — commit to pin)**
- route file: `eval/routes/shadowglen_hunter.dsl`
- route sha256: `321e3c3547a3e545c45d6d670fd249906a9201d36f87279e2a09b9accdbb78ab`
- world DB: vmangos mangos.sqlite (commit b40576b, see data/raw/PROVENANCE.md)

## Predicted totals

- **total duration: 6,621 s = 110.3 min**
- final level: 7 (4033 xp into level)
- quests completed: 26; level-ups: 6

## Time decomposition

| bucket | seconds | % |
|---|---:|---:|
| travel | 3,567 | 53.9% |
| combat | 2,394 | 36.2% |
| interaction | 374 | 5.6% |
| downtime | 285 | 4.3% |

## Predicted level at each turn-in

| t (min) | level | xp into | quest |
|---:|---:|---:|---|
| 0.2 | 1 | 0 | 'Welcome!' |
| 1.0 | 1 | 40 | 'The Woodland Protector' |
| 7.2 | 2 | 368 | 'The Balance of Nature' |
| 15.7 | 3 | 502 | 'The Balance of Nature' |
| 23.2 | 3 | 1382 | 'The Woodland Protector' |
| 25.3 | 4 | 252 | 'A Good Friend' |
| 26.8 | 4 | 342 | 'A Friend in Need' |
| 35.7 | 4 | 1233 | "Iverron's Antidote" |
| 37.2 | 4 | 1678 | "Iverron's Antidote" |
| 47.9 | 5 | 745 | 'Webwood Venom' |
| 48.2 | 5 | 1305 | 'Webwood Egg' |
| 48.6 | 5 | 1350 | "Tenaron's Summons" |
| 50.6 | 5 | 1685 | 'Crown of the Earth' |
| 53.1 | 5 | 1910 | 'Crown of the Earth' |
| 56.5 | 5 | 2020 | 'Dolanaar Delivery' |
| 57.0 | 5 | 2425 | 'The Emerald Dreamcatcher' |
| 58.7 | 5 | 2650 | "Denalan's Earth" |
| 66.3 | 6 | 1083 | 'The Sleeping Druid' |
| 76.5 | 6 | 2264 | "Zenn's Bidding" |
| 79.9 | 6 | 2976 | 'Twisted Hatred' |
| 86.0 | 7 | 606 | 'Timberling Seeds' |
| 87.5 | 7 | 1396 | 'Timberling Sprouts' |
| 90.7 | 7 | 1666 | 'A Troubling Breeze' |
| 92.5 | 7 | 2206 | 'Gnarlpine Corruption' |
| 102.3 | 7 | 2853 | 'The Moss-twined Heart' |
| 110.2 | 7 | 4033 | 'The Road to Darnassus' |

<!-- HAND-MAINTAINED BELOW: forecasts & provenance (preserved across regen) -->

## Freeze integrity

- **sim-base commit:** `a4dc967` (the first commit that actually contains the simulator; the
  Provenance header above records `1dea5f9`, the M0 commit, which does **not** contain the sim —
  see incident note).
- **verified at:** HEAD `8c25637e0ce9a1a7f40ff0c4b59b3d59ad69e338`, on **2026-07-02**.
- **tag:** `m1-freeze` (annotated) points at the commit that adds this section.
- **reproduction result:** re-simulating the frozen route through the committed sim reproduces the
  on-record numbers **exactly** — total **6,621 s**, all **26** turn-in rows match (t within 0.05 min,
  level and xp-into-level exact, 0 mismatches), route sha256 `321e3c35…` matches. Gate:
  `uv run python -m eval.verify_freeze` (nonzero exit on any drift).

### Incident note

The M1 freeze was *declared* during the M1 review session but was **never pinned**: (a) the
Provenance header recorded commit `1dea5f9` — the M0 commit, which predates and does not contain the
sim — and flagged the working tree DIRTY at generation ("commit to pin"), and (b) no code was
committed and no tag existed. So between the freeze declaration and **2026-07-02**, the "frozen" sim
lived only in an uncommitted working tree; its integrity was covered **only** by the route sha256
and the test suite, not by a pinned commit. The exact date of the original freeze declaration is
itself not git-pinned — which is part of this incident. Discovered unpinned on 2026-07-02, verified
to reproduce, and pinned via commit `a4dc967` (sim) + the `m1-freeze` tag on the commit carrying this
section. History is left as-is (no squash/rewrite): rewriting it would erase the evidence that the
freeze was unpinned for this interval, and an integrity ledger that edits away its own failures is
worthless. The ledger records its own failures.

## Grading note

The **total** duration grades the *forecasters* (expert prior vs sim). It does **not** attribute
error to model components: a single total residual cannot split a too-high TTK anchor from a
too-high travel model — they trade off freely against one number. Only **per-segment residuals**
from the calibration run (logged `/played` at each turn-in) can assign blame to a component. Grade
totals against forecasts; grade hypotheses below against per-segment direction, not the total.

## Expert prior v1 (superseded)

Mathew's forecast, recorded blind to the sim:

- point estimate: **35 min**; 80% interval: **30–40 min**
- sim's frozen figure: **110.3 min**
- **v1 caveat — recorded immediately post-VOD** (a *different route*, *different executor*): carries
  anchoring risk from the video. Kept as data — miscalibrated forecasts are still data — but
  **superseded by v2 below** once Mathew supplies a from-own-history estimate.

## Expert prior v2 (final)

*Populate only when Mathew supplies it (VOD consciously excluded).*

- point estimate: _TBD_ min
- 80% interval: _TBD_ – _TBD_ min
- date: _TBD_
- provenance: reasoned from own execution history; VOD consciously excluded
- logging overhead included in the estimate (y/n): _TBD_

## Model-critic hypotheses (Claude)

Derived from the **frozen decomposition** (travel 53.9% / combat 36.2%), so **NOT blind** —
grade on **direction only**, against per-segment residuals, never on the total:

- **`b_r`/`b_m` identifiability:** a skilled hunter kites → ranged-dominant, so `b_m` (melee EDPS
  term) should be pinned low. One playthrough cannot separate `b_r`/`b_m` (colinear); the domain
  prior, not the regression, must set the split.
- **TTK anchor high:** ~12 s for a level-1 mob is likely too slow; real is faster.
- **Travel over-counted on short hops:** Euclidean×k charges separate area centroids as full hops
  on overlapping Shadowglen mob fields. Early Shadowglen is the worst case; Dolanaar's real
  distances should fit better.
