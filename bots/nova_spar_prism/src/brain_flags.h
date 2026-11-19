#pragma once
// brain_flags.h: turn flags and tunables.

// Tie-break seek (runtime data flag; 0 = trunk). GameRules.md:27: r2000 compares tributed gems, gold earned, kills,
// then Team B wins. A kill pays gold, so on a 0-0-0 game one kill decides it. TSK_BITS bit 1: as Team A with nothing to do (no gems,
// no gold, nothing tributed by either team, no target for TSK_WAIT turns), walk at the enemy spawn: a loss is the tie-break's result
// anyway. Bit 2: Team B too (it loses more often than it wins in tests, leave off).
#define TSK_BITS 1
#define TSK_WAIT 60
inline constexpr int TSK_TAB[3] = { 0x54534B31, TSK_BITS, TSK_WAIT };

// A body whose move is still unused at the end of the turn it finished its target group steps onto a free spawn tile of that group,
// so the capture clock starts one round earlier (GameRules:122, :194; capture() itself runs only next turn). Bit 1: when I am the
// capturer (should_capture). Bit 2: also when a mate outranks me. Runtime data flag KS_TAB[1] (0 = trunk). Called from spin_on_turn_end, the
// last call of the turn, so no later spell in the turn is excluded by the walk.
#define KS_ON true

// Bank step: a carrier whose bank walk ends in submit range starts the tribute in the same turn, so the channel ticks on the arrival
// turn and completes a round earlier (GameRules:116, :273). Bit 1: every walk made inside bank(). bank_step_turn re-runs bank()'s
// start gates on the new tile. Runtime data flag BS_TAB[1] (0 = trunk), called from spin_on_turn_end.
#define BS_ON true

#define HSL_OK(c)

// RGB (rgb): brain and movement bugs. 0 = nova_b9968_rgf3r. Bits (kept after the firing read): 1 = a re-perceive keeps a foe recall verdict, 4 = move mask invalidated after a mid-turn perceive, 8 = tm2 coming set only on a taken step, 16 = walk_cast_end uses the real round.
// v630 RGB: recall re-perceive, move mask, coming, round
// TDC (tdc_rulecheck_1110, Rule Checker tribute-channel audit; b1781): runtime data flag TDC_TAB[1], read first; 0 = off. Non-Prism
// carriers only (owner rule: her keep/cancel is untouched). Bit 1: the low-HP cancel spares a winning channel too (td_win guarded
// only the rate branch). Bit 2: either cancel branch needs damage within my last 2 rounds (took_damage(2)), so a cancel is never
// followed by a same-turn restart from full ticks (new_tribute_blocked's hold reads took_damage(2)). Bit 4 (cap2_rulecheck_1110 bit 2):
// the channel-ender note (wsi_ec_h, econ_tribute_gates.cc) keeps up to 12 foes, not 4, so the restart hold sees every one.
// v685 TDC: 19 fixes phy1r2,npb1,orc1,wvc,cia3s,jgw31,x02,idm +11
#define TDC_BITS 7
inline constexpr int TDC_TAB[2] = { 0x54444331, TDC_BITS };
// FGD (b1809, Rule Checker X73 turn-pipeline fuel guards). Runtime data flag, read first; 0 = v693. Bit 1 SSF: spawn_siege_find_groups
// (~45k fuel) runs in early_stages only with fuel() > FGD_SSF left (ss_pending keeps it for a later turn), so the tribute, flee and move
// stages after it keep their fuel (rules-gaps:108). Bit 2 BGO: the SRB background map resume keeps ANALYSE_KEEP (24k) instead of 8k,
// so ks_turn, bank_step_turn and the spin recall after background_work still run (bot_errors:1965).
#define FGD_BITS 1
// v695 FGD: 9 fixes fbbw3,tcs,x66j,bhw1,x65c,fgd1,pbq8,qmd1,xgv1
#define FGD_SSF 60000
inline constexpr int FGD_TAB[2] = { 0x46474431, FGD_BITS }; // slot 0 magic keeps it out of .bss
// TDE (b2145, RC X555 TDE1, C553, INT:120): tribute_doomed keeps a channel (any kit) that lands by GAME_END when no restart (next round
// + full ticks) can. 0 = live. Bit 1: on.
#define TDE_BITS 1
// v803 TDE: end-game r2000 landing tests TDE1 DDL1 BFE1
#define TDE_END 2000 // the last round (GameRules; econ::GAME_END is not in scope here)
inline constexpr int TDE_TAB[2] = { 0x54444531, TDE_BITS }; // slot 0 magic keeps it out of .bss
// TTE (b2150, RC X564/X567 TTE1 = TSM1 corrected; bot_errors row 721): runtime data flag TTE_TAB[1], read first; 0 = v801.
// Bit 1 TTE1: tie seek (team A at 0-0 tributed) also stops once the TEAM is known to have earned gold (GR:29, GR:35): a sticky test,
// true once a 1-bit team spare field reads 1 (each team-A body writes it once when it first holds gold) or a visible mate holds gold
// or any shop item (bought with gold). Read only where the seek would start (idle wait passed), so other turns are unchanged.
// Bit 4 TTE2: WB2_LATE's score-lead bank refuses only when us + gems < them (an exact tie goes to the gold tiebreak, not a sure loss).
// v807 TTE: TTE tie-seek uses team-earned gold; bank to level
#define TTE_BITS 5
inline constexpr int TTE_TAB[2] = { 0x54544531, TTE_BITS }; // slot 0 magic keeps it out of .bss
// SBB (b2193, BB8 STALE-OPEN rows, docs/bot_errors.md): one runtime data flag per verified bug, read first; 0 = v820.
// CTHP row 507: the contest hit takes the lowest eff_hp foe in reach, never an unkillable foe on its spawn (GR:153).
// v822 CTHP: stale rows 462/506/507/541/643 (SBB)
#define CTHP_BITS 1
inline constexpr int CTHP_TAB[2] = { 0x43544850, CTHP_BITS }; // slot 0 magic keeps it out of .bss
