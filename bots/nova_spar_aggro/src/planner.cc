// planner.cc: Planner: a camp-state model for every group, route planning over sequences of groups with spare fuel, and capture routing to the
#include "planner.h"

#include "comms.h"
#include "mapinfo.h"
#include "move.h"
#include "plan.h"
#include "champions.h" // Kit layers.
#include "world.h"

namespace nova::planner {

namespace {

int now() { return W.round; }

std::vector<Camp> C;
const Camp kNone{};
std::array<int, 8> prev_claim{ -1, -1, -1, -1, -1, -1, -1, -1 };
int my_cap_group = -1, my_cap_round = -1000;

void ensure()
{
	if (C.size() != static_cast<std::size_t>(M.ng))
		C.assign(static_cast<std::size_t>(M.ng), Camp{});
}

// ---------------------------------------------------------------- group-to-group distances
std::vector<std::uint16_t> D;   // D[from * n + to]
std::vector<std::uint8_t> col;  // column `to` filled from its group field
int n_groups = 0;

void ensure_matrix()
{
	const int n = M.ng;
	if (n_groups == n && static_cast<int>(D.size()) == n * n)
		return;
	n_groups = n;
	D.assign(static_cast<std::size_t>(n) * static_cast<std::size_t>(n), UNREACH);
	col.assign(static_cast<std::size_t>(n), 0);
	for (int i = 0; i < n; ++i)
		D[static_cast<std::size_t>(i * n + i)] = 0;
}

// Fill column `to`: walking distance from each group's approach tiles to group `to` (its cached field).
void fill_group_distance_column(int to, const distance_field& f)
{
	const int n = n_groups;
	const FView fv = fview(f);
	for (int from = 0; from < n; ++from)
	{
		if (from == to)
			continue;
		const auto& g = M.groups[static_cast<std::size_t>(from)];
		std::uint16_t best = UNREACH;
		int k = 0;
		for (const vec2 p : g.approach)
		{
			const std::uint16_t v = fv(p);
			if (v < best)
				best = v;
			if (++k >= 4)
				break;
		}
		if (best != UNREACH)
			best = static_cast<std::uint16_t>(best + 1);
		D[static_cast<std::size_t>(from * n + to)] = best;
	}
	col[static_cast<std::size_t>(to)] = 1;
}

// ---------------------------------------------------------------- stats
struct Stats
{
	long t_start = 0;
	int r_start = -1;
	int turns = 0, susp = 0, over85 = 0;
	long long sum = 0;
	long mx = 0;
	std::array<int, 260> hist{};
	int trips = 0, wasted = 0, wasted_rounds = 0, wait_resp = 0, wait_crew = 0, idle = 0;
	int caps = 0, shared = 0, first = -1, capgems = 0, capgold = 0;
	int first_act = -1;
	std::array<int, 8> idle_act{};
	int wasted_ally = 0, wasted_enemy = 0;
};
Stats ST;

} // namespace

// ---------------------------------------------------------------- camp-state model

const Camp& camp(int gi)
{
	if (gi < 0 || gi >= static_cast<int>(C.size()))
		return kNone;
	return C[static_cast<std::size_t>(gi)];
}

void on_captured_by_me(int gi)
{
	ensure();
	if (gi < 0 || gi >= static_cast<int>(C.size()))
		return;
	auto& c = C[static_cast<std::size_t>(gi)];
	c.state = CS_RESPAWN;
	c.by = BY_ME;
	c.captured_at = now();
	c.respawn_at = now() + M.groups[static_cast<std::size_t>(gi)].respawn;
	c.exact = true;
	c.hp_left = -1;
	my_cap_group = gi;
	my_cap_round = now();
}

void observe()
{
	ensure();
	const int t = now();
	const vec2 me = W.me.pos;
	for (std::size_t gi = 0; gi < C.size(); ++gi)
	{
		auto& c = C[gi];
		if (c.state == CS_RESPAWN && t >= c.respawn_at)
		{
			c.state = CS_UNKNOWN;
			c.hp_left = -1;
			c.awake = false;
		}
	}
	if (!W.alive)
		return;
	// Visible camps by camp index (W.camp_by_index is a linear search).
	static std::vector<std::int16_t> vidx;
	if (vidx.size() != static_cast<std::size_t>(M.nc))
		vidx.assign(static_cast<std::size_t>(M.nc), -1);
	for (std::size_t i = 0; i < W.camps.size(); ++i)
		if (W.camps[i].ci >= 0 && W.camps[i].ci < static_cast<int>(vidx.size()))
			vidx[static_cast<std::size_t>(W.camps[i].ci)] = static_cast<std::int16_t>(i);
	// Vision: groups near me.
	for (std::size_t gi = 0; gi < C.size(); ++gi)
	{
		const auto& g = M.groups[gi];
		if (cheb(g.anchor, me) > 12)
			continue;
		auto& c = C[gi];
		int vis_n = 0, alive_n = 0;
		float hp = 0;
		bool awake = false;
		for (int ci : g.members)
		{
			const auto& cp = M.camps[static_cast<std::size_t>(ci)];
			if (!bbget(W.vis, cp.pos))
			{
				hp += cp.hp;
				continue;
			}
			++vis_n;
			if (bbget(W.occ_camps, cp.pos))
			{
				++alive_n;
				const int vi = vidx[static_cast<std::size_t>(ci)];
				const VisCamp* vc = vi >= 0 ? &W.camps[static_cast<std::size_t>(vi)] : nullptr;
				hp += vc ? vc->hp : cp.hp;
				awake |= vc && vc->awake;
			}
		}
		if (vis_n == 0)
			continue;
		c.seen = t;
		if (alive_n > 0)
		{
			c.state = CS_ALIVE;
			c.hp_left = hp;
			c.awake = awake;
			continue;
		}
		if (vis_n < g.nm)
			continue;
		if (c.state == CS_RESPAWN && c.exact)
			continue;
		std::uint32_t st = 0;
		if (cambc::detail::sdk_camp_group_state(g.handle, &st) != 0)
			continue;
		if (st == 2)
		{
			c.state = CS_CLEARED;
			c.awake = false;
		}
		else if (st == 3)
		{
			std::int32_t timer = 0;
			cambc::detail::sdk_camp_group_cooldown(g.handle, &timer);
			c.state = CS_RESPAWN;
			c.respawn_at = t + std::max(1, static_cast<int>(timer));
			c.captured_at = c.respawn_at - g.respawn;
			c.exact = true;
			c.hp_left = -1;
			c.awake = false;
			if (static_cast<int>(gi) == my_cap_group && iabs(my_cap_round - c.captured_at) <= 3)
				c.by = BY_ME;
			else if (c.engaged_by >= 0 && c.captured_at - c.engaged_round <= 12)
				c.by = BY_ALLY;
			else
				c.by = BY_ENEMY;
		}
		else if (st == 1)
			c.state = CS_ALIVE;
	}
	for (const auto& vc : W.camps)
		if (vc.ci >= 0 && vc.ci < static_cast<int>(vidx.size()))
			vidx[static_cast<std::size_t>(vc.ci)] = -1;
	// Allies' claims: who is fighting what, and claims that moved on from a group they were fighting.
	for (int s = 0; s < std::min(P.n, comms::CLAIM_SLOTS); ++s)
	{
		if (s == P.my_slot)
			continue;
		const int g = comms::cgroup(s);
		if (g >= static_cast<int>(C.size()))
			continue;
		if (g >= 0 && comms::cengaged(s))
		{
			C[static_cast<std::size_t>(g)].engaged_by = s;
			C[static_cast<std::size_t>(g)].engaged_round = t;
		}
		const int pg = prev_claim[static_cast<std::size_t>(s)];
		prev_claim[static_cast<std::size_t>(s)] = g;
	}
}

// ---------------------------------------------------------------- route planning


namespace {
// Per-group leg data for this body (refreshed in the background).
struct LegData
{
	float v = 0;     // value in gem units for me
	float clear = 0; // solo clear time
	bool ok = false; // walkable, worth something, solo feasible
	int round = -1000;
};
std::vector<LegData> L;
std::vector<Leg> cont1; // best single continuation from each group
std::vector<Leg> cont2; // best two-group continuation from each group
std::vector<int> cont_round, c1_round;
std::size_t leg_cursor = 0, c1_cursor = 0, c2_cursor = 0;
LegEvalFn route_leg_eval = nullptr;
std::array<int, 8> bg_claims{};

void ensure_legs()
{
	const std::size_t n = static_cast<std::size_t>(M.ng);
	if (L.size() != n)
	{
		L.assign(n, LegData{});
		cont1.assign(n, Leg{});
		cont2.assign(n, Leg{});
		cont_round.assign(n, -1000);
		c1_round.assign(n, -1000);
		leg_cursor = c1_cursor = c2_cursor = 0;
	}
}



} // namespace

void set_leg_eval(LegEvalFn fn) { route_leg_eval = fn; }

void background(long reserve)
{
	if (M.groups.empty())
		return;
	ensure();
	ensure_matrix();
	ensure_legs();
	const int n = M.ng;
	// 1. Matrix columns from the group fields already built.
	for (int to = 0; to < n && fuel() > reserve + 6L * n * 20 + 2000; ++to)
	{
		if (col[static_cast<std::size_t>(to)])
			continue;
		const distance_field* f = mv::group_field_raw(to);
		if (!f)
			continue;
		fill_group_distance_column(to, *f);
	}
	return;
}

// ---------------------------------------------------------------- stacking

// Damage per 100 base capture gold by kit x10, in champion_type order (ranks computed from the rules; Vesper's +33% gold is in her
// number). Ryth, Vesper, Vendetta, Cassi, Issac, Stellar, Prism, Marcella, Willow, Ren, Varg, Tavi, HoR.
static const int rcy_d100[13] = { 233, 344, 311, 149, 155, 166, 115, 181, 155, 230, 259, 259, 138 };
// Rank points this capture is worth to kit t now: damage its gold buys x RCY_K, x the share of the game left to use it (1 to r150,
// .65 at r300, .2 at r600, 0 from r875: the fall of gems per damage).
static int capture_rank_fit(cambc::champion_type t, int slot, int gold, int gems)
{
	const int ti = static_cast<int>(t);
	if (ti < 0 || ti >= 13)
		return 0;
	const int geq = static_cast<int>(mu::holder_gold_mult(slot) * (static_cast<float>(gold) + (marcella_layer::gem_gold(t) ? marcella_layer::tribute_gold(static_cast<float>(gems)) : 0.0f)));
	if (geq <= 0)
		return 0;
	const int r = now();
	const int fade = r <= 150 ? 100 : r <= 300 ? 100 - 35 * (r - 150) / 150 : r <= 600 ? 65 - 45 * (r - 300) / 300 : r < 875 ? 20 - 20 * (r - 600) / 275 : 0;
	return static_cast<int>(static_cast<std::int64_t>(geq) * rcy_d100[ti] * RCY_TAB[2] * fade / 100000);
}
int stack_rank_bonus(int slot, int gi)
{
	if (gi < 0 || gi >= M.ng || slot < 0)
		return 0;
	const auto& g = M.groups[static_cast<std::size_t>(gi)];
	const auto t = P.type[static_cast<std::size_t>(slot)];
	const Kit& k = kit_of(t);
	int b = 0;
	const bool rcy = true;
	// Marcella earns 2 gold per gem she tributes and Prism gains Focus per carried gem: gem captures go to them.
	if (g.gems > 0 && ((marcella_layer::gem_gold(t) && !rcy) || k.gem_focus))
		b -= 200 + 4 * g.gems;
	// Gold captures pass Cassi & Issac by when a mate stands there to take them (CI_CAP_PEN).
	if (g.gold > 0 && (ci_layer::type(t)))
		b += CI_CAP_PEN + g.gold / 2;
	// Vesper Vale earns a third more gold from her own captures.
	if (g.gold > 0 && vesper_layer::targets_own_gold(k) && !rcy)
	{
		b -= 100 + g.gold / 2;
	}
	b -= capture_rank_fit(t, slot, g.gold, g.gems);
	return b;
}

// ---------------------------------------------------------------- measurement

void stat_turn_begin()
{
	ST.t_start = fuel();
	ST.r_start = static_cast<int>(round_number_nc());
}
void stat_turn_end(bool counted)
{
	const long used = ST.t_start - fuel();
	if (static_cast<int>(round_number_nc()) != ST.r_start)
	{
		++ST.susp;
	}
	if (!counted || used < 0)
		return;
	++ST.turns;
	ST.sum += used;
	ST.mx = std::max(ST.mx, used);
	if (used > 85000)
		++ST.over85;
	++ST.hist[static_cast<std::size_t>(std::min(259L, used / 1000))];
	if (ST.first_act < 0 && (W.moved || W.attacked || W.cast))
		ST.first_act = W.round;
}

void stat_set_target(int) { ++ST.trips; }
void stat_wasted_trip(int gi, int walked)
{
	const Camp& c = camp(gi);
	if (c.by == BY_ALLY || c.by == BY_ME)
		++ST.wasted_ally;
	else
		++ST.wasted_enemy;
	++ST.wasted;
	ST.wasted_rounds += walked;
}
void stat_wait(int kind)
{
	if (kind == 0)
		++ST.wait_resp;
	else
		++ST.wait_crew;
}
void stat_idle(int act)
{
	++ST.idle;
	++ST.idle_act[static_cast<std::size_t>(std::clamp(act, 0, 7))];
}
void stat_capture(int, int sharing, int gems, int gold)
{
	++ST.caps;
	if (sharing > 1)
		++ST.shared;
	if (ST.first < 0)
		ST.first = W.round;
	ST.capgems += gems;
	ST.capgold += gold;
}

} // namespace nova::planner
