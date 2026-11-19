#pragma once
// champ_heart.h: this champion's rule card, passive and hooks. Shared code asks here; see champions.h for the layout. Heart of Ruin
// (GameRules.md:808-836). Melee, HP 1000 +100, Str 30 +3, Focus 80 +9. PASSIVE: up to +50% damage from missing health: x(1 + .5 x
// missing share of CURRENT max HP), on all damage including the dash landing; shields are not health. Code: heart_layer::damage_mult
// (the rule) and clear_mult (the average over a camp clear). Slot 0: self-shield 1.5 x Focus, five turns. Slot 1: dash 2 with a
// radius-1 landing of 1.5 x Focus that stuns.
#include "common.h"
#include "world.h"
#include "multipliers.h"

namespace nova::heart_layer {
// ---------------------------------------------------------------- PASSIVE
inline constexpr float CLEAR_AVG_MULT = 1.12f; // the passive averaged over a camp clear started at full health (it ends near half)
// the rule (GameRules.md:816): 1 + .5 x missing share of the CURRENT max HP
inline float damage_mult(float hp, float maxhp)
{
	const float f = maxhp > 0 ? hp / maxhp : 0.0f;
	return 1.0f + 0.5f * (1.0f - (f < 0.0f ? 0.0f : f > 1.0f ? 1.0f : f));
}
// kit_dps's flat clear average replaced by the rule at this health
inline float rule_over_clear(float hp, float maxhp) { return damage_mult(hp, maxhp) / CLEAR_AVG_MULT; }
// the same for an enemy body known by handle: its current health when it is in sight, full health when it is not
inline float rule_over_clear_of_foe(std::uint32_t h)
{
	for (const auto& e : W.enemies)
		if (e.h == h)
			return rule_over_clear(e.hp, e.maxhp);
	return rule_over_clear(1.0f, 1.0f);
}
// the bonus over a whole camp clear started at this health: x1.12 at full health, x1.31 at half, x1.42 at 20%, at most x1.5
inline float clear_mult(float hp, float maxhp)
{
	return damage_mult(hp, maxhp);
}
} // namespace nova::heart_layer

// ---------------------------------------------------------------- flags HOR_HP: Heart of Ruin buys Health earlier. Values: 0 = off;
// 1: the first Health emblem of the list moves to the front (one Health emblem before the first Focus one); 2: it moves to second
// place (Focus first, then Health); 3: the first two Health emblems move to the front (10 shards); 4: Heart's passive families take
// Health all game. Runtime data flag (HEART_HP_TAB[1]): code is identical at 0..4; read only for a Heart (k.missing_hp_bonus) in
// make_build/upitm_post.
#define HOR_HP 0
inline constexpr int HEART_HP_TAB[2] = { 0x42373334, HOR_HP }; // slot 0 magic keeps it out of .bss

namespace nova::heart_layer {
// ---------------------------------------------------------------- WHO
inline bool me() { return W.me.kit && W.me.kit->missing_hp_bonus; }               // I am Heart of Ruin
inline bool kit(const Kit& k) { return k.missing_hp_bonus; }                         // this kit is Heart of Ruin (a mate, a plan slot)
inline bool type(cambc::champion_type t) { return t == cambc::champion_type::heart_of_ruin; } // this body is a Heart
inline bool body(const Body& b) { return b.kit && b.kit->missing_hp_bonus; }         // this body (known kit) is a Heart

// ---------------------------------------------------------------- RECALL / BANK
inline bool ctx_lkc_skip() { return W.me.type == cambc::champion_type::heart_of_ruin; } // brain hit_champion_before_lock: the CTX LKC rule does not apply to him

// ---------------------------------------------------------------- SHOP
inline bool shop_rcb_health(const Kit& k) { return k.missing_hp_bonus; } // econ make_build (RCB bit 2): his Jungle emblem is Health
// econ crew soak (area bit 2): his slot 1 landing stuns every camp within radius 1 of the landing tile (GameRules.md:826).
inline float camp_landing_stuns(const Kit& k) { return k.dash_stun ? 1.0f : 0.0f; }

// ---------------------------------------------------------------- FIGHT (and heals on him)
inline bool fight_skip_vsh(const Kit& k) { return k.missing_hp_bonus; } // combat self_shield_after_hit_turn_slow: the hit shield does not apply to him
inline bool heal_hold(const Body& b) { return b.kit && b.kit->missing_hp_bonus; }  // combat try_heal_slow, support heal: keep him alive, do not top him up
} // namespace nova::heart_layer
