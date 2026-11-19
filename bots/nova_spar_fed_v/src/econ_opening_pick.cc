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
bool oc_wait = false; // the last turn deferred: this turn's fresh fuel goes to the pass, not to opening_prestep
int op_pre_g = -1;
int op_pre_steps = 0;
static int om_sg_n = 0, om_op_n = 0, om_first = -1;
// In rounds 1..START_ROUNDS no body stands near our spawn with nothing to do. The start goal is the group a body walks toward before
// it has a target: the best value per walk (gems + gold/2, the opening's own gold weight, over distance + 10) among the groups worth
// something on our side (walk distances once known, else straight lines from the spawn anchors); heavy groups only when nothing else
// is on our side. Every body computes the same goal from static data, so the team leaves the spawn together; the opening target
// replaces it when known.
int start_g = -1;
bool start_g_fixed = false; // computed from walk distances: final
int start_steps = 0; // count of start steps
int spw_prev_r = -10;
// a body with no target whose choice the fuel gate skipped on PES_K consecutive own turns runs a bounded choice: the PES_N nearest
// walkable groups (travel), each rated exactly while >= PES_FLOOR is left. Called only after the gate, with no target.
int pes_last = -1000, pes_n = 0;
__attribute__((noinline)) bool opening_choice_defer()
{
	if (opr_round >= 0) // a stopped pass resumes without this gate (its own stop prices the rest)
	{
		oc_wait = false;
		return false;
	}
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
	oc_wait = late;
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
// hoard-crew mode 2/3: rate_for<2> and the hoard bounds, and the hoard seeds.
template <bool HC, int DM = (HC ? 2 : 0)> // DM: BB8_ON(8) rates mode 3 with the DOM terms
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
		// the zone crew left at setup for the entry group: no other body counts on them.
		for (int s = 0; s < TM.n && s < 8; ++s)
			if (zc::is_crew(s))
			{
				OP.cl[static_cast<std::size_t>(s)] = zc::opening_target() >= 0 ? zc::opening_target() : -1;
				OP.done[static_cast<std::size_t>(s)] = true;
			}
		vesper_open::claim(OP.cl, OP.done);
		if constexpr (HC)
			opening_hoard_seed(out_rate, out_crew);
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
			if (fuel() < OPENING_RESERVE + 6000)
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
			if (fuel() < OPENING_RESERVE + std::min(op_worst_rate, 30000L))
			{
				TM.round = -1;
				return -2; // continue with this candidate next turn
			}
			int cc = 1;
			const long f_rate = fuel();
			const float rr = rate_for<HC ? 2 : 0>(gi, s, M.groups[static_cast<std::size_t>(gi)].d_home, cl, OP.free, &cc); // BB8 bit 8: mode 3 rates with DOM terms
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
	// the full simulation ran and left me without a group. Every body it left without one (not the healer, who follows her partner)
	// joins, in tank order, the drafted crew whose team rate it raises most (base stats, spawn walks: the same assignment on every body
	// that runs it). Resumable per body like the simulation.
	if (choice < 0 && OP.i >= TM.n)
	{
		for (; OP.j < TM.n; ++OP.j)
		{
			const int b = TM.by_tank[static_cast<std::size_t>(OP.j)];
			if (cl[static_cast<std::size_t>(b)] >= 0 || b == TM.sup)
				continue;
			if (fuel() < OPENING_RESERVE + 8000)
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
				}
			}
		}
	}
	vesper_open::rate(choice, out_rate, out_crew);
	TM.round = -1; // rebuild with live stats next time
	return choice;
}
} // namespace
} // namespace nova::econ
