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
// v716 ACX: MCL_BIT_CLUSTER when attacker groups hold < 10% of the walkable gems; MCL_BIT_GOLDFREE when the walkable gold rate per
// champion is under 60 (mapfeat's F_GOLD_RATE formula over walkable non-monolith groups). Static map data only.
static unsigned acx_class_bits()
{
	using namespace nova;
	float gem_all = 0.0f, gem_att = 0.0f, gold_r = 0.0f;
	const bool xfb_smx5 = true; // v7xx XFB SMX5: read once
#define XFB_SMX5 xfb_smx5
	for (const auto& g : M.groups)
	{
		if (g.access != ACC_WALK)
			continue;
		gem_all += static_cast<float>(g.gems);
		if (g.n_att > 0)
			gem_att += static_cast<float>(g.gems);
		if (!XFB_SMX5 && g.n_mono == 0)
			gold_r += static_cast<float>(g.gold) / (static_cast<float>(std::max(10, g.respawn + 10)) + g.hp / 150.0f);
	}
	unsigned b = 0;
	if (gem_all > 0.0f && gem_att < 0.10f * gem_all)
		b |= static_cast<unsigned>(MCL_BIT_CLUSTER);
	if (XFB_SMX5)
		return b; // v7xx XFB SMX5
	int ts = P.n;
	if (ts <= 0)
	{
		try
		{
			ts = static_cast<int>(cambc::draft::team_size()); // the draft turn (P is filled at play)
		}
		catch (...)
		{
			ts = 0;
		}
	}
	if (ts <= 0)
		return b; // no team size: no gold class (CLUSTER still stands)
	if (100.0f * gold_r / (2.0f * static_cast<float>(ts)) < 60.0f)
		b |= static_cast<unsigned>(MCL_BIT_GOLDFREE);
	return b;
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
	if (nc >= MCL_TAB[2] && !(nc == 0xFFFF)) // MDC bit 4: no walkable group is not a far map
		b |= 1u;
	if (nc >= MCL_TAB[3] && !(nc == 0xFFFF))
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
	b |= acx_class_bits();
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
// MCL3 (Shared Mem skeleton): the owners' class bits, from draft-time map features only (bits in common_flags.h at MCL3_XID).
unsigned mcl3_compute()
{
	unsigned b = 0;
	/* MCL3 owners: one line each, flag read first, e.g. if (X_ON(1) && feature()) b |= 1u; */
	if (nova::M.ng >= LAH_TAB[2]) // v7xx LAH: MANYGRP (bit 128)
		b |= 128u;
	return b;
}
static int mcl3_c = -1; // map_class3's cache
int map_class3()
{
	if (mcl3_c >= 0)
		return mcl3_c;
	const std::uint32_t v = nova::dmem::extra(MCL3_XID, 0xFFFFu);
	if (v != 0xFFFFu)
		mcl3_c = static_cast<int>(v & 0xFFu);
	else if (nova::M.done())
		mcl3_c = static_cast<int>(mcl3_compute());
	return mcl3_c < 0 ? 0 : mcl3_c;
}
// TBG: TAVI_BG from the map's camps (draft-time; same counts as tools/lab/mapclass.d/tavi_bg.py, one entry per physical camp).
static bool tbg_tavi_bg()
{
	int n = 0, gc = 0, mc = 0;
	for (const auto& c : nova::M.camps)
	{
		++n;
		if (c.type == cambc::camp_type::gold_cluster)
			++gc;
		else if (c.type == cambc::camp_type::gem_cluster)
			++mc;
		else if (c.type == cambc::camp_type::elk || c.type == cambc::camp_type::golem || c.type == cambc::camp_type::monolith)
			return false;
	}
	return gc + mc > 0 && 5 * (gc + mc) >= 4 * n && 2 * gc >= gc + mc;
}
// v79x JKC (b2088): the jackpot class from draft-time map features: the largest group by gems is mid (contest .4-.6), >= 300 gems,
// >= half of all gems, no other group >= 90% of it; our half's groups (contest < .4) cap < 150 gems and >= 400 gold per 100 rounds.
int jkc_class_group()
{
	using namespace nova;
	int big = -1, second = 0, tg = 0;
	for (int gi = 0; gi < M.ng; ++gi)
	{
		const auto& g = M.groups[static_cast<std::size_t>(gi)];
		tg += g.gems;
		if (big < 0 || g.gems > M.groups[static_cast<std::size_t>(big)].gems)
		{
			if (big >= 0)
				second = std::max(second, M.groups[static_cast<std::size_t>(big)].gems);
			big = gi;
		}
		else
			second = std::max(second, g.gems);
	}
	if (big < 0)
		return -1;
	const auto& b = M.groups[static_cast<std::size_t>(big)];
	float halfcap = 0, goldcap = 0;
	for (const auto& g : M.groups)
		if (g.contest < 0.4f)
		{
			halfcap += static_cast<float>(g.gems) * 100.0f / static_cast<float>(g.respawn + 5);
			goldcap += static_cast<float>(g.gold) * 100.0f / static_cast<float>(g.respawn + 5);
		}
	return (b.contest >= 0.4f && b.contest <= 0.6f && static_cast<float>(second) < 0.9f * static_cast<float>(b.gems) && b.gems >= 300 && 2 * b.gems >= tg &&
			   halfcap < 150.0f && goldcap >= 400.0f)
		? big
		: -1;
}
// MCL4 (Shared Mem skeleton, b1866): the second owners' class byte (bits in common_flags.h at MCL4_XID).
// v8xx PCP: ONEALTGRP = every altar tile within Chebyshev 8 of every other (tools/lab/mapclass.d/altgrp.py altgrp1).
static bool pcp_one_altar_group()
{
	const std::size_t n = nova::M.altars.size();
	if (n == 0)
		return false;
	for (std::size_t i = 0; i < n; ++i)
		for (std::size_t j = i + 1; j < n; ++j)
			if (nova::cheb(nova::M.altars[i].pos, nova::M.altars[j].pos) > 8)
				return false;
	return true;
}
// b2233 BWT: hidden-member tiles = camp spawn tiles whose cardinal bush cluster (Q44) holds no non-camp tile: no body can stand in
// that cluster, so the member is seen only by a ward on its tile or a refused move onto it (RC C670). Static (M only), built once.
static nova::bitboard bwt_hid_bb{};
static int bwt_hid_n = -1;
static __attribute__((noinline)) void bwt_hid_build()
{
	using namespace nova;
	bwt_hid_n = 0;
	if (M.w <= 0 || M.h <= 0)
		return;
	std::vector<std::uint8_t> seen(static_cast<std::size_t>(M.w * M.h), 0);
	std::vector<vec2> comp, st;
	for (const auto& c : M.camps)
	{
		const vec2 s0 = c.pos;
		if (!inb(s0) || !bbget(M.bushes, s0) || seen[static_cast<std::size_t>(s0.y * M.w + s0.x)])
			continue;
		comp.clear();
		st.clear();
		st.push_back(s0);
		seen[static_cast<std::size_t>(s0.y * M.w + s0.x)] = 1;
		bool all_camp = true;
		while (!st.empty())
		{
			const vec2 q = st.back();
			st.pop_back();
			comp.push_back(q);
			if (!bbget(M.camp_tiles, q))
				all_camp = false;
			const vec2 nb[4] = { { q.x + 1, q.y }, { q.x - 1, q.y }, { q.x, q.y + 1 }, { q.x, q.y - 1 } };
			for (const vec2 n : nb)
				if (inb(n) && bbget(M.bushes, n) && !seen[static_cast<std::size_t>(n.y * M.w + n.x)])
				{
					seen[static_cast<std::size_t>(n.y * M.w + n.x)] = 1;
					st.push_back(n);
				}
		}
		if (!all_camp)
			continue;
		for (const vec2 q : comp)
		{
			bbset(bwt_hid_bb, q);
			++bwt_hid_n;
		}
	}
}
// b2377 DCG (RC X817): bwt_hid_build's fuel estimate, ~110 per bush tile + the w*h seen vector (callers read DCG_ON first).
__attribute__((noinline)) long dcg_bwt_need()
{
	return 110L * static_cast<long>(nova::M.bushes.count()) + 4L * static_cast<long>(nova::M.w) * static_cast<long>(nova::M.h) + 20000L;
}
int bwt_hid_count()
{
	if (bwt_hid_n < 0)
	{
		if (!nova::M.done())
			return 0; // not cached before the map data is complete
		bwt_hid_build();
	}
	return bwt_hid_n;
}
bool bwt_hid_tile(int x, int y)
{
	if (bwt_hid_count() <= 0)
		return false;
	const nova::vec2 p{ x, y };
	return nova::inb(p) && nova::bbget(bwt_hid_bb, p);
}
static int bwt_cls = -1; // bwt_class's cache: the draft byte only (a missing byte reads OFF)
bool bwt_class()
{
	if (bwt_cls < 0)
		bwt_cls = (nova::dmem::extra(MCL4_XID, 0u) & 16u) != 0 ? 1 : 0;
	return bwt_cls != 0;
}
unsigned mcl4_compute()
{
	unsigned b = 0;
	if (nova::M.done() && bwt_hid_count() > 0) // b2233 BWT: MCL4 bit 16 HIDMEM (Shared Mem)
		b |= 16u;
	if (jkc_class_group() >= 0)
		b |= 128u; // v79x JKC (b2088): MCL4 bit 128 jackpot class
	return b;
}
static int mcl4_c = -1; // map_class4's cache
int map_class4()
{
	if (mcl4_c >= 0)
		return mcl4_c;
	const std::uint32_t v = nova::dmem::extra(MCL4_XID, 0xFFFFu);
	if (v != 0xFFFFu)
		mcl4_c = static_cast<int>(v & 0xFFu);
	else if (nova::M.done())
		mcl4_c = static_cast<int>(mcl4_compute());
	return mcl4_c < 0 ? 0 : mcl4_c;
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

// v642 LSP (spec_lsp_1109): the draft-time map features of the map-aware LNR constants. x1 log1p(farmable gems + gold/10 per
// body; farmable = no monolith, walk or dash), x2 log(area), x3 altars, x4 log1p(spawn-to-spawn walk), x5 heavy groups' gem share,
// x6 log((gems + 5) / (gold/10 + 5)), x7 scarcity clamp(1 - gems / (2T) / 37.25, 0, 1), x8 gem share of groups with walk share .4-.6.
void lsp_raw(int T, float* x)
{
	using namespace nova;
	float gems = 0, gold = 0, farm = 0, heavy = 0, mid = 0;
	for (const auto& g : M.groups)
	{
		gems += static_cast<float>(g.gems);
		gold += static_cast<float>(g.gold);
		if (g.n_mono == 0 && g.access != ACC_TP)
			farm += static_cast<float>(g.gems) + 0.1f * static_cast<float>(g.gold);
		if (g.heavy())
			heavy += static_cast<float>(g.gems);
		if (g.contest >= 0.4f && g.contest <= 0.6f)
			mid += static_cast<float>(g.gems);
	}
	const float tb = static_cast<float>(std::max(1, T));
	const std::uint16_t s2s = spawn_walk();
	x[0] = std::log1p(farm / tb);
	x[1] = std::log(static_cast<float>(std::max(1, G.w * G.h)));
	x[2] = static_cast<float>(M.na);
	x[3] = std::log1p(s2s == UNREACH ? static_cast<float>(plan_tune::FAR_WALK) : static_cast<float>(s2s));
	x[4] = gems > 0 ? heavy / gems : 0.0f;
	x[5] = std::log((gems + 5.0f) / (0.1f * gold + 5.0f));
	x[6] = std::min(1.0f, std::max(0.0f, 1.0f - gems / (2.0f * tb) / 37.25f));
	x[7] = gems > 0 ? mid / gems : 0.0f;
}
// pool mean and SD of each raw feature (b1762 diag: 1,178 records on 600 stock maps, half weird)
static constexpr float LSP_MU[8] = { 4.5807f, 7.7328f, 4.4992f, 3.2774f, 0.7120f, 1.1108f, 0.1400f, 0.4728f },
					   LSP_SD[8] = { 0.7104f, 0.6273f, 3.8560f, 1.0380f, 0.3187f, 1.0090f, 0.2533f, 0.3094f };
std::uint32_t lsp_map_pack(int T)
{
	float x[8];
	lsp_raw(T, x);
	std::uint32_t v = 0;
	for (int i = 0; i < 8; ++i)
	{
		const float z = (x[i] - LSP_MU[i]) / LSP_SD[i];
		const int q = std::min(15, std::max(0, static_cast<int>(std::floor(z * 3.75f + 8.0f))));
		v |= static_cast<std::uint32_t>(q) << (4 * i);
	}
	return v == 0xFFFFFFFFu ? 0xFFFFFFFEu : v; // all-ones is the play side's 'absent'
}

bool dm2_dead(cambc::vec2 p) { return false; }
// macros local to this module end here
