#pragma once
// econ_flags.h: economy flags and tunables.

// Bit 1: mate_waits_for_prism_capture's yield branch no longer steps a mate off a plan group whose team capture is already running
// (I stand on its region, capture_pay_in() >= 1, Prism not on it) when Prism's distance to a free spawn tile is above the rounds
// left: the region would empty and the timer reset (GameRules.md:194). The mate finishes (the capture relay hands off if she gets
// close). Runtime data flag, 0 = off. Respawn-expiry pass (FXP_TAB[1], 0 = off). Bit 1: econ::observe's respawn-expiry pass runs
// only when some group's respawn_at may have come (fxp_exp_lo, a lower bound on every GS_RESPAWN group's respawn_at, lowered at each
// of the 14 respawn_at writes in the econ code: any NEW write of GroupMem::respawn_at must call FXP_EXP_NOTE(m) after it).
#define FXP_BITS 1
inline constexpr int FXP_TAB[2] = { 0x46585031, FXP_BITS }; // observe skips the respawn-expiry pass when no group is due
#define FXP_ON(b) ((::FXP_TAB[1] & (b)) != 0)
constexpr int FXP_BIT_EXP = 1;

// A Prism with a bag under PHM_BAG stays on her own side (runtime data flag PHM_TAB[1], 0 = off, read first by every caller). Never
// touches her banking (the PC_OWNER_BANK and PRISM_GREED owner rules). Bit 1 (econ rate_for, bounds): attacker-free gem groups on
// our side of mid x PHM_OWN_X100 %; while one is free, groups on the mid line or past it x PHM_FOE_X100 %. Bit 2 (econ rate_for): a
// mate of a Prism prices those own-side groups x PHM_MATE_X100 %, leaving them to her. Bit 4 (combat fight): no walk-in step toward
// a focus standing past mid unless she can kill it; spells and in-reach hits stand, the turn goes on to farm. Bit 8 (combat assess,
// last word): FIGHT -> CALM when she stands past mid, no foe reaches her, she isn't caught and has no kill.
#define PHM_BITS 1
#define PHM_BAG 50
#define PHM_OWN_X100 200
#define PHM_FOE_X100 60
#define PHM_MATE_X100 50
inline constexpr int PHM_TAB[6] = { 0x50484D31, PHM_BITS, PHM_BAG, PHM_OWN_X100, PHM_FOE_X100, PHM_MATE_X100 }; // low-bag Prism own-side gems

// Race gate (runtime data flag RCG_TAB, read first, 0 = off). spawn_siege_commit_ok at spawn_siege_turn's RALLY and CHIP rate tests:
// crew = me + allies on our spawn that reach the group; R = their camp dps (Varg splash x min(2, pack - 1)); T = HP left / R. 1
// RACE: R >= RCG_RMIN, T <= RCG_CMAX and value > paid bodies x spawn_siege_alternative_supply x T pass the rate test. 2 FOE: also T
// + RCG_MARG < the earliest arrival of a foe seen in the last RCG_FAGE rounds (reach 5), waived for a group touching our spawn. 4
// FREE: a body on spawn below RCG_HF % HP heals anyway and chips at no cost. 8 CLASS: bits 1/2/4 only on MAPCLASS SPAWNECON maps
// (map_class() & MCL_BIT_SPAWNECON; the draft computes the bit while this bit is on). 16 NEAR: the spawn-siege reach bit 4 NEAREST
// (spawn_siege_is_safe) on SPAWNECON maps only.
#define RCG_BITS 31
#define RCG_RMIN 150
#define RCG_CMAX 800
#define RCG_HF 95
#define RCG_FAGE 30
#define RCG_MARG 0
inline constexpr int RCG_TAB[7] = { 0x52434731, RCG_BITS, RCG_RMIN, RCG_CMAX, RCG_HF, RCG_FAGE, RCG_MARG }; // race gate on MAPCLASS SPAWNECON (far spawns)
constexpr int RCG_BIT_RACE = 1;
// SPM: own-spawn monolith siege rate bar (flag read first, 0 = off). Bit 1: SS_RATE_PCT from SPM_TAB[2].
#define SPM_BITS 1
// v636 SPM: own-spawn monolith siege rate bar 6400 to 1600
#define SPM_RATE 1600
inline constexpr int SPM_TAB[3] = { 0x53504D32, SPM_BITS, SPM_RATE };

// Bit 1 (TOF, flag read first, 0 = off): the turn-order tables (the foes' last read priorities, toh_last; reach_burst_turns' table)
// are built at the start of every assess with a foe in sight, not on the first ask. Before, they kept memory that only refreshed
// when something asked, so a read-only caller (danger_veto) changed later play. Bit 1 (DWK, flag read first, 0 = off): a body with
// no dash doesn't commit to, and lets go of, DOM group D when its walk is over DWK_PCT % of the straight distance and over DWK_MIN
// tiles: D is gated for it. Normal rating then picks its target.
#define DWK_BITS 1
#define DWK_PCT 200
#define DWK_MIN 40
inline constexpr int DWK_TAB[4] = { 0x44574B31, DWK_BITS, DWK_PCT, DWK_MIN }; // walkers release a far big group commit

// Fuel cuts, one bit each (0 = no change). Runtime data flag, read first. 1 DSK (horizon_dps_k_dps): with DFX bit 1 a strength call
// takes dn = 99, so only `two` is read, and only a splash, area or dash kit reads it: others skip the scan. 2 FDN (foe_of_memo_dps):
// foe_of_calc makes a strength call only, so its memo key drops dn, and `two` on kits that don't read it: no scan, more hits. 4 NRM
// (horizon_dps_k_dps): the RawMemo hit about 6% of calls and its compare cost most of a dps_raw: call dps_raw directly. 8 AUF
// (foe_capture_pay_rounds): a body's emblem cache entry changes only at a write, so the holder test calls families() only for
// entries due a re-read. 16 TLZ (toh_build): turn ranks are worked out for the bodies asked about (my own at build, a foe or mate on
// its first query), not all of them. 32 unused. 256 TDB (reach_burst_turns): with TOH bit 4 both toh_turns calls per foe ask the
// same thing: one call. 128 AFE (changes play at the real budget): the act-first cheap action also arms at a first fuel mark left
// after econ::observe, at a lower floor on a turn armed only by that, so a fight or flee turn that would run dry bails to the cheap
// action. Inert at unlimited fuel. 64 CXL (observe): the pass over all groups for cleared-group expiry runs only when a CLEARED
// group can be due (a bound, as FXP bit 1), not every turn.
#define FUEL_CUTS_BITS 351
inline constexpr int FUEL_CUTS_TAB[2] = { 0x46583130, FUEL_CUTS_BITS };
#define FUEL_CUTS_ON(b) ((FUEL_CUTS_TAB[1] & (b)) != 0)
constexpr int FUEL_CUTS_BIT_DSK = 1, FUEL_CUTS_BIT_FDN = 2, FUEL_CUTS_BIT_NRM = 4, FUEL_CUTS_BIT_AUF = 8, FUEL_CUTS_BIT_TLZ = 16, FUEL_CUTS_BIT_CXL = 64, FUEL_CUTS_BIT_TDB = 256, FUEL_CUTS_BIT_AFE = 128;

// Runtime data flag, read first, 0 = zero work. Bit 8 LFE: target_turn's low-fuel exit did nothing for an engaged body and T.engaged
// blocks refresh_target, so with 6 foes in sight (assess leaves ~17k every turn) it stood for the rest of the game. An engaged body
// takes one cheap hit; a body still after LOW_FUEL_EXIT_LFE_N such turns runs the whole turn (a cut turn resumes). Bit 4 RTB:
// travel_recall_shop_due refuses a shop recall while the bag is >= 10 gems, bankable, non-Prism and the altar is <= CTX_BD walk and
// nearer than from home.
#define LOW_FUEL_EXIT_LFE_N 3
#define LOW_FUEL_EXIT_BITS 8
inline constexpr int LOW_FUEL_EXIT_TAB[3] = { 0x42483838, LOW_FUEL_EXIT_BITS, LOW_FUEL_EXIT_LFE_N }; // An engaged body no longer idles at low fuel.
constexpr int LOW_FUEL_EXIT_BIT_RTB = 4, LOW_FUEL_EXIT_BIT_LFE = 8;

// Own-kit rule corrections. Runtime data flag OWN_KIT_RULES_TAB[1], read first; 0 = off. bit 1 SSC: spawn_siege_my_dps /
// spawn_siege_kill_dps add the damaging stun slot (cc_mod x Focus / 8: Prism 1.5F, Tavi 1.6F, Ren 1.1F; GameRules.md :568-570, :700,
// :756) when it is cast on camps (camp_abilities_stun), i.e. not held for champions (camp_spell_hold_without_prism). bit 2 AREA: an
// area stun (Ryth slot 0, :504) or a landing stun (Heart slot 1, :826) cancels one hit of EVERY camp in its radius 1, not only the
// strongest: the crew soak adds the covered attackers past the strongest (ko1_cover_str). bit 4 HOLD: the soak drops the cc-slot
// stuns that combat camp_abilities' spell hold keeps for champions (spell_hold; Prism's spell only with a foe within her spell
// range). Marcella's armed-hit stun lands on camps: kept. bit 8 RSH: shards_of counts Ryth's Strength shards: (Str - base - 1% of
// bonus HP) / growth (:500). bit 16 MCI: crystal_step's ready-stun bar is skipped for a stun-immune body (Marcella): a stun does not
// stop her crystal. bit 32 BGC: ground area spells need no sight and pass walls; a body hit by an unseen attacker casts its ready
// area spell at the bush tile or cluster the hit most likely came from.
#define OWN_KIT_RULES_CNT(k, c) ((void)0) // fire count: the diag copy records site k when c; release: nothing, c unevaluated

                     // tiles out; gate_groups took only camps ON altar neighbours, so with no walkable altar and no adjacent gate no
                     // altar was bankable and our bodies stood by it with 126-436 gems. Now: with no walkable altar and no adjacent
                     // gate, a camp touching both the altar's enclosure and our side is a ring breach; its group is a gate, and once
                     // any breach is seen free (a camp kill leaves the group's tile empty until the whole group dies) or a tribute
                     // happens, the altar is bankable through it; 0 = off
#define RING_START 150 // the breach starts from this round, or earlier when the body carries 30+ gems
#define RING_LEAVE 0.4f // the breacher leaves below this share of its health (the camp keeps its damage) and returns at 90%

#define FREE_R 12
#define FREE_AGE 8
#define FREE_BONUS (static_cast<float>(ES_TAB[8]) / 100.0f)
#define CRYSTAL_MIN_V 20.0f // only groups worth this many gems (+ a tenth of their gold) per clear
#define CRYSTAL_NEAR 8 // a trip starts only within this walk of our spawn

// Bit 1: threat_seen's "new flee episode" test uses TS_BL (so at ES_TSBL=10 a re-flee 11-15 rounds later starts a new loot episode).
// Bit 2 (overrides bit 1): a new episode = the last run's blacklist (thr_until, incl. drop_target(20) on the target) has expired.
// Free-crew counting (RCM_TAB, flag read first). Bit 1: a visible unclaimed mate within 8 counts as free crew once I have seen it in
// a recall RCM_K rounds running (its recall ends within ~5 - RCM_K rounds; a self-spinning recall, cancelled each turn, is free
// already). Before, three bodies leaving recalls one at a time each rated the home elk group solo, because free_near() drops
// channelling mates.
#define RCM_BITS 1
#define RCM_K 3
inline constexpr int RCM_TAB[3] = { 0x52434D31, RCM_BITS, RCM_K }; // free_near() excluded channelling mates

// Crew numbers for an unseen mate (flag read first). UPG bit 2: from its last-seen Strength/Focus/max HP (age switch 1: grown by the
// growth model's ratio since then; 0: as seen), not base x growth_factor(). GRW bit 1 MODEL: from my own last sighting of it (stats,
// HP, gold), not the kit-agnostic growth ratio: Strength/Focus/max HP grow by the kit's own shard rate (GRW_SR, shards a round; x
// kit growth; x0.5 = mean-unbiased; age capped at GRW_CAP); a mate seen dead since then respawned and shopped: + (0.967 x gold/30 +
// 0.0213 x age) shards split by the kit's build mix (GRW_MIX), HP 0.9 of max; else HP heals from the last-seen share toward full: 1
// - (1 - f) x 30 / (30 + age).
#define GRW_BITS 1
#define GRW_CAP 80
inline constexpr int GRW_TAB[3] = { 0x47525731, GRW_BITS, GRW_CAP }; // slot 0 magic keeps it out of .bss
constexpr int GRW_BIT_MODEL = 1;

#define FIN_US 850 // finish mode once our tributed gems reach this
#define FIN_THEM 900 // or once theirs reach this
#define FIN_TIME 40 // or once the rounds left are within my walk + channel + this
#define FIN_BAG 10 // smallest bag banked in finish mode (capped at my share of the gems still missing)

// Combat passives (Heart of Ruin, Ren, Varg, Ryth).
#define PASSIVE_FINISH_KEEP 0.10f // health share (of max) a finished clear must leave (also >= two rounds of hits)

#define EB_WIN_D 10 // walk tiles (bank field) to the nearest tribute tile for the end-bank rule; int
// b1761 PKW (owner: per-kit gold worth; refined: "make sure we still capture camps ... other members in vision can steal"): runtime data
// flag, 0 = off. Target choice is untouched (a camp keeps today's value for whoever works it). The per-kit gold weight K (x100, by
// champion_type: ryth, vesper, vendetta, cassi, issac, stellar, prism, marcella, willow, ren, varg, tavi, heart) only decides WHO HOLDS a
// capture with gold. Bit 1 (variant B): cap_rank gets (K - 100) x min(gold, 300) x PKW_SCALE / 1000 off (a higher-K body ranks first) among
// the candidates should_capture already counts (in the region and claiming the group). Bit 2 (variant A): an ally in the region with a
// higher K than mine counts as a candidate without claiming it. All K at 100 = no change.
#define PKW_BITS 1
#define PKW_SCALE 30
#define PKW_RYTH 100
#define PKW_VESPER 110
#define PKW_VENDETTA 125
#define PKW_CASSI 80
#define PKW_ISSAC 80
#define PKW_STELLAR 75
#define PKW_PRISM 60
#define PKW_MARCELLA 90
#define PKW_WILLOW 60
#define PKW_REN 100
#define PKW_VARG 120
#define PKW_TAVI 115
#define PKW_HEART 85
#define PKW_PRISM_HS 0     // Prism: from this many Health shards (0 = never) her K is PKW_PRISM_AFTER
// v686 PKW: PKW per-kit gold capture weight, reopen v685
#define PKW_PRISM_AFTER 100
inline constexpr int PKW_TAB[18] = { 0x504B5731, PKW_BITS, PKW_SCALE, PKW_RYTH, PKW_VESPER, PKW_VENDETTA, PKW_CASSI, PKW_ISSAC, PKW_STELLAR, PKW_PRISM, PKW_MARCELLA, PKW_WILLOW, PKW_REN, PKW_VARG, PKW_TAVI, PKW_HEART, PKW_PRISM_HS, PKW_PRISM_AFTER }; // slot 0 magic keeps it out of .bss
// b1761 CMT (spec_cmt_1109, Mite 01a1be8b-414c-7a78 r983): runtime data flag, 0 = off. The bank decisions read my bank-field distance
// through bank_dist_here() (a camp spawn tile, blocked in the field, reads its best neighbour + 1) instead of the raw field at my tile.
// Bit 1: the recall-hop test (bank_trip_instead). Bit 2: the walled-in recall, the recall-bank route and the Prism safe-altar choice.
// v653 CMT: recall-hop bank test uses walk distance

// A group's approach tiles come from its first two members only (step_groups), so a group listed centre-first has an empty approach
// and d_altar / xt_sp read UNREACH (rate_for then prices the altar walk at 30). bit 1: play only (not the draft's M.init),
// step_distances sets d_altar = 1 + min f_altar over every member's 8 in-bounds neighbours outside block_camps; the approach vector
// and draft memory are untouched. bit 2: step_approach refills an EMPTY approach from every member's neighbours (not block, not a
// camp tile), at most 16; moves xt_sp, the planner and the draft's distances. bit 4: bit 1 only for groups whose approach read is
// UNREACH (empty or dead-end approach); others keep the old value. Runtime data flag, read first; 0 = off.
#define WB2_LATE 60 // the score-lead win test only in the last 60 rounds
#define WB2_SAFE_PCT 80 // foes' + camps' damage over walk + channel below 80% of HP + shield
#define WB2_BAG 100 // bags up to 100 gems (a channel of <= 10 turns); bigger bags (Prism hoards) keep the end-bank and Prism rules

// Fuel on wolf maps (many visible neutral camps): less work for the same results. 1: camp_threat answers from a per-turn list of the
// awake attackers (body distances on first need, a near-me prefilter, a per-tile memo), update_awake_mem uses an index (it was
// quadratic in awake camps), camp_threats_near and AvoidCampReach read the same list, and visible_camp reads W.camp_slot. Debug builds
// compare each with the plain code on the same state (FWCHK lines every 20 rounds; costs fuel, never in a live build). Bounds (fuel
// of the target choice on maps with many camp groups or long lanes): group_bounds and compute_travel give bit-identical bounds in
// the same order and the same travel for less work. BOUNDS_MIN_GROUPS: the BOUNDS paths run on maps with at least this many camp
// groups; smaller maps keep the plain code. 0 = every map.
#define BOUNDS_MIN_GROUPS 28

// COVER: a body with nothing to farm does not stand in the field. COVER_IDLE_HP: health share below which an idle body goes home
#define COVER_IDLE_HP 0.9f // health share below which an idle body goes home

#define TERR_OWN 0.50f // our territory (contest; 0.5 = the middle)
#define TERR_FIN 0.5f // bonus per share of a group's health already gone; 0 = off
#define TERR_HOLD 12 // extra rounds a capture in our territory is held; 0 = off
#define TERR_IDLE 12 // idle wait preference (tiles) for a chipped group in our territory; 0 = off

// Opening crews on compact contact maps: a compactness weight k in [0, 1] from map features only, computed once from draft memory:
// the mean of clip01((40 - n)/25), n = the gem-weighted walk from our spawn to the walkable gem groups with contest <= 0.55, and
// clip01((60 - s2s)/40), s2s = the spawn-to-spawn walk. The mode has full strength until round CREW_R/2 and fades out linearly by
// round CREW_R.
#define CREW_R 300 // the opening mode is gone by this round

// v683 JGW (b1788, jgw_rulecheck_1110 + end-game audit): late/respawn targeting fixes. Runtime data flag JGW_TAB[1], read first.
// Bit 1 JGW1: join_gain's arrive branch counts the respawn wait (the crew starts at respawn_at, GR:196). Bit 2 PEG1: the lone-v-pair
// trip repeats the round-2000 end test (gold only when it fails, INT:118). Bit 4 EGA: the end test and its bound run on bankable()
// maps, not only any_altar. Bit 8 ANYA: siege and spawn-siege late tests on bankable(). Bit 16 ETW1: the bank while a group respawns
// must finish its tribute by round 2000.
// v685 JGW: 19 fixes phy1r2,npb1,orc1,wvc,cia3s,jgw31,x02,idm +11
#define JGW_BITS 31
inline constexpr int JGW_TAB[2] = { 0x4A475731, JGW_BITS }; // slot 0 magic keeps it out of .bss

// Target-choice caps. Runtime data flag (0 = off; flag read first), one bit per idea. Bit 1: crew_bonus capped at TCA_CBCAP/100, so
// a pair on a gem camp keeps part of the second body's price (its readers, join gate and bound, see the capped value). Bit 2:
// group_value's gold x TCA_GOLD/100. Bit 4: the 61+ contest cell capped at the 31-60 cell of the same walk and size.
// STRIPPED (FL6): no reader of TCA_TAB in this tree; deadstrip.py find TCA before arming.
#define CREW_GUARD (static_cast<float>(B467_CREWG_X100) / 100.0f) // Half guard: a lone, unclaimed trip to a contested group (contest above 0.45, ramped 0.40-0.50) with no

                        // ally's claim or position within 8 tiles of it: rate x (1 - CREW_GUARD k)
#define CREW_PAIR 0.5f // On a gem camp with attackers on our side or in the centre (crew_group_k), a crew of 2+

                       // (a pair the chooser drafts, or joining a lone claimant) is worth 1/(1 - CREW_PAIR k) its per-body rate:
                       // pairs outrank solo trips that pay up to that much more
#define CREW_RESV (static_cast<float>(CAL_TAB[9]) / 100.0f) // crews of 2+ on such camps may spend (1 + CREW_RESV k) of their camp HP budget

                  // allowed (solo-rule exemption), a crew of 2+ is worth (1 + GN_PAIR need) per body, a lone unclaimed trip with no
                  // ally near must draft or recruit a second body (as sieges recruit) or is not taken
#define GN_MARGIN 8
#define GN_SAFE 0.25f
#define GN_LEAD 100.0f
#define GN_CREW_MIN 0.5f
#define GN_PAIR 0.5f

                  // (0: race = 1 while level or behind, 0 at a lead of GN_LEAD)
#define GN_PACE 0.2f
#define GN_LAG 60.0f

// Opening choice: an elk group on our side (contest < OE_CMAX) is a crew target with a floor of opening_elk_crew_floor() bodies
// (free bodies drafted by the opening simulation), joiners welcome below the floor, OE_BONUS per body; one such group at a time.
// After the opening the crew keeps its claims; no recruits. rate_for's x1.3 for my groups near a recent kill (kill_round < 20) is
// also in group_bounds' bound (group_bounds and group_bounds_finish), so rate <= bound holds. 0 = no x1.3 in the bound.
#define LOOP_FIX 12 // A support body with no safe tile in range escapes out of the camps' reach.

                       // main-stat emblems are Bruiser (5 main + 1 Health + 1 of the third stat = 7 units) instead of Power (6
                       // main); the Health emblems stay Power (6 Health); 0 = Power only. Greed for the passive-free tail. One Greed
                       // emblem (25 shards, 750 gold) = 40 stat units v 5 Power emblems = 30 (Bruiser x5 = 25 of its stat + 5 + 5 of
                       // the others). make_build's last step (greed_tail_pass; not healers, Prism or Tavi): every 5 tail entries of one
                       // family and stat (bit 1 Power; bit 2 Bruiser main stat; bit 4 Bruiser Health; the first Bruiser entry of
                       // each stat is the passive section's and stays) become one Greed entry of that stat at the first one's slot.
                       // shop buys it in 5-shard steps; next_emblem_cost keeps the 150 cadence. Gate (greed_gate, dynamic): when a
                       // Greed entry is next with no loose Greed shard of its stat, gold in hand + GRT_PCT % x my gold rate
                       // (emb_gold / round) x the race rounds left (emblem_rank's estimate) must reach 750, else that entry turns back
                       // into its 5 entries. Runtime data flag GRT_TAB[1], read first; 0 = off.
#define GRT_BITS 1
#define GRT_PCT 100
inline constexpr int GRT_TAB[3] = { 0x47525431, GRT_BITS, GRT_PCT };

// Runtime data flag, read first; 0 = a healer always takes Focus. Bit 1: make_build chooses a healer's main stat by the same value
// test as every other kit. Inert unless Willow is drafted.

// Runtime data flag, read first; 0 = off. Bit 1 walk filler: on the approach to a respawning target with left - walk >= FRL_MIN, try
// filler_target every 2 turns. Bit 2: capture_region_handoff hands off after 1 own turn of overlap. Bit 4: a solo chip filler during
// a respawn wait (quiet own-side live group within FRL_WR walk, share >= 25% of what is left in the budget). Bit 8: rate_for's
// chip-return branch also for a crew group already damaged to <= FRL_CRW % HP. Bit 16: the wait filler from left >= FRL_MIN. Bit 32
// near-leave: a capturer walking to a region a better-ranked mate holds moves on. Bit 64: bit 1's walk filler must end by the
// respawn (budget left - WAIT_FILL_SLACK).
#define FRL_BITS 54
#define FRL_MIN 5
#define FRL_WR 8
#define FRL_CRW 70
#define FRL_CHIP 100 // bit 4: the least solo share (%) of what is left a chip must take (100: the whole clear fits)
inline constexpr int FRL_TAB[6] = { 0x46524C31, FRL_BITS, FRL_MIN, FRL_WR, FRL_CRW, FRL_CHIP };

                   // travel recall within RT_GAP rounds of the last recall; 2 = also the walk from spawn from the group field; 0 =
                   // off
#define RT_GAP 12

                      // While one of theirs is down for KW_AHEAD or more rounds, a healthy body (50%+ HP) rates a mid group (contest
                      // 0.4-0.6) it can capture before the first of them is back x the bonus factor, without the enemy-seen
                      // discount; 0 = off
#define KW_AHEAD 15

                    // a lone trip (no claimant mate, no ally near) to a group past 0.6 of the walk to their spawn is rated x PD_PEN
                    // unless 2+ of theirs are down; 0 = off
#define PD_PEN (static_cast<float>(B467_PDPEN_X100) / 100.0f)

                     // Spawn tiles that an awake camp group's reach covers (an elk group's reach is 4) are hit every round and
                     // healed at turn end, so the 97% heal-wait never ended and the hits kept the group awake: the heal-wait skips a
                     // tile an awake camp reaches, and the turn's idle escape steps out of reach.
#define FR_TURNS 4
#define FR_BLOCK 40
#define FR_NEAR 12

// Focus hold (runtime data flag FKH_TAB[1], read first; 0 = off). pick_focus scores only the camps in sight, so a walk around a wall
// can lose its focus at one tile and find it at the next, and the two goals point at each other (a body flipping A-B-A, with
// FOCUS_REACH reset on each flip). Bit 1 HOLD: a focus I walked toward last turn stays the focus while it is out of sight and alive,
// I am not in its range yet, and the camp picked in its place can't be hit from here, for up to FKH_ROUNDS rounds since I last saw
// it. A non-attacker never holds against an attacker.
#define FKH_BITS 1
#define FKH_ROUNDS 12
inline constexpr int FKH_TAB[3] = { 0x464B4831, FKH_BITS, FKH_ROUNDS }; // slot 0 magic keeps it out of .bss
constexpr int FKH_BIT_HOLD = 1;
#define RECALL_TRAVEL 8 // the travel recall's margin RECALL_TRAVEL (rounds); a trip that ends in a recall

                  // drops to RTS_MARGIN while a shop or heal is due (gold >= RTS_GOLD and shopping allowed, or HP < RTS_HP100 %), so
                  // the recall that shops/heals anyway replaces the walk when it is no slower; also needs no enemy within RTS_FOE; 0
                  // = off
#define RTS_GOLD 90
#define RTS_HP100 80
#define RTS_MARGIN 0
#define RTS_FOE 10

                      // Recall walk cost (RTM_MODE, RTM_MARGIN): 0 = the recall only speeds up the trip to a target chosen by
                      // walking cost.
#define OE_CMAX 0.45f
#define OE_K 3
#define OE_BONUS 1.6f
#define OE_WAIT 20 // rendezvous wait at an own-side elk group with a claimant coming (12 elsewhere)

// A capture-timed recall (started during the capture wait, so it costs no time on the spot, only the walk back out) also goes home
// to shop once one shard per SHOPCR_TRIP tiles of walk home (at least SHOPCR_SHARDS) is affordable. Held middle: the low-gold rule
// only for groups on our side (contest <= SHOPCR_BAND) with no enemy close to me in the last SHOPCR_SAFE rounds, on maps less
// compact than SHOPCR_K; everything else keeps the full-emblem rule. No extra trips: want_shop / shop_recall are unchanged.
// SHOPCR_SHARDS: shards' worth of gold (30 each) that pays for a capture-timed shop recall
#define SHOPCR_SHARDS 1 // shards' worth of gold (30 each) that pays for a capture-timed shop recall
#define SHOPCR_TRIP 10 // > 0: one more shard per SHOPCR_TRIP tiles of walk home (the walk back out); 0: flat
#define SHOPCR_BAND 0.40f // the low-gold rule only for groups on our side (contest <= this; middle 0.40-0.60)
#define SHOPCR_SAFE 30 // and only with no enemy close to me in the last SHOPCR_SAFE rounds (0: no test)
#define SHOPCR_K 0.6f // and only on maps less compact than this (the crew's static crew_k, from map features)

                      // The shop rule's map limit above exists because on compact contact maps our side is contact ground too, and a
                      // body away loses the pack fights. Capture-recall detour: we go home when the next farm is nearer the capture
                      // than the spawn. Runtime data flag CRD_TAB (0 = off; flag read first): [1] bits: 1 skip a shop-only capture
                      // recall when the best candidate group is >= [2] walk turns nearer from here than from spawn (same group field
                      // for both); 2 respawning groups count with their timers (else only alive/unknown ones). [2] CRD_M margin
                      // (walk turns). [3] CRD_GMAX: gold_after at or above this always shops.
#define CRD_BITS 3
#define CRD_M 12
#define CRD_GMAX 240
inline constexpr int CRD_TAB[4] = { 0x43524431, CRD_BITS, CRD_M, CRD_GMAX }; // skip a shop-only capture recall when the next farm is nearer

// The tribute start loops (bank, bank step) skip an enemy-locked altar only via altar_lock_at().is_enemy(), which returns OUR lock
// when both teams hold one, so the both-locked tile was not skipped and the submit became lock hits while another unlocked altar in
// range sat open. Runtime data flag LKB_TAB[1] (0 = off): bit 1 also skips an altar whose enemy lock enemy_altar_lock_direct reads directly,
// so the loop goes on to the next altar (lock_hit still breaks it).
#define IR_WAIT 5
#define IR_FUEL_MIN 60000 // fuel left in the turn before each group the idle branch rates
#define IR_RMAX 1 // the idle branch tries at most this many recruits
#define IR_K 3
#define MB_FUEL 70000

// Opening simulation drop: a pending opening simulation is dropped and the body takes the ordinary per-body choice (otherwise bodies
// with no target stood on a large contact map). Runtime data flag OPX_TAB (0 = off; flag read first, no work at 0). Bit 1: from
// round OPX_ROUND. Bit 2: while a foe is seen within 8.
#define OPX_BITS 3
#define OPX_ROUND 10
inline constexpr int OPX_TAB[3] = { 0x4F505831, OPX_BITS, OPX_ROUND };

                  // Heavy camp groups worth a capture of at least the minimum crew gems that the best camp tank cannot clear alone
                  // at base stats are called by the same gate (stat ratio SG_CREW_SR); they stay normal targets too, and the call
                  // goes out in the event slot (type SG_CALL_EV); 0 = bosses only. Runtime data flag SGC_TAB[1], read first; 0 =
                  // off. Bit 1: no heavy-group crew operations (SG3 bosses stay).
#define SG_CREW_SR 1.1f // team stat ratio for a crew-group call (the boss gate's SG_SR by default)
#define SG_CREW_RATE (static_cast<float>(ES_TAB[15]) / 100.0f) // the crew's value per body-round must be at least this share of my current target's rate
#define SG_CALL_EV 5 // event-slot type of a crew call (subject = group)
#define SG_HPMIN 9000.0f // big groups have this much health or more (a lone golem with clusters, 6,440 HP, stays a 1-2 body target)
#define SG_MARGIN (static_cast<float>(CAL_TAB[8]) / 100.0f) // the start: the present crew's estimated camp damage must fit this share of its camp budget

                        // Measured for the start margin: starts at 0.86-0.97 x budget failed 5 of 7 uncontested; at <= 0.76, 8 of 10
                        // captured within 60 rounds.
#define SG_MARGIN_CALL (static_cast<float>(ES_TAB[14]) / 100.0f) // the call, from the free crew's stats (the crew arrives hurt and tanks bail at ~55% HP)

                            // Under a range-5 boss, calls at estimated damage <= 0.6 x budget finished 5 of 6 uncontested starts.
#define SG_MEMO 30 // a slot's last big claim counts this long while its claim byte is released (banking, recalls, death)
#define SG_COLLAPSE 15 // rounds after my call or join before fewer than SG_K committed bodies end the operation
#define SG_CONTEST_WAIT 8 // while gathering, a contest lasting this many rounds ends the operation (it never starts into one)
#define SG_RECALL_GAP 25 // after an operation of mine failed, no call of my own for this many rounds

// Early deaths to camps: crews on packs fall apart one bail at a time (bodies arrive 2-9 rounds apart and the first takes every
// attacker's hits; tank_turn's bail fires at 75-94% HP), mates re-enter alone hurt, holders have no bail, and after a bail or a drop
// nothing walks the body out of the reach first. Rules: a capture that pays before the hits kill it holds; a body left to walk out
// of the reach is benched (a healthy mate holds) or drops the group, and escapes on live health; a number of consecutive turns at
// camp damage above a set percent of the budget (and not finishing within 3 rounds) drops the group for every member.
#define CF_REENTRY_HP 70

// Opening and gather tuning (runtime data flags, read first; 0 = off). Slot 1 of the opening race table: bit 1 RACE: in the opening
// simulation a solo-feasible walkable gem group in the contested band is worth more, scaled by how much earlier we arrive than the
// foe walks: a group the foe reaches first is lost to us and gained by them, while an own-side group the foe cannot reach soon keeps
// its value. bit 2 SOLO_GO: the rally gather ends when the crew already here can clear the group (estimate feasible), re-checked
// every turn. bit 4: the gather ends when the nearest away claimant is at least 2 rounds out and the camp damage until it arrives
// costs no more than a set percent of the present crew's camp budget. bit 8: the gather ends when the present crew is feasible and
// no away mate can arrive within a set number of rounds. Slot 1 of the opening step table, bit 1: start_step_i / opening_prestep
// steps chosen on the Chebyshev fallback (no group field, no stored route) never lower my walk distance from home (M.f_home);
// otherwise a body can step back into the spawn pocket on a fuel-skip start step, then out again.
#define CF_RALLY_WAIT 15 // rounds a gathered part of the crew waits for the rest before it starts without them
#define TT_EV(...) ((void)0) // decision-trace events are no-ops in this build

#define SC_CRY_MIN 8 // rounds a crystal route must save over the walk
#define SC_LAND_CAP 256 // landing tiles kept (the largest saving to the tile itself first)

#define CR_CONTEST_X100 40 // own side only (contest x 100)
#define CR_QUIET 25 // rounds with no enemy champion known near the group
#define CR_ENEMY_R 10 // ... within this many tiles of its anchor
#define CR_MIN_PCT 30 // share (%) of the remaining health a trip must take off
#define DES_STALE 60
#define MP_ALTARS 5
#define MP_SEEN_X100 (static_cast<int>(ES_TAB[5]))
#define MP_LO 35
#define MP_HI 65

// estimate() corrections for heavy groups (an elk, golem or monolith, >= 30 gems). Bit 1: hit size: Member::budget_he counts
// Durability (0.9) on top of Jungle (0.7) for me, and allies at my reduction when their growth (maxHP / kit HP) is at least 90% of
// mine (measured hits on our bodies: 0.63x in ~50%, 0 in ~20%, full in 16-18%). Bit 2: trips: camps never regenerate and sleep 2
// rounds after nobody is in reach, so a quiet own-side group (low contest, no enemy seen at it for a set number of rounds, not
// within reach + 3 of our spawn) may be cleared over up to HE_TRIPS trips (budget x trips; each extra trip adds a recall + the walk
// back to e.t). Bit 4: a tank bail off such a target sets no blacklist. Slot 1 = mode bits, slot 2 = trips. Every new path reads the
// table after its cheap test.
#define HEAVY_EST 2
#define HE_TRIPS 3
inline constexpr int HE_TAB[3] = { 0x48455354, HEAVY_EST, HE_TRIPS }; // multi-trip heavy clears
#define HE_CONT_X100 55
#define HE_QUIET 25

// Camps hit through walls and into bushes, vision does not. tank_turn and camp_holder_bail summed only attackers in sight, so a tank
// next to an elk she could see, with a second elk behind a wall, read "winning" at half the real damage and died a step short of
// out. Bit 1: unseen attackers (hidden_camp_threats) in reach of my tile, of a visibly awake group, that the nearest-body rule says
// hit me, join the two bail tests' incoming and threat lists (next-round precision 37%). Bit 2: the same list only after direct
// evidence: last round I lost at least that camp's hit more than camp_threat predicted at my last turn's end, no foe near, held
// CBL_HOLD rounds (precision 51-64%). Runtime data flag CBL_TAB[1] (0 = off). Bit 4: no work at turn end. The damage check runs only
// on a turn that lost HP with no foe within 8 and an attacking camp in reach out of my sight; it prices camp_threat then. Bit 8
// (with 4): the check runs only on a body engaged on camps below 80% HP.
#define CBL_BITS 14
#define CBL_HOLD 3
inline constexpr int CBL_TAB[3] = { 0x43424C31, CBL_BITS, CBL_HOLD };

// The non-Prism loop as one switch: bag and missing HP are debts cleared often. Prism's rules are untouched (LTB_LIGHT is false for
// her). Bit 1 BAR: want_bank's bag bar = clamp(LTB_BANKB + LTB_BANKS_X100/100 x d, LTB_BANKB, LTB_BANKMAX); the wait-bank takes the
// same base. Bit 16 DETOUR: d in that bar becomes half the altar detour from my walk to my target (only lowers it). Bit 2 HEAL:
// wants_heal and capture_recall's heal line + LTB_HEAL_UP points. Bit 64 PASS: within LTB_PASS tiles of home the heal line is 90%.
// Bit 4 SHOP: no RD_SHOP bar for a light body. Bit 32 SHOPX: want_shop's non-eager spare gold LTB_SHOP_EXTRA. Runtime data flags (0
// = off). Bit 128: the bit 1 bar is min(live bar, new bar). Bits 2, 4, 32, 64 are off. The bank bar means a small bag is banked only
// where the altar is a short detour.
#define LTB_BITS 145
#define LTB_BANKB 6
#define LTB_BANKS_X100 300
#define LTB_BANKMAX 70
#define LTB_HEAL_UP 12
#define LTB_SHOP_EXTRA 60
#define LTB_PASS 8
inline constexpr int LTB_TAB[8] = { 0x4C423832, LTB_BITS, LTB_BANKB, LTB_BANKS_X100, LTB_BANKMAX, LTB_HEAL_UP, LTB_SHOP_EXTRA, LTB_PASS }; // non-Prism carriers bank a small bag
#define LTB_LIGHT(b) ((LTB_TAB[1] & (b)) != 0 && W.me.kit && !W.me.kit->gem_focus)

// Dynamic bank bar: a non-Prism carrier banks iff P(lose the bag before its next natural bank) x bag x 2 > trip x own farm rate. P =
// logistic(B0 + BQ ln(1+quiet) + BD x foe-spawn walk share + BH x HP share) / 1000, fitted on local games; quiet = rounds since
// intel::latest_sighting. trip = 2 x half_altar_detour + 1. bar = trip x rate / (2P), clamped. Bit 1: the bar replaces want_bank's non-Prism
// bag bar; bit 2: it only lowers it; bit 4: it only raises it. 0 = off.
#define DBK_BITS 12
#define DBK_B0 -622
#define DBK_BQ -243
#define DBK_BD -182
#define DBK_BH -1593
#define DBK_RATE_X100 50 // floor of the own farm rate (V x100 / round)
#define DBK_TMIN 6
#define DBK_TMAX 120
#define DBK_QCAP 300

// Bit 8: per-game online intercept from this game's evidence, deciding on the hazard's upper bound: z += DBK_UB + DBK_E1 [a foe seen
// in our half this game] + DBK_E2 [an unseen hit on me this game] + DBK_E3 x min(2, my bags of 10+ lost this game) (all x1000). Bits
// 4 + 8 = 12 are on.
#define DBK_UB 400
#define DBK_E1 300
#define DBK_E2 300
#define DBK_E3 1000

// Bank-bar clamp (second table slot, 0 = off): the dynamic bar's quiet raise (bit 4) was clamped at DBK_TMAX 120, over the
// 97-106-gem bags the base bar had already accepted, so carriers held them through a respawn wait. Bit 1: the raise is capped at a
// set percent of the bar before the raise (never below that bar). Bank distance (own table, 0 = off): want_bank priced a dasher's
// bag at the walk to the altar although bank() takes the hole-dash shortcut (hole_shortcut_turn on the altar slot) when it beats the
// walk, so a Heart 5 dash-turns from the altar was priced at a 36-step walk and never banked. Bit 1 (non-Prism, hole-dash bank walks
// on): the bar's distance is the shortcut's route when hole_shortcut_turn would take it (route + HOLE_SHORT_GAIN <= walk, no foe
// within 10), and a long detouring walk asks for the altar slot's field (hsb_req_r, built in background fuel as bank() asks).
inline constexpr int DBK_TAB[14] = { 0x44424B31, DBK_BITS, DBK_B0, DBK_BQ, DBK_BD, DBK_BH, DBK_RATE_X100, DBK_TMIN, DBK_TMAX, DBK_QCAP, DBK_UB, DBK_E1, DBK_E2, DBK_E3 };

// ---------------------------------------------------------------- walk to the twin altar when the near one is locked
// (econ_bank_walk). Locks are per altar (GameRules :236-244). Without it a carrier hits the lock of one altar from 3 tiles for
// several turns while a twin altar 2 steps away stands free. Flag ALT_TWIN_BITS, 0 = off. Bit 1 TWIN: in bank_i, where lock_hit would
// hit an enemy lock in my attack range, a carrier first walks toward another visible altar within ALT_TWIN_R (Chebyshev; its side tiles
// 2-3 steps away) that the engine reads with no enemy lock, and banks there. Bit 2 WALK: before the bank walk (bank_field leads to
// the nearest altar, locks unread), when the nearest altar has a seen enemy lock and another seen free altar is within its distance
// + ALT_TWIN_D, the carrier walks to the free one. Both cases are two altar entities (g.altars). Hooks: econ_*.cc bank_i before lock_hit
// (TWIN) and before the bank_field step (WALK).
#define ALT_TWIN_R 4

// ---------------------------------------------------------------- claimed mates near me that may join my crew (econ_team_model).
// free_near() and crew_for_ref's pass 0 count only mates with no claim, so two bodies each walking to its own far claim pass a pair
// group neither can clear alone. Bit 1: free_near also counts a visible mate within BYC_NEAR, not engaged, not in a fight, not
// channelling, whose claimed group is >= BYC_FAR tiles from it; crew_for_ref's pass 0 (my own crews only) takes such a mate for
// group q when its claim is also farther from it than q. Flag BYC_BITS, 0 = off.
#define BYC_BITS 1
#define BYC_FAR 15 // [2] the mate's claimed group is at least this far from it (Chebyshev, to the anchor)
#define BYC_NEAR 8 // [3] the mate stands within this Chebyshev distance of me (free_near's own radius)
inline constexpr int BYC_TAB[4] = { 0x42594331, BYC_BITS, BYC_FAR, BYC_NEAR };
constexpr int BYC_B_CREW = 1;

// ---------------------------------------------------------------- calling, joining and peeling for first fights (econ_team_ops).
// Case: a 2v2 lost while a full-HP body farmed a camp 3-5 tiles away: no HELP was posted, her camp engagement blocked help_join, and
// mutual peel held both fighters in. Flag FHC_BITS, 0 = off. Bits: 1 CALL a FIGHT turn under fire (hit this round or a foe in reach)
// at ratio_near < FHC_CALL_X100/100 with an idle mate (healthy, free, no foe I see within 4 of it) 3..EN_HELP_R away posts HELP
// (brain early_stages, beside en_help's post) 2 JOIN help_join may answer while engaged on a camp (not capturing) within FHC_JOIN_R
// when the fight swing is worth more than staying (join_worth: swing = (mates' bodies + bags at stake) x my numbers lift x arrival
// in time; stay = the camp's gems (half unless about to capture) + the camp damage of walking away) 4 PEEL assess_rule_peel holds no
// FIGHT when my worst ratio < FHC_PEEL_X100/100 while I am under fire myself (mutual peel)
#define FHC_CALL_X100 130
#define FHC_JOIN_R 8
#define FHC_PEEL_X100 60
#define FHC_BODY_G 40

// ---------------------------------------------------------------- recall a carried bag out of a dead-end (econ_recall_heal). Case:
// a 122-gem carrier at 49% HP, in a dead-end pocket 5-6 tiles from a tributing foe, walked A-B-A for 18 rounds and died when her
// channel ended. go_home refuses the recall whenever a visible foe could geometrically reach me during the channel (recall_safe:
// RO_REACH / enemy_close), whatever it can deal. Bit 1: a bag carrier recalls anyway when the most damage every visible foe can deal
// me before the recall lands (each foe's own cooldowns, walk and dash, each spell once; a channelling foe counted as acting at once)
// stays under RCD_PCT% of my health (the other recall_safe tests kept: hurt, recent cancel, awake camps). Bit 2 HOLD: go_home's "no
// tile nearer home" fallback no longer paths toward a goal tile through a threat's reach when I already stand outside every reach
// (the A-B-A: step_to_set(goals) stepped into the reach, step_to_set(homeward) stepped back). Flag RCD_BITS, 0 = off.
#define RCD_BITS 1
#define RCD_PCT 60 // [2] recall when the foes' best damage before it lands is under this % of my HP + shield
#define RCD_BAG 30 // [3] only with at least this many gems carried
#define RCD_R 14   // [4] foes counted within this Chebyshev distance
inline constexpr int RCD_TAB[5] = { 0x52434431, RCD_BITS, RCD_PCT, RCD_BAG, RCD_R };
constexpr int RCD_B_REC = 1, RCD_B_HOLD = 2;

#define WCK_TURNS 2

// ---------------------------------------------------------------- a winning bag stuck fleeing recalls home (econ_bank_win): a
// winning bag stuck in a flee/return loop recalls home. Case: a Prism with a winning 823 bag at 47% HP alternated flee_stage and
// bank_winning_bag's altar walk for 27 rounds and died with the bag; flee_streak never reached its count, and the winning-bag guard counts
// only refusals at the altar. Flag WFF_BITS, 0 = off. Bits (7): 1 = once WFF_FLEE_N of the last WFF_WIN turns were FLEE (no channel
// between), bank_winning_bag recalls when recall_safe, else on a FLEE turn leaves the turn to the flee (no altar walk), else walks home
// (econ::go_home). 2 = FIGHT_GATE: a winning bag starts a new FIGHT only on kill_now, when caught, or when the foes' two-turn burst
// is below my HP; else FLEE, and bank_winning_bag then recalls when safe (act), unless she stands on a tribute tile and the tribute guard
// passes (the bank starts as usual). Hooks: brain_*.cc turn() (note, before early_stages), combat_*.cc assess() (the gate, last
// rule), econ_*.cc bank_winning_bag_slow (after the winning test). 4 = STAKE: the bag's bar rise uses the stake share min(1, bag /
// max(WFF_STK_MIN, (1000 - tributed) / 2)) for the share of BAG_FULL: engage + E0 + E1 x stake, flee + F0 + F1 x stake (x100 in
// WFF_STK_TAB); the share is max(min(1, bag / WFF_STK_MIN), stake), so the bars only rise, in place of combat's BAG_ENGAGE/BAG_FLEE
// rise (combat_*.cc assess_bars_bag_and_support). Flag first: 0 does no work.
#define WFF_STK_MIN 80 // bit 4: the stake's floor, gems
#define WFF_STK_E0 20 // bit 4: engage bar + (E0 + E1 x stake) / 100
#define WFF_STK_E1 80
#define WFF_STK_F0 10 // bit 4: flee bar + (F0 + F1 x stake) / 100
#define WFF_STK_F1 50
inline constexpr int WFF_STK_TAB[6] = { 0x5746534b, WFF_STK_MIN, WFF_STK_E0, WFF_STK_E1, WFF_STK_F0, WFF_STK_F1 }; // bit 4 values

// WCD: the two-turn lethal test on a winning channel counted the dash twice (01a1bae3). foe_burst_lethal_to_healer only. 0 = off. Bits: 1 = visible
// foes use their real two-turn reach (combat::foe_damage_over_ticks_wcd); 2 (with 1) = remembered foes too, one tile a turn beyond their next-turn reach.
// v628 WCD: two-turn lethal test uses real foe reach

// WDV: foe_burst_lethal_to_healer charges a foe I see only the hits it can land in its two turns (01a1bc0e r404: Marcella d5 charged 1126, can land 840), not burst + dps x left. 0 = off. Bit 1 = on.
// v631 WDV: baked at its shipped value

// PBK (pbk): bank trip timing, docs/rules-gaps.md 'Prism carrier' and 'Bank trips'. 0 = nova_b9994_rgsfix2. Bit 2 = a winning bag or an urgent bank (why 2, 5, 6) walks to the nearest altar, and the late bank (why 1) is timed on the walk she takes.
// v635 PBK: bank trip timed by the altar she walks to

// v637 EB4: crew check counts unseen busy claimant
// EMD (emblem_plan_1108 S1): emblem_rank values from rules and amounts. Jungle (bit 1's absolute camp term; bit 2's own term was dead
// and is gone): 0.30 x camp damage taken per alive round x recall rounds per HP lost x income x rounds after completion / 30 gold a
// shard x EMD_GK %; before hits, a prior of the map's mean camp Str x EMD_PK % (x EMD_TANK % for the team's best camp tank). Cycle:
// recall (5, Home 3) + EMD_WD % of the spawn-to-spawn walk.
// Bit 1 (S1, emblem_plan_1108 section 11): every unowned family scored as my running rate x rounds left after completion, in gold +
// 2 x gems, blended with a kit/map cold-start prior by turns seen (EMD_PRN); fight families (Durability, Hunter, Skirmish, stat-only
// entries) on expected fight rounds; Durability with its death term. Re-ranks inside make_build's window (guards stay); absent
// passive families may replace the weakest stat-only entry. Gold values -> shards at EMD_GK % / 30; fight rounds x EMD_FR % after
// a contact in the last 50 rounds.
#define EMD_BITS 3
#define EMD_PK 12
#define EMD_TANK 250
#define EMD_WD 50
#define EMD_PRN 120
#define EMD_GK 65
// v641 EMD: emblem plan S1, rate-based family ranking
#define EMD_FR 130
inline constexpr int EMD_TAB[8] = { 0x454D4431, EMD_BITS, EMD_PK, EMD_TANK, EMD_WD, EMD_PRN, EMD_GK, EMD_FR }; // slot 0 magic keeps it out of .bss
// SKG (spec_skg_1108): greed_tail_pass turns the first Power entry it would make Greed into Skirmish of that stat when the body owns
// and plans no Skirmish (emblem_rank's swap never finds a Power entry once the tail is Greed). Bit 1: on.
// v641 SKG: emblem plan S1, rate-based family ranking

// CDX (spec_cdx_1109, owner game 01a1bfc9-...-7b65; b1760): dashers bought crystals where a free dash crossing is as fast. 0 = nova_base_v645.
// Bit 1 (not shipped): prepare the dash route before any crystal buy (kind 0 and the bank, not only when the walk is UNREACH), and before the bank hop.
// Bit 2 (not shipped): a dasher whose dash checks could not run for fuel (thin_hole_plan's fuel minimums, a skipped dash-route prepare) buys no crystal
// this turn and stays on the spawn (retry next turn, at most 3 turns); the mid hop waits a turn the same way.
// Bit 4 (Combat, owner game 01a1bfc9): no crystal into a contested landing: 2+ known foes (seen, or in combat memory <= 3 rounds old)
// within 5 of the landing and no living mate within 5 of it; the body walks or dashes instead (buy, spawn hold, every cast).
// v646 CDX: no crystal into a contested landing
// HVY (b1771, spec_hvy_1109 Step 1, factorial winner CAL): estimate()'s camp damage on own-half heavy groups (monolith or golem,
// contest <= .45) x HVY_CAL_X100 / 100: our bodies took .46-.62 of the modelled damage there (b1771 census, 600 games). Runtime data
// flag HVY_TAB[1], read first; 0 = off. Bit 2 CAL (bits 1 GRL and 4 TRIP closed, not carried).
#define HVY_BITS 2
// v651 HVY: baked at its shipped value
#define HVY_CAL_X100 55
inline constexpr int HVY_TAB[3] = { 0x48565932, HVY_BITS, HVY_CAL_X100 }; // slot 0 magic keeps it out of .bss

// FB1 (Rule Checker flag-leak audit, docs/bot_errors.md "Flag leaks and bake leftovers", v651; b1775): decision-identical fuel cuts.
// 0 = nova_base_v653. Bit 1 FL1: camp_engaged_check tests its cheap re-entry gate before incoming_at (no threat list). Bit 2 FL2:
// wants_heal / finish_target_before_shop pass no threat list to incoming_at. Bit 4 FL3: squad_partner_retarget tests its trigger
// before the fuel reads. Bit 8 FL4: bank_channel_camp_move prices bag_wins_with_mates only past its gate. Bit 16 CK2:
// focus_under_other_heavy_camp returns false at once (its loop result was never used).

// FB2 (Rule Checker "Play-identical fuel savings", v655/v656; b1775): play-identical fuel cuts, one bit per row. 0 = nova_base_v656.
// Bit 4 FU3: choose_target's candidate copies as resize + memcpy (same order; the sort untouched). Bit 8 FU4: threat_seen_t stops at
// the first foe near a group and the brain passes a.threats without a copy. (FU1 and FU2 measured no saving or a cost: not carried.)
// v667 FB2: FB2 cand memcpy + threat_seen early break
// v656 FB1: FB1 flag-leak fuel cuts, decisions identical
// SSG (spec_ssg_1109, b1777; verified bug): mf2_ssg ("the spawn monolith group is the map's economy") counted every other group,
// the foe's mirrored home monolith included, so it was false on every symmetric spawn-monolith map. Bit 1: skip groups nearer the
// enemy spawn than ours in that sum. 0 = off.
// v657 SSG: siege sum skips foe-half groups (SSG)
// SSGR (Tool Builder, 9 Nov ~23:10Z; owner asked for a double check of the bug-fix ships): two fresh reads of SSG v its flag-0 trunk read
// .4958 [.492,.500] and .4975 [.494,.501] n1200 each, both under .50. Bit 1 reverts SSG: the siege sum counts the foe's-half groups again.
// v675 SSGR: 3 fixes ssgrev,bb41,ktb64r
// FSR (b1769, Econ: far maps, we complete +20% recalls v the top 3; recallcycle_1031: same gold in 1.2x the shop trips): on far maps
// (max side >= FSR_SIDE, map data known at setup), a healthy body (HP >= RD_HURT %) more than 12 from home shop-recalls only with gold
// >= the next cost + FSR_EXTRA. 0 = off.
#define FSR_BITS 1
#define FSR_EXTRA 60
// v661 FSR: far-map shop trips carry bigger ord FSR_EXTRA=60
#define FSR_SIDE 70
inline constexpr int FSR_TAB[4] = { 0x46535231, FSR_BITS, FSR_EXTRA, FSR_SIDE }; // slot 0 magic keeps it out of .bss

// v662 IDL (b1776, Econ spec_idl_1109 v1): a crew that can already clear (target_turn_start_or_hold's ok) starts after IDL_S0 rounds
// without the better tank (was 3), and the ok-wait cap is IDL_OKW rounds (was 8).
#define IDL_BITS 1
#define IDL_S0 1
#define IDL_OKW 4

// BB29 (b1776, Rule Checker "End game re-audit", docs/bot_errors.md EG1-EG4): runtime data flag, read first; 0 = v662. Bit 1 EG1
// altar_hold keeps a remembered game-ending foe bag unless their tributed total rose by at least that bag (a completed tribute banks
// the whole bag, GR:226/233). Bit 2 EG2 the altar guard drops foe bags that cannot land by GAME_END (now + arrival + ticks).
// Non-Prism bodies only (the Prism halves are held for the owner; a Prism body never reaches these lines' new branches): bit 4 EG3
// end_hold_blocks_bank never holds a winning bag; bit 8 EG4 the winning-bag flip-flop guard clears only when no later start can
// land (round + walk + ticks >= GAME_END), not from 1990. Death and kill pricing: bit 16 DK1 stake_bars' win-progress term uses
// need = max(1, 1000 - tributed_us) (it was never below 80, so a winning bag read .625, GR:30); bit 32 DK2 emd_observe books a >= 90
// gold gain on a camp tile within 3 rounds of a fight, with no capture of that group in the last 2 rounds, as a kill, not a reward.
// Emblem valuation: bit 64 EV1 emb_fturns counts turns at dmin <= 5 like emb_hp_ch (it used <= 4: Durability read ~18% high).
// v668 BB29: BB29 end-game EG1-4 nonPrism, DK1-2, EV1
#define BB29_BITS 127
inline constexpr int BB29_TAB[2] = { 0x42423239, BB29_BITS }; // slot 0 magic keeps it out of .bss
#define BB29_ON(b) ((BB29_TAB[1] & (b)) != 0)
inline constexpr int IDL_TAB[4] = { 0x49444C31, IDL_BITS, IDL_S0, IDL_OKW }; // slot 0 magic keeps it out of .bss
// v701 q4 X93: RGF1 (spawn_siege_commit_ok prices a dead/stale foe at respawn left + its walk - 5, GR:375) and SSR1 (the RALLY
// recall takes CHIP's game-end test) baked on.

// MCK (b1759, Econ spec_mcl_1109 "MCL"; prefix MCK since MCL_ is the map-class table): light / cluster-only mid gem groups. Runtime data
// flag, read first; 0 = off. Bit 1: for a gem group with no attacking camp (n_att 0) and contest <= .70, the 25-round respawn-wait cap
// (and crew_wait_limit) in the bound loop and rate_for becomes MCK_WAIT; the rate's own t += wait prices the wait. Bit 2: group_value
// (and its bound) x MCK_V / 100 for a cluster-only or light (<= 2 wolves, nothing heavier) gem group in the mid (contest .35-.65).
#define MCK_BITS 2
#define MCK_WAIT 40
// v664 MCK: mid light gem group value (MCK_V) MCK_V=110
#define MCK_V 110
inline constexpr int MCK_TAB[4] = { 0x4D434B31, MCK_BITS, MCK_WAIT, MCK_V }; // slot 0 magic keeps it out of .bss
// MCK bit 2: a light or cluster-only gem group in the mid.
#define MCK_LIGHT_MID(g) ((g).gems > 0 && (g).contest >= 0.35f && (g).contest <= 0.65f && (g).n_mono == 0 && (g).n_golem == 0 && (g).n_elk == 0 && (g).n_wolf <= 2)
// HV2 (b1771, Rule Checker "Siege / heavy re-audit", bot_errors.md): crew_bail's holding rounds and skip summed my attackers' raw
// camp strength, while incoming_at / camp_threat apply my camp-hit factor (Durability .9, Jungle .7: mu::ct_k), so a Jungle tank read
// ~37% fewer holding rounds and bailed early. Runtime data flag HV2_TAB[1], read first; 0 = off. Bit 1: my own rounds and my
// incoming in skip use mu::ct_k (mates' factors are not known here; their sums stay raw).
// v665 HV2: crew bail rounds use my camp-hit factor

// BB27 (b1776, Rule Checker "Target rate formulas", docs/bot_errors.md RT1-RT2): runtime data flag, read first; 0 = v660. In
// RateJob::crew_term's lone-v-pair branch (target choice only, never tribute starts): bit 1 RT1 the pair's penalty also carries
// prism_mate_factor (applied to pen after pen_crew was saved, so the pair dropped it); bit 2 RT2 the pair's penalty swaps the solo
// foe-arrival factor faf_of(F, 1) for the pair's faf_of(F, 2).
// v666 BB27: BB27 pair rate keeps PHM + pair foe risk
// SEN (b1759, Rule Checker AB1 "A,B,A,B walking", RG 352): claim seniority. Runtime data flag SEN_TAB[1], read first; 0 = off. Bit 1:
// claims_for_me also drops a mate's claim on my target that started after my own choice of it (T.chosen), whatever the mate's priority,
// so the holder keeps the group and the later joiner becomes crew or moves on (a higher-priority crew joiner and a solo holder swapped
// groups every turn). The start round of each mate's claim is tracked where the team model reads it (sen_since).
// v669 SEN: claim seniority, newer claims yield (SEN)
// FB6 (b1759, Rule Checker docs/bot_errors.md "Reorder fuel lines", v663): removed work only, play-identical (cxeident 80/80 baked v665,
// same-work fuel -0.32%). Runtime data flag FB6_TAB[1], read first; 0 = off. 1 RO1 intel end_turn exits before the news loop when a fresh
// ENEMIES or TAKEN/CLEARED post stands; 2 RO2 sense() loops break on the first hit; 4 RO3 fight_gap_dash runs its gate before the kill
// tests; 8 RO4 time_and_value: finish v group value once, neither when the endgame test passes; 16 RO5/RO7 min-HP camp scans skip
// hp >= best first; 32 RO6 squad_partner_retarget: the FB1 cooldown before the squad reads; 64 RO8 observe_foe_near_group returns at
// the first hit. px_far (econ_tank_support.cc) is not touched (it changes steps by reference).
#define FB6_BITS 0
inline const volatile int FB6_TAB[2] = { 0x46423631, FB6_BITS }; // slot 0 magic keeps it out of .bss
#define FB6_ON(b) ((FB6_TAB[1] & (b)) != 0)
// CPT (b1778, Rule Checker A03 on v675): capture bookkeeping bugs. Runtime data flag CPT_TAB[1], read first; 0 = off.
// 1: spawn_purchases runs before the capture stage, so on a capture-recall's arrival turn the reward's gold is spent before the payout
//    test sees it; the test compares max(gold, gold before this turn's purchases), and a gain read while the group state is unknown (0)
//    counts only after a recall started since the timer, else it rebases. 2 (not shipped; its code is gone): a body joining an ally's
//    running capture takes the engine's remaining timer as the pay round. 4: track_progress resets best_d when its value turns from
//    Chebyshev to a path value (a fuel-short first call left a Chebyshev best that path values never beat, and drop_target(60) fired
//    mid-walk). 8: capture_recall's gold share uses split_share (GR:207). 16: the low-fuel exit count
//    resets on a turn that moved or captures.
// v682 CPT: 7 fixes fb10c,cpt29c,cpt29c,grd3c,cib47,cpw1,cis7
#define CPT_BITS 29
inline constexpr int CPT_TAB[2] = { 0x43505431, CPT_BITS }; // slot 0 magic keeps it out of .bss
// GRD (b1778, Rule Checker grd_fb11_rulecheck_1110): emblem shard counts by family (GR:289, :301-317: Greed combines at 25 shards and
// gives 40 shards' stats, Power gives 6, the rest 5). Runtime data flag GRD_TAB[1], read first; 0 = off. Bit 1: emblem_gold_refresh
// prices a Greed emblem's remaining cost as 30 x (25 - shards held), not a flat 150. Bit 2: refresh_owned_slow counts a Greed emblem as 40
// shards and a Power emblem as 6 (was 5 for every emblem).
// v682 GRD: 7 fixes fb10c,cpt29c,cpt29c,grd3c,cib47,cpw1,cis7
#define GRD_BITS 3
inline constexpr int GRD_TAB[2] = { 0x47524431, GRD_BITS }; // slot 0 magic keeps it out of .bss

// BB41 (b1756, Rule Checker RD1/RD2, bot_errors.md 'Recall decisions re-audit'). Runtime data flags, read first; 0 = off.
// WBQ_TAB[1] bit 1 (RD1): cancel_recall_for_winning_bag keeps the recall when bank_winning_bag will not take the turn: the tribute start
// is refused (brain's FIGHT-stance skip) or the winning-bag flee loop owns the bag (its act() restarts the recall or walks home).
// BTL_TAB[1] bit 1 (RD2): bag_too_late_to_bank_slow starts from d = BIG, not 0, so the home-altar recall time counts when the bank
// field is UNREACH; no altar reachable either way: false.
// v675 WBQ: 3 fixes ssgrev,bb41,ktb64r
// v675 BTL: 3 fixes ssgrev,bb41,ktb64r
// HVB (b1771; Rule Checker siege/heavy re-audit). Runtime data flag HVB_TAB[1], read first; 0 = off. (Bits 1 RELIEF, 2 BUDGET, 4
// FULLEXIT closed and not carried.) Bit 8 HV5: about_to_capture measures from the nearest member, not the anchor. Bit 16 HV6: the
// healer is not counted toward the siege crew K (SG_K's comment). Bit 32 HV4: an unseen slot is free for an operation only if I last
// saw it healthy (>= SG_HP) and not recalling.
// v677 HVB: 4 fixes hvb56c,drs,kfx,sjb1

// DRS (b1782, Rule Checker's death/respawn stale-state rows). Runtime data flag, read first; 0 = v675. Bit 2: a dead turn ends the spawn-crystal
// trip (sc_end), so a trip abandoned by death no longer blocks the recall hops and the bank walk's mid hop (SC.on && !SC.used tests,
// econ_crystal_spawn_route.cc, econ_crystal_mid_hops.cc). Bit 4: a dead turn forgets the region clock (reg_gi), so the capture hold logic
// does not read a pre-death arrival. Bit 8: recall_hop_prebuy does not price a crystal on the pre-death target (T.eval_round -1000).
// Bit 16 (A08): a dead turn and a new target clear the hole-shortcut commit (hs3_commit_g), so a stale commit no longer lowers the shortcut
// gain bar, skips HOLE_SHORT_MIN or fires the bank shortcut without its detour test. Bit 1 (filler/chip reset) not built: its Step 0 fired
// 0 times in 300 games.
// v677 DRS: 4 fixes hvb56c,drs,kfx,sjb1
// SJB (b1777; Deep owner_01a1c27e_1109 + Rule Checker / Planner amendments): a called siege that never starts holds bodies. Read first;
// 0 = nova_base_v674. Bit 1 (verified bug): no siege join whose bank trip cannot arrive before the gather deadline (walk + 2 x bank walk
// + 6 + SG_SLACK > SG_GMAX), tested before T.bank_until is raised. Bit 2: a committed mate counts only while it claims the group or its
// arrival (bank trip included) fits the deadline, so the early release and the collapse work. Bit 8 (A06, not shipped): a foe Prism's power drops
// the +1.5 Focus per carried gem (GR:564), so a banked or dead Prism no longer reads strong in the call gate's stats ratio.
// v677 SJB: 4 fixes hvb56c,drs,kfx,sjb1

// FX7 (b1782, v677 regressions + DRS follow-ups, Rule Checker). Runtime data flag, read first; 0 = v677.
// Bit 1 (KFX bit 4 regression): btl_too_late's both-UNREACH case (no altar walk, no home altar) reads "not too late" again (v675): its five
// callers bank by crystal, recall hop, walled-in recall or dash. Bit 128 (UBK): want_bank's idle-dasher bank needs a dash route. Bit 2 (HV6): siege_free_crew counts the healer toward SG_K again. Bit 4 (DRS bit 16):
// a new target keeps the bank-shortcut altar commit (hs3_commit_g == hsb_alt(), i.e. M.ng). Bit 8 (DRS bit 8): recall_hop_prebuy skips
// the pre-death target only while dead (!W.alive), not on the first live spawn turn. Bit 16 (DRS bit 1): a dead turn clears the filler
// hold and the chip budget (T.filler_until, frl_chip_gi / frl_chip_until). Owner's Prism rule (Rule Checker): bit 32: btl_too_late keeps
// v674's test for the Prism (d from 0, no both-UNREACH "too late"); bit 64: BB29 EG1 / EG2 (altar hold) skip the Prism, as EG3 / EG4 do.
// v678 FX7: v677 regressions + Prism owner rule
// LKR (b1786, Builder LKR1). Runtime data flag, read first; 0 = v682. Bit 1: lock_hit lets a ranged body that walked this turn reset
// and hit an enemy altar lock (walk, reset, basic is legal; a ranged walk uses the attack, INT:26/:29), under the same quiet rule as
// the second-hit reset (gems >= 30, no foe within 8), instead of skipping the hit until next turn.
// v683 LKR: ranged lock hit after a walk via reset
#define LKR_BITS 1
inline constexpr int LKR_TAB[2] = { 0x4C4B5231, LKR_BITS }; // slot 0 magic keeps it out of .bss
// ORC (b1800, Builder POSSIBLE row): runtime data flag ORC_TAB[1], read first; 0 = off. Bit 1: after my own recall cancel (doomed
// recall, Willow cancel, winning-bag cancel; brain_turn channel_holds) S.recalling clears at once, so the next sense() no longer reads it
// as a damage cancel (S.recall_cancel), which blocked recall_safe and carry_recall_gate for 3 rounds. The recall-hop and recall-loop
// guards still see the own cancel as a cancel (S.orc_cancel).
// v685 ORC: 19 fixes phy1r2,npb1,orc1,wvc,cia3s,jgw31,x02,idm +11
#define ORC_BITS 1
inline constexpr int ORC_TAB[2] = { 0x4F524331, ORC_BITS };
// HSC (b1800, Builder HSC1 POSSIBLE): runtime data flag HSC_TAB[1], read first; 0 = off. Bit 1: the hole-shortcut commit (hs3_commit_g)
// clears in on_recall and counts as held only while it was written last round or this one (hsc_commit_r >= now() - 1): a stale commit no
// longer skips the 12-walk floor, cuts the saving to 1 or forces the bank shortcut.
// v685 HSC: 19 fixes phy1r2,npb1,orc1,wvc,cia3s,jgw31,x02,idm +11
#define HSC_BITS 1
inline constexpr int HSC_TAB[2] = { 0x48534331, HSC_BITS };

// X02 (b1799, Rule Checker X02 audit): small error-path fixes. Runtime data flag X02_TAB[1], read first; 0 = off.
// Bit 1: shop: each buy books its gold at once (W.gold, emb_pgold, own.checked), so an engine throw later in the visit (the catch at
// the end) no longer leaves the spent gold counted and the purchase read as income. Bit 2: altar hold: a hold whose walk step fails
// does not claim the turn. Bit 4: ward pin: only a false return (GR rc 117 seen as false: a mate's ward) notes a mate's ward on the
// pin tile; a throw (no charge, bad tile, out of range, stunned) does not.
// v685 X02: 19 fixes phy1r2,npb1,orc1,wvc,cia3s,jgw31,x02,idm +11
#define X02_BITS 7
inline constexpr int X02_TAB[2] = { 0x58303231, X02_BITS }; // slot 0 magic keeps it out of .bss

// IDM (b1796, Rule Checker idl2_rulecheck_1110 IDL bit 1). Runtime data flag, read first; 0 = off. Bit 1: mid_hop_try does not spend the
// crystal on a group walk that is not to my target (idle_move's walk to its wait group), as econ.h's mid-hop comment says.
// v685 IDM: 19 fixes phy1r2,npb1,orc1,wvc,cia3s,jgw31,x02,idm +11
#define IDM_BITS 1
inline constexpr int IDM_TAB[2] = { 0x49444d31, IDM_BITS }; // slot 0 magic keeps it out of .bss
// ALZ (b1786, map_rulecheck_1110.md MAP bit 1). Runtime data flag, read first; 0 = v682. Bit 1: altar_hold_field builds each altar
// entry's field lazily in its own slot (a vector sized M.na) instead of 3 slots that are never freed, so a 4th altar entry the end-game
// hold asks about no longer returns nullptr (and is skipped) for the rest of the game.
// v685 ALZ: 19 fixes phy1r2,npb1,orc1,wvc,cia3s,jgw31,x02,idm +11
#define ALZ_BITS 1
inline constexpr int ALZ_TAB[2] = { 0x414C5A31, ALZ_BITS }; // slot 0 magic keeps it out of .bss

// WBH (b1789, Rule Checker WBH1, 10 Nov): cancel_recall_for_winning_bag cancels a recall for a bank that end_hold_blocks_bank then
// refuses (bag_wins_with_mates, own total < 1000, foe near, late game). Runtime data flag WBH_TAB[1], read first; 0 = off. Bit 1: the
// cancel is refused when the end hold would block that bank (non-Prism carriers only: owner's Prism rule, Prism part parked).
// v685 WBH: 19 fixes phy1r2,npb1,orc1,wvc,cia3s,jgw31,x02,idm +11
#define WBH_BITS 1
inline constexpr int WBH_TAB[2] = { 0x57424831, WBH_BITS }; // slot 0 magic keeps it out of .bss
// SOI (b1810, bot_errors row 852, Rule Checker verify_so_v684): the idle pick (econ_idle.cc) never skipped an awake group, so the
// body walked into Golem/Monolith reach and back. Runtime data flag SOI_TAB[1], read first; 0 = off. Bit 1: when the pick lands on a
// visibly awake group (group_awake), re-pick without awake groups (none left: no idle group this time).
// v687 SOI: 5 fixes tisbd,ip3rsgb,soi,ip3rsgs,bef32
#define SOI_BITS 1
inline constexpr int SOI_TAB[2] = { 0x534F4931, SOI_BITS }; // slot 0 magic keeps it out of .bss

// BKG (b1789, bot_errors row 595 BNK2): bank_first's finish branch (FLEE) set wb2_lc, so bank() skipped both tribute start guards
// (tribute_start_allowed, new_tribute_blocked: the foe that ended my last channel, a restart hold); a stun, death or new lock still
// ends a tribute (GameRules:226). Runtime data flag BKG_TAB[1], read first; 0 = off. Bit 1: that bank keeps the guards (the Prism never
// reaches the branch: bank_skip_bus). Supersedes the held SBG1 (sbf1), which skipped them at the step turn too.
// v688 BKG: 3 fixes bkg1ff,hcp3,pho1
#define BKG_BITS 1
inline constexpr int BKG_TAB[2] = { 0x424B4731, BKG_BITS }; // slot 0 magic keeps it out of .bss
// CRE (b1807, Rule Checker CRE1, bug bar). Runtime data flag CRE_TAB[1], read first; 0 = v686. Bit 1: cap_rank's two C&I terms test the
// RANKED slot's kit, not mine (CI2_FARM() reads W.me.type): a C&I slot always takes work_rank (econ_capture.cc) and never CI_CAP_PEN
// (planner.cc stack_rank_bonus), so every body ranks the pair the same and they stop splitting a gold group.
#define CRE_BITS 0
inline const volatile int CRE_TAB[2] = { 0x43524531, CRE_BITS }; // slot 0 magic keeps it out of .bss
#define CRE_ON(b) ((CRE_TAB[1] & (b)) != 0)
// X66 (b1790, Rule Checker X66 on v692): capture timing. Bit 1 JOIN: group_capture_pay_rounds dated a Capture Emblem holder's join by
// the round we first SEE it on the region; a holder that has not acted yet this round stepped on in its turn last round (after ours),
// so its join is now - 1 (Step 0: 1.4/g first sightings a round late v the engine timer). Bit 2 MATEPAY: mark_mate_capture dated the
// mate's payout as if its timer started now; while the engine shows our capture running, the payout is now + its timer (GR:196;
// Step 0: 15.5/g predictions 1-5 rounds late).
// v695 X66: 9 fixes fbbw3,tcs,x66j,bhw1,x65c,fgd1,pbq8,qmd1,xgv1
#define X66_BITS 1
inline constexpr int X66_TAB[2] = { 0x58363631, X66_BITS }; // slot 0 magic keeps it out of .bss
// PHO (b1807, Rule Checker PHO1, bug bar). Runtime data flag PHO_TAB[1], read first; 0 = v686. Bit 1: mate_holds_region counts only a
// mate that claims the group (claims(a.slot, gi)), as CHH bit 2 does in capture_region_handoff: a mate passing over holds nothing.
// v688 PHO: 3 fixes bkg1ff,hcp3,pho1
// b1816 PHO2 (Rule Checker Pass 4 PHO2 + the PHO1 handoff site, Planner spec_rcp4_1110 P3): the table is volatile again; bit 1 is baked.
// Bit 2: mate_holds_capture_region_turn counts only a non-channelling mate that claims the group; a passer on the region makes me wait
// (return 2) up to PHO_WAIT rounds instead of booking a mate capture (GR:196: the region empties when it walks off). Bit 4:
// capture_region_handoff hands the capture only to a mate that claims the group.
// v708 PHO: baked at its shipped value
#define PHO_BITS 7
inline constexpr int PHO_TAB[2] = { 0x50484F31, PHO_BITS }; // slot 0 magic keeps it out of .bss
#define PHO_WAIT 3
// WHV (b1810, Deep spec_whv_1109.md, owner replay 01a1c29e: Willow on heavy crews). Runtime data flag WHV_TAB[1], read first; 0 = off.
// Bit 4 ATTACH: Willow's own rate of a heavy group (golem, or 2+ elk; no monolith unless bit 16; attacking, walkable, alive) that
// >= 2 living mates work (claim it or stand within 6 of its anchor) is x (1 + WL2_PULL_X100/100) x (1 + WHV_PULL_X100/100) instead of
// WL2's factor; not with her bag >= WL2_BANK, under 50% HP, a foe near the group (15 rounds) or the group nearly dead.
// Bit 8: bit 4 needs >= 3 working mates. Bit 16: monoliths count as heavy (separate arm only).
#define WHV_BITS 4
#define WHV_PULL_X100 100
#define WHV_VAL_X100 15
// v690 WHV: Willow follows 3+ heavy crews (WHV 4)
#define WHV_HEAL_X100 75
inline constexpr int WHV_TAB[5] = { 0x57485631, WHV_BITS, WHV_PULL_X100, WHV_VAL_X100, WHV_HEAL_X100 }; // slot 0 magic keeps it out of .bss

// PRB (b1789, Prism start/keep bundle, owner-approved 10 Nov: the bars decide). Runtime data flag PRB_TAB[1], read first; 0 = off.
// Bit 2 (PRB1): recall_bank_saves_walk prices the nearest altar (not the Prism's safe altar) when pbk_nearest_altar() holds, as
// bank_carrier_field does. Bit 4: tribute_restart_hold runs its no-block test before ward::react (no ward on a turn it does not block).
// v693 PRB: 4 fixes be2b8f,fsb4,qms1,prb4f
#define PRB_BITS 4
inline constexpr int PRB_TAB[2] = { 0x50524231, PRB_BITS }; // slot 0 magic keeps it out of .bss
// TCS (b1796, Rule Checker target keep/switch pass TCS1). Runtime data flag, read first; 0 = off. apply_retarget_choice's keep exits
// re-rate the current target but wrote only T.eval_round, so T.crew / T.rate stayed stale for claims_for_me, the solo crystal and
// recall-hop gates and the siege rate test. Bit 1: the best < 0 keep exit stores the re-rate's crew and rate. Bit 2: the switch-test
// keep exit does.
// v695 TCS: 9 fixes fbbw3,tcs,x66j,bhw1,x65c,fgd1,pbq8,qmd1,xgv1
#define TCS_BITS 3
inline constexpr int TCS_TAB[2] = { 0x54435331, TCS_BITS }; // slot 0 magic keeps it out of .bss
// AHX (b1808, X76 altar-hold rows). Runtime data flag AHX_TAB[1], read first; 0 = v693. Bit 1 AHC1: alz_field walls M.block_camps, so a
// body on a camp tile read UNREACH; the hold's three reads (foe carriers, candidates, me) take mv::field_nb (best neighbour + 1). Bit 2
// AHC2: home_altar_dist also takes a gated altar once gate_open() (its gate group dead), as bankable() does.
// Bit 4 AHC3: the hold's foe ETA per altar adds the hits left on our own lock there (a foe must clear it first).
#define AHX_BITS 0
inline const volatile int AHX_TAB[2] = { 0x41485831, AHX_BITS }; // slot 0 magic keeps it out of .bss
#define AHX_ON(b) ((AHX_TAB[1] & (b)) != 0)
// b1802 XGV (Rule Checker X70): runtime data flag, 0 = off. Bit 1: the end-game gold-only value (rate_for's crew trip and the PEG1 pair
// trip) applies group_value's gold terms: the slot's gold weight, holder_gold_mult (Vesper +33%, Treasure +10%, GR:532) and Prospector gold
// (GR:297), instead of the bare team gold weight.
// v695 XGV: 9 fixes fbbw3,tcs,x66j,bhw1,x65c,fgd1,pbq8,qmd1,xgv1
#define XGV_BITS 1
inline constexpr int XGV_TAB[2] = { 0x58475631, XGV_BITS }; // slot 0 magic keeps it out of .bss
// EMX (b1808, X87 emblem choice). Runtime data flag EMX_TAB[1], read first; 0 = v696. Bit 1 PRS1: Prospector's realised term is 25% of my
// realised cluster value per round (GR:297 pays on the own cluster share only), not that share applied to all income. Bit 2 CPU1: Capture
// books timer - 3 rounds saved per capture joined at timer >= 4 (GR:313: 5 -> 3 saves 2, 4 -> 3 saves 1), .7 of each round turned into
// work. Bit 4 MTK1: a +90 gold jump right after a fight is no kill when my bag just dropped (a tribute paid it, Marcella 2/gem). Bit 8
// TVR1: Tavi's sale refunds are not income (emb_pgold reset after the sale).
// v698 EMX: 3 fixes tsb24g,tvr2,q2
#define EMX_BITS 8

// VOH (b1815, VOH1 bot_errors.md:2253): 0 = nova_b11309_fxb18z. Bit 1: cap_rank drops vesper_open::rank's -5000 (her first capture) for a
// slot under 35% HP, so the <35% yield works for a hurt Vesper and a mate in the region takes the capture (GR:196).
// v708 VOH: baked at its shipped value
#define VOH_BITS 1
inline constexpr int VOH_TAB[2] = { 0x564F4831, VOH_BITS }; // slot 0 magic keeps it out of .bss
inline constexpr int EMX_TAB[2] = { 0x454D5831, EMX_BITS }; // slot 0 magic keeps it out of .bss

// BSB (b1827; Deep spec_bsb_1110, ranked 01boss_battle v SBG, RC CONFIRMED GR:196 + INT:135 + probe p72). Runtime data flag BSB_TAB[1], read
// first; 0 = v705. Bit 1: a gated altar's tile opens once that tile's own camp is seen dead, not the whole group (gate_open, bankable through
// it, bank_gate_walk's open tiles). Bit 2: the gate siege and the gate group's tank bail price the tile camp plus the awake members that reach
// the tile or its path, over kill + walk + tribute turns, not the whole group.
// v711 BSB: baked at its shipped value
#define BSB_BITS 1
inline constexpr int BSB_TAB[2] = { 0x42534231, BSB_BITS }; // slot 0 magic keeps it out of .bss
// CSH (b1807 bug hunt C1/C2, shards_of). Runtime data flag CSH_TAB[1], read first; 0 = v704. Bit 1: a Prism's Focus shards count:
// (Focus - base - 1.5 x bag) / growth (GR:564), the bag only when read this round (mine, or a mate's by sdk_champion_gems), else
// skipped as before. Bit 2: Ryth's Strength shards count: (Strength - base - 1% of bonus health) / growth (GR:496).
// v711 CSH: baked at its shipped value
#define CSH_BITS 3
inline constexpr int CSH_TAB[2] = { 0x43534831, CSH_BITS }; // slot 0 magic keeps it out of .bss

// PEC (b1825, spec_pec_1110, Econ's fuel-floor row): best_group's rating loop cut by the fuel floor with candidates whose bound still
// beats the best found, for a body WITH a target, stores the unrated rest (st_cand) and rates it on the next round from the same tile or
// one step away (no group_bounds, as the target-less stage does); a resumed pick replaces the target only at > PEC_M_X100 / 100 of its
// rate. 0 = nova_base_v702. Bit 1: the resume. Bit 2 (cell, with bit 1): the stored list is cut to the PEC_K best bounds.
#define PEC_BITS 1
#define PEC_M_X100 110
// v706 PEC: PEC bit 1 direct read (owner: all ideas)
#define PEC_K 4
inline constexpr int PEC_TAB[4] = { 0x50454331, PEC_BITS, PEC_M_X100, PEC_K }; // slot 0 magic keeps it out of .bss
#define PEC_CNT(k, c) ((void)0) // fire count: the diag copy records site k when c; release: nothing, c unevaluated

// ECB (b1828, econ capture/bank bug hunt on v706; Rule Checker rows). Runtime data flag ECB_TAB[1], read first; 0 = v706. Bit 1 CUG1:
// an unseen group's gain counts as its capture only after a recall started during this capture (T.cap_on >= 0), not after any recall
// of the game (off the region T.cap_on is -1, so a kill's gold or bag on the walk in was booked as the capture: GR:196, INT:112).
// v711 ECB: baked at its shipped value
#define ECB_BITS 7
inline constexpr int ECB_TAB[2] = { 0x45434231, ECB_BITS }; // slot 0 magic keeps it out of .bss
// ECB bit 2 CRH1: cancel_recall_for_winning_bag with the home altar beside the spawn (ha 0): a kept recall tributes on its landing turn,
// a walk starts it on the arrival turn (INT:125), so cancel when d <= left (was d < left). Bit 4 BTD1: btl_too_late keeps the
// arrival-turn step for a WALK whose length equals the recall time; only the recall-onto-the-altar path skips it (INT:118).
// PTH (nova_b1827_pth): idle walks judge groups by walking distance, not Chebyshev (owner replay 01a1c642, spec_pth_1110). 0 = nova_base_v702.
// Bits: 1 = idle-group pick by walk (no-walk groups skipped), 2 = idle arrival test (> 6) by walk.
// Bit 4 (b1789, PTH's one pre-stated adaptation): the idle pick keeps live's cheb ranking and drops only groups whose walk is UNREACH or
// exceeds cheb + 8 (alone; not with bits 1-2).
// v707 PTH: idle pick skips groups far by walk (PTH adapt)
#define PTH_BITS 4
inline constexpr int PTH_TAB[2] = { 0x50544831, PTH_BITS }; // slot 0 magic keeps it out of .bss
// v701 q4 X92: TMO SRP (the crew-op rate test skips set_target's 1.0 placeholder) baked on.
// Q4B (b1831 bundle): q4r rows behind one data flag for the flag-0 identity: 1 RGF1, 2 SSR1, 4 SRP, 8 WKL1. 0 = v703.
// v708 Q4B: baked at its shipped value
#define Q4B_BITS 15
inline constexpr int Q4B_TAB[2] = { 0x51344231, Q4B_BITS }; // slot 0 magic keeps it out of .bss
// v701 q4 WKL1: foe_banks_winning_bag_first's foe ETA past our lock is walk-1 + max(0, hits-1) + tc (INT:122) baked on.
// BRS7 (b1817, Rule Checker X88). Runtime data flag, read first; 0 = v696. Bit 1: refresh_owned counts a Bruiser emblem (family 6) as
// 7 shards (5 of the stat plus 1 of each other, GR:311), not 5 (own.shards feeds the shop-trip gain, econ_recall_heal.cc).
// v708 BRS7: baked at its shipped value
#define BRS7_BITS 1
inline constexpr int BRS7_TAB[2] = { 0x42525337, BRS7_BITS }; // slot 0 magic keeps it out of .bss
// SIR (b1827 bug hunt SIR1, build_b1827_bughunt.md): support_turn's spell-range branch returned "acted" and reset the idle count on every
// turn, though camp_abilities casts only once per cooldown (GR:262). Runtime data flag SIR_TAB[1], read first; 0 = v704. Bit 1: a turn
// with no cast falls through to try_heal, the idle count (LOOP_FIX) and the threat escape.
// v710 SIR: 3 fixes sir1gt,hfx2s,cbh58
#define SIR_BITS 1
inline constexpr int SIR_TAB[2] = { 0x53495231, SIR_BITS }; // slot 0 magic keeps it out of .bss

// DTH (b1822, Deep spec_dth_1110 from dither_open_1110.md: open-ground dithers are target flips). Three runtime data flags, read first;
// 0 = nova_base_v711.
// RWD bit 1 (verified bug): target_turn_wait_for_respawn's drop banned the group until respawn_at - 20, already past when written, so the
// chooser re-picked it at once; the ban now lasts until the drop's own test would pass (now + left - path_dist - limit, >= now + 1).
#define RWD_BITS 1
inline const volatile int RWD_TAB[2] = { 0x52574431, RWD_BITS }; // slot 0 magic keeps it out of .bss
#define RWD_ON(b) ((RWD_TAB[1] & (b)) != 0)
// JNS bit 1: the no-margin fresh-pick switch (econ_retarget.cc, sw = 1.0) keeps the normal switch factor when a mate's claim on my
// target is newer than my pick or changed within JNS_ROUNDS (a mate just joined me), and I am not engaged or capturing.
#define JNS_BITS 0
#define JNS_ROUNDS 3
inline const volatile int JNS_TAB[3] = { 0x4A4E5331, JNS_BITS, JNS_ROUNDS }; // slot 0 magic keeps it out of .bss
#define JNS_ON(b) ((JNS_TAB[1] & (b)) != 0)
// RTE bit 1: respawn_too_late does not reject my own target when its respawn_at is unchanged since my pick and only my walk estimate got
// shorter (the wait it prices grew only because I came nearer).
#define RTE_BITS 0
inline const volatile int RTE_TAB[2] = { 0x52544531, RTE_BITS }; // slot 0 magic keeps it out of .bss
#define RTE_ON(b) ((RTE_TAB[1] & (b)) != 0)
inline int rte_pick_g = -1, rte_pick_ra = -1, rte_pick_trav = -1; // RTE: my target's respawn_at and walk at the pick
// SGB (Deep 10 Nov, crit 01a1c74d-6593-73a0 W3/W4): bit 1 a big group whose members are all dead (GS_CLEARED, reward waiting) counts as
// nearly dead (rate_for and the filler may take it); bit 2 the target bound keeps a GB_SGB group that is nearly dead (as rate_for does).
// v714 SGB: SGB cleared big group stays a target
#define SGB_BITS 3
inline constexpr int SGB_TAB[2] = { 0x53474231, SGB_BITS };
// VJN (b1822, VV Design spec_vjn_1110): Vesper joins a mates' fight on her holder gain. Runtime data flag VJN_TAB[1], read first;
// 0 = nova_base_v698. Bit 1, Vesper only, rounds <= VJN_END, gold groups: (a) join_gain's "without her" side uses the value of the
// claimant that would hold the capture (cap_rank), the "with her" side her own value when she would rank first, else the same crew
// holder's value (GR:532, 335; interactions.md:113); (b) choose_target runs the join loop also when she has her own best group (healthy, uncommitted, fuel floor) and takes the
// best join whose gain beats her own rate. Bit 2 (with 1, Planner guard): compare with her solo rate (rate_for, no extra) instead.
#define VJN_BITS 1
// v715 VJN: stack package VSP (VJN+VTK+VGT+VCD)
#define VJN_END 150 // last round of the window
inline constexpr int VJN_TAB[3] = { 0x564A4E31, VJN_BITS, VJN_END }; // slot 0 magic keeps it out of .bss
// VTK (spec_vtk_1110.md, owner "we spread our resources too much"): Vesper rates a gold group her mates have cleared or are clearing
// as a take-over trip (rate_for, before the 'a crew mate is capturing it' skip); the mate steps off by the live capture_region_handoff.
// 0 = v707. RC C45/C46 fixes: VTKR1 (bit 4 compares capture ranks), VTKP1 (an allied Capture holder caps the pay window at 3),
// VTKG1 (never leave an awake attacker group I alone engage). Bit 1: a running ally capture in sight she reaches before payment and outranks its holders on, valued at the
// gold she adds over the holder (group_value) per round of walk + countdown. Bit 2 (with 1): valued at the whole group_value. Bit 4
// (with 1): a claimed group she reaches after the crew's clear (estimate_cx) and >= 1 round before payment (clear + 5, 3 with my Capture).
// Bit 16 SHADOW: the take-over rating runs as with bit 1, its result is dropped (rare-lane control twin, VTK_BITS 23).
#define VTK_BITS 7
// v715 VTK: stack package VSP (VJN+VTK+VGT+VCD)
#define VTK_K 100 // VSP dose (b1833): her take-over value x VTK_K / 100 (percent; 100 = as VTK)
inline constexpr int VTK_TAB[3] = { 0x56544B31, VTK_BITS, VTK_K }; // slot 0 magic keeps it out of .bss
// VGT (b1789, spec_vgt_1110 VV Design, owner 9 Nov: too many Greed emblems). 0 = v698. Bit 1: Vesper's own build takes no Greed
// (greed_tail_pass's Skirmish slot as live). Bit 2 (only with bit 1): her Bruiser main entries stay Bruiser (not Power).
// v715 VGT: stack package VSP (VJN+VTK+VGT+VCD)
#define VGT_BITS 3
inline constexpr int VGT_TAB[2] = { 0x56475431, VGT_BITS }; // slot 0 magic keeps it out of .bss
