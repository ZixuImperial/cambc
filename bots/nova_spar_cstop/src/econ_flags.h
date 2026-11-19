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
#define OWN_KIT_RULES_BITS 2
inline constexpr int OWN_KIT_RULES_TAB[2] = { 0x4B4F3131, OWN_KIT_RULES_BITS }; // Varg splash priced at 0.26 per extra camp
constexpr int OWN_KIT_RULES_BIT_SSC = 1, OWN_KIT_RULES_BIT_AREA = 2, OWN_KIT_RULES_BIT_HOLD = 4, OWN_KIT_RULES_BIT_RSH = 8, OWN_KIT_RULES_BIT_MCI = 16, OWN_KIT_RULES_BIT_BGC = 32;
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

// A group's approach tiles come from its first two members only (step_groups), so a group listed centre-first has an empty approach
// and d_altar / xt_sp read UNREACH (rate_for then prices the altar walk at 30). bit 1: play only (not the draft's M.init),
// step_distances sets d_altar = 1 + min f_altar over every member's 8 in-bounds neighbours outside block_camps; the approach vector
// and draft memory are untouched. bit 2: step_approach refills an EMPTY approach from every member's neighbours (not block, not a
// camp tile), at most 16; moves xt_sp, the planner and the draft's distances. bit 4: bit 1 only for groups whose approach read is
// UNREACH (empty or dead-end approach); others keep the old value. Runtime data flag, read first; 0 = off.
#define APX_BITS 4
inline constexpr int APX_TAB[2] = { 0x41505831, APX_BITS }; // altar walk from all members where the first-two-members read is unreachable
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

// Target-choice caps. Runtime data flag (0 = off; flag read first), one bit per idea. Bit 1: crew_bonus capped at TCA_CBCAP/100, so
// a pair on a gem camp keeps part of the second body's price (its readers, join gate and bound, see the capped value). Bit 2:
// group_value's gold x TCA_GOLD/100. Bit 4: the 61+ contest cell capped at the 31-60 cell of the same walk and size.
#define TCA_BITS 0
#define TCA_CBCAP 150
#define TCA_GOLD 70
inline constexpr int TCA_TAB[4] = { 0x54434131, TCA_BITS, TCA_CBCAP, TCA_GOLD }; // slot 0 magic keeps it out of .bss
constexpr int TCA_BIT_CREWCAP = 1;
constexpr int TCA_BIT_GOLD = 2;
constexpr int TCA_BIT_ECLCAP = 4;
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
#define RWS_BITS 1
inline constexpr int RWS_TAB[2] = { 0x52575331, RWS_BITS }; // Willow build takes the normal stat test

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
#define RTM_MODE 0
#define RTM_MARGIN 8
inline constexpr int RECALL_WALK_COST_TAB[3] = { 0x42373635, RTM_MODE, RTM_MARGIN }; // slot 0 magic keeps it out of .bss

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
#define LKB_BITS 1
inline constexpr int LKB_TAB[2] = { 0x4C4B4231, LKB_BITS }; // with both teams' locks on one altar tile, bank start skips it
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
#define SGC_BITS 1
inline constexpr int SGC_TAB[2] = { 0x53474331, SGC_BITS }; // slot 0 magic keeps it out of .bss
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
#define ALT_TWIN_BITS 1
#define ALT_TWIN_R 4
inline constexpr int ALT_TWIN_TAB[2] = { 0x414C5432, ALT_TWIN_BITS }; // slot 0 magic keeps it out of .bss
constexpr int ALT_TWIN_BIT_TWIN = 1;
constexpr int ALT_TWIN_BIT_WALK = 2;

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
#define FHC_BITS 7
#define FHC_CALL_X100 130
#define FHC_JOIN_R 8
#define FHC_PEEL_X100 60
#define FHC_BODY_G 40
inline constexpr int FHC_TAB[2] = { 0x46484331, FHC_BITS }; // slot 0 magic keeps it out of .bss

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

#define WCK_BITS 7
#define WCK_TURNS 2
inline constexpr int WCK_TAB[2] = { 0x57434B31, WCK_BITS }; // slot 0 magic keeps it out of .bss

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
#define WFF_BITS 5
inline constexpr int WFF_TAB[2] = { 0x57464631, WFF_BITS }; // slot 0 magic keeps it out of .bss
#define WFF_STK_MIN 80 // bit 4: the stake's floor, gems
#define WFF_STK_E0 20 // bit 4: engage bar + (E0 + E1 x stake) / 100
#define WFF_STK_E1 80
#define WFF_STK_F0 10 // bit 4: flee bar + (F0 + F1 x stake) / 100
#define WFF_STK_F1 50
inline constexpr int WFF_STK_TAB[6] = { 0x5746534b, WFF_STK_MIN, WFF_STK_E0, WFF_STK_E1, WFF_STK_F0, WFF_STK_F1 }; // bit 4 values
