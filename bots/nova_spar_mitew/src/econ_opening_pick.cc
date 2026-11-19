// econ_opening_pick.cc: The opening: which group each body takes first.
#include "econ_internal.h"
namespace nova::econ {
namespace {
long op_worst_rate = 0;                  // review i2: costliest single rate_for in the opening simulation
// The first group_bounds pass has no check of its own and the 46k gate does not cover it. Priced per map from the group count (table
// 340-640 per group, first loop 750-850 per group), measured once a pass ran; the table is its own step so that a turn pays at most
// one of the two. The rest of the turn after the pass needs ~12k.
constexpr long OC_TAIL = 12000;
fg::Cost oc_gb;
int oc_defers = 0;
int op_pre_g = -1;
// In rounds 1..START_ROUNDS no body stands near our spawn with nothing to do. The start goal is the group a body walks toward before
// it has a target: the best value per walk (gems + gold/2, the opening's own gold weight, over distance + 10) among the groups worth
// something on our side (walk distances once known, else straight lines from the spawn anchors); heavy groups only when nothing else
// is on our side. Every body computes the same goal from static data, so the team leaves the spawn together; the opening target
// replaces it when known.
int start_g = -1;
bool start_g_fixed = false; // computed from walk distances: final
int spw_prev_r = -10;
// a body with no target whose choice the fuel gate skipped on PES_K consecutive own turns runs a bounded choice: the PES_N nearest
// walkable groups (travel), each rated exactly while >= PES_FLOOR is left. Called only after the gate, with no target.
int pes_last = -1000, pes_n = 0;
__attribute__((noinline)) bool opening_choice_defer()
{
	if (opr_round >= 0) // a stopped pass resumes without this gate (its own stop prices the rest)
		return false;
	const long n = static_cast<long>(static_cast<std::size_t>(M.ng));
	bool late = false;
	if (static_cast<int>(n) >= BOUNDS_MIN_GROUPS && gbs_tab.size() != static_cast<std::size_t>(M.ng))
	{
		if (fuel() < 700L * n + OC_TAIL)
			late = true;
		else
			group_static_table(sg_any());
	}
	if (!late)
		late = fuel() < std::min(70000L, (oc_gb.hi > 0 ? oc_gb.hi : 850L * n) + OC_TAIL);
	if (late && oc_defers >= 3)
		late = false; // three turns at most: then the full pass, whatever it costs
	if (late)
	{
		++oc_defers;
		TM.round = -1;
	}
	return late;
}
// the body at position i of the opening simulation: by_tank order, or with bit 1 the gold carrier first, then by_tank without her.
static int opening_sim_body_at(int i)
{
	if (P.carrier_gold < 0 || P.carrier_gold >= TM.n)
		return TM.by_tank[static_cast<std::size_t>(i)];
	if (i == 0)
		return P.carrier_gold;
	int k = 0;
	for (int j = 0; j < TM.n; ++j)
	{
		const int s = TM.by_tank[static_cast<std::size_t>(j)];
		if (s == P.carrier_gold)
			continue;
		if (++k == i)
			return s;
	}
	return TM.by_tank[static_cast<std::size_t>(i)];
}
// the first HC_OPEN_N bodies (tank order) go to the biggest hoard when our walk to it is at most the enemy's + HC_OPEN_SLACK.
void opening_hoard_seed(float* out_rate, int* out_crew)
{
	int h = -1;
	for (int gi = 0; gi < M.ng; ++gi)
	{
		const auto& g = M.groups[static_cast<std::size_t>(gi)];
		if (hc_group(gi) && g.d_home != UNREACH && (g.d_enemy == UNREACH || g.d_home <= g.d_enemy + HC_OPEN_SLACK) &&
			(h < 0 || hoard_gems(gi) > hoard_gems(h) ||
				(hoard_gems(gi) == hoard_gems(h) && hoard_region_id(gi) >= 0 &&
					(g.gems > M.groups[static_cast<std::size_t>(h)].gems ||
						(g.gems == M.groups[static_cast<std::size_t>(h)].gems && g.d_home < M.groups[static_cast<std::size_t>(h)].d_home)))))
			h = gi;
	}
	// one body per region group, best groups first (gems, then nearest home), all passing the slack test.
	std::array<int, HC_OPEN_N> hr_pick;
	hr_pick.fill(h);
	int hr_n = 1;
	const int hr = h >= 0 ? hoard_region_id(h) : -1;
	if (hr >= 0)
	{
		hr_n = 0;
		for (int q = 0; q < HC_OPEN_N; ++q)
		{
			int b = -1;
			for (int gi = 0; gi < M.ng; ++gi)
			{
				const auto& g = M.groups[static_cast<std::size_t>(gi)];
				if (hoard_region_id(gi) != hr || g.d_home == UNREACH || (g.d_enemy != UNREACH && g.d_home > g.d_enemy + HC_OPEN_SLACK))
					continue;
				bool taken = false;
				for (int u = 0; u < q; ++u)
					taken = taken || hr_pick[static_cast<std::size_t>(u)] == gi;
				if (taken)
					continue;
				const auto* bg = b >= 0 ? &M.groups[static_cast<std::size_t>(b)] : nullptr;
				if (!bg || g.gems > bg->gems || (g.gems == bg->gems && g.d_home < bg->d_home))
					b = gi;
			}
			if (b < 0)
				break;
			hr_pick[static_cast<std::size_t>(q)] = b;
			++hr_n;
		}
		if (hr_n == 0)
		{
			hr_pick.fill(h);
			hr_n = 1;
		}
	}
	for (int i = 0, k = 0; h >= 0 && i < TM.n && k < HC_OPEN_N; ++i)
	{
		const int s = TM.by_tank[static_cast<std::size_t>(i)];
		if (s < 0 || s >= 8 || OP.done[static_cast<std::size_t>(s)])
			continue;
		const int tg = hr_pick[static_cast<std::size_t>(k % hr_n)];
		OP.cl[static_cast<std::size_t>(s)] = tg;
		OP.done[static_cast<std::size_t>(s)] = true;
		++k;
		if (s == my_slot())
		{
			*out_rate = 1.0f;
			*out_crew = hr >= 0 ? (HC_OPEN_N + hr_n - 1 - (k - 1) % hr_n) / hr_n : HC_OPEN_N;
		}
	}
}
// v724 DFG (spec_dfg_1111): the draft's opening record, one group + crew bit per body slot (dmem extra 8 = bits 0-31, extra 6 = bits
// 32-63; per slot bit_width(M.ng) bits group, all-ones none, then the crew bit). The same tests on every body; any failure = no record.
namespace dfg {
int st = 0;      // 0 not read, 1 none, 2 read
int stage = 0;   // 0 not used yet, 1 my first pick took it, 2 seen as my target, 3 ended (live logic for good)
int rn = 0, me_s = -1;
long floor_f = 0; // the draft's hard budget: the simulation stops (returns -2) under this much fuel (0 in play)
std::array<int, 8> rg{}, rc{}, rt{}; // per slot: record group, crew bit, the roster's champion type
int why = -1;                          // diag: read's verdict (0 read; 1 no extra 8; 2 shape; 3 slot types differ; 4 group range; 5 no 6)
cambc::champion_type my_t{}; // my type (bit 2's kit)
int gwidth(int ng)
{
	int w = 0;
	while (w < 31 && (1 << w) <= ng)
		++w;
	return w;
}
int my_slot_raw(int& n) // P before setup; raw roster (handle order, as build_plan) in a pre-setup turn
{
	if (P.n > 0)
	{
		n = P.n;
		for (int i = 0; i < n && i < 8; ++i)
			rt[static_cast<std::size_t>(i)] = static_cast<int>(P.type[static_cast<std::size_t>(i)]);
		if (P.my_slot >= 0 && P.my_slot < 8)
			my_t = P.type[static_cast<std::size_t>(P.my_slot)];
		return P.my_slot;
	}
	static int cn = -1, cs = -1;
	if (cn < 0)
	{
		const auto allies = roster(team::ally);
		const auto mh = static_cast<std::uint32_t>(cambc::detail::sdk_my_champion());
		cn = static_cast<int>(std::min<std::size_t>(allies.size(), 8));
		for (int i = 0; i < cn; ++i)
			rt[static_cast<std::size_t>(i)] = static_cast<int>(allies[static_cast<std::size_t>(i)].type);
		for (int i = 0; i < cn; ++i)
			if (allies[static_cast<std::size_t>(i)].h == mh)
			{
				cs = i;
				my_t = allies[static_cast<std::size_t>(i)].type;
			}
	}
	n = cn;
	return cs;
}
// The record is used only when the slot types the draft stored (extra 7, 4 bits a slot) are the roster's, slot by slot (RC C96 DFO1:
// picks are simultaneous, so the fielded order can differ from the draft's guess).
int read_i()
{
	if (dmem::extra(8, 0u) != dmem::extra(8, 1u))
		return 1; // extra 8 absent
	int n = 0;
	const int me = my_slot_raw(n);
	const int gw = gwidth(M.ng);
	const int tot = n * (gw + 1);
	if (n < 1 || n > 8 || me < 0 || me >= n || M.ng < 1 || tot > 64 || dmem::extra(7, 0u) != dmem::extra(7, 1u))
		return 2;
	const std::uint32_t ty = dmem::extra(7, 0u);
	for (int s = 0; s < n; ++s)
		if (static_cast<int>((ty >> (4 * s)) & 15u) != rt[static_cast<std::size_t>(s)])
			return 3;
	std::uint64_t w = dmem::extra(8, 0u);
	if (tot > 32)
	{
		if (dmem::extra(6, 0u) != dmem::extra(6, 1u))
			return 5; // overflow word absent
		w |= static_cast<std::uint64_t>(dmem::extra(6, 0u)) << 32;
	}
	const std::uint64_t ones = (1ULL << gw) - 1ULL;
	for (int s = 0; s < n; ++s)
	{
		const int at = s * (gw + 1);
		const std::uint64_t g = (w >> at) & ones;
		if (g != ones && g >= static_cast<std::uint64_t>(M.ng))
			return 4;
		rg[static_cast<std::size_t>(s)] = g == ones ? -1 : static_cast<int>(g);
	}
	rn = n;
	me_s = me;
	return 0;
}
void read()
{
	why = read_i();
	st = why == 0 ? 2 : 1;
}
// The record ends at my first camp hit, an enemy in sight, my group respawning (cleared), or a retarget after it was my target.
bool ended()
{
	if (stage == 3)
		return true;
	if (st != 2)
		return false;
	const int g = rg[static_cast<std::size_t>(me_s)];
	bool end = g < 0 || T.engaged || T.capturing || !W.enemies.empty();
	if (!end && static_cast<std::size_t>(g) < gmem_size(mem) && mem[static_cast<std::size_t>(g)].status == GS_RESPAWN)
		end = true;
	if (!end && stage >= 1 && T.target >= 0)
	{
		if (T.target == g)
			stage = 2;
		else if (stage == 2)
			end = true;
	}
	if (end)
		stage = 3;
	return end;
}
// Bit 1: my first opening pick is the record's group (every body's row from the record, no simulation), rated once for me with the
// others' rows; a group rated <= 0 ends the record. Asked once a game.
int apply(float* out_rate, int* out_crew)
{
	static bool asked = false;
	if (asked || stage != 0)
		return -1;
	asked = true;
	if (st == 0 && M.groups_ready())
		read();
	const int me = my_slot();
	if (st != 2 || rn != TM.n || me != me_s || me < 0 || me >= 8 || OP.done[static_cast<std::size_t>(me)] || ended())
	{
		stage = 3;
		return -1;
	}
	const int g = rg[static_cast<std::size_t>(me)];
	Claims c2 = OP.cl;
	int cnt = 0;
	for (int s = 0; s < TM.n && s < 8; ++s)
	{
		if (!OP.done[static_cast<std::size_t>(s)])
			c2[static_cast<std::size_t>(s)] = rg[static_cast<std::size_t>(s)];
		cnt += c2[static_cast<std::size_t>(s)] == g ? 1 : 0;
	}
	Claims cr = c2; // my rating: the others' rows, my own crew's not counted (as the simulation rates a body before drafting its crew)
	for (int s = 0; s < TM.n && s < 8; ++s)
		if (s == me || cr[static_cast<std::size_t>(s)] == g)
			cr[static_cast<std::size_t>(s)] = -1;
	int cc = 1;
	const float rr = rate_for<0>(g, me, M.groups[static_cast<std::size_t>(g)].d_home, cr, std::max(0, cnt - 1), &cc);
	if (!(rr > 0.0f))
	{
		stage = 3;
		return -1;
	}
	OP.cl = c2;
	for (int s = 0; s < TM.n && s < 8; ++s)
		OP.done[static_cast<std::size_t>(s)] = true;
	OP.i = TM.n;
	OP.j = TM.n;
	OP.sim = false;
	*out_rate = rr;
	*out_crew = std::max(1, cnt);
	stage = 1;
	return g;
}
} // namespace dfg
// hoard-crew mode 2/3: rate_for<2> and the hoard bounds, and the hoard seeds.
template <bool HC, int DM = (HC ? 2 : 0)> // DM: unused (BB8 bit 8's DOM terms not shipped)
__attribute__((noinline)) int opening_pick(float* out_rate, int* out_crew)
{
	build_team(true);
	if (!OP.started)
	{
		OP.started = true;
		OP.cl.fill(-1);
		OP.done.fill(false);
		OP.i = 0;
		OP.j = 0;
		vesper_open::claim(OP.cl, OP.done);
		if constexpr (HC)
			opening_hoard_seed(out_rate, out_crew);
	}
	if constexpr (!HC)
		{
			const int dg = dfg::apply(out_rate, out_crew);
			if (dg >= 0)
			{
				vesper_open::rate(dg, out_rate, out_crew);
				TM.round = -1;
				return dg;
			}
		}
	Claims& cl = OP.cl;
	auto& done = OP.done;
	int choice = -1;
	for (; OP.i < TM.n && choice < 0; ++OP.i)
	{
		const int i = OP.i;
		const int s = opening_sim_body_at(i);
		if (done[static_cast<std::size_t>(s)])
		{
			if (s == my_slot())
				choice = cl[static_cast<std::size_t>(s)];
			continue; // drafted into an earlier body's crew
		}
		if (!OP.sim)
		{
			if (fuel() < OPENING_RESERVE + 6000 || (fuel() < dfg::floor_f)) // v724 DFG: the draft's budget
			{
				TM.round = -1;
				return -2;
			}
			if (opening_choice_defer()) // a pass under way resumes ungated
				return -2; // see OC_TAIL above
			OP.free = 0;
			for (int j = i + 1; j < TM.n; ++j)
				OP.free += done[static_cast<std::size_t>(opening_sim_body_at(j))] ? 0 : 1;
			if (i == 0 && s == P.carrier_gold)
				OP.free = 0; // the carrier's first choice is a solo group
			if constexpr (!HC)
			{
				opr_on = true;
				opr_stop = false;
				opr_slot = s;
			}
			const long oc_f0 = fuel();
			const int oc_r0 = fg::rnd();
			group_bounds(s, nullptr, true, OP.cand);
			if constexpr (HC)
				hoard_crew_bounds(OP.cand, false);
			fg::note(oc_gb, fg::fuel_used_since(oc_f0, oc_r0));
			if (!HC && opr_on)
			{
				opr_on = false;
				if (opr_stop)
				{
					opr_stop = false;
					TM.round = -1;
					return -2; // the pass goes on next turn from its place
				}
			}
			OP.k = 0;
			OP.best = -1;
			OP.best_crew = 1;
			OP.best_r = 0;
			OP.sim = true;
		}
		for (; OP.k < OP.cand.size(); ++OP.k)
		{
			const auto [ub, gi] = OP.cand[OP.k];
			if (ub <= OP.best_r)
				break;
			if (fuel() < OPENING_RESERVE + std::min(op_worst_rate, 30000L) || (fuel() < dfg::floor_f)) // v724 DFG
			{
				TM.round = -1;
				return -2; // continue with this candidate next turn
			}
			int cc = 1;
			const long f_rate = fuel();
			const float rr = rate_for<HC ? 2 : 0>(gi, s, M.groups[static_cast<std::size_t>(gi)].d_home, cl, OP.free, &cc); // mode 2 or 0, no DOM terms (BB8 bit 8 not shipped)
			op_worst_rate = std::max(op_worst_rate, f_rate - static_cast<long>(fuel()));
			if (rr > OP.best_r)
			{
				OP.best_r = rr;
				OP.best = gi;
				OP.best_crew = cc;
			}
		}
		OP.sim = false;
		NLOG("r%d slot %d opening sim body %d rated %d of %d best %d rate %.3f fuel %ld\n", now(), P.my_slot, s,
			static_cast<int>(std::min(OP.k + 1, OP.cand.size())), static_cast<int>(OP.cand.size()), OP.best, OP.best_r, fuel());
		const float r = OP.best_r;
		const int crew = OP.best_crew;
		const int g = OP.best;
		cl[static_cast<std::size_t>(s)] = g;
		done[static_cast<std::size_t>(s)] = true;
		if (g >= 0)
		{
			// The crew this choice needs is drafted now: the bodies it counted on take the same group.
			const int others = claimants(g, s, cl);
			if (crew > others + 1)
			{
				Claims extras;
				crew_for(g, s, crew - others - 1, cl, &extras);
				for (int e : extras)
					if (e >= 0)
					{
						cl[static_cast<std::size_t>(e)] = g;
						done[static_cast<std::size_t>(e)] = true;
						if (e == my_slot())
						{
							*out_rate = r;
							*out_crew = crew;
							choice = g;
						}
					}
			}
		}
		if (s == my_slot())
		{
			*out_rate = r;
			*out_crew = crew;
			choice = g;
		}
	}
	// the full simulation ran and left me without a group. Every body it left without one
	// joins, in tank order, the drafted crew whose team rate it raises most (base stats, spawn walks: the same assignment on every body
	// that runs it). Resumable per body like the simulation.
	if (choice < 0 && OP.i >= TM.n)
	{
		for (; OP.j < TM.n; ++OP.j)
		{
			const int b = TM.by_tank[static_cast<std::size_t>(OP.j)];
			if (cl[static_cast<std::size_t>(b)] >= 0)
				continue;
			if (fuel() < OPENING_RESERVE + 8000 || (fuel() < dfg::floor_f)) // v724 DFG
			{
				TM.round = -1;
				return -2; // continue with this body next turn
			}
			int best_g = -1, best_c = 1;
			float best_d = 0;
			for (int gi = 0; gi < M.ng; ++gi)
			{
				int cc = 1;
				const float d = join_gain(gi, b, M.groups[static_cast<std::size_t>(gi)].d_home, cl, -1, &cc);
				if (d > best_d)
				{
					best_d = d;
					best_g = gi;
					best_c = cc;
				}
			}
			if (best_g >= 0)
			{
				cl[static_cast<std::size_t>(b)] = best_g;
				if (b == my_slot())
				{
					*out_rate = best_d;
					*out_crew = best_c;
					choice = best_g;
					break; // v683 FB29: later bodies' cl[] is never read (opening_group_held needs done[] too)
				}
			}
		}
	}
	vesper_open::rate(choice, out_rate, out_crew);
	TM.round = -1; // rebuild with live stats next time
	return choice;
}
} // namespace
// v724 DFG: the record's group for me while it stands (bit 1's start goal), else -1. Needs the groups built.
int dfg_goal()
{
	if (dfg::stage >= 3 || !M.groups_ready())
		return -1;
	if (dfg::st == 0)
		dfg::read();
	if (dfg::st != 2 || dfg::ended())
		return -1;
	return dfg::rg[static_cast<std::size_t>(dfg::me_s)];
}
bool hoard_crew_decide();
long dfg_draft_fuel = -1; // diag: fuel the draft record took (-1 not run)
// v724 DFG, draft side (extras 7 slot types, 8 + 6 the record): the opening simulation for the planned lineup on the static map, run once per body as that body (its own row
// with its own terms), with play's round-1 state: base stats on the spawn anchor, no target, no foe seen, no claims. Draft instance only
// (it never plays). Writes extras 8 (+6) when every row finished with >= 3.5M of the turn left; hoard-crew maps write nothing.
namespace {
Body dfg_body(int s)
{
	Body b{};
	b.h = P.handle[static_cast<std::size_t>(s)];
	b.slot = s;
	b.ally = true;
	b.type = P.type[static_cast<std::size_t>(s)];
	b.kit = &kit_of(b.type);
	b.pos = M.home_anchor;
	b.hp = b.kit->hp;
	b.maxhp = std::max(1.0f, b.kit->hp);
	b.str = b.kit->str;
	b.foc = b.kit->foc;
	b.range = b.kit->range;
	b.state = ST_ALIVE | ST_CAN_MOVE | ST_CAN_ATTACK | ST_CAN_CAST;
	return b;
}
// Round 1 as play sees it: me alive on the spawn, every mate alive and in sight on the spawn (crews form from them).
void dfg_put_me(int s)
{
	P.my_slot = s;
	W.me = dfg_body(s);
	W.alive = true;
	W.allies.clear();
	for (int t = 0; t < P.n; ++t)
		if (t != s)
			W.allies.push_back(dfg_body(t));
}
} // namespace
bool dfg_draft_plan(const std::array<cambc::champion_type, 8>& ty, int n, std::uint8_t pflags, int s2s)
{
	dfg::st = 1; // the draft never reads a record
	dfg::stage = 3;
	if (n < 1 || n > 8 || !M.done() || M.ng <= 0 || fuel() < 4000000)
		return false;
	const int gw = dfg::gwidth(M.ng);
	if (n * (gw + 1) > 64)
		return false;
	const long f0 = fuel();
	const Plan p0 = P;
	const int r0 = W.round;
	const Body me0 = W.me;
	const bool os0 = W.on_spawn, al0 = W.alive;
	const std::vector<Body> allies0 = W.allies;
	bool ok = false;
	std::array<int, 8> g_of{}, c_of{};
	try
	{
		P = Plan{};
		P.n = n;
		for (int i = 0; i < n; ++i)
		{
			const auto si = static_cast<std::size_t>(i);
			P.handle[si] = 0x7F000001u + static_cast<std::uint32_t>(i);
			P.type[si] = ty[si];
			P.party[si] = -1;
			P.role[si] = ROLE_SOLO;
		}
		if (XCF_ON(4)) // v775 XCF bit 4 PSL1
			P.prism_at = plan_prism_scan();
		P.lead = { -1, -1 };
		P.flags = pflags;
		P.s2s = s2s;
		P.from_memory = true;
		plan_tank_order();
		plan_carriers();
		plan_capture_order();
		W.round = 1;
		W.on_spawn = true;
		dfg_put_me(0);
		init();
		TM.round = -1;
		build_team(true);
		const int dc = dom_commit_decide();
		ok = !(dc != 0 && hoard_crew_decide()); // hoard-crew mode: play runs opening_pick<true>; no record
		dfg::floor_f = 3500000; // hard budget: >= 3.5M of the 10M turn stays (the draft turn stays under 7M with the sim)
		for (int s = 0; s < n && ok; ++s)
		{
			dfg_put_me(s);
			OP = Opening{};
			T = Task{};
			opened = false;
			op_prestepped = false;
			TM.round = -1;
			op_worst_rate = 0;
			oc_defers = 0;
			opr_round = -1000;
			float r = 0;
			int c = 1, g = -2;
			for (int k = 0; k < 8 && g == -2 && fuel() > dfg::floor_f; ++k)
				g = opening_pick<false>(&r, &c);
			if (g == -2 || fuel() < dfg::floor_f)
				ok = false;
			if (g >= M.ng)
				g = -1;
			int crew = 0; // drafted into a crew: a body earlier in the simulation order holds the same group
			if (g >= 0)
				for (int i = 0; i < TM.n && opening_sim_body_at(i) != s; ++i)
					crew |= OP.cl[static_cast<std::size_t>(opening_sim_body_at(i))] == g ? 1 : 0;
			g_of[static_cast<std::size_t>(s)] = g;
			c_of[static_cast<std::size_t>(s)] = crew;
		}
	}
	catch (...)
	{
		ok = false;
	}
	dfg::floor_f = 0;
	P = p0;
	W.round = r0;
	W.me = me0;
	W.on_spawn = os0;
	W.alive = al0;
	W.allies = allies0;
	dfg_draft_fuel = f0 - fuel();
	if (!ok)
		return false;
	std::uint64_t w = 0;
	const std::uint64_t ones = (1ULL << gw) - 1ULL;
	for (int s = 0; s < n; ++s)
	{
		const int g = g_of[static_cast<std::size_t>(s)];
		const int at = s * (gw + 1);
		w |= (g < 0 ? ones : static_cast<std::uint64_t>(g)) << at;
		w |= static_cast<std::uint64_t>(c_of[static_cast<std::size_t>(s)] & 1) << (at + gw);
	}
	std::uint32_t tw = 0; // the slot types the record was made for (play drops it on any difference)
	for (int s = 0; s < n; ++s)
	{
		const int tv = static_cast<int>(ty[static_cast<std::size_t>(s)]);
		if (tv < 0 || tv > 15)
			return false;
		tw |= static_cast<std::uint32_t>(tv) << (4 * s);
	}
	const int tot = n * (gw + 1);
	dmem::extra_put(7, tw, 4 * n);
	dmem::extra_put(8, static_cast<std::uint32_t>(w & 0xFFFFFFFFULL), std::min(tot, 32));
	if (tot > 32)
		dmem::extra_put(6, static_cast<std::uint32_t>(w >> 32), tot - 32);
	else
		dmem::extra_clear(6);
	return true;
}
} // namespace nova::econ
