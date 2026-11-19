// move_escape.cc: Escapes: out of reach, priced, nearest safe tile, ring, toward a rally.
#include "move_internal.h"
namespace nova::mv {
int escape_steps(const std::vector<Threat>& threats, vec2 p)
{
	int s = 0;
	for (const auto& t : threats)
		s = std::max(s, t.reach - cheb(p, t.pos) + 1);
	return s;
}
// The field from the nearest free tile within win of me outside the danger board, searched to `search` steps. A mate's tile that is
// not next to me counts as open (it moves). False: no such tile.
static bool escape_exit_field(const bitboard& danger, int win, int search, distance_field& f, bitboard& walls)
{
	const vec2 me = W.me.pos;
	walls = dynamic_walls();
	for (const auto& al : W.allies)
		if (inb(al.pos) && cheb(al.pos, me) > 1)
			bbset(walls, al.pos, false);
	bbset(walls, me, false);
	bitboard goals;
	goals.draw_chebyshev(me, static_cast<float>(win));
	goals &= ~danger;
	goals &= ~walls;
	if (!bbany_simd_move(goals))
		return false;
	bitboard dest;
	bbset(dest, me);
	bitboard visited;
	f.compute_to(walls, goals, dest, visited, static_cast<std::uint16_t>(search));
	return true;
}
// The field to the nearest free tile outside every listed reach and every awake camp's reach. False: no such tile.
static bool safe_tile_field(const std::vector<Threat>& threats, distance_field& f, bitboard& walls, bitboard& danger)
{
	const vec2 me = W.me.pos;
	for (const auto& t : threats)
		if (t.reach >= 0)
			danger.draw_chebyshev(t.pos, static_cast<float>(t.reach));
	for (const auto& e : camp_threat_entries())
		if (e.reach >= 0 && e.str > 0 && cheb(e.pos, me) <= PX_LIMIT + e.reach)
			danger.draw_chebyshev(e.pos, static_cast<float>(e.reach));
	return escape_exit_field(danger, PX_LIMIT, PX_LIMIT, f, walls);
}
int safe_tile_walk_steps(const std::vector<Threat>& threats)
{
	if (fuel() < RE_FUEL_MIN)
		return 0;
	static int cr = -1, cs = 0; // a standing Prism asks every round: once a round is enough
	static vec2 cp{ -1, -1 };
	if (cr == W.round && cp == W.me.pos)
		return cs;
	distance_field f;
	bitboard walls, danger;
	cs = 99;
	if (safe_tile_field(threats, f, walls, danger) && dfget_me(f) != UNREACH)
		cs = static_cast<int>(dfget_me(f));
	cr = W.round;
	cp = W.me.pos;
	return cs;
}
bool escape_to_safe_tile(const std::vector<Threat>& threats)
{
	if (!W.can_move() || fuel() < RE_FUEL_MIN)
		return false;
	const vec2 me = W.me.pos;
	distance_field f;
	bitboard walls, danger;
	if (!safe_tile_field(threats, f, walls, danger))
		return false;
	const std::uint16_t cur = dfget(f, me);
	return cur != UNREACH && descend(f, walls, danger, cur);
}
// ======== Priced escape ======== Cheap priced escape. Call only with the bit set. Lazy per-call window state (stamps, no per-call
// clears), static boards and field (nothing calls it from inside), A* bounded by the host field from the goals.
namespace {
// b1839 EPW1: the A*'s work limit from the fuel left, clamp((fuel - EPW_F0) / EPW_DIV, TCF_EP9W, EPW_MAX).
__attribute__((noinline)) int epw_work_limit()
{
	const long w = (fuel() - static_cast<long>(EPW_TAB[2])) / std::max(1, static_cast<int>(EPW_TAB[3]));
	return static_cast<int>(std::clamp<long>(w, static_cast<long>(TCF_TAB[3]), static_cast<long>(EPW_TAB[4])));
}
constexpr int EP9_R = 7, EP9_S = 2 * EP9_R + 3, EP9_N = EP9_S * EP9_S, EP9_QMAX = 15, EP9_CMAX = 16 * 24, EP9_POPS = 600;
int ep9_stamp = 0;
int ep9_hst[EP9_N], ep9_hit[EP9_N], ep9_tst[EP9_N], ep9_hv[EP9_N], ep9_q[EP9_N], ep9_cst[EP9_N], ep9_cost[EP9_N], ep9_dmg[EP9_N],
	ep9_stp[EP9_N], ep9_par[EP9_N], ep9_headst[EP9_CMAX + 1], ep9_head[EP9_CMAX + 1], ep9_enode[EP9_N * 8 + 8],
	ep9_enext[EP9_N * 8 + 8];
unsigned char ep9_flags[EP9_N]; // 1 blocked, 2 goal
// b1976 XFE bit 8 EOF1 (RC X425): the window offsets of DIRS as constants (no per-call array).
constexpr std::array<int, 8> EP9_OFF = [] {
	std::array<int, 8> o{};
	for (int k = 0; k < 8; ++k)
		o[static_cast<std::size_t>(k)] = DIRS[static_cast<std::size_t>(k)].x * EP9_S + DIRS[static_cast<std::size_t>(k)].y;
	return o;
}();
} // namespace
namespace {
struct Ep9Camp
{
	vec2 pos;
	int reach, h, dmin, dtie;
};
Ep9Camp ep9_camps[32];
// The awake camps that can hit inside the window, with their hit on me and body distances. Returns the count.
NOVA_INLINE int escape_fill_camps(vec2 me)
{
	int n = 0;
	const float epk = 1.0f; // What lands on me.
	for (auto& e : ct_list)
	{
		if (e.reach < 0 || cheb(e.pos, me) > EP9_R + e.reach || n >= 32)
			continue;
		const int h = static_cast<int>(e.str * epk + 0.5f);
		if (h <= 0)
			continue;
		if (e.dmin < 0)
			camp_threat_other_bodies(e);
		ep9_camps[n++] = { e.pos, e.reach, h, e.dmin, e.dtie };
	}
	return n;
}
// One priced search: window tiles are read on first touch (stamps, no per-call clears). Members are all inlined into priced_escape.
struct Ep9Run
{
	const vec2 me;
	const int st, ncamp, i0, sw;
	const bitboard& goals;
	const bitboard& dw;
	const distance_field& f;
	int off[8];
	int ne = 0, pops = 0;
	int xf = 0, hi = -1; // b1976 XFE: the flag word (read once per call), EBS2's highest bucket pushed
	NOVA_INLINE vec2 tile(int i) const { return vec2{ me.x + i / EP9_S - EP9_R - 1, me.y + i % EP9_S - EP9_R - 1 }; }
	// hit on window tile i: the strength of awake camps that would hit me there (camp_threat's nearest-body rule).
	NOVA_INLINE int hit(int i) const
	{
		if (ep9_hst[i] == st)
			return ep9_hit[i];
		ep9_hst[i] = st;
		const vec2 p = tile(i);
		int v = 0;
		for (int k = 0; k < ncamp; ++k)
		{
			const int d = cheb(p, ep9_camps[k].pos);
			if (d <= ep9_camps[k].reach && d <= ep9_camps[k].dmin && d != ep9_camps[k].dtie)
				v += ep9_camps[k].h;
		}
		ep9_hit[i] = v;
		return v;
	}
	// Window tile i: blocked (padding, off board, wall), goal, field value, step weight.
	NOVA_INLINE unsigned char look(int i) const
	{
		if (ep9_tst[i] == st)
			return ep9_flags[i];
		ep9_tst[i] = st;
		ep9_cst[i] = 0;
		const int x = i / EP9_S - EP9_R - 1, y = i % EP9_S - EP9_R - 1;
		const vec2 p{ me.x + x, me.y + y };
		unsigned char fl = 0;
		if (x < -EP9_R || x > EP9_R || y < -EP9_R || y > EP9_R || !inb(p) || (i != i0 && bbget(dw, p)))
			fl = 1;
		else
		{
			if (i != i0 && bbget(goals, p))
				fl = 2;
			const std::uint16_t v = dfget(f, p);
			ep9_hv[i] = v == UNREACH ? 1000 : static_cast<int>(v);
			if ((xf & 2) == 0) // b1976 XFE bit 2 SWL1: q from hit() only on a relaxed step (hit is memoised per stamp)
				ep9_q[i] = std::min(EP9_QMAX, hit(i) / sw); // XFE_BITS bit 2 off
		}
		ep9_flags[i] = fl;
		return fl;
	}
	// The damage of the shortest walk, steering by the field; -1: it leaves the window.
	NOVA_INLINE int shortest_walk_damage(int dstar) const
	{
		int sdmg = 0, t = i0;
		for (int s = dstar; s > 0; --s)
		{
			int bj = -1;
			for (int k = 0; k < 8; ++k)
			{
				const int j = t + ((xf & 8) != 0 ? EP9_OFF[static_cast<std::size_t>(k)] : off[k]); // XFE_BITS bit 8
				if ((look(j) & 1) != 0 || ep9_hv[j] != s - 1)
					continue;
				if (bj < 0 || hit(j) < hit(bj))
					bj = j;
			}
			if (bj < 0)
				return -1;
			sdmg += hit(bj);
			t = bj;
		}
		return sdmg;
	}
	NOVA_INLINE void push(int j, int pr)
	{
		if (ep9_headst[pr] != st)
		{
			ep9_headst[pr] = st;
			ep9_head[pr] = -1;
		}
		if ((xf & 1) != 0 && pr > hi) // b1976 XFE bit 1 EBS2
			hi = pr;
		ep9_enode[ne] = j;
		ep9_enext[ne] = ep9_head[pr];
		ep9_head[pr] = ne++;
	}
	// A* on cost 1 + q per step; the field value is a lower bound on the steps left (each step costs >= 1), and prunes walks longer
	// than dstar + EP9_LONGER. Returns the goal tile reached, -1 for none.
	NOVA_INLINE int search(int dstar, int sdmg)
	{
		const int lim = dstar + tune::EP9_LONGER;
		const int epw_w = epw_work_limit(); // v7xx EPW1
		look(i0);
		ep9_cst[i0] = 1;
		ep9_cost[i0] = 0;
		ep9_dmg[i0] = 0;
		ep9_stp[i0] = 0;
		ep9_par[i0] = -1;
		push(i0, ep9_hv[i0]);
		int best = -1;
		// b1976 XFE bit 1 EBS2 (RC X425): buckets above the highest one pushed this stamp hold nothing, so the scan stops there.
		for (int c = ep9_hv[i0]; c <= ((xf & 1) != 0 ? hi : EP9_CMAX) && best < 0 && pops < EP9_POPS; ++c) // XFE_BITS bit 1
		{
			if (ep9_headst[c] != st)
				continue;
			while (ep9_head[c] >= 0) // pop from the head: a step with q 0 toward the goals pushes into this same bucket
			{
				const int e = ep9_head[c];
				ep9_head[c] = ep9_enext[e];
				const int t = ep9_enode[e];
				if (ep9_cost[t] + ep9_hv[t] != c)
					continue;
				if (++pops > EP9_POPS || ((pops & 15) == 0 && (pops * (TCF_TAB[5] + ncamp) > (epw_w)))) // Stops on a work count (EPW1: fuel-scaled).
					return -1; // bounded: at most about 35k fuel a call
				if ((ep9_flags[t] & 2) != 0)
				{
					best = t;
					break;
				}
				if (ep9_dmg[t] >= sdmg)
					continue; // Can no longer save anything: skip it.
				const int ns = ep9_stp[t] + 1;
				for (int k = 0; k < 8; ++k)
				{
					const int j = t + ((xf & 8) != 0 ? EP9_OFF[static_cast<std::size_t>(k)] : off[k]); // XFE_BITS bit 8
					if ((look(j) & 1) != 0 || ns + ep9_hv[j] > lim)
						continue;
					const int hj = (xf & 2) != 0 ? hit(j) : 0;
					const int nc = ep9_cost[t] + 1 + ((xf & 2) != 0 ? std::min(EP9_QMAX, hj / sw) : ep9_q[j]); // XFE_BITS bit 2
					const int pr = nc + ep9_hv[j];
					if (pr > EP9_CMAX || (ep9_cst[j] != 0 && ep9_cost[j] <= nc) || ne >= EP9_N * 8 + 8)
						continue;
					ep9_cst[j] = 1;
					ep9_cost[j] = nc;
					ep9_dmg[j] = ep9_dmg[t] + ((xf & 2) != 0 ? hj : hit(j)); // XFE_BITS bit 2
					ep9_stp[j] = ns;
					ep9_par[j] = t;
					push(j, pr);
				}
			}
		}
		return best;
	}
};
} // namespace

__attribute__((noinline)) bool priced_escape(const bitboard& goals)
{
	if (fuel() < tune::EP9_MIN_FUEL || avoid_on)
		return false;
	const vec2 me = W.me.pos;
	camp_threat_entries();
	if (ct_list.size() < 2)
		return false;
	const int ncamp = escape_fill_camps(me);
	if (ncamp < 2)
		return false;
	const int st = ++ep9_stamp;
	const int sw = std::max(1, static_cast<int>(W.me.maxhp / tune::EP9_STEP_SHARE));
	const int need = std::max(1, static_cast<int>(W.me.maxhp / tune::EP9_SAVE_SHARE));
	const bitboard& dw = dynamic_walls();
	// The shortest walk: a host field from the goals (walls as step_to_set), far enough to bound walks a few steps longer.
	static bitboard ep_walls, ep_vis;
	static distance_field ep_f;
	bb3_or(dw, dw, ep_walls); // One host call.
	bbset(ep_walls, me, false);
	ep_vis.clear();
	ep_f.compute(ep_walls, goals, ep_vis, static_cast<std::uint16_t>(tune::EP9_FIELD_R));
	const std::uint16_t cur = dfget(ep_f, me);
	if (cur == UNREACH || cur == 0)
		return false;
	const int dstar = cur;
	Ep9Run run{ me, st, ncamp, (EP9_R + 1) * EP9_S + (EP9_R + 1), sw, goals, dw, ep_f, {} };
	run.xf = XFE_TAB[1]; // b1976 XFE (0 = live)
	int k8 = 0;
#pragma clang loop unroll(full)
	for (const vec2 d : DIRS)
		if (k8 < 8)
			run.off[k8++] = d.x * EP9_S + d.y;
	const int sdmg = run.shortest_walk_damage(dstar);
	if (sdmg < need) // (-1 too) nothing to save: the shortest walk is already cheap, or it leaves the window
		return false;
	const int best = run.search(dstar, sdmg);
	if (best < 0 || sdmg - ep9_dmg[best] < need)
		return false;
	const int i0 = run.i0;
	int first = best;
	while (ep9_par[first] != i0 && ep9_par[first] >= 0)
		first = ep9_par[first];
	if (ep9_par[first] != i0)
		return false;
	CandList cands;
	cands.push_back({ run.tile(first), 0 });
	return move_best(cands);
}
// b1761 FD1P bit 1: priced_escape with the foe champions' zones priced too (costs, not walls).
__attribute__((noinline)) bool priced_escape_fd1p(const bitboard& goals, const std::vector<Threat>& threats)
{
	if (fuel() < tune::EP9_MIN_FUEL || avoid_on)
		return false;
	const vec2 me = W.me.pos;
	camp_threat_entries();
	int ncamp = escape_fill_camps(me);
	const int ncamp0 = ncamp;
	for (const auto& t : threats)
	{
		if (t.reach < 0 || ncamp >= 32 || cheb(t.pos, me) > EP9_R + t.reach)
			continue;
		int h = 0;
		for (std::size_t q = 0; q < W.enemies.size(); ++q)
			if (W.enemies[q].pos == t.pos)
			{
				h = static_cast<int>(nova::combat::foe_of(W.enemies[q], static_cast<int>(q)).burst + 0.5f);
				break;
			}
		if (h > 0)
			ep9_camps[ncamp++] = { t.pos, t.reach, h, 1 << 20, -1 };
	}
	if (ncamp == ncamp0)
		return false; // no foe champion priced: today's path
	const int st = ++ep9_stamp;
	const int sw = std::max(1, static_cast<int>(W.me.maxhp / tune::EP9_STEP_SHARE));
	const int need = std::max(1, static_cast<int>(W.me.maxhp / tune::EP9_SAVE_SHARE));
	const bitboard& dw = dynamic_walls();
	// The shortest walk: a host field from the goals (walls as step_to_set), far enough to bound walks a few steps longer.
	static bitboard ep_walls, ep_vis;
	static distance_field ep_f;
	bb3_or(dw, dw, ep_walls); // One host call.
	bbset(ep_walls, me, false);
	ep_vis.clear();
	ep_f.compute(ep_walls, goals, ep_vis, static_cast<std::uint16_t>(tune::EP9_FIELD_R));
	const std::uint16_t cur = dfget(ep_f, me);
	if (cur == UNREACH || cur == 0)
		return false;
	const int dstar = cur;
	Ep9Run run{ me, st, ncamp, (EP9_R + 1) * EP9_S + (EP9_R + 1), sw, goals, dw, ep_f, {} };
	run.xf = XFE_TAB[1]; // b1976 XFE (0 = live)
	int k8 = 0;
#pragma clang loop unroll(full)
	for (const vec2 d : DIRS)
		if (k8 < 8)
			run.off[k8++] = d.x * EP9_S + d.y;
	const int sdmg = run.shortest_walk_damage(dstar);
	if (sdmg < need) // (-1 too) nothing to save: the shortest walk is already cheap, or it leaves the window
		return false;
	const int best = run.search(dstar, sdmg);
	if (best < 0 || sdmg - ep9_dmg[best] < need)
		return false;
	const int i0 = run.i0;
	int first = best;
	while (ep9_par[first] != i0 && ep9_par[first] >= 0)
		first = ep9_par[first];
	if (ep9_par[first] != i0)
		return false;
	CandList cands;
	cands.push_back({ run.tile(first), 0 });
	return move_best(cands);
}
// ======== Escape: to the nearest safe tile ========
bool eox_escaping = false;
namespace {
struct EoxEsc // Escape's own steps are never refused by the keep-out test.
{
	bool set = false;
	EoxEsc()
	{
		if (!eox_escaping)
			set = eox_escaping = true;
	}
	~EoxEsc()
	{
		if (set)
			eox_escaping = false;
	}
};
} // namespace
// Free tiles within tune::ESC_WIN outside every threat's reach, with whole-board operations (a per-tile scan of the 13x13 window
// cost tens of thousands of fuel).
NOVA_INLINE void escape_goal_tiles(const std::vector<Threat>& threats, bitboard& goals)
{
	const vec2 me = W.me.pos;
	bitboard danger;
	for (const auto& th : threats)
		if (th.reach >= 0 && (cheb(th.pos, me) <= tune::ESC_WIN + th.reach))
			danger.draw_chebyshev(th.pos, static_cast<float>(th.reach)); // review i2: reach -1 (a remembered foe gone 3+ rounds) throws
	AF_CHECK();
	goals.draw_chebyshev(me, static_cast<float>(tune::ESC_WIN));
	goals &= ~danger;
	goals &= ~dynamic_walls();
}
static std::vector<vec2> threat_tiles(const std::vector<Threat>& threats)
{
	std::vector<vec2> pts;
	for (const auto& th : threats)
		pts.push_back(th.pos);
	return pts;
}
bool escape(const std::vector<Threat>& threats)
{
	const EoxEsc eox_esc;
	AF_CHECK();
	if (!W.can_move() || threats.empty())
		return false;
	// review i2 (from planner c4): late in a turn, only the cheap step away. A flee escape, the low-HP go-home scan
	// and the end-of-turn camp escape can all run in one turn (two features, each with its own whole-board work).
	if (fuel() < tune::ESC_MIN_FUEL)
		return fuel() > tune::ESC_AWAY_FUEL && step_away(threat_tiles(threats));
	bitboard goals;
	escape_goal_tiles(threats, goals);
	const bool any = bbany_simd_move(goals);
	PROF("esc_scan");
	if (any && priced_escape(goals))
	{
		PROF("esc_priced");
		return true;
	}
	if (any && step_to_set(goals, tune::ESC_SEARCH))
	{
		PROF("esc_step");
		return true;
	}
	PROF("esc_nostep");
	if (prism_layer::exit_rule() && W.me.gems > 0 && escape_to_safe_tile(threats))
		return true;
	if (M.ring && ring_escape())
		return true; // step_away from a ring walks to its centre; escape out of it instead.
	const bool r = step_away(threat_tiles(threats));
	PROF("esc_away");
	return r;
}

// ======== Ring escape ======== escape() found no safe tile within 6 it can walk to (inside an altar's awake camp ring every tile
// within 6 is in reach, so step_away would take the body to the centre and it would stand there, beside a dead-camp gap that leads
// out). With >= RE_MIN_CAMPS awake camps reaching me: the nearest tile out of every awake camp's reach within RE_WIN, the path
// allowed through the reach (the shortest walk takes the fewest hits) and over a mate's tile that is not next to me (it moves). True
// if I moved. ring_hit_k: a camp's strength as it lands on me.
NOVA_INLINE float ring_hit_k() { return 1.0f; }

int ring_in(int skip_group, float& str)
{
	int n = 0;
	str = 0;
	const float rgk = ring_hit_k();
	for (const auto& e : camp_threat_entries())
		if (e.reach >= 0 && e.group != skip_group && cheb(e.pos, W.me.pos) <= e.reach)
		{
			++n;
			str += e.str * rgk;
		}
	return n;
}

bool ring_escape()
{
	if (!W.can_move() || fuel() < RE_FUEL_MIN)
		return false;
	const vec2 me = W.me.pos;
	// One pass over the awake-camp list, no copies (a copied threat list cost 5-25k beside packs).
	bitboard danger;
	int in = 0;
	for (const auto& e : camp_threat_entries())
	{
		if (e.reach < 0)
			continue;
		const int d = cheb(e.pos, me);
		if (d > RE_WIN + e.reach)
			continue;
		danger.draw_chebyshev(e.pos, static_cast<float>(e.reach));
		in += d <= e.reach ? 1 : 0;
	}
	if (in < RE_MIN_CAMPS)
		return false;
	AF_CHECK();
	bitboard walls;
	distance_field f;
	if (!escape_exit_field(danger, RE_WIN, fuel() > tune::RE_NEAR_FUEL ? RE_SEARCH : tune::RE_NEAR_SEARCH, f, walls))
		return false;
	const std::uint16_t cur = dfget(f, me);
	PROF("ring_esc");
	return cur != UNREACH && descend(f, walls, danger, cur);
}
// ======== Escape toward a rally ======== A rally at home narrows `near` to the window's tiles that are a shorter walk home than
// mine, if any.
NOVA_INLINE void rally_home_narrow_near(vec2 me, bitboard& near)
{
	const std::uint16_t dm = dfget(M.f_home, me);
	if (dm == UNREACH)
		return;
	bitboard wc;
	bool anyw = false;
	const FView fvh = fview(M.f_home); // dfget's view made once for the 13x13 scan.
	for (int y = std::max(0, me.y - tune::ESC_WIN); y <= std::min(G.h - 1, me.y + tune::ESC_WIN); ++y)
		for (int x = std::max(0, me.x - tune::ESC_WIN); x <= std::min(G.w - 1, me.x + tune::ESC_WIN); ++x)
		{
			const vec2 p{ x, y };
			const std::uint16_t d = fvh(p);
			if (d != UNREACH && d < dm)
			{
				bbset(wc, p);
				anyw = true;
			}
		}
	if (anyw)
		near = wc;
}

// b2046 XDE RHN1 (X351): rally_home_narrow_near + `goals &= near` in one pass over the goal bits. With 0 < dm < UNREACH my tile's BFS
// predecessor (f_home is a plain BFS from my spawn) is a window tile with d < dm, so the scan's `anyw` holds and near = {window tiles,
// d < dm}; goals lie inside the ESC_WIN window (escape_goal_tiles), so goals & near = the goal tiles with d < dm. Same bit index in a
// board word and a field chunk. False (nothing done): dm 0 or UNREACH, where near stays the rally disk.
NOVA_INLINE bool rhn_filter_goals(vec2 me, bitboard& goals)
{
	const std::uint16_t dm = dfget(M.f_home, me);
	if (dm == UNREACH || dm == 0)
		return false;
	std::uint64_t* const w = goals.ptr();
	const std::uint16_t* const fp = fview(M.f_home).p;
	const int cx0 = std::max(0, me.x - tune::ESC_WIN) >> 3, cx1 = std::min(G.w - 1, me.x + tune::ESC_WIN) >> 3;
	const int cy0 = std::max(0, me.y - tune::ESC_WIN) >> 3, cy1 = std::min(G.h - 1, me.y + tune::ESC_WIN) >> 3;
	for (int cy = cy0; cy <= cy1; ++cy)
		for (int cx = cx0; cx <= cx1; ++cx)
		{
			std::uint64_t& word = w[cy * G.stride + cx];
			std::uint64_t m = word;
			if (!m)
				continue;
			const std::uint16_t* const base = fp + (cy * G.cw + cx) * 64;
			std::uint64_t keep = m;
			while (m)
			{
				const int b = __builtin_ctzll(m);
				m &= m - 1;
				if (base[b] >= dm)
					keep &= ~(std::uint64_t{ 1 } << b);
			}
			word = keep;
		}
	return true;
}
// The escape step of a retreat goes to the nearest safe tile within 6 that is no farther from the rally point (the nearest ally,
// else home) than I am now, so a retreat never walks away from the team; plain escape() when no such tile exists or fuel is short.
bool escape_toward(const std::vector<Threat>& threats, vec2 rally)
{
	const EoxEsc eox_esc;
	AF_CHECK();
	if (rally.x < 0 || !W.can_move() || threats.empty() || fuel() < tune::ESC_RALLY_FUEL)
		return escape(threats);
	const vec2 me = W.me.pos;
	bitboard goals;
	escape_goal_tiles(threats, goals);
	if (!(M.has_home && cheb(rally, M.home_anchor) <= 2 && rhn_filter_goals(me, goals))) // b2046 XDE RHN1
	{
		bitboard near;
		near.draw_chebyshev(rally, static_cast<float>(std::max(1, cheb(me, rally))));
		if (M.has_home && cheb(rally, M.home_anchor) <= 2)
			rally_home_narrow_near(me, near);
		goals &= near;
	}
	if (bbany_simd_move(goals) && priced_escape_fd1p(goals, threats)) // b1761 FD1P bit 1
		return true;
	if (bbany_simd_move(goals) && step_to_set(goals, tune::ESC_SEARCH))
		return true;
	return escape(threats);
}
} // namespace nova::mv
