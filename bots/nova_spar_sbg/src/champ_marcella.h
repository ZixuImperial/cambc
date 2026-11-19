#pragma once
// champ_marcella.h: this champion's rule card, passive and hooks. Shared code asks here; see champions.h for the layout. Marcella
// (GameRules.md:650-680). Melee, HP 1200 +100, Str 40 +3.5, Focus 60 +10. PASSIVE: immune to stuns (Kit::stun_immune); +2 gold per
// gem she tributes (marcella_layer::tribute_gold; gold bonuses apply, interactions.md:87). Slot 0: reset; the next hit stuns one
// round, and the reset needs an attack first (interactions.md:154). Slot 1: 2 x Focus, range 4, excludes walking.
#include "common.h"
#include "world.h"

namespace nova::marcella_layer {
// PASSIVE: gold she earns tributing this many gems (GameRules.md:658)
inline float tribute_gold(float gems) { return 2.0f * gems; }
// ---------------------------------------------------------------- WHO
inline bool me() { return W.me.kit && W.me.kit->stun_immune; }                     // I am Marcella (stun immunity)
inline bool kit(const Kit& k) { return k.stun_immune; }                              // this kit is Marcella
inline bool type(cambc::champion_type t) { return t == cambc::champion_type::marcella; } // this body is a Marcella
inline bool body(const Body& b) { return b.kit && b.kit->stun_immune; }              // this body (known kit) is a Marcella

// ---------------------------------------------------------------- BANK (her channel)
inline bool chan_stun_proof() { return W.me.kit && W.me.kit->stun_immune; } // combat channel_safe_check, prism tribute_start_allowed: a stun cannot cancel my channel
// econ crystal_step: a stun does not stop my crystal either, so its ready-stun bar does not apply to me (chan_stun_proof).

// ---------------------------------------------------------------- TARGETS (her gem gold)
inline bool gem_gold(cambc::champion_type t) { return t == cambc::champion_type::marcella; } // econ group_value, gbr ma_gems, planner capture_rank_fit / stack_rank_bonus: +2 gold per gem she tributes
inline bool plan_gem_carrier(cambc::champion_type t) { return t == cambc::champion_type::marcella; } // plan plan_carriers: she carries the gems when no Prism does

// ---------------------------------------------------------------- SHOP
inline bool shop_capture_item() { return W.me.type == cambc::champion_type::marcella; } // econ upitm_post: the capture item goes forward (as bonus-gold kits)

// ---------------------------------------------------------------- FIGHT (stuns by and on her)
inline bool fight_irb_imm() { return W.me.kit && W.me.kit->stun_immune; }          // combat reach_burst_test: the foes' stuns do not count on me
inline bool fight_stun_wasted(const Body& b) { return b.kit && b.kit->stun_immune; } // every stun choice (combat, econ): a stun does nothing on her
inline bool fight_stun_holds(const Body& b) { return b.kit && !b.kit->stun_immune; } // every stun choice: a known kit my stun holds (not her)
} // namespace nova::marcella_layer
