// combat_dps.cc: Damage over a horizon and kit strength.
#include "combat_internal.h"
namespace nova::combat {
namespace dmg
{
namespace tune
{
// Modules of this file, in order (each owns one job; shared types, state and tunables come first):
//   rules: kit values and rule numbers for damage
//   geom: tiles, reach, dash legality, danger zones
//   dps: damage over a horizon, kit strength
//   foes: the Foe record, memo, unreachable foes
//   burst: one-turn kill and lethal-burst model
//   memory: observe, per-round trackers
//   team: mates, focus choice, help
//   assess: the stance decision
//   cast: spells and raw attacks in a fight
//   fight: the FIGHT stance turn
//   flee: the FLEE stance, retreat, refuge
//   recall: is a recall safe
//   deny: altars, locks, tribute denial
//   camps: camps and camp casts
//   calm: casts on a calm turn
//   pair: linked Cassi and Issac pair
//   actfirst: act-first fallback
inline constexpr int DPS_HORIZON = 5;              // turns every damage-rate estimate looks ahead
inline constexpr float DPS_AREA_HITS = 1.3f;       // fitted bodies one splash, area or dash effect hits
inline constexpr float DPS_STUNNED = 0.8f;         // a stun costs exactly the next turn: 4 of 5
inline constexpr float DPS_REN_HITS_A_TURN = 0.5f; // assumed hits a turn Ren takes when the PASS count is off
}
static inline float foe_dmg_dps(const Foe& f) { return f.dps; } // the damage sums read f.dps
static inline float foe_hd_dps(const Foe& f) { return foe_dmg_dps(f); } // inc in tdps's units
// The damage sums (channel_damage_threat, channel_safe, foe_damage_over_ticks) read f.dps.

// The share of a body's damage that lands on one target d away (me, or a mate). Read only with the bit on.
static inline float dps_fs_ours(bool me, int d) { return 0.01f * static_cast<float>(DPS_TAB[me ? 2 : (d <= 1 ? 3 : 4)]); }
// The share of a foe's damage that lands on me, by its distance to me.
static inline float dps_fs_foe(int d) { return 0.01f * static_cast<float>(DPS_TAB[4 + std::clamp(d, 1, 6)]); }
namespace {
// The kit factor exp(.25 kit_fight_value) is a constant per type, computed on first use (exp is never 0).
static float kit_fight_factor(cambc::champion_type t)
{
	static std::array<float, 13> kf_exp{};
	const auto kt = static_cast<std::size_t>(t);
	if (kt >= kf_exp.size())
		return std::exp(0.25f * kit_rules::kit_fight_value(t));
	float& kf = kf_exp[kt];
	if (kf == 0.0f)
		kf = std::exp(0.25f * kit_rules::kit_fight_value(t));
	return kf;
}
} // namespace
namespace {
// Slot s's cooldown as this estimate reads it (-1 unknown: ready).
static inline int dps_slot_cd(const Body& b, bool me, int s)
{
	return me ? W.cd[static_cast<std::size_t>(s)] : foe_cd(b, s);
}
} // namespace
namespace {
// The fight-value factor: every strength call carries it, a damage call (bit 2) does not.
static __attribute__((always_inline)) inline float dps_kit_scaled(float d, const Body& b, int dpsb, bool one)
{
	if ((dpsb & 2) != 0 && one)
		return d;
	return d * kit_fight_factor(b.type);
}
// The fitted estimate: dn and two as the dps scan gives them (dn 99, two false and dpsb 0 are the flag-0 call).
static __attribute__((always_inline)) inline float horizon_fit(const Body& b, bool me, bool one, int dpsb, int dn, bool two)
{
	const Kit& k = *b.kit;
	constexpr int H = tune::DPS_HORIZON;
	auto soon = [&](int s) { return s >= 0 && s <= 1 && dps_slot_cd(b, me, s) <= H - 1; };
	// targets one multi-target effect hits; with bit 2 ONE: damage on one body counts each effect once (the splash never hits its own
	// target; an area or landing hits a body once)
	const float area_hits = (one) || ((dpsb & 4) != 0 && !two) ? 1.0f : tune::DPS_AREA_HITS;
	VSP_CNT(2, one && (k.splash || soon(k.slot_aoe) || (soon(k.slot_dash) && k.dash_mod > 0)));
	float dmg = b.str * static_cast<float>(H);
	if ((dpsb & 1) != 0 && dn < 99) // turns spent closing to the nearest opposing body hit nothing
		dmg = b.str * static_cast<float>(H - std::min(H, std::max(0, dn - b.range)));
	if (soon(k.slot_reset))
		dmg += b.str;
	if (k.splash)
		dmg *= area_hits;
	if (soon(k.slot_dmg))
		dmg += k.dmg_mod * b.foc;
	if (soon(k.slot_cc))
		dmg += k.cc_mod * b.foc;
	if (soon(k.slot_aoe))
		dmg += k.aoe_mod * b.foc * area_hits;
	if (soon(k.slot_dash) && k.dash_mod > 0)
		dmg += k.dash_mod * b.foc * area_hits;
	if (k.retaliation)
		dmg += ren_layer::retaliation_damage(b.foc) * static_cast<float>(H) * tune::DPS_REN_HITS_A_TURN;
	float d = dmg / static_cast<float>(H) * kit_rules::passive_mult(b);
	if (b.stunned)
		d *= tune::DPS_STUNNED;
	return dps_kit_scaled(d, b, dpsb, one);
}
} // namespace
float horizon_dps_k(const Body& b, bool me, bool one)
{
	if (!b.kit || !b.kit->valid)
		return 50.0f;
	return horizon_fit(b, me, one, 0, 99, false);
}
// Damage on one body.
float horizon_dps1(const Body& b, bool me) { return horizon_dps_k(b, me, true); } // a damage call when on (DPS, or VSP bit 2)
namespace {
} // namespace
// Healing one support body can put into a fight around `at` within `horizon` turns (0 when it is too far or its heal
// is not back in time). `cd` is its heal cooldown (-1: unknown, counted as ready).
// HCP: heal_of's casts with bit 2's stun turn and bit 1's cap (GR:724: up to 3 x Focus, another ally only).
static __attribute__((noinline)) int tbf_hcs1_stun_cd(int c) { return std::max(c, 1); } // v699 TBF bit 2 HCS1: the stun costs the next turn only
static float hcp_heal_of(const Body& b, int cd, int horizon)
{
	const Kit& k = *b.kit;
	int c = std::max(0, cd);
	if (b.stunned)
		c = tbf_hcs1_stun_cd(c);
	if (c > horizon - 1)
		return 0.0f;
	const int casts = 1 + (horizon - 1 - c) / 8;
	float per = k.heal_mod * b.foc;
	float miss = 0;
	const int hr = static_cast<int>(k.heal_range) + 1;
	auto consider = [&](const Body& t)
	{
		if (&t != &b && t.h != b.h && cheb(t.pos, b.pos) <= hr)
			miss = std::max(miss, t.maxhp - t.hp);
	};
	if (&b == &W.me || b.ally)
	{
		consider(W.me);
		for (const auto& al : W.allies)
			consider(al);
	}
	else
		for (const auto& e : W.enemies)
			consider(e);
	per = std::min({ per, 3.0f * b.foc, miss });
	return per * static_cast<float>(casts);
}
float heal_of(const Body& b, int cd, vec2 at, int horizon, int margin = 3) // margin: WL2_ON(524288) HLK passes WL2_HLK_K
{
	const Kit* kp = b.kit;
	if (!kp || !kp->valid || kp->slot_heal < 0 || b.channeling())
		return 0.0f;
	if (cheb(b.pos, at) > static_cast<int>(kp->heal_range) + margin) // live margin 3 unless WL2_ON(524288)
		return 0.0f;
	if (W.me.kit && !prism_layer::kit(*W.me.kit)) // HCP: capped heal, stunned healer
		return hcp_heal_of(b, cd, horizon);
	const int c = std::max(0, cd);
	if (c > horizon - 1)
		return 0.0f;
	const int casts = 1 + (horizon - 1 - c) / rs::slot_cooldown();
	return kp->heal_mod * b.foc * static_cast<float>(casts);
}
// a foe healer heals ANOTHER foe only: counted only with another foe within 8 of `at`.
static __attribute__((noinline)) int tbf_fhr1_r() { return 6; } // v699 TBF bit 1 FHR1: FIGHT_R (combat_assess_contact.cc, later in the unity build)
static float foe_heal_on_others(vec2 at, int horizon, const Assessment& a)
{
	float pool = 0;
	for (const auto& e : W.enemies)
		if (e.kit && e.kit->slot_heal >= 0)
		{
			const int j = static_cast<int>(&e - W.enemies.data());
			bool other = false;
			for (const auto& f : a.foes)
				if (f.idx != j && cheb(f.pos, at) <= (tbf_fhr1_r())) // v699 TBF bit 1 FHR1
				{
					other = true;
					break;
				}
			if (other)
				pool += heal_of(e, foe_cd(e, e.kit->slot_heal), at, horizon);
		}
	return pool;
}
} // namespace dmg
namespace {
float horizon_dps(const Body& b, bool me) { return dmg::horizon_dps_k(b, me, false); }
} // namespace
bool cast_at(int slot, vec2 p) { return cast::cast_via_sdk(slot, 0, 0, p); }
bool cast_self(int slot) { return cast::cast_via_sdk(slot, 0, 0, { -1, -1 }); }
float body_dps(const Body& b)
{
	if (!b.kit)
		return 50.0f;
	float d = kit_dps(*b.kit, b.str, b.foc, 1);
	if (b.kit->missing_hp_bonus) // kit_dps's flat x1.12 -> the rule
		d *= heart_layer::rule_over_clear(b.hp, b.maxhp);
	if (b.stunned)
		d *= (dmg::tune::DPS_STUNNED);
	return d;
}
float support_heal_pool(vec2 at, int horizon)
{
	float pool = 0;
	if (W.me.kit && W.me.kit->slot_heal >= 0)
		pool += dmg::heal_of(W.me, W.cd[static_cast<std::size_t>(W.me.kit->slot_heal)], at, horizon);
	for (const auto& al : W.allies)
		if (al.kit && al.kit->slot_heal >= 0)
		{
			pool += dmg::heal_of(al, al.cd[static_cast<std::size_t>(al.kit->slot_heal)], at, horizon,
				3); // WL2 HLK: a mate counts her heal only within reach + K
		}
	return pool;
}
float enemy_heal_pool(vec2 at, int horizon)
{
	float pool = 0;
	for (const auto& e : W.enemies)
		if (e.kit && e.kit->slot_heal >= 0)
			pool += dmg::heal_of(e, foe_cd(e, e.kit->slot_heal), at, horizon);
	return pool;
}
} // namespace nova::combat
