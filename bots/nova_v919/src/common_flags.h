#pragma once
// common_flags.h: flags and tunables read by more than one module.

// MFB: a bundle of minor fixes. Runtime data flag MFB_TAB[1], read first; 0 = off. One bit per fix: 1 OEG2 (OEG bit 2's branch), 2
// DLKS (lower-slot unseen claimant near the region pins), 4 DLKF (a pinning mate has >= 40% HP), 8 AGH (RTG bit 8, area ghost), 16
// LRP (lr_pos only for the group still respawning), 32 CPY (capture_pay_in uses the engine's cap_on), 64 CSP (the CS9 reader prices
// a seen foe's Capture emblem), 128 LHY (handle_low_hp keeps the foe-near leave bar MFB_LH_N rounds after a foe-near leave), 256 RFK
// (RFM bit 2: an unseen tile that refused my step stays blocked next turn), 512 NWK (the farm area spell skips tiles that wake
// another group's sleeping attacker), 1024 SP1 (spawn_step on the spawn-heal turn), 2048 PN1 (no switch bar on a just-chosen target
// when best is MFB_PN_NEAR+ nearer), 4096 B85 (hold budget x MFB_B85_PCT/100), 8192 TSS (foes resting on their spawn beyond 3 don't
// blacklist a group), 16384 FCL (RC9 bit 2, free cluster; bit 8 stays off, it needs 16), 32768 ESD (BGX bit 4, estimate dead), 65536
// XPS1 (parting_stun_for_stun_kits: a stunned chaser doesn't veto), 131072 XPS2 (the same in Prism's parting_stun), 262144 LHG (BGC
// bit 4, low-HP goal), 524288 CGL (a low body caught with no foe in basic range flees), 1048576 RFH (free hit on an attacker-free
// camp at an idle turn end), 2097152 PSA (Prism's free basic after parting_stun / spell_poke), 4194304 RPC (no shop trip that lands
// before the capture under me pays), 8388608 AH (no farm area spell at >= 50% HP with a foe seen within 6), 16777216 MIF (a melee
// support whose focus has no free safe tile hits another living member it can reach instead of idling), 33554432 OWL (a bush tile
// within 1 of the altar and a living mate out of sight: no lock before my tribute, it would cancel her unseen channel), 67108864
// R3B60 / 134217728 R3B100 (own-tribute lock min bag 60 / 100; winning tributes and Prism carry unchanged), 268435456 LKR (lock_hit:
// reset and a second hit when hits remain, bag >= 30, no foe within 8), 536870912 WALT (a winning non-Prism bag with a seen foe
// within 4 of the near altar walks to a foe-free altar tile when channel_survives_known_foes passes), 1073741824 FINF (bank_first at
// walk <= 1 in finish mode, non-Prism: channel_survives_known_foes instead of the t_hit refusal, TRIB_GUARD skipped).
#define MFB_BITS 1345051896
#define MFB_LH_N 4
#define MFB_PN_AGE 8
#define MFB_PN_NEAR 3
#define MFB_B85_PCT 40
inline constexpr int MFB_TAB[6] = { 0x4D464231, MFB_BITS, MFB_LH_N, MFB_PN_AGE, MFB_PN_NEAR, MFB_B85_PCT }; // slot 0 magic keeps it out of .bss

// PSY: general-path fixes for Prism; her core rules are untouched. Runtime data flag PSY_TAB[1], 0 = off. Bits: 1 (MF2 bit 2 RHG for
// Prism at the travel recall-hop: no recall hop within 8 rounds of a crystal landing), 2 (RHG for Prism in want_bank's walk estimate
// and bank_i's recall-hop; bank rules unchanged), 4 FHP (FINISH HOLD flee_race_allowed for Prism; its bag < 60 rule stays), 8 CRX
// (crystal escape crystal_escape_turn for Prism).
#define PSY_BITS 11
inline constexpr int PSY_TAB[2] = { 0x50535931, PSY_BITS }; // Prism RHG + CRX
#define HUNT_BITS 134
#define HUNT_FUEL 45000 // below this fuel at assess the hunt is off for the turn (95% of cuts come at under 30k, on 0.3% of its firings)
inline constexpr int HUNT_TAB[3] = { 0x48554E54, HUNT_BITS, HUNT_FUEL }; // HUNT: leash race uses lower bound

// DRAFT values only: Marcella is drafted up.
#define DRAFT_MA_PP 6.0f // DRAFT: pp per slot, every team size
#define HOLE_SHORT_MIN 12 // Only walks of this many steps or more look for a shortcut over a hole.
#define HOLE_SHORT_GAIN 4 // The dash route must save this many rounds to be taken.

// MCL MAPCLASS: rules that lose on a map type stay off there; the type is draft-determined from map data. The draft computes class
// bits once (map_class_compute) and stores them in draft memory (dmem extra MCL_XID, 8 bits); champions read them through
// map_class() (fallback when absent: the same computation from M.groups). Bit 1 FAR20: the walk from our spawn to the nearest
// walkable camp group >= MCL_T1; bit 2 FAR40: >= MCL_T2. Runtime data flag MCL_TAB, read first: MCL_BITS bit 1 = the draft writes
// the field; MCL_OFF_DLT / MCL_OFF_OPD = class bits on which DLT bit 1 / OPD bit 4 stay off. 0 = off.
#define MCL_BITS 1
#define MCL_T1 20
#define MCL_T2 40
#define MCL_OFF_DLT 1
#define MCL_OFF_OPD 0
inline constexpr int MCL_TAB[6] = { 0x4D434C31, MCL_BITS, MCL_T1, MCL_T2, MCL_OFF_DLT, MCL_OFF_OPD }; // MCL map class
#define MCL_XID 14
// MCL3 (Shared Mem skeleton, v718): one shared draft-time class byte (dmem extra MCL3_XID, 8 bits) for the MCL3 owners. Each owner adds ONE
// line to mcl3_compute() (plan_map_classes.cc) behind its own flag; map_class3() reads it (absent: the same computation once M is done).
// With every owner off the value is 0 and the draft writes nothing. Bits: 1 GOLDRACE, 2 HEAVY_GE50, 4 ISLAND_HOP, 8 BUSH_ALTAR, 16+32 GSC, 64 CORR.
#define MCL3_XID 10
// MCL4 (Shared Mem skeleton, b1866): the second owners' class byte (dmem extra MCL4_XID, 8 bits), same form as MCL3: one line per owner
// in mcl4_compute() behind its own flag; map_class4() reads it. Every owner off: 0, nothing written. Bits: 1 TAVI_BG (TBG).
// MCL4 bit 128 = JKC (b2088, jackpot class: jkc_class_group(); ledger /data/zw4424/st/sharedmem/classbits.tsv).
#define MCL4_XID 5
// TBG (b1802 TAM-S class, b1866): MCL4 bit 1 TAVI_BG = gem + gold cluster camps >= .80 of all camps, no elk/golem/monolith camp and gold
// cluster camps >= .50 of the cluster camps (tools/lab/mapclass.d/tavi_bg.py). Runtime data flag TBG_TAB[1], read first; 0 = v753.
// v754 TBG: MCL4 byte + TAVI_BG class bit (store-only)
#define TBG_BITS 1
inline constexpr int TBG_TAB[2] = { 0x54424731, TBG_BITS };
// NBF (b1844, RC X276 x276_floors.md): near-budget fuel floors at the v717 cut stacks. Runtime data flag NBF_TAB[1], read first; 0 = v717.
// 1 HFB3 hfb_bush_scan returns at once on an unarmed turn at <= ESC_AWAY_FUEL (identical); 2 TRD1 tribute_restart_hold skips its dead
// bush list (identical); 4 CRF1 crystal_escape_turn's fuel test before channel_safe (identical); 8 DAF1 dash-away floor; 16 FVV1 fight
// volley-veto floors (hold); 32 CAF1 camp area/dash floors; 64 WCF1 publish floor; 128 HPR1 hpr_refresh floor 2k + SCR1 crystal-route
// estimate 3000 + 80 per landing. Floors in slots 2-7.
#define NBF_BITS 7
#define NBF_DAF 15000
#define NBF_FVV 15000
#define NBF_FVVL 8000
#define NBF_CAF 15000
#define NBF_CAFD 10000
// v721 NBF: near-budget floors, identical rows (NBF)
#define NBF_WCF 4000
inline constexpr int NBF_TAB[8] = { 0x4E424631, NBF_BITS, NBF_DAF, NBF_FVV, NBF_FVVL, NBF_CAF, NBF_CAFD, NBF_WCF }; // slot 0 magic keeps it out of .bss
// NBF firing markers (the diag copy counts their entries; empty in release): the floor bound where the base went on.
__attribute__((noinline)) inline void nbf_fc_1() { __asm__ volatile(""); }
__attribute__((noinline)) inline void nbf_fc_2() { __asm__ volatile(""); }
__attribute__((noinline)) inline void nbf_fc_4() { __asm__ volatile(""); }
__attribute__((noinline)) inline void nbf_fc_8() { __asm__ volatile(""); }
__attribute__((noinline)) inline void nbf_fc_16() { __asm__ volatile(""); }
__attribute__((noinline)) inline void nbf_fc_32() { __asm__ volatile(""); }
__attribute__((noinline)) inline void nbf_fc_64() { __asm__ volatile(""); }
__attribute__((noinline)) inline void nbf_fc_128() { __asm__ volatile(""); }

// SQM / ACW: who the fight code counts as a mate. Runtime data flag SQM_TAB, read first (0 = off). 1 SQM: squad_mate_covers_focus
// (PAIRS strike gate) counts a mate only if it can hit the focus on its next turn: not stunned, not channelling, not fleeing by its
// claim (TM2 kind 4, stance FLEE), and within range + 1 of the focus, or a ready damage / stun / area spell's range, or range + 1 +
// dash range with a ready dash (one cast a turn: the best one). The 'any mate within 3 of me' arm is dropped. 2 ACW:
// ally_commit_weight weights foe-near 1.0 -> SQM_W1 %, me-near 0.9 -> SQM_W9 %, hurt x0.4 -> x SQM_HURT %.
#define SQM_BITS 2
#define SQM_W1 76
#define SQM_W9 66
#define SQM_HURT 55
inline constexpr int SQM_TAB[5] = { 0x53514D31, SQM_BITS, SQM_W1, SQM_W9, SQM_HURT }; // SQM: ACW: ally_commit_weight weighs mates by whether they can fight
constexpr int MCL_BIT_ONEGEM = 4;

// SSF: spawn-monolith groups. Runtime data flag SSF_TAB, read first (0 = off, byte for byte). Bits (spawn_siege_find_groups,
// map_class_compute): 1 FIX: spawn_siege_find_groups's SSG 'other' gem count leaves out groups within Chebyshev 3 of the ENEMY spawn
// (the foe's mirrored home group). With the bit off it counts them, so SSG is off on every symmetric spawn-monolith map. 2 CLASS:
// SSG also needs MAPCLASS bit 8 SPAWNECON, set by the draft (map_class_compute, map data only): walk from our spawn to beside the
// enemy spawn >= SSF_S2S, a monolith group within 3 of our spawn, and the gems of groups clear of both spawns (Chebyshev > 3) <=
// SSF_OPCT % of that group's gems.
#define SSF_BITS 0
#define SSF_S2S 50
#define SSF_OPCT 10
inline constexpr int SSF_TAB[4] = { 0x53534631, SSF_BITS, SSF_S2S, SSF_OPCT };
constexpr int SSF_BIT_FIX = 1;
constexpr int SSF_BIT_CLASS = 2;
constexpr int MCL_BIT_SPAWNECON = 8;
constexpr int MCL_BIT_CLUSTER = 64; // v716 ACX (Shared Mem): attacker groups hold < 10% of the walkable gems; set only while ACX is on
constexpr int MCL_BIT_GOLDFREE = 128; // v716 ACX (Shared Mem): walkable gold per champion < 60 (the F_GOLD_RATE test); set only while ACX is on

// FXDR: draft fuel cuts. Runtime data flag, read first; 0 = full draft work, byte for byte. Every bit gives the same picks and the
// same draft-memory bytes: 1 XT: travel_build_step reads each walk group's approach tiles through precomputed field offsets (same minimum). 2
// LATER: later draft turns reuse prism::write_plan / om_write bytes and map_class_compute's value (all static once M.done()). 4 (unused).
// 8 ENUM: enumerate_all caches set_terms per lineup across re-enumerations (keyed on everything set_terms
// reads). 16 DM3: draft_launch_scan reads the launch pairs through precomputed field offsets. 32 MCL2: compute_map_class_bits's 7x7 camp window scans
// row camp masks (same union order). 64 FC: travel_build_step keeps its fields of DM3's top groups (same walls, same roots); draft_launch_scan reads
// them instead of recomputing. 128 DSC: draft_swap_cell_code's map totals (gems, gold, clusters, heavy gems, wall and hole tiles) computed once,
// tiles by masked popcount. 256 PLAN: make_plan lists the admissible lineups once (index order) and runs passes 2 and 3 over that
// list only.

// CDW: one flag word, runtime data flag, 0 = off. A dasher's skip over a thin hole (walk to a launch tile, one 2-tile dash over the
// hole (Q42 middle rules), walk on) beats the walk around. Static part: the thin-hole launch pairs, built once per body; per use:
// the host BFS from me, the cooldown, the live middle test. Bit 1 SC: spawn_crystal_start does not buy the crystal when that skip
// arrives no later than the hop (and the walk then takes the skip). Bit 2 TRAVEL: every step_field walk takes such a skip when it
// saves HOLE_SHORT_GAIN rounds (walk-then-dash; dash-then-walk is travel_dash's). Bit 4 MH: mid_hop_try (a carried crystal's
// mid-route hop) does not hop when that skip arrives no later than the hop, and the walk on that field then takes the skip. Bits
// work on their own and together.
#define CDW_CNT(k, c) ((void)0) // CDW fire count: the diag copy records site k when c; release: nothing, c unevaluated

// Crew-pooled bail: one flag word, runtime data flag, 0 = off. Bit 1 POOL: the crew bail's "leaves before the kill" is a mate below
// its own bail line (not one that can't take every remaining hit alone), and a body skips its own camp bail while the crew's pooled
// holding rounds (each hitter down to its own bail line) cover the kill and I take no hits now (a mate is nearer to each attacker)
// or can step out next turn.
#define BH81_BITS 256
inline constexpr int BH81_TAB[2] = { 0x42483831, BH81_BITS }; // slot 0 magic keeps it out of .bss
constexpr int BH81_BIT_SRT = 1, BH81_BIT_HSD = 2, BH81_BIT_LTE = 4, BH81_BIT_LTL = 8, BH81_BIT_FTD = 16, BH81_BIT_LWD = 32, BH81_BIT_DAR = 64, BH81_BIT_EDW = 128, BH81_BIT_CRL = 256, BH81_BIT_BGK = 512;
#define BH81_CNT(k, c) ((void)0) // fire count: the diag copy records site k when c; release: nothing, c unevaluated

// Code error fixes: one bit per verified code error. Runtime data flag, 0 = off (read first). 1 WBR2 (channel_holds): a kept recall
// whose bag now wins (econ::bag_wins_with_mates) is cancelled when the altar walk from here beats the recall's ticks left + the
// home-altar walk and bank_winning_bag would bank it (its own guards); the turn goes on to early_stages, where bank_winning_bag
// takes it. Without it, channel_holds returns before bank_winning_bag for every kept recall. WBR2 cancels only when gems +
// tributed_us grew since my last free turn (the recall did not start with the winning bag: bank()'s own recalls are kept). 2 CVH
// (assess_converge_worth): the bodies counted near the mate in contact are only those at >= CONVERGE_ALLY_HP (the mate's own bar);
// otherwise a 1-HP mate counts as a full body. 4 HFP (hidden_fire_slow): an unexplained hit (no camp could cover me) taken while a
// capture pay hold returns early is remembered in hfc_prev, so the next unexplained hit within 2 rounds is 'again' (HFC's bush
// escape) as it is outside a pay hold. 8 unused. 16 FRB-A (the retreat-tile setter): a visible mate within 4 at the escape priority
// 40 (this round's or next round's value) keeps its retreat tiles (free neighbours farther from every foe within 8 of it): they join
// my move mask this turn unless I flee myself (stance FLEE or the low-HP rule of set_dynamic_turn_priority). Only while the mate's
// nearest visible foe is within CODE_ERR_FIX_FRB_D tiles. 32 FRB-B (set_dynamic_turn_priority): priority 40 also when the visible
// foes within 9 deal >= my HP + shield on their next turns (combat::visible_foes_lethal_next_turn, IRB's one-turn lethal_burst_hit
// sum), so the threatened body moves first next round.
#define CODE_ERR_FIX_CNT(k, c) ((void)0) // fire count: the diag copy records site k when c; release: nothing, c unevaluated

// SPH: the spawn heals to full at the END of the body's own turn (GameRules.md:153, docs/rules/20_interactions.md Q43), so every foe
// or camp hit before its next turn lands after that heal. Runtime data flag, 0 = off (read first). 1 LB (bolder):
// lethal_burst_assess on a spawn tile prices staying with the healed eff HP (max HP + shield), not the current one. 2 CAMP (bolder):
// a hurt body on a spawn tile under awake camp reach stays one turn to heal when one round of camp hits is below its healed HP and
// the stay gains HP (generalises the spawn-trap stay); camp_out's escape runs the turn after. 4 FIGHT (cautious): a body on a spawn
// tile missing >= SPH_FMISS % of its HP fights from the spawn (hits from the tile, steps and dash landings onto spawn tiles); it
// leaves only for a sure fight (ratio >= SPH_FR_X100 / 100) or a focus my burst kills. 8 BAR (cautious): with a foe seen within
// SPH_NEAR (a fight ahead, so HP is worth more than one turn's step), the spawn-exit bar .97 becomes SPH_GO_X1000 / 1000; with none,
// the old bar.
#define SPH_BITS 3
#define SPH_GO_X1000 990
#define SPH_FMISS 10
#define SPH_FR_X100 300
#define SPH_OLD_GO_X1000 970 // The old bar for leaving the spawn on an errand, used with bit 8 off.
#define SPH_NEAR 12 // Bit 8: the new bar holds only with a foe seen this near (a fight ahead); farther away, the old bar.
inline constexpr int SPH_TAB[7] = { 0x53504831, SPH_BITS, SPH_GO_X1000, SPH_FMISS, SPH_FR_X100, SPH_OLD_GO_X1000, SPH_NEAR }; // spawn heal priced before leaving spawn: lethal_burst_assess cap
constexpr int SPH_BIT_LB = 1, SPH_BIT_CAMP = 2, SPH_BIT_FIGHT = 4, SPH_BIT_BAR = 8;
#define SPH_CNT(k, c) ((void)0) // fire count: the diag copy records site k when c; release: nothing, c unevaluated


// Heal and assess fixes: runtime data flag, flag read first, zero work at 0. 1 GHA: assess's FL3a read of a HELP image uses
// comms::event_age_rounds (as every ghost-image reader does); otherwise the 5-bit stamp's age alone makes an image kept past 32
// rounds read as fresh. 2 THS: try_heal skips a mate on our spawn; the spawn fills it at its turn end (interactions Q43),
// support::heal skips it. 4 THG: try_heal reads the host's gem count when al.gems reads 0 (al.gems is read only near a foe). 8 WCK:
// support::incoming_on and camp_hazard take camp Strength x Durability x Jungle for mates (GameRules.md:307-309), as for my own
// body, not raw Strength against HP. 16 HVS: after my step W.allies is still perceive's; a mate my new tile can't see refuses the
// heal (rc 30), so heal and try_heal skip it. 32 TKW: intel_taken keeps a live timer inside [at - NEWS_TTL - 1, at]: TM2 bit 16
// carries only the post's parity and news waits up to NEWS_TTL for the slot, so `at` is a latest bound and must not overwrite the
// timer a body held.
// STRIPPED (FL6): no reader of HEAL_ASSESS_FIX_TAB in this tree; deadstrip.py find HEAL_ASSESS_FIX before arming.
constexpr int INTEL_NEWS_TTL = 20; // rounds a group news item waits for the slot (intel.cc NEWS_TTL)

// Rule fixes. Plain define, flag first, zero work at 0. 1 HEALSELF: Willow can't heal herself (Q43 rc 30): support_heal_pool counts
// my heal only with another friend in the fight; enemy_heal_pool counts a foe healer only with another foe within 8. 2 HKLMID:
// dash_middle_ok is dash_legal_between (a fogged camp tile may hold a living camp: blocks, Q42). 4 BGCMATE: the blind bush area cast
// skips no centre with a mate inside (no friendly fire, Q45); a mate's tile is no candidate. 8 CREWHEAL: Crew heal8 counts a
// member's heal only once the crew has a second body to heal (solo Willow: 0). 16 STALLCARD: the stall fix steps only to a bush of
// the target bush's cardinal cluster (cardinal neighbour first, a diagonal one only with a cardinal bush link; Q44 bush clusters are
// cardinal). 32 TSKEARN: the tie seek's nothing-to-lose test uses gold I have EVER held (lifetime earned), not unspent gold
// (GameRules.md:27-35). 64 WARDCAMP: a ward may go on a visible camp spawn tile with no living camp (Q44: a ward does not delay the
// respawn). 128 FOETRIB: a foe's tribute length with its Tribute emblem as last read (rs::tribute_turns_of): ALH ticks, WKH
// foe_banks_winning_bag_first. 256 CIBAG: hunt_prize of a foe Cassi/Issac adds its visible partner's bag (they die together; the
// killer takes both bags). 512 CRYSTUN: the crystal foe bar also refuses a visible foe whose ready stun reaches me after two walks
// (a stun cancels the channel and the crystal is lost, Q46). 1024 VSPLASH: lethal_burst_damage_sum adds a foe Varg's splash through
// a mate within 1 of the tile when its own hit can't reach the tile.
#define KIT_RULE_FIX_CNT(k, c) ((void)0) // Fire count: the diagnostic copy records site k when c holds (new answer != old); release builds do nothing and do not evaluate c.

// VSP: Varg splash on camps (the models would count 2-3x the bodies a splash hits). Runtime data flag VSP_TAB[1], read first; 0 =
// off. Bit 1 CAMP (cautious): kit_dps, kit_dps_pack1_and_3's pack-3 basic and spawn_siege_kill_dps take varg_layer::camp_splash_extra(pack) extra bodies a
// basic (measured 0.26 x (pack - 1)) instead of 0.7 x (pack - 1) / x2.4 at pack 3 / min(2, pack - 1); Crew::dps / dpsf, the clear
// estimates, the threat bail, zone dps and the RCG rally read them. Bit 2 ONE (GameRules: the splash hits the target's neighbours,
// never the target): horizon_dps1, damage on ONE body, counts splash, area and landing once (horizon_fit's DPS_AREA_HITS 1.3 only
// for strength calls; DFX bit 8's rule on the fit). Varg splash bodies are measured; area stuns cover all.
#define VSP_CNT(k, c) ((void)0) // VSP fire count: the diag copy records site k when c; release: nothing, c unevaluated

// CTM: combat half of the timer census. Runtime data flag slot 1, read first; 0 = off. Bit 4 RCW: go_home's walk (home within 7)
// yields to a SAFE recall when the recall lands sooner (home farther than the recall time: 4 pre-fired / 5, Home 3;
// rs::recall_rounds under CBN bit 32). Unsafe: the walk. FCS: focus-aware damage sums. Runtime data flag FCS_TAB[1], read first; 0 =
// off. Bit 1 SIMX: a melee damaging stun on a stun-immune focus (Marcella, GameRules.md:658) only when lethal, or when no stunnable
// foe stands within its cast range + a walk allowance of me (the cooldown has no other use soon). Bits 2-16 FOCUS: a foe hits the
// ONE body of ours in its reach with the best value per HP (fcs_share), so a foe whose best target is a mate adds only the floor
// fraction of its damage to sums on me. Bit 2 top sums: assess incoming, hd race inc. Bit 4 danger_at (expected value; keep it off
// danger_veto). Bit 32 lethal_burst_damage_sum (a veto: worst case stays at 0). Bit 8 other sums: engage counts,
// channel_damage_threat, foe_damage_over_ticks, support, brain damage_in / finish_first. Bit 16 other vetoes: the Heart landing
// veto, IRB, channel_safe.
// STRIPPED (FL6): no reader of FCS_TAB in this tree; deadstrip.py find FCS before arming.
#define DMF_BLOB_XID 12 // dmem extra: the tail blob's length in bytes (10 bits); the blob is the last bytes of draft memory
#define DMF_MCL2_XID 13 // dmem extra: MAPCLASS bits 8-23

                        // End-game margin: no shop trip in the last EG_ROUNDS (or in finish mode with a bag), no heal recall then
                        // with a bankable bag of 10+, a late capture counts its reward's channel in the deadline, and when neither
                        // team's tributed total + its last-200-round rate reaches 1000 by r2000 (from r1000) any bag of 10+ is
                        // banked; 0 = off
#define EG_ROUNDS 80
#define DEAD_BG 1 // DEAD_BG: a dead body's turn (60 rounds per death, about 95k fuel each) is unused

#define FULL_TEAM_NEAR 10 // A dead team mate counts toward a full team only if seen this close to me shortly before (0: anywhere).
#define FULL_TEAM_RECENT 15
#define FULL_TEAM_RATIO 1.5f
#define WAIT_MAX 6
#define WAIT_FILL_SLACK 15.0f
#define FLEE_WISE 1 // after FLEE_STREAK flee turns recall (safe) or fight back (cornered); HELP calls via team memory
#define FLEE_STREAK 5
#define FLEE_RECALL_D 7
#define FP_DETOUR 4 // a walk counts once it is at least cheb + FP_DETOUR
#define CR_ETA 5 // A mate starts the capture only if Prism's Chebyshev distance to a free spawn tile is 1 to this value.
#define TS_BL (static_cast<int>(ES_TAB[10])) // ES slot 10: threat_seen blacklists a group within 5 of a seen foe for this many rounds

// BFX: verified bug fixes, one bit each. Flag read first. Bits 1/2/4 unused. Bit 8: my own shield expiring is not damage taken
// (observe: dmg_round / took_damage). Bit 16: hs3 OPD bit 1 ROOTS reads EXPV (EXP_V | starved_map_bits()) like its neighbours, not
// EXP_V (inert while OPD is 0). Bit 32: STV bit 16's pocket_on_own_side / pocket_joins_home_loop read a kept enemy-spawn field
// (champions never build M.f_enemy); off (STV bit 16 off).
#define PS_SEENPEN 70 // fear: rate_for: value x this/100 for a group with enemies seen in the last 25 rounds (non-DOM)
#define B438_ALTW_X100 (static_cast<int>(ES_TAB[1])) // ES slot 1: rate_for altar-detour weight x100
#define B438_CONT_X100 (static_cast<int>(ES_TAB[2])) // ES slot 2: rate_for contest penalty slope x100
#define PS_HEALN 71 // wants_heal HP fraction x100 near home
#define PS_HEALF 49 // wants_heal HP fraction x100 far from home
#define PS_LOWHP 59 // handle_low_hp leave line x100 with a foe within 8, non-linked

// Constants as integer defines (PS_TAB slots), so data-only variants are possible.
#define PS_KILLW 130 // rate_for: kill-window bonus
#define PS_GATHER 600 // rate_for: crew gather rounds per extra body x100
#define B467_CREWG_X100 (static_cast<int>(ES_TAB[6])) // ES slot 6: CREW_GUARD lone-trip guard x100
#define B467_PDPEN_X100 (static_cast<int>(ES_TAB[7])) // ES slot 7: PD_PEN pair-deep lone trip factor x100
#define PS_SWITCH 118 // refresh_target: switch when a new rate > cur x this/100
#define B467_BANKB 20 // Base of the want_bank bag bar.
#define B467_BANKS_X100 (static_cast<int>(ES_TAB[13])) // Slot 13 of the economy table: slope of the want_bank bag bar per altar tile, x100.
#define B467_BANKTH_X100 (static_cast<int>(ES_TAB[12])) // ES slot 12: want_bank bar factor under threat x100
#define B467_GOLDW_X100 50 // gold_weight_in_gems early cap x100
#define PS_SHOPMIN 120 // want_shop: non-eager minimum gold
#define PS_LOWREC 86 // HP fraction x100 below which a body recalls.
#define PS_ENGAGE 120 // assess: base engage bar x100
#define PS_FLEE 56 // assess: base flee bar x100
#define PS_SYM 66 // Assess: discount x100 on a foe's power when none of us is within 3.
#define PS_PEEL 88 // PEEL_MIN x100
#define PS_CAUGHT 168 // CAUGHT_MIN x100
#define PS_INREACH 72 // assess: in-reach fight bar x100

// Constants in one volatile data table, so a search variant differs only in data bytes. Magic words at both ends keep it out of .bss
// and findable in the wasm.
#define PS_HPRIZE 15 // hunt_prize weight x100 in team_focus (0.15f)
#define PS_HDBAG 60 // hunt_leash_assess leash bag limit
#define PS_HDFR 40 // hunt_leash_assess leash HP line x100 (0.4f)
#define PS_HDRACE 90 // hunt_leash_assess race margin x100 (0.90f; lock = this + 30)
#define PS_HFLONE 400 // team_focus HUNT lone-foe bonus x100 (4.0f)
#define PS_HFBAG 50 // team_focus HUNT bag weight x1000 (0.05f)
inline constexpr int PS_TAB[23] = {
	0x36343862, // table magic
	PS_ENGAGE, // slot 1
	PS_FLEE, // slot 2
	PS_CAUGHT, // slot 3
	PS_INREACH, // slot 4
	PS_SYM, // slot 5
	PS_PEEL, // slot 6
	PS_SWITCH, // slot 7
	PS_KILLW, // slot 8
	PS_GATHER, // slot 9
	PS_SHOPMIN, // slot 10
	PS_LOWREC, // slot 11
	PS_SEENPEN, // slot 12
	PS_HEALN, // slot 13
	PS_HEALF, // slot 14
	PS_LOWHP, // slot 15
	PS_HPRIZE, // slot 16
	PS_HDBAG, // slot 17
	PS_HDFR, // slot 18
	PS_HDRACE, // slot 19
	PS_HFLONE, // slot 20
	PS_HFBAG, // slot 21
	0x6e763e0d, // end magic
};
#define B467_ENGAGE_X100 (static_cast<int>(PS_TAB[1]))
#define B467_FLEE_X100 (static_cast<int>(PS_TAB[2]))
#define B467_CAUGHT_X100 (static_cast<int>(PS_TAB[3]))
#define B467_INREACH_X100 (static_cast<int>(PS_TAB[4]))
#define B467_SYM_X100 (static_cast<int>(PS_TAB[5]))
#define B467_PEEL_X100 (static_cast<int>(PS_TAB[6]))
#define B467_SWITCH_X100 (static_cast<int>(PS_TAB[7]))
#define B467_KILLW_X100 (static_cast<int>(PS_TAB[8]))
#define B467_GATHER_X100 (static_cast<int>(PS_TAB[9]))
#define B467_SHOPMIN (static_cast<int>(PS_TAB[10]))
#define B467_LOWREC_X100 (static_cast<int>(PS_TAB[11]))
#define SEEN_PEN_X100 (static_cast<int>(PS_TAB[12]))
#define B438_HEALN_X100 (static_cast<int>(PS_TAB[13]))
#define B438_HEALF_X100 (static_cast<int>(PS_TAB[14]))
#define B438_LOWHP_X100 (static_cast<int>(PS_TAB[15]))
#define PSV_HPRIZE (static_cast<float>(PS_TAB[16]))
#define PSV_HDFR (static_cast<float>(PS_TAB[18]))
#define PSV_HDRACE (static_cast<float>(PS_TAB[19]))
#define PSV_HFLONE (static_cast<float>(PS_TAB[20]))
#define PSV_HFBAG (static_cast<float>(PS_TAB[21]))

// Econ and target-choice constants in one volatile data table, so search variants differ only in data bytes. Magic words at both
// ends.
#define ES_ALTW 10 // slot 1: rate_for altar-detour weight x100
#define ES_CONT 45 // slot 2: rate_for contest penalty slope x100
#define ES_CONT0 55 // slot 3: rate_for contest penalty threshold x100 (slope denominator 0.45 fixed)
#define ES_SEENWIN 25 // slot 4: rate_for enemy-seen penalty window (rounds)
#define ES_MPSEEN 85 // Slot 5: seen factor x100 for presence in the middle.
#define ES_CREWG 15 // slot 6: CREW_GUARD lone-trip guard x100
#define ES_PDPEN 32 // slot 7: PD_PEN pair-deep lone trip factor x100
#define ES_FREEB 130 // slot 8: FREE_BONUS x100
#define ES_WCAP 75   // slot 9: respawn-wait cap multiplier x100 (wait_cap_i)
#define ES_TSBL 10 // slot 10: threat_seen blacklist rounds (TS_BL)
#define ES_RDS 6 // slot 11: RD_SHOP gold per home-walk tile
#define ES_BANKTH 66  // slot 12: want_bank bar factor under threat x100
#define ES_BANKS 88   // slot 13: want_bank bar slope per altar tile x100
#define ES_SGCALL 60 // slot 14: SG_MARGIN_CALL x100
#define ES_SGRATE 80 // slot 15: SG_CREW_RATE x100
inline constexpr int ES_TAB[17] = {
	0x45533935, // table magic
	ES_ALTW, ES_CONT, ES_CONT0, ES_SEENWIN, ES_MPSEEN, ES_CREWG, ES_PDPEN, ES_FREEB,
	ES_WCAP, ES_TSBL, ES_RDS, ES_BANKTH, ES_BANKS, ES_SGCALL, ES_SGRATE,
	0x35395345, // end magic
};
#define ES_CONT0F (static_cast<float>(ES_TAB[3]) / 100.0f)

// CAL: calibrated crew estimate (survivorship-free: failed and abandoned trips included, ratio of sums by PLANNED crew) and the
// consumers tuned on the old biased numbers, as one runtime data table. Flag read first; CAL_BITS 0 = off. Bit 1: e.t x a per-crew
// time factor; bit 2: e.dmg x a per-crew damage factor (before the feasibility test). Slots 8-11 are the literals SG_MARGIN .75,
// CREW_RESV .10, the crew-budget HP floor .22 and SG_TMAX 70.
#define CAL_BITS 0
inline constexpr int CAL_TAB[13] = {
	0x43414C38, // table magic
	CAL_BITS, 77, 96, 96, 90, 136, 160, 75, 10, 22, 70,
	0x38434C41, // end magic
};

// Literals that copy a tunable's value read that tunable instead. Runtime data flag, read first; 0 = off. Bit 1:
// group_bounds_finish's last-kill bound uses PS_KILLW (1.3f at 130). Bit 2: mark_groups_near_kill and rate_for's MF2 bit 128 PDX use
// ES_SEENWIN for the enemy-seen window (25 by default). Bits 1-2 play identically at the default values. Bit 4: handle_low_hp's
// linked C&I leave line with a foe near is max(0.55, PS_LOWHP), so a linked body, whose death kills both, does not leave later than
// a lone one. Bit 8 (overrides 4): PS_LOWHP + 0.10.
#define LATE_GEMS_R 600
#define LATE_GEMS_LEAD 200.0f
#define CHOICE_STAGE_SPARE 10000
#define CHOICE_STAGE_KEEP 3
#define DRAFT_VE_PP 6.0f // DRAFT: Vendetta is drafted up on cluster-heavy maps
#define DRAFT_VE_LO 0.2f // DRAFT: chain share = share of the farmable walk value in groups of >= 2 members, all clusters
#define DRAFT_VE_HI 0.5f
#define DRAFT_WI_PP 4.0f // DRAFT: Willow is drafted down (pp per slot, every team size)
// WDR (b1748, Deep's prereg_wdraft): Willow's draft, baked (WDR_TAB[1] is not read). Bit 1: the DRAFT_WI_PP cut removed. Bit 2:
// +WDR_WI_T/10 pp. Both only at team size 5 on golem maps (WGL bit 1).
#define WDR_BITS 3
#define WDR_WI_T 40     // bit 2: tenths of a pp at T5 (set from the step-0 probe)
// v663 WDR: Willow raise with Marcella guard (WGLM)
inline constexpr int WDR_TAB[3] = { 0x57445231, WDR_BITS, WDR_WI_T };
// WGL (b1769, Deep's prereg_wgolem): Willow the heavy-camp tempo specialist. Bit 1 (draft): WDR's raise (bits 1, 2) only at team size 5
// on maps with >= 1 golem group. Bit 2 (play): on a crew working a golem or monolith group she takes an attack tile within heal range of
// the crew's tank and farther from the focus camp than the tank (never the camp's nearest body), and her heal goes to that tank first,
// on cooldown. Bit 4 (draft): where the plan built with the raise holds no Willow, the raise comes back out and the plan is rebuilt,
// so lineups without her keep live's values, order and draft memory. Bit 8 (draft): on maps whose camp value is under 70% gems
// (gems x 10 / (gems x 10 + gold)), Willow does not take Marcella's seat (the raise comes out when the plan swaps Marcella for her). 0 = off.
// v663 WGL: Willow raise with Marcella guard (WGLM)

// Compile-time switch for one-line decision logs. Logging costs fuel, so keep it 0 for games that count.
#define NLOG(...) ((void)0)

#define NOVA_INLINE __attribute__((always_inline)) inline

#define WARD_NEAR 0 // Enemies seen only by a ward this close to me still count for the fight logic.

// Rule audit fixes: runtime flag, 0 = off (no work). Bits: 1 DMID (dash_legal_between): only a living camp the dashing body sees
// blocks a middle (Q59): an unseen camp tile in a bush passes, unless the launch tile is in that bush's cluster (the body will see
// it there). An unseen tile outside bushes stays blocked: from a planned launch tile it comes into sight. W.occ_camps already holds
// what my ward sees. A pending crystal landing, ours or the foe's, blocks a middle too (Q43, Q59): the engine's visible board. 2 EBK
// (mates_landing_by, bag_wins_with_mates): a tributing mate's bag read from the SDK; al.gems is 0 on calm turns. Mates out of sight
// stay unread (rc 97, Q59; the team memory has no bag; a last sighting can't tell a cancelled channel): under-read, never a false
// win. 4 PROSP (capture_recall my_gems): a Prospector holder also gets floor(25%) of its share of the group's cluster gems
// (GameRules:297, Q38). 8 BLF: the CEX discount starts at the earliest foe pay, rs::capture_pay of a known foe Capture holder (6, 4
// with one), not the bare timer 5, and the CEX expiry uses the same pay; foe_hp_reads_full's recall uses the foe's Home emblem (3,
// GameRules:275). Emblems as read in sight (Q52). 16 RFE (champ_prism.cc foe_finish_eta): a foe bag's channel with that foe's
// Tribute emblem (100 gems: 7 turns, not 10).
#define RULE_AUDIT_FIX_CNT(k, c) ((void)0) // Fire count: the diagnostic copy records site k when c holds; release builds do nothing and do not evaluate c.

// Altar lock fixes: runtime flag, 0 = off (no work); bits: 1 LKB (hit_champion_before_lock_slow, CTX bit 1 LKC): the enemy lock on
// an altar in range is read with econ::enemy_lock_on (the direct enemy read), since altar_lock_at(...).is_enemy() returns OUR lock
// when both teams' locks stand (one lock per team per altar, Q41); otherwise LKC misses the foe lock and lock_hit (it reads the lock
// directly under bit 1) spends the attack on it. 2 SPLIT (capture_recall): my share of the capture's gems uses rs::split_share (win
// test, bag tests, bank bag): g.gems / sharing floors, and the lowest champion ID among the receivers takes the remainder
// (GameRules:207).
#define ALTAR_LOCK_SPLIT_CNT(k, c) ((void)0) // Fire count: the diagnostic copy records site k when c holds (new answer != old); release builds do nothing and do not evaluate c.

// WBG: perceive reads a foe's bag only within 9 of me in my own sight, so intel's note() would overwrite the remembered bag
// (team_bodies) with 0 on every ward-only or far sighting. Runtime data flag WBG_TAB[1] (0 = off, zero work): bit 1 = note() reads
// such a sighting's bag itself (sdk_champion_gems works on anything in vision) into the team copy only, keeping the last known bag
// if the read fails; bit 2 = a foe's remembered bag drops to 0 when it dies (the killer takes it), not at its first sighting after
// the respawn.
#define WBG_BITS 3
inline constexpr int WBG_TAB[2] = { 0x57424731, WBG_BITS }; // WBG: a far or ward-only sighting reads the foe's bag
// PFD (b1969; RC TPF1, Shared Mem prism_focus_memory_1112): intel's team copy (team_bodies) keeps a foe's last-read Focus with no age
// limit; a foe Prism's Focus holds 1.5 per carried gem (GR:564: losing the gems removes it), and her death zeroed only the copy's bag.
// Runtime data flag PFD_TAB[1] (0 = off): bit 1 = on her death the copy's Focus drops by 1.5 x the remembered bag before the bag is
// zeroed (read by foe_strength_lazy, the group-pick risk term).
// v769 PFD: dead foe Prism drops gem Focus in team copy
#define PFD_BITS 1
inline constexpr int PFD_TAB[2] = { 0x50464431, PFD_BITS }; // slot 0 magic keeps it out of .bss
// RSC (b1969; RC TPF2/TPF3, C390; the PFD bit 2 of the review): on any foe's death intel's team copy takes its respawn state: hp =
// maxhp, shield 0, not stunned, both ability cooldowns 0, channel bits (recall, tribute, teleport) cleared (GR:375: respawn "with full
// health and abilities reset"). Before, the copy kept the pre-death HP for 15 rounds after the respawn (healed reset needs age > 15)
// and the stored cd[], stun and channel. Runtime data flag RSC_TAB[1] (0 = off), bit 1.
// v770 RSC: dead foe copy takes respawn HP, stun, cooldowns
#define RSC_BITS 1
inline constexpr int RSC_TAB[2] = { 0x52534331, RSC_BITS }; // slot 0 magic keeps it out of .bss
#define WARD_WATCH 1 // group memory also reads the groups my ward watches from afar (state, respawn timer)

// AP_FAST: MapInfo::step_approach's altar loop is unguarded interpreted work, ~1.6k fuel an altar. The filter before it stops at 28k
// left, so only >= 16 altars can run a turn out of fuel there. AP_FAST = N > 0: from N altars the same boards come from bitboard
// calls, gate_groups in the same order read only at altars with a camp beside them, with a fuel floor so the stage resumes next
// turn. Runtime data flag, read first; 0 = plain loop.
#define AP_FAST 16
inline constexpr int APF_TAB[2] = { 0x41504631, AP_FAST }; // Flag table for the fast altar loop (the altar count from which it applies).

// Fuel profiler (debug builds, or profiling builds that print only overlong turns): PROF records a checkpoint, the dump call prints
// and clears them.
#define PROF(tag) ((void)0)

                    // LOOP_FIX: after LOOP_FIX support turns in a row at my target that end without a hit, drop it for 20 rounds; 0
                    // = off (the approach gate otherwise sends it back next turn: two-tile loops)
#define RECALL_OUT 6 // RECALL_OUT: completed recalls only (below 50% HP)
#define PTB_BAG 50
#define PTB_N 2
#define PTB_SEE 16
#define PTB_SLACK 2
#define SHOP_TAIL 100 // SHOP_TAIL: late-game shop trips for a body with much gold

#define FARM_RICH_FARM_MIN 7000
#define FARM_RICH_ROUNDS 5

#define PF_RESERVE 20000
#define START_ROUNDS 40 // START: rounds the start steps cover
#define START_NEAR 6 // The early start step applies within this walk of our spawn (and anywhere for a fuel-skipped target).
#define SG_GEMS 100 // SG3: a big group pays this many gems a capture or more
#define SG_K 3 // SG3: bodies (the healer counts, as siege_free_crew / committed / present count it) that must be free to come for a call, and present for the start
#define SG_SR 1.1f // SG3: team stat ratio (mean sqrt(maxHP x (str + focus)) of living bodies, ours over theirs) for a call
#define SG_NEAR_MAX 1 // SG3: a call needs at most this many enemies seen within 8 of the group (recent own, ward and team sightings)
#define SG_ABORT_N 2 // SG3: this many enemies within 8 of the group abort the operation
#define SG_CMAX 0.62f // SG3: big groups in our half or the middle only (contest = our walk / both walks)
#define SG_TMAX (static_cast<int>(CAL_TAB[11])) // CAL slot 11: SG3: the crew's estimated clear (rounds) must fit this (commit until done, no chipping)
#define SG_SLACK 20 // SG3: gather deadline = the slowest member's walk + this
#define SG_GMAX 70 // SG3: longest gather (rounds from the call or the join)
#define SG_ETA_MAX 60 // SG3: a call counts only bodies that can walk to the group within this many rounds
#define SG_LATE 12 // SG3: with SG_K+ bodies there and the clear feasible, start after this many rounds of waiting for the rest
#define SG_COOL 60 // SG3: a crew that did not form blacklists the group for this many rounds
#define SG_ABORT_COOL 30 // SG3: an aborted operation (enemies came) blacklists the group for this many rounds
#define SG_EVERY 4 // SG3: a free body checks the call gate every this many rounds
#define SG_HP 0.5f // SG3: a body joins (or rejoins after healing) at this health share or more (wants_heal sends it home below 0.5 far out)

// ---------------------------------------------------------------- ending the game through a capture (CCE) A foe can end the game by
// capturing a big uncontested group while our bodies stand a few tiles off. Flag CCE_BITS, 0 = off. Bit 1 END: contest_capture_turn also contests
// a reward-ready group whose gems end the game for them (tributed_them + gems >= 1000) when a foe is within CCE_FOE of its region
// and a region tile is within CC_D + 3 (no HP-fraction or numbers gate); the walk keeps contest_capture_turn's damage test, the last step / the
// hold needs one round of seen ready hits (lethal_burst_hit) below my effective HP. Bit 2 LOW: contest_capture_turn's CC_GEMS 100 becomes CCE_GEMS 80.
// Hooks: brain_*.cc contest_capture_turn (inline gate) and contest_capture_turn_slow (gem gate); flag first.
#define CCE_GEMS 80
#define CCE_T0 600 // no game-ending group below this many tributed (fuel early-out)
#define CCE_FOE 3

// CTH: at contested gem groups a body must not leave once our side has reached parity: FLEE turns there come at even-or-better true
// numbers (ally_commit_weight, the camp threat and unseen reinforcements discount our side), one body at a time, and each FLEE
// turn's threat_seen blacklists the group. At my target group (CTH_GEMS+ gems, not respawning, its anchor within CTH_NEAR of me),
// when our bodies within CTH_R of its anchor (above CTH_HP, not channelling) are at least theirs + CTH_EDGE (visible, or seen up to
// 4 rounds ago) and the plain Lanchester power there (no commit, camp or reinforcement discounts) is at least CTH_MIN of theirs, a
// FLEE of a body that is not caught and above CTH_HP becomes FIGHT (a focus in reach) or CALM (keep farming or capturing). The
// stance is then not FLEE, so threat_seen leaves the group alone; every body there counts the same bodies, so they hold or leave
// together. A linked Cassi & Issac pair holds only together and healthy (the CI_SAFE owner rule's gap and health). 0 = off.
#define CTH_GEMS 15
#define CTH_NEAR 6
#define CTH_R 8
#define CTH_EDGE 0
#define CTH_MIN 0.8f
#define CTH_HP 0.45f
#define DT_RADIUS 10
#define REACT_HOPE 0.9f // the hit-back bar on min(ratio, ratio_near); a bag of 20+ gems raises it
#define SR_RATIO_X100 80 // Spawn refuge applies only below this assess ratio x100.
#define SR_HOME_D 6 // a retreat within this many walk steps of my spawn rallies home (the refuge, which heals to full), not on an ally (0 = off)
#define SR_BURST_PCT 90 // not when the foes reaching the tile can deal this % of my full health before my next turn

// Spawn siege. A spawn tile heals to full at MY turn end (GameRules:122, :151), so on the tile only maxHP vs one window's damage
// counts. Runtime data flag SS_TAB[1] (0 = off): bit 1 CHIP (econ::spawn_siege_turn), bit 2 COUNTER (the combat counter to a siege),
// bit 4 RALLY (with bit 1: recall home when my chip pays). SS_TAB[2] SS_RATE_PCT: chip rate (value x my dps / HP left) must reach
// this % of a body's share of the map's other supply (econ spawn_siege_alternative_supply). SS_TAB[3] SS_SAFE_PCT: window damage
// below this % of maxHP. SS_TAB[4] SS_MINSTR: group's strongest attacker (200 monolith, 120 golem too). SS_TAB[5] SS_BAG: a bag this
// size goes to bank first.
#define SS_BITS 13
#define SS_RATE_PCT 6400
#define SS_SAFE_PCT 90
#define SS_MINSTR 200
#define SS_BAG 30
#define SS_NORALLY 150 // SS_TAB[6] bit 8: rounds a failed chip on the tile keeps RALLY off for that group; cleared when the group's status changes. Also no GS_CLEARED walk on FLEE or with a foe within 9.
inline constexpr int SS_TAB[7] = { 0x53533234, SS_BITS, SS_RATE_PCT, SS_SAFE_PCT, SS_MINSTR, SS_BAG, SS_NORALLY }; // slot 0 magic keeps it out of .bss

// NSK: runtime data flag, 0 = off. NSK_TAB[1] bits. Willow heal (champ_willow.cc): 1 = nothing incoming, no fight, no foe within 10:
// heal any ally missing >= NSK_TMIN% of the heal (overheal allowed; an unused heal is lost); 2 = the same top-up with a foe in
// sight; 4 (with 1) = Heart of Ruin topped up like any ally when no foe within 10; 8 = an ally under camp/foe damage is healed at
// any missing >= NSK_TMIN%. Cassi (camp_abilities): 16 = the nuke/stun hold needs a remembered foe within NSK_CR after NSK_CAGE
// rounds (nearest_foe_distance_seen), not any foe within 10 in 8 rounds; 32 = the nuke goes before the camp stun when it reaches the
// focus (one cast a turn); 64 = focus out of nuke range: nuke the nearest awake living camp of the focus group in range.
#define NSK_BITS 13
#define NSK_TMIN 5
#define NSK_CR 8
#define NSK_CAGE 2
inline constexpr int NSK_TAB[5] = { 0x4E534B31, NSK_BITS, NSK_TMIN, NSK_CR, NSK_CAGE };

// SGV (b1696, rules-gaps): slot_gold's cache key is an int, so a Vesper slot (vv 33) hits it. 0 = v630; fuel only, same values.
// v632 SGV: slot_gold int key, Vesper slots hit cache

// FGT (b1743, owner "use all the fuel"): cost-based fuel gate. Runtime data flag, read first; 0 = live. Bit 4: target_turn's
// "a choice ran this turn" cheap-step bail below FGT_BAIL (live 40k; the 28k bail stays).
#define FGT_BITS 4
// v639 FGT: bail 30k with camp-work fuel guard
#define FGT_BAIL 30000
inline constexpr int FGT_TAB[3] = { 0x46475431, FGT_BITS, FGT_BAIL }; // slot 0 magic keeps it out of .bss

// CTG (b1743, fuel cut fix for FGT bit 4's extra cut-offs; also a fuel fix on its own): runtime data flag, read first; 0 = live.
// Bit 1: support_turn's camp work (holder bail, rotate, hold, safe tiles, hits) runs only when the fuel left covers its measured
// cost per camp in sight x camps in sight (a decayed maximum per body, x100, fading 1/32 per measured turn) + CTG_TAIL; else the
// turn takes the cheap camp hit. CTG_TAIL covers the turn's ungated end (turn_tail, end escape check, background gates).
#define CTG_BITS 1
// v639 CTG: bail 30k with camp-work fuel guard
#define CTG_TAIL 16000
inline constexpr int CTG_TAB[3] = { 0x43544731, CTG_BITS, CTG_TAIL }; // slot 0 magic keeps it out of .bss
// FXR (b1765, spec_fxr_1109): a play call the engine suspended (fuel cut) and resumed in a later round restarts that round's turn
// fresh instead of acting on the old round's state. Runtime data flag FXR_TAB[1], read first; 0 = off. Bit 1 RESTART (stage 1, every
// fuel guard kept): a stale call reads 0 fuel, so every fuel-checked job stops at its own check; a round poll before every action,
// shared-memory write and AF_CHECK throws RestartTurn (not a std::exception) to fxr_run (brain_modes.cc), which runs the round's turn
// again from spin_on_turn_start; catch (...) sites pass RestartTurn and AfBail on; hand-set toggles are reset at turn entry. Bit 2
// TGL: vfd_dash_only and kca_busy (left set when an AfBail unwinds through their call) are reset at turn entry. Bit 4 EAO:
// spin_on_turn_end's acts (walk_cast_end, ks_turn, bank_step_turn) run after turn_tail, before intel::end_turn and the background.
// v643 FXR: reset stuck AfBail toggles
#define FXR_BITS 2
inline constexpr int FXR_TAB[2] = { 0x46585231, FXR_BITS }; // slot 0 magic keeps it out of .bss
#define FXR_ON(b) ((FXR_TAB[1] & (b)) != 0)

// BB8 (b1767, Rule Checker audits 9 Nov, docs/bot_errors.md): runtime data flag, read first; 0 = v641. One bit per line:
// 1 recall foe turns per foe; 2 race horizon to round 2000; 4 best_within rates per DM; 8 opening_pick<true> rates per DM;
// 16 tl_trib across modes; 32 crystal stun bar over 3 foe turns; 64 foe return died + respawn - 1; 128 altar hold age from the
// bag read; 256 capture contest hit picker; 512 siege follow drops a failed target; 1024 deny cancel: mate cd -1 not ready,
// excl walk +1; 2048 heal near/far switch scaled by spawn distance; 4096 route_len memo only on the same tile; 8192 dash_ahead
// keeps the dash with a foe within BB8_TDFR (travel_dash's TD_FOE_R); 16384 known_open never frees an ally-occupied tile;
// 32768 the draft memory's distance scale also covers the spawn-to-spawn walk (byte 14 no longer saturates on maze maps);
// 262144 (fuel, play-identical) raw imports for the step's move (move_absolute) and walk_cast_end's cooldowns (abilities()).
// v645 BB8: direct imports for move and cooldown reads
// BB14 (b1766, Bug Bundle 14): one bit per verified bug. 0 = v648 nova_base_v648. Bits: (1 unused: WRB, the bush-ward retry, read
// h2h -.019 in a leave-one-out and went to the bank); 2 WPN the contest pin skips known ally
// ward tiles (allied wards scanned at act()'s top, throttled) and a refusal retries (pin ends after 3); 4 FGR add_altar_side_landings
// checks fuel every 8 tiles of a row (resumes at that tile); 8 CST the camp stun only on a camp whose hit lands on one of us (nearest
// champion, GR:192), else the focus; 16 AFC the AfBail catch sets next round's priority as set_dynamic_turn_priority would, sets
// re_acted and publishes the task; 32 AFA act-first re-arms after channel_holds cancelled a channel and the turn goes on; 64 LBS the
// lethal-burst flee keeps the cast for its shield (bh57_noreset); 128 HDE Heart's landing dash waits while bh57_noreset is set.
#define BB14_BITS 254
// v650 BB14: bug bundle 14, 7 fixes (WRB banked)
#define BB14_AFC_FUEL 15000 // bit 16: the full priority logic with this much fuel left, else its frac/foe test only
inline constexpr int BB14_TAB[3] = { 0x42423134, BB14_BITS, BB14_AFC_FUEL }; // slot 0 magic keeps it out of .bss
#define BB14_CNT(k, c) ((void)0) // fire count: the diag copy records site k when c; release: nothing, c unevaluated

// BBM: failed-move fall-throughs, a stage decides, its move fails, a later stage acts against the decision (Rule Checker MF1-8,
// bot_errors.md). Runtime data flag BBM_TAB[1], read first; 0 = off. Bits: 1 MF1 (a FIGHT walk-in that fails steps greedy toward the
// focus or holds, and the turn ends), 2 MF2 (fight() keeps last_fight_round only when it acted, moved or held), 4 MF3 (game-ending deny
// walks run outside the foe walk guard), 8 MF4 (altar_hold_turn returns true only near the altar or after a step), 16 MF5 (a capture
// walk that failed 2 turns in a row drops the target). MF6-8 fired 0/g in 300 games: not built.
// v659 BBM: fight stamp only when it acted (BBM MF2)
// FLZ: a FLEE turn whose flee() finds no step falls through to later stages that walk with no guard (lethal zones are CALM/FIGHT-only,
// the CWG list CALM-only; Combat spec_flz_1109, Rule Checker VERIFIED). Runtime data flag FLZ_TAB[1], read first; 0 = off. Bit 1: for
// the rest of that turn the walk guard keeps out of flee's own foe zones (two-turn reach included) whose disc doesn't contain me.
// v660 FLZ: flee-failed turns keep flee's zones (FLZ fuel cut)
// BB34 (b1769, Rule Checker bot_errors.md 'Draft compliance + Willow after v663', bug bar). Runtime data flag BB34_TAB[1], read first;
// 0 = off. Willow's heal choice (champ_willow.cc wl2_heal) and stance. Bit 1 WL1: a calm crew tank keeps the least-missing filter (no
// 3F top-up of a scratch that puts the heal on cooldown before the golem hits). Bit 2 WL2: the tank's weight is x3 but under a lethal
// volley's 4 (3.9 at most) unless the tank itself faces one (4.5): a mate about to die is healed before a tank under camp fire. Bit 4
// WL3: the lethal weight 4 only when the heal saves the mate (hp + heal > incoming). Bit 8 WL5: her 'never starts a fight' CALM override
// is applied again after the stance rules that can raise FIGHT (after no_lone_fight). Bit 16 WL6: the tank she heals first is econ's
// crew tank (crew_here(gi).tank; none when that is me), not the mate nearest the group's anchor.
// v670 BB34: BB34 heal choice WL1-3 WL6 + stance WL5

// IFD (b1753, Fable spec_phl_1109; walking waste): a collection dash from 2 out. Camp dashes per 100 alive rounds: Issac .45 v 1.00,
// Vendetta .44 v 1.04 (top 3). Runtime data flag IFD_TAB[1], read first; 0 = off. Bit 1 = Issac's collection travel dash (cd_mode > 0)
// goes from a walk of 2 (live TD_COLLECT_WALK 3), landing 2 nearer (the attack tile); bit 2 = the same for Vendetta.
// v671 IFD: Vendetta collection dash from 2 out

// PRA2 (b1777, Planner spec_pra2_1109): turn-priority ablation, a read flag (never shipped). Each bit turns one live rule OFF; 0 = v659.
// 1 R0 the base order is draft order (priority 0 for every body, ties by draft order) instead of mv::turn_order_base / P.prio;
// 2 R1 escape 40; 4 R2 finish 35; 8 R3 lethal-next-turn 40; 16 R4 Issac's order/tie; 32 R5 AFC's after-bail priority;
// 64 R6 the walk-then-cast 38 (brain_modes walk_cast_end).
// v672 PRA2: escape-40 off + flee-path fuel cuts (PRA2F)
#define PRA2_BITS 2
inline constexpr int PRA2_TAB[2] = { 0x50524132, PRA2_BITS }; // slot 0 magic keeps it out of .bss

// PRF (b1777, bot_errors.md "v672 PRA2 knock-ons", Rule Checker); baked.
// PRF bit 1 PK1: v672's escape branch (now want = base) no longer swallows the 35 "finish first" test for a low-HP FIGHT body.
// v674 PRF: low-HP fighters keep the finish-first order (PRF)
// WST (b1798, WST1, bug bar): ready_healer_near returns a stunned Willow, so a hurt mate holds for (or cancels its recall into) a heal
// she cannot give: a pending stun (buff duration > 0, world.cc) loses her next turn, every action refused (interactions.md:35-38;
// GR:454). Runtime data flag WST_TAB[1], read first; 0 = off. Bit 1: the :681 reject also drops a stunned healer.
// v685 WST: 19 fixes phy1r2,npb1,orc1,wvc,cia3s,jgw31,x02,idm +11
#define WST_BITS 1
inline constexpr int WST_TAB[2] = { 0x57535431, WST_BITS }; // slot 0 magic keeps it out of .bss
// FB10 (b1778, Rule Checker fb10_rulecheck_1109): play-identical removals, econ/planner/intel/brain. Runtime data flag FB10_TAB[1]; 0 = off.
// 1 intel Stats S writes (never read); 2 econ dbg_path stores (never read); 4 cxc_ctx store and save/restore (never read); 8 TM.sup_near
// (never read); 16 write-only stores (travel_gdn, tcf_lazy_want, comms V.touched/V.camp_n, qct_lastpost, qct_pend, sight_round,
// fgr_n, sps_idle, start_d, p1x_first, last_vf/last_vs, fl_n_pub/fl_n_joinref, start_steps/op_pre_steps); 32 two always-false tests
// (intel news re-test after its remove_if, intel_cleared's !(cnw_own || cs9)); 64 crew_for copies -> crew_for_ref where the reference
// is not outlived by another crew_for_ref call; 128 reserved (row 8, mu::bits constexpr: FB9-2, b1779); 256 tank_holds computed only
// when target_turn_engaged_at_group reads it.
// FB11 rows (grd_fb11_rulecheck_1110), same table: 512 crew_for_ref asks free_near_mask only when pass 0 reads it (extra > 0); 1024
// foe_strength_lazy copies the Body only to project or heal it; 4096 assess_rule_local_power's avg_s only when a remembered foe needs it;
// 8192 assess_foe_weight returns at the first ally in contact and stops the pack count at PACK_N; 32768 observe_sightings stops at the
// first handle match, write-only gpv3_k stores; 65536 assess_carrier_cut returns before the bounty sums when the focus bag is under
// CUT_MIN_BAG; 524288 the dead siege crew-call path (event decode into write-only sg_crew_seen, slot_busy); 1048576 the threat-sense foe
// loop unseen_camp_hit_check already ruled on; 2097152 tank_follow_kill_to_next_member stops at the first member in reach; 4194304 the
// two (void) WL2 reads in support; 8388608 capture_recall returns before the foe_near loop without a capture timer; 16777216 the always-0 cap_penalty call and a (void) WL2 read. Not built: 2048 (late_factors locals), 16384 (bb27_pair_pen m3), 131072/262144 (possible rows).
// v682 FB10: 7 fixes fb10c,cpt29c,cpt29c,grd3c,cib47,cpw1,cis7
#define FB10_BITS 33142655
inline constexpr int FB10_TAB[2] = { 0x46423130, FB10_BITS }; // slot 0 magic keeps it out of .bss
#define FB10_ON(b) ((FB10_TAB[1] & (b)) != 0)
// NPB (b1790, Rule Checker comms pass 3 on v682). Bit 1 NPB1: team_mem_post_legacy_event set the entry's parity bit from the event's
// round, but readers decode the parity as the POST round (team_mem_read: p = this round or the last), and TAKEN (capture round), the
// CLEARED news (up to NEWS_TTL old) and the tmf resend pass older rounds, so on a mismatch the news is dated a round off: the parity is
// now() & 1. Bit 2 RIM1: a channel decode whose image repeats the old one byte for byte (32 m rounds later) kept the old first-seen
// round (note_seen), so help_join and the HOLD tests read a fresh post as stale: legacy_in stamps the seen round on every decode.
// v685 NPB: 19 fixes phy1r2,npb1,orc1,wvc,cia3s,jgw31,x02,idm +11
#define NPB_BITS 1
inline constexpr int NPB_TAB[2] = { 0x4E504231, NPB_BITS }; // slot 0 magic keeps it out of .bss
// MSY (Deep symmetry_1109 item 4, b1780 mirror-divergence Step 0: 48/60 live v live games stop mirroring before contact and r20; bug
// bar, one bit per site). Ties broken in board order play differently by seat. Runtime data flag MSY_TAB[1], read first; 0 = off.
// Bit 1: spawn anchors round toward the map centre, not down (mapinfo.cc ssu_anchors), so both teams' anchors mirror. Bit 2: move_best
// orders equal-score steps by a seat-mirrored key (the map's symmetry axes, signed by my side). Bit 4: dash_landing_search's equal
// landings by the same key.
// v680 MSY: 4 fixes msy7,fac,flr,lck
#define MSY_BITS 7
inline constexpr int MSY_TAB[2] = { 0x4D535931, MSY_BITS }; // slot 0 magic keeps it out of .bss

// WVC (b1779/b1796, Rule Checker wv_rulecheck_1110 WV2). Runtime data flag, read first; 0 = off. Bit 2: bail_ban_lapsed also finds
// the mate tanking through the group's member tiles I see (W.occ_camps, my ward too), not only W.camps (camps near me).
// v685 WVC: 19 fixes phy1r2,npb1,orc1,wvc,cia3s,jgw31,x02,idm +11
#define WVC_BITS 2
inline constexpr int WVC_TAB[2] = { 0x57564331, WVC_BITS }; // slot 0 magic keeps it out of .bss
// BCL (b1762, Rule Checker MAP bit 2, map_rulecheck_1110): on maps with more than 126 groups (the draft's stored count: the packed
// layout is off there) the 8-byte claim held group + 1 in 7 bits, so claims on groups >= 127 read as idle and crews duplicated. Bit 1:
// there, a claim byte holds the RANK of its group in one capped list of 126 claimable groups (most gems + gold first, ties by index),
// built from map data the same way on every body; a group outside the list stays unclaimable (idle, as before). Other maps: untouched.
// v685 BCL: 19 fixes phy1r2,npb1,orc1,wvc,cia3s,jgw31,x02,idm +11
#define BCL_BITS 1
inline constexpr int BCL_TAB[2] = { 0x42434C31, BCL_BITS }; // slot 0 magic keeps it out of .bss
// BVX (b1796, Rule Checker bsh_rulecheck_1110 BSH bit 1). Runtime data flag, read first; 0 = off. Bit 1: ward_bush_by_vanished_foe no
// longer returns when I stand in one of the foe-tile clusters: mine is lit (GR:351-353) and the lit filter drops its tiles, so the
// ward goes to the other, unlit cluster.
// v685 BVX: 19 fixes phy1r2,npb1,orc1,wvc,cia3s,jgw31,x02,idm +11
#define BVX_BITS 1
inline constexpr int BVX_TAB[2] = { 0x42565831, BVX_BITS }; // slot 0 magic keeps it out of .bss
// RFA (b1779/b1796, Rule Checker refused-action bundle rfa_rulecheck_1110 + WRD + WAB1). Runtime data flag, read first; 0 = off.
// Bit 4: heart_dash_cast_best_landing tries the next landing after a refused cast while the dash is ready. Bit 16: a ward placement
// that comes back plainly false records the tile as an ally ward; an own-state error (stunned, no charge, can't act) bans no tile and
// ends the react / bsx tries. Bit 128 (WAB1): a placement
// refused with rc 117 (a mate's ward holds the tile, GR:363: permanent) records the tile as an ally ward at the scout, react, bsx and
// chosen-ward sites, not a 40-round ban.
// v685 RFA: 19 fixes phy1r2,npb1,orc1,wvc,cia3s,jgw31,x02,idm +11
#define RFA_BITS 148
inline constexpr int RFA_TAB[2] = { 0x52464131, RFA_BITS }; // slot 0 magic keeps it out of .bss
// PSC (b1779, Rule Checker PSC1): parting_foes (combat_flee.cc) took every stunned foe in its unstunned reach as a stopped chaser, though a
// paired foe with a usable turn before mine (burst::bh81_stun2) still hits; the parting stun then went elsewhere. Runtime data flag, read
// first; 0 = off. Bit 1: such a foe means no stun holds the gap (parting_foes returns false).
// v685 PSC: 19 fixes phy1r2,npb1,orc1,wvc,cia3s,jgw31,x02,idm +11
#define PSC_BITS 1
inline constexpr int PSC_TAB[2] = { 0x50534331, PSC_BITS }; // slot 0 magic keeps it out of .bss
// DMP (b1789, Rule Checker DMP1): plan_memory_encode caps byte 10 at 200 groups and byte 11 at 40 altars while bytes 12/13 hold the
// true counts, so pack() refused the whole image on a >200-group or >40-altar map (map class and tail blob lost). Runtime data flag
// DMP_TAB[1], read first; 0 = off. Bit 1: pack() accepts true counts at or above the capped ones.
// v685 DMP: 19 fixes phy1r2,npb1,orc1,wvc,cia3s,jgw31,x02,idm +11
#define DMP_BITS 1
inline constexpr int DMP_TAB[2] = { 0x444D5031, DMP_BITS }; // slot 0 magic keeps it out of .bss
// v687 IP3: 5 fixes tisbd,ip3rsgb,soi,ip3rsgs,bef32
#define IP3_BITS 8
inline constexpr int IP3_TAB[2] = { 0x49503331, IP3_BITS }; // slot 0 magic keeps it out of .bss
// FB35 (b1807, play-identical): gate_target_turn tests the crew size (c.n < GT_K) before team_bag_total()'s engine reads.
// v756 FB35: RC X347 VBK1: dormant table baked at its live value 0 (owner 9 Nov bake-older rule)
#define FB35_BITS 0
inline constexpr int FB35_TAB[2] = { 0x46423335, FB35_BITS }; // slot 0 magic keeps it out of .bss

// b1812 BE2 (Rule Checker bot_errors verify_so_v684, next rows after the top 10): runtime data flag, 0 = off, one bit per row.
// Bit 1 (row 154a): the flee refuge turn ends with free_cast (damage spell, else stun, else area) instead of free_aoe only.
// Bit 2 (row 154b): the same at the fight refuge turn's end. Bit 4 (row 204): assess_finish_sure prices a ready damaging stun
// (cc_mod > 0, the turn's first cast) as its own damage, not as a reset/damage-spell extra. Bit 8 (row 243): only an awake camp near
// the move's destination cancels the pre-move camp hit. Bit 16 (row 906): the travel/collection dash skips landings in the step
// avoid zone (step_open's test). Bit 32 (row 1004): opportunity_factor's free-camp bonus also when no foe is alive. Bit 64 (row 241):
// a hurt me (frac <= .35) hands the camp tank job to the best healthy mate here even if its tank order is worse.
// v693 BE2: 4 fixes be2b8f,fsb4,qms1,prb4f
#define BE2_BITS 8
inline constexpr int BE2_TAB[2] = { 0x42453231, BE2_BITS }; // slot 0 magic keeps it out of .bss
// X65 (b1795, Rule Checker X65 rows): runtime data flag, read first; 0 = v692. Bit 1 SSK1: spawn_siege_kill_dps adds the stun spell's
// damage on camps (cc_mod x Focus per cooldown when cc_on_camps), as kit_dps and the team model do. Bit 2 SSK1: and the dash damage
// (dash_mod x Focus per cooldown). Bit 4 CNH1: cib_nuke_hold's finishing-kill test counts my camp damage multiplier (Monster,
// Collectors; INT:84). Bit 8 VOP1: vesper_open::decide prices the crew's clear with kit_dps (spells, reset, splash, retaliation),
// not base Strength only. Bit 16 KH3: spawn_siege_my_dps adds the stun and dash damage, as bits 1/2 do for the commit test.
// Bit 32 SSQ1: the spawn siege end-of-game test uses my dps plus the allies on our spawn that reach the group (as the commit test sums),
// not every body at my dps. Bit 64 SRM1: siege_slot_is_free does not count a seen mate on a real recall as free.
// v695 X65: 9 fixes fbbw3,tcs,x66j,bhw1,x65c,fgd1,pbq8,qmd1,xgv1
#define X65_BITS 63
inline constexpr int X65_TAB[2] = { 0x58363531, X65_BITS }; // slot 0 magic keeps it out of .bss
// TSB (b1814, Deep's Tavi/Stellar bug line, tavi_stellar_rework_1110.md). Runtime data flag, read first; 0 = v693. Inert unless the kit
// is fielded. Bit 1 (GR:700, INT:27): Tavi's parting stun that ends the flee also takes the basic at range 3 (ranged too). Bit 2 (GR:118):
// Tavi's flee hit / flee shot holds the reset when the damaging stun is ready with a foe within 4, so free_cast casts the stun. Bit 4:
// Stellar's flee_nuke casts the area when the single cannot go. Bit 8 (GR:336, :690): wants_heal ignores the max HP Tavi's field Health
// added (not healed). Bit 16: refresh_self after a Tavi field buy.
// v698 TSB: 3 fixes tsb24g,tvr2,q2
#define TSB_BITS 31
inline constexpr int TSB_TAB[2] = { 0x54534231, TSB_BITS }; // slot 0 magic keeps it out of .bss
inline float tsb_unhealed = 0.0f; // TSB bit 8: Tavi's field Health max HP not yet healed (reset on spawn)
// TBF (Tool Builder fix bundle, RC backlog v696): bit 1 FHR1 foe_heal_on_others uses FIGHT_R (6), not 8; bit 2 HCS1 a stunned healer's
// heal waits max(cd, 1), not cd + 1 (INT:35); bits 4 and 8 unused (BRS2 was a false positive: dashes are walking-compatible, INT:25;
// RVC1 is rebuilt alone with its farm_turn guard); bit 16 HRM1 Home recall time from csx_recall_t(), not 5; bit 32 WSH1
// Willow's lethal test counts the ally's live shield; bit 64 WRR1 Willow's foe reach is foe_next_turn_reach only (GR:100, INT:35).
// v708 TBF: baked at its shipped value
#define TBF_BITS 115
inline constexpr int TBF_TAB[2] = { 0x54424631, TBF_BITS }; // slot 0 magic keeps it out of .bss
// RC backlog fixes (b1820, Rule Checker backlog v696 rulecheck_backlog_v696_1110.tsv, Pass 4 v697 rulecheck_pass4_v697_1110.tsv, X126
// rules-gaps; docs/bot_errors.md). Four runtime data flags, one per arm group (armq lines may not share a flag), each read first; 0 = v698.
// RCA bit 1 BRM1: burst-reach miss = enemies_alive - visible (both tables).
// RCH bit 1 HL1: the hunt lock ages out (> 3 rounds unseen) and its margin needs a fresh lock.
// RCI (play-identical in 40/40): 1 SRT a resumed stale play turn bails (AfBail) at its next action/AF_CHECK poll; 2 BF1 bank_field
// falls back to f_altar when no open-altar field was built; 4 EH1 endgame hold drops my bag when no foe could land it by 2000 and
// scales EH_SLACK to rounds left; 8 CCB1 the capture contest skips foes on uncleared groups.
// RCB (bug bar, play-changing): 1 DBL1 a tributed bag counts as banked, not lost; 2 BUS1 remembered sightings to OBS_FORGET_ROUNDS,
// reach >= 5, one more step; 4 KW2/TPK1 kill_window: a stunned foe with a second turn, or a teleport landing now, is no window;
// 8 PK2 tie_prio keeps a channelling mate's set value; 16 AWM1 remembered awake camps skip only camps in sight now (both lists);
// 32 WHV1 Willow's own bound takes her pull; 64 E6 the Capture emblem alone sets capture_pay; 128 L68 Vesper's +33% counted once.
// v756 RCA: RC X347 VBK1: dormant table baked at its live value 0 (owner 9 Nov bake-older rule)
#define RCA_BITS 0
inline constexpr int RCA_TAB[2] = { 0x52434131, RCA_BITS }; // slot 0 magic keeps it out of .bss
// v708 RCH: baked at its shipped value
#define RCH_BITS 1
inline constexpr int RCH_TAB[2] = { 0x52434831, RCH_BITS }; // slot 0 magic keeps it out of .bss
// v801 RCB: RCB at live's value 0 (RC X593: lines closed, no waiting line)
#define RCB_BITS 0
inline constexpr int RCB_TAB[2] = { 0x52434231, RCB_BITS }; // slot 0 magic keeps it out of .bss
// RCB2 (b1820, Rule Checker Pass 5 on v698, rulecheck_pass5_v698_1110.tsv; C30/X134; docs/bot_errors.md). Runtime data flags, one per
// arm group, each read first; 0 = v698.
// R2S bit 1 SRT: a play call resumed in a later round bails (AfBail) at a poll before its long loops only.
// R2F: 1 BF1 bank_field falls back to f_altar when no open-altar field was built; 2 CCB1 the capture contest skips foes on uncleared groups.
// R2E bit 1 EH1 (C30): the endgame hold drops my bag when a killer could not bank it by 2000 (nearest altar - 6, approach ceil((dn-5)/2)).
// R2G bit 1 GDP1 + ESL1: a pre-lock after a stun cancels a game-ending channel; end_stun yields to the lock way; a just-stunned target's
// failed channel read counts as cancelled.
// R2T bit 1 TSG1: react_guard_slow holds the reset while Tavi's stun is due (the stun takes the cast).
// R2B (bug bar bundle): 1 GDD1, 2 QMSO1+QMS1, 4 CFS1, 8 (unused; TSG1 moved to R2T), 16 WBU1, 32 WVS1, 64 CCM1, 128 RCS1, 256 WRC2, 512 BTH1, 1024 KOW1,
// 2048 MUB2, 4096 TFH2, 8192 E6 allied Capture holder (GR:196).
// v756 R2S: RC X347 VBK1: dormant table baked at its live value 0 (owner 9 Nov bake-older rule)
#define R2S_BITS 0
inline constexpr int R2S_TAB[2] = { 0x52325331, R2S_BITS }; // slot 0 magic keeps it out of .bss
// v702 R2F: 3 fixes r2f3i,r2e1i,r2t1i
#define R2F_BITS 3
inline constexpr int R2F_TAB[2] = { 0x52324631, R2F_BITS }; // slot 0 magic keeps it out of .bss
// v702 R2E: 3 fixes r2f3i,r2e1i,r2t1i
#define R2E_BITS 1
inline constexpr int R2E_TAB[2] = { 0x52324531, R2E_BITS }; // slot 0 magic keeps it out of .bss
// v756 R2G: RC X347 VBK1: dormant table baked at its live value 0 (owner 9 Nov bake-older rule)
#define R2G_BITS 0
inline constexpr int R2G_TAB[2] = { 0x52324731, R2G_BITS }; // slot 0 magic keeps it out of .bss
// v702 R2T: 3 fixes r2f3i,r2e1i,r2t1i
#define R2T_BITS 1
inline constexpr int R2T_TAB[2] = { 0x52325431, R2T_BITS }; // slot 0 magic keeps it out of .bss
// R2V bit 1 RVC1 + RVC1C (C34): target_turn_engaged_at_group returns tank/support_turn's result (no '|| true'); farm_turn retries
// target_turn only when T.target changed.
// v756 R2V: RC X347 VBK1: dormant table baked at its live value 0 (owner 9 Nov bake-older rule)
#define R2V_BITS 0
inline constexpr int R2V_TAB[2] = { 0x52325631, R2V_BITS }; // slot 0 magic keeps it out of .bss
// R3G bit 1 (v703, GDP1/ESL1 re-arm per C33/X144): R2G's routes plus RGA1 (no lock on a mate's running tribute), RGY1 (end_stun yields
// only if game_deny will act: can move, not moved, mates ahead < GD_BODIES, carrier's nearest altar), RGS1 (no second stun on it).
// R3L bit 1 L68 (v703): capture_rank_fit takes Vesper's number without her +33% (259); holder_gold_mult adds it (GR:532).
// v756 R3L: RC X347 VBK1: dormant table baked at its live value 0 (owner 9 Nov bake-older rule)
#define R3L_BITS 0
inline constexpr int R3L_TAB[2] = { 0x52334c31, R3L_BITS }; // slot 0 magic keeps it out of .bss
// v756 R3G: RC X347 VBK1: dormant table baked at its live value 0 (owner 9 Nov bake-older rule)
#define R3G_BITS 0
inline constexpr int R3G_TAB[2] = { 0x52334731, R3G_BITS }; // slot 0 magic keeps it out of .bss
// v711 R2B: baked at its shipped value
#define R2B_BITS 4
inline constexpr int R2B_TAB[2] = { 0x52324231, R2B_BITS }; // slot 0 magic keeps it out of .bss
inline std::uint32_t r2g_stun_h = 0; // R2G bit 1 ESL1: the game-ending carrier end_stun stunned this round
inline int r2g_stun_r = -1;
inline int r2s_round = -1; // R2S bit 1: the round this play turn perceived (-1 outside play_turn_body)
// MDC (b1824, Rule Checker bot_errors.md:3613-3615): move/draft cleanup, one bit per verified bug. Runtime data flag, read first; 0 = off.
// Bit 1 TNF1: the thin-hole no-skip memo (and the same-round plan cache) is keyed on the field, the window and the ignored group, so a
// default-window miss no longer blocks a wider window. Bit 2 VGF-MFR: a Marcella chosen by the forced-Ryth swap is not turned into
// Vesper by VGF. Bit 4 MCLU: with no walkable group the far-map bits stay off. Bit 8 DXC1: the one-pack Vesper skip applies to DSW cells
// only, not DXC cells.
// v711 MDC: baked at its shipped value
#define MDC_BITS 15
inline constexpr int MDC_TAB[2] = { 0x4D444331, MDC_BITS }; // slot 0 magic keeps it out of .bss
// FB5 (b1823, fuel bundle 5: Rule Checker X138, X127, X139; logic-identical at unlimited fuel). Runtime data flag FB5_TAB[1], read first;
// 0 = v702. Bit 1 TRG1: deny_tribute/end_stun and game_deny run only with a tributing foe in sight (game_deny also with a live deny
// memory). 2 LPE1: linked_pair_cast returns with no foe in sight. 4 WBV1: the vanished-foe bush ward is called only with a tile;
// vanished_foe_last_tile returns first with no sighting or on a bushless map. 8 TSR1: track_spinner_recall_bit only when recalling or a
// streak is open. 16 LBZ1: lethal_burst_zones returns with no foe in sight. 32 HAW1: heal_any's first test inline. 64 GPS1:
// guard_post_slow reads the Prism bag at the slot it has. 128 FAF1: faf_F memoised per group per round. 256 FAF3: faf_of's last result
// per crew size reused for the same F and strength. 512 RBF1: the turn-order ranks are filled in place. 1024 ARG1: AreaGrid's counts are
// not zeroed (build writes the window before best reads it). 2048 SBC1: same_bush_cluster's queue is not zeroed.
// v705 FB5: fb5 logic-identical (unlimited fuel), fuel -0.5%
#define FB5_BITS 4095
inline constexpr int FB5_TAB[2] = { 0x46423531, FB5_BITS }; // slot 0 magic keeps it out of .bss
// BHC (b1824, Rule Checker 10 Nov): comms/world/mapinfo fixes, one bit each. Runtime data flag, read first; 0 = off.
// Bit 1 TMAB: a camp-news post of mine overwritten before delivery restores the team belief it replaced (tb_kind, tb_asof, post_lo)
// instead of clearing it, so an ALIVE correction is sent again. Bit 2 DSALT: the draft's dash field lets an altar with walkable
// opposite neighbours be crossed (an altar is a legal dash middle, interactions.md:135), as thin holes are. Bit 4 DSTALE: a dead turn
// clears on_spawn and my state bits. Bit 8 SMR: a stunned ally's next-turn reach is 0 (the stun costs the whole turn, GR:124).
// v711 BHC: baked at its shipped value
#define BHC_BITS 15
inline constexpr int BHC_TAB[2] = { 0x42484331, BHC_BITS }; // slot 0 magic keeps it out of .bss

// CBH (b1816 combat bug hunt, Rule Checker confirmed 10 Nov, C42 corrections; bug bar). Runtime data flag, read first; 0 = nova_base_v705.
// One bit a fix. 1 ZDS1: a 0-damage spell (Cassi's stun, GR:454-458) no longer widens a foe's DAMAGE reach (foe_of_calc f.reach);
// the shared foe_next_turn_reach (stun roots and cancels channels, GR:275) is unchanged.
// 2 ZDS2: reach_burst_test runs the stun test for a foe whose hit is 0 (a stun-only foe still costs me my turn, INT:35).
// 4 RFE1: a foe seen recalling is forgotten only after its recall could have landed (channel time left; GR:274-275, INT:126).
// 8 PTS1 (RC PST2): no parting stun when a foe within its reach + 1 gets two turns before my next (INT:20-22, :35).
// 16 KSP1: react_kite / react_guard_slow shoot no foe on its own spawn that the hit does not kill (GR:124, :153).
// 32 VAK1 (RC X159): Varg's no-wake side hit picks a foe the engine reads alive (a kill earlier this turn).
// v710 CBH: 3 fixes sir1gt,hfx2s,cbh58
#define CBH_BITS 58
inline constexpr int CBH_TAB[2] = { 0x43424831, CBH_BITS }; // slot 0 magic keeps it out of .bss

// RC5 (b1815, Rule Checker C41 on v706, bug bar; one bit per row, read first; 0 = v706):
// 1 RTC1: a crew_left event taken by retarget_not_due on a turn that makes no choice (waiting at the target, fuel short, a
//   deferred choice) leaves the choice due next turn (T.eval_round pulled back), so the event is not lost (econ_retarget.cc).
// 2 RVC2b: target_turn_at_dead_group returns false when the Prism-wait test dropped the target (T.target < 0) instead of calling
//   capture() on the dropped group and spending the turn (econ_target_turn.cc).
// 4 CPX1 (CXL1, x165_crystal.md): compute_travel_t prices an ACC_TP group by my walk when its group field reaches me (a body a crystal
//   landed inside the ring), not only via crystal_ok, which is false once landed (travel UNREACH dropped the target and recalled).
// 8 RLG1 (x167_recall_guard.md): recall_loop_guard allows a stranded body's recall (no walk leads home); when the chain began at
//   my crystal landing, that group is banned in my memory for RCL_SC_SKIP rounds so the loop ends at home.
// 16 RLG2: the guard pushes sc_skip_until once per chain, not again on every refused turn.
#define RC5_BITS 31
#define RLG1_CNT(c) ((void)0) // fire count (diag copies)
#define CPX1_CNT(c) ((void)0) // fire count (diag copies)
// v711 RC5: baked at its shipped value
inline constexpr int RC5_TAB[2] = { 0x52433531, RC5_BITS };
// BF5 (b1831 bugfix5, Rule Checker X194; one bit per row, read first; 0 = v708):
// 1 YCH1: mate_yield and deadend_yield skip an ally that is channelling or stunned (it cannot take my tile: GR:387, INT:125/38).
// 2 ZDS1 (CBH bit 1 before v710 baked CBH 58): a spell with no damage does not widen foe_next_turn_reach's damage reach.
// v711 BF5: baked at its shipped value
#define BF5_BITS 3
inline constexpr int BF5_TAB[2] = { 0x42463531, BF5_BITS }; // slot 0 magic keeps it out of .bss
// X2I (b1835, Rule Checker X212 huge-map fuel cuts; logic-identical at unlimited fuel). Runtime data flag X2I_TAB[1], read first; 0 = v710.
// Bit 1 IDL1: the idle repick tests the walk time before its filters below 50k fuel. Bit 2 TSI1: threat_seen finds the groups near each
// foe through an anchor-x index (maps with 64+ groups). Bit 16 GBS1 is not built (cxeident: 23/70 huge-map games differ, cut-offs up). Bit 32 BCS1 (X214): bcl_ready partial-sorts the top 126 of (value, index) keys. Bit 64 SGM1 (X214): start_goal_i keeps
// its no-distance answer while its inputs stay. Bit 128 FMP1 (X214): fight_map caches a no-result scan until the distance progress moves.
// Bits 4 (ENDT1) and 8 (GBA1) are not built: they edit the code of lgm157 (ISUB1) and gbw31 (GBR2).
// v712 X2I: X212 logic-identical, fuel -3.4% on huge maps
#define X2I_BITS 227
inline constexpr int X2I_TAB[2] = { 0x58324931, X2I_BITS }; // slot 0 magic keeps it out of .bss
// VCD (b1825, spec_vcd_1110, VV Redesign: Vesper's short walks with a ready dash; ranged finishers off the region). 0 = nova_base_v704.
// Bit 1: Vesper's collection dash goes from 2 tiles out (IFD's Vendetta rule). Bit 2: after the clearing shot on her group, the capture
// holder dashes onto a camp tile 1-2 away (a dash uses neither allowance, INT:27, GR:118). Bit 4: the farm dash (vesper_dash_approach)
// also on the tank path at a cluster-only group. Bit 8: a ranged body walking to bring a living camp into range prefers a dead camp
// tile of the group among the goal tiles at the same (Chebyshev) distance.
// v715 VCD: stack package VSP (VJN+VTK+VGT+VCD)
#define VCD_BITS 7
inline constexpr int VCD_TAB[2] = { 0x56434431, VCD_BITS }; // slot 0 magic keeps it out of .bss
#define VCD_CNT(k, c) ((void)0) // fire count: the diag copy records site k when c; release: nothing, c unevaluated
// X3I (b1835, Rule Checker X212/X207/X179/X232: the huge-map identity fuel rows not in X2I; logic-identical at unlimited fuel). Runtime data
// flag X3I_TAB[1], read first; 0 = v714. Bit 1 GBA1: a paused bounds list stays in the scratch buffer until another call needs it.
// Bits 2 LBM1 / 4 LBE1 (b1825's PEM 4/8): the escape scan memoises lethal_burst_hit per (enemy, distance) / stops the sum at the cap.
// Bits 8 LCX1 / 16 LCP1: the camp layout is read without a zero-filled vector / without the counting pass.
// v719 X3I: huge-map identity rows X3I + FB6 56
#define X3I_BITS 31
inline constexpr int X3I_TAB[2] = { 0x58334931, X3I_BITS }; // slot 0 magic keeps it out of .bss
// TSO (b1850, Rule Checker X304, MAJOR fuel, logic-identical). Runtime data flag TSO_TAB[1], read first; 0 = v723. Bit 1 TSO1: tsi_near
// builds tsi_ord with a counting sort on anchor.x (indices pushed ascending: stable_sort's order) instead of std::stable_sort, which is
// insertion sort at <= 128 elements (78-90k in one call at a body's first flee on 64-128 group maps).
// v728 TSO: tsi_near counting sort, no insertion sort X304
#define TSO_BITS 1
inline constexpr int TSO_TAB[2] = { 0x54534f31, TSO_BITS }; // slot 0 magic keeps it out of .bss

// PFB (b1836, spec_pfb_1110, Prism audit /data/zw4424/st/prism/audit/results.md): verified Prism flaws. Runtime data flag PFB_TAB[1],
// read first; 0 = v715. Bits: 1 PF2 a non-winning channel that no later start could land (INT:119) is started / kept whatever the foe
// distance (GR:226); 2 her bag + my mates' carried bags that win (why 6) count as a winning bag at channel_start_ok, channel_doom_exempt
// and td_win; 4 PF6 the mate's wait episode resets only after a gap > PFB_TAB[3] (PC_ROUTE_WAIT really caps the wait); 8 PF8
// pc_hold_why is 0 at the top of want_bank; 16 PF9 the winning-channel kill test converts foe damage with Durability (INT:71);
// 32 PF10 the foe-finish horizon is rounds left to GAME_END (INT:119); 64 PF11 the calm area poke skips a foe on its own spawn the
// hit does not kill (INT:97); 128 PF14 win_bag_flee::own's recall-loop test uses her Tribute emblem (GR:312).
// PFB_TAB[2]: PF2's restart margin (rounds); PFB_TAB[3]: PF6's reset gap (fail window + wait cap).
// v722 PFB: PFB 7 Prism flaws, bit 2 dropped (adaptation)
#define PFB_BITS 253
inline constexpr int PFB_TAB[4] = { 0x50464231, PFB_BITS, 5, 20 }; // slot 0 magic keeps it out of .bss
#define PFB_ON(b) ((PFB_TAB[1] & (b)) != 0)
#define PFB_CNT(k, c) ((void)0) // fire count: the diag copy records bit k when c; release: nothing, c unevaluated
// VCR (b1823, Rule Checker VCDR1, minor bug). Runtime data flag VCR_TAB[1], read first; 0 = live. Bit 1: vcd_clear_dash_impl does not
// dash onto its target group once it has respawned (captured: GS_RESPAWN).
// v723 VCR: no clearing dash onto a respawned group (vcr1)
#define VCR_BITS 1
inline constexpr int VCR_TAB[2] = { 0x56435231, VCR_BITS }; // slot 0 magic keeps it out of .bss

// XIB (b1849, Rule Checker X290/X292 identical-cut fuel bundle, /data/zw4424/rulecheck/p6/x290_identical_bundle.md, x292_countfirst.md).
// Logic-identical fuel cuts; 0 = v725. Only rows fuel-negative alone at unlimited AND at 100k on pool and huge maps are kept. Bits: 16 X148b1
// squad::begin_turn returns on an unchanged claim image; 256 EMC1 emd_observe's camp_index only on a reward; 512 PHB1 prestep skips asleep
// camps first; 16384 BWX1 bush_place returns when my ward lights the whole box; 2097152 DTV1 comms::read skips the decode when the 8-byte team
// memory is unchanged. The table is read once at start-up into xib_bits (no volatile read at the sites; flips still patch the table).
// v729 XIB: X290 identical fuel cuts (XIB)
#define XIB_BITS 2114320
inline constexpr int XIB_TAB[2] = { 0x58494231, XIB_BITS }; // slot 0 magic keeps it out of .bss
// v729 XIB: X290 identical fuel cuts (XIB)
inline constexpr int xib_bits = XIB_TAB[1]; // v740 baked: copy of the baked flag word
#define XIB_ON(b) ((xib_bits & (b)) != 0)
// XCF (b2005, RC X445 combat fuel, /data/zw4424/rulecheck/p6/x445_combat_fuel.md): logic-identical cuts; 0 = v774. Bits: 1 LHE1
// handle_low_hp asks ehc_herd_crew only at nearest 7..8; 4 PSL1 prism_slot cached at the P.type writers; 8 RTH1 refuge_tile returns
// at once off the spawn board grown by 1.
// v778 XCF: XCF+XOA identical fuel cuts -1.0M/g
#define XCF_BITS 13
inline constexpr int XCF_TAB[2] = { 0x58434631, XCF_BITS }; // slot 0 magic keeps it out of .bss
// v778 XCF: XCF+XOA identical fuel cuts -1.0M/g
inline constexpr int xcf_bits = XCF_TAB[1]; // v779 baked: copy of the baked flag word
#define XCF_ON(b) ((xcf_bits & (b)) != 0)
// XOA (b2005, RC X448 observe/assess, /data/zw4424/rulecheck/p6/x448_observe_assess.md): logic-identical cuts; 0 = v774. Bits: 1 XOA1
// the seen walk skips consider for a non-ALIVE/CLEARED group whose team round is already exact; 2 XOA2 local power returns when no
// rule can fire (not CALM and no bag case; CALM with no foe near reach).
// v778 XOA: XCF+XOA identical fuel cuts -1.0M/g
#define XOA_BITS 3
inline constexpr int XOA_TAB[2] = { 0x584F4131, XOA_BITS }; // slot 0 magic keeps it out of .bss
// v778 XOA: XCF+XOA identical fuel cuts -1.0M/g
inline constexpr int xoa_bits = XOA_TAB[1]; // v779 baked: copy of the baked flag word
#define XOA_ON(b) ((xoa_bits & (b)) != 0)

// WBN (b1853, Rule Checker X321 ward bundle WRB). Runtime data flag WBN_TAB[1], read first; 0 = off. Bit 1 WPC1: place_chosen_ward's
// silent false (a mate's unseen ward, INT:149) records the tile as an ally ward, as scout/react/bsx do. Bit 2 WAS1: scan_allied_wards
// erases a noted mate ward as 'seen empty' only on my vision now (my_current_vision), not perceive's pre-move board. Bit 4 (bot_errors row
// 768, X321 WBS1's site): bush_place's silent false or rc 117 records the tile as an ally ward (WBS1's own-state part: 0 firings, not built).
// Bit 8 WAN1: a tile noted from a refusal (owner unknown) expires after 40 rounds (a mate relocates its ward; a retry costs one call).
// v733 WBN: X321 ward bundle WPC1/WAS1/768/WAN1
#define WBN_BITS 15
inline constexpr int WBN_TAB[2] = { 0x57424E31, WBN_BITS }; // slot 0 magic keeps it out of .bss
// AWR (b1836, WST1 v2 = AWS1's one adaptation, RC idle list v753 (c)1). Runtime data flag AWR_TAB[1], read first; 0 = off. Bit 1: a ward
// placement refused with rc 117 (a mate's ward holds the tile; teammates' wards are not shared, GR:367) notes the tile as today and tries
// the next pick the SAME turn, once: place_chosen_ward re-picks (prepare_check, reachable_weights, pick_ward_tile, the same gate) and
// scout re-runs. A refused action spends nothing (GR:169).
// v755 AWR: rc117 ward refusal retries next pick same turn
#define AWR_BITS 1
inline constexpr int AWR_TAB[2] = { 0x41575231, AWR_BITS }; // slot 0 magic keeps it out of .bss
// VBC (b1851, RC X323 vbb coupling variants; one bit per variant). Runtime data flag VBC_TAB[1] (cached in vbc_bits), read first; 0 = v731.
// 1 VTKW12: Vesper take-over t = cs.timer on the cleared branch, clear + pay + 1 on the alive branch (INT:109).
// 2 ECP1k: a ward-seen foe capture's respawn uses the engine countdown; the TAKEN dedup keeps the old estimate (GroupMem::ecp_d).
// 4 ECP1t: the same fix, and the corrected timer goes to mates at once (record_group_taken).
// 8 CRT1s: the crystal escape's stun leg spans 3 ticks; the damage and unseen-sighting legs keep 4 (GR:275).
// 16 TTR1nv: foe two-turn reach at dash cd 1 exact (GR:118) everywhere except danger_veto. 32 TTR1d: exact at the deny lock only.
// v737 VBC: foe capture countdown, old TAKEN dedup (ECP1k)
#define VBC_BITS 2
inline constexpr int VBC_TAB[2] = { 0x56424331, VBC_BITS }; // slot 0 magic keeps it out of .bss
// v737 VBC: foe capture countdown, old TAKEN dedup (ECP1k)
inline constexpr int vbc_bits = VBC_TAB[1]; // v740 baked: copy of the baked flag word
#define VBC_ON(b) ((vbc_bits & (b)) != 0)

// VB2 (b1807, MINOR verified-bug bundle VBB2; bug bar). Runtime data flag VB2_TAB[1], read once into vb2_g (no volatile read in loops);
// 0 = v729. 1 ESD1 (RC X311): foe_damage_over_turns with n >= 2 turns sums the two turns (lethal_burst_two_turn_hit's memo), not the max of
// one hit. 4 EBW1 (RC X281): the winning-bag recall cancel takes the walk path's own safety test instead of the fixed 10-tile cap. 8 LBS1
// (RC X314): the FIGHT->FLEE burst test counts a ready self-shield on the stay tile (shield kit, no dash). (TRX1, bit 16, dropped by
// the per-bit screen: .4883 n599.) 32 CTG1 (Path Finding): the support fuel bail with no hit steps on the group field and counts
// the idle turn. 64 XDT1 (RC X319): dlf_pick_ok tests DTA's altar (where the lock goes), not nearest_altar. (HDE2, RC X317,
// fired 0 in a 200-game census with its counter: not carried.) 128 BB7 row 432 (RC X324, C116): the opening recall refreshes
// after a fresh recall(). 256 XDF1 (RC X319): gd_mem stores lock-only; the follow walk then uses DTA's altar and counts no stun-only mate.
// MRC1 (RC X328, try_move keeps the tile on rc 34/35/123): .705/g alone, 0 with BB7 on (the same stale-recall refusals): not carried.
// v742 VB2: VBB2b 7 MINOR rows (TRX1 dropped by screen)
#define VB2_BITS 493
inline constexpr int VB2_TAB[2] = { 0x56423231, VB2_BITS }; // slot 0 magic keeps it out of .bss
inline int vb2_g = -1;
inline int vb2_bits() { if (vb2_g < 0) vb2_g = VB2_TAB[1]; return vb2_g; }
#define VB2_ON(b) ((vb2_bits() & (b)) != 0)
// MBB (b1882, MINOR verified-bug bundle; bug bar). Runtime data flag MBB_TAB[1], read once into mbb_g; 0 = v756.
// 1 SSH: on spawn, spawn_refuge does not hold the turn when every foe within its range + 1 of me stands on its own spawn (GR:153).
// 2 GRF1: guard_post remembers for 6 rounds a mate that out-scored me (unseen now, alive). 4 GRF2: the PGW stall counter also counts
// a guard turn two rounds back. 8 EGL: a known foe bag that ends the game buys the altar lock before the shop spends the gold.
// 32 DLT1 (RC X360): dlf_pick_ok gives an acted foe's tribute its +1 round (GR:226/275). 1024 PAS1 (b1863, RC X354/C287): Ryth's
// parting area stun counts chasers on their own spawn (a stun lands there, INT:35). Not carried (0 firings in a 300-game census):
// HDE2 (b1807 census), CSL2, TVS1 (RC X360), HPG3, SMS1 (RC X362).
// v757 MBB: minor bug bundle (SSH GRF EGL DLT1 PAS1)
#define MBB_BITS 1071
inline constexpr int MBB_TAB[2] = { 0x4D424231, MBB_BITS }; // slot 0 magic keeps it out of .bss
inline int mbb_g = -1;
inline int mbb_bits() { if (mbb_g < 0) mbb_g = MBB_TAB[1]; return mbb_g; }
#define MBB_ON(b) ((mbb_bits() & (b)) != 0)
#define VB2_CNT(k, c) ((void)0) // fire count: the diag copy records bit k when c; release: nothing, c unevaluated

// EHC (spec_ehc_1109, Combat; Deep's elk-herd lead, 01elk_arena 01a1c16e; b1760): our bodies leave an awake herd for foes 7-8 away. 0 =
// nova_base_v660. Bit 1 CRH: a committed retreat stops when no foe has been seen for 2 rounds, HP >= .55 (linked .60) and my awake target
// has 2+ crew within 6. Bit 2 CRZ: a held-over FLEE (nearest >= 7, nothing in reach) does not mark the herd as a threat target. Bit 4 HLX:
// with my target awake and 3+ crew present, the heal exemption and the 59% leave line count a foe as near at 6, not 8.
// v745 EHC: fpb5 bank bundle bk5b+ehc3s+rts
#define EHC_BITS 7
inline constexpr int EHC_TAB[2] = { 0x45484331, EHC_BITS }; // slot 0 magic keeps it out of .bss
// PFA (b1875, Path Finding path_fault_ledger_1111 bundle 1): self-undoing flee and home steps. Runtime data flag PFA_TAB[1], read
// first; 0 = v754. Bits: 1 SOP step_out_of_reach skips a fresh prev_pos (as retreat_step) unless it is the only out-of-reach tile;
// 2 GHP2 go_home with no lower homeward tile leaves a fresh prev_pos out of its goal sets; 4 DAR1 dash_away tries the next best
// landing after one an unseen occupant refused (GameRules.md:167-169), up to 3 casts. pfa_fc_N mark a changed decision (diag counts).
// v766 PFA: PFA6 BIG2 re-read
#define PFA_BITS 6
inline constexpr int PFA_TAB[2] = { 0x50464131, PFA_BITS };
__attribute__((noinline)) inline void pfa_fc_1() { __asm__ volatile(""); }
__attribute__((noinline)) inline void pfa_fc_2() { __asm__ volatile(""); }
__attribute__((noinline)) inline void pfa_fc_4() { __asm__ volatile(""); }

// RCFX (b1877, RC X341 sight-gated mates, /data/zw4424/rulecheck/p6/x341_sightcrew.md): a mate unseen but known busy/claimed counts as
// its sibling code already counts it. 0 = nova_b12307_awr1. Bits (1 unused: DCM1 fired 0/200 games, not built): 2 CWL1
// crew_wait_crew_here adds unseen busy claimants (cwv_unseen_busy); 4 EHC1 ehc_herd_crew counts an
// unseen engaged claimant; 8 SQR1 rally_present_count's squad branch gets the mate_recently_near_rally fallback.
// v756 RCFX: unseen busy mates in crew wait + rally (CWL1 SQR1)
#define RCFX_BITS 10
inline constexpr int RCFX_TAB[2] = { 0x52434658, RCFX_BITS }; // slot 0 magic keeps it out of .bss
// WFL (b1878, fuel-floor census 1111): ward fuel floors fitted to the measured cost. Runtime data flag WFL_TAB[1], read first;
// 0 = v756. Bits: 1 stage_finish (ward_analyse.cc) needs reserve + cov_cost + 500 per bush spot actually found + 2k (measured: cov_cost +
// <= 290 per spot, 18.8k max) instead of + 2000 x MAX_BUSH (~79k on most maps, refused ~170 turns/g); 2 act() enters at 40k instead
// of ACT_FUEL 55k when this game's act() prefix (no floor of its own, up to ~35k on many-group maps) allows: max prefix + 25k.
// wfl_fc_N mark a turn flag 0 refused (diag counts).
// v762 WFL: WFL1 analysis floor at measured cost only
#define WFL_BITS 1
inline constexpr int WFL_TAB[2] = { 0x57464C31, WFL_BITS }; // slot 0 magic keeps it out of .bss
__attribute__((noinline)) inline void wfl_fc_1() { __asm__ volatile(""); }
__attribute__((noinline)) inline void wfl_fc_2() { __asm__ volatile(""); }
// MNR (b1947, MINOR bundle on v763). Two runtime data flags, each read first; 0 = v763.
// MNR_BITS, logic-identical rows: 1 FEC H14a step_greedy(_fresh) drop v * GREEDY_TILE (v = cur - 1, a constant shift); 2 FEC H14b
// step_to_set drops v * STEP_TILE (exact field); 4 FEC I10 fitfeat::compute skips the features no decision reads (F_HEAVY, F_CLU_GEM,
// F_CLU_GOLD, F_RECALL stay 0); 8 WFL stage_finish skips the wfl_fc_1 diag test; 16 X369 A3 MCL2 carries a presence bit (field bit 15)
// once computed (no reader yet); 32 X369 A4 the MCL byte is written only while MCL_BITS bit 1 (the documented gate) is on.
// MNR_PC_BITS, play-changing minor fixes: 1 THT1 (RC X387) thin_hole_turn drops its plan when the step onto path.front() is refused;
// 2 LKA1-B (RC X397) bbl_our_lock_on remembers an altar_lock_already_locked refusal per altar for MNR_LKA_R rounds (a hidden altar
// reads api_not_in_vision, not "no lock") and a refused lock keeps lock_known; 4 IT1 (RC X398) upitm_post moves the part-bought
// occurrence of a repeated family (emblems owned + 1), not the first; 8 GRT1 (RC X399 HZ2) greed_gate's horizon is the leader's
// r^1.7 tribute pace (grt1_rounds_left), not the straight-line pace.
#define MNR_BITS 31
#define MNR_PC_BITS 15
// v776 MNR: B2 re-carry OBF+CCX+XFE identical fuel cuts
#define MNR_LKA_R 20
inline constexpr int MNR_TAB[2] = { 0x4D4E5231, MNR_BITS }; // slot 0 magic keeps it out of .bss
// v767 MNR_PC: MNR minor bugs THT1 LKA1-B IT1 GRT1
inline constexpr int MNR_PC_TAB[3] = { 0x4D4E5232, MNR_PC_BITS, MNR_LKA_R };
// SRL (b1891, RC X364 /data/zw4424/rulecheck/p6/x364_rrcensus.md): reached-range bugs. 0 = nova_b12323_cwsq1. Bits: 1 SRN1 spawn_refuge
// casts free_cast() (single-target nuke, falls back to free_aoe) instead of free_aoe() (bot_errors 154a, be2b1 port); 2 LKT1 bank_i
// starts the tribute the same turn its hit broke the foe lock (INT:123); 4 SHK1 turn_tail shops again on spawn after kill gold arrives (GR:110).
// v759 SRL: swept v759: shipped value with no ledger record
#define SRL_BITS 6
// v7xx RKB (b1912 bug-bar bundle): bit 1 R2B 8192 E6, my or an allied Capture holder on the group prices its capture 1 + 3 (GameRules:196) in finish_target_before_shop
// v761 RKB: allied Capture holder prices capture 1+3
#define RKB_BITS 1
inline constexpr int RKB_TAB[2] = { 0x524B4231, RKB_BITS }; // slot 0 magic keeps it out of .bss
inline constexpr int SRL_TAB[2] = { 0x53524C31, SRL_BITS }; // slot 0 magic keeps it out of .bss
// SMZ (b1976, SSM step 0 identity, spec_ssm_1111 + RC C316): 1 D1 setup re-runs strat::begin_turn once build_plan decoded the
// draft's Mode, so the setup turn plays that Mode's policy; 2 an empty item_plan falls through to item_plan_base, and SIEGE plays the
// base plan (its Monster plan waits for SSM bit 2). Identity today: every game plays BASE.
// v773 SMZ: SSM step 0 identity (D1, empty item plan)
#define SMZ_BITS 3
inline constexpr int SMZ_TAB[2] = { 0x534D5A31, SMZ_BITS }; // slot 0 magic keeps it out of .bss
// OBF (b1966, RC X412 + X405: logic-identical fuel bundle). Runtime data flag OBF_TAB[1], read first; 0 = v768. Bits: 1 OBX1 observe skips
// a group's member loop when none of its member tiles (per-group bitboard words, at most 2) is in sight; 2 OBX2 observe lists the groups it
// saw and the camp-news scan walks that list (same set, same order); 4 WSS1 bush_score_step's box test four spots at a time (SIMD).
// v776 OBF: B2 re-carry OBF+CCX+XFE identical fuel cuts
#define OBF_BITS 7
inline constexpr int OBF_TAB[2] = { 0x4F424631, OBF_BITS }; // slot 0 magic keeps it out of .bss
// CCX (b1950, RC X395 combat + turn-loop identical fuel cuts, /data/zw4424/rulecheck/p6/x395_combatfuel.md). 0 = v766. Each bit gives
// the same play with less fuel. Bits: 1 VDB1 perceive reads my vision board once (bc_champion_vision of my own body is the engine's
// GetVision, the board sdk_vision returns); 4 DCS1 comms::read decodes only the claim bytes (and the event) the 8-byte image changed.
// (Bit 2 FPS1 dropped: not fuel-negative at 100k on fresh, b1950.)
// v776 CCX: B2 re-carry OBF+CCX+XFE identical fuel cuts
#define CCX_BITS 5
inline constexpr int CCX_TAB[2] = { 0x43435831, CCX_BITS }; // slot 0 magic keeps it out of .bss
// v776 CCX: B2 re-carry OBF+CCX+XFE identical fuel cuts
inline constexpr int ccx_bits = CCX_TAB[1]; // v779 baked: copy of the baked flag word
#define CCX_ON(b) ((ccx_bits & (b)) != 0)
// MBB5 (b2015, RC X456, minor bug bundle, report analysts/prism_altar_pacing_cc34_1111.md, witness 01a1cc34): 1 AWM1 update_awake_mem keeps a
// remembered awake camp out of sight while I stand in its reach (GR:192: it cannot sleep with a champion in range; INT:103 it hits through
// walls); 2 AWM2 bank_leave_camps: this round's loss fits one unseen camp whose reach covers me (hidden_fire's tests): remember it awake;
// 4 WBW1 rate_for refuses an asleep group with a living monolith, golem or elk while tributed_us + my bag >= WIN_TRIBUTE (do not wake it);
// 8 WBW2 (Middle) the same for any asleep group; 16 WBW3 (Wide) a winning bag skips the farm step (idle_bank, else holds; the end escape runs).
// v777 MBB5: MBB5 AWM1 awake camp in reach + WBW1 winning-bag heavy skip
#define MBB5_BITS 5
inline constexpr int MBB5_TAB[2] = { 0x4D424235, MBB5_BITS }; // slot 0 magic keeps it out of .bss

// SUT (b2026, RC X460): many-group setup-turn fuel cuts, logic-identical. Bits: 1 BCL1 full sort in bcl_ready, 2 KPW1 kit cache warmed on
// the analysis turn, 4 EIF1 econ::init's per-group loops in one pass, 8 RFD1 read_foes reads the enemy roster once.
// v781 SUT: SUT setup-turn identical cuts without KPW1
#define SUT_BITS 13
inline constexpr int SUT_TAB[2] = { 0x53555431, SUT_BITS }; // slot 0 magic keeps it out of .bss
// MBB7 (b2038 minor bug bundle): 1 RWL1 (RC X475, GR:118) respawn_wait_lifted's nearest-free-body test skips channelling or stunned
// mates; 2 RHS1 (RC X474, GR:124/153) a foe last seen on its spawn is remembered at full HP; 4 CI2X2 (RC X483, GR:381) the lock-break
// reset, mark_groups_near_kill and the siege call read the C&I pair's bag.
// v783 MBB7: MBB7 RWL1 chan mate, RHS1 spawn HP, CI2X2 bag
#define MBB7_BITS 7
inline constexpr int MBB7_TAB[2] = { 0x4D424237, MBB7_BITS }; // slot 0 magic keeps it out of .bss
// MBB10 (b2079 minor bug bundle; bug bar). Runtime data flag, read first; 0 = v789. 1 VTK2 (RC X499, GR:207) vtk_take_rate prices a
// take-over with mates on the region as the split team value (her share x her mu + each mate's share x theirs).
// v790 MBB10: VTK2 Vesper take-over split value
#define MBB10_BITS 1
inline constexpr int MBB10_TAB[2] = { 0x4D423130, MBB10_BITS }; // slot 0 magic keeps it out of .bss
// MBB11 (b2079 minor bug bundle; bug bar). Runtime data flag, read first; 0 = v790. 2 SGP1 (RC X508, GR:256-262) the siege stat ratio uses
// sqrt(maxHP x kit damage per turn), with SG_SR / SG_CREW_SR re-mapped to MBB11_SGP_SR; 4 CDM1X (RC X491/C481, GR:192, INT:105) the fight
// walk-in keeps out of each awake heavy camp's exact target zone (the tiles where I would be its nearest body or win its tie);
// 16 COL1 (RC X515/C463 F7, INT:59, BalanceChanges.md:1243) emblem_rank: with Collectors owned, a first Power or Bruiser adds a family (+1%).
// v792 MBB11: COL1 Collectors family bonus in emblem rank
#define MBB11_BITS 16
inline constexpr int MBB11_TAB[2] = { 0x4D423131, MBB11_BITS }; // slot 0 magic keeps it out of .bss
// BCP (b2116, RC X531): bit 1 BCP1: the BCL rank list (> 126-group maps) is sorted on a setup turn before M.init; bcl_on still flips on the
// same call as before. Logic-identical. 0 = v793.
// v798 BCP: BCP1 setup rank sort + GTB1 bg table
#define BCP_BITS 1
inline constexpr int BCP_TAB[2] = { 0x42435031, BCP_BITS }; // slot 0 magic keeps it out of .bss

// VGB (b2072, RC X500 VGB1, owner: never burn out on extreme maps): logic-identical growth-copy cuts in ward::analyse's bush stages
// (inlined into play_turn_body: cutprof's play_turn_body > vector<vec2>::__emplace_back_slow_path on w_bushall). Runtime data flag
// VGB_TAB[1], read first; 0 = v786. Bit 1 VGB1: stage_bush_tiles reserves bush_tiles to the bush board's popcount before the scan;
// bit 2 VGB2: the cluster list cl is reserved to bush_tiles.size() before the clusters grow (a cluster never exceeds it).
// Baked (constexpr 3) companion of nova_b2072_vgb.
#define VGB_BITS 3
inline constexpr int VGB_TAB[2] = { 0x56474231, VGB_BITS }; // slot 0 magic keeps it out of .bss

// BWN (b2158, RC X553): logic-identical cut-family fuel rows. Runtime data flag BWN_TAB[1], read first; 0 = v804.
// Bit 1 BWC1: ward bush_place lists up to 512 contested anchors (was 64) so the per-tile all-groups loop never runs.
// Bit 2 NFQ1: next_farm_nearer_than_spawn reads the group field pointer before claimants() (same AND, order only).
// v809 BWN: bounded walk anchors + field-first claim test (BWN)
#define BWN_BITS 3
inline constexpr int BWN_TAB[2] = { 0x42574e31, BWN_BITS }; // slot 0 magic keeps it out of .bss
// b2157 TMR (RC X574 team/comms riders). Bit 1 HMR1: a HELP whose raw equals my last post's is mine only within 4 rounds of that post
// (help_my_raw is never cleared; raw = cell + round mod 32). Bit 2 RTY1: rally-ally ties (combat_flee rally_ally, combat_team
// react_rally) go to the lower home_steps, then msy_before, not W.allies order (seat-dependent). Bit 4 CTB1: the thin-hole centroid
// distance in int64 (WASM32 long is 32-bit; dx*dx overflowed past ~46k).
// v812 TMR: TMR help-raw clear, seat-free rally ties, int64
#define TMR_BITS 7
inline constexpr int TMR_TAB[2] = { 0x544D5231, TMR_BITS }; // slot 0 magic keeps it out of .bss

// RQN (b2158, RC X588 RQN1, bug bar): carry_recall::foe_can_hit (RCQ2's carry-start block) read only the foe's next turn; any hit in the
// channel's foe turns cancels the recall. Runtime data flag RQN_TAB[1], read first; 0 = v813. Bit 1 RQN1: n = foe_turns_during_recall(sps_pending).
// v815 RQN: recall safety counts all channel foe turns (RQN1)
#define RQN_BITS 1
inline constexpr int RQN_TAB[2] = { 0x52514E31, RQN_BITS }; // slot 0 magic keeps it out of .bss
// b2176 BAF (RC X604): bush_place's contested-anchor list keeps only anchors with cheb(anchor, me) <= reach_r + 6 (every candidate
// tile is within reach_r of me, so a farther anchor can never be within 6 of one: play-identical). Bit 1 BAF1. 0 = v814.
// v818 BAF: bush_place anchors within reach+6 only (BAF1)
#define BAF_BITS 1
inline constexpr int BAF_TAB[2] = { 0x42414631, BAF_BITS }; // slot 0 magic keeps it out of .bss
// b2214 TSZ (TMS1 redo, spec tms_redo_1112 + RC C611; patch bank tms1 from b1991): bit 1 TMS1 a 6-body team takes the slim claim
// layout where it fits even where the full one does not (comms.cc init_message_layout; saved = 0 there, so the channel sizes K
// from the slim layout), only while at least one spare bit stays free after the channel (TTE1's team bit); bit 8 TMS1K with bit 1:
// there the packed slim field frees its unused bits for the channel. 0 = v822.
// v826 TSZ: slim message layout keeps the full fit (TMS1)
#define TSZ_BITS 9
inline constexpr int TSZ_TAB[2] = { 0x54535A31, TSZ_BITS }; // slot 0 magic keeps it out of .bss
// b2225 RDR (RC X645, per-body state across death and respawn; GR:375 respawn resets abilities, INT:17 a dead body writes team memory).
// Runtime data flag RDR_TAB[1], read first; 0 = v823. Bit 1 free (RPZ1 closed by count: 0 pre-death paused turns in 380 games).
// Bit 2 WRS: dead_turn clears ward::ready_since, so the ward wait restarts at respawn. Bit 4 DMC1: the assess's coming
// mates skip a mate that is dead this round. Bit 8 DMC1b: help_fight_call's support curve skips a dead eta-1 mate. Bit 16 OPN1:
// team_bag_total drops a dead mate's stored bag. Bit 32 HP2: a body's first dead turn posts a FIGHT stop over its own live call.
// b2320: RDR reverted (sites removed; = v826 behaviour)
#define RDR_BITS 0
inline constexpr int RDR_TAB[2] = { 0x52445231, RDR_BITS }; // slot 0 magic keeps it out of .bss
// b2315 HP2S (RC X742: HP2 alone after the v834 RDR revert, with the DMC1/DMC1b riders; GR:375, INT:17 a dead body writes team
// memory, INT:22 is_alive readable out of sight). Runtime data flag HP2S_TAB[1], read first; 0 = live. Bit 1 HP2: a body's first dead
// turn posts a FIGHT stop over its own fresh rally/commit call. Bit 2 DMC1: the assess's coming mates skip a mate that is dead now.
// Bit 4 DMC1b: help_fight_call's support curve skips a dead eta-1 mate.
// v842 HP2S: dead body posts a stop over its own fight call
#define HP2S_BITS 7
inline constexpr int HP2S_TAB[2] = { 0x48503253, HP2S_BITS }; // slot 0 magic keeps it out of .bss

// GSL (b2337, RC X779 GHST1, bug bar): runtime data flag, read first; 0 = v845. Bit 1: threat_tiles (move_escape.cc, the step_away
// paths) skips remembered foes with reach -1 (3-4 round old sightings), keeping all only when none is left. (SLLB1 counted 0/300: dropped.)
// v851 GSL: swept v851: 0 in live and nova_b13966_rrz1r, no line flips it
#define GSL_BITS 0
inline constexpr int GSL_TAB[2] = { 0x47534C31, GSL_BITS }; // slot 0 magic keeps it out of .bss
// TVW (b2349, PCQ 2b Step 0's one valid piece): a dead body's last dead turn warms TVM bit 1's travel memo for the tile it should respawn on
// (econ_travel_gates.cc tvw_dead_warm). Runtime data flag TVW_TAB[1], read first; 0 = v845. Bit 1 WARM. [2] the fuel the warm needs.
// v852 TVW: TVW dead-turn travel warm for respawn tile
#define TVW_BITS 1
inline constexpr int TVW_TAB[3] = { 0x54565731, TVW_BITS, 75000 }; // slot 0 magic keeps it out of .bss
// b2233 BWT (spec_bwt_1112 + Amendment 1, RC C670 WCT3/BWT1; owner replay 01a1cf4a): a camp member on a bush tile whose cardinal bush
// cluster holds no non-camp tile ("hidden member", draft-time class: MCL4 bit 16 HIDMEM; a missing byte reads OFF). Runtime data flag
// BWT_TAB[1], read first; 0 = v824. Bit 1 BWT_BUMP: adjacent to the class tile, a refused move onto it (free) reveals the member:
// perceive() and hit it this turn. Bit 2 BWT_WARD: no bump this turn: place_ward on the class tile, perceive(), the warding body hits.
// With bit 1 or 2 the 6-look / 60-round ban of target_turn_look_from_bush does not run on the class tile while the act lands hits.
// Bit 4 WCT3: camp_tile_blocks_ward and the react / vanished-foe bush pickers allow the class tile (only).
// v856 BWT: BWT7 rebased (brace lost in the merge)
#define BWT_BITS 7
inline constexpr int BWT_TAB[2] = { 0x42575431, BWT_BITS }; // slot 0 magic keeps it out of .bss

// DCG (b2377, RC X817 draft/play fuel guards on the map-class computes). Runtime data flag, read first; 0 = v856. Bit 1 DCG1 (draft): handoff's
// mcl4_compute (BWT HIDMEM flood + JKC) runs only with dcg1_need() fuel left (class estimate + the encode and submit after it); else it is
// skipped this handoff and the MCL4 byte stays absent (bwt_class reads OFF). Bit 2 BWTP1 (play): bwt_hid_build runs only with
// dcg_bwt_need() fuel left; until then bwt_hid_count reads 0 (OFF) and retries on a later call.
// v859 DCG: DCG1 fuel guard on handoff class computes
#define DCG_BITS 1
inline constexpr int DCG_TAB[2] = { 0x44434731, DCG_BITS }; // slot 0 magic keeps it out of .bss
// ALHV1 (b2381, RC X805 S1): intel bumps alhv_ver at every write of its foe team table (init, a death or respawn, my or a ward's sighting);
// altar_hold_note returns early while the version and the table size are unchanged (both loops would write the same values).
// Runtime data flag ALHV_TAB[1], read first; 0 = v864.
// v866 ALHV: ALHV identical fuel cut (rebased v864)
#define ALHV_BITS 1
inline constexpr int ALHV_TAB[2] = { 0x414C4856, ALHV_BITS }; // slot 0 magic keeps it out of .bss

// CFL (b2361, RC X851 fuel floors; RC C1113/C1113b): runtime data flag CFL_TAB[1], read first; 0 = v868. Bit 1 LSA1: at fuel <= CFL_TAB[3]
// (= mv ESC_AWAY_FUEL 15k) step_away's three unfloored sites (handle_low_hp, escape, escape_toward's VFL line) take mv::cfl_cheap_away instead:
// one greedy step to the free neighbour farthest from the threats, never into an awake camp's reach. Bit 4 TTF1: turn_tail runs only above
// CFL_TAB[2] fuel (the tail's measured p95 1.6k, p99 2.1k on 40 hms maps x2). [2] the tail floor, [3] the step-away floor.
// v870 CFL: CFL1 cheap step-away under 15k fuel
#define CFL_BITS 1
inline constexpr int CFL_TAB[4] = { 0x43464C31, CFL_BITS, 2000, 15000 }; // slot 0 magic keeps it out of .bss
// VTW (b2392, VTKW bundle; RC X323 VTKW1/VTKW2, X859 VTKW3; Vesper take-over rate vtk_take_rate econ_rate.cc; bug bar). Runtime data flag,
// read first; 0 = live v868 (VBC bit 1, the old home of VTKW1/2, is baked off). Bit 1 VTKW1: an alive group's take-over pays the round after
// the capture timer ends (t = clear + pay + 1, INT:109). Bit 2 VTKW2: a cleared group's payment comes at now + timer (t = timer, not trav +
// timer). Bit 4 VTKW3: the alive window refuses only when a > clear + pay (it was clear + pay - 1, one round short v the cleared branch's
// trav <= timer - 1). Bit 8 RAK1 (RC X861): fight() skips the area cast when a melee body one step out of reach kills the focus by walk +
// hit + reset hit and the area alone does not (the cast rules out the walk). Bit 16 VCS2 (RC X861): channel_safe_check gives a splash foe
// reach + 1 when a mate stands within 1 of my channel tile.
// v874 VTW: small-fix bundle A (VTKW RAK1 VCS2 PKR FMH ADC CPT1)
#define VTW_BITS 31
inline constexpr int VTW_TAB[2] = { 0x56545731, VTW_BITS }; // slot 0 magic keeps it out of .bss
// PKR (b2392, owner replay 01a1d2d2 v Sponge, owner_01a1d2d2_prism_cancel_1113.md Arm A; PFB bit 2's keep side, narrow form): while she
// channels a tribute, channel_doom_exempt also counts her bag as winning when tributed_us + her bag + the bags of visible mates IN a tribute
// channel whose timer <= her ticks left reach WIN_TRIBUTE (their gems land first; GR:226/:275 damage does not stop a tribute). Runtime
// data flag, read first; 0 = live v868. Bit 2 (B+C, RC C1109, verified bug: the v722 pfb253 drop left the stop test only in comments): with
// PC_DOOM_LEFT <= left <= PKR_TAB[2] (K) ticks left, channel_doomed cancels only when a foe can STOP the tribute (GR:226/:275: a stun,
// a new altar lock or her death): a ready stun landing within its turns (foe_turns_within_rounds, double turns count), a lock holder
// within lock reach, or damage over the remaining turns >= HP + shield; a remembered unseen foe enters with its distance cut by the
// rounds since seen (one tile a round), its kit's stun and a possible lock within lock reach + a dash (C, RC C1109b).
#define PKR_BITS 3
// v874 PKR: small-fix bundle A (VTKW RAK1 VCS2 PKR FMH ADC CPT1)
#define PKR_K 3
inline constexpr int PKR_TAB[3] = { 0x504B5231, PKR_BITS, PKR_K }; // slot 0 magic keeps it out of .bss
// FMH (b2392; Deep spec_fmh_1113, RC C1131 CONFIRMED, bug bar; witness 01a1d2ff shop recall at 973/1000): finish_mode_hold (econ_recall_heal.cc)
// returned false whenever T.target < 0, the state right after a bank, so the finish-mode shop hold never held there. Runtime data flag, read
// first; 0 = live v868. Bit 1: with no target, skip the target tests and apply the horizon and value test alone (the finish_mode, mem-size
// and 15k fuel guards stay).
// v874 FMH: small-fix bundle A (VTKW RAK1 VCS2 PKR FMH ADC CPT1)
#define FMH_BITS 1
inline constexpr int FMH_TAB[2] = { 0x464D4831, FMH_BITS }; // slot 0 magic keeps it out of .bss
// CGT (b2392, RC X866 CPT1, bug bar): capm_gone (econ_capture.cc, CAPM bit 1) counts a channelling mate whose channel lands before the
// capture pays as off the region, but a TRIBUTE does not move the body (GR:226; only recall and crystal relocate, GR:275). Runtime data flag,
// read first; 0 = live v868. Bit 1: a tributing mate is not gone.
// v874 CGT: small-fix bundle A (VTKW RAK1 VCS2 PKR FMH ADC CPT1)
#define CGT_BITS 1
inline constexpr int CGT_TAB[2] = { 0x43475431, CGT_BITS }; // slot 0 magic keeps it out of .bss
// b2365 RTZ (prefix RTZ: RLX is taken in failure_chains; RC X875 RLX1, GR:387-389 recall completes at the owner's next turn start after timer 0; GR:124 camp phase after all champion
// turns): a recalling body at channel time 0 that has not acted this round leaves for its spawn before the camp phase, but camp_threat
// counted it as the camp's nearer target. Runtime data flag, read first; 0 = v875. Bit 1: camp_threat_other_bodies skips such a body
// (state & ST_RECALL, not completed_turn (state bit 32), sdk_champion_channel_time 0).
// v878 RTZ: RTZ recall shield + SKB stake tip
#define RTZ_BITS 1
inline constexpr int RTZ_TAB[2] = { 0x52545A31, RTZ_BITS }; // magic, bits
// b2365 SKB (RC X880 SKB1, GR:375 the killer takes my bag on top of its own, GR:29 a tribute of 1000 wins): EFB SB1's 'my death would win it
// for them' test read tributed_them + my bag only. Runtime data flag, read first; 0 = v876. Bit 1: + the largest visible foe bag within
// KILLER_R (the carrier cut's killer set), at the stake gate (assess_bars_bag_and_support) and in stake_bars.
// v878 SKB: RTZ recall shield + SKB stake tip
#define SKB_BITS 1
inline constexpr int SKB_TAB[2] = { 0x534B4231, SKB_BITS }; // magic, bits
namespace nova {
inline int skb_fb = 0; // SKB bit 1: this assessment's largest foe bag within KILLER_R (written only with the bit on)
}
// TDY (b2388, play-identical tidy bundle; RC notes docs/bot_errors.md CDL1 / CSP1 / BFD1). Runtime data flag TDY_TAB[1], read first; 0 = v876.
// Bit 1 CDL1: drop the dead `linked && !CI2_FIGHT()` terms (a linked body is always C&I, so CI2_FIGHT() holds). Bit 2: no write of the
// write-only S.cancel_pos. Bit 4 BFD1: no scan of move_fields' `nub` list (no writer since NB3 was baked).
// v879 TDY: dead CI2 linked terms, cancel_pos, nub
#define TDY_BITS 7
inline constexpr int TDY_TAB[2] = { 0x54445931, TDY_BITS };
// b2370 DSS (RC X894, IDENT fuel bundle): runtime data flag DSS_TAB[1], read first; 0 = v881. Bit 1 DLKB1: dlk_hold's danger() stops once
// the answer is decided (lock-tile scan: once d >= my eff HP; neighbour scan: once dv > the best so far; hits are >= 0, so the order of the
// sum and the picks are unchanged). Bit 2 SSM1: sidestep_tile memoises ok() / val() per tile of the 5 x 5 around me (pure within the call).
// v883 DSS: DSS deny danger early-stop + sidestep memo
#define DSS_BITS 3
inline constexpr int DSS_TAB[2] = { 0x44535331, DSS_BITS };
// b2370 ESCF (ESC1 form b, RC X894 / X877): runtime data flag ESCF_TAB[1], read first; 0 = v883. Bit 2: when the camp-threat memo is stale
// (a new round, a version bump or a mid-turn perceive: the next camp_threat call rebuilds it, measured max 4.2k), the late-turn floors that
// lead into it are raised by ESCF_TAB[3]: the end-of-turn camp escape (END_ESCAPE_FUEL), escape()'s step-away floor (ESC_AWAY_FUEL) and its
// cheap-away floors (CFL_TAB[3], both sites). (Bit 1, the kept memo, closed at 0 firing.)
#define ESCF_BITS 2
// v885 ESCF: ESCF2 price stale camp-threat rebuild into late floors
#define ESCF_PRICE 5000
inline constexpr int ESCF_TAB[4] = { 0x45534332, ESCF_BITS, 0, ESCF_PRICE };
#define ESCF_ON(b) ((ESCF_TAB[1] & (b)) != 0)

// LSD (X680 LSD1): intel::latest_sighting() ignored foe deaths, so after a kill the bank bar's quiet age, the slow-retreat 2-round
// test and QKW quiet mode read a fresh sighting. 0 = nova_base_v825. Bit 1: latest_sighting() = the latest own sighting of a living
// foe or a mate report newer than the last foe death.
// v897 LSD: LSD1 death-aware latest sighting (FPB re-read)
#define LSD_BITS 1
inline constexpr int LSD_TAB[2] = { 0x4C534431, LSD_BITS }; // slot 0 magic keeps it out of .bss
// GTM (b2402, RC X908 GTM1 + BTZ1; play-identical fuel cuts, q1bar). Runtime data flag GTM_TAB[1], read first; 0 = v893. Bit 1 GTM1:
// MapInfo keeps gate_mask (one byte per group, set at each gate_groups push_back, cleared with it) and is_gate reads it instead of a
// linear find (gi < 0 keeps the find). Bit 2 GTM2: the writers' dedup tests and ring_map_sealed read the mask too. Bit 4 BTZ1: the
// bounds-tail copies into best_group's cand use assign (no zero fill before the memcpy). Same answers and bytes; fuel only.
// v898 GTM: GTM1 gate mask + BTZ1 bounds-tail assign
#define GTM_BITS 7
inline constexpr int GTM_TAB[2] = { 0x47544D31, GTM_BITS }; // slot 0 magic keeps it out of .bss
#define GTM_ON(b) ((GTM_TAB[1] & (b)) != 0)

// b2384 LBN = the Planner's LBE, LAND BEFORE END (owner replays 01a1d507, 05hoard; prefix LBE was taken by the closed X3I/b1249 chain):
// runtime data flag LBN_TAB[1], read first; 0 = v897. Bit 1: when the foe's tributed + a known bag reaches the target (the
// egl_foe_bag_ends_game test, combat_deny.cc), a carrier of ours whose bag wins outright (tributed + bag >= WIN_TRIBUTE) banks now
// (want_bank, econ_bank_decide.cc), before the capture and bag-bar rules (Prism too: an outright win). RC C1294: no 'keep us ahead'
// clause (the first team to 1000 wins at once; FWT/GEZ own that case).
// v899 LBN: LBN bank to end the game before the foe
#define LBN_BITS 1
inline constexpr int LBN_TAB[2] = { 0x4C424E31, LBN_BITS };

// DNP (b2418; Prism Planner from the death census pfatal_tab: her deny-walk deaths .255/g v the foe Prism's .092; behaviour). Runtime
// data flag DNP_TAB[1], read first; 0 = v908. Bit 1: a Prism of ours carrying >= DNP_TAB[2] (100) gems takes no lock walk, hold,
// follow or memory walk in game_deny: she casts s0 at the channeller only from a tile outside every visible acting foe's next-turn
// reach (or one safe step into range), or when 2.5 x her Focus >= its HP + shield (a kill); mates' game_deny_mates_ahead skips her.
// Bit 2: the same with DNP_TAB[3] (300) gems (bit 1 wins when both are set).
// v910 DNP: rich Prism denies by safe cast, no lock walk
#define DNP_BITS 1
inline constexpr int DNP_TAB[4] = { 0x444E5031, DNP_BITS, 100, 300 };
// REB (b2410, RC C1244 E-PR1, bug bar): 0 = nova_base_v904. Bit 1 EPR1: write_plan's Prospector-first test (flags bit 2) counts a
// group's gem-CLUSTER gems (7 per gem cluster, capped at its gems), not its whole gem count (GR:295-297, INT:96).
// v911 REB: REB BNX SCL XCB4 (owner ship) v910
#define REB_BITS 1
inline constexpr int REB_TAB[2] = { 0x52454231, REB_BITS }; // slot 0 magic keeps it out of .bss
// XCB (b2387, RC X801 comms bug bundle; bug bar). Runtime data flag XCB_TAB[1], read first; 0 = v855. Bit 1 F1: HP2's dead-turn stop
// reads my own last FIGHT/rally call (comms::xcb_my, kept apart from fl_call, which any decoded mate post overwrites) and posts the stop
// at that call's cell, not my last live tile's (a mate's newer call in the same cell stands). Bit 2 R932: slim-4 retreat claims always
// encode (comms.cc slim4_of_full; the slim-2 width guard failed on ng 7/39/103). Bit 4 CMS1/TND1: a channel TAKEN is dated at the post
// round (a latest bound; news waits up to INTEL_NEWS_TTL), so intel_taken keeps a live respawn timer inside [at - TTL - 1, at].
// Bit 8 CK1: drop the dead ckind == 1 terms (codes 1-3 fold to idle in the slim field; mates never decode kind 1).
// v911 XCB: REB BNX SCL XCB4 (owner ship) v910
#define XCB_BITS 4
inline constexpr int XCB_TAB[2] = { 0x58434231, XCB_BITS }; // slot 0 magic keeps it out of .bss
