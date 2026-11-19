#pragma once
// champ_willow.h: this champion's rule card, passive and hooks. Shared code asks here; see champions.h for the layout. Willow
// (GameRules.md:714-742). Ranged 3, HP 700 +50, Str 55 +3, Focus 140 +5. PASSIVE: none. Slot 0: heal another ally up to 3 x Focus,
// range 4. Slot 1: reset. The heal itself is priced from kit data in the shared models (dmg::heal_of); her positioning and heal
// choice are here.
#pragma once
#include "common.h"
#include "world.h"

// Tuning switches (test builds override them): fight-bias factor on the engage threshold near our healer, and whether the partner's
// crew estimates count the healer's heal and damage. OPENING: Willow must not idle at base.
#define WILLOW_ENGAGE 0.65f
// The share of a full heal an ally above 50% must be missing for a top-up (calm, or Heart of Ruin).
#define WILLOW_TOPUP_MIN 0.9f
#define WF_CAMP 8
#define WF_ENEMY_R 10
#define WF_QUIET 5
#define WF_ALLY_R 4
#define WF_ALLY_PCT 60
#define WF_FROM 30
// Mode 2: she farms while a mate is within WF_ALLY_R, or (alone) while no enemy was seen within WF2_ENEMY_R for WF_QUIET rounds;
// never while an ally within WF_ALLY_R is below WF_ALLY_PCT (60 or 75). fight_turn keeps the backline fight in stance FIGHT.
#define WF2_ENEMY_R 8
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
#define WILLOW_REGEN 1
#define WR_MODE 3
inline constexpr int WILLOW_REGEN_TAB[3] = { 0x57524547, WILLOW_REGEN, WR_MODE }; // slot 0 magic keeps it out of .bss
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


namespace nova::support {

// Ally slot of our healer (a kit with an ally heal), or -1. Static (plan).
int healer_slot();
// The healer's partner: the first living ally in the partner order (Heart of Ruin, Prism, then the best camp
// tanks). Same answer on every body (allies' liveness is always known). -1 when none.
int partner_slot();
// Slot of the healer while it follows a partner (alive, partner alive), else -1. Crews and captures skip it.
int support_slot();
// This body is the healer and follows a partner.
bool me_active();

// Healer turn outside fights: a backline spot near the partner, heals, attacks on what the partner fights. Publishes
// the partner's claim. True if the turn is used.
bool turn(const combat::Assessment& a);
// Healer turn in a fight (stance FIGHT): retreat first when focused, heal, a backline spot within heal range of the partner and
// attack range of the focus, walk + reset + attack. False: use the generic fight.
bool fight_turn(const combat::Assessment& a);
// The healer's heal: the ally about to die, the tank holding camps, the ally in a fight; never a full ally, and held
// while no damage is coming unless it heals in full. True if cast.
bool heal();
// Passive Willow: the healer's heal at the start of any turn branch. True if cast.
bool heal_any();
// WILLOW_REGEN: our visible healer within maxd of me whose heal is back within maxcd rounds (nullptr: none; never me).
const Body* ready_healer_near(int maxd, int maxcd);
// WILLOW_REGEN: no foe can damage me within its reach + margin.
bool no_foe_reach_within_margin(const combat::Assessment& a, int margin);

// Engage-threshold multiplier for this body: below 1 when our healer fights with us (her heal and damage tilt fights).
float engage_scale();
// Healing the partner can count on in the next few rounds (its healer close by), for camp bail-out checks.
// Capture-rank penalty: the healer never captures while another body can.
int cap_penalty(int slot);

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
inline bool rank_yield(const Kit& k) { return kit(k); } // econ cap_rank: +300, she never takes a reward from her partner
inline bool plan_no_tank(const Kit& k) { return kit(k); } // plan rank_of: never a camp tank, last on camp ties

// ---------------------------------------------------------------- SHOP
inline bool shop_skip_pwl(const Kit& k) { return kit(k); } // econ focus_worth_less: its adjustment does not apply to her
inline bool shop_skip_grt(const Kit& k) { return kit(k); } // econ greed_tail_pass: GRT does not apply to her (with Prism and Tavi)
inline bool shop_focus_stat(const Kit& k) { return kit(k); } // econ make_build: her stat is Focus (unless RWS bit 1)
inline bool shop_skip_treasure(const Kit& k) { return kit(k); } // econ make_build: no Treasure (healers support)
inline bool shop_skip_tb(const Kit& k) { return kit(k); } // econ make_build: the TB_MIN_PCT balance does not apply to her
inline bool shop_skip_emb(const Kit& k) { return kit(k); }      // econ emblem window: not hers (as Prism's carry)

// ---------------------------------------------------------------- FIGHT
inline bool team_fight_self() { return me(); }          // combat team_fight_mode: she is the support (a mate near to heal)
inline bool team_fight_near(const Body& al) { return body(al); } // combat team_fight_mode: a healer mate within 6
inline bool hunt_skip() { return me(); } // combat hunt_leash_assess: no hunt for her
inline bool move_support(const Kit& k) { return kit(k); } // combat support_move: her step before a heal
inline bool fight_hold_back(const Kit& k) { return kit(k); } // combat fight_choose_hold: r3, she stays behind her front line

// ---------------------------------------------------------------- PRISM (her place in Prism's plan)
inline bool prism_guard_skip(const Body& b) { return body(b); } // prism guard code (hidden test, guard_post, guard step): no guard
} // namespace nova::willow_layer
