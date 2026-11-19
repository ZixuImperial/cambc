// econ_staging.cc: Near and respawn staging.
#include "econ_internal.h"
namespace nova::econ {
namespace {
// bit 3 * (oy + 1) + (ox + 1) is set when tile c + (ox, oy), ox, oy in [-1, 1], is within some attacker's reach (cheb <= reach):
// in_reach_of(att, c + (ox, oy), 0) for the centre and its 8 neighbours, in one pass over att.
static unsigned neighbour_reach_mask9(const std::vector<Attacker>& att, vec2 c)
{
	unsigned m = 0;
	for (const auto& a : att)
	{
		const int dx = a.pos.x - c.x, dy = a.pos.y - c.y, r = a.reach;
		// cheb(c + (ox, oy), a.pos) <= r  <=>  ox in [dx - r, dx + r] and oy in [dy - r, dy + r]
		const int x0 = std::max(-1, dx - r), x1 = std::min(1, dx + r);
		const int y0 = std::max(-1, dy - r), y1 = std::min(1, dy + r);
		if (x0 > x1 || y0 > y1)
			continue;
		unsigned row = 0;
		for (int ox = x0; ox <= x1; ++ox)
			row |= 1u << (ox + 1);
		for (int oy = y0; oy <= y1; ++oy)
			m |= row << (3 * (oy + 1));
		if (m == 0x1FFu)
			break;
	}
	return m;
}
// Walk to a waiting spot near the group: outside every attacker's reach.
bool stage_near(int gi)
{
	last_act = ACT_WAIT;
	std::vector<Attacker> la_tmp;
	const auto& att = living_attackers_cached(gi, true, la_tmp);
	const auto& g = M.groups[static_cast<std::size_t>(gi)];
	const vec2 me = W.me.pos;
	PROF("sn0");
	const unsigned m9 = neighbour_reach_mask9(att, me);
	if ((m9 & (1u << 4)) != 0u)
	{
		if (W.me.frac() >= 0.5f && !group_awake(gi))
			return false; // a sleeping target never hits: wait here, not out and back
		std::vector<mv::Threat> th;
		for (const auto& a : att)
			th.push_back({ a.pos, a.reach });
		PROF("sn_esc0");
		const bool r = mv::escape(th);
		PROF("sn_esc");
		return r;
	}
	const int ring = (g.reach_max > 0 ? g.reach_max : 1) + 2;
	if (cheb(me, g.anchor) > ring + 1)
	{
		// Approach, but never step inside an attacker's reach.
		const distance_field* f = mv::group_field(gi);
		PROF("sn_field");
		if (f && dfget(*f, me) != UNREACH)
		{
			const std::uint16_t cur = dfget(*f, me);
			vec2 best{ -1, -1 };
			std::uint16_t bv = cur;
			for (const vec2 d : DIRS)
			{
				const vec2 n = me + d;
				if (!mv::free_tile(n) || (((m9 >> (3 * (d.y + 1) + (d.x + 1))) & 1u) != 0u))
					continue;
				const std::uint16_t v = dfget(*f, n);
				if (v < bv)
				{
					bv = v;
					best = n;
				}
			}
			if (best.x >= 0)
				return mv::try_move(best);
			return false;
		}
		return mv::step_to(g.anchor, ring, 25, gi);
	}
	return false;
}
// a non-tank member at >= 90% HP of an own-side elk opening group whose tank is <= 3 walking rounds away.
bool nontank_joins_elk_opening(int gi, const Here& here)
{
	if (here.tank_is_me || !here.tank || W.me.frac() < 0.9f || !opening_elk_group(gi))
		return false;
	const distance_field* f = mv::group_field_ready(gi);
	int d = f ? static_cast<int>(dfget(*f, here.tank->pos)) : UNREACH;
	if (d == UNREACH)
	{
		d = BIG;
		for (int ci : M.groups[static_cast<std::size_t>(gi)].members)
			d = std::min(d, cheb(M.camps[static_cast<std::size_t>(ci)].pos, here.tank->pos));
	}
	return d - 1 <= 3;
}
// Wait for a respawn 1-2 tiles from the group, since a respawned group sleeps until it is hit, and never on one of its spawn tiles,
// since an occupied tile holds the whole group back. The first hit then lands the round it respawns instead of after a walk from
// outside its reach.
bool respawn_stage(int gi)
{
	const auto& g = M.groups[static_cast<std::size_t>(gi)];
	const distance_field* f = mv::group_field(gi);
	const vec2 me = W.me.pos;
	if (!f || dfget(*f, me) == UNREACH)
		return stage_near(gi);
	last_act = ACT_WAIT;
	auto member_tile = [&](vec2 p)
	{
		for (int ci : g.members)
			if (M.camps[static_cast<std::size_t>(ci)].pos == p)
				return true;
		return false;
	};
	const std::uint16_t cur = dfget(*f, me);
	const bool on_member = cur == 0 || member_tile(me);
	if (!on_member && cur <= PLAN_WAIT_DIST)
		return false; // in place: wait
	if (!W.can_move())
		return false;
	const float here_threat = mv::camp_threat(me, gi);
	vec2 best{ -1, -1 };
	int best_s = BIG;
#pragma clang loop unroll(full) // unroll fully
	for (const vec2 d : DIRS)
	{
		const vec2 n = me + d;
		if (!mv::free_tile(n) || member_tile(n))
			continue;
		const std::uint16_t v = dfget(*f, n);
		// A body must not stand on a camp's spawn tile: the group respawns around it and can never respawn again. Every free neighbour of
		// a two-camp group's member tile is an approach tile (field 0), which the step-off refused. Off a member tile an approach tile is
		// a fallback, after any tile just outside the ring.
		if (v == UNREACH || (v == 0 && !on_member) || (!on_member && v >= cur))
			continue;
		const float th = mv::camp_threat(n, gi);
		if (th > here_threat)
			continue;
		const int s = (on_member ? (v == 0 ? 64 : iabs(static_cast<int>(v) - 1)) : static_cast<int>(v)) * 16 + static_cast<int>(th);
		if (s < best_s)
		{
			best_s = s;
			best = n;
		}
	}
	if (best.x < 0)
		return false;
	return mv::try_move(best);
}
} // namespace
} // namespace nova::econ
