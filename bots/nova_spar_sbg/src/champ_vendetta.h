#pragma once
// champ_vendetta.h: this champion's rule card, passive and hooks. Shared code asks here; see champions.h for the layout. Vendetta
// (GameRules.md:618-648). Melee, HP 900 +100, Str 65 +6, Focus 100 +10. PASSIVE: a kill, camps included, resets all her cooldowns;
// usable next turn since one cast per turn still applies (interactions.md:156). Code: Kit::kill_reset through the vendetta_layer
// hooks below. Slot 0: reset. Slot 1: dash 2.
#include "common.h"
#include "world.h"

namespace nova::vendetta_layer {
// ---------------------------------------------------------------- WHO
inline bool me() { return W.me.kit && W.me.kit->kill_reset; }                      // I am Vendetta (kill reset)
inline bool kit(const Kit& k) { return k.kill_reset; }                               // this kit is Vendetta
inline bool type(cambc::champion_type t) { return t == cambc::champion_type::vendetta; } // this body is a Vendetta (combat mate_hit_focus_dash_ok, with Issac and Ren)

// ---------------------------------------------------------------- TARGETS (camps: VENDASH chains, kill refunds)
inline bool vendash(const Kit& k) { return k.kill_reset && !k.ranged; }             // econ member_stat (the chain value), tank_turn (the step to the next member)
inline bool camp_kill_reset(const Kit& k) { return k.kill_reset; }                  // combat hit_camp (re-read refunded cooldowns), econ hit_claimed_camp_in_range_slow (hit_camp)
inline bool camp_kill_refresh() { return W.me.kit && W.me.kit->kill_reset; }      // combat prestep_hit_camp: re-read refunded cooldowns after a kill

// ---------------------------------------------------------------- FIGHT
inline bool fight_kill_refresh() { return W.me.kit && W.me.kit->kill_reset; } // combat attack_champion: CCB VRK, a kill refunds her cooldowns
inline bool fight_ve_dash() { return W.me.type == cambc::champion_type::vendetta; } // combat fight_gap_dash: her dash is the cast
inline bool dash_vei(cambc::champion_type t) { return t == cambc::champion_type::vendetta; } // combat healthy_focus_dash_ok: the healthy-focus dash is hers

// ---------------------------------------------------------------- INTEL (a foe Vendetta)
inline bool intel_cd_reset(const Body& b) { return b.kit && b.kit->kill_reset; }   // world est: a Vendetta out of sight may have reset both slots
} // namespace nova::vendetta_layer
