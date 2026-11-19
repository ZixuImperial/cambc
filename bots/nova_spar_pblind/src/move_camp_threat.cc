// move_camp_threat.cc: The awake camps that would hit a tile.
#include "move_internal.h"
namespace nova::mv {
namespace {
// One more body at `at`: the nearest other body, and the nearest that takes camp ties.
NOVA_INLINE void camp_threat_add_body(CtEntry& e, vec2 at, bool tie)
{
	const int db = cheb(at, e.pos);
	e.dmin = std::min(e.dmin, db);
	if (tie)
		e.dtie = std::min(e.dtie, db);
}
void camp_threat_other_bodies(CtEntry& e)
{
	e.dmin = BIG;
	e.dtie = BIG;
	// The other bodies' tiles and tie flags, once per camp list and W state (ct_stamp, fg::pstamp, round): the first fill asks
	// takes_tie of every body in the same order as this loop's first run, and its answer is fixed for the round (tie_prio per round,
	// enemies never take ties), so the minima are the same.
	if (W.allies.size() + W.enemies.size() <= 32)
	{
		static int bs = -1, bp = -1, br = -1, nb = 0;
		static std::array<vec2, 32> pos{};
		static std::array<std::uint8_t, 32> tie{};
		if (bs != ct_stamp || bp != fg::pstamp || br != W.round)
		{
			bs = ct_stamp;
			bp = fg::pstamp;
			br = W.round;
			nb = 0;
			for (const auto* lst : { &W.allies, &W.enemies }) // the first call of a state: this loop's own scan, kept
				for (const auto& b : *lst)
				{
					const bool t = takes_tie(b);
					camp_threat_add_body(e, b.pos, t);
					pos[static_cast<std::size_t>(nb)] = b.pos;
					tie[static_cast<std::size_t>(nb)] = t ? 1 : 0;
					++nb;
				}
			return;
		}
		for (int k = 0; k < nb; ++k)
			camp_threat_add_body(e, pos[static_cast<std::size_t>(k)], tie[static_cast<std::size_t>(k)] != 0);
		return;
	}
	for (const auto* lst : { &W.allies, &W.enemies })
		for (const auto& b : *lst)
			camp_threat_add_body(e, b.pos, takes_tie(b));
}
NOVA_INLINE void camp_threat_add(const CampI& c)
{
	const int dm = cheb(c.pos, ct_me);
	if (dm <= c.reach + CT_NEAR)
	{
		ct_near.push_back(static_cast<std::int32_t>(ct_list.size()));
		if (dm <= c.reach + 1)
			ct_near1.push_back(static_cast<std::int32_t>(ct_list.size()));
	}
	ct_list.push_back({ c.pos, c.reach, c.str, c.group, -1, -1 });
}
// The visible awake attackers, then the remembered ones. TICK: a fuel check every 16 entries; an unarmed turn runs the plain copy.
template <bool TICK> NOVA_INLINE void camp_threat_fill()
{
	for (const auto& vc : W.camps)
	{
		if (!vc.awake)
			continue;
		const auto& c = M.camps[static_cast<std::size_t>(vc.ci)];
		if (!c.attacks())
			continue;
		if (TICK)
			AF_TICK(ct_list.size());
		camp_threat_add(c);
	}
	for (const auto& m : awake_mem)
	{
		if (m.round == W.round) // v699 RCB bit 16 AWM1: skip only camps in sight now
			continue;
		if (TICK)
			AF_TICK(ct_list.size());
		camp_threat_add(M.camps[static_cast<std::size_t>(m.ci)]);
	}
}
__attribute__((noinline)) void camp_threat_build()
{
	AF_CHECK();
	ct_list.clear();
	ct_near.clear();
	ct_near1.clear();
	ct_me = W.me.pos;
	if (af_armed)
		camp_threat_fill<true>();
	else
		camp_threat_fill<false>();
	ct_round = W.round;
	ct_built = ct_ver;
	ct_ps = fg::pstamp;
	++ct_stamp;
}
NOVA_INLINE const std::vector<CtEntry>& camp_threat_entries() // Inlined: the memo test runs about 20k times a game.
{
	if (ct_round != W.round || ct_built != ct_ver || (ct_ps != fg::pstamp)) // A mid-turn perceive changed W's bodies and camps.
		camp_threat_build();
	return ct_list;
}
} // namespace
__attribute__((always_inline)) float camp_threat(vec2 p, int ignore_group)
{
	camp_threat_entries();
	if (ct_list.empty())
		return 0; // F4: no entry adds anything (the memo would hold 0)
	auto& mm = ct_memo[static_cast<std::size_t>((p.x * 7 + p.y * 13 + ignore_group * 5) & 63)];
	float total = 0;
	if (mm.stamp == ct_stamp && mm.p == p && mm.ig == ignore_group)
		total = mm.v;
	else
	{
		auto one = [&](CtEntry& e)
		{
			if (e.group == ignore_group)
				return;
			const int d = cheb(p, e.pos);
			if (d > e.reach)
				return;
			if (e.dmin < 0)
				camp_threat_other_bodies(e);
			if (d > e.dmin || d == e.dtie)
				return;
			total += e.str;
		};
		const int dq = cheb(p, ct_me);
		if (dq <= 1)
			for (const std::int32_t i : ct_near1)
				one(ct_list[static_cast<std::size_t>(i)]);
		else if (dq <= CT_NEAR)
			for (const std::int32_t i : ct_near)
				one(ct_list[static_cast<std::size_t>(i)]);
		else
			for (auto& e : ct_list)
				one(e);
		mm = { p, ignore_group, ct_stamp, total };
	}
	return total * mu::ct_k; // The camps' hits on me x Durability .9 x Jungle .7 (1 when off).
}
bool camp_tie_with(vec2 q)
{
	camp_threat_entries();
	for (const auto& e : ct_list)
	{
		const int d = cheb(W.me.pos, e.pos);
		if (d > e.reach || cheb(q, e.pos) != d)
			continue;
		bool nearer = false;
		for (const auto& b : W.allies)
			nearer = nearer || (b.pos != q && cheb(b.pos, e.pos) < d);
		for (const auto& b : W.enemies)
			nearer = nearer || cheb(b.pos, e.pos) < d;
		if (!nearer)
			return true;
	}
	return false;
}
} // namespace nova::mv
