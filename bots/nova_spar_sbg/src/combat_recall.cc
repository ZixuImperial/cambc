// combat_recall.cc: Whether a recall is safe.
#include "combat_internal.h"
namespace nova::combat {
namespace recall
{
namespace tune
{
inline constexpr int BUS_SIGHTING_ROUNDS = 4; // a foe last seen this long ago still counts
inline constexpr int BUS_SIGHTING_REACH = 4;  // an old sighting: assume a dash or a spell, as bank_first
}
namespace {
// The first round foe e's stun can land on a channel dist away; ch: rounds before e can act (foe_channel_act_delay). BIG if none.
static int foe_stun_landing_round(const Body& e, const Foe& f, int dist, int ch)
{
	const Kit& k = *e.kit;
	const auto lands = [&](int s, int r) { // the round its stun from slot s (range r) can land; BIG if none
		if (s < 0 || s > 1)
			return static_cast<int>(BIG);
		const int cd = std::max(0, foe_cd(e, s)); // -1 unknown: ready
		return std::max(1 + std::max(0, dist - r) + ch, cd + 1);
	};
	int t = BIG;
	if (k.slot_cc >= 0)
	{
		t = std::min(t, lands(k.slot_cc, static_cast<int>(k.cc_range) + (k.cc_excl ? 0 : 1)));
		if (k.slot_dash >= 0 && k.slot_dash <= 1 && k.slot_dash != k.slot_cc && !k.dash_stun) // the dash on an earlier turn
			t = std::min(t, std::max({ lands(k.slot_cc, static_cast<int>(k.cc_range) + static_cast<int>(k.dash_range) + (k.cc_excl ? 0 : 1)), 2 + ch, std::max(0, foe_cd(e, k.slot_dash)) + 2 }));
	}
	if (k.aoe_stun)
		t = std::min(t, lands(k.slot_aoe, static_cast<int>(k.aoe_range + k.aoe_radius) + (k.aoe_excl ? 0 : 1)));
	if (k.dash_stun)
		t = std::min(t, lands(k.slot_dash, (k.ranged ? e.range : 1) + 2 + (k.ranged ? 0 : 1)));
	if (k.reset_enhanced)
		t = std::min(t, lands(k.slot_reset, burst::fk1_armed_reach(e, k)));
	return t;
}
template <bool STUN>
static bool channel_safe_check(int walk, int ticks, float camp_dmg)
{
	const vec2 me = W.me.pos;
	const int w = std::max(0, walk);
	const int span = w + std::max(1, ticks);
	float dmg = std::max(0.0f, camp_dmg) * static_cast<float>(span);
	const bool immune = marcella_layer::chan_stun_proof();
	const auto body = [&](const Body& e, int idx) -> bool { // false: it can stop the channel
		const int dist = std::max(0, cheb(e.pos, me) - w);
		const int ch = foe_channel_act_delay(e);
		const Foe f = foe_of(e, idx);
		const int expo = span - (1 + std::max(0, dist - f.reach) + ch) + 1;
		if (expo > 0)
			dmg += mu::mult_foe_hit_to_real_hp(f.burst + dmg::foe_dmg_dps(f) * static_cast<float>(expo - 1));
		if constexpr (STUN)
		{
			const int fs = stance::foe_turns_within_rounds(e, span + 1);
			if (immune)
				return true;
			if (!e.kit || !e.kit->valid)
				return expo <= 0; // kit unknown: in reach counts as a stun
			return foe_stun_landing_round(e, f, dist, ch) > fs;
		}
		return true;
	};
	for (std::size_t i = 0; i < W.enemies.size(); ++i)
		if (!body(W.enemies[i], static_cast<int>(i)))
			return false;
	for (const auto& e : W.enemies_far)
		if (!body(e, -1))
			return false;
	for (const auto& s : seen)
	{
		const int age = W.round - s.round;
		if (age <= 0 || age > tune::BUS_SIGHTING_ROUNDS)
			continue;
		bool known = false;
		for (const auto& e : W.enemies)
			known = known || e.h == s.h;
		for (const auto& e : W.enemies_far)
			known = known || e.h == s.h;
		if (known)
			continue;
		const int dist = std::max(0, cheb(s.foe.pos, me) - age - w);
		const int reach = std::max(tune::BUS_SIGHTING_REACH, s.foe.reach);
		const int expo = span - (1 + std::max(0, dist - reach)) + 1;
		if (expo <= 0)
			continue;
		if (STUN && !immune)
			return false; // its kit and cooldowns are not known here: in reach counts as a stun
		dmg += mu::mult_foe_hit_to_real_hp(s.foe.burst + dmg::foe_dmg_dps(s.foe) * static_cast<float>(expo - 1));
	}
	return dmg * 100.0f < static_cast<float>(BUS_PCT) * (W.me.hp + W.me.shield);
}
} // namespace
} // namespace recall
// ---------------------------------------------------------------- recall safety
bool recall_bush_threat()
{
	const vec2 me = W.me.pos;
	for (const auto& s : seen)
	{
		const int age = W.round - s.round;
		if (age < 1 || age > 2 || cheb(s.foe.pos, me) > s.foe.reach + 1)
			continue;
		for (int dx = -1; dx <= 1; ++dx)
			for (int dy = -1; dy <= 1; ++dy)
			{
				const vec2 q{ s.foe.pos.x + dx, s.foe.pos.y + dy };
				if (inb(q) && bbget(M.bushes, q))
					return true;
			}
	}
	return false;
}
bool recall_safe(const Assessment& a)
{
	if (took_damage(2))
		return false;
	const vec2 me = W.me.pos;
	// Any awake camp that has me in reach may pick me (allies move away, ties break by turn order).
	for (const auto& vc : W.camps)
	{
		const auto& c = M.camps[static_cast<std::size_t>(vc.ci)];
		if (vc.awake && c.attacks() && cheb(c.pos, me) <= c.reach)
			return false;
	}
	// A foe that can reach me within the five turns of the channel.
	for (const auto& f : a.foes)
		if (cheb(f.pos, me) <= f.reach + 4)
			return false;
	for (const auto& s : seen)
		if (W.round - s.round <= 5 && cheb(s.foe.pos, me) <= s.foe.reach + 4 + (W.round - s.round))
			return false;
	if (W.round - turn_memory.cancel_round < 3)
		return false;
	return true;
}
bool recall_doomed(const Assessment& a)
{
	if (!(W.me.state & ST_RECALL))
		return false;
	if (a.in_reach)
		return true;
	return mv::camp_threat(W.me.pos) > 0;
}
int nearest_foe_distance_seen(int max_age)
{
	int best = BIG;
	for (const auto& s : seen)
	{
		const int age = W.round - s.round;
		if (age < 0 || age > max_age)
			continue;
		best = std::min(best, std::max(0, cheb(s.foe.pos, W.me.pos) - age));
	}
	return best;
}
// Rounds before this foe can act, counting a channel it has open. Called only with a BUS bit on.
int foe_channel_act_delay(const Body& e)
{
	if (!(e.state & ST_TELEPORT))
		return 0; // recall / tribute: cancellable by hand, so the foe can act at its next turn
	std::int32_t left = 0;
	if (cambc::detail::sdk_champion_channel_time(e.h, &left) != 0 || left < 0)
		return 0;
	return static_cast<int>(left);
}
bool channel_safe(int walk, int ticks, float camp_dmg, bool crystal)
{
	return recall::channel_safe_check<true>(walk, ticks, camp_dmg);
}
// Every foe in my combat memory or seen through a ward: burst + dps x the ticks left once it stands in reach, walking straight in (distance - age - reach
// - 2 for a dash; Chebyshev, so a lower bound on its walk).
float foe_damage_over_ticks(int max_age, int ticks)
{
	const auto one = [&](const Foe& f, int d) {
		const int reach = f.reach >= 0 ? f.reach : 4; // an old sighting: assume a dash or a spell, as bank_first
		const int left = ticks - std::max(0, d - reach - 2);
		return left > 0 ? (f.burst + dmg::foe_dmg_dps(f) * static_cast<float>(left)) * (1.0f) : 0.0f;
	};
	float sum = 0.0f;
	for (const auto& s : seen)
	{
		const int age = W.round - s.round;
		if (age >= 0 && age <= max_age)
			sum += one(s.foe, std::max(0, cheb(s.foe.pos, W.me.pos) - age));
	}
	for (const auto& e : W.enemies_far)
	{
		bool known = false;
		for (const auto& s : seen)
			known = known || (s.h == e.h && W.round - s.round <= max_age);
		if (!known)
			sum += one(foe_of(e, -1), cheb(e.pos, W.me.pos));
	}
	return sum;
}
} // namespace nova::combat
