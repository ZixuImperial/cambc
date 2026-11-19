#pragma once
// champ_ren.h: this champion's rule card, passive and hooks. Shared code asks here; see champions.h for the layout. Ren
// (GameRules.md:744-774). Melee, HP 900 +100, Str 35 +5, Focus 100 +9. PASSIVE: retaliation, 0.2 x Focus on each direct hit, also
// while stunned and as he dies, never from splash (interactions.md:158). Code: ren_layer::retaliation_damage, ren_ret_on and
// ren_retaliation_of_cast (champ_ren.cc). Slot 0: 1.1 x Focus and a one-round stun, range 4, excludes walking. Slot 1: dash 2.
#include "common.h"
#include "world.h"

namespace nova::ren_layer {
// PASSIVE (GameRules.md:752): before multipliers
inline float retaliation_damage(float foc) { return 0.2f * foc; }
} // namespace nova::ren_layer

namespace nova::combat {
float ren_ret_on(const Body& e); // defined in champ_ren.cc
namespace {
float eff_hp(const Body& b); // the combat sources (unity build: one translation unit)
} // namespace
} // namespace nova::combat

namespace nova::ren_layer {
// ---------------------------------------------------------------- WHO
inline bool kit(const Kit& k) { return k.retaliation; }                     // this kit retaliates (Ren)
inline bool body(const Body& b) { return b.kit && b.kit->retaliation; }     // this body (kit known) retaliates
inline bool type(cambc::champion_type t) { return t == cambc::champion_type::ren; } // this body is a Ren

// ---------------------------------------------------------------- FIGHT (about a foe Ren) Foe e's retaliation for one hit of mine
// takes my effective HP: the hit is refused (the 12 combat guards, ren_kills_me).
__attribute__((always_inline)) inline bool kills_me(const Body& e) { return e.kit && e.kit->retaliation && combat::ren_ret_on(e) >= combat::eff_hp(W.me); }
// ... two retaliations do (the reset's second hit: combat CCB bit 1).
__attribute__((always_inline)) inline bool kills_me_twice(const Body& e) { return e.kit && e.kit->retaliation && 2.0f * combat::ren_ret_on(e) >= combat::eff_hp(W.me); }
} // namespace nova::ren_layer
