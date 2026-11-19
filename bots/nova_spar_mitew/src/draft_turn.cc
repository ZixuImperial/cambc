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
	if (fuel() > enum_estimate() + replan_estimate() + 40000) // BB8P: a Prism swap re-enumerates (it changes the cache key)
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


// v708 BHX bit 4 RNB1: in null-reach mode a pick set that takes a non-dasher in or holds more dashers than S.max_dash is not admissible.
static bool bhx_null_bad(std::uint16_t set, int to)
{
	return S.reach_null && (!(DASHERS >> to & 1) || __builtin_popcount(set & DASHERS) > S.max_dash);
}
// VGF bit 1 (draft_flags.h; the VSM strict swap): the plan holds Marcella, not Vesper, no Prism (and Prism's plan is not viable).
static __attribute__((always_inline)) inline bool vgf_plan_swaps()
{
	return S.values && PL.ok && M.done() && (PL.top_m >> MA & 1) && !(PL.top_m >> VV & 1) && !(PL.top_m >> PR & 1) && !S.pz_viable && vgf_gate();
}
static __attribute__((always_inline)) inline void vgf_virtual(DraftTurn& d)
{
	if ((d.have >> VV & 1) && !(d.have >> MA & 1) && vgf_plan_swaps())
		d.have = static_cast<std::uint16_t>((d.have & ~bit(VV)) | bit(MA)); // VGF: our Vesper stands in for Marcella in the plan's eyes
}
static bool mdc_mfr = false; // MDC bit 2: this turn's Marcella came from the forced-Ryth swap
static __attribute__((always_inline)) inline void vgf_pick(DraftTurn& d, std::uint16_t real)
{
	d.have = real;
	const bool mdc_keep = mdc_mfr;
	mdc_mfr = false;
	if (d.choice == MA && !(real >> VV & 1) && !(mdc_keep) && !(bhx_null_bad(static_cast<std::uint16_t>(real | bit(VV)), VV)) && vgf_plan_swaps()) // BHX bit 4
		d.choice = VV; // VGF: Marcella's seat goes to Vesper
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
			if (from >= 0 && !(bhx_null_bad(0, MA))) // BHX bit 4 RNB1: Marcella is a null pick in null mode
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
					if (has_from && !has_to && !(bhx_null_bad(static_cast<std::uint16_t>((eff & ~bit(from)) | bit(to)), to))) // BHX bit 4 RNB1
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
			const int code0 = draft_swap_cell_code(eff, S.pz_viable, 0, DXC_N, DXC_TAB);
			const int code = (code0 == DXC0_C && dxs_keep_prism(eff)) ? 0 : code0;
			const int from = (code & 15) - 1, to = (code >> 4 & 15) - 1;
			if (from >= 0 && from < NC && to >= 0 && to < NC && from != to && (eff >> from & 1) && !(eff >> to & 1) && !(bhx_null_bad(static_cast<std::uint16_t>((eff & ~bit(from)) | bit(to)), to))) // BHX bit 4 RNB1
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

// OHD class (baked at its shipped value): the largest gem group (ties: the lower index) holds >= OHD_TAB[2] % of the map's gems and an elk,
// golem or monolith.
static bool ohd_class()
{
	long tot = 0;
	const GroupI* top = nullptr;
	for (const auto& g : M.groups)
	{
		tot += g.gems;
		if (!top || g.gems > top->gems)
			top = &g;
	}
	return top && tot > 0 && top->n_elk + top->n_golem + top->n_mono > 0 && 100L * top->gems >= static_cast<long>(OHD_TAB[2]) * tot;
}
// OHD (baked at its shipped value): one swap on class maps, first draft turn, the exchange_by_cell_table pattern.
static __attribute__((noinline)) void ohd_swap(DraftTurn& d)
{
	if (d.have != 0 || !S.values || !cached || !PL.ok || !M.done() || !ohd_class())
		return;
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
		const int to = MA;
		int from = -1;
		if (eff >> VA & 1)
			from = VA;
		else
			for (int c = 0; c < NC; ++c)
				if ((eff >> c & 1) && c != CI && c != PR && c != to && S.base[static_cast<std::size_t>(c)] <= 500.0f &&
					(from < 0 || S.base[static_cast<std::size_t>(c)] < S.base[static_cast<std::size_t>(from)]))
					from = c;
		if (from < 0 || from == to || (eff >> to & 1))
			return;
		for (int c = 0; c < NC; ++c)
			if ((eff >> c & 1) && c != from)
				S.base[static_cast<std::size_t>(c)] += 3000.0f;
		S.base[static_cast<std::size_t>(from)] -= 5000.0f;
		S.base[static_cast<std::size_t>(to)] += 5000.0f;
		replan_and_adopt(d);
		if (d.choice == from)
			d.choice = -1;
	}
	catch (...)
	{
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
	{
		d.choice = MA; // Marcella in Ryth's pick on heavy 5-body maps.
		mdc_mfr = true; // MDC bit 2: VGF keeps this Marcella
	}
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

// v724 DFG: the opening record for the lineup the draft plans to field (the plan's lineup, VGF's seat swap applied, in its guessed slot
// order), made once on the first (10M) draft turn after its pick and hand-off, then submitted again. It carries its slot types (extra 7),
// so play drops it when the fielded order differs; later draft turns never touch it (no repack).
static void dfg_plan(const std::vector<champion_draft>& after)
{
	static bool tried = false;
	if (tried || !M.done() || !PL.ok || fuel() < 4000000)
		return;
	tried = true;
	std::uint16_t m = PL.top_m;
	if (vgf_plan_swaps())
		m = static_cast<std::uint16_t>((m & ~bit(MA)) | bit(VV));
	const std::uint16_t real = lineup_mask(after);
	if ((real & ~m) != 0 || popc(m) != team_size())
		return;
	std::vector<int> order; // the picks in draft order (play's slot order): ours so far, then the plan's steps, then any left
	for (auto c : after)
		order.push_back(idx_of(c));
	std::uint16_t got = real;
	for (int i = 0; i < 5 && i < PL.r; ++i)
	{
		int c = PL.step[static_cast<std::size_t>(i)].pick;
		if (c == MA && !(m >> MA & 1))
			c = VV;
		if (c >= 0 && c < NC && (m >> c & 1) && !(got >> c & 1))
		{
			order.push_back(c);
			got = static_cast<std::uint16_t>(got | bit(c));
		}
	}
	for (int c = 0; c < NC; ++c)
		if ((m >> c & 1) && !(got >> c & 1))
		{
			order.push_back(c);
			got = static_cast<std::uint16_t>(got | bit(c));
		}
	std::array<cambc::champion_type, 8> ty{};
	int n = 0;
	for (int c : order)
	{
		if (n >= 8)
			break;
		if (c == static_cast<int>(champion_draft::cassi_and_issac))
		{
			ty[static_cast<std::size_t>(n++)] = cambc::champion_type::cassi;
			if (n < 8)
				ty[static_cast<std::size_t>(n++)] = cambc::champion_type::issac;
		}
		else
			ty[static_cast<std::size_t>(n++)] = static_cast<cambc::champion_type>(c <= 2 ? c : c + 1);
	}
	const int s2s = S.mem.size() > 14 && S.mem[14] > 0 ? (S.mem[14] - 1) * std::max<int>(1, S.mem[9]) : -1;
	if (nova::econ::dfg_draft_plan(ty, n, S.mem.size() > 3 ? S.mem[3] : S.flags, s2s))
		pack_and_submit_draft_memory();
}
// After the pick: the stored walks (resumable over draft turns), then the hand-off to team memory.
static __attribute__((always_inline)) inline void finish_after_pick(const DraftTurn& d, int picked)
{
	// The stored walks run after the pick (the pick is unchanged), leaving the memory encode and submit their fuel.
	try
	{
		const long enc = S.mem.empty() ? (S.cost_encode > 0 ? S.cost_encode : 6000L + 220L * static_cast<long>(static_cast<std::size_t>(M.ng) + static_cast<std::size_t>(M.na))) : 0L;
		const long sub = S.cost_submit > 0 ? S.cost_submit + 3000L : 4000L;
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
		dfg_plan(after);
	}
	catch (...)
	{
	}
}
} // namespace

// FORCED TEAM (tools/lab/forceteam.py, owner 3 Nov): TEST COPIES ONLY, never a candidate. FTEAM_TAB[1]: up to 5 picks, 4 bits each
// (champion index + 1, first in the low bits); [2] bit 0 shuffles the pick order per map (seeded by the walls), bits 8+ a seed.
// The first team_size() listed are drafted; a shorter list leaves the rest to the plan.
inline const volatile int FTEAM_TAB[3] = { 0x46544d31, 535492, 0 };
int ft_choice(std::uint16_t have, int choice)
{
	const int T = team_size();
	int L[5], n = 0;
	for (int i = 0, v = FTEAM_TAB[1]; i < 5 && n < T; ++i, v >>= 4)
		if ((v & 15) && (v & 15) <= NC)
			L[n++] = (v & 15) - 1;
	if (FTEAM_TAB[2] & 1)
	{
		std::uint32_t s = 2166136261u ^ static_cast<std::uint32_t>(FTEAM_TAB[2] >> 8);
		bbforeach(cambc::map::walls(), [&](vec2 p) { s = (s ^ static_cast<std::uint32_t>(p.x * 4099 + p.y)) * 16777619u; });
		for (int i = n - 1; i > 0; --i)
		{
			s = s * 1664525u + 1013904223u;
			const int j = static_cast<int>((s >> 16) % static_cast<std::uint32_t>(i + 1));
			const int t = L[i];
			L[i] = L[j];
			L[j] = t;
		}
	}
	for (int i = 0; i < n; ++i)
		if (!(have >> L[i] & 1))
			return L[i];
	return choice;
}

void play_draft()
{
	const long f_start = fuel();
	++S.turn;
	DraftTurn d;
	try
	{
		d.ours = cambc::draft::current_draft(team::ally);
	}
	catch (...)
	{
	}
	d.have = lineup_mask(d.ours);
	const std::uint16_t vgf_real = d.have;
	vgf_virtual(d); // VGF bit 1
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
	if (d.have == 0 && S.values && cached && PL.ok && M.done() && (PL.top_m >> WI & 1) && !(PL.top_m >> MA & 1) && wgl_gem_share_low())
	{ // WGL bit 8 (b1769): on gold-leaning maps Willow does not take Marcella's seat
		const float r = wgl_raise_pp();
		if (r != 0.0f)
		{
			S.base[WI] -= r;
			replan_and_adopt(d);
			if (!(PL.top_m >> MA & 1)) // without the raise the plan still has no Marcella: her seat was not the one, keep the raise
			{
				S.base[WI] += r;
				replan_and_adopt(d);
			}
		}
	}
	swap_vesper_for_marcella(d);
	swap_by_cell_table(d);
	exchange_by_cell_table(d);
	ohd_swap(d); // OHD (b1829): one-source heavy maps
	force_prism_first(d);
	marcella_for_forced_ryth(d);
	hold_override_in_plan(d);
	vgf_pick(d, vgf_real); // VGF bit 1
	if (FTEAM_TAB[1]) // FORCED TEAM (forceteam.py): test copies only
	{
		d.choice = ft_choice(d.have, d.choice);
		S.pz_viable = false; // Prism is not in the forced list
	}
	int picked = try_pick(d.choice, d.have) ? d.choice : -1;
	if (picked < 0)
		greedy_fallback_pick(d, picked);
	if (picked >= 0)
		finish_after_pick(d, picked);
	(void)f_start;
}

} // namespace nova::drafting
