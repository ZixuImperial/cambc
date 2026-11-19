// draft_values.cc: Champion and lineup values.
#include "draft_internal.h"
namespace nova::drafting {
namespace {

float zf(int f, float x, int tier)
{
	float t = dv3::LOG1P[f] ? std::log1p(std::max(0.0f, x)) : x;
	t = clampf(t, dv3::LO[tier][f], dv3::HI[tier][f]);
	return (t - dv3::MU[tier][f]) / dv3::SD[tier][f];
}

// The gate and the economy axes, from the draft's own features, computed on demand (no static data: a new static moves the heap
// base).
inline bool gem_dominance_gate()
{
	if (!S.map_term || S.reach_null)
		return false;
	const float gold = std::max(0.0f, S.mf.x[static_cast<std::size_t>(dv3::F_GOLD_RATE)]);
	const float gem = std::max(0.0f, S.mf.x[static_cast<std::size_t>(dv3::F_GEM_RATE)]);
	return gold >= N1_G_LO && gem >= N1_GEM_RATIO * gold;
}
bool base_lineup_has_vv_or_ci(); // See base_lineup_has_vv_or_ci, defined after the lineup search below.

void set_values(bool map_term)
{
	team_size();
	S.map_term = map_term && S.mf.ok;
	S.tier = S.map_term ? std::clamp(S.mf.tier, 0, 2) : 0;
	for (int f = 0; f < dv3::NF; ++f)
		S.z[static_cast<std::size_t>(f)] = S.map_term ? zf(f, S.mf.x[static_cast<std::size_t>(f)], S.tier) : 0.0f;
	for (int c = 0; c < NC; ++c)
	{
		float m = 0.0f;
		for (int f = 0; f < dv3::NF; ++f)
			m += dv3::B[S.tier][c][f] * S.z[static_cast<std::size_t>(f)];
		S.mt[static_cast<std::size_t>(c)] = m;
		S.base[static_cast<std::size_t>(c)] = dv3::A[S.tier][S.ki][c] + m;
	}
	S.cov = dv3::COV_B0[S.ki] + dv3::COV_B1[S.ki] * S.z[dv3::F_LEN];
	// Value changes (not in null mode, where the reach rule orders the picks by their fitted values).
	if (!S.reach_null)
	{
		// Marcella's draft value is lowered by DRAFT_MA_PP: her team-size value is large (+10 to +14 pp per slot, twice the next champion)
		// but was measured mostly against Marcella-less opponents.
		S.base[MA] -= DRAFT_MA_PP;
		// Vesper is not played on maps where gold is required: her +33% gold pays with the map's gold rate.
		S.base[VV] += vesper_layer::draft_gold(S.z[dv3::F_GOLD_RATE]);
		// Ryth is drafted less.
		S.base[RY] -= DRAFT_RY_PP;
		S.base[VA] -= DRAFT_VA_PP;
		// Tavi is drafted less.
		S.base[TA] -= DRAFT_TA_PP;
		// Willow is drafted less. She is mostly the last pick, chosen within the band at a margin under 1 pp, so a 1 pp cut moves that
		// slot to the next champion.
		S.base[WI] -= DRAFT_WI_PP;
		if (S.dr_ok)
		{
			[[maybe_unused]] auto ramp = [](float x, float lo, float hi) { return hi > lo ? clampf((x - lo) / (hi - lo), 0.0f, 1.0f) : (x >= lo ? 1.0f : 0.0f); };
			// Cassi & Issac are two bodies for one pick: where most of the value sits in one area both teams walk to
			// alike, the first team fight is there and the extra body wins it.
			const float ci = ci_layer::DF_CI_PP * ramp(S.dr_cen, DRAFT_CI_LO, DRAFT_CI_HI);
			S.base[CI] += ci;
			// Every dash kit gains with the profit per round its dashes add on this map (shortcuts over holes and sections only a dash
			// reaches).
			{
				const float dv = DF_DASH_PP * ramp(S.dr_dash, DRAFT_DASH_LO, DRAFT_DASH_HI);
				for (int c = 0; c < NC; ++c)
					if (DASHERS >> c & 1)
					{
						S.base[static_cast<std::size_t>(c)] += dv;
					}
			}
			// DTM bit 2: where walking anywhere important is slow and a dash is far faster, dash kits replace walkers. C&I takes no part: her
			// deaths are not a price this term should pay.
			if (S.dtm_ok)
			{
				const float dv = 0.01f * static_cast<float>(DTM_TAB[2]) * S.dtm_x;
				const float dn = 0.01f * static_cast<float>(DTM_TAB[3]) * dv;
				for (int c = 0; c < NC; ++c)
				{
					if (c == CI || (c == RE))
						continue;
					float d = (DASHERS >> c & 1) ? dv : -dn;
					if (c == VA)
						d = dv * S.dtm_h - dn * (1.0f - S.dtm_h);
					S.base[static_cast<std::size_t>(c)] += d;
				}
			}
			// Vendetta kills a cluster (120 HP) per hit once upgraded (one per turn at base: attack, reset, attack) and each
			// kill resets her cooldowns, so groups of clusters fall turn after turn.
			const float ve = DF_VE_PP * ramp(S.dr_ve, DRAFT_VE_LO, DRAFT_VE_HI);
			S.base[VE] += ve;
		}
		// On large maps that are gold-free, or single-altar with little gold, CI takes VV's slot.
		const float ci_gold = S.map_term ? std::max(0.0f, S.mf.x[static_cast<std::size_t>(dv3::F_GOLD_RATE)]) : 1e9f;
		// A gold-free map gets the swap at any size.
		[[maybe_unused]] const bool ci_gf_small = ci_layer::draft_gf_small(S.map_term, ci_gold);
		if (ci_layer::draft_gate(S.map_term, G.w * G.h, ci_gf_small, ci_gold, static_cast<std::size_t>(M.na)))
		{
			S.base[VV] -= DRAFT_CI_GATE_PP;
			S.base[CI] += DRAFT_CI_GATE_PP;
		}
		// No Cassi & Issac on smaller maps, except gold-free ones.
		if (ci_layer::draft_small_ban(G.w * G.h, ci_gf_small))
		{
			S.base[CI] -= 100.0f;
			S.mt[CI] -= 100.0f;
		}
		// Gem-heavy maps with gold only; everywhere else the values above stand.
		if (gem_dominance_gate())
		{
			// C&I's gem-dominance terms apply only where the base lineup holds VV (C&I replaces only VV) or already holds C&I.
			const bool n2_ci = base_lineup_has_vv_or_ci();
			const float gold = std::max(0.0f, S.mf.x[static_cast<std::size_t>(dv3::F_GOLD_RATE)]);
			const float gem = std::max(0.0f, S.mf.x[static_cast<std::size_t>(dv3::F_GEM_RATE)]);
			const float r = std::log((gem + 5.0f) / (0.1f * gold + 5.0f));
			const float er = clampf((r - N1_R_LO) / (N1_R_HI - N1_R_LO), 0.0f, 1.0f);
			const float eg = clampf((N1_G_HI - gold) / (N1_G_HI - N1_G_LO), 0.0f, 1.0f);
			const float e = std::max(er, eg);
			auto add = [](int c, float x)
			{
				S.base[static_cast<std::size_t>(c)] += x;
				S.mt[static_cast<std::size_t>(c)] += x;
			};
			add(VV, N1_E_VV * e);
			if (n2_ci)
				add(CI, N1_E_CI * e);
			add(PR, N1_E_PR * er);
			// C&I's centrality bonus (value only) scaled by e: the extra body's central edge pays where items are scarce.
			if (S.dr_ok && n2_ci)
				S.base[CI] -= ci_layer::DF_CI_PP * clampf((S.dr_cen - DRAFT_CI_LO) / (DRAFT_CI_HI - DRAFT_CI_LO), 0.0f, 1.0f) * (1.0f - e);
			// The small-map C&I ban (gold_rate >= 60 here, so it applied above) becomes a soft penalty that fades as gold runs out.
			if (ci_layer::draft_small(G.w * G.h) && n2_ci)
				add(CI, 100.0f - N1_CI_SMALL * (1.0f - eg));
		}
		// Where her carry plan pays, pick() takes Prism first and set_terms wants a tank beside her.
		if (S.map_term)
			S.pz_viable = prism::plan_for_map().viable;
		if (M.done() && M.has_home)
		{
			bool walk_alt = false;
			for (const auto& a : M.altars)
				if (a.d_home != UNREACH)
				{
					walk_alt = true;
					break;
				}
			long ngcl = 0;
			for (const auto& cp : M.camps)
				if (cp.type == cambc::camp_type::gem_cluster)
					++ngcl;
			if (!walk_alt)
			{
				S.pz_viable = false;
				S.base[PR] -= 1000.0f;
			}
			else if (S.map_term && ngcl >= PZB_NGCL && 1000L * ngcl > static_cast<long>(PZB_SH1000) * static_cast<long>(static_cast<std::size_t>(M.nc)))
				S.pz_viable = true;
		}
	}
	// MCT: smooth terms from the camp groups, after the other hand terms. Then the chosen strategy's additive pick biases (strategy.h;
	// 0 for every strategy until one defines them).
	for (int c = 0; c < NC; ++c)
		S.base[static_cast<std::size_t>(c)] += strat::pick_bias(static_cast<strat::Mode>(strat::draft_choice()), c);
	for (int c = 0; c < NC; ++c)
		S.base[static_cast<std::size_t>(c)] += 0.01f * static_cast<float>(ECDV_TAB[2 + c]);
	// A pick that reaches none of the map's resources is a null pick: value 0 (its fitted value only orders the null picks, a follower
	// last), no map term, no roles, no composition terms.
	S.live = 0xFFF;
	for (int c = 0; c < NC; ++c)
	{
		const auto ci = static_cast<std::size_t>(c);
		S.roles[ci] = dv3::ROLES[c];
		if (!S.reach_null || (DASHERS >> c & 1))
			continue;
		S.base[ci] = 0.001f * S.base[ci] - ((FOLLOWERS >> c & 1) ? 0.05f : 0.0f);
		S.mt[ci] = 0.0f;
		S.roles[ci] = 0;
		S.live = static_cast<std::uint16_t>(S.live & ~bit(c));
	}
	S.values = true;
}

unsigned roles_of(unsigned m)
{
	unsigned r = 0;
	for (; m; m &= m - 1)
		r |= S.roles[static_cast<std::size_t>(__builtin_ctz(m))]; // Null picks cover no role.
	return r;
}

// Composition: the lineup judged as a whole (ro = OR of the members' role masks). n1 = false leaves the gem-dominance term out.
inline float set_terms(unsigned m, unsigned ro, bool n1 = true)
{
	const int ki = S.ki;
	float s = 0.0f;
	if (!(m & TANKS))
	{
		s += dv3::NOTANK[ki];
		if (m & bit(WI))
			s += dv3::WWT[ki];
	}
	// Prism never in Marcella's slot on gated maps (Marcella's tribute gold is the item engine of a gem economy).
	if (n1 && (m & bit(PR)) && !(m & bit(MA)) && gem_dominance_gate())
		s -= N1_PRMA;
	(void)n1;
	// Where her carry plan is viable, her mates include a tank (Marcella fits).
	if (S.pz_viable && (m & bit(PR)) && !(m & TANKS))
		s -= PZD_TANK_PP;
	if (popc(m & ECON) >= 2)
		s += dv3::ECON2[ki];
	if ((m & VAHR) == VAHR)
		s += dv3::VAHOR[ki];
	if ((m & VEVV) == VEVV)
		s += dv3::VEVV[ki];
	if ((m & WIHR) == WIHR)
		s += dv3::WIHOR[ki];
	return s + S.cov * static_cast<float>(popc(ro));
}
float lineup_value(unsigned m)
{
	float v = 0.0f;
	for (unsigned t = m; t; t &= t - 1)
		v += S.base[static_cast<std::size_t>(__builtin_ctz(t))];
	return v + set_terms(m & S.live, roles_of(m)); // Composition among the picks that reach something.
}

float map_term_sum(unsigned m)
{
	float v = 0.0f;
	for (; m; m &= m - 1)
		v += S.mt[static_cast<std::size_t>(__builtin_ctz(m))];
	return v;
}

// Does the base lineup hold VV or C&I? The plan's target for an empty draft from the values set so far, since set_values calls this
// inside the gem-dominance gate before any of its terms (null mode is off there and the strategy bias is 0), with no such
// composition term. The lineups and values of enumerate_all in its order, then make_plan's passes 1-2 (the best admissible value,
// then the largest map term in the near-tie band). Two sweeps, nothing stored, no static data; turn 1 only.
bool base_lineup_has_vv_or_ci()
{
	const int k = team_size();
	if (k < 3 || k > 5)
		return true; // No such map so far: leave the n1 values as they are.
	for (int c = 0; c < NC; ++c)
		S.roles[static_cast<std::size_t>(c)] = dv3::ROLES[c]; // the kit roles (set_values sets them again below)
	const int need = std::min(S.min_dash, k), most = std::max(S.max_dash, 0);
	const float* b = S.base.data();
	const unsigned* R = S.roles.data();
	float vmax = -1e30f, floor_v = 0.0f, bk = -1e30f, bv = -1e30f;
	unsigned tm = 0;
	bool band = false;
	auto visit = [&](unsigned m, float v, unsigned ro)
	{
		const int nd = popc(m & DASHERS);
		if ((need != 0 && nd < need) || nd > most)
			return;
		const float x = v + set_terms(m, ro, false);
		if (!band)
		{
			if (x > vmax)
				vmax = x;
			return;
		}
		if (x < floor_v)
			return;
		const float key = map_term_sum(m);
		if (key > bk + 1e-4f || (key >= bk - 1e-4f && x > bv))
		{
			bk = key;
			bv = x;
			tm = m;
		}
	};
	for (int pass = 0; pass < 2; ++pass)
	{
		band = pass == 1;
		if (band)
		{
			if (vmax < -1e29f)
				return true;
			floor_v = vmax - dv3::EPS[S.ki];
		}
		for (int c1 = 0; c1 < NC; ++c1)
			for (int c2 = c1 + 1; c2 < NC; ++c2)
			{
				const float v2 = b[c1] + b[c2];
				const unsigned r2 = R[c1] | R[c2], m2 = (1u << c1) | (1u << c2);
				for (int c3 = c2 + 1; c3 < NC; ++c3)
				{
					const float v3 = v2 + b[c3];
					const unsigned r3 = r2 | R[c3], m3 = m2 | (1u << c3);
					if (k == 3)
					{
						visit(m3, v3, r3);
						continue;
					}
					for (int c4 = c3 + 1; c4 < NC; ++c4)
					{
						const float v4 = v3 + b[c4];
						const unsigned r4 = r3 | R[c4], m4 = m3 | (1u << c4);
						if (k == 4)
						{
							visit(m4, v4, r4);
							continue;
						}
						for (int c5 = c4 + 1; c5 < NC; ++c5)
							visit(m4 | (1u << c5), v4 + b[c5], r4 | R[c5]);
					}
				}
			}
	}
	return tm == 0 || (tm & (bit(VV) | bit(CI))) != 0;
}
} // namespace
} // namespace nova::drafting
