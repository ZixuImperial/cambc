// draft_lineup_search.cc: Exact lineup search and its fuel estimates.
#include "draft_internal.h"
namespace nova::drafting {
namespace {

// Every k-lineup and its value, cached in lexicographic order (c1 < c2 < ...): nested loops with partial sums of the
// values and of the role masks for k = 3, 4, 5 (Gosper's hack otherwise). The best admissible value for an empty draft
// is tracked on the way (plan pass 1 for turn 1).
float vmax0 = -1e30f;
unsigned bm0 = 0;
int need0 = -1;

// set_terms per lineup slot, kept across re-enumerations while everything it reads is unchanged.
std::array<float, MAXL> fxdr_terms{};
std::array<std::uint32_t, NC + 8> fxdr_tkey{};
bool fxdr_tkey_ok = false, fxdr_tread = false, fxdr_twrite = false;
inline void store(int& n, unsigned m, float v, unsigned ro)
{
	float t;
	if (fxdr_tread)
		t = fxdr_terms[static_cast<std::size_t>(n)];
	else
	{
		t = set_terms(m & S.live, ro);
		if (fxdr_twrite)
			fxdr_terms[static_cast<std::size_t>(n)] = t;
	}
	const float x = v + t; // Null picks take part in no composition term.
	LM[static_cast<std::size_t>(n)] = static_cast<std::uint16_t>(m);
	LV[static_cast<std::size_t>(n)] = x;
	++n;
	if (x > vmax0 && (need0 == 0 || popc(m & DASHERS) >= need0) && popc(m & DASHERS) <= S.max_dash)
	{
		vmax0 = x;
		bm0 = m;
	}
}
bool enumerate_all(int min_dash)
{
	const int k = team_size();
	if (!S.values || k < 1 || k > 5)
		return false;
	int n = 0;
	vmax0 = -1e30f;
	bm0 = 0;
	need0 = std::min(min_dash, k);
	const float* b = S.base.data();
	const unsigned* R = S.roles.data(); // Null picks cover no role.
	fxdr_tread = fxdr_twrite = false;
	std::array<std::uint32_t, NC + 8> key{};
	for (int c = 0; c < NC; ++c)
		key[static_cast<std::size_t>(c)] = R[c];
	std::uint32_t cb;
	std::memcpy(&cb, &S.cov, sizeof cb);
	key[NC] = cb;
	key[NC + 1] = static_cast<std::uint32_t>(S.ki);
	key[NC + 2] = S.pz_viable ? 1u : 0u;
	key[NC + 3] = gem_dominance_gate() ? 1u : 0u;
	key[NC + 4] = S.live;
	key[NC + 5] = static_cast<std::uint32_t>(k);
	key[NC + 6] = 0x46584452u;
	if (fxdr_tkey_ok && key == fxdr_tkey)
		fxdr_tread = true;
	else
	{
		fxdr_tkey = key;
		fxdr_tkey_ok = false; // valid only once a whole enumeration wrote it
		fxdr_twrite = true;
	}
	if (k >= 3)
	{
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
						store(n, m3, v3, r3);
						continue;
					}
					for (int c4 = c3 + 1; c4 < NC; ++c4)
					{
						const float v4 = v3 + b[c4];
						const unsigned r4 = r3 | R[c4], m4 = m3 | (1u << c4);
						if (k == 4)
						{
							store(n, m4, v4, r4);
							continue;
						}
						for (int c5 = c4 + 1; c5 < NC; ++c5)
							store(n, m4 | (1u << c5), v4 + b[c5], r4 | R[c5]);
					}
				}
			}
	}
	else
	{
		// k = 1 or 2 (no such map so far): Gosper's hack, increasing masks.
		unsigned m = (1u << k) - 1u;
		while (m < (1u << NC) && n < MAXL)
		{
			float v = 0.0f;
			unsigned ro = 0;
			for (unsigned t = m; t; t &= t - 1)
			{
				v += b[__builtin_ctz(t)];
				ro |= R[__builtin_ctz(t)];
			}
			store(n, m, v, ro);
			const unsigned t = m | (m - 1u);
			const unsigned u = ~t;
			m = (t + 1u) | (((u & (0u - u)) - 1u) >> (__builtin_ctz(m) + 1));
		}
	}
	NL = n;
	if (fxdr_twrite)
		fxdr_tkey_ok = true;
	fxdr_tread = fxdr_twrite = false;
	cached = n > 0;
	return cached;
}

// One pick of the plan, with its explanation.
struct Step
{
	int pick = -1;
	float regret = 0.0f, without = 0.0f;
	std::uint16_t wo_m = 0;
	int next = -1; // runner-up open member and its regret
	float next_regret = 0.0f;
	bool forced = false; // no admissible lineup lacks the pick: finite regret against the worst admissible lineup
};

// The whole remaining draft, decided at once. Values do not depend on the enemy, so the target T stays the target on
// every later turn, and each later turn's explicit regrets follow from one pass: best[s] = the best admissible lineup
// whose intersection with T's open members is s (32 subsets at most). Then best-without(c) after picks P = max over s
// containing P and not c of best[s].
struct PlanT
{
	bool ok = false;
	std::uint16_t have = 0, top_m = 0, best_m = 0;
	int need_dash = 0;
	float top = 0.0f, vmax = 0.0f;
	int nband = 0;
	int r = 0; // open members of T
	std::array<Step, 5> step{};
};
PlanT PL;
bool make_plan(std::uint16_t have, int min_dash)
{
	if (!S.values || !cached)
		return false;
	PlanT p;
	p.have = have;
	const int left = team_size() - popc(have);
	if (left <= 0)
		return false;
	const int need = std::min(min_dash, popc(have & DASHERS) + left);
	p.need_dash = need;
	const int most = std::max(S.max_dash, popc(have & DASHERS)); // No more dashers than the dash-only groups.
	auto admissible = [&](unsigned m)
	{ return (m & have) == have && (need == 0 || popc(m & DASHERS) >= need) && popc(m & DASHERS) <= most; };
	// Pass 1: the best admissible value (already known from the enumeration when the draft is empty).
	float vmax = -1e30f;
	unsigned bm = 0;
	// The admissible lineups in index order, so passes 2 and 3 visit the same lineups in the same order.
	const bool fxdr_p = have != 0; // an empty draft admits nearly every lineup: the list would cost more
	static std::array<std::uint16_t, MAXL> fxdr_adm;
	int fxdr_na = 0;
	if (have == 0 && need == need0 && most == S.max_dash && bm0 != 0)
	{
		vmax = vmax0;
		bm = bm0;
		if (fxdr_p)
			for (int i = 0; i < NL; ++i)
				if (admissible(LM[static_cast<std::size_t>(i)]))
					fxdr_adm[static_cast<std::size_t>(fxdr_na++)] = static_cast<std::uint16_t>(i);
	}
	else if (fxdr_p)
		for (int i = 0; i < NL; ++i)
		{
			const unsigned m = LM[static_cast<std::size_t>(i)];
			if (!admissible(m))
				continue;
			fxdr_adm[static_cast<std::size_t>(fxdr_na++)] = static_cast<std::uint16_t>(i);
			if (LV[static_cast<std::size_t>(i)] > vmax)
			{
				vmax = LV[static_cast<std::size_t>(i)];
				bm = m;
			}
		}
	else
		for (int i = 0; i < NL; ++i)
		{
			const unsigned m = LM[static_cast<std::size_t>(i)];
			if (LV[static_cast<std::size_t>(i)] > vmax && admissible(m))
			{
				vmax = LV[static_cast<std::size_t>(i)];
				bm = m;
			}
		}
	if (bm == 0)
		return false;
	// Pass 2: the near-tie band (the data cannot separate these lineups); the validated map term settles it.
	const float floor_v = vmax - dv3::EPS[S.ki];
	float bk = -1e30f, bv = -1e30f;
	unsigned tm = 0;
	const int fxdr_n2 = fxdr_p ? fxdr_na : NL;
	for (int i2 = 0; i2 < fxdr_n2; ++i2)
	{
		const int i = fxdr_p ? static_cast<int>(fxdr_adm[static_cast<std::size_t>(i2)]) : i2;
		const float v = LV[static_cast<std::size_t>(i)];
		const unsigned m = LM[static_cast<std::size_t>(i)];
		if (v < floor_v || (!fxdr_p && !admissible(m)))
			continue;
		++p.nband;
		const float key = map_term_sum(m);
		if (key > bk + 1e-4f || (key >= bk - 1e-4f && v > bv))
		{
			bk = key;
			bv = v;
			tm = m;
		}
	}
	if (tm == 0)
		return false;
	const float top = bv;
	std::array<int, 5> oc{};
	int r = 0;
	for (unsigned o = tm & ~static_cast<unsigned>(have); o && r < 5; o &= o - 1)
		oc[static_cast<std::size_t>(r++)] = __builtin_ctz(o);
	// Pass 3: best[s] over the cache. The subset index comes from two 64-entry tables over the low and high six bits.
	std::array<std::uint8_t, 64> lo{}, hi{};
	for (int j = 0; j < r; ++j)
	{
		const int c = oc[static_cast<std::size_t>(j)];
		for (unsigned x = 0; x < 64; ++x)
		{
			if (c < 6 && (x >> c & 1))
				lo[x] = static_cast<std::uint8_t>(lo[x] | (1u << j));
			if (c >= 6 && (x >> (c - 6) & 1))
				hi[x] = static_cast<std::uint8_t>(hi[x] | (1u << j));
		}
	}
	std::array<float, 32> best;
	best.fill(-1e30f);
	std::array<std::uint16_t, 32> bestm{};
	for (int i2 = 0; i2 < fxdr_n2; ++i2)
	{
		const int i = fxdr_p ? static_cast<int>(fxdr_adm[static_cast<std::size_t>(i2)]) : i2;
		const unsigned m = LM[static_cast<std::size_t>(i)];
		if (!fxdr_p && !admissible(m))
			continue;
		const unsigned si = static_cast<unsigned>(lo[m & 63u] | hi[(m >> 6) & 63u]);
		if (LV[static_cast<std::size_t>(i)] > best[si])
		{
			best[si] = LV[static_cast<std::size_t>(i)];
			bestm[si] = static_cast<std::uint16_t>(m);
		}
	}
	float lowest = top;
	for (float x : best)
		if (x > -1e29f)
			lowest = std::min(lowest, x);
	// Simulate our remaining turns: pick the open member with the largest explicit regret, then the next.
	const unsigned full = (1u << r) - 1u;
	unsigned hs = 0;
	for (int t = 0; t < r; ++t)
	{
		Step st;
		float k1 = -1e30f, k2 = -1e30f;
		for (int j = 0; j < r; ++j)
		{
			if (hs >> j & 1)
				continue;
			float w = -1e30f;
			std::uint16_t wm = 0;
			for (unsigned sub = 0; sub <= full; ++sub)
				if ((sub & hs) == hs && !(sub >> j & 1) && best[sub] > w)
				{
					w = best[sub];
					wm = bestm[sub];
				}
			const int c = oc[static_cast<std::size_t>(j)];
			const bool none = w < -1e29f;
			// Finite even when the dash rule leaves no lineup without c: the lowest admissible bucket stands in, a point lower.
			const float reg = none ? top - lowest + 1.0f : top - w;
			const float key = reg + 1e-4f * S.base[static_cast<std::size_t>(c)]; // ties: the larger own value first
			if (key > k1)
			{
				if (st.pick >= 0)
				{
					k2 = k1;
					st.next = st.pick;
					st.next_regret = st.regret;
				}
				k1 = key;
				st.pick = c;
				st.regret = reg;
				st.without = none ? lowest - 1.0f : w;
				st.wo_m = wm;
				st.forced = none;
			}
			else if (key > k2)
			{
				k2 = key;
				st.next = c;
				st.next_regret = reg;
			}
		}
		for (int j = 0; j < r; ++j)
			if (oc[static_cast<std::size_t>(j)] == st.pick)
				hs |= 1u << j;
		p.step[static_cast<std::size_t>(t)] = st;
	}
	p.top = top;
	p.top_m = static_cast<std::uint16_t>(tm);
	p.vmax = vmax;
	p.best_m = static_cast<std::uint16_t>(bm);
	p.r = r;
	p.ok = true;
	PL = p;
	return true;
}
// Our next pick from the plan, if our picks so far are the plan's: the step index, else -1.
int plan_step(std::uint16_t have)
{
	if (!PL.ok || (PL.have & ~have) != 0 || (have & ~(PL.have | PL.top_m)) != 0)
		return -1;
	const int t = popc(have) - popc(PL.have);
	if (t < 0 || t >= PL.r)
		return -1;
	// The plan's first t picks, in order, must be exactly the extra picks.
	std::uint16_t want = PL.have;
	for (int i = 0; i < t; ++i)
		want = static_cast<std::uint16_t>(want | bit(PL.step[static_cast<std::size_t>(i)].pick));
	return want == have ? t : -1;
}

// Marginal value order for the fallback: what each champion adds to our picks (own value and composition), the dash
// rule first. Needs only S.base. `val` (optional) receives each champion's marginal value.
std::array<int, NC> greedy_order(std::uint16_t have, int min_dash, std::array<float, NC>* val = nullptr)
{
	std::array<std::pair<float, int>, NC> v{};
	const int left = std::max(0, team_size() - popc(have));
	const bool dash_short = popc(have & DASHERS) < min_dash;
	const bool dash_only = popc(have & DASHERS) + left <= min_dash; // every open slot must be a dasher
	const bool dash_full = popc(have & DASHERS) >= S.max_dash; // No more dashers than the dash-only groups.
	const float vh = lineup_value(have);
	for (int c = 0; c < NC; ++c)
	{
		float x = lineup_value(have | bit(c)) - vh;
		if ((DASHERS >> c & 1) && dash_short)
			x += dash_only ? 1000.0f : 20.0f;
		if ((DASHERS >> c & 1) && dash_full)
			x -= 1000.0f;
		v[static_cast<std::size_t>(c)] = { -x, c };
		if (val)
			(*val)[static_cast<std::size_t>(c)] = x;
	}
	std::sort(v.begin(), v.end());
	std::array<int, NC> order{};
	for (int i = 0; i < NC; ++i)
		order[static_cast<std::size_t>(i)] = v[static_cast<std::size_t>(i)].second;
	return order;
}

bool try_pick(int c, std::uint16_t ours)
{
	if (c < 0 || c >= NC || (ours >> c & 1))
		return false;
	try
	{
		cambc::draft::pick(static_cast<champion_draft>(c));
		return true;
	}
	catch (const std::exception& e)
	{
		NLOG("draft pick %d failed: %s\n", c, e.what());
		(void)e;
		return false;
	}
	catch (...)
	{
		return false;
	}
}

// ---------------------------------------------------------------- fuel estimates

// Fuel per lineup on turn 1 (enumeration <= 142, plan passes <= 105 per lineup at k = 3, 4, 5; both are the same work on every map),
// with a margin.
constexpr long ENUM_PER = 150, PLAN_PER = 112;

long enum_estimate() { return S.cost_enum > 0 ? S.cost_enum + 4000 : ENUM_PER * choose(NC, team_size()) + 6000; }
long replan_estimate(std::uint16_t have = 0)
{
	const long full = S.cost_plan > 0 ? S.cost_plan + 6000 : PLAN_PER * choose(NC, team_size()) + 10000;
	if (have == 0)
		return full;
	// After our picks: three passes, each a cheap mask test per cached lineup plus the full work on the completions.
	const long nl = std::max(1L, choose(NC, team_size())), nc = choose(NC - popc(have), team_size() - popc(have));
	// BB8P: in int64 (WASM32 long is 32-bit: the product overflowed past cost_plan ~4.3M), clamped >= 0
	return static_cast<long>(std::clamp<std::int64_t>(3LL * 12LL * nl + (static_cast<std::int64_t>(full) * 3LL / 2LL) * nc / nl + 8000LL, 0LL, 2000000000LL));
}
long plan_estimate() { return (cached ? 0 : enum_estimate()) + replan_estimate(); }

// What must remain after the map features on turn 1: enumeration and plan, then the memory encode under its own guard.
long reserve_after_features()
{
	const long enc = S.cost_encode > 0 ? S.cost_encode : 6000L + 220L * static_cast<long>(static_cast<std::size_t>(M.ng) + static_cast<std::size_t>(M.na));
	return plan_estimate() + std::max(40000L, enc + 25000L) + 10000L;
}
} // namespace
} // namespace nova::drafting
