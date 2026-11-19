// econ_crystal_plan.cc: Whether and when to carry and use crystals.
#include "econ_internal.h"
namespace nova::econ {
namespace {
// Walking distance from me to every group: read from the cached group fields (built in spare fuel), Chebyshev distance with a detour
// margin for groups whose field is not built yet. CRYSTAL: camp groups no walk or dash reaches (ACC_TP) are taken by crystal trips
// from our spawn, which gives free uncontested material or a safe spot for depositing. A body near the spawn holding a crystal walks
// to a launch tile L and teleports to a landing tile T inside the group's walled area (Chebyshev <= 3, terrain ignored, a 3-turn
// channel that damage does not stop and nothing cancels); walled in, it recalls home to bank. One plan per group, built lazily from
// the group's walk field and our spawn's.
constexpr std::uint32_t RAW_CRYSTAL = 0; // engine consumable id of the teleport crystal
// CDX bit 4: a landing with 2+ known foes within 5 (visible, ward-seen, or remembered <= 3 rounds) and no living mate within 5.
static bool cdx_hot_landing(vec2 t)
{
	std::array<std::uint32_t, 16> hs{};
	int nh = 0;
	auto add = [&](std::uint32_t h, vec2 p)
	{
		if (cheb(p, t) > 5)
			return;
		for (int i = 0; i < nh; ++i)
			if (hs[static_cast<std::size_t>(i)] == h)
				return;
		if (nh < 16)
			hs[static_cast<std::size_t>(nh++)] = h;
	};
	for (const auto* v : { &W.enemies, &W.enemies_far })
		for (const auto& e : *v)
			add(e.h, e.pos);
	const int r = now();
	for (const auto& s : nova::combat::seen)
		if (r - s.round <= 3)
			add(s.h, s.foe.pos);
	if (nh < 2)
		return false;
	for (const auto& a : W.allies)
		if (cheb(a.pos, t) <= 5)
			return false;
	return true;
}
static int mf2_land_r = -1000; // the round my last crystal channel lands
int tp_groups_checked = -1;
bool tp_groups_any = false;
std::unique_ptr<distance_field> fL;
static bool cp_in_bg = false; // inside crystal_plan_background
int cp_gen = 0; // bumped by every crystal_plan call (it may change a plan's done or retry)
struct SCLand
{
	vec2 T{ -1, -1 }, L{ -1, -1 };
	std::uint16_t off = 0;  // walk from our spawn to L
	std::uint16_t gain = 0; // walk from our spawn to T minus off
};
std::vector<SCLand> sc_land;
int sc_stage = 0, sc_cur = 0;
bool sc_any_r = false; // some group or the bank has a route
std::vector<std::uint16_t> sc_wtrav;     // compute_travel: my walk travel where a crystal route priced the group lower (else 0)
std::unique_ptr<distance_field> sc_fl;   // the trip's launch field: walk to the nearest tile within 3 of the landing
// spawn_crystal_prep's result with v128 passes. The window minimum is separable and min is exact and order-free, so taking the 7-row
// minimum first (stage 1, v128 across x) and then the existing 7-column row pass (stage 2) gives sc_win exactly. The two w x h
// buffers are left unfilled (the export writes every tile, stage 1 every tile of sc_win). Stage 3 tests 8 tiles at a time with the
// same skip rule and runs the scalar candidate code on the others, in the same order, with the same fuel checks.
std::unique_ptr<std::uint16_t[]> fx_buf, fx_win;
// Routes per walkable group (once its walk field is built) and for the bank field (when an altar is walkable).
std::size_t sc_rt_all_n = static_cast<std::size_t>(-1); // every group's route done or never eligible
// One move of the trip toward field f: walk to the launch; within 3 of the planned landing, teleport to the free landing within 3
// that is nearest the target (the planned one first), unless an enemy is seen within 4 of it or of me. A trip that ends with the
// crystal unused (timeout, hold, no landing) blocks crystal trips for RCL_SC_SKIP rounds (the foe abort keeps its own 30, 10 with
// no recall hop); otherwise the spawn restarts the same stalled trip.
int cxf_key = -1, cxf_holds = 0; // the trip (by its deadline) and its foe holds
// a hop's price: dt walk steps past the landing, and the price for a target past the landing (the landing filters).
static inline int sc_hop(int dt) { return rs::crystal_hop(dt); }
static inline int sc_hop0() { return sc_hop(0); }
int crystals_carried()
{
	if (crystal_count >= 0 && now() - crystal_checked < 20)
		return crystal_count;
	std::array<std::uint32_t, 4> counts{};
	if (cambc::detail::sdk_champion_consumables(W.me.h, counts.data()) != 0)
		return 0;
	crystal_count = static_cast<int>(counts[RAW_CRYSTAL]);
	crystal_checked = now();
	return crystal_count;
}
bool walled_in() { return W.alive && M.has_home && dfget_me(M.f_home) == UNREACH; }
// v711 WIC bit 1: shut in by a living door: the camps-blocked home field UNREACH here (not on a camp tile), the camps-open one reachable, and
// the gate redirect failed within 3 rounds.
int wic_gate_fail = -1000;
bool wic_shut_in()
{
	if (!W.alive || !M.has_home || now() - wic_gate_fail > 3 || bbget(M.camp_tiles, W.me.pos) || dfget_me(M.f_home) == UNREACH)
		return false;
	const distance_field* hf = mv::home_field_cb(); // camps blocked (M.f_home_cb is skipped when distances come from draft memory)
	return hf && dfget_me(*hf) == UNREACH;
}
bool any_teleport_groups()
{
	if (tp_groups_checked == M.ng)
		return tp_groups_any;
	tp_groups_any = false;
	for (const auto& g : M.groups)
		if (g.access == ACC_TP && g.gems + g.gold > 0)
			tp_groups_any = true;
	tp_groups_checked = M.ng;
	return tp_groups_any;
}
// The gems only a crystal reaches are at least those I can reach another way (decided once).
static bool crystal_gems_scarce()
{
	static int v = -1;
	if (v < 0 && M.has_home && M.groups_ready())
	{
		int w = 0, tp = 0;
		for (const auto& g : M.groups)
		{
			if (g.access == ACC_WALK || (g.access == ACC_DASH && dn::dasher()))
				w += g.gems;
			else if (g.access == ACC_TP)
				tp += g.gems;
		}
		v = tp > 0 && w <= tp ? 1 : 0;
	}
	return v == 1;
}
// on a scarce map, is `self` the trip body?
static bool crystal_plan_trip_body(int self)
{
	const int c = P.carrier_gems >= 0 ? P.carrier_gems : P.tank_order[0];
	return self == c;
}
// crystal_plan's scan state, kept across turns (a full scan does not finish within one turn's fuel); gi >= 0 while a scan is part done.
static struct CpScan
{
	int gi = -1, hrow = 0, trow = 0, cost = UNREACH;
	vec2 L{ -1, -1 }, T{ -1, -1 };
	int rm[25][19];
	signed char ri[25][19];
} cps;
// v698 CPSCANR: the group whose scan is part done (-1: none), which crystal_plan_background serves first so the part is not discarded.
int crystal_plan_partial_gi() { return cps.gi; }
const CPlan* crystal_plan(int gi)
{
	++cp_gen;
	if (cplans.size() != static_cast<std::size_t>(M.ng))
		cplans.assign(static_cast<std::size_t>(M.ng), CPlan{});
	CPlan& c = cplans[static_cast<std::size_t>(gi)];
	if (c.done)
		return c.cost == UNREACH ? nullptr : &c;
	if (!cp_in_bg)
		return nullptr; // built by crystal_plan_background, last in the turn
	if (!M.has_home || fuel() < (30000) || now() < c.retry)
		return nullptr; // later, with spare fuel
	c.retry = now() + 10;
	const distance_field* f = mv::group_field_ready(gi);
	if (!f && fuel() > (3L * G.w * G.h + 30000))
		f = mv::group_field(gi); // one build, with fuel to spare
	if (!f)
		return nullptr;
	// The same scan (target t within 9 of the anchor, launch l within 3 of t, first strict minimum of f_home(l) + 3 + f(t) in (dy, dx,
	// ly, lx) order) as a separable 7x7 window minimum (rows of window minima of f_home, then a column pass per target), kept across
	// turns in cps because a full scan does not finish within one turn's fuel. Every input here (f_home, the group's field, block) is
	// static.
	const vec2 a = M.groups[static_cast<std::size_t>(gi)].anchor;
	if (cps.gi != gi)
	{
		cps.gi = gi;
		cps.hrow = cps.trow = 0;
		cps.cost = UNREACH;
	}
	constexpr int INF = 1 << 30;
	const FView vh = fview(M.f_home), vf = fview(*f);
	const BView vb = bview(M.block);
	auto out_of_fuel = [&]() -> bool
	{
		if (!(fuel() < 17000)) // out of this turn's fuel: on from here next turn
			return false;
		c.done = false;
		c.cost = UNREACH;
		c.retry = now() + 1;
		return true;
	};
	for (; cps.hrow < 25; ++cps.hrow)
	{
		if (out_of_fuel())
			return nullptr;
		const int y = a.y - 12 + cps.hrow;
		int hv[25];
		for (int q = 0; q < 25; ++q)
			hv[q] = INF;
		if (y >= 0 && y < G.h)
			for (int q = std::max(0, 12 - a.x), qe = std::min(25, G.w - a.x + 12); q < qe; ++q)
			{
				const vec2 l{ a.x - 12 + q, y };
				if (vb(l))
					continue;
				const std::uint16_t fl = vh(l);
				if (fl != UNREACH)
					hv[q] = fl;
			}
		int* const rmr = cps.rm[cps.hrow];
		signed char* const rir = cps.ri[cps.hrow];
		for (int tx = 0; tx < 19; ++tx)
		{
			int m = hv[tx], mi = 0;
			for (int k = 1; k < 7; ++k)
				if (hv[tx + k] < m)
				{
					m = hv[tx + k];
					mi = k;
				}
			rmr[tx] = m;
			rir[tx] = static_cast<signed char>(mi);
		}
	}
	for (; cps.trow < 19; ++cps.trow)
	{
		if (out_of_fuel())
			return nullptr;
		const int ty = cps.trow;
		const int y = a.y - 9 + ty;
		if (y < 0 || y >= G.h)
			continue;
		for (int tx = std::max(0, 9 - a.x), txe = std::min(19, G.w - a.x + 9); tx < txe; ++tx)
		{
			const vec2 t{ a.x - 9 + tx, y };
			if (vb(t))
				continue;
			const std::uint16_t ft = vf(t);
			if (ft == UNREACH || (ft == 0)) // v711 ISL bit 4 CPT1: the group's own (dead) camp tile is a landing too
				continue;
			int m = cps.rm[ty][tx], mr = 0;
			for (int k = 1; k < 7; ++k)
				if (cps.rm[ty + k][tx] < m)
				{
					m = cps.rm[ty + k][tx];
					mr = k;
				}
			if (m == INF)
				continue;
			const int cost = m + rs::crystal_hop(static_cast<int>(ft)); // ft >= 1 here
			if (cost < cps.cost)
			{
				cps.cost = cost;
				cps.L = vec2{ t.x - 3 + cps.ri[ty + mr][tx], t.y - 3 + mr };
				cps.T = t;
			}
		}
	}
	c.done = true;
	if (cps.cost < c.cost) // c.cost is UNREACH here (a fresh or aborted plan)
	{
		c.cost = cps.cost;
		c.L = cps.L;
		c.T = cps.T;
	}
	cps.gi = -1;
	return c.cost == UNREACH ? nullptr : &c;
}
int rlg_cast_gi = -1, rlg_cast_round = -1000; // v707 RC5 RLG1: my last crystal landing (group, round)
// A crystal trip to group gi is open to me: a walled-off group with a plan, I am near our spawn and hold a crystal.
bool crystal_ok(int gi)
{
	const auto& g = M.groups[static_cast<std::size_t>(gi)];
	if (g.access != ACC_TP || !W.alive || !M.has_home)
		return false;
	if (crystal_gems_scarce() && !crystal_plan_trip_body(my_slot()))
		return false;
	if (static_cast<float>(g.gems) + 0.1f * static_cast<float>(g.gold) < CRYSTAL_MIN_V && !(crystal_gems_scarce()))
		return false; // a trip (and the recall home) pays only for a rich group
	const int cp_dh = dfget_me(M.f_home);
	if ((cp_dh > CRYSTAL_NEAR && !(crystal_gems_scarce() && cp_dh != UNREACH)) || crystals_carried() <= 0)
		return false;
	const CPlan* cpl = crystal_plan(gi);
	if (cpl && !(crystal_gems_scarce()))
	{
		const std::uint16_t fl = dfget(M.f_home, cpl->L);
		if (fl == UNREACH || static_cast<int>(fl) > CRYSTAL_NEAR)
			return false; // the launch is past CRYSTAL_NEAR, so the walk there would drop the trip
	}
	return cpl != nullptr;
}
// One move of a crystal trip to group gi (outside its walled area): walk to L, then teleport to T when no enemy is close.
bool crystal_step(int gi)
{
	if (cplans.size() != static_cast<std::size_t>(M.ng))
		return false;
	const CPlan& c = cplans[static_cast<std::size_t>(gi)];
	if (!c.done || c.cost == UNREACH || crystals_carried() <= 0)
		return false;
	if ((W.me.pos.x == c.L.x && W.me.pos.y == c.L.y) || (cheb(W.me.pos, c.T) <= 3))
	{
		for (const auto& e4 : W.enemies)
			if (cheb(e4.pos, W.me.pos) <= 4)
				return false; // the foe bar is 4
		// a stun does not stop Marcella's crystal (champ_marcella.h chan_stun_proof), so no stun bar.
		const bool ko1_mci = false;
		for (const auto& e5 : W.enemies) // a ready stun that reaches me after two walks during the channel blocks the cast
		{
			if (combat::rf2_stun_reach(e5, cheb(e5.pos, W.me.pos) - 2))
			{
				OWN_KIT_RULES_CNT(16, ko1_mci);
				KIT_RULE_FIX_CNT(9, true);
				return false;
			} // the channel cannot be cancelled: not with an enemy close
		}
		std::int32_t ok = 0;
		vec2 land = c.T;
		if (!mv::free_tile(land))
		{
			const distance_field* fg = mv::group_field_ready(gi);
			if (!fg)
				return false;
			vec2 nb{ -1, -1 };
			if (mid_hop_best_landing(W.me.pos, fview(*fg), &nb) == UNREACH)
				return false;
			land = nb;
		}
		if (cdx_hot_landing(land))
			return false; // CDX bit 4: a contested landing: walk instead
		try
		{
			cancel_spin_before_action();
			if (cambc::detail::sdk_use_consumable(RAW_CRYSTAL, land.x, land.y, &ok) == 0 && ok)
			{
				crystal_count = 0;
				crystal_checked = now();
				rlg_cast_gi = gi;
				rlg_cast_round = now();
				NLOG("r%d slot %d crystal %d,%d -> %d,%d group %d\n", now(), P.my_slot, c.L.x, c.L.y, c.T.x, c.T.y, gi);
				return true;
			}
		}
		catch (...)
		{
			FXR_PASS();
		}
		return false;
	}
	if (!(fL && fL_at.x == c.L.x && fL_at.y == c.L.y) && fuel() > 3L * G.w * G.h + 45000)
	{
		auto f = std::make_unique<distance_field>();
		bitboard visited, root;
		bbset(root, c.L);
		f->compute(M.block_camps & ~root, root, visited);
		fL = std::move(f);
		fL_at = c.L;
	}
	if (fL && fL_at.x == c.L.x && fL_at.y == c.L.y && dfget_me(*fL) != UNREACH && dfget_me(*fL) > 0)
		return mv::step_field(*fL);
	return mv::step_to(c.L, 0, 40);
}
// Window minimum over +-3 of a padded line: out[i] = min(p[i..i+6]) for i < n (p holds n + 6 values).
void window_min_7(const std::uint16_t* p, std::uint16_t* out, int n, std::uint16_t* t2, std::uint16_t* t4)
{
	// each pass 8 lanes at a time (u16 min is exact), the tail scalar; reads stay inside the elements the scalar pass reads (lane 7 of
	// the last vector is index j + 7 + k <= the scalar loop's last read).
	int j = 0;
	for (; j + 8 <= n + 5; j += 8)
		wasm_v128_store(t2 + j, wasm_u16x8_min(wasm_v128_load(p + j), wasm_v128_load(p + j + 1)));
	for (; j < n + 5; ++j)
		t2[j] = std::min(p[j], p[j + 1]);
	for (j = 0; j + 8 <= n + 3; j += 8)
		wasm_v128_store(t4 + j, wasm_u16x8_min(wasm_v128_load(t2 + j), wasm_v128_load(t2 + j + 2)));
	for (; j < n + 3; ++j)
		t4[j] = std::min(t2[j], t2[j + 2]);
	for (j = 0; j + 8 <= n; j += 8)
		wasm_v128_store(out + j, wasm_u16x8_min(wasm_v128_load(t4 + j), wasm_v128_load(t4 + j + 3)));
	for (; j < n; ++j)
		out[j] = std::min(t4[j], t4[j + 3]);
}
} // namespace
} // namespace nova::econ
