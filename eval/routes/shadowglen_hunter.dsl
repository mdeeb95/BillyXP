# Shadowglen -> Dolanaar reference route — Night Elf HUNTER, levels 1 -> ~6 (M1, DESIGN §12).
# Hand-authored, chain- and level-gate-respecting. One comment per step names the quest.
# Expected level checkpoints are noted at phase boundaries; the engine's actual levels are the
# record. Area ids / provider tokens come from world.sqlite (M1 ETL). WORK <q> <obj> <area|->.
#
# STATUS: PROPOSED for hand review (M1 step 2). Not yet treated as the reference; acceptance
# numbers are not claimed until reviewed. EDPS bumps are applied at the Shadowglen hunter
# trainer Ayanna Everstride (creature 3596, world x=10458 y=828 — DB spawn coords).

# ---- Phase 1: Shadowglen entrance, starter quests (start L1) --------------------------
ACCEPT 5842            # Welcome! (Shadowglen gift voucher, quest-provided)
WORK 5842 0 -          # voucher is in bags on accept
TURNIN 5842
ACCEPT 458             # The Woodland Protector (speak to the protector)
TURNIN 458
ACCEPT 459             # The Woodland Protector — collect Nightsaber... (Grellkin moss)
ACCEPT 456             # The Balance of Nature
WORK 456 0 30          # kill Young Nightsaber
WORK 456 1 1           # kill Young Thistle Boar
TURNIN 456
ACCEPT 457             # The Balance of Nature (cont.)
WORK 457 0 32          # kill Mangy Nightsaber
WORK 457 1 6           # kill Thistle Boar
TURNIN 457
WORK 459 0 8           # collect grell moss from Grellkin
TURNIN 459

# ---- Phase 2: A Good Friend + Iverron chain, Webwood chain (expect ~L3) ---------------
ACCEPT 4495            # A Good Friend (talk)
TURNIN 4495
ACCEPT 3519            # A Friend in Need (talk)
TURNIN 3519
ACCEPT 3521            # Iverron's Antidote — collect moonpetal/venom + gather
WORK 3521 0 8          # collect from Grellkin (moonpetal lily proxy: grell source)
WORK 3521 2 7          # collect webwood venom (Webwood Spider)
WORK 3521 1 -          # gather (object-source item, unlocated)
TURNIN 3521
ACCEPT 3522            # Iverron's Antidote (deliver antidote, quest-provided)
WORK 3522 0 -
TURNIN 3522
ACCEPT 916             # Webwood Venom (min L3) — collect webwood venom
WORK 916 0 7           # Webwood Spider
TURNIN 916
ACCEPT 917             # Webwood Egg (gather)
WORK 917 0 -
TURNIN 917
ACCEPT 920             # Tenaron's Summons (talk, up the tower)
TURNIN 920

# ---- Phase 3: train, Crown of the Earth start (expect ~L4) ----------------------------
GOTO xy:10458:828      # to Ayanna Everstride, Shadowglen hunter trainer
TRAIN ALL              # apply eligible hunter EDPS bumps (Serpent Sting @4, etc.)
ACCEPT 921             # Crown of the Earth — fill phial at Shadowglen Moonwell
WORK 921 0 -           # FILL_OBJECT provider (moonwell)
TURNIN 921
ACCEPT 928             # Crown of the Earth (cont., quest-provided vessel)
WORK 928 0 -
TURNIN 928

# ---- Phase 4: south to Dolanaar, first Dolanaar tier (expect ~L4-5) -------------------
ACCEPT 2159            # Dolanaar Delivery (deliver crate to Dolanaar innkeeper)
WORK 2159 0 -
TURNIN 2159
ACCEPT 2438            # The Emerald Dreamcatcher (gather)
WORK 2438 0 -
TURNIN 2438
ACCEPT 997             # Denalan's Earth (deliver rare earth, quest-provided)
WORK 997 0 -
TURNIN 997
ACCEPT 2541            # The Sleeping Druid — collect from Nightsaber (rare drop)
WORK 2541 0 22
TURNIN 2541
ACCEPT 488             # Zenn's Bidding — collect from strider/thistle/nightsaber
WORK 488 0 36
WORK 488 1 10
WORK 488 2 16
TURNIN 488
ACCEPT 932             # Twisted Hatred — collect corrupt timberling core
WORK 932 0 33
TURNIN 932
ACCEPT 918             # Timberling Seeds — collect from Timberlings
WORK 918 0 26
TURNIN 918
ACCEPT 919             # Timberling Sprouts (gather)
WORK 919 0 -
TURNIN 919

# ---- Phase 5: Gnarlpine + Road to Darnassus tier (expect ~L5-6) -----------------------
ACCEPT 475             # A Troubling Breeze (talk / investigate)
TURNIN 475
ACCEPT 476             # Gnarlpine Corruption (talk)
TURNIN 476
ACCEPT 927             # The Moss-twined Heart (NE-allowed, rr=77) — collect
WORK 927 0 43
TURNIN 927
ACCEPT 487             # The Road to Darnassus — kill Strigid Owl / gnarlpine
WORK 487 0 40
TURNIN 487
SETHEARTH 6736         # bind at the Dolanaar innkeeper (end of the slice, ~L6)
