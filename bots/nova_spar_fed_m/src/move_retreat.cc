// move_retreat.cc: Step away, camp lists, reach guards and retreat.
#include "move_internal.h"
namespace nova::mv {
bool step_away(const std::vector<vec2>& from, int min_gain)
{
	AF_CHECK();
	if (!W.can_move() || from.empty())
		return false;
	const vec2 me = W.me.pos;
	auto mind = [&](vec2 p)
	{
		int m = BIG;
		for (vec2 f : from)
			m = std::min(m, cheb(p, f));
		return m;
	};
	const int base = mind(me);
	CandList cands;
#pragma clang loop unroll(full)
	for (const vec2 d : DIRS)
	{
		const vec2 n = me + d;
		if (!free_tile(n))
			continue;
		const int md = mind(n);
		if (md < base + min_gain && md < base)
			continue;
		if (md == base && n == prev_pos)
			continue; // No sideways step back onto the tile I just left (A-B-A along the threat's contour).
		int score = -md * tune::AWAY_TILE + static_cast<int>(camp_threat(n));
		if (M.has_home)
		{
			const std::uint16_t hv = dfget(M.f_home, n);
			if (hv != UNREACH)
				score += static_cast<int>(hv) / tune::AWAY_HOME_DIV;
		}
		cands.push_back({ n, score });
	}
	if (cands.empty())
		return false;
	return move_best(cands);
}
std::vector<Threat> camp_threats_near(int radius)
{
	AF_CHECK();
	// camp_threat's list holds exactly the visible awake attackers, then remembered ones not seen awake this round, in the same order.
	std::vector<Threat> out;
	auto scan = [&](auto tick) __attribute__((always_inline))
	{
		std::size_t af_i = 0;
		for (const auto& e : camp_threat_entries())
		{
			if (tick.value)
				AF_TICK(af_i++); // The checked copy.
			if (cheb(e.pos, W.me.pos) <= radius)
				out.push_back({ e.pos, e.reach });
		}
	};
	if (af_armed)
		scan(std::true_type{});
	else
		scan(std::false_type{});
	return out;
}
// The guard's zone is the reach of every awake attacking camp in sight (and the ones remembered awake out of sight), whichever
// champion is nearest to it: allies move, and a hurt body cannot afford to bet on them.
NOVA_INLINE bool camp_reach_zone(bitboard& z)
{
	bool any = false;
	for (const auto& e : camp_threat_entries())
		if (e.str > 0 && e.reach >= 0)
		{
			z.draw_chebyshev(e.pos, static_cast<float>(e.reach));
			any = true;
		}
	return any;
}
bool spawn_in_camp_reach()
{
	if (!bbany_simd_move(M.my_spawn))
		return false;
	bitboard z;
	if (!camp_reach_zone(z))
		return false;
	bitboard out = M.my_spawn;
	out &= ~z;
	return !bbany_simd_move(out);
}
AvoidCampReach::AvoidCampReach(bool on)
{
	if (!on || (avoid_on && !avoid_foe) || !W.alive)
		return; // Off, or an outer camp guard rules (a foe guard's zone is added to).
	bitboard z;
	// camp_threat's list holds the same camps (the visible ones are attackers by construction; the remembered ones keep the attacks()
	// test, str > 0); a union of reaches, so the order does not matter.
	if (!camp_reach_zone(z) || bbget(z, W.me.pos))
		return; // nothing awake near, or already inside a reach (escape's job)
	if (avoid_on && avoid_foe)
	{
		prev = std::make_unique<bitboard>(avoid_bb); // Inside a foe guard: add the camps' reach, restore on exit.
		avoid_bb |= z;
		merged = true;
		return;
	}
	avoid_bb = z;
	avoid_on = true;
	active = true;
}
AvoidCampReach::~AvoidCampReach()
{
	if (merged && prev)
		avoid_bb = *prev;
	if (active)
		avoid_on = false;
}
// GSP: I stand inside the guard's union. Bit 1: the lethal zones (from gsp_lf) that don't contain me, unless one does; bit 2: every zone
// that doesn't contain me. True: that board is now the guard's zone.
static bool gsp_inside_guard(const std::vector<std::pair<vec2, int>>& foes)
{
	bitboard z;
	bool any = false;
	const int from = GSP_ON(2) ? 0 : GSP_ON(1) ? gsp_lf : -1;
	if (from < 0)
		return false;
	for (std::size_t i = static_cast<std::size_t>(from); i < foes.size(); ++i)
	{
		const auto& [p, r] = foes[i];
		if (cheb(W.me.pos, p) <= r)
		{
			if (!GSP_ON(2))
				return false; // inside a lethal zone: the flee logic's call
			continue;
		}
		z.draw_chebyshev(p, static_cast<float>(r));
		any = true;
	}
	if (!any || bbget(z, W.me.pos))
		return false;
	avoid_bb = z;
	avoid_on = true;
	avoid_foe = true;
	return true;
}
AvoidFoeReach::AvoidFoeReach(const std::vector<std::pair<vec2, int>>& foes, bool on)
{
	if (!on || avoid_on || !W.alive || foes.empty())
		return;
	bitboard z;
	for (const auto& [p, r] : foes)
		z.draw_chebyshev(p, static_cast<float>(r));
	if (bbget(z, W.me.pos))
	{
		if (GSP_TAB[1] != 0 && gsp_inside_guard(foes))
			active = true;
		return; // already inside a reach: the fight and flee logic's call
	}
	avoid_bb = z;
	avoid_on = true;
	avoid_foe = true;
	active = true;
}

AvoidFoeReach::~AvoidFoeReach()
{
	if (active)
	{
		avoid_on = false;
		avoid_foe = false;
	}
}

SuspendFoeGuard::SuspendFoeGuard(bool on)
{
	if (!on || !avoid_on || !avoid_foe)
		return;
	avoid_on = false;
	active = true;
}
SuspendFoeGuard::~SuspendFoeGuard()
{
	if (active)
		avoid_on = true;
}
bool in_threat(const std::vector<Threat>& threats, vec2 p, int margin)
{
	for (const auto& t : threats)
		if (cheb(p, t.pos) <= t.reach + margin)
			return true;
	return false;
}
int home_steps(vec2 p)
{
	if (M.has_home)
	{
		const std::uint16_t v = dfget(M.f_home, p);
		if (v != UNREACH)
			return v;
	}
	return cheb(p, M.home_anchor);
}


// ======== Retreat ======== Walk steps from the rally tile, one bounded field per round and rally (fuel ~1-2 per tile reached).
static int rally_walk_dist(vec2 p, vec2 rally)
{
	static distance_field f;
	static bitboard vis, roots;
	static int at_round = -1;
	static vec2 at{ -1, -1 };
	const int r = static_cast<int>(FRW_TAB[2]);
	if (at_round != W.round || !(at == rally))
	{
		roots.clear();
		bbset(roots, rally);
		f.compute(M.block, roots, vis, static_cast<std::uint16_t>(r));
		at_round = W.round;
		at = rally;
	}
	const std::uint16_t v = dfget(f, p);
	if (v != UNREACH)
		return static_cast<int>(v);
	return r + 1 + cheb(p, rally);
}

bool retreat_step(const std::vector<Threat>& threats, int margin, vec2 rally)
{
	AF_CHECK();
	if (!W.can_move())
		return false;
	const vec2 me = W.me.pos;
	const bool to_rally = rally.x >= 0;
	// Only tiles within 1 of me are scored, so a threat farther than reach + margin + 1 adds 0 to each (integer terms: the float sums
	// are exact in any order, and the kept ones stay in order).
	static std::vector<Threat> rts_near;
	rts_near.clear();
	for (const auto& t : threats)
		if (cheb(me, t.pos) <= t.reach + margin + 1)
			rts_near.push_back(t);
	// The score without camp_threat (which is >= 0): reach danger, then the walk to the rally or home.
	auto reach_score = [&](vec2 p)
	{
		float danger = 0;
		for (const auto& t : rts_near)
			danger += static_cast<float>(std::max(0, t.reach + margin + 1 - cheb(p, t.pos)));
		const float goal = to_rally ? static_cast<float>(std::max(0, rally_walk_dist(p, rally) - 1)) : static_cast<float>(home_steps(p));
		return danger * tune::RETREAT_DANGER + goal;
	};
	auto with_camps = [](float reach, vec2 p) { return reach + camp_threat(p) / tune::RETREAT_CAMP_DIV; };
	const float stay = with_camps(reach_score(me), me);
	CandList cands;
#pragma clang loop unroll(full)
	for (const vec2 d : DIRS)
	{
		const vec2 n = me + d;
		if (!free_tile(n) || (n == prev_pos && !(W.round - prev_round > SS_PREV_R))) // A fresh prev_pos only.
			continue;
		const float reach = reach_score(n);
		if (reach >= stay) // sc >= stay whatever camp_threat adds.
			continue;
		const float sc = with_camps(reach, n);
		if (sc >= stay)
			continue;
		cands.push_back({ n, static_cast<int>(sc * tune::RETREAT_SCALE) + ((d.x != 0 && d.y != 0) ? 1 : 0) });
	}
	if (cands.empty())
		return false;
	return move_best(cands);
}
} // namespace nova::mv
