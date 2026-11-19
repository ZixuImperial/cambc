// move_dash_blocks.cc: Launch tiles and corridors blocked for dashes.
#include "move_internal.h"
namespace nova::mv {
bool launch_tile(vec2 p)
{
	if (!M.has_home || !inb(p))
		return false;
	static vec2 memo_p{ -1, -1 }; // the answer for the last tile asked (idle bodies ask for the same tile each turn)
	static bool memo_v = false;
	if (p == memo_p)
		return memo_v;
	memo_p = p;
	memo_v = false;
	const FView vh = fview(M.f_home);
	const bool hp = vh(p) != UNREACH;
	for (int dx = -2; dx <= 2; ++dx)
		for (int dy = -2; dy <= 2; ++dy)
		{
			if (std::max(iabs(dx), iabs(dy)) != 2)
				continue;
			const vec2 u{ p.x + dx, p.y + dy };
			if (!inb(u) || bbget(M.block_camps, u) || (vh(u) != UNREACH) == hp)
				continue;
			if (dash_mid_ok(p, u))
				return memo_v = true;
		}
	return false;
}
int open_neighbour_count(vec2 p)
{
	int n = 0;
#pragma clang loop unroll(full)
	for (const vec2 d : DIRS)
	{
		const vec2 q = p + d;
		if (inb(q) && !bbget(M.block_camps, q))
			++n;
	}
	return n;
}
bool unpark()
{
	if (!W.can_move() || !M.has_home)
		return false;
	// On a big map with many launch tiles (01islands) one try costs up to ~8k.
	static int last_try = -100;
	if (W.round - last_try < tune::UNPARK_EVERY)
		return false;
	last_try = W.round;
	const vec2 me = W.me.pos;
	const FView vh = fview(M.f_home);
	const std::uint16_t here = vh(me);
	CandList cands;
#pragma clang loop unroll(full)
	for (const vec2 d : DIRS)
	{
		const vec2 n = me + d;
		if (!free_tile(n))
			continue;
		const std::uint16_t v = vh(n);
		// A corridor tile only on the way home (out of a corridor that ends at a launch tile).
		const bool homeward = here != UNREACH && v != UNREACH && v < here;
		const int open = open_neighbour_count(n);
		if (open <= tune::CORRIDOR_OPEN && !homeward)
			continue;
		cands.push_back({ n, (open <= tune::CORRIDOR_OPEN ? 100 : 0) - 8 * open - (homeward ? 16 : 0) });
	}
	std::sort(cands.begin(), cands.end(), [](const Cand& a, const Cand& b) { return a.score < b.score; });
	// Another launch tile only on the way home; test the best few only.
	int tested = 0;
	for (const auto& c : cands)
	{
		if (tested++ >= tune::UNPARK_TESTS)
			break;
		const std::uint16_t v = vh(c.p);
		if (launch_tile(c.p) && !(here != UNREACH && v != UNREACH && v < here))
			continue;
		if (camp_threat(c.p) > 0)
			continue;
		if (try_move(c.p))
			return true;
	}
	return false;
}

} // namespace nova::mv
namespace nova::combat {
namespace kit_rules {
static bool same_bush_cluster(vec2 a, vec2 b)
{
	constexpr int CAP = 48;
	alignas(vec2) unsigned char sbc_raw[CAP * sizeof(vec2)]; // FB5 SBC1: only q[0, n) is read, each written first
	vec2* q = reinterpret_cast<vec2*>(sbc_raw);
	int n = 1;
	q[0] = a;
	for (int i = 0; i < n; ++i)
		for (const vec2 d : { vec2{ 1, 0 }, vec2{ -1, 0 }, vec2{ 0, 1 }, vec2{ 0, -1 } })
		{
			const vec2 p = q[i] + d;
			if (!inb(p) || !bbget(M.bushes, p))
				continue;
			if (p == b)
				return true;
			bool seen = false;
			for (int k = 0; k < n && !seen; ++k)
				seen = q[k] == p;
			if (seen)
				continue;
			if (n == CAP)
				return true;
			q[n++] = p;
		}
	return false;
}
} // namespace kit_rules
namespace geom {
namespace {
// The engine's dash path from a to t as measured: one step is free;
// a 2-step dash needs a middle next to both ends that is not a wall, a living camp (visible, or a camp tile I can't see) or a visible
// enemy champion. Holes, altars, allies and dead camp tiles pass.
// the blocked middles once per perceive; the same answer as the per-tile tests it replaces.
static int bh65_bm_r = -1, bh65_bm_ps = -1, bh65_bm_sp = -1;
static int bh81_bm_at = 0; // the mask was built after my attack
// The unseen camp tiles in bushes, and whether a and b are in one cardinal bush cluster (a walk of the cluster, run only with a
// launch tile in a bush next to such a tile). A cluster past the walk's cap counts as one.
static bitboard au2_ub;
} // namespace
} // namespace geom
// The engine's dash path from a to t (a dash the engine accepts); defined here because the dash steps of mv call it.
bool dash_legal_between(vec2 a, vec2 t)
{
	if (cheb(a, t) <= 1)
		return true;
	static bitboard bh65_bm;
	const int sp = 1;
	const int bgk = 0;
	if (geom::bh65_bm_r != W.round || geom::bh65_bm_ps != fg::pstamp || geom::bh65_bm_sp != sp || geom::bh81_bm_at != bgk)
	{
		geom::bh81_bm_at = bgk;
		geom::bh65_bm_r = W.round;
		geom::bh65_bm_ps = fg::pstamp;
		geom::bh65_bm_sp = sp;
		static bitboard dlb_ctb{ cambc::uninitialized }, dlb_ctn{ cambc::uninitialized }, dlb_ws{ cambc::uninitialized }, dlb_nv{ cambc::uninitialized };
		static bool dlb_st = false; // the static boards, once the analysis is done (camp tiles, bushes, walls, spawn are final)
		if (!dlb_st && M.done())
		{
			bb3_and(M.camp_tiles, M.bushes, dlb_ctb);  // camp tiles in bushes
			bb3_xor(M.camp_tiles, dlb_ctb, dlb_ctn);   // camp tiles outside bushes
			bb3_or(M.walls, M.enemy_spawn, dlb_ws);
			dlb_st = true;
		}
		if (dlb_st)
		{
			nchk(cambc::detail::sdk_Bitboard_Not(W.vis.ptr(), dlb_nv.ptr()));
			bb3_and(dlb_ctb, dlb_nv, geom::au2_ub); // unseen camp tiles in bushes
			bb3_and(dlb_ctn, dlb_nv, bh65_bm);      // unseen camp tiles outside bushes
			bb3_or(bh65_bm, dlb_ws, bh65_bm);
			bb3_or(bh65_bm, W.occ_camps, bh65_bm);
		}
		else
		{
			bb3_and(M.camp_tiles, W.vis, bh65_bm);   // camp tiles in sight
			bb3_xor(M.camp_tiles, bh65_bm, bh65_bm); // camp tiles out of sight
			bb3_and(bh65_bm, M.bushes, geom::au2_ub);
			bb3_xor(bh65_bm, geom::au2_ub, bh65_bm);
			bb3_or(bh65_bm, M.walls, bh65_bm);
			bb3_or(bh65_bm, W.occ_camps, bh65_bm);
			bb3_or(bh65_bm, M.enemy_spawn, bh65_bm);
		}
		static bitboard bh81_oc{ cambc::uninitialized };
		for (const auto& e : W.enemies)
			if (inb(e.pos))
				bbset(bh65_bm, e.pos);
			else
				BH81_CNT(9, inb(e.pos));
		static bitboard au2_tp{ cambc::uninitialized };
		if (cambc::detail::sdk_teleport_occupancy(au2_tp.ptr()) == 0)
			bb3_or(bh65_bm, au2_tp, bh65_bm);
	}
	const int x0 = std::max(-1, t.x - a.x - 1), x1 = std::min(1, t.x - a.x + 1);
	const int y0 = std::max(-1, t.y - a.y - 1), y1 = std::min(1, t.y - a.y + 1);
	for (int mx = x0; mx <= x1; ++mx)
		for (int my = y0; my <= y1; ++my)
		{
			const vec2 m{ a.x + mx, a.y + my };
			if ((mx == 0 && my == 0) || !inb(m) || cheb(m, t) != 1)
				continue;
			if (!bbget(bh65_bm, m) && !(bbget(geom::au2_ub, m) && bbget(M.bushes, a) && kit_rules::same_bush_cluster(a, m))) // seen from a bush of its own cluster
			{
				RULE_AUDIT_FIX_CNT(0, !au2_old_ok(a, t));
				return true;
			}
		}
	RULE_AUDIT_FIX_CNT(1, static_cast<bool>(au2_old_ok(a, t)));
	return false;
}
} // namespace nova::combat
