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
bool rgf_crystal_chan = false; // RGF bit 8: a lock stops a tribute, not a crystal
// a foe that carries a lock and gets within 2 of the altar (Chebyshev; the altar is within 1 of me, so taken as dist - 1) in its turns of the channel. A dash
// ready on one of those turns adds its 2 tiles once (interactions.md:30; GameRules:159); kit or cooldown unknown counts as ready.
static bool rgf_foe_lock_within(const Body& e, int dist, int foe_turns)
{
	const bool dash_kit = !e.kit || !e.kit->valid || (e.kit->slot_dash >= 0 && e.kit->slot_dash <= 1);
	const bool dash_up = foe_turns > 0 && dash_kit && (!e.kit || !e.kit->valid || std::max(0, foe_cd(e, e.kit->slot_dash)) < foe_turns);
	std::array<std::uint32_t, 4> cnt{};
	return std::max(0, dist - 3 - (dash_up ? 2 : 0)) <= foe_turns && cambc::detail::sdk_champion_consumables(e.h, cnt.data()) == 0 && cnt[RAW_LOCK] > 0;
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
		const bool r1s = e.stunned; // CB3 bit 32 R1: the stun costs one turn, not the channel's whole span
		const int ch = foe_channel_act_delay(e) + (r1s && burst::stun_takes_next_turn(e) ? 1 : 0);
		const Foe f = r1s ? foe_of_unstunned(e, idx) : foe_of(e, idx);
		const int expo = span - (1 + std::max(0, dist - f.reach) + ch) + 1;
		if (expo > 0)
			dmg += mu::mult_foe_hit_to_real_hp(f.burst + dmg::foe_dmg_dps(f) * static_cast<float>(expo - 1));
		if constexpr (STUN)
		{
			const int fs = stance::foe_turns_within_rounds(e, span + 1);
			if (immune)
			{
				return !(!rgf_crystal_chan && rgf_foe_lock_within(e, dist, fs));
			}
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
bool rgf_foe_lock_in_time(int ticks)
{
	const auto one = [&](const Body& e) { return recall::rgf_foe_lock_within(e, cheb(e.pos, W.me.pos), stance::foe_turns_within_rounds(e, ticks + 1)); };
	for (const auto& e : W.enemies)
		if (one(e))
			return true;
	for (const auto& e : W.enemies_far)
		if (one(e))
			return true;
	return false;
}
bool channel_safe(int walk, int ticks, float camp_dmg, bool crystal)
{
	recall::rgf_crystal_chan = crystal;
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
// v628 WCD: Foe.reach already holds the walk and the dash of the foe's next turn, so the "- 2 for a dash" above counts the dash twice.
// A foe's reach on one of its turns, cooldowns cdh turns on; no_dash: its dash went on the turn before (foe_next_turn_reach, GameRules:118).
static int wcd_turn_reach(const Body& e, int cdh, bool no_dash)
{
	const Kit* kp = e.kit;
	if (!kp || !kp->valid)
		return std::max(2, e.range + 1);
	const Kit& k = *kp;
	int reach = k.ranged ? e.range + (foe_ready(e, k.slot_reset, cdh) ? 1 : 0) : 2;
	if (!no_dash && foe_ready(e, k.slot_dash, cdh))
		reach = std::max(reach, (k.ranged ? e.range : 1) + 2 + (k.ranged ? 0 : 1));
	const auto sp = [&](int s, float range, bool excl, float radius)
	{
		if (foe_ready(e, s, cdh))
			reach = std::max(reach, static_cast<int>(range + radius) + (excl ? 0 : 1));
	};
	sp(k.slot_dmg, k.dmg_range, k.dmg_excl, 0.0f);
	sp(k.slot_cc, k.cc_range, k.cc_excl, 0.0f);
	sp(k.slot_aoe, k.aoe_range, k.aoe_excl, k.aoe_radius);
	return reach;
}
// How far a visible foe can hit on its second turn from now: turn 1 walks (and dashes when the dash is up; one cast per turn, so the
// reach of a spell or reset stays for turn 2, which the next-turn reach does not add), turn 2 has cooldowns one turn on. A stun that
// takes its next turn leaves only turn 2. Two foe turns either way: a double turn across a round boundary is the same two turns.
static int wcd_second_turn_reach(const Body& e)
{
	if (burst::stun_takes_next_turn(e))
		return wcd_turn_reach(e, 1, false);
	int r = wcd_turn_reach(e, 1, false) + 1;
	if (e.kit && e.kit->valid && foe_ready(e, e.kit->slot_dash, 0))
		r = std::max(r, wcd_turn_reach(e, 1, true) + 1 + std::max(1, static_cast<int>(e.kit->dash_range)));
	return r;
}
// foe_damage_over_ticks without the double count. A foe I see now: both turns inside its next-turn reach, one turn inside its second-turn
// reach. A remembered foe (no Body, cooldowns unknown): with mem_tile, one tile a turn beyond its next-turn reach; else as before.
// v629 WDV (WCK_TURNS 2): a foe I see is charged the hits it can land in its two turns (an excludes-walking spell needs a turn begun
// in range), not burst + dps x left. A remembered foe has no Body: as foe_damage_over_ticks.
float foe_damage_over_ticks_deliver(int max_age, int ticks)
{
	const auto hits = [](const Body& e, int d) {
		return burst::stun_takes_next_turn(e) ? burst::lethal_burst_hit(e, d, 1, nullptr) : burst::foe_two_turn_damage(e, d, burst::lethal_burst_hit(e, d, 0, nullptr));
	};
	const auto mem = [&](const Foe& f, int d) {
		const int reach = f.reach >= 0 ? f.reach : 4;
		const int left = ticks - std::max(0, d - reach - 2);
		return left > 0 ? f.burst + dmg::foe_dmg_dps(f) * static_cast<float>(left) : 0.0f;
	};
	float sum = 0.0f;
	for (const auto& s : seen)
	{
		const int age = W.round - s.round;
		if (age < 0 || age > max_age)
			continue;
		const int d = std::max(0, cheb(s.foe.pos, W.me.pos) - age);
		const Body* vis = nullptr;
		if (age == 0)
			for (const auto& e : W.enemies)
				if (e.h == s.h)
					vis = &e;
		sum += vis ? hits(*vis, d) : mem(s.foe, d);
	}
	for (const auto& e : W.enemies_far)
	{
		bool known = false;
		for (const auto& s : seen)
			known = known || (s.h == e.h && W.round - s.round <= max_age);
		if (!known)
			sum += hits(e, cheb(e.pos, W.me.pos));
	}
	return sum;
}
float foe_damage_over_ticks_wcd(int max_age, int ticks, bool mem_tile)
{
	const auto one = [&](const Foe& f, int d, const Body* e) {
		const int reach = f.reach >= 0 ? f.reach : 4;
		const int left = e ? (d <= reach ? ticks : ticks - 1 - std::max(0, d - wcd_second_turn_reach(*e))) : ticks - std::max(0, d - reach - (mem_tile ? 0 : 2));
		return left > 0 ? f.burst + dmg::foe_dmg_dps(f) * static_cast<float>(left) : 0.0f;
	};
	const auto visible = [&](std::uint32_t h) -> const Body* {
		for (const auto& e : W.enemies)
			if (e.h == h)
				return &e;
		return nullptr;
	};
	float sum = 0.0f;
	for (const auto& s : seen)
	{
		const int age = W.round - s.round;
		if (age >= 0 && age <= max_age)
			sum += one(s.foe, std::max(0, cheb(s.foe.pos, W.me.pos) - age), age == 0 ? visible(s.h) : nullptr);
	}
	for (const auto& e : W.enemies_far)
	{
		bool known = false;
		for (const auto& s : seen)
			known = known || (s.h == e.h && W.round - s.round <= max_age);
		if (!known)
			sum += one(foe_of(e, -1), cheb(e.pos, W.me.pos), &e);
	}
	return sum;
}
} // namespace nova::combat
