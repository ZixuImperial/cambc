// plan_map_classes.cc: Map classes, decided from draft-time map features.
#include "plan_internal.h"
// The walk from our spawn to the tiles around the enemy's.
static std::uint16_t spawn_walk()
{
	using namespace nova;
	std::uint16_t s2s = UNREACH;
	bbforeach(M.enemy_spawn,
		[&](vec2 p)
		{
			for (const vec2 d : DIRS)
			{
				const vec2 q = p + d;
				if (inb(q) && !bbget(M.enemy_spawn, q))
					s2s = std::min(s2s, dfget(M.f_home, q));
			}
		});
	return s2s;
}
// 0 below lo, 2 at hi or above, else 1.
NOVA_INLINE unsigned band3(float v, float lo, float hi) { return v < lo ? 0u : (v >= hi ? 2u : 1u); }
// The richest group by our spawn outweighs everything off both spawns, and the spawns lie far apart.
static bool spawn_econ_dominant()
{
	using namespace nova;
	struct Rc { int x0 = 1 << 20, y0 = 1 << 20, x1 = -(1 << 20), y1 = -(1 << 20); };
	auto rect = [](const bitboard& sp)
	{
		Rc r;
		bbforeach(sp, [&](vec2 q) { r.x0 = std::min(r.x0, q.x); r.y0 = std::min(r.y0, q.y); r.x1 = std::max(r.x1, q.x); r.y1 = std::max(r.y1, q.y); });
		return r;
	};
	const Rc ra = rect(M.my_spawn), rb = rect(M.enemy_spawn); // the engine's spawn is one rectangle: Chebyshev distance O(1)
	auto near_sp = [](const Rc& r, vec2 p)
	{
		return std::max(std::max(0, std::max(r.x0 - p.x, p.x - r.x1)), std::max(0, std::max(r.y0 - p.y, p.y - r.y1))) <= 3;
	};
	std::int64_t home = 0, oth = 0;
	for (const auto& g : M.groups)
	{
		bool mine = false, theirs = false;
		for (int ci : g.members)
		{
			const vec2 p = M.camps[static_cast<std::size_t>(ci)].pos;
			mine = mine || near_sp(ra, p);
			theirs = theirs || near_sp(rb, p);
		}
		if (mine && g.n_mono > 0)
			home = std::max<std::int64_t>(home, g.gems);
		if (!mine && !theirs)
			oth += g.gems;
	}
	const int s2s = spawn_walk();
	return home > 0 && s2s != UNREACH && s2s >= SSF_TAB[2] && oth * 100LL <= home * static_cast<std::int64_t>(SSF_TAB[3]);
}
unsigned map_class_compute()
{
	if (nova::M.groups.empty())
		return 0;
	int nc = 0xFFFF;
	for (const auto& g : nova::M.groups)
		if (g.d_home != nova::UNREACH)
			nc = std::min<int>(nc, g.d_home);
	unsigned b = 0;
	if (nc >= MCL_TAB[2])
		b |= 1u;
	if (nc >= MCL_TAB[3])
		b |= 2u;
	std::int64_t tot = 0, top = 0;
	for (const auto& g : nova::M.groups)
	{
		tot += g.gems;
		top = std::max<std::int64_t>(top, g.gems);
	}
	if (tot > 0 && top * 100LL >= static_cast<std::int64_t>(OGS_TAB[2]) * tot)
		b |= static_cast<unsigned>(MCL_BIT_ONEGEM);
	if (nova::M.has_home && spawn_econ_dominant()) // Static map data.
		b |= static_cast<unsigned>(MCL_BIT_SPAWNECON);
	return b;
}

static int mcl_c = -1; // map_class's cache at file scope, its hit inline.
int map_class_slow();
__attribute__((always_inline)) int map_class()
{
	if (mcl_c >= 0)
		return mcl_c;
	return map_class_slow();
}
__attribute__((noinline)) int map_class_slow()
{
	int& c = mcl_c;
	const std::uint32_t v = nova::dmem::extra(MCL_XID, 0xFFFFu);
	if (v != 0xFFFFu)
		c = static_cast<int>(v & 0xFFu);
	else if (!nova::M.groups.empty())
		c = static_cast<int>(map_class_compute());
	if (c >= 0)
		c |= static_cast<int>(nova::dmem::extra(DMF_MCL2_XID, 0u) & 0xFFFFu) << 8; // MCL2 bits 8+.
	return c < 0 ? 0 : c;
}

// MCL2 bits from the draft's analysis (inert until a gate reads them). Features: T bodies, area = w * h, gems/gold = all camps, top1
// = largest group's gem share, s2s = walk to beside their spawn (float math). Contested region: regions = groups linked by camp
// tiles within Chebyshev 3; value rate vr = (gems + .35 gold) / respawn, monolith groups out; rho = d_home / (d_home + d_enemy) of
// the region's nearest groups; the top region with .4 <= rho <= .6 holds S of vr and SL of the light (no elk/golem/monolith) vr; AC
// = S >= 1/3 or SL >= 1/3.
static bool contested_region_present()
{
	using namespace nova;
	const int ng = M.ng;
	std::vector<int> uf(static_cast<std::size_t>(ng));
	for (int i = 0; i < ng; ++i)
		uf[static_cast<std::size_t>(i)] = i;
	auto fd = [&](int x)
	{
		while (uf[static_cast<std::size_t>(x)] != x)
			x = uf[static_cast<std::size_t>(x)] = uf[static_cast<std::size_t>(uf[static_cast<std::size_t>(x)])];
		return x;
	};
	std::vector<std::int16_t> lab(static_cast<std::size_t>(G.w * G.h), -1); // camp tile -> group
	for (const auto& c : M.camps)
		if (c.group >= 0 && inb(c.pos))
			lab[static_cast<std::size_t>(c.pos.y * G.w + c.pos.x)] = static_cast<std::int16_t>(c.group);
	if (G.w <= 128)
	{
		// The same window, row by row through a mask of the labelled tiles (x ascending, as above).
		std::vector<std::uint64_t> rm(static_cast<std::size_t>(2 * G.h), 0);
		for (const auto& c : M.camps)
			if (c.group >= 0 && inb(c.pos))
				rm[static_cast<std::size_t>(2 * c.pos.y + (c.pos.x >> 6))] |= 1ull << (c.pos.x & 63);
		for (const auto& c : M.camps)
		{
			if (c.group < 0 || !inb(c.pos))
				continue;
			const int x0 = std::max(0, c.pos.x - plan_tune::AC_LINK_R), x1 = std::min(G.w - 1, c.pos.x + plan_tune::AC_LINK_R);
			for (int y = std::max(0, c.pos.y - plan_tune::AC_LINK_R); y <= std::min(G.h - 1, c.pos.y + plan_tune::AC_LINK_R); ++y)
				for (int wi = x0 >> 6; wi <= (x1 >> 6); ++wi)
				{
					const int lo = std::max(x0, wi * 64) - wi * 64, hi = std::min(x1, wi * 64 + 63) - wi * 64;
					std::uint64_t m = rm[static_cast<std::size_t>(2 * y + wi)];
					m &= hi >= 63 ? ~0ull : ((1ull << (hi + 1)) - 1ull);
					m &= ~((1ull << lo) - 1ull);
					while (m)
					{
						const int x = wi * 64 + __builtin_ctzll(m);
						m &= m - 1;
						const int o = lab[static_cast<std::size_t>(y * G.w + x)];
						if (o >= 0 && o != c.group)
							uf[static_cast<std::size_t>(fd(o))] = fd(c.group);
					}
				}
		}
	}
	else
		for (const auto& c : M.camps)
		{
			if (c.group < 0 || !inb(c.pos))
				continue;
			for (int y = std::max(0, c.pos.y - plan_tune::AC_LINK_R); y <= std::min(G.h - 1, c.pos.y + plan_tune::AC_LINK_R); ++y)
				for (int x = std::max(0, c.pos.x - plan_tune::AC_LINK_R); x <= std::min(G.w - 1, c.pos.x + plan_tune::AC_LINK_R); ++x)
				{
					const int o = lab[static_cast<std::size_t>(y * G.w + x)];
					if (o >= 0 && o != c.group)
						uf[static_cast<std::size_t>(fd(o))] = fd(c.group);
				}
		}
	std::vector<float> rv(static_cast<std::size_t>(ng), 0), rl(static_cast<std::size_t>(ng), 0);
	std::vector<int> rh(static_cast<std::size_t>(ng), UNREACH), re(static_cast<std::size_t>(ng), UNREACH);
	float tv = 0, tl = 0;
	for (int i = 0; i < ng; ++i)
	{
		const auto& g = M.groups[static_cast<std::size_t>(i)];
		const int r = fd(i);
		rh[static_cast<std::size_t>(r)] = std::min<int>(rh[static_cast<std::size_t>(r)], g.d_home);
		re[static_cast<std::size_t>(r)] = std::min<int>(re[static_cast<std::size_t>(r)], g.d_enemy);
		if (g.n_mono > 0 || g.respawn <= 0)
			continue;
		const float v = (static_cast<float>(g.gems) + plan_tune::AC_GOLD_SHARE * static_cast<float>(g.gold)) / static_cast<float>(g.respawn);
		rv[static_cast<std::size_t>(r)] += v;
		tv += v;
		if (g.n_elk == 0 && g.n_golem == 0)
		{
			rl[static_cast<std::size_t>(r)] += v;
			tl += v;
		}
	}
	int best = -1;
	for (int r = 0; r < ng; ++r)
	{
		if (fd(r) != r || rh[static_cast<std::size_t>(r)] == UNREACH || re[static_cast<std::size_t>(r)] == UNREACH)
			continue;
		const float rho = static_cast<float>(rh[static_cast<std::size_t>(r)]) /
			std::max(1.0f, static_cast<float>(rh[static_cast<std::size_t>(r)] + re[static_cast<std::size_t>(r)]));
		if (rho >= plan_tune::AC_RHO_LOW && rho <= plan_tune::AC_RHO_HIGH && (best < 0 || rv[static_cast<std::size_t>(r)] > rv[static_cast<std::size_t>(best)]))
			best = r;
	}
	return best >= 0 && ((tv > 0 && 3.0f * rv[static_cast<std::size_t>(best)] >= tv) || (tl > 0 && 3.0f * rl[static_cast<std::size_t>(best)] >= tl));
}
unsigned compute_map_class_bits(int T)
{
	using namespace nova;
	if (M.groups.empty() || T <= 0 || !M.has_home)
		return 0;
	float gems = 0, gold = 0, top = 0, pocket = 0;
	for (const auto& g : M.groups)
	{
		gems += static_cast<float>(g.gems);
		gold += static_cast<float>(g.gold);
		top = std::max(top, static_cast<float>(g.gems));
		if (g.access != ACC_WALK)
			pocket += static_cast<float>(g.gems);
	}
	const std::uint16_t s2s = spawn_walk();
	const float tt = 2.0f * static_cast<float>(T);
	const float apb = std::log1p(static_cast<float>(G.w * G.h) / tt), gpb = gems / tt;
	const float top1 = gems > 0 ? top / gems : 0.0f;
	const float ls2s = std::log1p(s2s == UNREACH ? static_cast<float>(plan_tune::FAR_WALK) : static_cast<float>(s2s));
	namespace t = plan_tune;
	const float F = t::F_APB_W * (apb - t::F_APB_MU) / t::F_APB_SD +
		t::F_GPB_W * (std::log1p(gpb) - t::F_GPB_MU) / t::F_GPB_SD +
		t::F_TOP_W * (top1 - t::F_TOP_MU) / t::F_TOP_SD +
		t::F_S2S_W * (ls2s - t::F_S2S_MU) / t::F_S2S_SD;
	unsigned b = band3(F, t::F_LOW, t::F_HIGH);
	const float gg = std::log((gold + 50.0f) / (gems + 10.0f));
	b |= band3(gg, t::GG_LOW, t::GG_HIGH) << 2;
	b |= band3(gpb, t::GPB_LOW, t::GPB_HIGH) << 4;
	if (s2s != UNREACH && s2s <= t::S2S_NEAR)
		b |= 64u;
	if (pocket > 0)
		b |= 128u;
	if (M.ng <= 255 && contested_region_present())
		b |= 256u;
	return b;
}

bool dm2_dead(cambc::vec2 p) { return false; }
// macros local to this module end here
