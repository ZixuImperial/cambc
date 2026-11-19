// econ_comms_fields.cc: Shared-memory initialisation and occupancy fields.
#include "econ_internal.h"
namespace nova::econ {
// Observe's member counts and health sum for group gi from a member-tile mask (the group's nonzero words only). False
// (the caller runs the member loop) when the layout is not direct, the group is small, a member tile is off the board, shared or not
// the camp's own index, or a health value is not a small integer.
struct OfMask
{
	std::vector<int> k;			   // word index
	std::vector<std::uint64_t> m;  // member bits in that word
	std::vector<int> beg;		   // the word's members: entries beg[j] .. beg[j + 1] - 1
	std::vector<std::uint64_t> eb; // entry: member bit
	std::vector<int> eci, ehp;	   // entry: camp index, static health
	std::int64_t tot = 0;		   // static health of all members
	signed char ok = 0;			   // 0 unbuilt, 1 usable, -1 not
};
std::vector<std::uint8_t> f2_xd, f2_yd;
std::size_t f2_ng = static_cast<std::size_t>(-1);
int f2_w = -1, f2_h = -1;
std::vector<std::int16_t> f2_ax, f2_ay; // the anchors' x and y, padded to 8 with a far value (filled with the masks' reset)
namespace {
struct CmpState
{
	bool init = false;
	int k = 0, ew = 0;
	comms::Spare f;
	std::array<std::uint32_t, 2> last{ 0xFFFFFFFFu, 0xFFFFFFFFu }; // the raw entry I last decoded (or wrote)
	std::array<int, 2> first{ -1000, -1000 };                        // the round I first saw that raw entry
	std::vector<int> post_lo;                                        // team level: the R each group's last post said
	bool due = false; // a new entry moved my target's respawn past my arrival
	bool t2 = false;
	int t2_ng = 0, t2_rc = 0, t2_rr = 0; // code ranges: CAPTURE starts at 1, RESPAWNING at t2_rc, FIGHT at t2_rr
	int t2_c6 = 0, t2_rcrew = 0, t2_rnews = 0; // CREW at t2_rcrew, the news types 0-3 at t2_rnews
	int t2_fs = 4; // FIGHT codes a cell (4: rally commit hold retreat; 3: rally commit stop)
	std::vector<std::int8_t> tb_kind;        // team belief: 0 none, 1 alive, 2 cleared, 3 timed
	std::vector<int> own_r;                  // the respawn round I read from the engine myself (capture countdown or cooldown), 0 none
	std::vector<std::uint8_t> own_set;       // on own_list
	std::vector<int> own_list; // the groups with a live own_r
	std::vector<int> tb_asof;
	int pend_e = -1, pend_g = -1;            // my last post, checked at my next turn
	std::uint32_t pend_v = 0;
} CS;
// 4-bit respawn buckets (lower edge for 'go', upper edge for 'don't bother before').
constexpr int T2_LO[16] = { 0, 1, 2, 3, 4, 5, 6, 8, 11, 15, 21, 29, 41, 57, 81, 113 };
constexpr int T2_HI[16] = { 0, 1, 2, 3, 4, 5, 7, 10, 14, 20, 28, 40, 56, 80, 112, 100000 };
// T2_EDGE[w]: w is some bucket's low edge (a post on this round is exact), so the check costs one load.
constexpr std::array<std::uint8_t, 113> T2_EDGE = [] { std::array<std::uint8_t, 113> e{}; for (int b = 0; b < 15; ++b) e[static_cast<std::size_t>(T2_LO[b])] = 1; return e; }();
struct TmfLp // my last intel news post on the channel, checked at my next turn start
{
	int e = -1, t = -1000, sub = -1, type = 0, round = 0;
	std::uint32_t v = 0;
	bool resent = false;
} tmf_lp;
bool tmf_resending = false;
} // namespace
// an old-layout event on the channel. No free entry: dropped (its writer re-posts by its own rules).
int t2_lp_res = -1;
bool bh64_lp_drop = false; // the last team_mem_post_legacy_event found no entry
namespace {
// Writer: one entry per turn for a group I saw die (own sight), whatever I target now. camps_near_me_mask's masks path (M.ready(), my tile
// on the map) is a function of my tile, M.ng (and words, from it) and the map size (fixed for the game): the axis masks are reset
// only when ng or the map size change, each column/row is filled once, and anchors are fixed once M.ready() (stages only advance).
// With ow_on its watch words are a function of ward's watch flags, whose every write bumps ward::watch_version() (++watch_ver then
// watch.assign, the only write, so the pointer and size move with it). Nothing else writes f2_cand. obx_f2_xy is valid only after a
// call that took that path; any other path clears it.
int obx_f2_xy = -2147483647 - 1, obx_f2_ng = -1;
std::uint32_t obx_f2_ver = 0;
} // namespace
void init()
{
	mem.assign(static_cast<std::size_t>(M.ng), GroupMem{}); mem_n = M.ng; fxp_exp_lo = -2147483647 - 1; // full pass next
	T = Task{};
	S = Sense{};
	build_ready = false;
	float all = 0, open = 0;
	for (const auto& g : M.groups)
	{
		all += static_cast<float>(g.gems);
		if (!siege_group(g))
			open += static_cast<float>(g.gems);
	}
	open_gem_share = all > 0 ? open / all : 1.0f;
	crew_init();
	gem_need_init();
}
bool of_build(OfMask& o, const std::vector<int>& mem, int n)
{
	constexpr int HP_MAX = 1 << 20;
	constexpr std::int64_t SUM_MAX = 1 << 24;
	struct E
	{
		int k;
		std::uint64_t b;
		int ci, hp;
	};
	std::vector<E> es;
	es.reserve(mem.size());
	for (int ci : mem)
	{
		if (ci < 0 || static_cast<std::size_t>(ci) >= static_cast<std::size_t>(M.nc))
			return false;
		const auto& c = M.camps[static_cast<std::size_t>(ci)];
		const vec2 p = c.pos;
		const int k = inb(p) ? (p.y >> 3) * G.stride + (p.x >> 3) : -1;
		const float h = c.hp;
		if (k < 0 || k >= n || M.camp_index(p) != ci || !(h >= 0.0f && h <= static_cast<float>(HP_MAX)) ||
			h != static_cast<float>(static_cast<int>(h)))
			return false;
		es.push_back({ k, std::uint64_t{ 1 } << (((p.y & 7) << 3) | (p.x & 7)), ci, static_cast<int>(h) });
		o.tot += static_cast<std::int64_t>(h);
	}
	if (o.tot >= SUM_MAX)
		return false;
	std::stable_sort(es.begin(), es.end(), [](const E& a, const E& b) { return a.k < b.k; });
	// one allocation per vector instead of a reallocation at every doubling (same contents).
	o.k.reserve(es.size());
	o.m.reserve(es.size());
	o.beg.reserve(es.size() + 1);
	o.eb.reserve(es.size());
	o.eci.reserve(es.size());
	o.ehp.reserve(es.size());
	for (std::size_t i = 0; i < es.size(); ++i)
	{
		if (o.k.empty() || o.k.back() != es[i].k)
		{
			o.k.push_back(es[i].k);
			o.m.push_back(0);
			o.beg.push_back(static_cast<int>(i));
		}
		if (o.m.back() & es[i].b)
			return false; // two members on one tile
		o.m.back() |= es[i].b;
		o.eb.push_back(es[i].b);
		o.eci.push_back(es[i].ci);
		o.ehp.push_back(es[i].hp);
	}
	o.beg.push_back(static_cast<int>(es.size()));
	return true;
}
bool of_scan(std::size_t gi, int& vis_n, int& alive_n, float& hp)
{
	constexpr std::int64_t HP_MAX = 1 << 20, SUM_MAX = 1 << 24;
	if (!NOVA_GDIRECT || gi >= static_cast<std::size_t>(M.ng))
		return false;
	const auto& mem = M.groups[gi].members;
	if (mem.size() < 6)
		return false;
	const int n = G.ch * G.stride;
	if (n <= 0)
		return false;
	static std::vector<OfMask> om;
	if (om.size() != static_cast<std::size_t>(M.ng))
	{
		// no resize this turn when the fuel left can't cover it and the mask build after it.
		if (fuel() < SF_OF_FLOOR + SF_OF_PER * static_cast<long>(mem.size()) +
						 static_cast<long>(OFMASK_RESIZE_TAB[2]) * static_cast<long>(static_cast<std::size_t>(M.ng) + om.size()))
			return false;
		om.assign(static_cast<std::size_t>(M.ng), OfMask{});
	}
	OfMask& o = om[gi];
	if (o.ok == 0)
	{
		// no mask build on a short turn (the setup turn); the member loop gives the same counts.
		if (fuel() < SF_OF_FLOOR + SF_OF_PER * static_cast<long>(mem.size()))
			return false;
		o.ok = of_build(o, mem, n) ? 1 : -1;
	}
	if (o.ok < 0 || o.beg.size() != o.k.size() + 1)
		return false;
	const std::uint64_t* v = W.vis.ptr();
	const std::uint64_t* oc = W.occ_camps.ptr();
	int seen = 0, al = 0;
	std::int64_t vis_st = 0, cur = 0;
	for (std::size_t j = 0; j < o.k.size(); ++j)
	{
		const int k = o.k[j];
		if (k < 0 || k >= n)
			return false;
		const std::uint64_t vm = v[k] & o.m[j];
		if (!vm)
			continue;
		const std::uint64_t va = vm & oc[k];
		seen += __builtin_popcountll(vm);
		al += __builtin_popcountll(va);
		for (int e = o.beg[j]; e < o.beg[j + 1]; ++e)
		{
			const std::uint64_t b = o.eb[static_cast<std::size_t>(e)];
			if (!(vm & b))
				continue;
			const int hs = o.ehp[static_cast<std::size_t>(e)];
			vis_st += hs;
			if (va & b)
			{
				const VisCamp* vc = visible_camp(o.eci[static_cast<std::size_t>(e)]);
				if (!vc)
					cur += hs;
				else
				{
					const float h = vc->hp;
					if (!(h >= 0.0f && h <= static_cast<float>(HP_MAX)) || h != static_cast<float>(static_cast<int>(h)))
						return false;
					cur += static_cast<std::int64_t>(h);
				}
			}
		}
	}
	// Every partial sum of the member loop is at most the static total plus the visible current health.
	if (o.tot + cur >= SUM_MAX)
		return false;
	vis_n = seen;
	alive_n = al;
	hp = static_cast<float>(o.tot - vis_st + cur);
	return true;
}
const std::uint64_t* axis_mask_row(std::vector<std::uint64_t>& tab, std::vector<std::uint8_t>& done, int v, bool is_y, std::size_t words)
{
	std::uint64_t* r = tab.data() + static_cast<std::size_t>(v) * words;
	if (!done[static_cast<std::size_t>(v)])
	{
		done[static_cast<std::size_t>(v)] = 1;
		const std::vector<std::int16_t>& ac = is_y ? f2_ay : f2_ax;
		if (ac.size() >= ((f2_ng + 7) & ~static_cast<std::size_t>(7)) && v >= -20000 && v <= 20000)
		{
			// the same test (|anchor - v| <= 12) 8 groups at a time; group gi0 + k is bit k of the 8 (gi0 % 8 == 0)
			const v128_t lo = wasm_i16x8_splat(static_cast<std::int16_t>(v - 12)), hi = wasm_i16x8_splat(static_cast<std::int16_t>(v + 12));
			for (std::size_t gi0 = 0; gi0 < f2_ng; gi0 += 8)
			{
				const v128_t a = wasm_v128_load(ac.data() + gi0);
				const std::uint32_t m = wasm_i16x8_bitmask(wasm_v128_and(wasm_i16x8_ge(a, lo), wasm_i16x8_le(a, hi)));
				if (m)
					r[gi0 >> 6] |= static_cast<std::uint64_t>(m) << (gi0 & 63);
			}
			return r;
		}
		const auto* gp = M.groups.data();
		for (std::size_t gi = 0; gi < f2_ng; ++gi)
		{
			const int d = (is_y ? gp[gi].anchor.y : gp[gi].anchor.x) - v;
			if (d <= 12 && d >= -12)
				r[gi >> 6] |= std::uint64_t(1) << (gi & 63);
		}
	}
	return r;
}
void camps_near_me_mask(vec2 me, const std::vector<std::uint8_t>& ow_f, std::size_t words, bool ow_on)
{
	const std::size_t ng = static_cast<std::size_t>(M.ng);
	if (f2_cand.size() != words)
		f2_cand.resize(words);
	std::uint64_t* cand = f2_cand.data();
	if (M.ready() && me.x >= 0 && me.y >= 0 && me.x < G.w && me.y < G.h)
	{
		if (f2_ng != ng || f2_w != G.w || f2_h != G.h)
		{
			f2_ng = ng;
			f2_w = G.w;
			f2_h = G.h;
			f2_xm.assign(static_cast<std::size_t>(G.w) * words, 0);
			f2_ym.assign(static_cast<std::size_t>(G.h) * words, 0);
			f2_xd.assign(static_cast<std::size_t>(G.w), 0);
			f2_yd.assign(static_cast<std::size_t>(G.h), 0);
			// the anchors as i16 lanes (out-of-range anchors keep the scalar test)
			const std::size_t np = (ng + 7) & ~static_cast<std::size_t>(7);
			f2_ax.assign(np, static_cast<std::int16_t>(-32000));
			f2_ay.assign(np, static_cast<std::int16_t>(-32000));
			bool f2_fit = true;
			for (std::size_t gi = 0; gi < ng; ++gi)
			{
				const vec2 a = M.groups[gi].anchor;
				f2_fit &= a.x >= -20000 && a.x <= 20000 && a.y >= -20000 && a.y <= 20000;
				f2_ax[gi] = static_cast<std::int16_t>(a.x);
				f2_ay[gi] = static_cast<std::int16_t>(a.y);
			}
			if (!f2_fit)
			{
				f2_ax.clear();
				f2_ay.clear();
			}
		}
		const std::uint64_t* xm = axis_mask_row(f2_xm, f2_xd, me.x, false, words);
		const std::uint64_t* ym = axis_mask_row(f2_ym, f2_yd, me.y, true, words);
		for (std::size_t w = 0; w < words; ++w)
			cand[w] = xm[w] & ym[w];
	}
	else
	{
		for (std::size_t w = 0; w < words; ++w)
			cand[w] = 0;
		for (std::size_t gi = 0; gi < ng; ++gi)
			if (cheb(M.groups[gi].anchor, me) <= 12)
				cand[gi >> 6] |= std::uint64_t(1) << (gi & 63);
	}
	if (!ow_on) // watch off: the ward's per-group test
	{
		for (std::size_t gi = 0; gi < ng; ++gi)
			if (ward::watches_group(static_cast<int>(gi)))
				cand[gi >> 6] |= std::uint64_t(1) << (gi & 63);
		return;
	}
	const std::size_t wn = std::min(ow_f.size(), ng);
	const std::uint8_t* wf = ow_f.data();
	{
		// the watch flags as bit words, rebuilt only when the ward's flags changed (same bits OR-ed in).
		static std::vector<std::uint64_t> fz_wb;
		static std::uint32_t fz_wver = 0;
		static std::size_t fz_wn = static_cast<std::size_t>(-1), fz_words = 0;
		static const std::uint8_t* fz_wp = nullptr;
		const std::uint32_t ver = ward::watch_version();
		if (ver != fz_wver || wn != fz_wn || words != fz_words || wf != fz_wp)
		{
			fz_wver = ver;
			fz_wn = wn;
			fz_words = words;
			fz_wp = wf;
			fz_wb.assign(words, 0);
			for (std::size_t j = 0; j < wn; ++j)
				if (wf[j])
					fz_wb[j >> 6] |= std::uint64_t(1) << (j & 63);
		}
		for (std::size_t w = 0; w < words; ++w)
			cand[w] |= fz_wb[w];
		return;
	}
	for (std::size_t i = 0; i < wn; i += 8)
	{
		std::uint64_t b = 1;
		if (i + 8 <= wn)
			__builtin_memcpy(&b, wf + i, 8);
		if (b)
			for (std::size_t j = i; j < i + 8 && j < wn; ++j)
				if (wf[j])
					cand[j >> 6] |= std::uint64_t(1) << (j & 63);
	}
}
} // namespace nova::econ
