#pragma once
// champ_willow.h: this champion's rule card, passive and hooks. Shared code asks here; see champions.h for the layout. Willow
// (GameRules.md:714-742). Ranged 3, HP 700 +50, Str 55 +3, Focus 140 +5. PASSIVE: none. Slot 0: heal another ally up to 3 x Focus,
// range 4. Slot 1: reset. The heal itself is priced from kit data in the shared models (dmg::heal_of); her positioning and heal
// choice are here.
#pragma once
#include "common.h"
#include "world.h"

// Camp hit: with no target of her partner's group in reach, she hits any awake camp an ally holds (its nearest champion is not her),
// so her Strength (55, the best ranged base) clears camps instead of idling.

namespace nova::combat {
struct Assessment;
}
// WILLOW_REGEN: our hurt bodies near our Willow regenerate as long as there are turns. Runtime data flag (code identical at 0/1).
// WR_MODE bits: 1 = no heal recall / heal walk home while our Willow is within WR_R, her heal back within WR_CD rounds (any cooldown
// at >= 50% HP) and no foe within its reach + 2: hold within 2 of her instead, at most WR_HOLD rounds without a heal; 2 = cancel a
// heal recall once her heal lifted me 25%+ above my health at the recall and above the low-HP recall line (no bag, no shop due, not
// capturing); line WR_CANCEL_X100; 4 = below 50% HP in a fight I am not winning, with her heal back within WR_CD: step back toward
// her out of foe reach; 8 = Willow positions on the most hurt mate (< 50%) within WR_R instead of her partner.
#define WR_R 6
#define WR_CD 3
#define WR_HOLD 12
// Dead-majority hold (part of bit 1): >= half the enemy bodies dead, first respawn >= WR_DM_RESP rounds away, Willow within WR_DM_R
// (any cooldown), me >= WR_DM_HOME walk from home: no heal recall; hold at her up to WR_HOLD_DM rounds.
#define WR_DM_R 8
#define WR_DM_HOME 25
#define WR_DM_RESP 10
#define WR_HOLD_DM 24
#define WR_CANCEL_X100 55 // (2): cancel line (above handle_low_hp 45 and the near heal line 50)
// WL2 (b1740): Willow's own path from the shared primitives (policy condor-work/reports/analysts/willow_policy_1108.md). Bit 1: no partner or
// follow rule, the shared target choice, fight and capture rules; her heal on cooldown by min(missing, 3 x Focus) (dies to the next hit, then
// camp fire, then champion fire, then a calm top-up); a soft target pull toward groups a working mate is on. Old Willow rules are not called.
// Bit 2: on camps, a safe attack tile in heal reach of the tank. Bit 4: off a group with attackers once a mate holds its region. Bits 8, 16,
// 32 restore the old hunt skip, backline hold (r3) and team-fight mode. Bit 64: a step to heal a mate one tile out of reach. Bit 128: the
// backline fight turn (retreat when focused, stand beside the nearest mate), no partner. Bit 256: she never starts a champion fight and
// joins one only within heal reach of a mate in contact. Bit 512: bank at WL2_BANK. Bit 1024: on camps, a safe tile within 2 of a mate.
// Bit 4096: mates near her keep the old healer engage scale. Bit 16384 (diagnostic): the old heal rules on the new path.
// Bit 32768: her capture rank: fit weight x WL2_RCY_X100 / 100 and + WL2_CAPPEN (rewards route to mates).
// Bit 65536: the mates' heal hold (WILLOW_REGEN bit 1) uses WL2_WR_R / WL2_WR_CD. Bit 131072: with her heal ready and nobody in reach,
// she steps toward a mate below half health within WL2_WR_R (it holds for her rather than recalling).
// Bit 262144 (she takes no gold): she leaves any region a mate holds, and works a cluster-only group only when a mate claims it or
// stands within 6 of it.
// Bit 524288 HLK: mates count her heal only within heal range + WL2_HLK_K. Bit 1048576 PRX: with a foe near a mate she moves into heal
// reach of that mate, behind it from the foe, and farms no farther than WL2_PRX_R from it while the trigger holds.
// Bit 2048: the shared target choice lets her join a group mates already claim (no solo-by-default rule for her).
#define WL2_BITS 35101
#define WL2_PULL_X100 50 // decision 3: target weight x100 for a group a working mate claims or stands near (0-100)
#define WL2_MIN 50       // decision 4: least missing HP for a calm heal (0-150)
#define WL2_BANK 25      // bit 512, decision 8: bank once the bag reaches this (15-30)
#define WL2_RCY_X100 0  // bit 32768: her capture-rank fit weight x100 (0-100)
#define WL2_CAPPEN 0     // bit 32768: rank points added to her capture rank (0-300; the old path's healer yield was 300)
#define WL2_WR_R 6       // bit 65536: a hurt mate holds for her heal within this distance instead of recalling (WR_R; 6, 8, 10)
#define WL2_WR_CD 3      // bit 65536: ... while her heal is back within this many rounds below 50% HP (WR_CD)
#define WL2_HLK_K 1      // bit 524288 (HLK): mates count her heal within heal range + K (live 3; 1, 2)
#define WL2_PRX_F 10     // bit 1048576 (PRX): a foe within this of a mate triggers presence (8, 10, 12)
#define WL2_PRX_T 5      // PRX: the trigger holds this many rounds
// v663 WL2: Willow raise with Marcella guard (WGLM)
#define WL2_PRX_R 4      // PRX: while it holds she stays within this of that mate (4, 5)
// HRH (b2295, RC X704 HRH1): Heart of Ruin hits harder while hurt (GR:816). Runtime data flag HRH_TAB[1], read first; 0 = v829.
// Bit 1: wl2_heal skips a calm (w 1) top-up on a Heart above HRH_TAB[2] percent of her max HP. Under camp or champion fire nothing changes.
#define HRH_BITS 0
// v840 HRH: swept v840: 0 in live and nova_b13609_fxp16z, no line flips it
#define HRH_PCT 45
inline constexpr int HRH_TAB[3] = { 0x48524831, HRH_BITS, HRH_PCT }; // slot 0 magic keeps it out of .bss
inline constexpr int WL2_TAB[13] = { 0x574C3250, WL2_BITS, WL2_PULL_X100, WL2_MIN, WL2_BANK, WL2_RCY_X100, WL2_CAPPEN, WL2_WR_R, WL2_WR_CD, WL2_HLK_K, WL2_PRX_F, WL2_PRX_T, WL2_PRX_R };
// WHL (b1810, Rule Checker Willow rows with X19). Runtime data flag WHL_TAB[1], read first; 0 = off. Bit 1 WHL1: in wl2_heal the
// WL2_MIN floor holds on the camp-fire (w 2) and champion-fire (w 1.75) branches too: a mate missing less than min(heal, WL2_MIN) is
// not worth the 8-turn heal (GR:724-726) unless the heal saves it (w 4).
// v756 WHL: RC X347 VBK1: dormant table baked at its live value 0 (owner 9 Nov bake-older rule)
#define WHL_BITS 0
inline constexpr int WHL_TAB[2] = { 0x57484C31, WHL_BITS }; // slot 0 magic keeps it out of .bss
// WCT (b1810, Rule Checker WCT1). Runtime data flag WCT_TAB[1], read first; 0 = off. Bit 1: in wl2_heal a camp tied between me and the
// mate hits whoever acts first this round (INT:101, mv::takes_tie), so a tie I take is not charged to the mate.
// v692 WCT: camp tie with me goes by turn order (WCT1)
#define WCT_BITS 1
inline constexpr int WCT_TAB[2] = { 0x57435431, WCT_BITS }; // slot 0 magic keeps it out of .bss
#define WL2_ON(b) ((WL2_TAB[1] & (b)) != 0)
// b2433 WMC (owner 13 Nov: "if willow is failing on these long maps, we just need a better willow so do not stop iterating on willow";
// VV: on FAR maps a mate is in her heal range .52 of the time v .74 for theirs). Runtime data flag WMC_TAB[1], read first; 0 = live.
// Bit 1: Willow farms only groups a living mate works (claims it, or stands within 6 of its anchor: wl2_pull's test); with no target
// she walks each turn to the mate whose spot has the most living mates within her heal range (4), ties to a hurt mate (seen < 70%),
// then the gem carrier, then the lowest slot. A mate's spot: where I see it, else its claimed group's anchor (posted claims).
// b2451 bits (each with bit 1): 2 = mates weighted 10 + 10 x seen missing-HP share; 4 = stay put while my tile covers >= best count - 1
// (>= 1); 8 = heal more than 2 turns off: groups within 6 of the mate spot also count and the walk stops within 6 of it.
// v913 WMC: Willow stays with the most mates
#define WMC_BITS 1
inline constexpr int WMC_TAB[2] = { 0x574D4331, WMC_BITS };
// WHB (b1748, spec_whb_1109): Willow held in a foe's reach by hold-back leaves instead. Bit 1: a FIGHT Willow in reach, not caught,
// focus beyond her range and hold-back true -> FLEE (combat_assess_rules.cc assess). Bit 2: Willow joins Cassi's react_kite exemption
// (combat_flee.cc): a caught Willow steps away unless her burst kills.
// v663 WHB: Willow raise with Marcella guard (WGLM)


namespace nova::support {

// Ally slot of our healer (a kit with an ally heal), or -1. Static (plan).
int healer_slot();

// Healer turn in a fight: always false (WL7: the healer follows no partner), so the generic fight runs.
bool fight_turn(const combat::Assessment& a);
// Passive Willow: the healer's heal at the start of any turn branch. True if cast.
bool heal_any();
// WILLOW_REGEN: our visible healer within maxd of me whose heal is back within maxcd rounds (nullptr: none; never me).
const Body* ready_healer_near(int maxd, int maxcd);
// WILLOW_REGEN: no foe can damage me within its reach + margin.
bool no_foe_reach_within_margin(const combat::Assessment& a, int margin);

// Engage-threshold multiplier for this body: always 1 (WL7: no support slot).
float engage_scale();
// WL2: the new path's heal (decision 4); the soft target pull (decision 3) on her own rate of group gi.
bool wl2_heal();
// b2390 WSS (same task). Runtime data flag WSS_TAB[1], read first; 0 = v904. Bit 1: in the heal-first call, when her heal is ready and no
// mate in heal reach is worth a heal (wl2_heal found none), a seen mate at heal reach + 1 .. WSS_FAR (not recalling, not on our spawn)
// missing >= 3 x her Focus (a full heal, no overheal; RC C1342) draws one step toward it (before any camp attack), then the heal rule
// runs again.
#define WSS_BITS 1
// v905 WSS: step to a mate a full heal fits
#define WSS_FAR 8
inline constexpr int WSS_TAB[3] = { 0x57535331, WSS_BITS, WSS_FAR }; // slot 0 magic keeps it out of .bss
float wl2_pull(int gi, float rate);
bool wmc_mate_group(int gi); // b2433 WMC bit 1 (caller read the flag)
bool wmc_follow();           // b2433 WMC bit 1 (caller read the flag)

} // namespace nova::support

#include "common.h"
#include "world.h"

namespace nova::willow_layer {
// ---------------------------------------------------------------- WHO
inline bool me() { return W.me.kit->slot_heal >= 0; }                        // I am the healer (the caller checked W.me.kit)
inline bool kit(const Kit& k) { return k.slot_heal >= 0; }                   // this kit heals (a mate's, or *W.me.kit)
inline bool body(const Body& b) { return b.kit && b.kit->slot_heal >= 0; }   // this body (kit known) heals
inline bool type(cambc::champion_type t) { return t == cambc::champion_type::willow; } // this body is a Willow

// ---------------------------------------------------------------- RECALL (WILLOW_REGEN: rules her hurt mates run)
inline bool regen_skip() { return me(); }               // brain hold_near_willow / flee_recall_skip_for_willow / willow_recall_cancel_ok: not hers

// ---------------------------------------------------------------- TARGETS
inline bool rank_yield(const Kit& k) { return kit(k) && !WL2_ON(1); } // econ cap_rank: +300, she never takes a reward from her partner (WL2: off)
inline bool plan_no_tank(const Kit& k) { return kit(k) && !WL2_ON(1); } // plan rank_of: never a camp tank, last on camp ties (WL2: shared order)

// ---------------------------------------------------------------- SHOP
inline bool shop_skip_pwl(const Kit& k) { return kit(k); } // econ focus_worth_less: its adjustment does not apply to her
inline bool shop_skip_grt(const Kit& k) { return kit(k); } // econ greed_tail_pass: GRT does not apply to her (with Prism and Tavi)
inline bool shop_skip_treasure(const Kit& k) { return kit(k); } // econ make_build: no Treasure (healers support)
inline bool shop_skip_tb(const Kit& k) { return kit(k); } // econ make_build: the TB_MIN_PCT balance does not apply to her
inline bool shop_skip_emb(const Kit& k) { return kit(k); }      // econ emblem window: not hers (as Prism's carry)

// ---------------------------------------------------------------- FIGHT
inline bool team_fight_self() { return me() && (false); }          // combat team_fight_mode: she is the support (a mate near to heal)
inline bool team_fight_near(const Body& al) { return body(al) && (false); } // combat team_fight_mode: a healer mate within 6
inline bool hunt_skip() { return static_cast<bool>(me()); } // combat hunt_leash_assess: no hunt for her
inline bool move_support(const Kit& k) { return kit(k) && !WL2_ON(1); } // combat support_move: her step before a heal
inline bool fight_hold_back(const Kit& k) { return static_cast<bool>(kit(k)); } // combat fight_choose_hold: r3, she stays behind her front line

// ---------------------------------------------------------------- PRISM (her place in Prism's plan)
inline bool prism_guard_skip(const Body& b) { return body(b); } // prism guard code (hidden test, guard_post, guard step): no guard
} // namespace nova::willow_layer
namespace nova::support {
// FB5 HAW1: heal_any's own first test, inline at its call sites (non-Willow turns skip the call).
inline bool heal_any_may() { return W.alive && !W.me.channeling() && W.me.kit && willow_layer::me(); }
} // namespace nova::support
