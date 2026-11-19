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

// FXDR: draft fuel cuts. Runtime data flag, read first; 0 = full draft work, byte for byte. Every bit gives the same picks and the
// same draft-memory bytes: 1 XT: travel_build_step reads each walk group's approach tiles through precomputed field offsets (same minimum). 2
// LATER: later draft turns reuse prism::write_plan / om_write bytes and map_class_compute's value (all static once M.done()). 4 (unused)
// ZONE: skipping the dead zone::draft_step would change the image size PACK stores (1024 vs 768 bytes where a zone exists), so the
// memory bytes would differ. 8 ENUM: enumerate_all caches set_terms per lineup across re-enumerations (keyed on everything set_terms
// reads). 16 DM3: draft_launch_scan reads the launch pairs through precomputed field offsets. 32 MCL2: compute_map_class_bits's 7x7 camp window scans
// row camp masks (same union order). 64 FC: travel_build_step keeps its fields of DM3's top groups (same walls, same roots); draft_launch_scan reads
// them instead of recomputing. 128 DSC: draft_swap_cell_code's map totals (gems, gold, clusters, heavy gems, wall and hole tiles) computed once,
// tiles by masked popcount. 256 PLAN: make_plan lists the admissible lineups once (index order) and runs passes 2 and 3 over that
// list only.
#define FXDR_BITS 507
inline constexpr int FXDR_TAB[2] = { 0x46584452, FXDR_BITS }; // FXDR: draft fuel cuts (same picks)

// CDW: one flag word, runtime data flag, 0 = off. A dasher's skip over a thin hole (walk to a launch tile, one 2-tile dash over the
// hole (Q42 middle rules), walk on) beats the walk around. Static part: the thin-hole launch pairs, built once per body; per use:
// the host BFS from me, the cooldown, the live middle test. Bit 1 SC: spawn_crystal_start does not buy the crystal when that skip
// arrives no later than the hop (and the walk then takes the skip). Bit 2 TRAVEL: every step_field walk takes such a skip when it
// saves HOLE_SHORT_GAIN rounds (walk-then-dash; dash-then-walk is travel_dash's). Bit 4 MH: mid_hop_try (a carried crystal's
// mid-route hop) does not hop when that skip arrives no later than the hop, and the walk on that field then takes the skip. Bits
// work on their own and together.
#define CDW_BITS 7
inline constexpr int CDW_TAB[2] = { 0x43445731, CDW_BITS }; // CDW: dashers skip thin holes instead of buying a crystal
constexpr int CDW_BIT_SC = 1, CDW_BIT_TRAVEL = 2, CDW_BIT_MH = 4;
#define CDW_CNT(k, c) ((void)0) // CDW fire count: the diag copy records site k when c; release: nothing, c unevaluated

// Crew-pooled bail: one flag word, runtime data flag, 0 = off. Bit 1 POOL: the crew bail's "leaves before the kill" is a mate below
// its own bail line (not one that can't take every remaining hit alone), and a body skips its own camp bail while the crew's pooled
// holding rounds (each hitter down to its own bail line) cover the kill and I take no hits now (a mate is nearer to each attacker)
// or can step out next turn.
#define CREW_BAIL_POOL_BITS 1
inline constexpr int CREW_BAIL_POOL_TAB[2] = { 0x43425832, CREW_BAIL_POOL_BITS }; // slot 0 magic keeps it out of .bss
constexpr int CREW_BAIL_POOL_BIT_POOL = 1;
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
#define CODE_ERR_FIX_BITS 39
#define CODE_ERR_FIX_FRB_D 3
inline constexpr int CODE_ERR_FIX_TAB[3] = { 0x42313476, CODE_ERR_FIX_BITS, CODE_ERR_FIX_FRB_D }; // bank when a recall's bag turns winning, plus the other verified fixes in this table
constexpr int CODE_ERR_FIX_BIT_WBR2 = 1, CODE_ERR_FIX_BIT_CVH = 2, CODE_ERR_FIX_BIT_HFP = 4, CODE_ERR_FIX_BIT_FRBA = 16, CODE_ERR_FIX_BIT_FRBB = 32;
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

// Team combat fixes. Runtime data flag slot 1, read first; 0 = off. 1 FLD: fight_layer_turn's FL2 lead rule defers to a visible
// lower-slot mate within 6 only if it is not channelling, has a foe I see within 6 of it and (claims v2 on) last published an
// in-fight or engaged claim. Without the bit, a channelling mate or one with no foe within 6 also counts, though its
// fight_layer_turn returns before posting, so no FIGHT/HELP call goes out. 2 HGD: a HELP post the TM2 channel dropped (no free
// entry) restores the local image and is not counted as posted; otherwise it kept its image and help_last_post, so help_post and
// fight_layer_turn believed it out and did not re-post for about 4 rounds. 4 SKF: squad::begin_turn counts a mate's return from an
// FL1 fight claim (no group) to the SAME group as keeping the round of the real change; otherwise the squad-stick rule followed it
// as 'just claimed'.
#define TEAM_HELP_FIX_BITS 2

// Heal and assess fixes: runtime data flag, flag read first, zero work at 0. 1 GHA: assess's FL3a read of a HELP image uses
// comms::event_age_rounds (as every ghost-image reader does); otherwise the 5-bit stamp's age alone makes an image kept past 32
// rounds read as fresh. 2 THS: try_heal skips a mate on our spawn; the spawn fills it at its turn end (interactions Q43),
// support::heal skips it. 4 THG: try_heal reads the host's gem count when al.gems reads 0 (al.gems is read only near a foe). 8 WCK:
// support::incoming_on and camp_hazard take camp Strength x Durability x Jungle for mates (GameRules.md:307-309), as for my own
// body, not raw Strength against HP. 16 HVS: after my step W.allies is still perceive's; a mate my new tile can't see refuses the
// heal (rc 30), so heal and try_heal skip it. 32 TKW: intel_taken keeps a live timer inside [at - NEWS_TTL - 1, at]: TM2 bit 16
// carries only the post's parity and news waits up to NEWS_TTL for the slot, so `at` is a latest bound and must not overwrite the
// timer a body held.
#define HEAL_ASSESS_FIX_BITS 0
inline constexpr int HEAL_ASSESS_FIX_TAB[2] = { 0x42483738, HEAL_ASSESS_FIX_BITS }; // slot 0 magic keeps it out of .bss
constexpr int HEAL_ASSESS_FIX_BIT_GHA = 1, HEAL_ASSESS_FIX_BIT_THS = 2, HEAL_ASSESS_FIX_BIT_THG = 4, HEAL_ASSESS_FIX_BIT_WCK = 8, HEAL_ASSESS_FIX_BIT_HVS = 16, HEAL_ASSESS_FIX_BIT_TKW = 32;
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
#define KIT_RULE_FIX_BITS 2047
inline constexpr int KIT_RULE_FIX_TAB[2] = { 0x52463232, KIT_RULE_FIX_BITS }; // Flag table for the rule-constant fixes, read through the rs:: helpers.
#define KIT_RULE_FIX_CNT(k, c) ((void)0) // Fire count: the diagnostic copy records site k when c holds (new answer != old); release builds do nothing and do not evaluate c.

// VSP: Varg splash on camps (the models would count 2-3x the bodies a splash hits). Runtime data flag VSP_TAB[1], read first; 0 =
// off. Bit 1 CAMP (cautious): kit_dps, kit_dps_pack1_and_3's pack-3 basic and spawn_siege_kill_dps take varg_layer::camp_splash_extra(pack) extra bodies a
// basic (measured 0.26 x (pack - 1)) instead of 0.7 x (pack - 1) / x2.4 at pack 3 / min(2, pack - 1); Crew::dps / dpsf, the clear
// estimates, the threat bail, zone dps and the RCG rally read them. Bit 2 ONE (GameRules: the splash hits the target's neighbours,
// never the target): horizon_dps1, damage on ONE body, counts splash, area and landing once (horizon_fit's DPS_AREA_HITS 1.3 only
// for strength calls; DFX bit 8's rule on the fit). Varg splash bodies are measured; area stuns cover all.
#define VSP_BITS 3
inline constexpr int VSP_TAB[2] = { 0x56535031, VSP_BITS }; // Flag table for the Varg splash fixes.
constexpr int VSP_BIT_CAMP = 1, VSP_BIT_ONE = 2;
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
#define FCS_BITS 0
inline constexpr int FCS_TAB[2] = { 0x46435331, FCS_BITS }; // slot 0 magic keeps it out of .bss
constexpr int FCS_BIT_SIMX = 1, FCS_BIT_TOPS = 2, FCS_BIT_TOPV = 4, FCS_BIT_RESTS = 8, FCS_BIT_RESTV = 16, FCS_BIT_LBSUM = 32;
constexpr int FXDR_BIT_XT = 1;
constexpr int FXDR_BIT_LATER = 2;
constexpr int FXDR_BIT_ENUM = 8;
constexpr int FXDR_BIT_DM3 = 16;
constexpr int FXDR_BIT_MCL2 = 32;
constexpr int FXDR_BIT_FC = 64;
constexpr int FXDR_BIT_DSC = 128;
constexpr int FXDR_BIT_PLAN = 256;
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
#define B467_BANKB 15 // Base of the want_bank bag bar.
#define B467_BANKS_X100 (static_cast<int>(ES_TAB[13])) // Slot 13 of the economy table: slope of the want_bank bag bar per altar tile, x100.
#define B467_BANKTH_X100 (static_cast<int>(ES_TAB[12])) // ES slot 12: want_bank bar factor under threat x100
#define B467_GOLDW_X100 50 // gold_weight_in_gems early cap x100
#define PS_SHOPMIN 120 // want_shop: non-eager minimum gold
#define PS_LOWREC 86 // HP fraction x100 below which a body recalls.
#define PS_ENGAGE 115 // assess: base engage bar x100
#define PS_FLEE 53 // assess: base flee bar x100
#define PS_SYM 66 // Assess: discount x100 on a foe's power when none of us is within 3.
#define PS_PEEL 88 // PEEL_MIN x100
#define PS_CAUGHT 168 // CAUGHT_MIN x100
#define PS_INREACH 72 // assess: in-reach fight bar x100

// Constants in one volatile data table, so a search variant differs only in data bytes. Magic words at both ends keep it out of .bss
// and findable in the wasm.
#define PS_HPRIZE 15 // hunt_prize weight x100 in team_focus (0.15f)
#define PS_HDBAG 60 // hunt_leash_assess leash bag limit
#define PS_HDFR 40 // hunt_leash_assess leash HP line x100 (0.4f)
#define PS_HDRACE 90 // hunt_leash_assess race margin x100 (1.1f; lock = this + 30)
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
#define ES_BANKS 66   // slot 13: want_bank bar slope per altar tile x100
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
#define RULE_AUDIT_FIX_BITS 31
inline constexpr int RULE_AUDIT_FIX_TAB[2] = { 0x41553231, RULE_AUDIT_FIX_BITS }; // Flag table for the rule audit fixes.
constexpr int RULE_AUDIT_FIX_BIT_DMID = 1, RULE_AUDIT_FIX_BIT_EBK = 2, RULE_AUDIT_FIX_BIT_PROSP = 4, RULE_AUDIT_FIX_BIT_BLF = 8, RULE_AUDIT_FIX_BIT_RFE = 16;
#define RULE_AUDIT_FIX_CNT(k, c) ((void)0) // Fire count: the diagnostic copy records site k when c holds; release builds do nothing and do not evaluate c.

// Altar lock fixes: runtime flag, 0 = off (no work); bits: 1 LKB (hit_champion_before_lock_slow, CTX bit 1 LKC): the enemy lock on
// an altar in range is read with econ::enemy_lock_on (the direct enemy read), since altar_lock_at(...).is_enemy() returns OUR lock
// when both teams' locks stand (one lock per team per altar, Q41); otherwise LKC misses the foe lock and lock_hit (it reads the lock
// directly under bit 1) spends the attack on it. 2 SPLIT (capture_recall): my share of the capture's gems uses rs::split_share (win
// test, bag tests, bank bag): g.gems / sharing floors, and the lowest champion ID among the receivers takes the remainder
// (GameRules:207).
#define ALTAR_LOCK_SPLIT_BITS 3
inline constexpr int ALTAR_LOCK_SPLIT_TAB[2] = { 0x42483636, ALTAR_LOCK_SPLIT_BITS }; // Flag table for the altar lock fixes.
constexpr int ALTAR_LOCK_SPLIT_BIT_LKB = 1, ALTAR_LOCK_SPLIT_BIT_SPLIT = 2;
#define ALTAR_LOCK_SPLIT_CNT(k, c) ((void)0) // Fire count: the diagnostic copy records site k when c holds (new answer != old); release builds do nothing and do not evaluate c.

// WBG: perceive reads a foe's bag only within 9 of me in my own sight, so intel's note() would overwrite the remembered bag
// (team_bodies) with 0 on every ward-only or far sighting. Runtime data flag WBG_TAB[1] (0 = off, zero work): bit 1 = note() reads
// such a sighting's bag itself (sdk_champion_gems works on anything in vision) into the team copy only, keeping the last known bag
// if the read fails; bit 2 = a foe's remembered bag drops to 0 when it dies (the killer takes it), not at its first sighting after
// the respawn.
#define WBG_BITS 3
inline constexpr int WBG_TAB[2] = { 0x57424731, WBG_BITS }; // WBG: a far or ward-only sighting reads the foe's bag
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
#define SG_K 3 // SG3: bodies (healer not counted) that must be free to come for a call, and present for the start
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
#define CCE_BITS 3
#define CCE_GEMS 80
#define CCE_T0 600 // no game-ending group below this many tributed (fuel early-out)
#define CCE_FOE 3
inline constexpr int CCE_TAB[2] = { 0x43434531, CCE_BITS }; // slot 0 magic keeps it out of .bss

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
