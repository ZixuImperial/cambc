// mapfeat.cc: Draft map features. The nine features of the REPL table, computed once on the first draft turn from MapInfo plus fitfeat's
#include "mapfeat.h"

#include "mapinfo.h"

namespace nova::mapfeat {

namespace {

constexpr int MAXN = 32; // members handled by the exact simulation (bit masks)

// Greedy splash multiplier of one group: repeatedly hit the living member with the most living members within Chebyshev 1 (ties:
// most HP in that set; then the lowest index); every member of the set takes the same damage until the weakest dies. Returns total
// HP / sum of per-hit damage.
float splash_exact(const GroupI& g)
{
	const int n = static_cast<int>(std::min<std::size_t>(static_cast<std::size_t>(g.nm), MAXN));
	if (n <= 1)
		return 1.0f;
	std::array<std::uint32_t, MAXN> nb{};
	std::array<float, MAXN> h{};
	float total = 0;
	for (int i = 0; i < n; ++i)
	{
		const CampI& ci = M.camps[static_cast<std::size_t>(g.members[static_cast<std::size_t>(i)])];
		h[static_cast<std::size_t>(i)] = ci.hp;
		total += ci.hp;
		for (int j = 0; j < n; ++j)
			if (j != i && cheb(ci.pos, M.camps[static_cast<std::size_t>(g.members[static_cast<std::size_t>(j)])].pos) <= 1)
				nb[static_cast<std::size_t>(i)] |= 1u << j;
	}
	std::uint32_t alive = (n == 32) ? 0xffffffffu : ((1u << n) - 1u);
	float hits = 0;
	while (alive)
	{
		int best = -1, bestc = -1;
		float besth = -1;
		for (std::uint32_t a = alive; a; a &= a - 1)
		{
			const int i = __builtin_ctz(a);
			const std::uint32_t s = (nb[static_cast<std::size_t>(i)] & alive) | (1u << i);
			const int c = __builtin_popcount(s);
			if (c < bestc)
				continue;
			float hs = 0;
			for (std::uint32_t t = s; t; t &= t - 1)
				hs += h[static_cast<std::size_t>(__builtin_ctz(t))];
			if (c > bestc || hs > besth)
			{
				best = i;
				bestc = c;
				besth = hs;
			}
		}
		const std::uint32_t s = (nb[static_cast<std::size_t>(best)] & alive) | (1u << best);
		float m = 1e30f;
		for (std::uint32_t t = s; t; t &= t - 1)
			m = std::min(m, h[static_cast<std::size_t>(__builtin_ctz(t))]);
		hits += m;
		for (std::uint32_t t = s; t; t &= t - 1)
		{
			const int j = __builtin_ctz(t);
			h[static_cast<std::size_t>(j)] -= m;
			if (h[static_cast<std::size_t>(j)] <= 1e-3f)
				alive &= ~(1u << j);
		}
	}
	return hits > 0 ? total / hits : 1.0f;
}
// Neighbour proxy: HP-weighted 1 + number of camp tiles (any group) within Chebyshev 1. Reads the camp index grid directly (8
// lookups per member; bbget through DIRS costs about 4x more fuel).
float splash_proxy(const GroupI& g)
{
	const int W = M.w, H = M.h;
	const std::int16_t* ca = M.camp_at.data();
	if (M.camp_at.size() < static_cast<std::size_t>(W) * static_cast<std::size_t>(H))
		return 1.0f;
	float num = 0, den = 0;
	for (const int ci : g.members)
	{
		const CampI& c = M.camps[static_cast<std::size_t>(ci)];
		const int x = c.pos.x, y = c.pos.y;
		int nb = 0;
		for (int yy = y - 1; yy <= y + 1; ++yy)
		{
			if (yy < 0 || yy >= H)
				continue;
			const std::int16_t* row = ca + yy * W;
			for (int xx = x - 1; xx <= x + 1; ++xx)
				if (xx >= 0 && xx < W && (xx != x || yy != y) && row[xx] >= 0)
					++nb;
		}
		num += c.hp * static_cast<float>(1 + nb);
		den += c.hp;
	}
	return den > 0 ? num / den : 1.0f;
}

// Fuel per exact simulation of an n-member group: a conservative estimate.
inline long exact_cost(long n) { return n <= 1 ? 200L : 1000L + 100L * n * n; }
inline long proxy_cost(long n) { return 400L + 350L * n; }
constexpr long LOOP_PER = 2000; // measured <= 1,130 per farmable group (tank load + walks), 134 maps

} // namespace
Feats compute(int team_size, const std::vector<std::uint8_t>& acc, long reserve)
{
	Feats F;
	const long f0 = fuel();
	const std::size_t ng = static_cast<std::size_t>(M.ng);
	if (!M.done() || !M.has_home || acc.size() != ng || f0 < reserve + 20000L + 400L * static_cast<long>(ng))
		return F;
	const float champs = 2.0f * static_cast<float>(std::max(1, team_size));

	// Walk field to the altars with camps passable (feat3 dAlt): sources are the standable altar neighbours.
	distance_field fa;
	const long field = 3L * M.w * M.h + 4000;
	if (fuel() > reserve + field + 30000 && bbany(M.altar_adj_all))
	{
		bitboard vis{};
		fa.compute(M.block, M.altar_adj_all, vis);
		F.altar_field = true;
	}

	// Splash tier from the budget: exact needs every farmable group <= 32 members. Costs per group (fuel, with a margin): exact
	// simulation exact_cost(n), neighbour proxy proxy_cost(n), the rest of the loop (tank load, walks) LOOP_PER.
	long est_exact = 0, est_cap = 0, est_prx = 0, base = 0;
	bool exact_ok = true;
	for (std::size_t i = 0; i < ng; ++i)
	{
		const GroupI& g = M.groups[i];
		if (acc[i] > 1 || g.n_mono > 0)
			continue;
		const long n = static_cast<long>(static_cast<std::size_t>(g.nm));
		F.max_members = std::max(F.max_members, static_cast<int>(n));
		if (n > MAXN)
			exact_ok = false;
		base += LOOP_PER + 25L * n;
		est_exact += exact_cost(n);
		est_cap += n <= 10 ? exact_cost(n) : proxy_cost(n);
		est_prx += proxy_cost(n);
	}
	const long budget = fuel() - reserve - 15000L - base;
	if (est_prx > budget + 40000)
		return F; // not even the proxy tier fits: no map features (team-size values)
	F.tier = (exact_ok && est_exact < budget) ? 0 : (est_cap < budget ? 1 : 2);
	F.est_splash = F.tier == 0 ? est_exact : (F.tier == 1 ? est_cap : est_prx);

	const long f_loop = fuel();
	F.fuel_field = f0 - f_loop;
	float gem_r = 0, gold_r = 0, all_r = 0, hp_r = 0, att_r = 0, solo_r = 0, spl_r = 0, prx_r = 0;
	float w_sum = 0, tr_sum = 0, wa_sum = 0, da_sum = 0;
	long fs = 0;
	for (std::size_t i = 0; i < ng; ++i)
	{
		const GroupI& g = M.groups[i];
		const float cyc = static_cast<float>(std::max(10, g.respawn + 10)) + g.hp / 150.0f;
		const float gr = static_cast<float>(g.gems) / cyc, dr = static_cast<float>(g.gold) / cyc, hr = g.hp / cyc;
		if (acc[i] <= 2)
			all_r += gr; // game length: every group we can reach (walk, dash or crystal), monoliths included
		if (acc[i] > 1 || g.n_mono > 0)
			continue;
		++F.n_farm;
		gem_r += gr;
		gold_r += dr;
		hp_r += hr;
		att_r += hr * static_cast<float>(g.n_att);
		// Tank load: attackers by strength per HP, descending; load = sum strength * elapsed clear time.
		std::array<std::pair<float, float>, 40> a{};
		const std::size_t na = std::min<std::size_t>(g.att.size(), a.size());
		for (std::size_t j = 0; j < na; ++j)
			a[j] = g.att[j];
		for (std::size_t j = 1; j < na; ++j) // insertion sort, strength per HP descending (stable)
		{
			const auto key = a[j];
			std::size_t q = j;
			while (q > 0 && key.second * a[q - 1].first > a[q - 1].second * key.first)
			{
				a[q] = a[q - 1];
				--q;
			}
			a[q] = key;
		}
		float t = 0, load = 0;
		for (std::size_t j = 0; j < na; ++j)
		{
			t += a[j].first / 150.0f;
			load += a[j].second * t;
		}
		if (load <= 900.0f)
			solo_r += gr;
		// Splash of the chosen tier. If the exact tier runs short (estimate wrong), the whole map falls back to the proxy
		// tier, recomputed below over every farmable group.
		const long n = static_cast<long>(static_cast<std::size_t>(g.nm));
		if (F.tier == 0 || (F.tier == 1 && n <= 10))
		{
			if (fuel() < reserve + 10000 + 2 * exact_cost(n))
				F.tier = 2;
			else
			{
				const long fq = fuel();
				spl_r += hr * splash_exact(g);
				fs += fq - FXR_FUEL();
			}
		}
		else if (F.tier == 1)
			spl_r += hr * splash_proxy(g);
		if (acc[i] == 0 && g.d_home != UNREACH)
		{
			const float w = gr + 0.05f * dr + 1e-9f;
			std::uint16_t dal = UNREACH;
			if (F.altar_field)
			{
				const FView va = fview(fa);
				for (const int ci : g.members)
					dal = std::min(dal, va(M.camps[static_cast<std::size_t>(ci)].pos));
			}
			else
				dal = g.d_altar;
			w_sum += w;
			tr_sum += w * (static_cast<float>(g.d_home) + (dal == UNREACH ? 200.0f : static_cast<float>(dal)));
			if (dal != UNREACH)
			{
				wa_sum += w;
				da_sum += w * static_cast<float>(dal);
			}
		}
	}
	if (F.tier == 2)
	{
		// Proxy tier (chosen, or the fallback): neighbour counts over every farmable group.
		for (std::size_t i = 0; i < ng; ++i)
		{
			const GroupI& g = M.groups[i];
			if (acc[i] > 1 || g.n_mono > 0)
				continue;
			const float cyc = static_cast<float>(std::max(10, g.respawn + 10)) + g.hp / 150.0f;
			prx_r += g.hp / cyc * splash_proxy(g);
		}
	}
	F.fuel_splash = fs;
	F.fuel_loop = f_loop - FXR_FUEL();
	using namespace dv3;
	F.x[F_GEM_RATE] = 100.0f * gem_r / champs;
	F.x[F_GOLD_RATE] = 100.0f * gold_r / champs;
	F.x[F_GROUPS] = static_cast<float>(F.n_farm) / champs;
	F.x[F_LEN] = std::min(2000.0f, 100.0f + 1000.0f / std::max(1e-6f, 0.4f * 0.5f * all_r));
	F.x[F_ATT] = hp_r > 0 ? att_r / hp_r : 0.0f;
	F.x[F_DALT] = wa_sum > 0 ? da_sum / wa_sum : 200.0f;
	F.x[F_TRIP] = w_sum > 0 ? tr_sum / w_sum : 300.0f;
	F.x[F_SOLO] = gem_r > 0 ? solo_r / gem_r : 0.0f;
	const float mult = F.tier == 2 ? (hp_r > 0 ? prx_r / hp_r : 1.0f) : (hp_r > 0 ? spl_r / hp_r : 1.0f);
	F.x[F_SPLASH] = std::log(std::max(1.0f, mult));
	F.ok = true;
	F.fuel_used = f0 - FXR_FUEL();
	return F;
}

} // namespace nova::mapfeat
