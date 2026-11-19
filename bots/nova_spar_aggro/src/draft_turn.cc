// draft_turn.cc: play_draft: the draft turn.
#include "draft_internal.h"
namespace nova::drafting {
namespace {
// State shared by the steps of one draft turn.
struct DraftTurn
{
	std::vector<champion_draft> ours;
	std::uint16_t have = 0;
	[[maybe_unused]] long f_init = 0, f_feat = 0, f_plan = 0;
	[[maybe_unused]] const char* how = "plan";
	[[maybe_unused]] bool first_values = false;
	Step st;
	float top = 0.0f;
	std::uint16_t top_m = 0;
	int choice = -1;
};

// Takes plan step t as the pick, its top value and its top lineup.
static __attribute__((always_inline)) inline void adopt_plan_step(DraftTurn& d, int t)
{
	d.st = PL.step[static_cast<std::size_t>(t)];
	d.choice = d.st.pick;
	d.top = PL.top;
	d.top_m = PL.top_m;
}

// Re-plans on the adjusted S.base when the fuel allows and adopts the new plan's step.
static __attribute__((always_inline)) inline void replan_and_adopt(DraftTurn& d)
{
	if (fuel() > plan_estimate() + 40000)
	{
		enumerate_all(S.min_dash);
		if (make_plan(d.have, S.min_dash))
		{
			const int t2 = plan_step(d.have);
			if (t2 >= 0)
				adopt_plan_step(d, t2);
		}
	}
}

// Step 1: map analysis, first turn only (about 1M fuel; resumable stages). Its distances and access bytes go to the champions through
// draft memory.
static __attribute__((always_inline)) inline void analyse_map(DraftTurn& d)
{
	if (!S.analysed && fuel() > 400000)
	{
		M.want_dash = true;
		M.init(150000);
		S.analysed = M.done();
	}
	d.f_init = fuel();
}

// Step 2: map features -> values. Without them: team-size values and the cheap rules, never random.
static __attribute__((always_inline)) inline void compute_values(DraftTurn& d)
{
	if (S.analysed && !S.feat_tried && fuel() > 260000)
	{
		map_features();
		d.first_values = S.values;
	}
	if (!S.values)
	{
		cheap_rules();
		set_values(false);
		d.first_values = true;
	}
	d.f_feat = fuel();
}

// Step 3: the plan: decided once, followed on later turns at no cost. Rebuilt from the cache only when our picks left it (a failed pick),
// and only when the measured cost fits.
static __attribute__((always_inline)) inline void follow_or_rebuild_plan(DraftTurn& d)
{
	int t = plan_step(d.have);
	if (t < 0)
	{
		// The cache is built only when the plan can follow it in the same turn.
		if (!cached && fuel() > plan_estimate() + 40000)
		{
			const long f0 = fuel();
			enumerate_all(S.min_dash);
			S.cost_enum = f0 - fuel();
		}
		if (cached)
		{
			if (fuel() > replan_estimate(d.have) + 30000)
			{
				const long f0 = fuel();
				if (make_plan(d.have, S.min_dash))
					t = plan_step(d.have);
				S.cost_plan = std::max(S.cost_plan, f0 - fuel());
			}
		}
	}
	d.f_plan = fuel();
	if (t >= 0)
		adopt_plan_step(d, t);
}

// Read only when the plan holds C&I, so every other draft is untouched.
static __attribute__((always_inline)) inline void demote_ci_in_band(DraftTurn& d)
{
	if (d.have == 0 && S.values && S.map_term && cached && PL.ok && (PL.top_m >> CI & 1) && M.done())
	{
		long tot = 0, own = 0;
		for (const auto& g : M.groups)
		{
			tot += g.gems;
			if (g.gems > 0 && g.n_clu == g.nm && g.d_home != UNREACH && g.contest < 0.35f)
				own += g.gems;
		}
		if (ci_layer::draft_band(own, tot))
		{
			S.base[CI] -= 1000.0f;
			replan_and_adopt(d);
			if (d.choice == CI)
				d.choice = -1; // the greedy fallback reads S.base: no C&I there either
		}
	}
}

// A runtime flag, no #if, so the switch-off build has the same code.
static __attribute__((always_inline)) inline void swap_vesper_for_marcella(DraftTurn& d)
{
	if (d.have == 0 && S.values && cached && PL.ok && M.done() && !(PL.top_m >> MA & 1) && !dash_term_keeps(VV, MA))
	{
		try
		{
			bool ryma = false;
			ryma = marcella_for_ryth_band();
			int from = -1;
			if (!ryma)
			{
				int altd = UNREACH;
				for (const auto& a : M.altars)
					if (a.d_home != UNREACH)
						altd = std::min(altd, static_cast<int>(a.d_home));
				const bool arm1 = altd != UNREACH && altd <= MI_ALTD && (PL.top_m >> VV & 1);
				if (arm1)
				{
					from = VV;
				}
			}
			if (from >= 0)
			{
				S.base[static_cast<std::size_t>(from)] -= 1000.0f;
				S.base[static_cast<std::size_t>(MA)] += 1000.0f;
				replan_and_adopt(d);
				if (d.choice == from)
					d.choice = -1; // The greedy fallback reads S.base: no FROM there either.
			}
		}
		catch (...)
		{
		}
	}
}

// A runtime flag, no #if, so the switch-off build has the same code.
static __attribute__((always_inline)) inline void swap_by_cell_table(DraftTurn& d)
{
	if (d.have == 0 && S.values && cached && PL.ok && M.done())
	{
		try
		{
			const int passes = 1; // Test arm in cell 0, then the live cells on its lineup.
			for (int pass = 0; pass < passes; ++pass)
			{
				// Where Prism is viable she is forced first (below), so the lineup we field is the plan with Prism held: judge FROM / TO on that
				// plan (PL restored).
				std::uint16_t eff = PL.top_m;
				if (S.pz_viable && !(d.have >> PR & 1))
				{
					const auto pl0 = PL;
					if (fuel() > replan_estimate(bit(PR)) + 60000 && make_plan(static_cast<std::uint16_t>(d.have | bit(PR)), S.min_dash))
						eff = static_cast<std::uint16_t>(PL.top_m | bit(PR));
					PL = pl0;
				}
				const int code = passes == 1 ? draft_swap_cell_code(eff, S.pz_viable) : pass == 0 ? draft_swap_cell_code(eff, S.pz_viable, 0, 1) : draft_swap_cell_code(eff, S.pz_viable, 1, DSW_N);
				const int from = (code & 15) - 1, to = (code >> 4 & 15) - 1;
				if (from >= 0 && from < NC && to >= 0 && to < NC && from != to)
				{
					const bool has_from = (eff >> from & 1) || (from == PR && S.pz_viable);
					const bool has_to = (eff >> to & 1) || (to == PR && S.pz_viable);
					if (has_from && !has_to)
					{
						if (from == PR)
							S.pz_viable = false;
						if (to == PR)
							S.pz_viable = true; // Prism viable, first pick, her carry plan.
						S.base[static_cast<std::size_t>(from)] -= 1000.0f;
						S.base[static_cast<std::size_t>(to)] += 1000.0f;
						replan_and_adopt(d);
						if (d.choice == from)
							d.choice = -1; // The greedy fallback reads S.base: no FROM there either.
					}
				}
			}
		}
		catch (...)
		{
		}
	}
}

// The flag is read first; 0 does nothing.
static __attribute__((always_inline)) inline void exchange_by_cell_table(DraftTurn& d)
{
	if (d.have == 0 && S.values && cached && PL.ok && M.done())
	{
		try
		{
			std::uint16_t eff = PL.top_m;
			if (S.pz_viable)
			{
				const auto pl0 = PL;
				if (fuel() > replan_estimate(bit(PR)) + 60000 && make_plan(bit(PR), S.min_dash))
					eff = static_cast<std::uint16_t>(PL.top_m | bit(PR));
				PL = pl0;
			}
			const int code = draft_swap_cell_code(eff, S.pz_viable, 0, DXC_N, DXC_TAB);
			const int from = (code & 15) - 1, to = (code >> 4 & 15) - 1;
			if (from >= 0 && from < NC && to >= 0 && to < NC && from != to && (eff >> from & 1) && !(eff >> to & 1))
			{
				if (from == PR)
					S.pz_viable = false;
				if (to == PR)
					S.pz_viable = true;
				for (int c = 0; c < NC; ++c)
					if ((eff >> c & 1) && c != from)
						S.base[static_cast<std::size_t>(c)] += 3000.0f;
				S.base[static_cast<std::size_t>(from)] -= 5000.0f;
				S.base[static_cast<std::size_t>(to)] += 5000.0f;
				replan_and_adopt(d);
				if (d.choice == from)
					d.choice = -1;
			}
		}
		catch (...)
		{
		}
	}
}

// Where her carry plan pays (set_values), Prism is our first pick and the rest come from the draft.
static __attribute__((always_inline)) inline void force_prism_first(DraftTurn& d)
{
	if (S.pz_viable && !(d.have >> PR & 1))
	{
		d.choice = PR;
	}
}

// A forced Ryth (TO, its +1000 persists in S.base over the draft turns) is not turned into Marcella.
static __attribute__((always_inline)) inline void marcella_for_forced_ryth(DraftTurn& d)
{
	const bool ds_ry = S.base[RY] > 500.0f;
	if (d.choice == RY && !ds_ry && !(d.have >> MA & 1) && marcella_for_ryth_band())
		d.choice = MA; // Marcella in Ryth's pick on heavy 5-body maps.
}

// Flag first; an override of the plan's step is held in a rebuilt plan while the fuel allows.
static __attribute__((always_inline)) inline void hold_override_in_plan(const DraftTurn& d)
{
	if (d.choice >= 0 && d.choice < NC && !(d.have >> d.choice & 1) && cached && PL.ok)
	{
		const int t0 = plan_step(d.have);
		if (t0 < 0 || PL.step[static_cast<std::size_t>(t0)].pick != d.choice)
		{
			const std::uint16_t hc = static_cast<std::uint16_t>(d.have | bit(d.choice));
			if (fuel() > replan_estimate(hc) + 60000)
			{
				const auto pl0 = PL;
				if (!make_plan(hc, S.min_dash))
					PL = pl0;
			}
		}
	}
}

// Fallback: the table's marginal values (own value and composition given our picks) with the dash rule.
static __attribute__((always_inline)) inline void greedy_fallback_pick(DraftTurn& d, int& picked)
{
	d.how = "greedy";
	d.st = Step{};
	d.top_m = 0;
	if (!S.values)
	{
		try
		{
			set_values(false);
		}
		catch (...)
		{
		}
	}
	std::array<float, NC> gv{};
	const auto order = greedy_order(d.have, S.min_dash, &gv);
	for (int i = 0; i < NC && picked < 0; ++i)
	{
		const int c = order[static_cast<std::size_t>(i)];
		if (try_pick(c, d.have))
			picked = c;
	}
	// Explanation: the marginal value of the pick and its margin over the best other champion.
	if (picked >= 0)
		for (int i = 0; i < NC; ++i)
		{
			const int c = order[static_cast<std::size_t>(i)];
			if (c != picked && !(d.have >> c & 1))
			{
				d.st.pick = picked;
				d.st.next = c;
				d.st.next_regret = gv[static_cast<std::size_t>(c)];
				d.st.regret = gv[static_cast<std::size_t>(picked)] - gv[static_cast<std::size_t>(c)];
				d.top = gv[static_cast<std::size_t>(picked)];
				break;
			}
		}
}

// After the pick: the zone model and the stored walks (resumable over draft turns), then the hand-off to team memory.
static __attribute__((always_inline)) inline void finish_after_pick(const DraftTurn& d, int picked)
{
	// The zone model runs after the pick (the pick is unchanged), resumable over draft turns, leaving the memory encode and submit
	// their fuel.
	try
	{
		const long enc = S.mem.empty() ? (S.cost_encode > 0 ? S.cost_encode : 6000L + 220L * static_cast<long>(static_cast<std::size_t>(M.ng) + static_cast<std::size_t>(M.na))) : 0L;
		const long sub = S.cost_submit > 0 ? S.cost_submit + 3000L : 4000L + 16L * static_cast<long>(zone::BLOCK_END);
		// Margin 18k (24k cost the zone block on some maps). A turn that runs out is resumed and finished by the draft-resume step
		// (main.cc).
		if (M.done() && !zone::ready() && zone::draft_step(enc + sub + 18000L, team_size()))
		{
		}
		if (M.done()) // The stored walks, resumable over draft turns.
			travel_build_step(std::max(enc + sub + 26000L, 2500000L)); // leaves 2.5M of the 10M first draft turn; none on 100k turns
	}
	catch (...)
	{
	}
	try
	{
		auto after = d.ours;
		after.push_back(static_cast<champion_draft>(picked));
		handoff(after);
	}
	catch (...)
	{
	}
}
} // namespace

void play_draft()
{
	const long f_start = fuel();
	++S.turn;
	DraftTurn d;
	std::vector<champion_draft> theirs;
	try
	{
		d.ours = cambc::draft::current_draft(team::ally);
		theirs = cambc::draft::current_draft(team::enemy);
	}
	catch (...)
	{
	}
	d.have = lineup_mask(d.ours);
	const std::uint16_t seen = lineup_mask(theirs);
	(void)seen;
	try
	{
		team_size();
		analyse_map(d);
		compute_values(d);
		follow_or_rebuild_plan(d);
	}
	catch (const std::exception& e)
	{
		NLOG("draft analysis error: %s\n", e.what());
		(void)e;
	}
	catch (...)
	{
	}
	demote_ci_in_band(d);
	swap_vesper_for_marcella(d);
	swap_by_cell_table(d);
	exchange_by_cell_table(d);
	force_prism_first(d);
	marcella_for_forced_ryth(d);
	hold_override_in_plan(d);
	int picked = try_pick(d.choice, d.have) ? d.choice : -1;
	if (picked < 0)
		greedy_fallback_pick(d, picked);
	if (picked >= 0)
		finish_after_pick(d, picked);
	(void)f_start;
}

} // namespace nova::drafting
