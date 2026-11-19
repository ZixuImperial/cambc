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

                  // drops to RTS_MARGIN while a shop or heal is due (gold >= RTS_GOLD and shopping allowed, so
                  // the recall that shops/heals anyway replaces the walk when it is no slower; also needs no enemy within RTS_FOE; 0
                  // = off
#define RTS_GOLD 90
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
// XFB (b1867, RC X346/X349/X350 play-identical fuel bundle; one bit per row, the same output by construction, cxeident-proven):
// 1 GSI1 group_static_table: only the analysis key changed (kd 1 -> 2): set the altar-walk part in place, no full rebuild.
// 2 NUB1 build_fields: one scan per call for the nearest unbuilt walk group (same first-lowest-gi pick).
// 4 CTI1 compute_travel_t: group_dist_here through an always-inline copy.
// 8 GFM1 group_field / group_field_ready: dfget_me (the memoised offset of my tile) for the value at my tile.
// 16 SCR2 spawn_crystal_route_on: the spawn tiles' and landings' field offsets kept across calls.
// 32 HS3S the hole-shortcut scan: an interior hole's 8 neighbours read once.
// 64 GBC1 (X355) the bounds pass: emblem gold bonus, Prospector rows and the tribute channel read once per pass; paused() only at gi % 8 == 0.
// 128 SMX4 (X365) no decode of the unread DFG crew bit; 256 SMX5 (X365) no MCL_BIT_GOLDFREE (no reader; logic-identical, draft fuel);
// 512 SMX6 (X365) no c0 count of ETA-0 helpers (never published) in help_post's call.
// 1024 TBG0 (CI Planner: MCL4/tavi_bg dropped): no TAVI_BG bit, so no MCL4 draft byte (store-only; nothing reads it). Flag XFB_BITS, 0 = off.
// v759 XFB: XFB play-identical fuel bundle (11 rows)
#define XFB_BITS 2047
inline constexpr int XFB_TAB[2] = { 0x58464231, XFB_BITS }; // slot 0 magic keeps it out of .bss
// b1968 GBF: logic-identical fuel cuts on the target-choice path (RC X414, X421, X428). Each bit is read before its work; the
// bounds pass reads the word once and runs a template copy of its loop (no per-group flag test). Bits: 1 GBF1 group bounds: `opened`
// read once a pass, the pass-invariant terms (OE crew max, crystal-plan prize, holder gold mult, emblem gold bonus, Marcella gems) as
// cold branches, the MCK light-mid factor as a per-group GBS multiplier (1 when off). 2 GBF2 group bounds: the six vector bases read once
// a pass (only while tf_fast and gt_fast hold: nothing resizes them in the pass), travel and GBS rows by base + stride. 16 TML2
// mate_last_seen_put's math waits for the first read of the slot (tm_m). 64 RTX1 mates_claims_now with the comms state read once,
// claims compared as one word. (4, 8, 32, 128: unused; GBF4, CTF1, BTS1, RTX2 dropped after measurement.) Flag GBF_BITS, 0 = off.
// v775 GBF: GBF choice-path logic-identical fuel cuts
#define GBF_BITS 83
inline constexpr int GBF_TAB[2] = { 0x47424631, GBF_BITS }; // slot 0 magic keeps it out of .bss
#define GBF_WORD() (static_cast<unsigned>(GBF_TAB[1]))
// b2131 GBZ (RC X540, logic-identical): bound-build fuel cuts. The pass reads the word once (all loop bits on: a template copy with no
// per-group flag test). Bits: 1 GPM1 opened/fc_alive tests as per-pass masks on s.fl; 2 GVT1 bk set with ow, exact x mu_g5, eg_min +INF
// when off; 4 GZF1 one ZERO/RGK/SGB test; 8 GTN1 gt_now before gate_done; 16 GPT1 a loop copy for passes with no Marcella, Prism, gv_exact
// or crystal-plan terms; 32 KLX1 the finish kill loop runs only with a kill under 20 rounds old; 64 TFQ1 team_feasible's refresh test
// latches off once a read is <= 60k (fuel falls in a pass). Flag GBZH_BITS, 0 = off.
// b2147 GBZH (Builder 05:49Z, RC class split): GBZ (b2131) only on maps with more than GBZH_G camp groups (draft-time static count); at
// GBZH_G or fewer every bit reads off, so play is v803's.
#define GBZH_BITS 127
// v813 GBZH: GBZ bound cuts on huge maps only (GBZH)
#define GBZH_G 150
inline constexpr int GBZH_TAB[3] = { 0x475A4831, GBZH_BITS, GBZH_G }; // slot 0 magic keeps it out of .bss
// b1990 GBH (RC X457, logic-identical): the bounds pass's per-visit globals read once a pass. Bit 1 GBH1: team_feasible's estimate-round
// reset (tf_est_round/tf_est_n) done once before the loop (nrow is fixed in a pass; every reader resets first). Bit 2 GBH2: the gate test's
// `!M.has_home || GT.round == nrow` latched in a member, re-read after a gates_step (the only writer of GT.round). Flag GBH_BITS, 0 = off.
// v779 GBH: GBH bounds-pass reset and gate latch, identical
#define GBH_BITS 3
inline constexpr int GBH_TAB[2] = { 0x47424831, GBH_BITS }; // slot 0 magic keeps it out of .bss

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
// (econ::go_home). (Bit 2 FIGHT_GATE is gone: v609 stripped its assess() hook, b2391 its dead gate code, RC X818 N1.) Hooks:
// brain_*.cc turn() (note, before early_stages), econ_*.cc bank_winning_bag_slow (after the winning test). 4 = STAKE: the bag's bar rise uses the stake share min(1, bag /
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
// BFE (b2145, RC X555 BFE1, INT:120): bank_first refuses a bag too late to bank (bag_too_late_to_bank), as every other bank()
// caller does. 0 = live. Bit 1: on.
// v803 BFE: end-game r2000 landing tests TDE1 DDL1 BFE1
#define BFE_BITS 1
inline constexpr int BFE_TAB[2] = { 0x42464531, BFE_BITS }; // slot 0 magic keeps it out of .bss
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
// v776 FB6: B2 re-carry OBF+CCX+XFE identical fuel cuts
#define FB6_BITS 122
inline constexpr int FB6_TAB[2] = { 0x46423631, FB6_BITS }; // slot 0 magic keeps it out of .bss
// v8xx CAPM (b2211 rebuild of b1790, CAP bit 1, cap_rulecheck_1110.md): should_capture, capture_region_handoff and mate_holds_region skipped ANY channelling
// mate, so B stepped on while A's recall still stood on the region at payment and both got half (GR:196/:207). A recall lands at the
// owner's turn start (GR:275/:387); payment is at round start (GR:124). Bit 1: a channelling mate counts as off the region only if its
// channel lands before the pay round (landing = now + left + 1 if it already acted; pay = now + the engine's timer while our capture
// runs, else now + pay_d).
// v825 CAPM: channelling mate at pay still counts
#define CAPM_BITS 1
inline constexpr int CAPM_TAB[2] = { 0x4341504D, CAPM_BITS }; // slot 0 magic keeps it out of .bss
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
// v756 CRE: RC X347 VBK1: dormant table baked at its live value 0 (owner 9 Nov bake-older rule)
#define CRE_BITS 0
inline constexpr int CRE_TAB[2] = { 0x43524531, CRE_BITS }; // slot 0 magic keeps it out of .bss
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
// v756 AHX: RC X347 VBK1: dormant table baked at its live value 0 (owner 9 Nov bake-older rule)
#define AHX_BITS 0
inline constexpr int AHX_TAB[2] = { 0x41485831, AHX_BITS }; // slot 0 magic keeps it out of .bss
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
// v713 RWD: respawn-drop ban lasts until the wait test (RWD1; added by hand 11 Nov: missed by shipbake
#define RWD_BITS 1
inline constexpr int RWD_TAB[2] = { 0x52574431, RWD_BITS }; // slot 0 magic keeps it out of .bss
// JNS bit 1: the no-margin fresh-pick switch (econ_retarget.cc, sw = 1.0) keeps the normal switch factor when a mate's claim on my
// target is newer than my pick or changed within JNS_ROUNDS (a mate just joined me), and I am not engaged or capturing.
#define JNS_BITS 0
// v756 JNS: RC X347 VBK1: dormant table baked at its live value 0 (owner 9 Nov bake-older rule)
#define JNS_ROUNDS 3
inline constexpr int JNS_TAB[3] = { 0x4A4E5331, JNS_BITS, JNS_ROUNDS }; // slot 0 magic keeps it out of .bss
// RTE bit 1: respawn_too_late does not reject my own target when its respawn_at is unchanged since my pick and only my walk estimate got
// shorter (the wait it prices grew only because I came nearer).
// v807 RTE: RTE at live's value 0 (RC X593: RTE CLOSED 11 Nov)
// v896 NTG: 7 verified bug fixes (TTCX TDP EAF OLK RFV NTG CHO)
#define NTG_BITS 1
inline constexpr int NTG_TAB[2] = { 0x4E544731, NTG_BITS }; // slot 0 magic keeps it out of .bss
// NTG bit 1 (b2143): the starved-choice streak counts rounds, not calls (farm_turn's second target_turn call reset it every round)
#define RTE_BITS 0
inline constexpr int RTE_TAB[2] = { 0x52544531, RTE_BITS }; // slot 0 magic keeps it out of .bss
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
// HPG (b1807, owner replay 01a1c7b9 "use teleport crystals, generalise"; analysts/owner_01a1c7b9_crystal_1110.md s6). Runtime data
// flag HPG_TAB[1], read first; 0 = v717. Bit 1 CROSS: a dasher holding a crystal whose target has no walk (the dash route) casts at the
// legal landing within 3 from which the group walks, when 3 + that walk + HPG_SMIN <= the dash route (approach_group never priced a hop
// for a dash-reachable group). Bit 2 BUY: on the spawn, a dasher whose target has no walk buys a crystal (with bit 1). Bit 8 SAFE: no
// cast with a seen foe within HPG_FOE of me or the landing, on a contested landing (cdx_hot_landing), or carrying >= HPG_BAG gems (a
// sealed island's only exit is a recall). Bits 4 / 16: not built.
// v751 HPG: crystal hop field v built dash route (01a1c7b9)
#define HPG_BITS 11
inline constexpr int HPG_TAB[2] = { 0x48504731, HPG_BITS }; // slot 0 magic keeps it out of .bss
#define HPG_SMIN 8
#define HPG_FOE 4
#define HPG_BAG 50
#define HPG_SCAN_FUEL 60000 // HPG bit 1 v2: the launch scan pauses below this fuel and resumes next turn (fuel adaptation b1821: was 30000; the turn's tail ran dry)
// HPG bit 1 v2 (b1807, 11 Nov): a one-hop launch field per group no walk reaches (hpg_launch, econ_crystal_mid_hops.cc): prices those
// groups for a crystal holder (or on the spawn with 10 gold, bit 2) and walks the holder to a launch more than 3 away.
// HPG bit 16 RETURN (b1807, 11 Nov): a bank trip with a crystal walks the one-hop bank field (hpg_bank_field) to a launch and casts when
// it beats the walk by HPG_SMIN (bit 8 SAFE on the cast).

// CSW (b1839, RC X237 CSW1, x237_mixed_fields.md): the spawn crystal's landing list is built on the camps-OPEN spawn walk (f_home), so a
// tile just past a camp wall reads near and is dropped, while the routes are priced on camps-blocked fields: the crystal never hops a
// camp wall. Runtime data flag CSW_TAB[1], read first; 0 = off. Bit 1: stage 0 exports the camps-blocked spawn field
// (mv::home_field_cb, built here when fuel allows), else f_home as before.
// v718 CSW: 2 fixes csw1si,fwb1si
#define CSW_BITS 1
inline constexpr int CSW_TAB[2] = { 0x43535731, CSW_BITS }; // slot 0 magic keeps it out of .bss
// ISL (b1827; RC X216 island/moat bundle, owner pathfinding + map types). Runtime data flag ISL_TAB[1], read first; 0 = v711. One bit a row.
// Bit 1 DRT1: a group with no standable neighbour (one camp ringed by holes) takes its own camp tiles as dashnav roots (a dead camp tile is a
// legal landing, GR:161; capture stands on it, GR:196). Bit 2 CDH1: the capture walk onto a dead group that walking cannot reach dashes onto a
// free member tile within 2 (dash_legal_between) instead of waiting on the shore. Bit 4 CPT1: crystal_plan takes the group's own (dead) camp
// tiles as landings (GR:159/161; crystal_step re-tests the tile free). Bit 8 TWB1 (RC X219, identical): the thin-hole window BFS stops at
// walk - HOLE_SHORT_GAIN - the nearest landing walk. Bit 16 TWC1 (with bit 8): the plan's fuel bar is (min(walk, 4R) + 16) x chunks + CDW_FUEL.
// Bit 32 STB1 (RC X226, bug bar): want_bank prices a walled-in carrier's bank as recall + home-altar walk instead of returning false.
// Bit 64 NWB1 (RC X228, bug bar): bank_dist_here reads bank_field() (M.f_altar) on nwc maps instead of UNREACH (no walk to an altar).
// Bit 128 RBW1 (RC X219, behaviour, ring maps): a breach turn whose built f_breach reads beyond step_to_set's radius walks the field without
// the failing step_to_set(40) first. Bit 256 MSK1 (RC X231, with CPT1): at the crystal launch, a ranged body whose landing is a living member
// tile fights it from there and holds; the hop goes once the tile is dead and free. Bit 512 RG3C (RC X234, with NWB1): add_altar_side_landings
// filters altar landings with the camps-blocked spawn field (M.ring_fo), not M.f_home, so a 2-deep camp plug leaves a crystal bank route.
// v726 ISL: nwc bank field + plug-side crystal landings
#define ISL_BITS 576
inline constexpr int ISL_TAB[2] = { 0x49534C31, ISL_BITS }; // slot 0 magic keeps it out of .bss
// WIC (b1827; RC X220 WIC1, w_revolving/w_campring/w_deadend/w_choke). Runtime data flag WIC_TAB[1], read first; 0 = v710. walled_in/stranded
// read M.f_home, which lets living camps pass, so a body shut in by a respawned door camp loops on the gate redirect's drop_target(30) and
// never recalls (its bag never banks). Bit 1: when the camps-blocked home field reads UNREACH here, the camps-open one does not, and the gate
// redirect just failed (no crew can clear the door), recall (the respawned door sleeps: GR:192). Composes with RC5 RLG1/2 (a refused recall).
// v807 WIC: WIC at live's value 0 (RC X593: no line, no waiting marker)
#define WIC_BITS 0
inline constexpr int WIC_TAB[2] = { 0x57494331, WIC_BITS }; // slot 0 magic keeps it out of .bss
// RGF (b1939, static_rules_audit_1111 Step 0 #5): play-identical cleanups of round gates that never decided a turn (0 of 300 fresh
// team-games). Runtime data flag RGF_TAB[1], read first; 0 = v762. Bit 1: the opening test of retarget_fuel_short drops now() < 30;
// 2: hoard_crew_reopen drops now() < 30; 4: an unfinished hoard decision always continues (no HR_LATE_END); 8: buy_crystal drops r < 20.
// v629 RGF: dash, lock, reset, refund, race consistency
#define RGF_BITS 0
inline constexpr int RGF_TAB[2] = { 0x52474631, RGF_BITS }; // slot 0 magic keeps it out of .bss
// RSF (b1939, static_rules_audit_1111 Step 0 #5): game state replaces a round gate that decided turns. Runtime data flag RSF_TAB[1],
// read first; 0 = v762. Bit 1 OEG: a non-tank elk-opening member self-starts on tank state alone (no OEG_OPEN_R). 2 SQF: a squad pull
// waits until every live slot has published a claim (no SQ_FORM_FROM). 4 LSG: low_score_game on the 200-round pace test alone (no r1000).
// (bit 4 rebuilt: Variant B, see lsg_state_form; bit 64: Variant A, used only when bit 4 is off.) 8 IDL: no idle walk while the opening simulation is pending, any round. 16 OPX: a pending opening simulation is dropped when it
// made no progress since the last check (or a foe is within 8), not at OPX_ROUND. 32 OPD: the travel dash hold lasts while hs3 is pending.
// v764 RSF: OEG elk self-start on tank state, no r30
#define RSF_BITS 1
inline constexpr int RSF_TAB[2] = { 0x52534631, RSF_BITS }; // slot 0 magic keeps it out of .bss

// CPS2 (VBB bit 8, b1836 verified bug, RC C98; single-bit line after vbb1 closed, b1851): capture_pay_in is -1 when the engine reads
// the region paid (no capture available, state 0) or held by the enemy (state 3), from the same single capture-state read.
// Runtime data flag CPS_TAB[1], read first; 0 = off.
// v731 CPS: capture_pay_in -1 when engine says paid/foe (CPS2)
#define CPS_BITS 1
inline constexpr int CPS_TAB[2] = { 0x43505332, CPS_BITS }; // slot 0 magic keeps it out of .bss
// DFG (b1853, spec_dfg_1111, Shared Mem): the draft runs the opening simulation for its planned lineup (map-only inputs, spare 10M-turn
// fuel) and stores each body's first group + crew bit (dmem extra 8, overflow extra 6). Runtime data flag DFG_TAB[1], read first; 0 = off.
// Bit 1 GOAL: the record replaces the start goal on the opening steps and is the first opening pick (no in-play simulation); used once,
// until my first camp hit, an enemy in sight, the group respawning, or a retarget. Bit 2 EARLY: in the opening's pre-turn steps a body
// with a record hits a camp of its group in reach, or travel-dashes toward it (Combat's guard: never C&I or Prism; landing no nearer the
// foe spawn than my spawn tile and in our half or by the goal; 40k reserve). Bit 4 HOLD: while the record stands, the no-crew drop, the
// switch margin and Prism's plan-group follow do not move me off it. Writes happen only while DFG_BITS != 0.
// v735 DFG: DFG draft opening record + r1 acts (dfg3)
#define DFG_BITS 3
inline constexpr int DFG_TAB[2] = { 0x44464731, DFG_BITS }; // slot 0 magic keeps it out of .bss

// GNK (b1848, Deep spec_gnk_1111; owner replay 01a1c7cc). 0 = v732. Bit 1 (bug A): recruit()'s loop counted nfree from free_near()
// (econ_team_model.cc:460, which adds crew_bypass::count() for any group) while pass 0 takes a bypass mate only when crew_bypass::ok(s, gi)
// holds, so the loop broke at r = 1 and never tried recruits; with the bit, nfree is size_crew's real pass-0 count (RC C119 form). Bit 2 (keep) closed at
// Step 0 (c1 .03/g).
// v736 GNK: recruit loop counts the real pass-0 crew (GNK)
#define GNK_BITS 1

// PRE (b1844, RC X322 PRE1; identical): each body's first camp turn sized the living-attacker and camp-focus tables lazily (~14k instead of
// ~1.2k), on the group_bounds peak turns. Runtime data flag PRE_TAB[1], read at its one call site; 0 = live. Bit 1: econ::pre_tables(),
// called once from background_work before build_bg, sizes them with the same size tests and initial values, so the lazy builders find
// them ready.
// Bit 2 PRE2 (RC X329, PRE's one adaptation): also at the top of background_work, before the map-init chain, once the groups are
// built (ST_GROUPS) and fuel > MAP_INIT_FUEL: bodies camp before the map stages finish (pre1 ran after M.done, so the lazy sizing
// still came first in 390 of 429 cases).
// v739 PRE: camp-turn tables sized before map stages (PRE2)
#define PRE_BITS 3
inline constexpr int PRE_TAB[2] = { 0x50524531, PRE_BITS }; // slot 0 magic keeps it out of .bss
inline constexpr int GNK_TAB[2] = { 0x474E4B31, GNK_BITS }; // slot 0 magic keeps it out of .bss
// VB3 (b1828, MINOR bundle VBB3). Runtime data flag VB3_TAB[1], read first; 0 = v735. Bit 1 XRS1 (RC X333): the siege ratio skips a foe
// by intel's alive bit, not a 60-round window from the round we first saw it dead (a foe seen dead at D+1 is back at D+60, GR:375).
// Bit 2 IRP1 (RC X336): a foe first seen after a mid-turn re-perceive is noted at end_turn (sighting, bag and own tables), as begin_turn
// notes its sightings (GR:351). Census (full games): EGW1/EGW2/EGW3 (X331), XRS2, IRO1 and XSP1 never fired and are not built.
// v740 VB3: siege ratio uses the foe alive bit (XRS1)
#define VB3_BITS 1
inline constexpr int VB3_TAB[2] = { 0x56423331, VB3_BITS }; // slot 0 magic keeps it out of .bss
#define VB3_CNT(k, c) ((void)0) // fire count: the diag copy records site k when c; release: nothing, c unevaluated
// bk5 HFB (was HFT, renamed b1827: b1835 parks an HFT line; b1462; bank bk5b hand rebase onto v708; bit 4 RTSH only): the travel recall's shop/heal margin counts a heal below
// HFB_RTSHP % instead of RTS_HP100, so a trip home on the way heals sooner. Runtime data flag, read first; 0 = off.
#define HFB_BITS 4
// v745 HFB: fpb5 bank bundle bk5b+ehc3s+rts
#define HFB_RTSHP 90
inline constexpr int HFB_TAB[3] = { 0x48464231, HFB_BITS, HFB_RTSHP }; // slot 0 magic keeps it out of .bss
constexpr int HFB_BIT_RTSH = 4;
// bk5 VDB (b1481 KT_VD_BANK; bank bk5b): Vendetta's want_bank bar x VD_BANK / 100, after the threat term. Runtime data flag, read first; 0 = off.
#define VD_BANK 130
// v745 VDB: fpb5 bank bundle bk5b+ehc3s+rts
inline constexpr int VDB_TAB[2] = { 0x56444231, VD_BANK }; // slot 0 magic keeps it out of .bss
// RTS (b1525, bank rts hand rebase onto v708; Econ, owner replay 01a1b7d8 r9 Vendetta idle): tt_choose's low-fuel cheap step needs the
// target's cached group field, which a NEW target does not have yet, so the retarget turn ended with no step. Runtime data flag, read
// first; 0 = off. Bit 1: the low-fuel choice turn with no field takes one greedy step to the anchor (as SG3). Bit 8: approach_group
// with no field: when step_to's short search finds no step, a greedy step (fuel() >= RTS_F2) that strictly closes on the anchor and is
// not last turn's tile (mv::step_greedy_fresh), else stand.
#define RTS_BITS 9
// v745 RTS: fpb5 bank bundle bk5b+ehc3s+rts
#define RTS_F2 6000
inline constexpr int RTS_TAB[2] = { 0x52545331, RTS_BITS }; // slot 0 magic keeps it out of .bss

// ROB2 (b1813 -> b1862, Combat spec_rob_1111 ROB2; b1836's identity finding: the LOW branch is exempt from the enemy_close guard;
// 00the_line 01a1c8e2-70c6 r43). Runtime data flag ROB2_TAB[1], read first; 0 = live. recall_safe refuses, whichever branch (out or
// low) passed, when no foe is visible and enemy_close is <= 4 rounds old (bit 1) or <= 2 rounds old (bit 2). b1813's bit 4
// (remembered-foe reach) is dropped: .4708 with deaths +.70 z+3.2.
// v748 ROB2: no recall within 2 rounds of contact (ROB2)
#define ROB2_BITS 2
inline constexpr int ROB2_TAB[2] = { 0x524F4232, ROB2_BITS }; // slot 0 magic keeps it out of .bss

// WFB (spec_wfb_1111, 04yin_yang v NTU 01a1cb48-a438): 0 = nova_b12374_xfb2047. Bits: 1 = finish bank past a stale capture flag; 2 = no farm crystal hop for 10 rounds after a finish bank. 8 = Prism bank branch skips a stale capture flag too. X383: 16 WFT1 every want_bank rule past a paid capture; 32 HLR1 heal recall; 64 LHC1 low-HP escape; 128 SHR1 shop recall; 256 DBK1 dash bank; 512 BFC1 bank_first; 2048 SWD2 travel dash; 4096 WFS1 settle a stale paid capture the turn after the payout (RC C348; required with 1-512).
// v763 WFB: baked at its shipped value
#define WFB_BITS 4097
inline constexpr int WFB_TAB[2] = { 0x57464231, WFB_BITS }; // slot 0 magic keeps it out of .bss
#define WFB_ON(b) ((WFB_TAB[1] & (b)) != 0)
// ECX (b1945 from RC X394: econ fuel, play-identical cuts only). Runtime data flag ECX_TAB[1], read first; 0 = v763.
// Bit 1 TML: build_team defers each member's member_put until a reader first takes TM.m[s] (tm_m); unread members cost nothing.
// v768 ECX: TML defers member_put to first read
#define ECX_BITS 1
inline constexpr int ECX_TAB[2] = { 0x45435831, ECX_BITS }; // slot 0 magic keeps it out of .bss
#define ECX_TM(s) tm_m(s) // TML readers of TM.m[s]: the member, built on first read (at ECX 0 nothing is pending: TM.m[s] as before)
// DPX (b1971, spec_dpx_1111.md, Path Finding from Deep's ambush764 walk; RC C395): a dash pocket (no walk home) is LEFT BY A DASH, not a
// recall. Runtime data flag DPX_TAB[1], read first; 0 = off. Bit 1 DPX1 DASH OUT: at the stranded recall starts (econ_idle walled_in and
// stranded, approach_group's blocked launch, the bank walk) a dasher dashes to a legal landing that walks home (nearest the next goal's
// field, else home); with a landing in reach it holds up to DPX_WAIT rounds for its cooldown; with none it walks back (<= 12 tiles) to
// the landing of its last route dash; no foe within DPX_FOE_R. The recall stays the fallback.
#define DPX_BITS 1
#define DPX_WAIT 3
// v772 DPX: DPX1 leave dash pockets by dash, not recall
#define DPX_FOE_R 6
inline constexpr int DPX_TAB[4] = { 0x44505831, DPX_BITS, DPX_WAIT, DPX_FOE_R }; // slot 0 magic keeps it out of .bss

// BLX (b1974, RC X422 BLX1 / C394): the camp bail line. Camps hit at round start, before any champion moves (GR:124), so bailing now
// costs steps - 1 hits and one more turn costs one more: the last-safe line is hits x steps + 8%; live charges steps + 1.5.
// 0 = nova_base_v769. Bit 1: tank_bail_out / camp_holder_bail bar at steps + BLX_M10/10.
// Bit 2: inside the band the new line keeps but live's would bail, price the true walk (mv::safe_tile_walk_steps, every kit).
// Bit 4: the same line in rotate_camps_to_mate, crew_mates_in_reach and crew_bail (mates at steps + BLX_M10/10).
#define BLX_BITS 7
// v774 BLX: BLX1 camp bail line at true hits, no margin
#define BLX_M10 0
inline constexpr int BLX_TAB[3] = { 0x424C5831, BLX_BITS, BLX_M10 }; // slot 0 magic keeps it out of .bss
// LAH (b1994, sharedmem/lookahead_1112.md; owner: decide the next camp before the current one pays, in spare fuel): on many-group maps
// (MCL3 bit 128 MANYGRP = M.ng >= LAH_NG, decided at the draft and stored in draft memory) the next target choice runs during the
// capture stand. Runtime data flag LAH_TAB[1], read first; 0 = v772. Bit 1: on stand turns, after capture(), best_group's bounds, rating
// loop and linear pick run resumably over the stand turns (own group out; every step only while the turn keeps LAH_FLOOR = the
// PLAN_EVAL_FLOOR level); a finished pick is stored and the next stand turn starts a fresher one. The payout turn (same tile) re-rates the stored
// pick and takes it when it keeps LAH_KEEP % of its stored rate; otherwise today's choice runs.
#define LAH_BITS 1
#define LAH_NG 35
#define LAH_FLOOR 32000
// v783 LAH: swept v783: shipped value with no ledger record
#define LAH_KEEP 70
// b2056 DTR (RC X490, death and respawn bugs; GR:131, GR:375). Runtime data flag DTR_TAB[1], read first; 0 = v783. Bit 1 DT1R:
// busy_with_group is false while dead (a dead body applies mates' cleared/taken/timer news about its target). Bit 2 RS1R: death_reset
// drops my siege operation (plain reset, no siege_end ban). Bit 4 RS2R: claim_target posts -1 after a death until the re-rate runs.
// Bit 8 QBR1: qbr_unseen_bag drops a bag read QBR_AGE rounds ago (>=). Flag DTR_BITS, 0 = off.
// v787 DTR: DTR dead news, siege, claim, qbr age
#define DTR_BITS 15
inline constexpr int DTR_TAB[2] = { 0x44545231, DTR_BITS }; // slot 0 magic keeps it out of .bss
inline bool dtr_rsp = false; // DTR bit 4: dead since the last re-rate
inline constexpr int LAH_TAB[5] = { 0x4C414831, LAH_BITS, LAH_NG, LAH_FLOOR, LAH_KEEP }; // slot 0 magic keeps it out of .bss

// TRF (b2050, RC X488): bank path rows. 0 = v782.
// Bit 1 TRF1: a non-Prism carrier whose 60+ non-winning bag tribute_start_allowed refuses (a foe known within TG_R) gets the pcf hold
// (pcf_ref = round; brain_turn want_bank sets W.no_move while no foe has me in reach), so the farm stage no longer walks it off the
// altar for bank_i to walk back next turn (diag: .38 such turns/g on fresh maps).
// Bit 2 SRL2: bank_i's lock hit takes the last refused altar (srl_lkt) first when it stands in reach, so the LKT1 retry tests the altar
// whose lock was hit (lock_hit_slow otherwise hits the first enemy-locked altar in list order).
// Bit 4 PHW1: bank() run before want_bank this turn (bank_winning_bag's late path) reads no stale pc_hold_why from an earlier turn.
// v784 TRF: SRL2 lock hit on refused altar, PHW1 stale hold why
#define TRF_BITS 6
inline constexpr int TRF_TAB[2] = { 0x54524631, TRF_BITS }; // slot 0 magic keeps it out of .bss
// OCR (b2063, RC C458 on owner replay 01a1c85c; bug bar). Runtime data flag OCR_TAB[1], read first; 0 = v783. Bit 1 (2a): the
// siege rally walk keeps going while its own rally-field distance falls each step (it skips the path_dist bar the approach shares,
// so the two no longer alternate 13/14). Bit 2 (3): a heal go_home on a mate's live capture region (not my target) steps off the
// region first and recalls next turn (GR:196: a body on the region at payout shares it).
// v788 OCR: OCR rally latch + heal step-off
#define OCR_BITS 3
inline constexpr int OCR_TAB[2] = { 0x4F435231, OCR_BITS }; // slot 0 magic keeps it out of .bss

// FRS (b2070, RC X504 FRB1, C488): tank focus-reach blocks. 0 = v789.
// Bit 1 FRS1: the focus-reach block keeps up to 4 blocked camps (each its own FR_BLOCK clock) instead of one scalar, so blocking camp B
// no longer un-blocks camp A (two unreachable camps took turns every FR_TURNS; diag .063 A-B-A blocks/g on fresh maps).
// Bit 2 FRS2 (with bit 1): when the focus and at least one other visible member are blocked and no unblocked visible member is left, drop
// the target, banned until the group's last block expires (at least 20 rounds).
// v791 FRS: FRS stall-net fixes A+B
#define FRS_BITS 3
inline constexpr int FRS_TAB[2] = { 0x46525331, FRS_BITS }; // slot 0 magic keeps it out of .bss
// TVM (b2093; RC X522 TVM1): logic-identical fuel cut. Runtime data flag TVM_TAB[1], read first; 0 = v789. Bit 1: compute_travel keeps the raw
// walk value of each walkable group (the field read, table row, deferred estimate or Chebyshev fallback, before spawn-crystal pricing) and
// reuses them while my tile, the walk inputs' generation (group field builds, field list resize, travel-table closure updates), W.alive,
// the stored-travel state (xtt.v, table pointer), M.ng and M.has_home are unchanged. Teleport groups, spawn-crystal pricing and the dash
// part are recomputed on a reuse; travel_round/from are stamped as before.
// v793 TVM: TVM1 identical compute_travel memo
#define TVM_BITS 1
inline constexpr int TVM_TAB[2] = { 0x54564D31, TVM_BITS }; // slot 0 magic keeps it out of .bss
namespace nova { inline int tvm_gen = 0; } // TVM bit 1: bumped wherever a walk input of compute_travel changes

// RCQ (b2113, RC x529 DRL1 + bot_errors 554): 0 = v792. Bit 2: go_home's carry recall waits out the round of my own recall_doomed
// cancel and refuses while a foe can hit me next turn (any hit cancels a recall, GR:275): ends the cancel-restart loop. Bit 1 unused
// (RHW1's home_dist() > CSX_RCT() gate only delayed the recall-hop on both puppets; not built).
// v794 RCQ: no carry recall restart after doom cancel
#define RCQ_BITS 2
inline constexpr int RCQ_TAB[2] = { 0x52435131, RCQ_BITS }; // slot 0 magic keeps it out of .bss
// SGX (b2068, RC X501/C482): siege rows. Runtime data flag SGX_TAB[1], read first; 0 = v786.
// Bit 2 SFC1: siege_present_count (unengaged start count) counts a seen mate in the operation (claim memory) that posts a fight code
// (ckind 4, not retreating) and so no group.
// Bit 4 SNO1: siege_running_group skips a mate's operation on a nearly dead group (big_group_nearly_dead): no call block, follow or join.
// v795 SGX: SGX crew count + dying group (bar .4975)
#define SGX_BITS 6
inline constexpr int SGX_TAB[2] = { 0x53475831, SGX_BITS }; // slot 0 magic keeps it out of .bss
// GHL (b2086, RC X419 GHP1 alone, GHX chain adaptation): a partial sighting stores min(read, remembered) HP of a living group at both
// hp_left writers (econ_observe.cc). 0 = nova_b12603_wcb3. Bit 1 only.
// v797 GHL: GHL1 partial sighting keeps group HP (.4975)
#define GHL_BITS 1
inline constexpr int GHL_TAB[2] = { 0x47484C31, GHL_BITS }; // slot 0 magic keeps it out of .bss
// GTB (b2116, RC X531/X538): checker_big cut-offs, logic-identical. Bit 1 GTB1: each body's first full group_static_table build runs in
// background spare fuel once its key is final (map done, no ring/open work left), priced before it starts, so the decision turn finds it
// ready. 0 = v793.
// v798 GTB: BCP1 setup rank sort + GTB1 bg table
#define GTB_BITS 1
inline constexpr int GTB_TAB[2] = { 0x47544231, GTB_BITS }; // slot 0 magic keeps it out of .bss
// HTK (b2147, RC C530; Deep hms_prechoice): my own target-less choice on maps with more than HTK_G camp groups (draft-time static
// count). Flag read first; 0 = v800. Bit 2 HTK2: on a safe standing turn (no foe in sight, no damage in 2 rounds, no camp threat, not on
// a camp tile, not a dash-stun kit) the bounds slice pauses at HTK_SLICE instead of TCF_GBFLOOR. (Bit 1 HTK1 top-K sort: killed at Step 0.)
#define HTK_BITS 2
#define HTK_G 150
// v806 HTK: HTK2 hms slice floor 24k on safe standing target-less turns
#define HTK_SLICE 24000
inline constexpr int HTK_TAB[4] = { 0x48544B31, HTK_BITS, HTK_G, HTK_SLICE }; // slot 0 magic keeps it out of .bss
inline bool htk_low = false; // HTK2: this pass (set around best_group's own group_bounds call)
// b2157 DDT (RC X495 dead-turn rows, b2056 DTR2 re-carried on v802 as its own flag; RC C460c CORRECT on the logic). Bit 1 DTP1:
// group_is_ours_to_post needs W.alive for my own target. Bit 2 DTM1: a dead turn forgets last_pos (the respawn jump is no step-back).
// Bit 4 DTF1: build_fields orders unbuilt fields from M.home_anchor while dead. Bit 8 DTH1: the dead background shortcut scan skips
// the kept pre-death target.
// v808 DDT: DTR2 dead-turn post, step, fields, scan
#define DDT_BITS 15
inline constexpr int DDT_TAB[2] = { 0x44445431, DDT_BITS }; // slot 0 magic keeps it out of .bss

// NSG (b2154; Deep spec_nsg_1112, RC C581 DEFECT by intent: an orphaned exclusion). heavy_multi_trip_ok's "not next to our spawn" term
// handed those groups to b746's spawn-farm case, which closed before it shipped; today's spawn siege takes monoliths only, so no path
// takes a golem or elk group beside our spawn. Bit 1: for a heavy NON-monolith group, own side or middle, within reach + 3 of our spawn,
// on a map whose open gem share (from M, a static per-group test at init, not siege_map()) is >= .15, the term is dropped; at d_home <= 5
// a further trip is priced as the walk (2 x d_home turns, healed at the spawn turn's end, GR:153/385; a recall in an awake golem's range
// is cancelled by its first hit, GR:387) with each trip's budget = budget - str_sum x 2 x (d_home - 1). 0 = v804.
// v814 NSG: heavy near-spawn trips not orphaned (NSG)
#define NSG_BITS 1
inline constexpr int NSG_TAB[2] = { 0x4E534731, NSG_BITS }; // slot 0 magic keeps it out of .bss
// b2169 SVR (RC C606, was EGR1): a same-code re-post whose word would not change (cmp_ent == v) takes the other entry when it is empty
// or stood 2+ rounds, else is not posted (bh64_lp_drop / false, the retry lands at an odd gap). Bit 1 HELP + FIGHT, bit 2 ENEMY news.
// v817 SVR: same-word HELP/FIGHT re-post not lost (SVR)
#define SVR_BITS 1
inline constexpr int SVR_TAB[2] = { 0x53565231, SVR_BITS }; // slot 0 magic keeps it out of .bss
// CALX (b1771, spec_calx_1109): CAL beyond own-half monolith/golem. estimate()'s camp damage x CALX_X100 / 100 where our bodies take
// about that share of the modelled damage (b1771 census: own-half elk .60-.62, mid elk .56-.57, mid golem/monolith .49-.53). Runtime
// data flag CALX_TAB[1], read first; 0 = off. Bit 8 ELK: own-half elk groups (no golem/monolith, contest <= .45). Bit 16 MID: heavy
// groups in the middle band (contest .45-.70).
#define CALX_BITS 8
// v819 CALX: own-half elk camp damage estimate x.55 (retest)
#define CALX_X100 55
inline constexpr int CALX_TAB[3] = { 0x43414C58, CALX_BITS, CALX_X100 }; // slot 0 magic keeps it out of .bss

// b2189 RGE (economy bugs, bot_errors 259-263, RC C629; bug bar). Bit 32 the altar-hold note runs below the 300 exit (true baselines);
// 128 reading an enemy lock keeps my recall spin; 256 a landed tribute (gap < 60, team total up by the bag) is not a lost bag.
// v820 RGE: LKB recall spin, flee stand-down, RGE bag/base
#define RGE_BITS 416
inline constexpr int RGE_TAB[2] = { 0x52474531, RGE_BITS }; // slot 0 magic keeps it out of .bss

// b2189 CFQ (RC X615 CFQ1): bit 1 camp_reach_flee_tile takes camp_out's b957 stand-down (last turn's walk home into a spawn under awake reach).
// v820 CFQ: LKB recall spin, flee stand-down, RGE bag/base
#define CFQ_BITS 1
inline constexpr int CFQ_TAB[2] = { 0x43465131, CFQ_BITS }; // slot 0 magic keeps it out of .bss
// PYB (b2191, spec_pyb_1112, RC C627 PTS1): on a capture's payout turn the stale T.capturing kept want_bank refusing, then farm_turn
// re-chose at once. Bit 1: when the old target paid this turn (GS_RESPAWN, respawn_at = now + respawn), farm_turn's retry asks
// want_bank first and runs the bank errand when it says yes, before re-choosing. Runtime data flag PYB_TAB[1], read first; 0 = off.
// v821 PYB: bank on the payout turn instead of retrying
#define PYB_BITS 1
inline constexpr int PYB_TAB[2] = { 0x50594231, PYB_BITS }; // slot 0 magic keeps it out of .bss
// SBB (b2193, BB8 STALE-OPEN rows, docs/bot_errors.md): one runtime data flag per verified bug, read first; 0 = v820.
// BWDM row 462: best_within rates each group in my mode (rate_for<DM>, not rate_for<0>).
// v822 BWDM: stale rows 462/506/507/541/643 (SBB)
#define BWDM_BITS 1
inline constexpr int BWDM_TAB[2] = { 0x4257444D, BWDM_BITS }; // slot 0 magic keeps it out of .bss
// SFTD row 506: the siege follow branch clears SGO; a join that does not take drops the old target (as siege_end does).
// v822 SFTD: stale rows 462/506/507/541/643 (SBB)
#define SFTD_BITS 1
inline constexpr int SFTD_TAB[2] = { 0x53465444, SFTD_BITS }; // slot 0 magic keeps it out of .bss

// LTP (X680 LTP1): legacy TAKEN/CLEARED news is written at priority 20 but readers score it 40 when a mate claims its group
// (team_mem_priority_of_entry). 0 = nova_base_v825. Bit 1: the writer uses the same mate-claim test (priority 40).
// v828 LTP: LTP1 TAKEN/CLEARED priority write = score (RC C730)
#define LTP_BITS 1
inline constexpr int LTP_TAB[2] = { 0x4C545031, LTP_BITS }; // slot 0 magic keeps it out of .bss

// JKC (b2088, JKP centre reopen on w_jackpot2; PF flips on owner replay 01a1cccf): take the jackpot centre. 0 = v789. Class decided at draft
// from map features (jkc_class_group(), plan_map_classes.cc) and stored as MCL4 bit 128; in play jkc_group() is the largest group by gems
// on a map with that bit (missing = off). Every bit acts only on that group.
// Bit 1 (PF i-b): a mate whose siege ETA to it is 61-95 still counts as free crew (SG_ETA_MAX 60 elsewhere).
// Bit 2 (PF vi): its call and start gates take the estimate's multi-trip plan (no one-trip margin) and SG_TMAX does not cap its clear.
// v830 JKC: JKC jackpot centre ETA 95 + multi-trip
#define JKC_BITS 3
inline constexpr int JKC_TAB[2] = { 0x4A4B4331, JKC_BITS }; // slot 0 magic keeps it out of .bss
#define JKC_ETA 95
// b2192 SKS (bot_errors 422: the old Skirmish swap is skipped; EMD bit 1's CAND loop ranks Skirmish). Bit 1. 0 = v819.
// v831 SKS: SKS stale row 1/g fix
#define SKS_BITS 1
// b2313 CRS (RC C778 on spec_gtc_1112 bit 4, bug bar; CRE1's evaluator defect). Runtime data flag, read first; 0 = v831. Bit 1: cap_rank's
// C&I terms read the RANKED slot's kit, never the evaluator's (CI2_FARM reads W.me): on a gold-only group (gold > 0, gems 0) a C&I slot
// ranks + CI_CAP_PEN + gold / 2 on every body, elsewhere work_rank on every body, so both bodies rank alike and a gold capture stops
// splitting. Bit 2: no +10 per shard term on a gold-only group (the shard term outlasted the fading kit terms: gold to the poorer body).
// v838 CRS: CRS carry claims shared gold (owner) near-miss
#define CRS_BITS 3
inline constexpr int CRS_TAB[2] = { 0x43525331, CRS_BITS }; // slot 0 magic keeps it out of .bss
#define CRS_GOLD_ONLY(g) ((g).gold > 0 && (g).gems == 0)
inline constexpr int SKS_TAB[2] = { 0x534B5331, SKS_BITS }; // slot 0 magic keeps it out of .bss
// VKD (RC X348-1, b1867): VCD's clearing dash may land on the tile of the camp its shot just killed this turn. W.occ_camps is the
// turn-start read (KSO1), so that tile still reads occupied; a dead camp's tile can be stood and landed on (GR:196, INT:136). Bit 1: accept
// a member tile whose only blocker is that dead camp (occ_camps set, no unit, camp_alive_now false). Flag VKD_BITS, 0 = off.
// v832 VKD: Vesper clearing dash past a just-killed camp
#define VKD_BITS 1
inline constexpr int VKD_TAB[2] = { 0x564B4431, VKD_BITS }; // slot 0 magic keeps it out of .bss
// SHY (b2284, Prism Planner spec_shy_ifl_1112 + REVISION after RC C741; ledger SHYP): a capture hold yields to the capturer.
// Runtime data flag SHY_TAB[1], read first; 0 = v827. Bit 1: hold_capture_slow steps off the region when a better-ranked visible
// mate (CAPM_SKIP) stands on it. Bit 2: on a gem-only group a Prism (HP >= 35%) ranks best at the yield sites (hold path,
// capture_region_handoff, mate_holds_region). Bit 4: not built. Bit 8 (SHYP, Prism last tile): her target pick takes a mate-claimed
// gem-only group whose pay leaves her W = timer - SHY_TAB[3] - (holder acts first) steps to a free member tile, no seen foe within
// SHY_TAB[2] of the region; a holder steps off only when it sees her on a member tile this turn (not CAPM_SKIP), on both hold paths.
// v833 SHY: SHY Prism takes gem-only groups from holders (arm B)
#define SHY_BITS 3
inline constexpr int SHY_TAB[4] = { 0x53485931, SHY_BITS, 8, 1 }; // magic, bits, foe radius, window slack
// KCV (b2161, RC X586): identical fuel cuts in the rating's crew estimate. 0 = nova_b12872_gbzhsrsr (v813). Bits: 1 KCV1: stun_soak_cancel
// skips the area/land stun cover for a group with <= 1 attacker (its cover extra is exactly 0); 2 EWM1: team_feasible_refresh memoises the
// estimate per (single-camp group class, crew_epoch) at scale 1 (no crew-mode term); (4 FCM1 dropped at Step 0: +0.16M/g same-work
// on w_hms). RC X589: 8 TCB1: the team crew build adds members
// through an always_inline copy of Crew::add; 16 TCB2 (with 8): that copy skips budget_he and its x3 (estimate reads it only when he & 1,
// never: static_assert HE_TAB[1] & 1 == 0); 32 TFE1: the refresh uses a feasible-only inline copy of estimate (e.t and the chain block only
// inside the multi-trip branch, their one reader).
// v835 KCV: KCV identical cut (IDENT, Coord ruling)
#define KCV_BITS 59
inline constexpr int KCV_TAB[2] = { 0x4B435631, KCV_BITS }; // slot 0 magic keeps it out of .bss
constexpr int KCV_BIT_KCV = 1;
constexpr int KCV_BIT_EWM = 2;
constexpr int KCV_BIT_TCB = 8;
constexpr int KCV_BIT_TCB2 = 16;
constexpr int KCV_BIT_TFE = 32;
// MTG (b2295, CLG 128 / RC X704): Marcella's tribute gold. Runtime data flag MTG_TAB[1], read first; 0 = v829.
// Bit 1 MTG: no tribute gold where her gems cannot bank (gem_weight < 1), in group_value and choose_target's two bound copies.
// Bit 2 MTP1: her Prospector gems earn tribute gold too (BC:205, GR:297), in group_value and the same bound copies.
// v839 MTG: 2 fixes mtp1,pyc1
#define MTG_BITS 2
inline constexpr int MTG_TAB[2] = { 0x4D544731, MTG_BITS }; // slot 0 magic keeps it out of .bss
// WTN (b2295, RC X704 WTN1): Willow heals only ANOTHER ally (GR:724). Runtime data flag WTN_TAB[1], read first; 0 = v829.
// Bit 1: in Crew::add a first member (the camp tank) with a heal never releases it into heal8 (the tank's own damage is not soaked by it).
// v840 WTN: swept v840: 0 in live and nova_b13609_fxp16z, no line flips it
#define WTN_BITS 0

// PRW (spec_prw_1112, Prism Planner; 04gem_rush v Fish): the Prism's bank releases see the foe's finish sooner. 0 = live v837.
// Bits: 1 = true team bag (unbuilt: needs the MBB team-word field), 2 = foe hoard floor (foe_finish_eta keeps a living foe's
// last known bag with no age cut-off until it is seen banked), 4 = PC_RACE_T 120 -> 160 on ONEALTGRP maps (MCL4 bit 64; classbits.tsv row 79, RC C844 F1).
// v844 PRW: PRW8 bank before her race is lost
#define PRW_BITS 8
inline constexpr int PRW_TAB[2] = { 0x50525731, PRW_BITS }; // slot 0 magic keeps it out of .bss
// PRW bit 8 LATENCY (spec addition 20:10Z): why 6 adds our tributed rate x (her walk + channel); bit 16 caps that time at PRW_LAT.
constexpr int PRW_LAT = 60;
// PRW bit 32 (spec bit 16, renamed: 16 is bit 8's cap): a live race latch outranks the capturing/about-to-capture hold unless the capture pays within PRW_PAY.
constexpr int PRW_PAY = 3; // capture_pay_in metric (RC C874): 3 = the reward lands within 2 rounds
inline constexpr int WTN_TAB[2] = { 0x57544E31, WTN_BITS }; // slot 0 magic keeps it out of .bss
// FSQ (b2147, RC X569 FSQ1): suspend-through slice on maps with more than FSQ_G camp groups (draft-time static count). Flag read
// first; 0 = v806. Bit 1: my own target-less choice on a safe standing turn (no foe in sight, no damage in 2 rounds, no camp threat,
// not on a camp tile, not a dash-stun kit) skips the bounds pass's pause (slice or order wait) once per choice and lets the engine
// suspend the turn; fsq_r (the skip's round) clears at a pick, once I hold a target, or on death.
#define FSQ_BITS 1
// v840 FSQ: skip a fruitless choice once on huge maps (FSQ)
#define FSQ_G 150
inline constexpr int FSQ_TAB[3] = { 0x46535131, FSQ_BITS, FSQ_G }; // slot 0 magic keeps it out of .bss
inline bool fsq_pass = false; // FSQ1: this pass may skip one pause (set around best_group's own group_bounds call)
inline int fsq_r = -1;        // FSQ1: the round of this choice's skip (-1: none yet)
// CHW (b2336, Shared Mem carry_sharedstate_1112 C1 + RC C875 + Shared Mem correction; owner 12 Nov "carries and funnelling"): a mate at a
// cleared group leaves it for a carry it cannot see. 0 = v841. Each body keeps every carrier's last-seen tile and round (local). The
// unseen test: the carrier's claim digit names g, it is not dead (digit) and siege_ally_alive, it was seen <= CHW_SEEN rounds ago and
// (walk from its last-seen tile to g) - (rounds since) <= CHW_TAB[2]; I am no carrier. The action is the live Prism wait's: no foe in
// view, my running capture finishes when she cannot arrive before it pays, else I mark g failed for CHW_TAB[2] rounds, drop the target,
// keep off her region and step off it (the capture restarts when she stands on it). Bit 1: the gold carrier at a group with gold.
// Bit 2: the gem carrier at a group with gems: on the Prism's plan groups the unseen test only widens mate_waits_for_prism_capture's
// sight test (one episode timer, max(PC_ROUTE_WAIT, CHW_TAB[2])); elsewhere (or a Marcella carrier) the same action.
// C875b (binding): a mate already on the region keeps live play (a running capture holds; capture_region_handoff gives her the reward);
// CHW changes play only for a mate not yet on it. A carrier seen in a tribute waits only if its rounds left end within the wait; in a
// recall or a teleport never (read_allies already drops the idle spin's first-tick recall). Bit 4: a mate next to the
// region (not on it) holds there up to CHW_TAB[2] rounds instead of the release.
#define CHW_BITS 1
#define CHW_W 4
// v845 CHW: CHW mate leaves a cleared camp for the carry
#define CHW_SEEN 6
inline constexpr int CHW_TAB[3] = { 0x43485731, CHW_BITS, CHW_W }; // magic, bits, wait rounds
// b2273 CLTF (Path Finding spec_clt_1112 REVISION after RC C883; owner funnel top item): clear and leave, the carry trails and collects.
// Runtime data flag CLTF_TAB[1], read first; 0 = v841. Roster (owner 12 Nov): carries = fielded Prism, Vesper, Marcella (a helper when Prism
// and Vesper are both fielded: two carries at most); Varg / Vendetta never. Per
// group: the carries within CLTF_WAIT of it, else the nearest one (split areas); with two or more present, Prism leads (owner); without
// her, gold-led (10 x gems <= gold) -> Vesper > Marcella, gem-led -> Marcella > Vesper. Carry: alive, >= 50% HP, not channelling, claim kind not dead/fight.
// Bit 32 (C883 bit 1 (a), a capture re-rank: off in the lead arm per the Planner's ruling after fun6pk): shy_rank ranks the group's carry
// first, so a clearer on the region hands its running capture over only once she stands on a member tile (capture_region_handoff).
// Bit 1 (b): a clearer not on the region with no capture running leaves the group empty only while the carry
// claims it and her distance is beyond a fresh timer (5; 3 with my Capture emblem) and <= CLTF_WAIT; no mark_mate_capture; it re-picks
// the group (econ_rate_crew claimed() skip lifted) at now > left + ETA + 2, her claim gone, her death / fight / recall, or a foe within 8.
// Bit 2: the carry's choose_target takes a cleared group of hers with gold or gems within CLTF_WAIT path tiles and no capture running
// (claimed() lets her keep it). Bit 4: with no such group and her target farther than CLTF_TRAIL, she takes the group the nearest
// non-carry mate (within 2 of its anchor) clears, one carry per crew. Slots: [2] CLTF_WAIT 6 [3] foe radius 8 [4] CLTF_TRAIL 15 [5] CLTF_V1 (bit 1 only on groups whose
// group_value >= it; 0 = all).
#define CLTF_BITS 7
#define CLTF_WAIT 7
#define CLTF_TRAIL 15
// v846 CLTF: CLTF clear and leave, carry trails
#define CLTF_V1 0
inline constexpr int CLTF_TAB[6] = { 0x434C5446, CLTF_BITS, CLTF_WAIT, 8, CLTF_TRAIL, CLTF_V1 }; // slot 0 magic keeps it out of .bss
// SQWL (b2355, RC X769 SQWL1): squad leashes are Chebyshev between anchors, through walls. Runtime data flag SQWL_TAB[1], read first;
// 0 = v844. A walk is read from a built group field only (mv::group_walk_at; -1 = not built: Chebyshev kept). Bit 1: near_objectives
// and form()'s seed mate test also need walk <= SQ_LEASH + 4. Bit 2: the partner trigger (squad_partner_retarget) also fires when my
// target's walk from the seed's group anchor exceeds SQ_FORM_LEASH + 4. Bit 4: best_within drops groups whose walk from c exceeds r + 4.
// v848 SQWL: swept v848: 0 in live and nova_b13866_sqen1r, no line flips it
#define SQWL_BITS 0
inline constexpr int SQWL_TAB[2] = { 0x5351574C, SQWL_BITS }; // slot 0 magic keeps it out of .bss
// SQEN (b2355, RC X769 SQEN1): the rally gather waits for a squad mate engaged at its own group. Runtime data flag SQEN_TAB[1], read
// first; 0 = v844. Bit 1: rally_present_count's squad-mate branch and no_mate_arrives_in_time's mate test skip comms::cengaged(s).
// v847 SQEN: SQEN mate test before rally
#define SQEN_BITS 1
inline constexpr int SQEN_TAB[2] = { 0x5351454E, SQEN_BITS }; // slot 0 magic keeps it out of .bss
// MYLV (b2355, RC X769 MYLV1): mate_yield corridor right-of-way holes. Runtime data flag MYLV_TAB[1], read first; 0 = v844.
// Bit 1: with my own field unbuilt, the lower slot never yields to a higher slot (A-B-A livelock). Bit 2: no yield tile under the
// camp-threat filter: a second pass allows camp threat up to th0 + MYLV_CT% of my max HP. Bit 4: no tile found: try the next stuck
// ally instead of stopping.
#define MYLV_BITS 0
// v848 MYLV: swept v848: 0 in live and nova_b13866_sqen1r, no line flips it
#define MYLV_CT 10
// BRW (b2294, rebuilt from b1848's BRW for RC X789 RSMK1 A; GR:401): a paused bounds pass resumed only on the exact pause tile, but a
// walking targeted body steps on its pause turn (target_turn_choose_step), so the pass restarted from group 0. 0 = v846. Bit 1: resume
// within cheb 1 of the pause tile when the travel field is still the pause tile's (travel_from == gbr_pos); choose_target and lah_stand then
// skip compute_travel (they test bounds_resume_ready), so the resumed list and its rating keep the pause tile's travel (1 round stale).
// v851 BRW: BRW1 resume bounds pass one tile off
#define BRW_BITS 1
inline constexpr int BRW_TAB[2] = { 0x42525731, BRW_BITS }; // slot 0 magic keeps it out of .bss
// XEP (b2294, RC X780; GR:399/401): site-local prices of the hms bounds pass. 0 = v845. Bits, each read first:
// 1 GBEP1: a fresh bounds pass (no resume ready) that starts under the loop's own pause floor stashes an empty list (gbr_gi 0) at once,
//   instead of running setup + the first 8 groups into a cut; r+1 resumes from group 0 (the same list).
// 2 STNP1: a due static-table rebuild with fuel() < XEP_STN_A + XEP_STN_B x ng is skipped for this pass: the loop fills each group
//   inline (tab null path, the same rows) and can pause every 8 groups.
// 4 QTB1: gtb_prebuild builds the table in background slices (a staged copy, a row cursor, swapped in when complete) instead of its
//   all-or-nothing gate, which never passes on hms.
#define XEP_BITS 7
#define XEP_STN_A 10000
#define XEP_STN_B 400
// v849 XEP: XEP GBEP1+STNP1+QTB1 hms bounds pauses
#define XEP_QTB_ROW 600
inline constexpr int XEP_TAB[5] = { 0x58455031, XEP_BITS, XEP_STN_A, XEP_STN_B, XEP_QTB_ROW };
inline constexpr int MYLV_TAB[3] = { 0x4D594C56, MYLV_BITS, MYLV_CT }; // slot 0 magic keeps it out of .bss

// ALC (b2287 alc1 + b2330, RC C748/C748b/C807): altar-hold finish ETA. 0 = nova_base_v838. Bits: 1 = ALC1 eta = d + ticks - age while > 0
// (overdue: max(0, d - age) + ticks, RC C748b F1), not max(0, d - age) + ticks. 2 = ALC2 a carrier seen channelling this round (age 0,
// ST_TRIBUTE): at an altar within cheb 1 of her (RC C815 A1) the eta (and the EG2 game-end test) is the channel's real time left + 1 if
// it acted (GR:226/:275), not the full ticks; other altars and an unreadable channel keep the clock above. 8 = ALC8 a camp tile reads UNREACH in the altar fields (built on block_camps): at the carrier,
// a candidate or me, a camp tile takes 1 + the least of its 8 neighbours (UNREACH if all are). 32 = ALC32 (RC C807c, GR:29) the hold's
// early-out (altar_hold_turn, _slow, altar_hold_pinned) is tributed_them + the largest live row bag < 1000, not tributed_them < 300.
// v848 ALC: 3 fixes alc32,ktw15,wbh1s
#define ALC_BITS 32
inline constexpr int ALC_TAB[2] = { 0x414C4331, ALC_BITS }; // slot 0 magic keeps it out of .bss

// KTW (b2330, RC X728 CTW sweep): a dead, standable camp tile reads UNREACH in the block_camps fields (field_here, mapinfo.h). 0 =
// nova_base_v838. Bits: 1 = KTW1 the recall-to-bank rule (econ_bank_walk.cc recall step, far-altar read; the walled-in read is CLEAN per X728 and fired 0) reads my tile with
// field_here. 2 = KTW2 the hole-dash bank route (bank_dist_via_hole_dash, bank_hole_dash). 4 = KTP1 Prism's safe-altar reads
// (recall_bank_saves_walk, bank_carrier_field, pbk_walk_she_takes). 8 = KTF1 eh1_foe_can_land reads a foe on a camp tile by its neighbours,
// not as standing at the altar.
// v848 KTW: 3 fixes alc32,ktw15,wbh1s
#define KTW_BITS 15
inline constexpr int KTW_TAB[2] = { 0x4B545731, KTW_BITS }; // slot 0 magic keeps it out of .bss
// BWLR (b2354, RC C886 BWLR1): walk_to_free_twin_altar's fewest-hits read (econ_bank_walk.cc) took altar_lock_at(..).is_enemy(), which
// returns OUR lock when both stand (INT:132), so the foe lock's hits were missed; bit 1 reads the foe lock directly
// (enemy_altar_lock_direct, as lock_hit_slow). 0 = v841.
// v848 BWLR: 3 fixes alc32,ktw15,wbh1s
#define BWLR_BITS 1
inline constexpr int BWLR_TAB[2] = { 0x42574C52, BWLR_BITS };
// MCKS (b2354, Builder/VV/RC MCKS1): Marcella's crystal channel is stun-proof (GR:658 passive, INT:139) and damage does not cancel a
// crystal, yet her crystal casts ran the foe gates. Bit 1: crystal_step's ready-stun bar (econ_crystal_plan.cc) skipped for her
// (marcella_layer::chan_stun_proof). Bit 2: the "no crystal channel with a foe within 4 of me" gates (crystal_step's foe bar and
// the spawn crystal trip's cxf_me) skipped for her; foe-near landing filters stay. 0 = v841.
// v849 MCKS: swept v849: 0 in live and nova_b13893_fxp20zsr, no line flips it
#define MCKS_BITS 0
inline constexpr int MCKS_TAB[2] = { 0x4D434B53, MCKS_BITS };

// FGP (fgx, RC X635/X636). Bit 1 FGP1: a targeted body's rejected stored bounds pass that pauses again meters its cost (spent + the floor)
// into fg_pre, so the fg_pre gate keeps the target without a choice next turn. Bit 2 GBX1: the gate does not skip a turn whose paused pass
// can resume (same tile), so a standing body's chain is not aged out. 0 = v821.
// v853 FGP: LZI arm C group_bounds sort fix (hms)
#define FGP_BITS 3
inline constexpr int FGP_TAB[2] = { 0x46475031, FGP_BITS }; // slot 0 magic keeps it out of .bss
// b2187 LZI (RC X616/X619): group_bounds_finish's sort, bit 1 in best_group (LZI1), bit 2 in lah_stand (LZI2), is libc++'s own introsort run lazily: each right range waits on a
// stack until a reader reaches its index (the same entries at every index, ties included; a drain gives std::sort's array).
// v853 LZI: LZI arm C group_bounds sort fix (hms)
#define LZI_BITS 3
inline constexpr int LZI_TAB[2] = { 0x4C5A4931, LZI_BITS }; // slot 0 magic keeps it out of .bss
// SPZ (b2336, spec_spz_1112, Path Finding + Aggression; owner replay 01a1d1cf "we should not teleport that close to their spawning area"):
// distance to their spawn. 0 = v845. The home balance at tile p (spz_home_ok): me + visible mates within SPZ_MATE_R of p (eff_hp x (Str +
// Focus)) against the foes that COULD BE HOME at full health by team intel (roster): alive and unseen for >= SPZ_RECALL rounds (a recall
// takes 5 turns, GR) or respawned onto their spawn within SPZ_RECALL rounds; dead foes out. Bit 8 (8a HOP):
// mid_hop_try refuses a crystal landing within SPZ_D of their spawn rectangle unless that balance is > 1. Bit 32 (8b TARGET): my own pick
// skips a group whose anchor is within SPZ_D of their spawn unless the balance at the anchor (mates there or claiming it) is > 1.
// Bit 4 (CHASE-BACK, RC C919): each body notes foes seen under 50% HP (round, Chebyshev steps to their spawn rect, range). A foe "just healed"
// = (a) seen on its spawn tile after such a sighting, or (b) unseen for >= its steps since that sighting; "just" = within SPZ_CB_WIN rounds.
// While one did, a body under 50% HP within its two-turn return reach of their spawn rect (walk 2 + its kit dash + range) walks home (home field)
// and holds that leave until outside the reach + 1 or SPZ_CB_HOLD rounds. Not on kill_now, a foe in reach now (flee), on our spawn, channelling or
// on a capture region.
#define SPZ_BITS 1
#define SPZ_D 6
// Bit 1 (GRADED KILL, RC C919 + Builder M): NOCHASE's "within 2 of its spawn" is replaced in hunt_target, the focus drop (nc_cleared) and
// engage_dash_ok by "kill in hand": off its spawn, ceil(kt) + SPZ_TAB[2] (M) <= window, window = its steps to heal (Chebyshev to the spawn
// rect, -1 with a possibly ready dash, +1 stunned) if it has acted this round, else steps - 1. kt = eff HP / (me + mates whose reach covers
// it). Known leaks: FUL bits and finish_low keep live's tests. Lead arm M = 2, second M = 0.
// Form B (v854, b2364; the one adaptation after spz1 .4627): the graded test gates MOVEMENT only. NOCHASE_R 2 stays everywhere as live. A fight
// turn whose focus is not kill-in-hand (and no kill_now) refuses any step (try_move) or dash (cast_via_sdk) ending closer to their spawn rect than
// my tile; hunt_target skips a not-in-hand foe outside my attack range. Attacks / casts from the tile and focus are unchanged. Arm SPZ_M = 0.
// RC C950c: the gate arms only for a focus within SPZ_D of their spawn, prices my walk-in (ceil(kt) + t + M <= window, t = cheb - my range,
// my dps counted, mates within range + 1) and is consulted only while fight_stage runs (econ / capture / rally steps are never refused).
// v857 SPZ: SPZ B no chase into their spawn zone (M=0)
#define SPZ_M 0
inline constexpr int SPZ_TAB[3] = { 0x53505A31, SPZ_BITS, SPZ_M }; // slot 0 magic keeps it out of .bss

// ZCS (b2366 from b2341, RC X786 ZCS1 + X789 STGM1; bug bar): a target-less choice cut by the fuel floor with no pick stages only its
// UNRATED rest, from the cut as pec_store does, not the whole list from index 0 (bit 1); a staged run cut again with no pick re-stages its
// own unrated rest instead of clearing the stage (bit 2), so successive turns walk down the list; the target-less stage holds within one
// tile as PEC's list does (bit 4; st_pos == pos exactly before). Runtime data flag, read first; 0 = live v855.
// v858 ZCS: ZCS cut choice keeps its unrated rest + STGM1
#define ZCS_BITS 7
inline constexpr int ZCS_TAB[2] = { 0x5A435331, ZCS_BITS }; // slot 0 magic keeps it out of .bss
// CRO (b2371, RC X812 CRO1/CRO1b + X813 CRDN1): own-capture bookkeeping fixes. Runtime data flag CRO_TAB[1], read first; 0 = v856.
// Bit 1 CRO1: capture()'s paid branch with no gain on a GS_RESPAWN group whose observed timer runs keeps that exact timer and posts it
// (as wfb_settle_turn) instead of now + full respawn. Bit 2 CRO1b: on a GS_RESPAWN group a gain is rebased (not a capture) when the
// engine shows the group alive/unpaid (1/2), or respawning (3) while I never stood on the region this capture (T.cap_on < 0).
// Bit 1 also gives PYB (econ_idle.cc pyb_paid) its own marker, set in capture()'s paid branch (gain or no gain), in place of the
// respawn_at == now + respawn test that the old overwrite produced (RC X814 N1). CRO1 reopens CRX1 (failed bug bar 10 Nov): the changes
// are the PYB marker, the post of the kept engine time and CRO1b. Bit 8 GSM2 (SDR, RC X814 N4): drop_stalled_target counts a running
// respawn as progress only while the status is GS_RESPAWN.
// Bit 4 CRDN1: next_farm_nearer_than_spawn reads a group with no camps-open field from its built raw field (field_nb at my tile).
// v860 CRO: CRO keep exact respawn time + PYB marker + GSM2
#define CRO_BITS 11
inline constexpr int CRO_TAB[2] = { 0x43524F31, CRO_BITS }; // slot 0 magic keeps it out of .bss
inline int cro_pyb_r = -1000; // CRO bit 1: the round capture()'s paid branch ran (PYB's marker)
// SAX (b2389, Econ spec_sax_1113, RC C976): on a siege map a monolith group with 2+ attacker camps gets the siege recruit. Bit 1:
// sax_siege_ok (econ_team_model.cc) at recruit()'s siege branch and siege_allowed / designated_siege. Bit 2: heavy_multi_trip_ok admits
// that group next to our spawn. Bit 4: bit 1 only for a group in our half (contest <= .5). Bit 8 (RC C976b, own bit): designated_siege latches only once
// M is done (RC C976 req 1). 0 = v855.
// v862 SAX: SAX siege recruit + near-spawn multi-trip, 2+-att monolith
#define SAX_BITS 3
inline constexpr int SAX_TAB[2] = { 0x53415831, SAX_BITS }; // slot 0 magic keeps it out of .bss
// SCH (b2388, Path Finding carry walk split 1113): a spawn-crystal trip was dropped mid-walk when refresh_target re-chose (24-30% of
// Vesper trips ended unused, 44 of 73 by a target change, -3 to -6 turns each). Runtime data flag SCH_TAB[1], read first; 0 = v855.
// Bit 1: while my trip to group T.target is live and its hop not cast, its group up (alive or unknown) and no foe seen within SCH_FOE_R
// of me, a due re-choice keeps the target (as LCE bit 64 for island launches).
#define SCH_BITS 1
// v863 SCH: SCH spawn-crystal trip keeps target until the hop
#define SCH_FOE_R 6
inline constexpr int SCH_TAB[2] = { 0x53434831, SCH_BITS };

// v864 OXF (b2366, RC X770 / X826; baked, play-identical): RXLS1's respawn list (econ_observe.cc expiry pass, mark_respawn) on maps with
// OXF_NG+ groups (the pool's cap; ladder / hms maps reach 114+); OVSC1 (observe skips an unseen group's dead hoard note) needs no state.
#define OXF_NG 64
inline std::vector<int> oxf_rl;           // groups mark_respawn made respawning (deduped by oxf_rin)
inline std::vector<std::uint8_t> oxf_rin; // 1 while the group is in oxf_rl
inline bool oxf_l2 = false;               // list mode this game (set by the expiry pass each turn)
// b2384 EFB (RC F2 econ-formula audit, /data/USER/rulecheck/p6/f2_econ_formulas.md): runtime data flag EFB_TAB[1], read first; 0 = v865.
// Bit 1 SB1: stake_bars' stake is 1 when tributed_them + my bag (the C&I pair's) >= 1000 (my death hands the bag to the killer, GR:375,
// and the first team to 1000 wins, GR:29); the BAG_MIN gate is skipped then. Bit 2 HNT1: the emblem ranking prices Hunter's +50 a kill
// times my gold multiplier (Hunter adds before the gold bonuses, BalanceChanges.md:1210). Bit 4 FGV1: finish_group_value counts a
// Prospector holder's cluster gems (GR:297, INT:96), exactly as group_value adds them (no share, RC C1091). Bit 8 TGF1: on a gem-cluster-only map Marcella keeps Treasure
// (it raises her tribute gold, INT:95) instead of the Treasure->Hunter swap.
// v867 EFB: econ formula bundle SB1/HNT1/FGV1/TGF1
#define EFB_BITS 15
inline constexpr int EFB_TAB[2] = { 0x45464231, EFB_BITS };

// RHQ (b2394, RC X845 RHQ1, fix --q1bar): recall_hop_early (econ_recall_heal.cc) returns at the first gem group or altar whose bound
// reaches RWK_TAB[3] and skips those with d_home < RWK_TAB[3] + 4, instead of scanning all for the max (same v on every map; ~38k on hms
// behind a 34k guard). Runtime data flag, read first; 0 = v865. Bit 1 only.
// v868 RHQ: recall_hop_early returns at the first qualifier
#define RHQ_BITS 1

// b2390 ODM1 (RC X850; Step 0 0 mismatches in 1,086 rows, /data/USER/st/b2390/odm): the draft's per-slot opening sims (DFG loop,
// n(n+1)/2 runs) keep each NON-self row (the claims and done state it leaves, its rate and crew) and a later slot's run takes it at the
// same sim position from the same state instead of re-running group_bounds + rate_for. Self rows run as live. Runtime data flag
// ODM_TAB[1], read first; 0 = v868. Bit 1 only.
// v869 ODM: ODM1 reuse identical non-self sim rows
#define ODM_BITS 1
inline constexpr int ODM_TAB[2] = { 0x4F444D31, ODM_BITS }; // slot 0 magic keeps it out of .bss
inline constexpr int RHQ_TAB[2] = { 0x52485131, RHQ_BITS }; // slot 0 magic keeps it out of .bss

// SGPS1 (b2381, RC X855): start_goal_i's "any group with a distance" pre-scan reads only the groups a distance can be in: none before
// M.init's ST_DASH stage (unless draft memory gave them), the groups below the cursor during ST_DASH phase 0, all after. The same answer.
// Runtime data flag SGPS_TAB[1], read first; 0 = v866.
// v872 SGPS: swept v872: shipped value with no ledger record
#define SGPS_BITS 1
inline constexpr int SGPS_TAB[2] = { 0x53475053, SGPS_BITS }; // slot 0 magic keeps it out of .bss
// HRTS (b2387; RC X869 HRT1, bug bar, bundle C). Runtime data flag HRTS_TAB[1], read first; 0 = v872. Bit 1: home_round_trip_too_costly
// (the 15-round home-trip veto of a shop recall) tests my last dropped target (drop_target keeps it and the round in hrts_last / hrts_last_r)
// when T.target is -1, if it was dropped within the last 2 rounds (RC C1155) and its group is still up (alive or unknown) and not failed.
// v881 HRTS: baked at its shipped value
#define HRTS_BITS 1
inline constexpr int HRTS_TAB[2] = { 0x48525453, HRTS_BITS }; // slot 0 magic keeps it out of .bss
// FGSF (b2387; RC X871 FGS1 CONFIRMED, bug bar, bundle C). Runtime data flag FGSF_TAB[1], read first; 0 = v872. Bit 1: finish_group_value
// scales the Prospector holder's cluster bonus by her share (GR:297: 25% of the holder's own share), not the whole cluster reward.
// v881 FGSF: baked at its shipped value
#define FGSF_BITS 1
inline constexpr int FGSF_TAB[2] = { 0x46475346, FGSF_BITS }; // slot 0 magic keeps it out of .bss
// b2377 RC X862 fuel lines on v868 (each its own flag, read first; 0 = v868).
// ILP (replaces IDM1; IDM is a shipped prefix): idle_move's re-pick loop sets IDL1's walk-time prune (idl_t1) once a poll every 8 groups reads
// fuel() < 50000, not only at loop entry. Exact: below 50k reachable_target writes nothing and a pruned group cannot change the pick.
// v873 ILP: ILP1 idle re-pick fuel poll
#define ILP_BITS 1
inline constexpr int ILP_TAB[2] = { 0x494C5031, ILP_BITS }; // slot 0 magic keeps it out of .bss
// FLB: filler_target rejects a group whose round-trip lower bound (walk + capture pay + walk back, integers) already exceeds left +
// WAIT_FILL_SLACK before group_value / estimate_cx run. Exact (live's total >= the bound whenever e.t >= 0).
// v874 FLB: swept v874: 0 in live and nova_b14565_ilp1s, no line flips it
#define FLB_BITS 0
inline constexpr int FLB_TAB[2] = { 0x464C4231, FLB_BITS };
// FWG (X721/X862 FWG1): target_turn_take_filler_task prices the wait-chip pass: no wait_chip_target with fuel() < FWG_BASE + FWG_PG x ng
// (T.filler_check already set: the pass retries after 4 rounds, as after a no-pick). Identical at unlimited fuel; changes the pick only on
// turns that would be cut.
// v874 FWG: swept v874: 0 in live and nova_b14565_ilp1s, no line flips it
#define FWG_BITS 0
inline constexpr int FWG_TAB[2] = { 0x46574731, FWG_BITS };
// CQR (b2376, Deep spec_cqr_1113 + Amendment 1, Planner approved; funnel family). Runtime data flag CQR_TAB[1], read first; 0 = v866.
// Carry = a roster carry (owner roster v2: Prism, Vesper, Marcella; a Vendetta when fewer than two of those are
// fielded); bits 16 / 32 act only in my own rating / decision. Bit 4 SHORTER LEGS (every rate_for row of a carry slot, RC C1103): travel time weighs x CQR_LEG/100 (150) for
// a group with no golem/monolith, x CQR_LEG0/100 (200) in my own row while I stand on my spawn (the first pick after a respawn, recall or shop).
// Bit 16 NO WALK TO A WAIT: a respawning group whose wait on my arrival exceeds CQR_WT (4) rounds is refused while some live group
// (alive or unknown, gems or gold) is no farther in time (its travel <= that group's travel + wait). Bit 32 HEAL ON: the far-from-home
// heal line (B438_HEALF) is not taken at HP >= 35% when no foe champion was seen within 12 of me for 10 rounds (intel::count_near)
// and a live group without golem/monolith is within 10 travel (only with a fresh travel table, PESR1's test). Slots: [2] CQR_LEG 150 [3] CQR_LEG0 200 [4] CQR_WT 4.
#define CQR_BITS 32
#define CQR_LEG 150
#define CQR_LEG0 200
// v876 CQR: CQR32 skip far heal recall when quiet
#define CQR_WT 4
inline constexpr int CQR_TAB[5] = { 0x43515231, CQR_BITS, CQR_LEG, CQR_LEG0, CQR_WT }; // slot 0 magic keeps it out of .bss
// b2384 CPL (Shared Mem spec_cpl_1113 + Planner / VV / RC rulings; owner: "can we do the same for the other stacking champions"): a carry
// plan for the primary carry when it is not Prism. Runtime data flag CPL_TAB[1], read first; 0 = v879. Bit 1 PLAN: at the draft
// hand-off of the complete lineup with Vesper and no Prism, the plan block's 4 group slots (bytes 744-747) hold HER groups: walk access,
// contest <= .6, camp gold >= CPL_GOLD_MIN, a monolith / golem group only where SAX's siege class admits it, richest gold first. Prism
// lineups keep Prism's plan byte for byte; Marcella's plan is Prism's (gems, the same order). The plan carry's kind is read in play from
// the lineup (Prism > Vesper > Marcella): no format change. Every live consumer of the plan groups is Prism-only.
// v884 CPL: CPL plan bytes, fail-safe skip (no-harm)
#define CPL_BITS 1
inline constexpr int CPL_TAB[2] = { 0x43504C31, CPL_BITS };
#define CPL_GOLD_MIN 100
// XCP (b2368, RC X892 capture bookkeeping; bug bar). Flag read first; 0 = live v882. Bit 1 CHO1: hold_capture's calm no-foe release does not
// fire on a cleared region whose pay is 1-5 rounds away when my target is another group (capture() holds only my target, so the region
// emptied before the pay: GR:196). Bit 2 CRO1c: capture()'s gain branch on a group observe holds GS_RESPAWN with a future respawn_at posts
// respawn_at - respawn and keeps that time (it was booked d rounds late after a combat-path hold; C351 fix-1 form).
// v886 XCP: XCP hold near-pay region + exact respawn booking
#define XCP_BITS 3
inline constexpr int XCP_TAB[2] = { 0x58435031, XCP_BITS }; // slot 0 magic keeps it out of .bss
// b2383 PTY S1 (spec_pty_1113 S1 + Shared Mem / Deep amendment; field: teamword_bits.tsv "ESC (reused by PTY S1)"; never with ECT).
// Runtime data flag PTY_TAB[1], read first; 0 = v883 (no field allocated). Bit 1: the roster lead carry (Prism > Vesper > Marcella) SAYS
// a party in the 4-bit ESC spare field (single writer, put on change): on a FORM tick (every PTY_TICK r) with her own target heavy
// (golem/monolith) or contested (.35-.65), she names the 1-2 nearest available units (bodies other than her, ascending slot, Cassi +
// Issac one unit) when the party rate at crew size (value share / (slowest walk + clear + 5), plus the per-member camp-damage saving
// L(1) - L(n)/n at PTY_KS / PTY_TH) beats the units' solo sum x PTY_M %. Named units take her target while it names them. She holds
// the party; it dissolves on her 2-tick test (party < solo sum by > PTY_HYS %; then PTY_BAN r no re-form on that target), and at once on
// a foe within 8 of her, her recall/tribute/bank walk, a named body dead or under 50% HP, her death (0 on her first dead turn).
// S1b (Planner's one adaptation): bit 4: parties form only for a target neither she nor any named unit can clear alone (estimate, one trip).
// Bit 2 (spec step 2, build correction; no standing hold over 2 turns): escorts walk to her target from the form tick, and at the group a
// crew-incomplete body of the said party starts as soon as every other party body is in sight within PTY_NEAR (2) tiles of it and that
// crew clears the group by estimate_cx(4) (RC C1027), instead of the live crew wait.
#define PTY_BITS 0
#define PTY_TICK 5
#define PTY_M 100
#define PTY_HYS 10
#define PTY_BAN 10
#define PTY_KS 250
#define PTY_TH 100
#define PTY_FUEL 45000 // the FORM tick's fuel floor (pty7 fuel cap: was 20000)
// v888 PTY: swept v888: 0 in live and nova_b14841_mgy4rs, no line flips it
#define PTY_NEAR 2
inline constexpr int PTY_TAB[10] = { 0x50545931, PTY_BITS, PTY_TICK, PTY_M, PTY_HYS, PTY_BAN, PTY_KS, PTY_TH, PTY_FUEL, PTY_NEAR }; // slot 0 magic keeps it out of .bss
// b2383 MGY MID GEM PARTY (Planner, b2383 why-not count: no_crew binds 51% fresh / 43% v Fish; the MGP prefix is taken: spec_mgp_1109). Runtime
// data flag MGY_TAB[1], read first; 0 = v883. Uses PTY's ESC field and party code (allocated when PTY bit 1 or MGY is on). Bit 1: after the
// opening choice (opened) and before finish mode (finish_mode(0)'s test; RC C1145, no round gate), on a FORM tick (PTY_TICK), the roster lead
// carry (the ESC writer) rates the mid gem groups (contest .35-.65, gems >= MGY_G, alive, no mate claim, her walk <= MGY_W, not banned) she cannot
// clear alone (estimate; the no_crew proxy), at crew = her + the 1-2 available units nearest the group within MGY_W walk; the party forms iff the
// party rate (PTY's form, GHP saving included) >= PTY_M % of her current pick's solo rate + the units' solo rates at their digits' groups. She takes
// the group; named units take her digit. Breaks: foe within 8 of her, recall/tribute/bank walk, a named body dead or < 50% HP, her death, her
// target changed or the group respawning, or 2 FORM ticks below the solo sum by > PTY_HYS % (then PTY_BAN r no re-form). Lead-carry-only form
// (a non-carry lead cannot be said in ESC: no group id in 4 bits).
// Bit 2 MGY2 (Planner's pre-stated form after the break split: foe within 8 ended 40% of abandoned parties): a candidate group also needs no
// foe seen within MGY_FR of it in the last MGY_FA rounds (intel::count_near: my sight / ward; plus my sight now). Arm MGY_BITS=3.
// Bit 4 MGY3 SYNC ENGAGE (Planner, member losses were camp damage 595 v foe 51 at 88% HP: staggered engagement): at a living party group
// nobody starts the clear (target_turn_start_or_hold stages outside the reach) until every member is within MGY_SR of the lead (the lead's
// own view; an escort is released as soon as the lead's claim shows her engaged on the group, RC C1145d: one shared release); MGY_ST rounds
// after the form without that the lead dissolves it and drops the target (no solo start, the group banned PTY_BAN r); and a party forms only
// if the clear at crew = its bodies (estimate_cx, current HP) predicts no member under 50% (camp damage split evenly). Arm MGY_BITS=7.
// Bit 8 MGY4 MEMBERS (Planner, b2383 convergence count: named escorts re-picked away in 70-89% of episodes, 23-56% busy, 54% unseen): NAMING
// names only units whose bodies are not busy (not channelling, not engaged on their claim, not fighting their claimed group), placed by
// the lead's sight or their digit, and within MGY_NW (Chebyshev) of the group; MEMBER KEEP: a body named for its target keeps it in the
// retarget switch (apply_retarget_choice returns at its top, the MFB PN switch included); the naming's own exits (party breaks, own HP <
// 50%, a foe within 8, channelling, the group respawning) end it. Arm MGY_BITS=15.
#define MGY_BITS 15
#define MGY_G 15 // least gems
#define MGY_W 15 // walk cap (her and the units)
#define MGY_FLOOR 44000 // the form scan's fuel floor: measured p99 of the scan on 40 hms maps x2 (19,576) + 24k (RC X874)
#define MGY_FR 15 // bit 2: no foe seen within this of the group
#define MGY_FA 10 // bit 2: ... in this many rounds
#define MGY_SR 3 // bit 4: gathered = every member within this of the lead
#define MGY_ST 8 // bit 4: rounds after the form to gather, else dissolve (no solo start)
// v887 MGY: MGY4 member keep re-read (owner ruling a)
#define MGY_NW 6 // bit 8: named bodies within this (Chebyshev) of the group
inline constexpr int MGY_TAB[10] = { 0x4D475931, MGY_BITS, MGY_G, MGY_W, MGY_FLOOR, MGY_FR, MGY_FA, MGY_SR, MGY_ST, MGY_NW }; // slot 0 magic keeps it out of .bss
// b2383 MFU (Econ spec_mfu_1113; RC X848 CMG1 / CRV1; 00elkring v pdi witness): the Marcella-sole-primary class (Marcella fielded, no Prism or
// Vesper; roster kinds, draft-time) and her as the group's lead roster carry (cltf_level == 1). Runtime data flag MFU_TAB[1], read first;
// 0 = v881. Bit 1 (VHO1b's hold in the class): she claims the group and is not hurt (frac >= .35): cap_rank ranks her MFU_CARRY ahead. Bit 2
// (CMG1 only): cap_rank drops the 10 x shards term and the PKW gold term for her. Bit 4: a helper on a member tile of the group she claims,
// while she stood within her range + 1 of a living member in the last MFU_DR rounds and its visible remaining HP is within 2 hits of hers +
// mine, steps to a free non-member tile next to a living member (engaged turn). Arms: A = 2, B = 1, C = 6.
// v888 MFU: MFU-A Marcella sole carry keeps captures (fresh)
#define MFU_BITS 2
inline constexpr int MFU_TAB[2] = { 0x4D465531, MFU_BITS }; // slot 0 magic keeps it out of .bss

// MTM (b2366; Econ spec_mtm_1113.md from Combat's 05slant trace, 540 monolith gems: a verified logic bug). estimate() calls a heavy clear
// multi-trip feasible (econ_clear_estimate.cc) but keeps e.dmg = the whole clear and e.budget = one trip, so the siege margin tests
// (econ_team_ops.cc siege_start_gate, siege_crew_ready) can never pass it (only JKC's group bypasses them). Bit 1: both margin tests read
// the per-trip damage e.dmg / e.trips (siege_crew_ready's 'cannot clear' release at :591 reads the same feas). Bit 4: the crew-ready test
// only. Bit 2 (RC MTM pre-build): the op counts as started for one recall cycle after the last engaged round (econ_team_ops.cc mtm_held), so
// the deadline / collapse ends do not fire between trips. Arms: 1 (bug bar), 3 = 1+2 (behaviour), 4 alone (Econ 2nd witness 01a1d2be:
// the crew-ready check is the one that refuses). Read first; 0 = live v882.
// v889 MTM: MTM6 per-trip crew-ready + trip hold
#define MTM_BITS 6
inline constexpr int MTM_TAB[2] = { 0x4D544D31, MTM_BITS }; // slot 0 magic keeps it out of .bss
// RHF (b2364; Shared Mem spec_rhf_1113, owner replay 01a1d490 01yellow_brick_road: 6 of their 12 road captures followed our holder stepping off
// under FLEE). 0 = v891. Bit 1 HOLD THE TILE UNDER FLEE (brain_turn after hold_capture): on a member tile of a CLEARED group with a waiting reward
// (gold + 10 x gems) >= RHF_V, with no live hold (capture_pay_in() < 1) and FLEE or a foe in reach: keep the tile (shield, damage spell,
// hold_region) while HP >= 35% and the seen foes' two-turn damage is under HP + shield. Bits 2 (step back on) and 4 (no budget give-up): not built.
#define RHF_BITS 1
// v895 RHF: RHF road hold, per-group class gate
#define RHF_V 300
inline constexpr int RHF_TAB[3] = { 0x52484631, RHF_BITS, RHF_V };
// OLK (b2387; owner witness 01a1d2f1 r245: our own altar lock cancelled a bush-hidden mate's tribute; b2364's engine read was blind to hidden
// mates). Shared Mem field RTC (teamword_bits.tsv, replaces OTA; shared with WBX bit 1): 3-bit NEED band + bit_width(na - 1) altar index,
// allocated right after TTE / SLA (ORDER RULE), here behind OLK_ON(1) (WBX bit 1 adds its own condition); absent = off. Runtime data flag
// OLK_TAB[1], read first; 0 = v880. Bit 1: WRITER (the channelling body only, rtc_turn): band of need = max(0, 1000 - tributed_us - my bag)
// (1: 0, 2: <= 10, 3: <= 20, 4: <= 35, 5: <= 50, 6: <= 80, 7: > 80) | altar index << 3, at its tribute start and on a band change; 0 on
// land, cancel and its first dead turn; spare_put on change only; two channellers: the field keeps the smaller band, the other re-writes when
// it clears. READER (protect_tribute): no own lock on the named altar while the band is non-zero; stale guard: a non-zero value is dropped
// once tributed_us has risen since it was first read with the field unchanged, or after the longest channel (no Tribute emblem, GR:312) + OLK_SLACK rounds. [2] 2.
#define OLK_BITS 1
// v896 OLK: 7 verified bug fixes (TTCX TDP EAF OLK RFV NTG CHO)
#define OLK_SLACK 2
inline constexpr int OLK_TAB[3] = { 0x4F4C4B32, OLK_BITS, OLK_SLACK }; // slot 0 magic keeps it out of .bss
// CHO (b2402, RC X909 CHO3; bug bar): capture_pay_in returned max(1, k) = 1 at k == 0 (the pay round: the capture phase paid the region
// before champion turns, GR:124 / INT:120) without the engine check, so a calm orphan hold stood one extra round on a paid region.
// Runtime data flag CHO_TAB[1], read first; 0 = v893. Bit 1: the engine check (engine_capture_countdown, cps_cps2_dead) also runs at k == 0.
// v896 CHO: 7 verified bug fixes (TTCX TDP EAF OLK RFV NTG CHO)
#define CHO_BITS 1
inline constexpr int CHO_TAB[2] = { 0x43484F33, CHO_BITS }; // slot 0 magic keeps it out of .bss
// PSO (b2392, RC X910; bug bar): choose_target_when_starved counted a second call in the same round as a new starved round only when
// pes_last == now() - 1, but a repeat call in the SAME round re-ran the whole search (build_team, travel, pick) once pes_n had reached PES_K.
// Runtime data flag PSO_TAB[1], read first; 0 = v897. Bit 1: return at once when pes_last == now() (the round's search already ran).
// v900 PSO: PSO one starved search a round
#define PSO_BITS 1
inline constexpr int PSO_TAB[2] = { 0x50534F31, PSO_BITS }; // slot 0 magic keeps it out of .bss
// GCZ (b2387; Econ spec_gcz_1113, witness 04horseshoes v Fish 01a1d4fd-9675-771f-b0fa-b371db8ca26f: we picked our golems 143x and took 0;
// the top 3 bring 3.7-3.9 bodies per golem cycle v our 2.6-2.8). Groups with a golem, no monolith and one attacker (gcz_group). Runtime data
// flag GCZ_TAB[1], read first; 0 = v898. Bit 1: size_crew does not stop at a feasible crew whose clear is multi-trip (trips > 1); it adds free
// bodies until a single-trip feasible crew, else keeps the smallest feasible one (today's). Bit 2: also a crew under 3 is not final while the
// group is contested (contest >= .35 or a shared foe report within 15 of its anchor in the last 20 rounds). Bit 4: once a crew of k is final,
// k + 1 replaces it when it is single-trip feasible and clears in less crew-time ((k + 1) x t < k x t). Arms: A = 1, B = 3, C = 5.
// The group bounds need no change: a larger crew's exact rate V / (k x trav + hp / d) never exceeds the bound's single-body form.
// v901 GCZ: GCZ golem crew keeps sizing past multi-trip
#define GCZ_BITS 1
inline constexpr int GCZ_TAB[2] = { 0x47435A31, GCZ_BITS }; // slot 0 magic keeps it out of .bss
// OCF (b2387, spec_ocf_1113; owner direct: "just allow stacker to have first pick ... with ordering of prism > VV > marcella"). Runtime
// data flag OCF_TAB[1], read first; 0 = live. Bit 1 PRIMARY FIRST: position 0 of the opening simulation (opening_sim_body_at) is the
// primary carry in the owner's order: Prism if fielded, else Vesper, else Marcella; the rest follow in tank order (Vesper-primary lineups
// unchanged). Bit 4 SECOND CARRY SECOND: a Vendetta is simulated right after the primary.
// b2365 OCF-P bit 8 (spec_ocf_1113 adaptation, pre-registered 14:42Z): bit 1's primary-first only when the primary carry is Prism; every
// other lineup keeps live's opening (the gold carrier first, else tank order).
// b2365 OCF-M bit 16 (owner 13 Nov 14:49Z, spec_ocf_1113 OCF-M): bit 1's primary-first only when our primary is Marcella (no Prism, no
// Vesper fielded); every other lineup keeps live's opening. Arm M1 = OCF_BITS=16.
// v902 OCF: OCF-M second class set (owner-rule follow-up)
#define OCF_BITS 16
inline constexpr int OCF_TAB[2] = { 0x4F434631, OCF_BITS }; // slot 0 magic keeps it out of .bss

// SWG (b2395, spec_swg_1113, owner replay 01a1d410): switch gears. 0 = nova_b14894_pgl6cs. Bits: 1 = EDGE-PRICED PACK CLEAR (a wolf-only
// group of 12+ is priced from its rim: the fewest attackers in reach of a stand tile, for the clear time; it may take the multi-trip path).
// SWG bit 4 (b2394, folded into SWG 1's pack class per Aggression): within SWG4_R rounds of a camp_out reversal, while an awake camp of a
// pack group (n_wolf >= 12, wolf-only) threatens within SWG4_D of me, errand_stage skips the bank errand. Reads with bit 1 as one arm (5).
#define SWG4_R 10
#define SWG4_D 8
#define SWG4_END 100 // RC C1256: the game-end bank rows are exempt
// SWG bit 16 (b2395, STAND-OFF, ranged kits): on a pack target my hit tile minimises the living wolves whose reach covers it (free, a wolf in
// my range, out of a seen foe's one-turn reach); no hit when every such tile has more than SWG_K (slot 2) wolves in reach.
#define SWG_K 2
#define SWG_FM 60000 // fuel margin (slot 3, Builder 13 Nov adaptation): SWG's grid / rim / pick work runs only with fuel_remaining above it
// v903 SWG: baked at its shipped value
#define SWG_BITS 21
inline constexpr int SWG_TAB[4] = { 0x53574731, SWG_BITS, SWG_K, SWG_FM }; // slot 0 magic keeps it out of .bss
// CGB (b2388, Path Finding cage fm_1fdf80_279 v855, exact puppet; owner "fix all the variants"): gbf_blocked/blocked close every group
// whose path trace (gates_step, fixed camp tiles, traced once) crosses a gate group the whole team cannot clear (team_feasible), so a
// caged spawn stays target-less even after a ring camp dies (Vesper on spawn r375-2000). Runtime data flag CGB_TAB[1], read first;
// 0 = v863. Bit 1 BREACH SEEN: a closed group counts as open when it is reachable from our spawn with only the LIVING camp tiles of the
// gate groups blocked (a gate member tile seen empty is dead); that field is rebuilt only when a seen gate member changes state, with
// CGB_FLOOR + 3 x w x h fuel left. Bit 2 ONE CAMP: a ring gate group (M.ring_camps, gate_step) whose cheapest one-camp breach (least
// hp x str, not a monolith or golem, ring_breach's refusal) exists does not close (ring_breach attacks that camp). Bit 4 LAST RESORT:
// after CGB_N choices in a row with no group while caged (cgb_caged), the gates stop closing groups for me until a choice finds one, and
// redirect_to_gate keeps (no drop/ban) a caged body's target behind the ring gate. Bit 8 STALE CLAIM: claim_target drops the ring breach
// claim on a turn its holder did not run the breach (ring_last != now). Bit 16 TEAM BREACH: while caged, every body breaches the same
// cheapest ring camp (least hp x str, then nearest the spawn); no 'a ranged mate / a lower slot breaches' return. Bit 32 NO HOLD UNDER
// THE RING: while caged and below 97% HP inside a living ring camp's reach, step out of those reaches before the spawn heal hold.
#define CGB_BITS 63
#define CGB_FLOOR 30000
// v906 CGB: CGB free bodies on caged spawns v904
#define CGB_N 6
inline constexpr int CGB_TAB[2] = { 0x43474231, CGB_BITS };

// b2408 PCM (Prism Planner spec_pcm, owner on 01a1d5e9: "Make prism's capture multiplier much higher as she should of claimed the first camp
// not marcella"; "Instead of ever splitting between our 2 carries we should most of the time donate to primary"). Runtime data flag PCM_TAB[1],
// read first; 0 = v904. Bit 1 RANK: on a group with gems >= PCM_G (slot 2) and our Prism alive within 6 of its anchor, cap_rank ranks her
// PCM_R (slot 3) ahead and drops PKW's gold pull for her mates. Bit 2 STAND: she steps onto a free member tile a mate already holds (no foe
// within 8), and a non-Prism mate holds off starting / hands over the capture while she stands within 2 of a member tile (CAP_RELAY).
// Bit 4 SECOND CARRY: while our Prism lives, Marcella / Vesper lose their carrier rank and stack bonus on gem groups (gold-only keep theirs).
#define PCM_BITS 1
#define PCM_G 15
// v907 PCM: PCM variant PCM_BITS=1
#define PCM_R 400
inline constexpr int PCM_TAB[4] = { 0x50434D31, PCM_BITS, PCM_G, PCM_R }; // slot 0 magic keeps it out of .bss
// b2379 RTL (Shared Mem's RTC lazy writer + band edges v2, teamword_bits.tsv 'RTC BAND EDGES v2'; owner "stop parking"). Runtime data flag
// RTL_TAB[1], read first; 0 = live. Bit 1: rtc_turn writes only on the channelling body's own turns (tribute start / band change, and the
// clear on land, cancel or its first dead turn while it owns the field); the field's age (value + round first seen + tributed_us then) is
// kept inside rtc_value, i.e. only when a reader decides; the need bands are v2 (1: need <= 10, 2: <= 25, 3: <= 50, 4: <= 80, 5: <= 120,
// 6: <= 200, 7 more; OLK's reader tests band != 0 only).
// v908 RTL: RTL lazy RTC writer + v2 band edges
#define RTL_BITS 1
inline constexpr int RTL_TAB[2] = { 0x52544C31, RTL_BITS };

// BNX (b2368; RC X912 /data/USER/rulecheck/p6/x912_bounds.md): the target search's pruning bound (group_bounds) sat below the rate it
// bounds, so best_group / lah / the opening sim could prune a group that would win. Each bit only raises a bound, applied once per bounds
// pass before group_bounds_finish (econ_choose_target.cc bnx_bounds). Bit 1 BNX1: my Willow's bound takes rate_for's wl2_pull (the
// dead rcb_pull 1.0f). Bit 2 BNX3+4: my Vesper's bound is at least VTK's take-over rate, the best slot's group_value over the payment
// time (cs.timer cleared, trav + 1 alive). Bit 4 BNX2: on FAR20 the bound takes the largest sqrt(ECL cell) over walk buckets >= wb(tr).
// Read first; 0 = live v891.
// v911 BNX: REB BNX SCL XCB4 (owner ship) v910
#define BNX_BITS 5
inline constexpr int BNX_TAB[2] = { 0x424E5831, BNX_BITS }; // slot 0 magic keeps it out of .bss
// b2384 PCR (Prism Planner after the exact puppet of owner replay 01a1d61a; owner: "make her bonus apply when there is a some gem ratio to
// gold ratio on camps"): runtime data flag PCR_TAB[1], read first; 0 = v907. Bit 1 RATIO: on a group with gems x PCR_GV >= gold and gems
// >= PCM_G with our Prism alive within 6 (PCM's test), the mates' gold-fit stack term (planner capture_rank_fit) and the PKW gold term
// are not applied, and her 10 x shards term is 0 (cap_rank, econ_capture.cc; added to PCM bit 1's -400). Bit 2 RELAY CONSISTENCY:
// mate_holds_region takes should_capture's Prism relay exception (a non-Prism mate on her plan group, no enemy in sight, does not
// make her drop it). Bit 4 HANDOFF (RC X914 #1): the same exception in capture_region_handoff and mate_holds_capture_region_turn.
// Arms: 7 at GV 4 (lead), 6 (--bugbar), 7 at GV 3 and GV 10.
#define PCR_BITS 6
// v912 PCR: PCR6v Prism relay consistency (flag-first)
#define PCR_GV 4
inline constexpr int PCR_TAB[3] = { 0x50435231, PCR_BITS, PCR_GV };

// CNF (b2405; Deep spec_cnf_1113: our carry passes the nearest worthwhile group at spawn exit for one >= 4 farther, 2.39 v 1.73/g v the top 3,
// and a mate then hits the passed group). Runtime data flag CNF_TAB[1], read first; 0 = v903. Bit 1 (cltf_carry_pick, CLTF bit 4's loop): at
// spawn exit (home_dist() <= CNF_EXIT), safe by state (the visible foes' two hits within reach + 2 under my HP + shield, not the 50% gate),
// a non-carry mate's claim on a live walk non-siege gold/gem group within CLTF_TRAIL whose carry I am also qualifies when the mate is within
// CNF_MATE of its anchor or nearer to it than I am, and my own target (if any) is >= CNF_GAIN farther: no CLTF_TRAIL early-out for it. Pay:
// capture rewards are shared among allies present (GR:196); CLTF bit 1 (live) lets the clearer leave, so the carry is paid there.
// Bit 2 (b2409; Deep, after cnf1 .5215 -> .5023): the same take at ANY pick, not only at spawn exit: safe by state, a non-carry mate's claim
// (the shared claim channel, any slot) on a live walk non-siege gold/gem group whose carry I am, within CNF_EXIT of me, my target >= CNF_GAIN
// farther; checked after CLTF bit 4's cleared-group pick, before the CLTF_TRAIL early-out.
#define CNF_BITS 2
#define CNF_EXIT 3
#define CNF_MATE 4
// b2405 variants of bit 2 (Builder 13 Nov, cnf2 near miss .5085): bit 4 WIDE: a group also qualifies when a seen non-carry mate stands within
// CNF_WIDE of it (claimed or not); bit 8 VESPER: bit 2 only for a Vesper carry; bit 16 VALUE: the near group must be worth >= CNF_VAL_X100 %
// of my current target's group_value. The margin CNF_GAIN is slot [4] (cnfav = CNF_GAIN=2).
#define CNF_GAIN 2
#define CNF_WIDE 6
#define CNF_VAL_X100 70
inline const volatile int CNF_TAB[7] = { 0x434E4631, CNF_BITS, CNF_EXIT, CNF_MATE, CNF_GAIN, CNF_WIDE, CNF_VAL_X100 }; // slot 0 magic keeps it out of .bss
#define CNF_ON(b) ((CNF_TAB[1] & (b)) != 0)
// b2429 SHV (Econ spec_shv_1113, 03homonoliths v Mite): heavy groups (monolith / golem) with a member in attack range of one of OUR spawn
// tiles (GR:153: standing there heals; GR:254 Chebyshev range, ranged 3, melee 1). Runtime data flag SHV_TAB[1], read first; 0 = v908.
// Bit 1 BUDGET: for such a group (contest <= .45) whose crew has a body that can hit it from a spawn tile, the camp damage of the
// budget test is 0 (tfe_feasible / estimate), RC C1392: every body has a spawn tile in reach, str_sum under the tank budget. Bit 2 STAND: the tank / support walk to such a group goes to the spawn tiles in range,
// and a body standing on one (hp above the group's strength sum) does not bail.
#define SHV_BITS 3
inline const volatile int SHV_TAB[2] = { 0x53485631, SHV_BITS };
#define SHV_ON(b) ((SHV_TAB[1] & (b)) != 0)
