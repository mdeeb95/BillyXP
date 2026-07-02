Ledger provenance correction + relay protocol — freeze-safe; m1-freeze unmoved.

0. Protocol, effective immediately: create specs/ at repo root. Save THIS block verbatim as
   specs/001-enroute-prereg-and-relay.md as the session's first act, then execute it.
   CLAUDE.md rule 9: every relayed instruction block is saved verbatim to specs/NNN-slug.md
   before execution; reports cite spec IDs; "confirm X landed" is answered from specs/, not
   memory. Rule 1 extension: stop-don't-reconstruct applies to specs and ledger entries — if
   referenced spec content is absent from context and specs/, STOP and request retransmission.
   Authoring ledger content at pin-time is a provenance error even when disclosed.

1. Re-attribute hypothesis #4 in place (append-only, no renumbering): retitle
   "Verification precondition — authored by session agent at pin-time absent spec; retained
   on merit: XP accounting is exact…" Graded pass/fail as verification, not direction; it is
   not a Claude model-critic hypothesis.

2. Pin as hypothesis #5, verbatim, attribution Claude, relay note "drafted pre-run, lost in
   relay, retransmitted 2026-07-02 — still pre-run, still valid":
   "En-route combat is unmodeled: sim travel legs generate time but no XP or combat. Predicted
   signature: actual level runs AHEAD of frozen checkpoints; per-segment excess XP
   (ΔXP_actual − Σ quest XP that segment) correlates with travel distance through hostile
   corridors, not with time at WORK areas. Related unmodeled XP: subzone discovery XP — check
   the dump for exploration base-XP tables (no values from memory)."

3. DESIGN §8.1/§13 + TODO M5: show me the text you authored there, then merge the original
   spec content (design notes aren't provenance-sensitive; merge freely): travel legs become
   (time, xp, hazard) generators; E[forced encounters per leg] ≈ hostile density × aggro
   swath × leg length × engage-propensity, with propensity an EXECUTOR-PROFILE param;
   marginal en-route kill cost = TTK + stop overhead (no acquisition travel), strictly
   cheaper than GRIND kills; router implication (M4): when XP-gated, prefer paths through
   level-appropriate corridors over grind-then-travel; road/off-road choice requires
   TravelModel → waypoint graph (§13 trigger); M6 tie-in: the same encounter model is the HC
   hazard source. TODO M5: fit adds engage-propensity + en-route terms; k_zone is fit on the
   movement share only, after subtracting inferred en-route combat time.

4. Capture-sheet hygiene: remove predicted_xp_into from template.csv. Capture artifacts hold
   observables only; the comparator joins predictions from the frozen timeline (already
   pinned by verify-freeze). Confirm the playsheet renders levels only, no XP predictions.

5. Append incident #3 to the freeze-integrity section: instruction block lost in chat→session
   relay; ledger entry reconstructed at pin-time; corrected same day, pre-run. Note that the
   specs/ protocol is the remediation.
