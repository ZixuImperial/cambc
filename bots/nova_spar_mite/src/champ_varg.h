#pragma once
// champ_varg.h: this champion's rule card, passive and hooks. Shared code asks here; see champions.h for the layout. Varg
// (GameRules.md:776-806). Melee, HP 1000 +100, Str 50 +5, Focus 100 +10. PASSIVE: splash, Strength to every other enemy and camp
// within radius 1 of the basic attack's target; the target is not hit twice; carries his modifiers (interactions.md:81). Code:
// varg_layer::camp_splash_extra, burst::splash_through_mate and prestep_splash_ok (champ_varg.cc). Slot 0: reset. Slot 1: self-shield
// 2.5 x Focus, five turns.
#include "common.h"
#include "world.h"

namespace nova::combat::burst {
float splash_through_mate(const Body& e, vec2 t, int cdh); // defined in champ_varg.cc
}

// ---------------------------------------------------------------- flags VARG_NOWAKE: Varg's BASIC-attack splash wakes dangerous
// groups too: a splash attacker's champion hit whose radius-1 splash covers a camp of a sleeping group wakes_other_group() vetoes goes to
// another foe in reach whose splash is clean (lowest effective HP), else is skipped unless the hit kills a foe in the square (the
// caller then steps or holds). Runtime data flag (VARG_NOWAKE_TAB[1]): the off copy has the same code bytes.
#define PASSIVE_VARG_NBR 1000.0f // PASSIVE Varg: focus score credit per living same-group neighbour (camp HP units)

namespace nova::varg_layer {
// ---------------------------------------------------------------- WHO
inline bool me() { return W.me.kit && W.me.kit->splash; }                          // I am Varg (splash)
inline bool kit(const Kit& k) { return k.splash; }                                   // this kit is Varg
inline bool type(cambc::champion_type t) { return t == cambc::champion_type::varg; } // this body is a Varg

// ---------------------------------------------------------------- TARGETS (camps)
inline bool route_skip_rtg() { return W.me.kit && W.me.kit->splash; }     // combat next_camp_after_kill: no next-camp pick (a splash may wake a neighbour)
inline bool reset_splash_aim() { return W.me.kit && W.me.kit->splash; }   // combat next_camp_in_reach: the reset's second hit goes where the splash reaches most
inline bool prestep_splash() { return W.me.kit->splash; }                  // combat prestep_hit_before_move_slow: the pre-step hit must pass prestep_splash_ok
inline bool focus_splash() { return W.me.kit && W.me.kit->splash; } // econ pick_focus_fast: PASSIVE_VARG_NBR, the focus with living neighbours
inline bool paw_splash() { return W.me.kit->splash; } // econ hit_claimed_camp_in_range_slow: PAW's free awake-camp hit does not apply to him

// ---------------------------------------------------------------- SHOP
inline bool shop_str(const Kit& k) { return k.splash; }                      // econ make_build: his Str counts x1.5 (splash)

// ---------------------------------------------------------------- FIGHT
inline bool fight_nowake() { return W.me.kit && W.me.kit->splash; } // combat attack_champion: VARG_NOWAKE, the splash wakes no dangerous group

// ---------------------------------------------------------------- CLEAR ESTIMATES (VSP bit 1) Extra camp bodies one basic's splash
// hits, by the group's pack (most camps in one 3x3). Measured on our Varg's camp basics (27.8k basics): pack 2 .36, 3 .53, 4 .77,
// about 0.26 x (pack - 1). Attackers die and the target sits on an edge, so 0.7 x (pack - 1) or min(2, pack - 1) would be 2-3x high.
// Linear, so the crews' dps1-dps3 line (Crew::dps / dpsf) stays exact; pack is capped at 4 as in kit_dps (larger packs unmeasured).
inline constexpr float VSP_CAMP_SPLASH_PER_BODY = 0.26f;
inline float camp_splash_extra(float pack) { return VSP_CAMP_SPLASH_PER_BODY * (std::clamp(pack, 1.0f, 4.0f) - 1.0f); }
} // namespace nova::varg_layer

// ---------------------------------------------------------------- how much Varg's splash reaches at a group (VSR) VSP bit 1 CAMP
// prices the Varg splash in spawn_siege_kill_dps (the spawn-siege rate gate, econ_*.cc spawn_siege_commit_ok) at .26 x (pack - 1) instead of min(2, pack -
// 1). VSR scopes the pricing to that one place; VSP's pricing stays everywhere else. Flag VSR_BITS, 0 = off. Bit 1 RCG: spawn_siege_kill_dps
// takes min(2, pack - 1) bodies. Bit 4 GEOM (rule 40_champions.md:109: the splash hits every other camp within radius 1 of the
// target): spawn_siege_kill_dps takes, per group, the mean over its camps of the other camps of the group within Chebyshev 1 (once per group;
// wins over bit 1).
#include "mapinfo.h"
namespace nova::econ::splash_geometry
{
float adjacent_camp_mean(const GroupI& g); // bit 4: the mean other-camps-within-1 of g's members (cached by group index)
}
