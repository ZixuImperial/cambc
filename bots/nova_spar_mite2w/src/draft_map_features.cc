// draft_map_features.cc: Map features computed on the first draft turn.
#include "draft_internal.h"
namespace nova::drafting {
namespace {

// Two map features from MapInfo (walk distances from both spawns and the groups), computed once on turn 1. Per group the value is
// gem rate + 0.1 x gold rate, rates per cycle (cyc = max(10, respawn + 10) + hp / 150). Centrality: the walkable value in the best
// area of radius 6 (Chebyshev between member centroids) made of groups both teams walk to alike (|d_home - d_enemy| <= max(3, 0.2 x
// the larger)), as a share of all walkable value, monoliths in. Chain share: the farmable walkable value (no monolith) in groups of
// >= 2 members that are all clusters (members that never attack, 120 HP), as a share of all farmable walkable value. Rule knowledge
// only (camp kinds). Skipped (terms 0) when the fuel estimate does not fit.
long centrality_fuel_estimate()
{
	long n = 0;
	for (const auto& g : M.groups)
		n += static_cast<long>(static_cast<std::size_t>(g.nm));
	return 6000L + 260L * static_cast<long>(static_cast<std::size_t>(M.ng)) + 60L * n;
}

// Real turns from our spawn, walking v walking + dash. One search over (tile, turn, q), q = the first turn a dash could leave this
// tile: a turn is a walk step and / or a dash (walk first), a dash lands 2 steps away over a hole, the next one comes
// slot_cooldown() turns later, camps block as at game start. Only hops with no walkable middle are searched (a hop a walker could
// take in 2 steps saves 1 turn in 8 on any map, and searching them is expensive: 4M fuel on a 34 x 34 map), so a map without such
// hops costs nothing and the dash time is the walk. Fronts by turn (walk steps) and buckets (dash landings); a label lives only if
// its q beats every label already taken on its tile, so the first label on a tile gives its dash time. About 200 fuel a label, 1.7
// labels a tile, so first the cooldown-free f_home_dash bounds x: below DTM_XSKIP (x^2 under .001) there is nothing to search and x
// is 0. Stops at the turn the last target walks to, at DTM_TMAX, or when fuel falls to `reserve` (then dtm_ok stays false and the
// draft is the base draft).
constexpr int DTM_TMAX = 200;
constexpr float DTM_XSKIP = 0.03f;
// x: per target, the share of the walk a dash saves x how slow the walk is (w / (w + W0)); the altar's and the groups' weighted by slot.
float dash_slow_save(float aw, float ad, float gw, float gd)
{
	const float w0 = static_cast<float>(DTM_TAB[4]), wa = 0.01f * static_cast<float>(DTM_TAB[5]);
	auto f = [&](float w, float d) { return w > 1e-3f ? std::max(w - d, 0.0f) / (w + w0) : 0.0f; };
	return wa * f(aw, ad) + (1.0f - wa) * f(gw, gd);
}
constexpr std::uint16_t DW_INF = 0xFFFF;
constexpr int DW_NX[8] = { -1, 0, 1, -1, 1, -1, 0, 1 }, DW_NY[8] = { -1, -1, -1, 0, 0, 1, 1, 1 };
struct DashLab
{
	std::uint16_t tile, q;
	int next;
};
struct DashCell
{
	std::uint16_t tile, q;
};
// The grid, labels and targets of one dash_walk_times search. The grid is padded by 2 tiles on every side.
struct DashWalk
{
	int W, H, PW, PH, N;
	// minq: the best q taken on a tile, 0 on a tile no label may enter. hopm: 16 bits, the shortcut hops from a tile.
	std::vector<std::uint16_t> minq_v, arr_v, hopm;
	std::vector<std::uint8_t> mo_v;
	std::vector<int> gaps; // HMS bit 1: the gap tiles (mo == 2), filled by classify_tiles only with the bit on
	std::uint16_t* minq;
	std::uint16_t* arr;
	std::uint8_t* mo;
	std::vector<DashLab> L;
	std::array<int, DTM_TMAX + 16> head;
	FView vcb, vda;
	float cap;
	int tstop;
	std::vector<std::uint16_t> gwalk;
	float aw, alb, vs, gw, glb;
	bool any_gap;
	int off[8];
	int hop[16], mid[16][3], nmid[16];

	void push_dash(int t, int p, int q)
	{
		L.push_back(DashLab{ static_cast<std::uint16_t>(p), static_cast<std::uint16_t>(q), head[static_cast<std::size_t>(t)] });
		head[static_cast<std::size_t>(t)] = static_cast<int>(L.size()) - 1;
	}
	int near_walk(vec2 c) const
	{
		int b = DW_INF;
		for (int d = 0; d < 8; ++d)
		{
			const vec2 n{ c.x + DW_NX[d], c.y + DW_NY[d] };
			if (inb(n))
				b = std::min<int>(b, vcb(n));
		}
		return b >= UNREACH ? DW_INF + 0 : b;
	}
	int near_dash(vec2 c) const
	{
		int b = DW_INF;
		for (int d = 0; d < 8; ++d)
			b = std::min<int>(b, arr[static_cast<std::size_t>((c.y + DW_NY[d] + 2) * PW + c.x + DW_NX[d] + 2)]);
		return b;
	}
	float capped(int v) const { return std::min(static_cast<float>(v), cap); }
	int near_lb(vec2 c) const
	{
		int b = DW_INF;
		for (int d = 0; d < 8; ++d)
		{
			const vec2 n{ c.x + DW_NX[d], c.y + DW_NY[d] };
			if (inb(n))
				b = std::min<int>(b, vda(n));
		}
		return b >= UNREACH ? DW_INF + 0 : b;
	}
};

// Walk times once (kept for the results), the slowest target, and the upper bound of x.
static __attribute__((always_inline)) inline void measure_walk_times(DashWalk& c)
{
	c.tstop = 0;
	c.gwalk = std::vector<std::uint16_t>(static_cast<std::size_t>(M.ng), DW_INF);
	c.aw = c.cap;
	c.alb = c.cap;
	c.vs = 0.0f;
	c.gw = 0.0f;
	c.glb = 0.0f;
	for (const auto& a : M.altars)
	{
		const int w = c.near_walk(a.pos);
		c.tstop = std::max(c.tstop, w);
		c.aw = std::min(c.aw, c.capped(w));
		c.alb = std::min(c.alb, c.capped(c.near_lb(a.pos)));
	}
	for (int gi = 0; gi < M.ng; ++gi)
	{
		const auto& g = M.groups[static_cast<std::size_t>(gi)];
		int w = DW_INF, d = DW_INF;
		for (const int ci : g.members)
		{
			const vec2 cp = M.camps[static_cast<std::size_t>(ci)].pos;
			w = std::min(w, c.near_walk(cp));
			d = std::min(d, c.near_lb(cp));
		}
		c.gwalk[static_cast<std::size_t>(gi)] = static_cast<std::uint16_t>(w);
		c.tstop = std::max(c.tstop, w);
		if (d == DW_INF)
			continue;
		const float v = static_cast<float>(g.gems) + 0.1f * static_cast<float>(g.gold);
		c.vs += v;
		c.gw += v * c.capped(w);
		c.glb += v * c.capped(d);
	}
	if (c.vs > 1e-6f)
	{
		c.gw /= c.vs;
		c.glb /= c.vs;
	}
	c.tstop = std::min(c.tstop, DTM_TMAX);
}

// Marks each tile: open (1), a gap a dash may cross but nobody may stand on (2), or no label may enter.
static __attribute__((always_inline)) inline void classify_tiles(DashWalk& c)
{
	c.any_gap = false; // Set when some tile is a gap: a dash may cross it but nobody may stand on it.
	const int W = c.W, H = c.H, PW = c.PW;
	c.gaps.clear();
	c.gaps.reserve(static_cast<std::size_t>(W * H / 8 + 8));
	const BView bb = bview(M.block_camps), bw = bview(M.walls), bc = bview(M.camp_tiles), be = bview(M.enemy_spawn);
	for (int y = 0; y < H; ++y)
		for (int x = 0; x < W; ++x)
		{
			const vec2 v{ x, y };
			const int i = (y + 2) * PW + x + 2;
			if (!bb(v))
			{
				c.minq[i] = DW_INF;
				c.mo[i] = 1;
			}
			else if (!bw(v) && !bc(v) && !be(v))
			{
				c.mo[i] = 2;
				c.any_gap = true;
				c.gaps.push_back(i);
			}
		}
}

// The 16 dash landings; each with the middles next to both ends (a straight hop has three, a knight's two, a corner one).
static __attribute__((always_inline)) inline void build_hop_tables(DashWalk& c)
{
	for (int d = 0; d < 8; ++d)
		c.off[d] = DW_NY[d] * c.PW + DW_NX[d];
	int h = 0;
	for (int dy = -2; dy <= 2; ++dy)
		for (int dx = -2; dx <= 2; ++dx)
		{
			if (std::max(std::abs(dx), std::abs(dy)) != 2)
				continue;
			c.hop[h] = dy * c.PW + dx;
			c.nmid[h] = 0;
			for (int d = 0; d < 8; ++d)
				if (std::max(std::abs(dx - DW_NX[d]), std::abs(dy - DW_NY[d])) == 1)
					c.mid[h][c.nmid[h]++] = c.off[d];
			++h;
		}
}

// A shortcut hop: the landing stands, some middle is a gap, no middle is walkable. From each gap tile, the tiles around it.
static __attribute__((always_inline)) inline void mark_shortcut_hops(DashWalk& c)
{
	const int W = c.W, H = c.H, PW = c.PW;
	const std::uint8_t* const mo = c.mo;
	c.hopm.assign(static_cast<std::size_t>(c.N), 0);
	for (int y = 0; y < H; ++y)
		for (int x = 0; x < W; ++x)
		{
			const int g = (y + 2) * PW + x + 2;
			if (mo[static_cast<std::size_t>(g)] != 2)
				continue;
			for (int d = 0; d < 8; ++d)
			{
				const int p = g + c.off[d];
				if (mo[static_cast<std::size_t>(p)] != 1 || c.hopm[static_cast<std::size_t>(p)] != 0)
					continue;
				unsigned hm = 0;
				for (int h = 0; h < 16; ++h)
				{
					if (mo[static_cast<std::size_t>(p + c.hop[h])] != 1)
						continue;
					int best = 0;
					for (int j = 0; j < c.nmid[h]; ++j)
						best = std::max<int>(best, mo[static_cast<std::size_t>(p + c.mid[h][j])] == 1 ? 3 : mo[static_cast<std::size_t>(p + c.mid[h][j])]);
					if (best == 2)
						hm |= 1u << h;
				}
				c.hopm[static_cast<std::size_t>(p)] = static_cast<std::uint16_t>(hm | 0);
			}
		}
}

// b1839 HMF: mark_shortcut_hops with bit 1 HMD1 (a launch tile is computed once: the same marks) and bit 2 HMF1 (a fuel test every row;
// false at the reserve, and dash_walk_times then keeps no dash times).
__attribute__((noinline)) bool hmf_mark_shortcut_hops(DashWalk& c, long reserve)
{
	const int W = c.W, H = c.H, PW = c.PW;
	const std::uint8_t* const mo = c.mo;
	const bool once = true, test = true;
	c.hopm.assign(static_cast<std::size_t>(c.N), 0);
	std::vector<std::uint8_t> done(once ? static_cast<std::size_t>(c.N) : 0, 0);
	int hms_row = -1;
	for (const int g : c.gaps)
	{
		if (test && g / PW != hms_row) // HMF1's fuel test, once per row that holds a gap
		{
			hms_row = g / PW;
			if (fuel() < reserve)
				return false;
		}
		for (int d = 0; d < 8; ++d)
		{
			const int p = g + c.off[d];
			if (mo[static_cast<std::size_t>(p)] != 1 || c.hopm[static_cast<std::size_t>(p)] != 0 || (once && done[static_cast<std::size_t>(p)] != 0))
				continue;
			if (once)
				done[static_cast<std::size_t>(p)] = 1;
			unsigned hm = 0;
			for (int h = 0; h < 16; ++h)
			{
				if (mo[static_cast<std::size_t>(p + c.hop[h])] != 1)
					continue;
				int best = 0;
				for (int j = 0; j < c.nmid[h]; ++j)
					best = std::max<int>(best, mo[static_cast<std::size_t>(p + c.mid[h][j])] == 1 ? 3 : mo[static_cast<std::size_t>(p + c.mid[h][j])]);
				if (best == 2)
					hm |= 1u << h;
			}
			c.hopm[static_cast<std::size_t>(p)] = static_cast<std::uint16_t>(hm | 0);
		}
	}
	return true;
}
// b1839 HMF bit 4 (HFR1a): the dash-label list bound for the fuel left above `reserve` (about 40 fuel a label, a regrowth copy included).
__attribute__((noinline)) std::size_t hfr_label_cap(long reserve)
{
	const long left = fuel() - reserve;
	return left > 0 ? static_cast<std::size_t>(left / 40) : 0;
}
// The search over fronts by turn (walk steps) and buckets (dash landings). False when the fuel falls to `reserve` or a front overflows.
static __attribute__((always_inline)) inline bool sweep_fronts(DashWalk& c, long reserve)
{
	std::uint16_t* const minq = c.minq;
	std::uint16_t* const arr = c.arr;
	const int tstop = c.tstop;
	const int CD = rs::slot_cooldown();
	const int FCAP = c.W * c.H;
	std::vector<DashCell> fa, fb;
	std::unique_ptr<DashCell[]> dfa_a, dfa_b; // v726 DFA1: default-initialised frontier buffers
	dfa_a.reset(new DashCell[static_cast<std::size_t>(FCAP)]);
	dfa_b.reset(new DashCell[static_cast<std::size_t>(FCAP)]);
	DashCell* cur = dfa_a.get();
	DashCell* nxt = dfa_b.get();
	int nc = 0;
	bbforeach(M.my_spawn, [&](vec2 v)
	{
		const int i = (v.y + 2) * c.PW + v.x + 2;
		if (minq[i] != 0 && nc < FCAP)
			cur[nc++] = DashCell{ static_cast<std::uint16_t>(i), 0 };
	});
	const int o0 = c.off[0], o1 = c.off[1], o2 = c.off[2], o3 = c.off[3], o4 = c.off[4], o5 = c.off[5], o6 = c.off[6], o7 = c.off[7];
	int hfr_k = 0; // v7xx HMF bit 4 (HFR1a): labels since the last fuel test
	std::size_t hfr_cap = 0; // v7xx HMF bit 4: the label-list bound from the fuel left
	for (int t = 0; t <= tstop; ++t)
	{
		if (fuel() < reserve)
			return false;
		hfr_cap = hfr_label_cap(reserve);
		int nn = 0, ci = 0;
		for (;;)
		{
			if ((++hfr_k & 63) == 0 && fuel() < reserve)
				return false; // v7xx HMF bit 4: a fuel test inside the front
			int p, q;
			if (ci < nc)
			{
				p = cur[ci].tile;
				q = cur[ci].q;
				++ci;
			}
			else
			{
				const int li = c.head[static_cast<std::size_t>(t)];
				if (li < 0)
					break;
				const DashLab b = c.L[static_cast<std::size_t>(li)];
				c.head[static_cast<std::size_t>(t)] = b.next;
				p = b.tile;
				q = b.q;
			}
			if (arr[p] == DW_INF)
				arr[p] = static_cast<std::uint16_t>(t);
			if (q > minq[p])
				continue;
			minq[p] = static_cast<std::uint16_t>(q);
			const int qw = q > t ? q : t;
			if (nn + 8 > FCAP)
				return false;
			// A walk step lands in the next front, so it takes its tile now: one label a front, not one per neighbour.
			auto step = [&](int n)
			{
				if (qw < minq[n])
				{
					minq[n] = static_cast<std::uint16_t>(qw);
					nxt[nn++] = DashCell{ static_cast<std::uint16_t>(n), static_cast<std::uint16_t>(qw) };
				}
			};
			step(p + o0);
			step(p + o1);
			step(p + o2);
			step(p + o3);
			step(p + o4);
			step(p + o5);
			step(p + o6);
			step(p + o7);
			if (c.any_gap && c.hopm[static_cast<std::size_t>(p)] != 0 && q + 1 <= tstop)
				for (int h = 0; h < 16; ++h)
					if ((c.hopm[static_cast<std::size_t>(p)] >> h & 1) && q + CD < minq[p + c.hop[h]])
					{
						if (c.L.size() >= hfr_cap)
							return false; // v7xx HMF bit 4: the label list is bounded by the fuel left
						c.push_dash(q + 1, p + c.hop[h], q + CD);
					}
		}
		std::swap(cur, nxt);
		nc = nn;
	}
	return true;
}
// v728 DPR1 + DPR2 (RC X313, from the diag copy nova_x313_dga sweep_fronts_new): the walk label carries the step that pushed it (high
// byte of q); the neighbours of its parent are skipped (their minq <= the parent's qw = this q <= qw already). Pops split into the front
// list, then the bucket. hopm pointer cached. The label body must stay always_inline (+27% fuel without).
static __attribute__((noinline)) bool sweep_fronts_dpr(DashWalk& c, long reserve)
{
	std::uint16_t* const minq = c.minq;
	std::uint16_t* const arr = c.arr;
	const int tstop = c.tstop;
	const int CD = rs::slot_cooldown();
	const int FCAP = c.W * c.H;
	std::vector<DashCell> fa, fb;
	std::unique_ptr<DashCell[]> dfa_a, dfa_b; // v731 DFA1 (C106 port): default-initialised frontier buffers
	dfa_a.reset(new DashCell[static_cast<std::size_t>(FCAP)]);
	dfa_b.reset(new DashCell[static_cast<std::size_t>(FCAP)]);
	DashCell* cur = dfa_a.get();
	DashCell* nxt = dfa_b.get();
	int nc = 0;
	bbforeach(M.my_spawn, [&](vec2 v)
	{
		const int i = (v.y + 2) * c.PW + v.x + 2;
		if (minq[i] != 0 && nc < FCAP)
			cur[nc++] = DashCell{ static_cast<std::uint16_t>(i), 0 };
	});
	const int o0 = c.off[0], o1 = c.off[1], o2 = c.off[2], o3 = c.off[3], o4 = c.off[4], o5 = c.off[5], o6 = c.off[6], o7 = c.off[7];
	const std::uint16_t* const hp = c.any_gap ? c.hopm.data() : nullptr;
	int hfr_k = 0; // v731 HMF bit 4 (HFR1a, C106 port): pops since the last fuel test, counted as sweep_fronts counts them
	std::size_t hfr_cap = 0; // v731 HMF bit 4: the label-list bound from the fuel left
	for (int t = 0; t <= tstop; ++t)
	{
		if (fuel() < reserve)
			return false;
		hfr_cap = hfr_label_cap(reserve);
		int nn = 0;
		// one label: false = the front overflowed
		auto label = [&](int p, int q, int dir) __attribute__((always_inline)) -> bool
		{
			if (arr[p] == DW_INF)
				arr[p] = static_cast<std::uint16_t>(t);
			if (q > minq[p])
				return true;
			minq[p] = static_cast<std::uint16_t>(q);
			const int qw = q > t ? q : t;
			if (nn + 8 > FCAP)
				return false;
			auto step = [&](int n, int k) __attribute__((always_inline))
			{
				if (qw < minq[n])
				{
					minq[n] = static_cast<std::uint16_t>(qw);
					nxt[nn++] = DashCell{ static_cast<std::uint16_t>(n), static_cast<std::uint16_t>(qw | (k + 1) << 8) };
				}
			};
			switch (dir)
			{
			case 1: step(p + o0, 0); step(p + o1, 1); step(p + o2, 2); step(p + o3, 3); step(p + o5, 5); break;
			case 2: step(p + o0, 0); step(p + o1, 1); step(p + o2, 2); break;
			case 3: step(p + o0, 0); step(p + o1, 1); step(p + o2, 2); step(p + o4, 4); step(p + o7, 7); break;
			case 4: step(p + o0, 0); step(p + o3, 3); step(p + o5, 5); break;
			case 5: step(p + o2, 2); step(p + o4, 4); step(p + o7, 7); break;
			case 6: step(p + o0, 0); step(p + o3, 3); step(p + o5, 5); step(p + o6, 6); step(p + o7, 7); break;
			case 7: step(p + o5, 5); step(p + o6, 6); step(p + o7, 7); break;
			case 8: step(p + o2, 2); step(p + o4, 4); step(p + o5, 5); step(p + o6, 6); step(p + o7, 7); break;
			default:
				step(p + o0, 0); step(p + o1, 1); step(p + o2, 2); step(p + o3, 3); step(p + o4, 4); step(p + o5, 5); step(p + o6, 6); step(p + o7, 7);
			}
			if (hp && hp[static_cast<std::size_t>(p)] != 0 && q + 1 <= tstop)
				for (int h = 0; h < 16; ++h)
					if ((hp[static_cast<std::size_t>(p)] >> h & 1) && q + CD < minq[p + c.hop[h]])
					{
						if (c.L.size() >= hfr_cap)
							return false; // v731 HMF bit 4: the label list is bounded by the fuel left
						c.push_dash(q + 1, p + c.hop[h], q + CD);
					}
			return true;
		};
		for (int ci = 0; ci < nc; ++ci)
		{
			if ((++hfr_k & 63) == 0 && fuel() < reserve)
				return false; // v731 HMF bit 4: a fuel test inside the front (one count per front-list pop, as sweep_fronts)
			if (!label(cur[ci].tile, cur[ci].q & 0xFF, cur[ci].q >> 8))
				return false;
		}
		for (;;)
		{
			if ((++hfr_k & 63) == 0 && fuel() < reserve)
				return false; // v731 HMF bit 4: one count per bucket pop and per final empty check, as sweep_fronts
			const int li = c.head[static_cast<std::size_t>(t)];
			if (li < 0)
				break;
			const DashLab b = c.L[static_cast<std::size_t>(li)];
			c.head[static_cast<std::size_t>(t)] = b.next;
			if (!label(b.tile, b.q, 0))
				return false;
		}
		std::swap(cur, nxt);
		nc = nn;
	}
	return true;
}

// Dash times of the targets from the searched arrival times, and the results kept in S.
static __attribute__((always_inline)) inline void publish_dash_times(DashWalk& c)
{
	float ad = c.cap, gd = 0.0f;
	for (const auto& a : M.altars)
		ad = std::min(ad, c.capped(c.near_dash(a.pos)));
	c.vs = 0.0f;
	c.gw = 0.0f;
	for (int gi = 0; gi < M.ng; ++gi)
	{
		const auto& g = M.groups[static_cast<std::size_t>(gi)];
		int d = DW_INF;
		for (const int ci : g.members)
			d = std::min(d, c.near_dash(M.camps[static_cast<std::size_t>(ci)].pos));
		if (d == DW_INF)
			continue; // no route for anyone (walled in, or behind the enemy spawn)
		const float v = static_cast<float>(g.gems) + 0.1f * static_cast<float>(g.gold);
		c.vs += v;
		c.gw += v * c.capped(c.gwalk[static_cast<std::size_t>(gi)]);
		gd += v * c.capped(d);
	}
	if (c.vs > 1e-6f)
	{
		c.gw /= c.vs;
		gd /= c.vs;
	}
	S.dtm_aw = c.aw;
	S.dtm_ad = ad;
	S.dtm_gw = c.gw;
	S.dtm_gd = gd;
	// Squared so that ordinary maps stay near 0 with no threshold.
	const float x = dash_slow_save(c.aw, ad, c.gw, gd);
	S.dtm_x = x * x;
	float hv = 0.0f, gt = 0.0f;
	for (const auto& g : M.groups)
	{
		gt += static_cast<float>(g.gems);
		if (g.str_max >= 60.0f)
			hv += static_cast<float>(g.gems);
	}
	S.dtm_h = gt > 1e-6f ? hv / gt : 0.0f;
	S.dtm_ok = true;
}

void dash_walk_times(long reserve)
{
	if (!M.done() || !M.has_home_cb || !M.has_dash)
	{
		// No hole anywhere (or no dash field): the dash time is the walk, x = 0.
		S.dtm_ok = M.done() && M.has_home_cb;
		return;
	}
	if (fuel() < reserve + 300L * M.w * M.h)
		return;
	DashWalk c;
	c.W = M.w;
	c.H = M.h;
	c.PW = c.W + 4;
	c.PH = c.H + 4;
	c.N = c.PW * c.PH;
	c.minq_v.assign(static_cast<std::size_t>(c.N), 0);
	c.arr_v.resize(static_cast<std::size_t>(c.N));
	c.mo_v.assign(static_cast<std::size_t>(c.N), 0);
	c.minq = c.minq_v.data();
	c.arr = c.arr_v.data();
	c.mo = c.mo_v.data();
	std::memset(c.arr, 0xFF, static_cast<std::size_t>(c.N) * sizeof(std::uint16_t));
	c.head.fill(-1);
	c.vcb = fview(M.f_home_cb);
	c.cap = static_cast<float>(DTM_TMAX);
	c.vda = fview(M.f_home_dash);
	measure_walk_times(c);
	if (dash_slow_save(c.aw, std::min(c.aw, c.alb), c.gw, std::min(c.gw, c.glb)) < DTM_XSKIP)
	{
		S.dtm_aw = S.dtm_ad = c.aw;
		S.dtm_gw = S.dtm_gd = c.gw;
		S.dtm_ok = true;
		return;
	}
	classify_tiles(c);
	build_hop_tables(c);
	if (c.any_gap) // v7xx HMF: the hop marking computes each tile once (bit 1) and tests the fuel (bit 2)
	{
		if (!hmf_mark_shortcut_hops(c, reserve))
			return;
	}
	else if (c.any_gap)
		mark_shortcut_hops(c);
	if (!((DTM_TMAX + 2 * rs::slot_cooldown() < 256) ? sweep_fronts_dpr(c, reserve) : sweep_fronts(c, reserve))) // v728 DPR
		return;
	publish_dash_times(c);
}

// Whether this map's term keeps dash kit `from` against walker `to` (DTM bit 4).
bool dash_term_keeps(int from, int to)
{
	if (!S.dtm_ok || !(DASHERS >> from & 1) || (DASHERS >> to & 1))
		return false;
	// Varg under bit 16: the term between them is dv (1 - h) + dn (1 - h).
	const float w = to == VA && (DTM_TAB[1] & DTM_BIT_VARG) ? 1.0f - S.dtm_h : 1.0f;
	return static_cast<float>(DTM_TAB[2]) * S.dtm_x * (1.0f + 0.01f * static_cast<float>(DTM_TAB[3])) * w >= static_cast<float>(DTM_TAB[6]);
}

void centrality_chain_features(long reserve)
{
	if (!M.done() || !M.has_home || !M.has_enemy)
		return;
	const long est = centrality_fuel_estimate();
	if (fuel() < reserve + est)
		return;
	const long f0 = fuel();
	constexpr int MAXC = 40;
	std::array<float, MAXC> cx{}, cy{}, cv{};
	int nc = 0;
	float all_v = 0.0f, farm_v = 0.0f, chain_v = 0.0f;
	for (const auto& g : M.groups)
	{
		if (g.d_home == UNREACH || g.members.empty())
			continue;
		const float cyc = static_cast<float>(std::max(10, g.respawn + 10)) + g.hp / 150.0f;
		const float v = (static_cast<float>(g.gems) + 0.1f * static_cast<float>(g.gold)) / cyc;
		all_v += v;
		if (g.n_mono == 0)
		{
			farm_v += v;
			if (g.n_att == 0 && g.n_clu >= 2)
				chain_v += v; // every member a cluster: she one-shots each of them in turn once upgraded
		}
		if (g.d_enemy == UNREACH)
			continue;
		const int dh = g.d_home, de = g.d_enemy;
		if (static_cast<float>(dh > de ? dh - de : de - dh) > std::max(3.0f, 0.2f * static_cast<float>(std::max(dh, de))))
			continue;
		++S.dr_ncon;
		int w = nc;
		if (nc < MAXC)
			++nc;
		else
		{
			// More contested groups than slots: replace the smallest when this one is worth more.
			w = 0;
			for (int j = 1; j < MAXC; ++j)
				if (cv[static_cast<std::size_t>(j)] < cv[static_cast<std::size_t>(w)])
					w = j;
			if (v <= cv[static_cast<std::size_t>(w)])
				continue;
		}
		float sx = 0.0f, sy = 0.0f;
		for (const int ci : g.members)
		{
			const vec2 p = M.camps[static_cast<std::size_t>(ci)].pos;
			sx += static_cast<float>(p.x);
			sy += static_cast<float>(p.y);
		}
		const float inv = 1.0f / static_cast<float>(static_cast<std::size_t>(g.nm));
		cx[static_cast<std::size_t>(w)] = sx * inv;
		cy[static_cast<std::size_t>(w)] = sy * inv;
		cv[static_cast<std::size_t>(w)] = v;
	}
	if (fuel() < reserve + 3000L + 40L * nc * nc)
		return; // the area search does not fit: terms 0
	float best = 0.0f;
	for (int a = 0; a < nc; ++a)
	{
		float s = 0.0f;
		for (int b = 0; b < nc; ++b)
			if (std::max(std::fabs(cx[static_cast<std::size_t>(a)] - cx[static_cast<std::size_t>(b)]),
					std::fabs(cy[static_cast<std::size_t>(a)] - cy[static_cast<std::size_t>(b)])) <= 6.0f)
				s += cv[static_cast<std::size_t>(b)];
		best = std::max(best, s);
	}
	S.dr_cen = all_v > 1e-6f ? clampf(best / all_v, 0.0f, 1.0f) : 0.0f;
	S.dr_ve = farm_v > 1e-6f ? clampf(chain_v / farm_v, 0.0f, 1.0f) : 0.0f;
	// Profit per round of trips from our spawn, a walker against a dasher who crosses thin holes (one dash per crossing,
	// DRAFT_DASH_COST rounds of cooldown on the trip) and reaches the sections only a dash reaches. Per group: value per cycle as above
	// / (round trip + 10).
	if (M.has_dash)
	{
		float pw = 0.0f, pd = 0.0f;
		for (const auto& g : M.groups)
		{
			if (g.members.empty() || g.n_mono > 0)
				continue;
			int dd = UNREACH;
			for (const int ci : g.members)
				dd = std::min<int>(dd, dfget(M.f_home_dash, M.camps[static_cast<std::size_t>(ci)].pos));
			const int dw = g.d_home;
			if (dw == UNREACH && dd == UNREACH)
				continue;
			const float cyc = static_cast<float>(std::max(10, g.respawn + 10)) + g.hp / 150.0f;
			const float v = (static_cast<float>(g.gems) + 0.1f * static_cast<float>(g.gold)) / cyc;
			if (dw != UNREACH)
				pw += v / (2.0f * static_cast<float>(dw) + 10.0f);
			const float dash_trip = dd != UNREACH && dd < dw ? 2.0f * static_cast<float>(dd) + DRAFT_DASH_COST : 1e9f;
			const float walk_trip = dw != UNREACH ? 2.0f * static_cast<float>(dw) : 1e9f;
			pd += v / (std::min(dash_trip, walk_trip) + 10.0f);
		}
		S.dr_dash = pw > 1e-6f ? clampf(pd / pw - 1.0f, 0.0f, 2.0f) : (pd > 1e-6f ? 2.0f : 0.0f);
	}
	S.dr_ok = true;
	S.dr_fuel = f0 - fuel();
}


void map_features()
{
	S.feat_tried = true;
	S.fr = fitfeat::compute(team_size(), 150000);
	if (!S.fr.ok)
		return;
	const auto& v = S.fr.v;
	S.no_walk_altar = v[fitfeat::F_NO_WALK_ALTAR] > 0.5f;
	S.min_dash = S.no_walk_altar ? 2 : 0;
	{
		// The dash-only share of what the map lets us score decides the dashers and the null picks.
		const int k = team_size();
		const float vw = S.fr.reach_vw, vd = S.fr.reach_vd;
		const int nd = S.fr.reach_nd;
		S.reach_s = vd > 1e-6f ? clampf(1.0f - vw / vd, 0.0f, 1.0f) : 0.0f;
		const int share = static_cast<int>(std::floor(static_cast<float>(k) * S.reach_s + 0.5f));
		S.min_dash = std::max(S.min_dash, std::min({ k, nd, share }));
		S.reach_null = vd > 1e-6f && vw < REACH_EPS * vd && !S.fr.meet_walk;
		S.max_dash = S.reach_null ? std::max(S.min_dash, std::min(k, nd)) : k;
	}
	// Plan flags (logged by the champions; decisions there do not read them). No gold flag on a map without gold.
	std::uint8_t fl = 0;
	if (S.no_walk_altar)
		fl |= PF_NO_ALTAR;
	if (v[fitfeat::F_MONO] >= 0.45f)
		fl |= PF_SIEGE;
	if (v[fitfeat::F_FIGHT] >= 0.5f)
		fl |= PF_FIGHT;
	if (v[fitfeat::F_DASH_ONLY] >= 0.3f)
		fl |= PF_ISLANDS;
	if (v[fitfeat::F_GOLD_PC] > 1.0f && v[fitfeat::F_GEM_PC] < 15.0f)
		fl |= PF_LONG_GAME;
	S.flags = fl;
	// The centrality and chain-share features first (cheap), so mapfeat's splash tier sees the fuel they used.
	centrality_chain_features(reserve_after_features() + 60000L);
	// The reach features; what must stay for the plan, the memory and a margin is the reserve.
	S.mf = mapfeat::compute(team_size(), S.fr.acc, reserve_after_features());
	strat::choose(S.mf); // before the last set_values, so the chosen strategy's pick_bias counts
	dash_walk_times(reserve_after_features() + 500000L); // after mapfeat: its splash tier must see the base's fuel
	set_values(S.mf.ok);
}

// Without features (fuel or failure): what the analysis alone shows, at no extra cost.
void cheap_rules()
{
	if (!M.done() || !M.has_home)
		return;
	bool walk = false;
	for (const auto& a : M.altars)
		walk |= a.d_home != UNREACH;
	S.no_walk_altar = !walk;
	S.min_dash = S.no_walk_altar ? 2 : 0;
	if (S.no_walk_altar)
		S.flags |= PF_NO_ALTAR;
}
} // namespace
} // namespace nova::drafting
