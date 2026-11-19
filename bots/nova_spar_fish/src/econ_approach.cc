// econ_approach.cc: Walking to the group: progress and crew present.
#include "econ_internal.h"
namespace nova::econ {
namespace {
// The crew-wait bans this body may lift: group and the fail_until the drop wrote (another, longer ban replaces it).
std::array<int, 8> dtl_g{}, dtl_u{};
int dtl_n = 0;
// The bail bans this body may lift: group and the fail_until the drop wrote (another, longer ban replaces it).
std::array<int, 8> bll_g{}, bll_u{};
int bll_n = 0;
// The walk to group gi with living camps blocked. Function-local statics: built on a firing path only.
bitboard& ring_gate_seen_free()
{
	static bitboard b;
	return b;
}
const distance_field* ring_gate_field(int gi)
{
	static distance_field f;
	static bitboard blk, last, tiles, visited;
	static int f_round = -1000;
	if (gi == rgg_f_gi && now() - f_round < 4)
		return &f;
	if (fuel() < 3L * G.w * G.h + 40000) // the flood (~3wh) plus a turn's tail: below this, use the trunk's gate answer
		return gi == rgg_f_gi ? &f : nullptr;
	// Walls with bitboard ops (a per-camp loop cost 8k a call, up to 23k): static walls, camps alive in sight, and camps out of
	// sight unless their group is known dead (cleared, or respawning and not yet due). The dead-tile masks are rebuilt only
	// when some group's status code changes.
	static bitboard dead_m, nofr_m, t1, t2, t3;
	static std::vector<signed char> codes;
	const int ng = static_cast<int>(std::min(static_cast<std::size_t>(M.ng), gmem_size(mem)));
	bool rebuild = static_cast<int>(codes.size()) != ng;
	if (rebuild)
		codes.assign(static_cast<std::size_t>(ng), -1);
	for (int g = 0; g < ng; ++g)
	{
		const auto& om = mem[static_cast<std::size_t>(g)];
		const signed char code = om.status == GS_CLEARED ? 1 : om.status == GS_RESPAWN ? (now() >= om.respawn_at ? 3 : 2) : 0;
		if (code != codes[static_cast<std::size_t>(g)])
		{
			codes[static_cast<std::size_t>(g)] = code;
			rebuild = true;
		}
	}
	if (rebuild)
	{
		dead_m.clear(); // out of sight, open
		nofr_m.clear(); // out of sight: treat as alive whatever the memory says
		for (const auto& c : M.camps)
		{
			const int code = c.group >= 0 && c.group < ng ? codes[static_cast<std::size_t>(c.group)] : 3;
			if (code == 1 || code == 2)
				bbset(dead_m, c.pos);
			else if (code == 3)
				bbset(nofr_m, c.pos);
		}
	}
	const bitboard& fr = ring_gate_seen_free();
	bb3_and(M.camp_tiles, W.vis, t1); // camps in sight
	bb3_and(t1, W.occ_camps, t2);     // of those, alive
	bb3_or(M.block, t2, blk);
	bb3_xor(M.camp_tiles, t1, t3); // camps out of sight
	bb3_and(t3, dead_m, t1);
	t3 ^= t1; // ... not known dead
	blk |= t3;
	if (gi == rgg_f_gi && blk == last) // same walls: the same field
	{
		f_round = now();
		return &f;
	}
	last.clear();
	last |= blk;
	tiles.clear();
	for (int ci : M.groups[static_cast<std::size_t>(gi)].members)
	{
		const vec2 p = M.camps[static_cast<std::size_t>(ci)].pos;
		bbset(tiles, p);
		bbset(blk, p, false);
	}
	visited.clear();
	f.compute(blk, tiles, visited);
	rgg_f_gi = gi;
	f_round = now();
	return &f;
}
// f = mv::group_field(gi). True when I stepped along the live route.
bool ring_gate_walk(int gi, const distance_field* f)
{
	const distance_field* raw = mv::group_field_raw(gi);
	if (gi != rgg_go || !raw || !f || f == raw || dfget_me(*raw) != UNREACH || dfget_me(*f) == UNREACH)
		return false;
	const distance_field* lf = ring_gate_field(gi);
	if (!lf)
		return false;
	const std::uint16_t d = dfget_me(*lf);
	if (d == UNREACH || d <= 1)
		return false;
	return mv::step_field(*lf, gi);
}
bool approach_group(int gi)
{
	last_act = ACT_WALK;
	// Keep the walk out of awake attackers' reach (another group's, or mine woken by someone else, which I cannot take alone now). For
	// 5 rounds after an escape, so the walk does not step back into the reach just left (step_field's camp_threat uses the
	// nearest-champion test and camp_out does not, so with a nearer non-claimant body the two could alternate). Off while my own target
	// is awake (joining a crew that fights it).
	const bool cf_on = now() - cf_esc_round <= 5;
	const mv::AvoidCampReach cf_guard(cf_on && !group_awake(gi));
	const distance_field* f = mv::group_field(gi);
	if (ring_gate_walk(gi, f))
		return true;
	if (M.groups[static_cast<std::size_t>(gi)].access == ACC_TP && !(f && dfget_me(*f) != UNREACH) && crystal_step(gi))
		return true; // walk to the launch tile, then teleport into the walled area
	if (f && M.groups[static_cast<std::size_t>(gi)].access == ACC_WALK && spawn_crystal_group_trip(gi, *f))
		return true; // out of the spawn by a crystal hop
	// A dasher with a long walk to the group takes the dash route across holes when it is clearly shorter (walk steps + 8 rounds per
	// dash), and keeps it for this target so it does not flip between the two routes.
	if (f && ht_state == 1 && dfget_me(*f) != UNREACH && spawn_crossing_turn(gi, *f)) // out of the spawn by a hole dash
		return true;
	if (f && dfget_me(*f) != UNREACH && hole_shortcut_turn(gi, *f)) // the single hole dash that beats the walk
		return true;
	if (f && (crystal_count != 0) && mid_hop_try(*f, gi)) // no crystal, no cost
		return true;
	if (f && dfget_me(*f) != UNREACH)
	{
		if (mv::step_field(*f, gi))
			return true;
	}
	else if (dn::dasher())
	{
		if ((EXPV & 1) && f && island_dash_turn(gi, *f)) // walk to the launch, dash onto the island
			return true;
		// no walk leads there: use the dash route (over holes). Built in spare fuel; extended here when this turn can afford a layer at
		// its worst measured cost.
		if (fuel() > 45000)
			dn::prepare(gi, W.me.pos, 20000);
		if (dn::step(gi))
			return true;
		// Stranded on a launch tile whose landings a teammate holds: go home by recall and free the tile (two dashers facing each other
		// across one hole line would wait for each other forever).
		if (stranded() && dn::blocked_rounds() >= 4 && !T.capturing && recall_safe() && start_recall())
			return true;
	}
	// No field yet (it is built in spare fuel): a short search, or a greedy step when fuel is short.
	const auto& g = M.groups[static_cast<std::size_t>(gi)];
	return mv::step_to(g.anchor, 1, 25, gi);
}
template <int DM>
void track_progress(int gi)
{
	int d = cheb(W.me.pos, M.groups[static_cast<std::size_t>(gi)].anchor);
	bool walk = false;
	bool path = false; // d is a path distance
	std::uint16_t gv = UNREACH;
	const distance_field* tf = gv != UNREACH ? nullptr : mv::group_field(gi);
	if (gv != UNREACH || tf)
	{
		const std::uint16_t v = gv != UNREACH ? gv : dfget_me(*tf);
		if (v != UNREACH)
		{
			d = v;
			walk = true;
			path = true;
		}
	}
	if (dn::dasher() && (!walk || M.has_thin)) // progress along the dash route, or along the shorter hole shortcut
	{
		const int rl = dn::route_len(gi, W.me.pos);
		if (rl != UNREACH && (!walk || rl < d))
		{
			d = rl;
			path = true;
		}
		const int hl = walk ? hole_shortcut_len(gi, W.me.pos) : ((EXPV & 1) ? hole_shortcut_len(gi, W.me.pos) : UNREACH); // progress along the hole shortcut counts; so does the island launch
		if (hl != UNREACH && hl < d)
			d = hl;
	}
	// Turns spent elsewhere (recalling, fleeing, fighting, banking) do not count against the target.
	if ((now() - T.tracked > 2 || cheb(W.me.pos, tpr_pos) >= 4))
	{
		T.best_d = BIG; // the walk back after a recall, respawn or teleport starts a new progress count
		T.best_path = false;
	}
	tpr_pos = W.me.pos;
	if (now() - T.tracked > 2)
		T.progress = now();
	T.tracked = now();
	if (d < T.best_d)
	{
		T.best_d = d;
		T.best_path = path;
		T.progress = now();
	}
	else if (now() - T.progress > 30 && !T.engaged && !T.capturing && T.wait_since < 0)
	{
		NLOG("r%d slot %d drop target %d: no progress\n", now(), P.my_slot, gi);
		drop_target((DM & 1) && dc_is(gi) ? DC_FAIL : 60); // D comes back soon
	}
}
// Crew mates at group gi: allies claiming it within 7 tiles of its anchor, plus allies next to its attackers.
Here crew_here(int gi)
{
	Here h;
	const auto& g = M.groups[static_cast<std::size_t>(gi)];
	std::array<const Body*, 8> bodies{};
	int nb = 0;
	std::vector<Attacker> la_tmp;
	const auto& att = living_attackers_cached(gi, false, la_tmp);
	int seen_claimants = 0;
	const int sup = TM.sup;
	const Body* sup_body = nullptr;
	for (const auto& a : W.allies)
	{
		if (a.channeling() || a.slot < 0)
			continue;
		if (a.slot == sup)
		{
			sup_body = &a; // support, never the tank (added below)
			continue;
		}
		const bool cl = claims(a.slot, gi);
		bool adjacent = false;
		for (const auto& x : att)
			adjacent |= cheb(a.pos, x.pos) <= 1;
		if ((cl && cheb(a.pos, g.anchor) <= 7) || adjacent)
		{
			if (nb < 8)
				bodies[static_cast<std::size_t>(nb++)] = &a;
			if (cl)
				++seen_claimants;
		}
	}
	h.claim_away = std::max(0, claimants(gi) - seen_claimants);
	h.n = nb + 1;
	// The tank: the best camp tank here, preferring melee bodies (they hold camps next to them).
	const int my_order = P.my_slot >= 0 ? P.tank_order[static_cast<std::size_t>(P.my_slot)] : 99;
	const bool me_melee = !W.me.kit->ranged;
	for (int i = 0; i < nb; ++i)
	{
		const Body* b = bodies[static_cast<std::size_t>(i)];
		const bool melee = b->kit && !b->kit->ranged;
		const int order = P.tank_order[static_cast<std::size_t>(b->slot)];
		const bool better = (melee && !me_melee) || (melee == me_melee && order < my_order);
		if (better && b->frac() > 0.35f && (!h.tank || P.tank_order[static_cast<std::size_t>(h.tank->slot)] > order))
			h.tank = b;
	}
	h.tank_is_me = h.tank == nullptr && now() >= T.bench_until;
	// Stats of the bodies here, best tank first.
	std::sort(bodies.begin(), bodies.begin() + nb, [](const Body* a, const Body* b)
		{ return P.tank_order[static_cast<std::size_t>(a->slot)] < P.tank_order[static_cast<std::size_t>(b->slot)]; });
	bool me_added = false;
	for (int i = 0; i < nb; ++i)
	{
		const Body* b = bodies[static_cast<std::size_t>(i)];
		if (!me_added && P.tank_order[static_cast<std::size_t>(b->slot)] > my_order)
		{
			h.crew.add(TM.m[static_cast<std::size_t>(my_slot())]);
			me_added = true;
		}
		h.crew.add(TM.m[static_cast<std::size_t>(b->slot)]);
	}
	if (!me_added)
		h.crew.add(TM.m[static_cast<std::size_t>(my_slot())]);
	// the healer next to its partner heals the crew.
	if (sup_body && cheb(sup_body->pos, g.anchor) <= 9)
	{
		const int ps = TM.partner;
		bool partner_here = ps == my_slot();
		for (int i = 0; i < nb; ++i)
			partner_here |= bodies[static_cast<std::size_t>(i)]->slot == ps;
	}
	return h;
}
// The crew a crew-wait ban waited for is here now: the mates I see within DTL_R of the group's anchor (that claim it; with bit 2,
// any), plus me, in crew_here's order, pass estimate() (the start test of target_turn).
bool crew_wait_crew_here(int gi, bool any)
{
	const auto& g = M.groups[static_cast<std::size_t>(gi)];
	if (g.n_att == 0)
		return true;
	const int rr = DTL_TAB[2];
	std::array<const Body*, 8> bodies{};
	int nb = 0;
	for (const auto& a : W.allies)
	{
		if (a.channeling() || a.slot < 0 || a.slot == TM.sup || cheb(a.pos, g.anchor) > rr || (!any && !claims(a.slot, gi)))
			continue;
		if (nb < 8)
			bodies[static_cast<std::size_t>(nb++)] = &a;
	}
	if (nb == 0)
		return false;
	std::sort(bodies.begin(), bodies.begin() + nb, [](const Body* a, const Body* b)
		{ return P.tank_order[static_cast<std::size_t>(a->slot)] < P.tank_order[static_cast<std::size_t>(b->slot)]; });
	const int my_order = P.my_slot >= 0 ? P.tank_order[static_cast<std::size_t>(P.my_slot)] : 99;
	Crew c;
	bool me_added = false;
	for (int i = 0; i < nb; ++i)
	{
		const Body* b = bodies[static_cast<std::size_t>(i)];
		if (!me_added && P.tank_order[static_cast<std::size_t>(b->slot)] > my_order)
		{
			c.add(TM.m[static_cast<std::size_t>(my_slot())]);
			me_added = true;
		}
		c.add(TM.m[static_cast<std::size_t>(b->slot)]);
	}
	if (!me_added)
		c.add(TM.m[static_cast<std::size_t>(my_slot())]);
	const int cx0 = cxc_ctx;
	const bool ok = estimate_cx(4, g, mem[static_cast<std::size_t>(gi)], c).feasible;
	cxc_ctx = cx0;
	return ok;
}
// Remember a crew-wait ban (called right after its drop_target), unless the crew test passes already (then it is no missing crew).
void crew_wait_ban_mark(int gi, int rounds)
{
	if (gi < 0 || gi >= mem_n || mem[static_cast<std::size_t>(gi)].fail_until != now() + rounds || crew_wait_crew_here(gi, false))
		return; // a longer ban was there already, or the crew test passes: not this ban's case
	int k = 0;
	while (k < dtl_n && dtl_g[static_cast<std::size_t>(k)] != gi)
		++k;
	if (k == dtl_n)
	{
		if (dtl_n < 8)
			++dtl_n;
		else
			k = 0; // full: the oldest goes
	}
	dtl_g[static_cast<std::size_t>(k)] = gi;
	dtl_u[static_cast<std::size_t>(k)] = mem[static_cast<std::size_t>(gi)].fail_until;
}
// Once a turn before the target choice: lift each remembered ban whose crew is here now; forget expired or replaced ones.
void crew_wait_ban_pass()
{
	int k = 0;
	for (int i = 0; i < dtl_n; ++i)
	{
		const int gi = dtl_g[static_cast<std::size_t>(i)];
		const int u = dtl_u[static_cast<std::size_t>(i)];
		if (gi >= mem_n)
			continue;
		auto& m = mem[static_cast<std::size_t>(gi)];
		if (m.fail_until <= now() || m.fail_until != u)
			continue;
		if (crew_wait_crew_here(gi, false))
		{
			m.fail_until = now(); // lifted: rate_for and the other choosers see it free this turn
			T.eval_round = std::min(T.eval_round, now() - PLAN_EVAL_EVERY); // choose again now
			continue;
		}
		dtl_g[static_cast<std::size_t>(k)] = gi;
		dtl_u[static_cast<std::size_t>(k)] = u;
		++k;
	}
	dtl_n = k;
}
// Remember a bail ban (called right after its drop_target(25)); a drop that wrote no 25-round ban (a 0 estimate, a longer ban kept)
// is skipped.
void bail_ban_remember(int gi)
{
	if (gi < 0 || gi >= mem_n || mem[static_cast<std::size_t>(gi)].fail_until != now() + 25)
		return;
	int k = 0;
	while (k < bll_n && bll_g[static_cast<std::size_t>(k)] != gi)
		++k;
	if (k == bll_n)
	{
		if (bll_n < 8)
			++bll_n;
		else
			k = 0; // full: the oldest goes
	}
	bll_g[static_cast<std::size_t>(k)] = gi;
	bll_u[static_cast<std::size_t>(k)] = mem[static_cast<std::size_t>(gi)].fail_until;
}
// The bail's reason has lapsed: I am healthy, no foe near the group, and a healthy melee claimant holds an awake member I see.
static bool bail_ban_lapsed(int gi)
{
	if (W.me.frac() * 100.0f < static_cast<float>(BLL_TAB[2]))
		return false;
	const vec2 an = M.groups[static_cast<std::size_t>(gi)].anchor;
	for (const auto& e : W.enemies)
		if (cheb(e.pos, an) <= 8)
			return false;
	for (const auto& vc : W.camps)
	{
		if (!vc.awake || vc.ci < 0)
			continue;
		const auto& cp = M.camps[static_cast<std::size_t>(vc.ci)];
		if (cp.group != gi || !cp.attacks())
			continue;
		for (const auto& a : W.allies)
			if (cheb(a.pos, cp.pos) <= 1 && claims(a.slot, gi) && a.kit && !a.kit->ranged && a.frac() > 0.5f && !a.channeling())
				return true;
	}
	return false;
}
// Once a turn before the target choice: lift each remembered bail ban whose reason has lapsed; forget expired or replaced ones.
void bail_ban_lift_lapsed()
{
	int k = 0;
	for (int i = 0; i < bll_n; ++i)
	{
		const int gi = bll_g[static_cast<std::size_t>(i)];
		const int u = bll_u[static_cast<std::size_t>(i)];
		if (gi >= mem_n)
			continue;
		auto& m = mem[static_cast<std::size_t>(gi)];
		if (m.fail_until <= now() || m.fail_until != u)
			continue;
		if (bail_ban_lapsed(gi) || nova::econ::camp_crew::heal_lift(gi))
		{
			m.fail_until = now(); // lifted: rate_for and the other choosers see it free this turn
			T.eval_round = std::min(T.eval_round, now() - PLAN_EVAL_EVERY); // choose again now
			continue;
		}
		bll_g[static_cast<std::size_t>(k)] = gi;
		bll_u[static_cast<std::size_t>(k)] = u;
		++k;
	}
	bll_n = k;
}
} // namespace
} // namespace nova::econ

// ---------------------------------------------------------------- camp crews waiting on a heal. Unity build: compiled only through
// nova_all.cpp, after econ_*.cc.
namespace nova::econ::camp_crew
{
inline constexpr int BLH_QUIET = 15; // rounds with no foe seen near the group
inline constexpr int BLH_R = 8;      // foe radius around the anchor
__attribute__((noinline)) bool blh_fire() { return true; }
bool heal_lift(int gi)
{
	using namespace nova::econ;
	if (gi < 0 || gi >= M.ng || W.me.frac() * 100.0f < static_cast<float>(BLL_TAB[2]))
		return false;
	if (now() - mem[static_cast<std::size_t>(gi)].enemy_seen < BLH_QUIET)
		return false;
	const vec2 an = M.groups[static_cast<std::size_t>(gi)].anchor;
	for (const auto* lst : { &W.enemies, &W.enemies_far })
		for (const auto& e : *lst)
			if (cheb(e.pos, an) <= BLH_R)
				return false;
	return blh_fire();
}
// per-camp health at this body's last sighting (0 = seen dead) and its round (-1: none); per-group 'has sightings'.
static std::vector<float> lsh_h;
static std::vector<int> lsh_at;
static std::vector<std::uint8_t> lsh_g;
} // namespace nova::econ::camp_crew
