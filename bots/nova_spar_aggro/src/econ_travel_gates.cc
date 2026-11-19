// econ_travel_gates.cc: Gates on my way: dash routes and gate state.
#include "econ_internal.h"
namespace nova::econ {
namespace {

// The living group of camps that blocks my walk to group gi (a gate: e.g. a wolf wall across the spawn exit), or -1. Only for groups
// that no walk reaches with every other camp tile blocked; then the walk down the group's camps-passable field from here, preferring
// tiles that are free now, finds the first living camp of another group that every shortest way crosses. Dead camps (seen empty, or
// remembered cleared/respawning) do not block. Cached for a few rounds per target and position (each traced step reads 8 field
// cells).
struct GateSeen
{
	int gi = -1, gate = -1, round = -1000;
	vec2 from{ -1, -1 };
};
GateSeen GS;
// Gatekeeper deadlock: bodies could take clusters behind the spawn exit's wolf wall, be "at" them by the camps-passable distance,
// engage them (no attackers) and stand next to the wall until round 2000 (an engaged target is never re-evaluated). Work on the gate
// first when the econ would take it (the crew logic gathers the team for it); otherwise leave the target for a while. True when the
// target changed.
int gate_try = -1, gate_since = -1000, gate_last = -1000; // the gate I keep being sent to, and since when
// set up the call (flag read first; zero work at 0)
static void stored_travel_begin()
{
	xtt.v = 0;
	const int v = XT_V;
	if (!W.alive || !xt_ready() || !(xt_dense() || travel_table_build(60000)))
		return;
	xtt.D = travel_table(&xtt.n, &xtt.S, &xtt.DER);
	if (!xtt.D || xtt.n != M.ng)
		return;
	xtt.v = v;
	xtt.nr = XT_NEAR;
	xtt.row = nullptr;
	xtt.cg = -1;
	for (int k = 0; k < 3; ++k)
	{
		xtt.a[k] = -1;
		xtt.av[k] = UNREACH;
	}
	xtt.hd = -1;
	xtt.pend.clear();
	const int ci = M.camp_index(W.me.pos);
	if (ci >= 0 && ci < M.nc)
		xtt.cg = M.camps[static_cast<std::size_t>(ci)].group;
	if (xtt.cg >= 0 && xtt.cg < xtt.n)
		xtt.row = xtt.D + static_cast<std::size_t>(xtt.cg) * static_cast<std::size_t>(xtt.n);
	else
		xtt.cg = -1;
	if (M.has_home)
	{
		const std::uint16_t h = dfget_me(M.f_home);
		if (h != UNREACH && static_cast<int>(h) <= xtt.nr)
			xtt.hd = static_cast<int>(h);
	}
}
// group i's value v (from its field, UNREACH = none). Returns true when i is deferred to the pass after the loop (bit 2).
static inline bool stored_travel_group(int i, std::uint16_t& v)
{
	if (xtt.row && i != xtt.cg) // bit 1: on a camp tile every group field reads UNREACH here (or the camps-open field)
	{
		const std::uint16_t d = xtt.row[i];
		if (d != UNREACH)
		{
			v = d;
			++xtt.fired_cg;
			return false;
		}
	}
	if (!(xtt.v & 2))
		return false;
	if (v == UNREACH)
	{
		xtt.pend.push_back(i);
		return true;
	}
	if (v < xtt.av[2])
	{
		int k = 2;
		for (; k > 0 && v < xtt.av[k - 1]; --k)
		{
			xtt.av[k] = xtt.av[k - 1];
			xtt.a[k] = xtt.a[k - 1];
		}
		xtt.av[k] = v;
		xtt.a[k] = i;
	}
	return false;
}
// bit 2: a deferred group's walk = min(nearest built group's walk + stored walk, home walk + stored spawn walk), each only within
// XT_NEAR; else Chebyshev x 4/3 + 2.
static std::uint16_t stored_travel_deferred(int i)
{
	// Upper bounds (triangle inequality): walk to a built group + its stored walk on; home walk + the spawn walk. Lower bound: stored
	// walk from a built group minus my walk to it. Near an anchor (<= XT_NEAR) the best upper bound is the estimate; farther, Chebyshev
	// x 4/3 + 2 clamped into [lower, upper].
	int ub = -1, lb = 0, hub = -1;
	bool near = false;
	for (int k = 0; k < 3 && xtt.a[k] >= 0; ++k)
	{
		const std::size_t ix = static_cast<std::size_t>(xtt.a[k]) * static_cast<std::size_t>(xtt.n) + static_cast<std::size_t>(i);
		const std::uint16_t dd = xtt.D[ix];
		if (dd == UNREACH)
			continue;
		const bool der = xtt.DER[ix] != 0; // a derived pair is an upper bound only: no lower bound from it
		const int d = dd;
		const int av = static_cast<int>(xtt.av[k]);
		if (ub < 0 || av + d < ub)
			ub = av + d;
		if (!der && d - av > lb)
			lb = d - av;
		if (av <= xtt.nr)
			near = true;
	}
	if (xtt.hd >= 0 && xtt.S[i] != UNREACH)
	{
		const int d = xtt.S[i];
		{
			if (ub < 0 || xtt.hd + d < ub)
				ub = xtt.hd + d;
			near = true;
		}
	}
	if (xtt.S[i] != UNREACH) // a looser upper bound through our spawn (clamp only): anchor -> spawn -> group
		for (int k = 0; k < 3 && xtt.a[k] >= 0; ++k)
			if (xtt.S[xtt.a[k]] != UNREACH)
			{
				const int h = static_cast<int>(xtt.av[k]) + static_cast<int>(xtt.S[xtt.a[k]]) + static_cast<int>(xtt.S[i]);
				if (hub < 0 || h < hub)
					hub = h;
			}
	int est = std::min(60000, cheb(W.me.pos, M.groups[static_cast<std::size_t>(i)].anchor) * 4 / 3 + 2);
	xtt.kind = 0;
	if (near && ub >= 0)
	{
		est = ub;
		xtt.kind = 2;
	}
	else
	{
		if (est < lb)
		{
			est = lb;
			xtt.kind = 4;
		}
		const int cap = ub >= 0 && (hub < 0 || ub < hub) ? ub : hub;
		if (cap >= 0 && est > cap)
		{
			est = cap;
			xtt.kind = 4;
		}
	}
	if (xtt.kind != 0)
		++xtt.fired_near;
	return static_cast<std::uint16_t>(std::min(60000, est));
}
static int starved_map_bits()
{
	const int b = STV_TAB[1];
	if (stv_c < 0)
	{
		if (!M.ready() || M.groups.empty())
			return 0;
		int tot = 0, dsh = 0;
		for (const auto& g : M.groups)
		{
			tot += g.gems;
			if (g.access == ACC_DASH)
				dsh += g.gems;
		}
		stv_c = (tot > 0 && tot <= STV_TAB[2] && dsh * 100 >= STV_TAB[3] * tot) ? 1 : 0;
	}
	return stv_c ? (b & 31) : 0;
}
static bool pocket_on_own_side(int gi)
{
	static std::vector<std::int8_t> own; // -1 unknown, 0 no, 1 yes (static map data, once per group)
	if (own.size() != static_cast<std::size_t>(M.ng))
		own.assign(static_cast<std::size_t>(M.ng), -1);
	auto& o = own[static_cast<std::size_t>(gi)];
	if (o < 0)
	{
		const distance_field* fp = &M.f_enemy;
		const vec2 a = M.groups[static_cast<std::size_t>(gi)].anchor;
		int dh = BIG, de = BIG;
		for (int dx = -4; dx <= 4; ++dx)
			for (int dy = -4; dy <= 4; ++dy)
			{
				const vec2 u{ a.x + dx, a.y + dy };
				if (!inb(u))
					continue;
				const int k = std::max(iabs(dx), iabs(dy));
				const int h = dfget(M.f_home, u), e = dfget(*fp, u);
				if (h != UNREACH)
					dh = std::min(dh, h + k);
				if (e != UNREACH)
					de = std::min(de, e + k);
			}
		o = (dh < BIG && dh < de) ? 1 : 0;
	}
	return o == 1;
}
// The pocket joins a home-side body's home loop instead of pulling a fighter. Per turn: own-side pocket, I stand home-side (walk
// from our spawn <= walk from theirs), no mate claims it, no mate in a fight or coming to one (claim kinds 4/5) and no fresh FIGHT
// call, and the team is quiet (nobody saw a foe or took an unseen hit for QK_QTR rounds).
static bool pocket_joins_home_loop(int gi)
{
	if (!pocket_on_own_side(gi) || !W.alive)
		return false;
	const distance_field* fp = static_cast<cambc::distance_field *>(&M.f_enemy); // pocket_on_own_side true built the field
	if (!fp)
		return false;
	const int mh = dfget_me(M.f_home), me = dfget_me(*fp);
	if (mh == UNREACH || (me != UNREACH && mh > me))
		return false;
	for (int s = 0; s < comms::CLAIM_SLOTS; ++s)
	{
		if (s == my_slot())
			continue;
		if (comms::cgroup(s) == gi)
			return false;
		if ((comms::V.ck[static_cast<std::size_t>(s)] == 4 || comms::V.ck[static_cast<std::size_t>(s)] == 5))
			return false;
	}
	if (comms::fl_call.r >= now() - comms::FL_TAB[2])
		return false;
	return team_quiet();
}
static bool group_outside_walk(int gi)
{
	if (M.groups[static_cast<std::size_t>(gi)].access == ACC_WALK)
		return false;
	const distance_field* f = mv::group_field(gi);
	return !f || dfget_me(*f) == UNREACH;
}
static void island_dash_travel()
{
	if (!dn::dasher() || !W.alive)
		return;
	for (std::size_t i = 0; i < static_cast<std::size_t>(M.ng) && i < travel.size(); ++i)
		if (M.groups[i].access != ACC_WALK && travel[i] == UNREACH)
		{
			if ((starved_map_bits() & 16) != 0 && M.groups[i].access == ACC_DASH && group_outside_walk(static_cast<int>(i)) && !pocket_joins_home_loop(static_cast<int>(i)))
				continue; // the hole-launch route serves only the home loop; dash-navigation routes stay as they are
			const int hl = hole_shortcut_len(static_cast<int>(i), W.me.pos);
			if (hl != UNREACH)
				travel[i] = static_cast<std::uint16_t>(std::min(hl + 2, 60000));
		}
}
// one field read per walkable group (mv::group_dist_here)
template <bool ONE_READ>
void compute_travel_t()
{
	PROF("travel0");
	travel.assign(static_cast<std::size_t>(M.ng), UNREACH);
	const int sc_mode = spawn_crystal_travel_mode();
	const bool strand = stranded();
	const long dash_floor = fuel() - 8000; // at most ~8k on dash-only groups per call (lengths are memoised)
	int dash_n = 0;
	// A recall (6 rounds with the arrival) and the walk from spawn is a route too, while one can start here: only while the recall
	// could really start and finish now, and never for an engaged or capturing body.
	const bool gdn = false;
	travel_gdn = gdn;
	stored_travel_begin(); // EXACT_TRAVEL (plan.h): xtt.v stays 0 when off
	for (std::size_t i = 0; i < static_cast<std::size_t>(M.ng); ++i)
	{
		const auto& g = M.groups[i];
		if (g.access != ACC_WALK)
		{
			if (g.access == ACC_TP && crystal_ok(static_cast<int>(i)))
			{
				const CPlan& c = cplans[i];
				travel[i] = static_cast<std::uint16_t>(std::min(60000, c.cost + static_cast<int>(dfget_me(M.f_home)) + (OWR_TAB[2]))); // + the recall home (OWR bit 4: the real recall)
				continue;
			}
			if (dn::dasher() && fuel() > 40000 && (dash_n++ < TCF_TAB[4])) // dash-only groups over the routes built, counted
			{
				const int rl = dn::route_len(static_cast<int>(i), W.me.pos);
				if (rl != UNREACH)
					travel[i] = static_cast<std::uint16_t>(std::min(rl, 60000));
			}
			continue;
		}
		std::uint16_t v = UNREACH; // the camps-blocked walk from my best neighbour
		if constexpr (ONE_READ)
			v = mv::group_dist_here(static_cast<int>(i));
		else if (const distance_field* f = mv::group_field_ready(static_cast<int>(i)))
			v = dfget_me(*f);
		if (v == UNREACH && strand)
			continue; // on an island no walk leads there (the recall home does)
		if (xtt.v != 0 && stored_travel_group(static_cast<int>(i), v))
			continue; // after the loop
		if (v == UNREACH)
			v = static_cast<std::uint16_t>(std::min(60000, cheb(W.me.pos, g.anchor) * 4 / 3 + 2));
 // recall travel as a rating term; no call at flag 0 (compute_travel caps its own fuel per call: dash_floor)
		if (ht_state == 1) // trunk2: no call at flag 0 (compute_travel caps its own fuel per call: dash_floor)
			v = spawn_crossing_travel(static_cast<int>(i), v); // out of the spawn by a hole dash
		travel[i] = sc_mode ? spawn_crystal_travel(static_cast<int>(i), v, sc_mode) : v;
	}
	if (xtt.v != 0) // the deferred groups
		for (const int i : xtt.pend)
		{
			std::uint16_t v = stored_travel_deferred(i);
			if (ht_state == 1)
				v = spawn_crossing_travel(i, v);
			travel[static_cast<std::size_t>(i)] = sc_mode ? spawn_crystal_travel(i, v, sc_mode) : v;
		}
	if (EXPV & 1)
		island_dash_travel(); // after the loop, so the loop runs the same instructions with and without it (its 8k dash window)
	travel_round = now();
	travel_from = W.me.pos;
	PROF("travel");
}
void compute_travel()
{
	if (M.ng >= BOUNDS_MIN_GROUPS)
		compute_travel_t<true>();
	else
		compute_travel_t<false>();
}
// Gated altars open once a gate group is dead (cleared, or respawning but not due soon). An enemy tribute on a
// map whose altars are all gated also tells us the gate is open, unless we have seen it alive since.
bool gate_open()
{
	const int sig = M.ring ? ring_signal : gate_signal; // on a ring map their tribute says nothing of our side
	bool seen_alive_since_signal = false;
	bool unseen_since_signal = false; // some gate not seen alive since the signal
	for (int gi : M.gate_groups)
	{
		if (gi < 0 || gi >= static_cast<int>(gmem_size(mem)))
			continue;
		const auto& m = mem[static_cast<std::size_t>(gi)];
		if (m.status == GS_CLEARED || (m.status == GS_RESPAWN && m.respawn_at - now() > 15))
			return true;
		if (m.status == GS_ALIVE && m.seen > sig)
			seen_alive_since_signal = true;
		else
			unseen_since_signal = true;
	}
	return now() - sig < 60 && !seen_alive_since_signal;
}
// Gate-mate bank field: the bank walk's field to the open gate tiles (static walls only, as f_altar_open), rebuilt when the open set
// changes. Function-local statics: built on the first gated bank walk only, so other maps keep their heap layout.
const distance_field* gate_mate_bank_field(const bitboard& open_adj)
{
	static distance_field gm_f;
	static bitboard gm_roots;
	static bool gm_ok = false;
	if (gm_ok && gm_roots == open_adj)
		return &gm_f;
	if (fuel() < 33000L + 3L * G.w * G.h)
		return nullptr; // no fuel for a rebuild this turn: fall back to the plain bank walk
	bitboard visited;
	gm_f.compute(M.block, open_adj, visited);
	gm_roots = open_adj;
	gm_ok = true;
	return &gm_f;
}
bool dash_bankable() { return dash_bank_flag; }
void update_dash_bank()
{
	dash_bank_flag = !M.any_altar && (M.gate_groups.empty() || M.ring) && M.ready() && dn::dasher() && dn::route_len(dn::GOAL_ALTAR, W.me.pos) != UNREACH;
	nwc_bank_flag = nwc_map() && sc_bank_f == &bank_field() && sc_bank_r.cost != UNREACH;
}
const std::array<int, 3>& gates(int gi)
{
	if (gate_of.size() != static_cast<std::size_t>(M.ng))
	{
		gate_of.assign(static_cast<std::size_t>(M.ng), std::array<int, 3>{ -1, -1, -1 });
		gate_done.assign(static_cast<std::size_t>(M.ng), 0);
	}
	const auto i = static_cast<std::size_t>(gi);
	if (gate_done[i] || !M.has_home || GT.round == now() || (fuel() < 50000))
		return gate_of[i];
	return gates_step(gi);
}
// the gates' work after its early return
const std::array<int, 3>& gates_step(int gi)
{
	const auto i = static_cast<std::size_t>(gi);
	const distance_field* hcb = mv::home_field_cb();
	if (!hcb)
		return gate_of[i];
	GT.round = now();
	const FView fh = fview(M.f_home);
	if (GT.gi < 0)
	{
		const auto& g = M.groups[i];
		if (g.d_home == UNREACH || M.group_dist_blocked(*hcb, g) != UNREACH)
		{
			gate_done[i] = 1;
			return gate_of[i];
		}
		GT = GateTrace{};
		GT.gi = gi;
		GT.round = now();
		// gates unknown until the trace ends: the group counts as open meanwhile
		for (int ci : g.members)
		{
			const vec2 q = M.camps[static_cast<std::size_t>(ci)].pos;
			const std::uint16_t v = fh(q);
			if (v < GT.cur)
			{
				GT.cur = v;
				GT.p = q;
			}
		}
	}
	// Advance the trace in progress (it may belong to another group than the one asked about).
	const int tg = GT.gi;
	const auto ti = static_cast<std::size_t>(tg);
	const BView vc = bview(M.camp_tiles);
	for (int it = 0; it < 12 && GT.p.x >= 0 && GT.cur > 0 && GT.cur != UNREACH; ++it)
	{
		vec2 nb{ -1, -1 };
		bool nb_camp = true;
#pragma clang loop unroll(full)
		for (const vec2 d : DIRS)
		{
			const vec2 q = GT.p + d;
			if (!inb(q) || fh(q) != GT.cur - 1)
				continue;
			const bool camp = vc(q);
			if (nb.x < 0 || (nb_camp && !camp))
			{
				nb = q;
				nb_camp = camp;
				if (!camp)
					break;
			}
		}
		if (nb.x < 0)
		{
			GT.p = vec2{ -1, -1 };
			break;
		}
		GT.p = nb;
		GT.cur = static_cast<std::uint16_t>(GT.cur - 1);
		if (nb_camp)
		{
			const int ci = M.camp_index(GT.p);
			const int og = ci >= 0 ? M.camps[static_cast<std::size_t>(ci)].group : -1;
			if (og >= 0 && og != tg && GT.n < 3 && og != gate_of[ti][0] && og != gate_of[ti][1])
				gate_of[ti][static_cast<std::size_t>(GT.n++)] = og;
		}
	}
	if (GT.p.x < 0 || GT.cur == 0 || GT.cur == UNREACH)
	{
		gate_done[ti] = 1;
		GT.gi = -1;
		NLOG("GATES g %d: %d %d %d\n", tg, gate_of[ti][0], gate_of[ti][1], gate_of[ti][2]);
	}
	return gate_of[i];
}
// A group behind a gate that is alive and that the whole team cannot clear is out of reach.
bool behind_closed_gate(int gi)
{
	for (const int og : gates(gi))
	{
		if (og < 0)
			continue;
		const auto& m = mem[static_cast<std::size_t>(og)];
		if (m.status == GS_CLEARED || m.status == GS_RESPAWN)
			continue;
		if (!team_feasible(og))
			return true;
	}
	return false;
}
// Walking distance to the nearest member tile of a group (cached field), Chebyshev to the anchor as a fallback.
int path_dist(int gi)
{
	std::uint16_t gv = UNREACH;
	const distance_field* pf = gv != UNREACH ? nullptr : mv::group_field(gi);
	if (gv != UNREACH || pf)
	{
		const std::uint16_t v = gv != UNREACH ? gv : dfget_me(*pf);
		if (v != UNREACH)
		{
			// a dash route over holes that is already built and shorter counts (no layer is built here).
			if (dn::dasher() && M.has_thin)
			{
				const int rl = dn::route_len(gi, W.me.pos);
				if (rl != UNREACH && rl < v)
					return rl;
				const int hl = (hole_shortcut_is_top(gi) || ht_choice()) ? hole_shortcut_len(gi, W.me.pos) : UNREACH; // the built hole shortcut (top groups only for banking; every built one when hole travel is on)
				if (hl != UNREACH && hl < v)
					return hl;
			}
			return v;
		}
	}
	if (dn::dasher()) // across holes, the dash route's length
	{
		const int rl = dn::route_len(gi, W.me.pos);
		if (rl != UNREACH)
			return rl;
	}
	return cheb(W.me.pos, M.groups[static_cast<std::size_t>(gi)].anchor);
}
template <int DM>
int gate_on_way(int gi)
{
	if (gi == GS.gi && W.me.pos == GS.from && now() - GS.round < 4)
		return GS.gate;
	const distance_field* raw = mv::group_field_raw(gi);
	if (!raw || dfget_me(*raw) != UNREACH || fuel() < 30000)
		return -1;
	const distance_field* f = mv::group_field(gi); // the camps-passable field when I am cut off
	if (!f || f == raw)
		return -1;
	GS = GateSeen{ gi, -1, now(), W.me.pos };
	vec2 p = W.me.pos;
	std::uint16_t cur = dfget(*f, p);
	if (cur == UNREACH)
		return -1;
	const BView vc = bview(M.camp_tiles);
	for (int it = 0; it < 16 && cur > 1; ++it)
	{
		vec2 next{ -1, -1 };
		int gate = -1;
		bool open = false;
#pragma clang loop unroll(full)
		for (const vec2 d : DIRS)
		{
			const vec2 q = p + d;
			if (!inb(q) || dfget(*f, q) != cur - 1)
				continue;
			int og = -1;
			if (vc(q))
			{
				const int ci = M.camp_index(q);
				og = ci >= 0 ? M.camps[static_cast<std::size_t>(ci)].group : -1;
				if (og >= 0 && og != gi)
				{
					const auto& om = mem[static_cast<std::size_t>(og)];
					const bool alive = bbget(W.vis, q) ? bbget(W.occ_camps, q)
														: !(om.status == GS_CLEARED || om.status == GS_RESPAWN);
					if (!alive)
						og = -1;
				}
				else
					og = -1;
			}
			if (og < 0)
			{
				next = q;
				open = true;
				break;
			}
			if (gate < 0)
			{
				gate = og;
				next = q;
			}
		}
		if (next.x < 0)
			return -1;
		if (!open)
		{
			if (const distance_field* lf = ring_gate_field(gi); lf && gi == rgg_f_gi && dfget_me(*lf) != UNREACH)
			{
				rgg_go = gi;
				return -1;
			}
			GS.gate = gate;
			return gate;
		}
		p = next;
		cur = static_cast<std::uint16_t>(cur - 1);
	}
	return -1;
}
template <int DM>
bool redirect_to_gate(int gi)
{
	const int og = gate_on_way<DM>(gi);
	if (og < 0 || og == gi)
		return false;
	auto& om = mem[static_cast<std::size_t>(og)];
	if (og != gate_try || now() - gate_last > 60)
	{
		gate_try = og;
		gate_since = now();
	}
	gate_last = now();
	float r = -1;
	int crew = 1;
	if (now() - gate_since > 30)
	{
		// The crew did not gather in 30 rounds: farm on this side for a while.
		om.fail_until = std::max(om.fail_until, now() + 30);
		gate_since = now() + 30;
	}
	else if (om.fail_until <= now() && reachable_target(og))
	{
		build_team(false);
		const int d = path_dist(og);
		const Claims cl = claims_for_me();
		r = rate_for<DM>(og, my_slot(), static_cast<std::uint16_t>(std::min(d, 60000)), cl, free_near(), &crew);
		// No free crew in sight (every body holds a target, often one behind the same gate: those bodies are sent
		// here too): worth a try when the bodies here (its claimants, and allies within 8 that are not fighting)
		// could clear it together.
		if (r <= 0)
		{
			Crew c;
			c.add(TM.m[static_cast<std::size_t>(my_slot())]);
			for (int s = 0; s < TM.n; ++s)
			{
				const auto ss = static_cast<std::size_t>(s);
				if (s == my_slot() || s == TM.sup || TM.busy[ss])
					continue;
				bool here = cl[ss] == og;
				for (const auto& a : W.allies)
					here |= a.slot == s && !a.channeling() && cheb(a.pos, W.me.pos) <= 8;
				if (here)
					c.add(TM.m[ss]);
			}
			if (c.n > 1 && estimate_cx(2, M.groups[static_cast<std::size_t>(og)], om, c).feasible)
			{
				r = 0.01f;
				crew = c.n;
			}
		}
	}
	NLOG("r%d slot %d gate %d blocks target %d rate %.3f crew %d\n", now(), P.my_slot, og, gi, r, crew);
	if (r > 0)
	{
		set_target(og, r, std::max(1, crew));
		// Committed for a while (no re-evaluation): the gate's crew rate is low until the crew is here, and the
		// target behind it would win every re-evaluation. The crew wait still drops it when nobody comes.
		T.filler_until = now() + 15;
	}
	else
		drop_target(30);
	return true;
}
} // namespace
const std::vector<GroupMem>& memory() { return mem; }
// Recall timing bit 128: rounds from the turn a recall is decided to the first turn the body acts on its spawn. Measured on local
// games: a kept spin (started at the previous turn end) 4, a fresh recall 5; GameRules:387 5 turn ends, 3 with Home (no spin with
// Home).
int csx_recall_t()
{
	return cbn_recall_t(); // the rule's table with the spin's real state, not the constant 4 the old spin rule assumed
}
// camp ci is known dead. Seen: no camp on its tile. Unseen: its group's memory says cleared, or respawning and not due yet (the test
// fogged_camp_group_near_landing uses in the combat files). Callers read the flag first.
bool camp_known_dead(int ci)
{
	if (ci < 0 || ci >= M.nc)
		return false;
	const CampI& c = M.camps[static_cast<std::size_t>(ci)];
	if (bbget(W.vis, c.pos))
		return !bbget(W.occ_camps, c.pos);
	if (c.group < 0 || static_cast<std::size_t>(c.group) >= mem.size())
		return false;
	const GroupMem& gm = mem[static_cast<std::size_t>(c.group)];
	return gm.status == GS_CLEARED || (gm.status == GS_RESPAWN && gm.respawn_at > W.round);
}
} // namespace nova::econ
