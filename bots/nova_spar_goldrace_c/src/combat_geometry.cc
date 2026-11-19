// combat_geometry.cc: Tiles, reach, dash legality and danger zones.
#include "combat_internal.h"
namespace nova::combat {
namespace geom
{
namespace tune
{
// a dash landing next to foe f from tile `from`: free, within the dash's reach (a 2-step dash
// needs its midpoint free of walls), next to f (Heart of Ruin: within its landing radius); for a plain dash at most one
// other enemy within 2 of it. (-1, -1): none.
inline constexpr int LAND_CROWD_R = 2; // another foe this near a landing crowds it
// dash_away's landing score: danger * this + home steps (lowest wins).
inline constexpr int DASH_DANGER_WEIGHT = 100;
inline constexpr int HEART_SCAN_R = 2; // a Heart of Ruin landing lies at most this far from me
}
float my_burst(const Body& f, int d) { return burst::my_burst_m(f, d, true); }
static inline int dash_tiles(const Kit& k) { return std::max(1, static_cast<int>(k.dash_range)); }
namespace {
// The dash's path from `from` to t is open (both rules a landing must pass).
static __attribute__((always_inline)) inline bool dash_path_open(vec2 from, vec2 t)
{
	if (cheb(t, from) != 2 && !BGX_ON(2))
		return true;
	return dash_legal_between(from, t);
}
// The landing in a window of offsets from `from` within `need` of f with the fewest other enemies near it; (-1, -1): none. init: the
// initiation dash's landing test too. BY_REACH: a foe crowds a tile it can reach (else one within LAND_CROWD_R), ties the farthest
// from f.
template <bool BY_REACH>
static __attribute__((always_inline)) inline vec2 dash_landing_search(vec2 from, const Body& f, int dx0, int dx1, int dy0, int dy1, int need, bool init, int& best_s)
{
	vec2 best{ -1, -1 };
	best_s = 1 << 30;
	for (int dx = dx0; dx <= dx1; ++dx)
		for (int dy = dy0; dy <= dy1; ++dy)
		{
			const vec2 t{ from.x + dx, from.y + dy };
			if (t == from || !mv::free_tile(t) || cheb(t, f.pos) > need || !dash_path_open(from, t))
				continue;
			if (init && init_dash_landing_bad(t))
				continue;
			int s = 0;
			for (const auto& e : W.enemies)
				if (e.h != f.h && cheb(e.pos, t) <= (BY_REACH ? std::max(1, e.range) + 1 : tune::LAND_CROWD_R))
					++s;
			if (s < best_s || (BY_REACH && s == best_s && cheb(t, f.pos) > cheb(best, f.pos)) || (s == best_s && (!BY_REACH || cheb(t, f.pos) == cheb(best, f.pos)) && msy_before(t, best))) // MSY bit 4: mirrored ties
			{
				best_s = s;
				best = t;
			}
		}
	return best;
}
} // namespace
vec2 landing_from(vec2 from, const Body& f)
{
	const Kit& k = *W.me.kit;
	const int r = dash_tiles(k);
	const int need = k.dash_mod > 0 ? std::max(1, static_cast<int>(k.dash_radius)) : 1;
	// A landing must be within `need` of f, so the window clips to f.pos +- need: the same
	// tiles in the same (dx, dy) order pass the tests (every clipped tile fails cheb(t, f.pos) > need).
	const int dx0 = std::max(-r, f.pos.x - need - from.x);
	const int dx1 = std::min(r, f.pos.x + need - from.x);
	const int dy0 = std::max(-r, f.pos.y - need - from.y);
	const int dy1 = std::min(r, f.pos.y + need - from.y);
	int best_s = 0;
	const vec2 best = dash_landing_search<false>(from, f, dx0, dx1, dy0, dy1, need, false, best_s);
	if (best.x >= 0 && k.dash_mod <= 0 && best_s > 1)
		return { -1, -1 };
	return best;
}
// the free step (next to me) from which a dash lands next to f, for a foe one step beyond the dash.
vec2 dash_step_for(const Body& f)
{
	const int d = cheb(f.pos, W.me.pos);
	for (const vec2 dd : DIRS)
	{
		const vec2 s = W.me.pos + dd;
		if (inb(s) && mv::free_tile(s) && cheb(s, f.pos) == d - 1 && landing_from(s, f).x >= 0)
			return s;
	}
	return { -1, -1 };
}
// The dash's landing: a tile within the dash with f in my range, the fewest other enemies able to reach it; ties the farthest from
// f. init: the initiation dash's landing test too.
static vec2 dash_landing_tile(const Body& f, bool init, int& best_s)
{
	const int r = dash_tiles(*W.me.kit);
	return dash_landing_search<true>(W.me.pos, f, -r, r, -r, r, W.me.range, init, best_s);
}
std::vector<mv::Threat> zones_of(const Assessment& a)
{
	std::vector<mv::Threat> z;
	z.reserve(a.foes.size() + 8);
	for (const auto& f : a.foes)
		z.push_back({ f.pos, f.reach });
	return z;
}
// Awake camps that would hit me where I stand count as a threat too.
void add_camp_zones(std::vector<mv::Threat>& z)
{
	for (const auto& t : mv::camp_threats_near(7))
		z.push_back(t);
}
bool home_close(int steps) { return mv::home_steps(W.me.pos) <= steps; }
namespace {
// How deep tile p lies inside zone t (0 outside).
static __attribute__((always_inline)) inline int dash_depth(const mv::Threat& t, vec2 p)
{
	return std::max(0, t.reach + 1 - cheb(p, t.pos));
}
static __attribute__((always_inline)) inline int dash_danger(const std::vector<mv::Threat>& zs, vec2 p)
{
	int d = 0;
	for (const auto& t : zs)
		d += dash_depth(t, p);
	return d;
}
// True when p's score (danger * weight + hs) is below lim. The sum only grows, so it stops once it reaches the limit.
static __attribute__((always_inline)) inline bool dash_beats(const std::vector<mv::Threat>& zs, vec2 p, int hs, int lim)
{
	if (hs >= lim)
		return false;
	const int cap = (lim - hs + tune::DASH_DANGER_WEIGHT - 1) / tune::DASH_DANGER_WEIGHT; // score < lim  <=>  danger < cap
	int d = 0;
	for (const auto& t : zs)
	{
		d += dash_depth(t, p);
		if (d >= cap)
			return false;
	}
	return true;
}
// A dash from me to t is legal.
static __attribute__((always_inline)) inline bool dash_path_ok(vec2 me, vec2 t)
{
	return (cheb(t, me) == 2 || BGX_ON(2)) ? dash_legal_between(me, t) : true; // v66x PFC bit 2: one legality test
}
// The lowest-scoring landing within r of me that beats staying (danger `now`); x < 0: none.
static __attribute__((always_inline)) inline vec2 dash_landing(const std::vector<mv::Threat>& zs, vec2 me, int r, int now)
{
	vec2 best{ -1, -1 };
	int best_s = now * tune::DASH_DANGER_WEIGHT + mv::home_steps(me);
	for (int dx = -r; dx <= r; ++dx)
	{
		AF_CHECK();
		for (int dy = -r; dy <= r; ++dy)
		{
			const vec2 t{ me.x + dx, me.y + dy };
			if (t == me || !mv::free_tile(t))
				continue;
			const int hs = mv::home_steps(t);
			if (!dash_beats(zs, t, hs, best_s) || !dash_path_ok(me, t)) // the legality tests are the dear part, so they come last
				continue;
			best_s = dash_danger(zs, t) * tune::DASH_DANGER_WEIGHT + hs;
			best = t;
		}
	}
	return best;
}
} // namespace
// Dash (any kit with a dash slot) to the landing tile that leaves the threats' reach. True if dashed.
bool dash_away(const std::vector<mv::Threat>& zones)
{
	AF_CHECK();
	const Kit& k = *W.me.kit;
	if (k.slot_dash < 0 || !ready(k.slot_dash))
		return false;
	const vec2 me = W.me.pos;
	const int r = std::max(1, static_cast<int>(k.dash_range));
	// only the zones that reach a tile within r of me count (a farther zone adds 0 to every tile scored here).
	static std::vector<mv::Threat> aof_near;
	aof_near.clear();
	for (const auto& t : zones)
		if (t.reach + 1 - cheb(me, t.pos) + r > 0)
			aof_near.push_back(t);
	const int now = dash_danger(aof_near, me);
	if (now <= 0)
		return false; // v66x PFC bit 1: no landing can beat danger 0
	const vec2 best = dash_landing(aof_near, me, r, now);
	if (best.x < 0 || dash_danger(aof_near, best) >= now)
		return false;
	return cast_at(k.slot_dash, best);
}
// A legal dash middle from a to b (Chebyshev 2): a tile next to both that is not a wall or a camp tile (dash_mid_ok in the move
// code).
bool rgf_crystal_at(vec2 p)
{
	static bitboard tp{ cambc::uninitialized };
	static int tp_r = -1;
	static bool tp_ok = false;
	if (tp_r != W.round)
	{
		tp_ok = cambc::detail::sdk_teleport_occupancy(tp.ptr()) == 0;
		tp_r = W.round;
	}
	return tp_ok && inb(p) && bbget(tp, p);
}
bool dash_middle_tile_ok(vec2 a, vec2 b)
{
	// Only the offsets whose tile can be within 1 of b (|a + d - b| <= 1 per axis), in the same
	// mx-then-my order; every test below still runs on them, so the first passing tile is the same one.
	const int x0 = std::max(-1, b.x - a.x - 1), x1 = std::min(1, b.x - a.x + 1);
	const int y0 = std::max(-1, b.y - a.y - 1), y1 = std::min(1, b.y - a.y + 1);
	static bitboard dmt_wce{ cambc::uninitialized }; // walls | camp tiles | enemy spawn, once the analysis is done (all final)
	static bool dmt_st = false;
	if (!dmt_st && M.done())
	{
		bb3_or(M.walls, M.camp_tiles, dmt_wce);
		bb3_or(dmt_wce, M.enemy_spawn, dmt_wce);
		dmt_st = true;
	}
	for (int mx = x0; mx <= x1; ++mx)
		for (int my = y0; my <= y1; ++my)
		{
			const vec2 m{ a.x + mx, a.y + my };
			if ((mx == 0 && my == 0) || !inb(m) || cheb(m, b) != 1)
				continue;
			if (dmt_st ? bbget(dmt_wce, m) : (bbget(M.walls, m) || bbget(M.camp_tiles, m) || bbget(M.enemy_spawn, m)))
				continue;
			if (rgf_crystal_at(m))
				continue; // INT:129: both block a dash middle
			if (BGX_ON(2) && bbget(W.occ_units, m) && !dash_legal_between(a, b))
				return false; // a unit on this middle; the engine rule decides
			return true;
		}
	return false;
}
// a plain-dash melee body (Vendetta, Issac, Ren) at >= 50% HP, a focus a mate within 2 of it hit since my last
// turn (track_foe_hp_drops's HP-drop record).
bool mate_hit_focus_dash_ok(const Body& f)
{
	const auto t = W.me.type;
	if (!(vendetta_layer::type(t) || ci_layer::issac(t) || ren_layer::type(t)) ||
		W.me.frac() < 0.5f)
		return false;
	bool near = false;
	for (const auto& al : W.allies)
		near |= cheb(al.pos, f.pos) <= 2;
	if (!near)
		return false;
	for (const auto& c : ct_hp)
		if (c.h == f.h)
			return c.mate_hit == W.round;
	return false;
}
// the shared bars of an engage dash onto a healthy focus (any_hp: the chain dash, no focus-health test).
bool engage_dash_ok(const Assessment& a, const Body& f, bool any_hp = false)
{
	if (a.stance != FIGHT || W.me.frac() < 0.6f || a.caught || (!any_hp && f.frac() < 0.5f) || static_cast<int>(W.me.gems) >= CR_BAG ||
		a.ratio_fc < static_cast<float>(B467_ENGAGE_X100) / 100.0f)
		return false;
	int nf = 1, ne = 0; // seen allies within 6 of me (me included) >= seen foes within 6 of the focus
	for (const auto& al : W.allies)
		nf += cheb(al.pos, W.me.pos) <= 6;
	for (const auto& e : W.enemies)
		ne += cheb(e.pos, f.pos) <= 6;
	if (nf < ne)
		return false;
	for (int dx = -NOCHASE_R; dx <= NOCHASE_R; ++dx)
		for (int dy = -NOCHASE_R; dy <= NOCHASE_R; ++dy)
		{
			const vec2 t{ f.pos.x + dx, f.pos.y + dy };
			if (inb(t) && bbget(M.enemy_spawn, t))
				return false;
		}
	return true;
}
// mate_hit_focus_dash_ok's healthy-focus alternative (Vendetta only).
bool healthy_focus_dash_ok(const Assessment& a, const Body& f)
{
	const auto t = W.me.type;
	if (!(vendetta_layer::dash_vei(t)))
		return false;
	return engage_dash_ok(a, f);
}
namespace {
// an init landing also needs an engine-legal dash middle and no NO_WAKE veto.
bool init_dash_landing_bad(vec2 t)
{
	if (cheb(t, W.me.pos) == 2 && !dash_middle_tile_ok(W.me.pos, t))
		return true;
	return static_cast<bool>(camps::wakes_other_group(t, 1, t, -1, 0.0f));
}
static bool dash_middle_ok(vec2 a, vec2 b)
{
	return dash_legal_between(a, b);
}
} // namespace
// a free neighbour of mine that keeps f in my basic range, is out of every awake camp's reach and has no
// more foe danger than my tile; {-1,-1} when none or no camp hits me here.
static vec2 safe_in_range_step(const Assessment& a, const Body& f)
{
	const float here = mv::camp_threat(W.me.pos);
	if (here <= 0.0f)
		return vec2{ -1, -1 };
	const float foe_here = danger_at(a, W.me.pos) - here;
	vec2 best{ -1, -1 };
	float best_s = 1e9f;
	for (const vec2 dd : DIRS)
	{
		const vec2 t = W.me.pos + dd;
		if (cheb(t, f.pos) > W.me.range || !mv::free_tile(t))
			continue;
		const float ct = mv::camp_threat(t);
		if (ct > 0.0f)
			continue;
		const float foe_t = danger_at(a, t) - ct;
		if (foe_t > foe_here + 0.5f)
			continue;
		const float s = foe_t + 0.01f * static_cast<float>(mv::home_steps(t));
		if (s < best_s)
		{
			best_s = s;
			best = t;
		}
	}
	return best;
}
namespace {
// A tile the Heart of Ruin dash can land on, close enough to f for the landing to hit it.
// ren: some visible enemy retaliates (else ren_retaliation_of_cast sums nothing: 0).
static __attribute__((always_inline)) inline bool heart_landing_tile_ok(const Kit& k, const Body& f, vec2 t, bool ren)
{
	if (t == W.me.pos || !mv::free_tile(t) || cheb(t, f.pos) > static_cast<int>(k.dash_radius))
		return false;
	if ((ren ? kit_rules::ren_retaliation_of_cast(k.slot_dash, 0u, 0u, t) : 0.0f) >= eff_hp(W.me))
		return false; // BB12 RENT
	return cheb(t, W.me.pos) != 2 || dash_middle_ok(W.me.pos, t);
}
// Not onto a sleeping dangerous group that would hit us first (unless the landing kills).
static __attribute__((always_inline)) inline bool heart_landing_wakes_group(const Kit& k, vec2 t)
{
	return camps::wakes_other_group(t, std::max(1, static_cast<int>(k.dash_radius)), t, -1, -k.dash_mod); // BB12 KPAIR
}
static __attribute__((always_inline)) inline bool any_retaliator()
{
	for (const auto& e : W.enemies)
		if (e.kit && e.kit->retaliation)
			return true;
	return false;
}
} // namespace
// The Heart of Ruin landing on f that hits the most enemies; {-1, -1} when there is none. The landing hit and stun pay on the focus alone too.
static vec2 heart_landing(const Kit& k, const Body& f)
{
	vec2 best{ -1, -1 };
	int best_hits = 0;
	const bool ren = any_retaliator();
	for (int dx = -tune::HEART_SCAN_R; dx <= tune::HEART_SCAN_R; ++dx)
		for (int dy = -tune::HEART_SCAN_R; dy <= tune::HEART_SCAN_R; ++dy)
		{
			const vec2 t{ W.me.pos.x + dx, W.me.pos.y + dy };
			if (!heart_landing_tile_ok(k, f, t, ren))
				continue;
			int hits = 0;
			for (const auto& e : W.enemies)
				if (cheb(e.pos, t) <= static_cast<int>(k.dash_radius))
					++hits;
			if (hits > best_hits && !heart_landing_wakes_group(k, t))
			{
				best_hits = hits;
				best = t;
			}
		}
	return best;
}
// The next landing on f after `bad` was refused (an unseen body stands there): the first one in scan order.
static vec2 heart_landing_next(const Kit& k, const Body& f, vec2 bad)
{
	const bool ren = any_retaliator();
	for (int dx = -tune::HEART_SCAN_R; dx <= tune::HEART_SCAN_R; ++dx)
		for (int dy = -tune::HEART_SCAN_R; dy <= tune::HEART_SCAN_R; ++dy)
		{
			const vec2 t{ W.me.pos.x + dx, W.me.pos.y + dy };
			if (!(t == bad) && heart_landing_tile_ok(k, f, t, ren) && !heart_landing_wakes_group(k, t))
				return t;
		}
	return { -1, -1 };
}
// A melee plain dash's landing: next to f, with the fewest other enemies within 2.
static vec2 plain_land(const Body& f, bool init, int& best_s)
{
	const int r = dash_tiles(*W.me.kit);
	return dash_landing_search<false>(W.me.pos, f, -r, r, -r, r, 1, init, best_s);
}
namespace {
// The ONE two-turn reach of a foe before my next turn, worst case. Returns -1 when it gets one turn (its zone and
// danger_at keep f.reach), else f.reach + 1 (its turn-1 walk) + its dash range when its dash is ready (a body not in sight: +1 only).
// *e_out: the foe's body when in sight (nullptr otherwise).
static int foe_two_turn_reach_after_turn_count(const Foe& f, const Body* e) // the part of foe_two_turn_reach after the turn count
{
	if (e && e->stunned)
		return -1;
	if (e && e->kit && e->kit->slot_dash >= 0 && (foe_ready(*e, e->kit->slot_dash, 1))) // v699 PDZ bit 1: a dash at cd 1 is ready on its 2nd turn (GR:118)
		return foe_next_turn_reach(*e, true) + 1 + std::max(1, static_cast<int>(e->kit->dash_range));
	return f.reach + 1;
}
} // namespace
static int foe_two_turn_reach(const Foe& f, const Body** e_out)
{
	const bool vis = !f.remembered && f.idx >= 0 && f.idx < static_cast<int>(W.enemies.size());
	const Body* e = vis ? &W.enemies[static_cast<std::size_t>(f.idx)] : nullptr;
	if (e_out)
		*e_out = e;
	if (f.reach < 0 || (e && (burst::reach_burst_turns(*e)) < 2)) // PDZ bit 2: the Prism's flee zones take the TIS count
		return -1;
	return foe_two_turn_reach_after_turn_count(f, e);
}
// Damage expected on tile t from the foes' next turns (their burst when t is in reach) and from awake camps.
float danger_at(const Assessment& a, vec2 t)
{
	float d = mv::camp_threat(t);
	for (const auto& f : a.foes)
		if (f.reach >= 0 && cheb(t, f.pos) <= f.reach)
			d += (f.burst);
	return d;
}
// danger_at for the FATAL checks and vetoes only (walk guards, the out-of-reach tests): a foe with two turns before
// my next (foe_two_turn_reach, worst case) reaches farther and hits with its two-turn burst (foe_two_turn_damage). Stance / ratio / tile-scoring consumers
// keep danger_at's expected value. No FCS share here (a share on a veto raises lethal misses).
float danger_veto(const Assessment& a, vec2 t)
{
	float d = mv::camp_threat(t);
	for (const auto& f : a.foes)
	{
		if (f.reach < 0)
			continue;
		const int dt = cheb(t, f.pos);
		const Body* e = nullptr;
		const int r2 = foe_two_turn_reach(f, &e); // -1: one turn
		if (dt > std::max(f.reach, r2))
			continue;
		if (r2 >= 0 && e && dt > f.reach) // beyond its one-turn reach only the two-turn hit counts
			d += burst::foe_two_turn_damage(*e, dt, 0.0f);
		else
			d += r2 >= 0 && e ? std::max(f.burst, burst::foe_two_turn_damage(*e, dt, burst::lethal_burst_hit(*e, dt, 0, nullptr))) : f.burst;
	}
	return d;
}
} // namespace geom
} // namespace nova::combat
