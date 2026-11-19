#pragma once
// champ_ryth.h: this champion's rule card, passive and hooks. Shared code asks here; see champions.h for the layout. Ryth
// (GameRules.md:492-522). Melee, HP 1200 +100, Str 45 +4.5, Focus 100 +10. PASSIVE: Strength = 1% of bonus health. The engine
// applies it to her Strength stat; ryth_layer::str_from_health tells the shop and shard counts to value Health as her Strength. Slot
// 0: area stun, 1 x Focus, radius 1, range 4, excludes walking. Slot 1: reset.
#include "common.h"
#include "world.h"

namespace nova {
} // namespace nova

namespace nova::ryth_layer {
inline constexpr float RYTH_START_NEAR = 1.0f; // a Ryth body starts a fight only at this near balance
// ---------------------------------------------------------------- WHO
inline bool me() { return W.me.type == cambc::champion_type::ryth; }           // I am Ryth
inline bool kit(const Kit& k) { return k.health_strength; }        // this kit is Ryth's
// ---------------------------------------------------------------- FIGHT
inline bool fight_calm_start() { return me(); } // combat assess: she starts a fight only at RYTH_START_NEAR, else CALM
// ---------------------------------------------------------------- SHOP
inline bool str_from_health(const Kit& k) { return k.health_strength; } // econ shards_of: her Strength is her Health, not Strength shards
// econ crew soak (area bit 2): her slot 0 area stun cancels one hit of every camp within radius 1 of its centre.
inline float camp_area_stuns(const Kit& k) { return k.aoe_stun ? 1.0f : 0.0f; }
inline bool shop_health_families(const Kit& k) { return k.health_strength; } // econ make_build: her passive families take Health
inline bool shop_tail_hhs(const Kit& k) { return k.health_strength; } // econ make_build: her tail is Health, Health, Strength
} // namespace nova::ryth_layer

// ---------------------------------------------------------------- DRAFT (draft_*.cc set_values) Ryth is drafted down by DRAFT_RY_PP
// points.
#define DRAFT_RY_PP 4.0f
