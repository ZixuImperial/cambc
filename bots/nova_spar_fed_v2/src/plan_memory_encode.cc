// plan_memory_encode.cc: Draft memory: tunables and encoding.
#include "plan_internal.h"
namespace nova {

// ======== Tunables: the limits of the stored block and the map class model ========
namespace plan_tune
{
inline constexpr std::size_t XT_MAX_GROUPS = 200; // exact travel: no table past this many groups
inline constexpr std::size_t XT_MAX_ALTARS = 40;
inline constexpr int FAR_WALK = 200;              // a spawn-to-spawn walk that does not exist counts as this
// MCL2's size score F: weight, mean, deviation per feature, and its two cuts.
inline constexpr float F_APB_W = -4.824909771937116f, F_APB_MU = 5.687944507499192f, F_APB_SD = 0.6776878862162714f;
inline constexpr float F_GPB_W = -6.7748711415292915f, F_GPB_MU = 4.021668293003347f, F_GPB_SD = 1.0191938409618209f;
inline constexpr float F_TOP_W = 5.786212993682333f, F_TOP_MU = 0.24218090452261282f, F_TOP_SD = 0.1889890563523651f;
inline constexpr float F_S2S_W = -3.913063098897691f, F_S2S_MU = 3.43762704806695f, F_S2S_SD = 1.052169180759191f;
inline constexpr float F_LOW = -6.137435434906846f, F_HIGH = 4.783029247367503f;
inline constexpr float GG_LOW = 1.0240699568842198f, GG_HIGH = 1.4870628315421393f; // log gold per gem cuts
inline constexpr float GPB_LOW = 42.4f, GPB_HIGH = 94.5f;                           // gems per body-round cuts
inline constexpr int S2S_NEAR = 22; // Spawns this close set bit 64.
inline constexpr int AC_LINK_R = 3;               // camp tiles this near link groups into a region
inline constexpr float AC_GOLD_SHARE = 0.35f;     // a gold's worth in gems in a region's value rate
inline constexpr float AC_RHO_LOW = 0.4f, AC_RHO_HIGH = 0.6f; // a contested region lies this far between the spawns
}

// ======== Draft memory: encode ========
Plan P;

namespace {
std::uint8_t encode_distance(std::uint16_t d, int scale)
{
	if (d == UNREACH)
		return 255;
	return static_cast<std::uint8_t>(std::min(254, (d + scale - 1) / scale));
}
std::uint16_t decode_distance(std::uint8_t v, int scale)
{
	if (v == 255)
		return UNREACH;
	return static_cast<std::uint16_t>(v * scale);
}
// Exact travel keeps a table only for this many groups (and altars).
NOVA_INLINE bool xt_group_count_ok(std::size_t n) { return n >= 2 && n <= plan_tune::XT_MAX_GROUPS; }
NOVA_INLINE bool xt_size_ok(std::size_t n, std::size_t na) { return xt_group_count_ok(n) && na <= plan_tune::XT_MAX_ALTARS; }
} // namespace
std::vector<std::uint8_t> encode_draft_memory(const std::vector<cambc::champion_draft>& picks, std::uint8_t flags)
{
	std::vector<std::uint8_t> buf(16, 0);
	buf.reserve(16 + 3 * (std::min<std::size_t>(static_cast<std::size_t>(M.ng), 200) + std::min<std::size_t>(static_cast<std::size_t>(M.na), 40)));
	buf[0] = MEM_MAGIC;
	buf[1] = MEM_VERSION;
	buf[2] = static_cast<std::uint8_t>(picks.size());
	buf[3] = flags;
	buf[15] = strat::draft_choice(); // This game's strategy (strategy.h).
	for (std::size_t i = 0; i < 5; ++i)
		buf[4 + i] = i < picks.size() ? static_cast<std::uint8_t>(picks[i]) : 0xFF;
	int maxd = 1;
	for (const auto& g : M.groups)
	{
		if (g.d_home != UNREACH)
			maxd = std::max<int>(maxd, g.d_home);
		if (g.d_enemy != UNREACH)
			maxd = std::max<int>(maxd, g.d_enemy);
	}
	for (const auto& a : M.altars)
	{
		if (a.d_home != UNREACH)
			maxd = std::max<int>(maxd, a.d_home);
		if (a.d_enemy != UNREACH)
			maxd = std::max<int>(maxd, a.d_enemy);
	}
	const int scale = std::max(1, (maxd + 253) / 254);
	const std::size_t ng = std::min<std::size_t>(static_cast<std::size_t>(M.ng), 200);
	const std::size_t na = std::min<std::size_t>(static_cast<std::size_t>(M.na), 40);
	buf[9] = static_cast<std::uint8_t>(scale);
	buf[10] = static_cast<std::uint8_t>(ng);
	buf[11] = static_cast<std::uint8_t>(na);
	buf[12] = static_cast<std::uint8_t>(static_cast<std::size_t>(M.ng) > 255 ? 255 : static_cast<std::size_t>(M.ng));
	buf[13] = static_cast<std::uint8_t>(static_cast<std::size_t>(M.na) > 255 ? 255 : static_cast<std::size_t>(M.na));
	// Byte 14 = spawn-to-spawn walk (walking distance from our spawn to the tiles around theirs, as the draft's F.s2s), encoded
	// ceil(d/scale) + 1; 0 = unknown.
	if (M.has_home)
	{
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
		if (s2s != UNREACH)
			buf[14] = static_cast<std::uint8_t>(std::min(254, (static_cast<int>(s2s) + scale - 1) / scale) + 1);
	}
	for (std::size_t i = 0; i < ng; ++i)
	{
		const auto& g = M.groups[i];
		buf.push_back(encode_distance(g.d_home, scale));
		buf.push_back(encode_distance(g.d_enemy, scale));
		buf.push_back(g.access);
	}
	for (std::size_t i = 0; i < na; ++i)
	{
		const auto& a = M.altars[i];
		buf.push_back(encode_distance(a.d_home, scale));
		buf.push_back(encode_distance(a.d_enemy, scale));
		buf.push_back(static_cast<std::uint8_t>((a.gated ? 1 : 0) | (a.access << 1)));
	}
	if (buf.size() > 1024)
		buf.resize(1024);
	return buf;
}

// Exact travel (plan.h).
namespace {
// draft side
std::vector<std::uint8_t> xc_full; // The block with the full triangle (mode 0), whatever its size; pack stores it compactly when it fits.
std::vector<std::uint16_t> xt_full; // n x n walks (row a = from group a)
std::vector<std::uint16_t> xt_sp;   // spawn -> group (camps blocked)
struct XtRoute
{
	int g = -1, len = 0;
	vec2 s{ -1, -1 };
	std::uint8_t dir[XT_MAXRL] = {};
};
std::vector<XtRoute> xt_rt;         // draft: routes (nearest groups first)
std::vector<int> xt_rsel;           // draft: route slot of each group (-1 none)
std::size_t xt_cur = 0;
bool xt_started = false, xt_done = false, xt_put = false;
std::size_t fxdr_xt_n = 0; // Walk groups, their approach offsets into a field buffer.
std::vector<int> fxdr_xt_wl, fxdr_xt_ab, fxdr_xt_ao;
} // namespace
namespace fxdr
{
// draft_launch_scan's static slots are the top HS3_TOP walkable groups by gems (its own ranking, repeated here); travel_build_step's field of such a
// group (walls M.block_camps minus its tiles, roots its tiles) is the field draft_launch_scan computes for it.
std::array<std::unique_ptr<distance_field>, HS3_TOP> fc;
std::array<int, HS3_TOP> top{};
int nt = -1;
int launch_slot_of_group(int gi)
{
	if (nt < 0)
	{
		nt = 0;
		const int ng = M.ng;
		for (int k = 0; k < HS3_TOP; ++k)
		{
			int best = -1, bg = 0;
			for (int g = 0; g < ng; ++g)
			{
				const auto& gr = M.groups[static_cast<std::size_t>(g)];
				bool used = false;
				for (int j = 0; j < nt; ++j)
					used |= top[static_cast<std::size_t>(j)] == g;
				if (!used && gr.access == ACC_WALK && gr.gems > bg)
				{
					bg = gr.gems;
					best = g;
				}
			}
			if (best < 0)
				break;
			top[static_cast<std::size_t>(nt++)] = best;
		}
	}
	for (int k = 0; k < nt; ++k)
		if (top[static_cast<std::size_t>(k)] == gi)
			return k;
	return -1;
}
void launch_field_keep(int gi, distance_field&& f)
{
	const int s = launch_slot_of_group(gi);
	if (s >= 0)
		fc[static_cast<std::size_t>(s)] = std::make_unique<distance_field>(std::move(f));
}
const distance_field* launch_field(int gi)
{
	const int s = launch_slot_of_group(gi);
	return s >= 0 ? fc[static_cast<std::size_t>(s)].get() : nullptr;
}
void launch_fields_free()
{
	for (auto& p : fc)
		p.reset();
}
} // namespace fxdr
namespace
{
// champion side
std::vector<std::uint8_t> xt_raw;   // the checked block (header + S + R + G)
int xt_n = 0, xt_mode = 0, xt_scale = 1, xt_nr = 0;
std::size_t xt_ro = 0, xt_go = 0;   // offsets of R and G inside xt_raw
bool xt_ok = false, xt_dn = false;
bool xt_cx = false; // A compact block is waiting to be expanded (xt_ok is set; xt_raw is empty until then).
std::vector<std::uint16_t> xt_d; // Dense n x n (UNREACH unknown).
std::vector<std::uint16_t> xt_s;    // dense spawn -> group
std::vector<std::uint8_t> xt_der;   // 1 = a k-list gap filled through stored neighbours (an upper bound, not a stored walk)
struct XtPath
{
	int g = -1;
	std::size_t off = 0; // offset of the route record in xt_raw
	std::vector<vec2> t; // expanded tiles (lazy), t[0] = the spawn tile
	bool built = false;
};
std::vector<XtPath> xt_paths;
int xt_cg = -1, xt_cj = -1; // route-estimate cache: group, best index

std::size_t xt_rbytes(int len) { return 4 + (static_cast<std::size_t>(len) * 3 + 7) / 8; }
} // namespace
namespace econ {
// The draft's copy of hole_shortcut_background's launch scan (same slots, fields, loop order and 512 cap) for the static slots: the top HS3_TOP
// walkable groups by gems (hole_shortcut_top_ready's ranking) and, with an altar our spawn walks to, the altar slot (M.f_altar). Per slot: the
// roots (launches within HS3_BAND of the best landing walk vmin) as tile indices; no launch: no roots.
void draft_launch_scan(std::vector<Dm3Rec>& out, long reserve)
{
	out.clear();
	if (!M.has_thin || !NOVA_GDIRECT || M.groups.empty() || static_cast<std::size_t>(M.ng) > 250)
		return;
	const int ng = M.ng;
	std::array<int, HS3_TOP> top{};
	int nt = 0;
	for (int k = 0; k < HS3_TOP; ++k)
	{
		int best = -1, bg = 0;
		for (int gi = 0; gi < ng; ++gi)
		{
			const auto& g = M.groups[static_cast<std::size_t>(gi)];
			bool used = false;
			for (int j = 0; j < nt; ++j)
				used |= top[static_cast<std::size_t>(j)] == gi;
			if (!used && g.access == ACC_WALK && g.gems > bg)
			{
				bg = g.gems;
				best = gi;
			}
		}
		if (best < 0)
			break;
		top[static_cast<std::size_t>(nt++)] = best;
	}
	std::vector<int> slots(top.begin(), top.begin() + nt);
	if (M.any_altar)
		slots.push_back(ng);
	static const vec2 PU[12] = { { 1, 0 }, { 0, 1 }, { 1, 1 }, { 1, -1 }, { 1, 0 }, { 1, 0 }, { -1, 0 }, { -1, 0 }, { 0, 1 }, { 0, 1 },
		{ 0, -1 }, { 0, -1 } };
	static const vec2 PW[12] = { { 1, 0 }, { 0, 1 }, { 1, 1 }, { 1, -1 }, { 1, 1 }, { 1, -1 }, { -1, 1 }, { -1, -1 }, { 1, 1 }, { -1, 1 },
		{ 1, -1 }, { -1, -1 } };
	// the dash pairs (a, b) over each thin hole in hole_shortcut_background's scan order, both ends inside the board and outside M.block_camps (every push
	// in the scan needs both): built once, then each slot only reads its field at the two ends
	const std::uint64_t* hw = M.thin_holes.ptr();
	const int nw = G.ch * G.cw;
	std::vector<std::pair<vec2, vec2>> pr;
	std::vector<int> fxdr_po;
	std::size_t nh = 0;
	for (int pos = 0; pos < nw; ++pos)
		nh += static_cast<std::size_t>(__builtin_popcountll(hw[(pos / G.cw) * G.stride + pos % G.cw]));
	pr.reserve(12 * nh);
	const BView vbc = bview(M.block_camps);
	for (int pos = 0; pos < nw; ++pos)
	{
		const int cy = pos / G.cw, cx = pos % G.cw;
		std::uint64_t bits = hw[cy * G.stride + cx];
		while (bits)
		{
			const int bit = __builtin_ctzll(bits);
			bits &= bits - 1;
			const vec2 hl{ cx * 8 + (bit & 7), cy * 8 + (bit >> 3) };
			if (hl.x >= G.w || hl.y >= G.h)
				continue;
			for (int q = 0; q < 12; ++q)
			{
				const vec2 a{ hl.x - PU[q].x, hl.y - PU[q].y }, b{ hl.x + PW[q].x, hl.y + PW[q].y };
				if (!inb(a) || !inb(b) || vbc(a) || vbc(b))
					continue;
				pr.push_back({ a, b });
			}
		}
	}
	fxdr_po.resize(2 * pr.size());
	for (std::size_t k = 0; k < pr.size(); ++k)
	{
		const vec2 a = pr[k].first, b = pr[k].second;
		fxdr_po[2 * k] = ((a.y >> 3) * G.cw + (a.x >> 3)) * 64 + ((a.y & 7) << 3) + (a.x & 7);
		fxdr_po[2 * k + 1] = ((b.y >> 3) * G.cw + (b.x >> 3)) * 64 + ((b.y & 7) << 3) + (b.x & 7);
	}
	std::vector<Hs3Cand> cs;
	for (const int gi : slots)
	{
		const long prior = 3L * M.w * M.h + 3000 + static_cast<long>(distance_field::raw_buffer_size()) +
			2L * static_cast<long>(bitboard::raw_buffer_size()) + 2000L;
		if (fuel() < reserve + 2 * prior + 80L * static_cast<long>(pr.size()) + 50000)
			break;
		std::unique_ptr<distance_field> own;
		const distance_field* F = &M.f_altar;
		const distance_field* fxdr_f = gi < ng && true ? fxdr::launch_field(gi) : nullptr; // travel_build_step's field
		if (fxdr_f != nullptr)
			F = fxdr_f;
		else if (gi < ng)
		{
			bitboard tiles;
			for (int ci : M.groups[static_cast<std::size_t>(gi)].members)
				bbset(tiles, M.camps[static_cast<std::size_t>(ci)].pos);
			own = std::make_unique<distance_field>();
			bitboard visited;
			own->compute(M.block_camps & ~tiles, tiles, visited);
			F = own.get();
		}
		const FView fv = fview(*F);
		cs.clear();
		if (fv.p != nullptr && fv.cw == G.cw)
		{
			const std::uint16_t* fp = fv.p;
			const int* po = fxdr_po.data();
			for (std::size_t k = 0, e = pr.size(); k < e; ++k)
			{
				const int fa = fp[po[2 * k]], fb = fp[po[2 * k + 1]];
				if (fa == UNREACH || fb == UNREACH)
					continue;
				if (fb + 1 + HS3_SAVE <= fa && cs.size() < 512)
					cs.push_back({ pr[k].first, fb + 1 });
				else if (fa + 1 + HS3_SAVE <= fb && cs.size() < 512)
					cs.push_back({ pr[k].second, fa + 1 });
			}
		}
		else
			for (const auto& ab : pr)
			{
				const int fa = fv(ab.first), fb = fv(ab.second);
				if (fa == UNREACH || fb == UNREACH)
					continue;
				if (fb + 1 + HS3_SAVE <= fa && cs.size() < 512)
					cs.push_back({ ab.first, fb + 1 });
				else if (fa + 1 + HS3_SAVE <= fb && cs.size() < 512)
					cs.push_back({ ab.second, fa + 1 });
			}
		Dm3Rec r;
		r.gi = gi;
		if (!cs.empty())
		{
			int vmin = UNREACH;
			for (const auto& c : cs)
				vmin = std::min(vmin, c.v);
			bitboard roots{};
			for (const auto& c : cs)
				if (c.v <= vmin + HS3_BAND)
					bbset(roots, c.a);
			r.vmin = vmin;
			bbforeach(roots, [&](vec2 p) { r.roots.push_back(static_cast<std::uint16_t>(p.y * G.w + p.x)); });
			if (r.roots.empty())
				continue; // cannot happen (the best launch is a root); no record keeps the scan
		}
		out.push_back(std::move(r));
	}
	fxdr::launch_fields_free();
}
} // namespace econ
} // namespace nova
