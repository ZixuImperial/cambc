// plan_exact_travel.cc: Exact travel tables built during the draft.
#include "plan_internal.h"
namespace nova {
// The first call: empty tables, and which groups get an opening route (nearest first).
NOVA_INLINE void travel_start(std::size_t n)
{
	xt_full.assign(n * n, UNREACH);
	xt_sp.assign(n, UNREACH);
	xt_rsel.assign(n, -1);
	std::vector<std::pair<int, int>> near;
	for (std::size_t b = 0; b < n; ++b)
	{
		const auto& g = M.groups[b];
		if (g.access != ACC_WALK)
			continue;
		xt_sp[b] = M.group_dist_blocked(M.f_home_cb, g);
		if (xt_sp[b] != UNREACH && g.gems + g.gold > 0)
			near.emplace_back(static_cast<int>(xt_sp[b]), static_cast<int>(b));
	}
	std::sort(near.begin(), near.end());
	for (std::size_t k = 0; k < near.size() && k < static_cast<std::size_t>(XT_MAXR); ++k)
		xt_rsel[static_cast<std::size_t>(near[k].second)] = static_cast<int>(k);
	xt_rt.assign(std::min<std::size_t>(near.size(), XT_MAXR), XtRoute{});
	xt_cur = 0;
}
// The walks from every group to b through precomputed offsets (the same minimum as travel_rows_plain).
NOVA_INLINE void travel_rows_fast(std::size_t n, std::size_t b, const FView& vf)
{
	if (fxdr_xt_n != n)
	{
		fxdr_xt_n = n;
		fxdr_xt_wl.clear();
		fxdr_xt_ab.assign(n + 1, 0);
		fxdr_xt_ao.clear();
		for (std::size_t a = 0; a < n; ++a)
		{
			fxdr_xt_ab[a] = static_cast<int>(fxdr_xt_ao.size());
			if (M.groups[a].access != ACC_WALK)
				continue;
			fxdr_xt_wl.push_back(static_cast<int>(a));
			for (const vec2 q : M.groups[a].approach)
				fxdr_xt_ao.push_back(((q.y >> 3) * vf.cw + (q.x >> 3)) * 64 + ((q.y & 7) << 3) + (q.x & 7));
		}
		fxdr_xt_ab[n] = static_cast<int>(fxdr_xt_ao.size());
	}
	const std::uint16_t* fp = vf.p;
	const int* ao = fxdr_xt_ao.data();
	for (const int ai : fxdr_xt_wl)
	{
		const std::size_t a = static_cast<std::size_t>(ai);
		if (a == b)
		{
			xt_full[a * n + b] = 0;
			continue;
		}
		std::uint16_t best = UNREACH;
		for (int k = fxdr_xt_ab[a], e = fxdr_xt_ab[a + 1]; k < e; ++k)
		{
			const std::uint16_t v = fp[ao[k]];
			if (v < best)
				best = v;
		}
		xt_full[a * n + b] = best == UNREACH ? UNREACH : static_cast<std::uint16_t>(best + 1);
	}
}
NOVA_INLINE void travel_rows_plain(std::size_t n, std::size_t b, const FView& vf)
{
	for (std::size_t a = 0; a < n; ++a)
	{
		if (M.groups[a].access != ACC_WALK)
			continue;
		if (a == b)
		{
			xt_full[a * n + b] = 0;
			continue;
		}
		std::uint16_t best = UNREACH;
		for (const vec2 q : M.groups[a].approach)
		{
			const std::uint16_t v = vf(q);
			if (v < best)
				best = v;
		}
		xt_full[a * n + b] = best == UNREACH ? UNREACH : static_cast<std::uint16_t>(best + 1);
	}
}
// The route's steps downhill from r.s (ties: the straighter line to the anchor), at most RL.
NOVA_INLINE void travel_walk_route(XtRoute& r, const FView& vf, vec2 anchor, std::uint16_t sv, int RL)
{
	vec2 cur = r.s;
	std::uint16_t cv = sv;
	while (r.len < RL && cv > 0)
	{
		int bk = -1, bl = BIG;
		std::uint16_t bv = cv;
		for (int k = 0; k < 8; ++k)
		{
			const vec2 q = cur + DIRS[static_cast<std::size_t>(k)];
			if (!inb(q))
				continue;
			const std::uint16_t v = vf(q);
			if (v == UNREACH || v >= cv)
				continue;
			const int lin = iabs(q.x - anchor.x) + iabs(q.y - anchor.y);
			if (v < bv || (v == bv && lin < bl))
			{
				bv = v;
				bl = lin;
				bk = k;
			}
		}
		if (bk < 0)
			break;
		r.dir[r.len++] = static_cast<std::uint8_t>(bk);
		cur = cur + DIRS[static_cast<std::size_t>(bk)];
		cv = bv;
	}
}
// The opening route of group b: from the spawn tile nearest the group, downhill.
NOVA_INLINE void travel_trace_route(XtRoute& r, std::size_t b, const FView& vf, int RL)
{
	r.g = static_cast<int>(b);
	std::uint16_t sv = UNREACH;
	bbforeach(M.my_spawn, [&](vec2 p) { const std::uint16_t v = vf(p); if (v < sv) { sv = v; r.s = p; } });
	if (sv != UNREACH)
		travel_walk_route(r, vf, M.groups[b].anchor, sv, RL);
	else
		r.g = -1;
}

bool travel_build_step(long reserve)
{
	if (xt_done)
		return true;
	if (!M.done())
		return false;
	const std::size_t n = static_cast<std::size_t>(M.ng), na = static_cast<std::size_t>(M.na);
	if (!xt_started)
	{
		xt_started = true;
		if (!xt_size_ok(n, na) || 16 + 3 * (n + na) + 16 + n > XT_END || !M.has_home_cb)
		{
			xt_done = true;
			return true;
		}
		travel_start(n);
	}
	long app = 0;
	for (const auto& g : M.groups)
		app += static_cast<long>(g.approach.size());
	const long cost = 4L * static_cast<long>(G.w) * static_cast<long>(G.h) + 12000L + 60L * app + 4000L;
	const int RL = std::max(1, std::min(XT_MAXRL, static_cast<int>(XT_TAB[3])));
	while (xt_cur < n)
	{
		if (fuel() < cost + reserve)
			return false;
		const std::size_t b = xt_cur++;
		const auto& gb = M.groups[b];
		if (gb.access != ACC_WALK)
			continue;
		bitboard tiles;
		for (int ci : gb.members)
			bbset(tiles, M.camps[static_cast<std::size_t>(ci)].pos);
		distance_field f;
		bitboard visited;
		f.compute(M.block_camps & ~tiles, tiles, visited);
		const FView vf = fview(f);
		if (vf.p != nullptr)
			travel_rows_fast(n, b, vf);
		else
			travel_rows_plain(n, b, vf);
		const int slot = xt_rsel[b];
		if (slot >= 0 && slot < static_cast<int>(xt_rt.size()))
			travel_trace_route(xt_rt[static_cast<std::size_t>(slot)], b, vf, RL);
		if (M.has_thin && M.ng <= 250)
			fxdr::launch_field_keep(static_cast<int>(b), std::move(f)); // draft_launch_scan's field of this group, if a top slot.
	}
	xt_done = true;
	return true;
}

void travel_write(std::vector<std::uint8_t>& mem)
{
	if (!xt_done || xt_put)
		return;
	xt_put = true;
	const std::size_t n = static_cast<std::size_t>(M.ng), na = static_cast<std::size_t>(M.na);
	if (!xt_size_ok(n, na) || xt_full.size() != n * n || xt_sp.size() != n)
		return;
	const std::size_t E = 16 + 3 * (n + na);
	if (E + 8 + n > XT_END)
		return;
	auto sym = [&](std::size_t a, std::size_t b) { return std::min(xt_full[a * n + b], xt_full[b * n + a]); };
	int maxd = 1;
	for (std::size_t a = 0; a < n; ++a)
	{
		if (xt_sp[a] != UNREACH)
			maxd = std::max<int>(maxd, xt_sp[a]);
		for (std::size_t b = a + 1; b < n; ++b)
			if (sym(a, b) != UNREACH)
				maxd = std::max<int>(maxd, sym(a, b));
	}
	const int scale = std::max(1, (maxd + 253) / 254);
	auto enc = [scale](std::uint16_t d) { return encode_distance(d, scale); };
	const std::size_t rem = XT_END - E - 8 - n; // after the header (6), S and the checksum (2)
	const std::size_t tri = n * (n - 1) / 2;
	std::vector<std::size_t> rb(1, 0); // bytes of the first i routes
	for (const auto& r : xt_rt)
		if (r.g >= 0 && r.len > 0)
			rb.push_back(rb.back() + xt_rbytes(r.len));
	std::size_t nr = 0;
	while (nr + 1 < rb.size() && rb[nr + 1] + tri <= rem)
		++nr;
	int mode = 0;
	if (rb[nr] + tri > rem || (nr < 2 && nr + 1 < rb.size())) // the triangle leaves < 2 routes: routes up to a third, k-lists the rest
	{
		while (nr + 1 < rb.size() && rb[nr + 1] <= rem / 3)
			++nr;
		if (rb[nr] + tri > rem)
		{
			const std::size_t k = std::min<std::size_t>(8, (rem - rb[nr]) / (2 * n));
			mode = k < 1 ? 255 : static_cast<int>(k);
		}
	}
	std::vector<std::uint8_t> blk;
	blk.reserve(XT_END - E);
	blk.push_back(XT_MAGIC);
	blk.push_back(XT_VERSION);
	blk.push_back(static_cast<std::uint8_t>(n));
	blk.push_back(static_cast<std::uint8_t>(std::min(255, scale)));
	blk.push_back(static_cast<std::uint8_t>(mode));
	blk.push_back(static_cast<std::uint8_t>(nr));
	for (std::size_t a = 0; a < n; ++a)
		blk.push_back(enc(xt_sp[a]));
	blk[5] = 0; // no route is stored: nr above only sizes the rest
	if (mode == 0)
	{
		for (std::size_t a = 0; a < n; ++a)
			for (std::size_t b = a + 1; b < n; ++b)
				blk.push_back(enc(sym(a, b)));
	}
	else if (mode != 255)
	{
		const std::size_t k = static_cast<std::size_t>(mode);
		std::vector<std::pair<std::uint16_t, std::uint8_t>> row;
		for (std::size_t a = 0; a < n; ++a)
		{
			row.clear();
			for (std::size_t b = 0; b < n; ++b)
				if (b != a && sym(a, b) != UNREACH)
					row.emplace_back(sym(a, b), static_cast<std::uint8_t>(b));
			std::sort(row.begin(), row.end());
			for (std::size_t j = 0; j < k; ++j)
			{
				blk.push_back(j < row.size() ? row[j].second : 255);
				blk.push_back(j < row.size() ? enc(row[j].first) : 255);
			}
		}
	}
	int s1 = 0, s2 = 0; // Fletcher-16 (sums reduced once: the same value as reducing per byte; < 2^31 for <= 736 bytes)
	for (const std::uint8_t c : blk)
	{
		s1 += c;
		s2 += s1;
	}
	s1 %= 255;
	s2 %= 255;
	blk.push_back(static_cast<std::uint8_t>(s1));
	blk.push_back(static_cast<std::uint8_t>(s2));
	if (E + blk.size() > XT_END)
		return;
	if (mem.size() < E + blk.size())
		mem.resize(E + blk.size(), 0);
	std::copy(blk.begin(), blk.end(), mem.begin() + static_cast<std::ptrdiff_t>(E));
	xt_full.clear();
	xt_full.shrink_to_fit();
}

namespace {
// Champions: check the block at E and keep it (no tables yet: travel_table_build makes them when fuel allows).
bool xt_tried = false; // A decode was attempted (once).
// The checks and setup of a block whose first byte is b[0] (absolute offset E in the old image; len bytes from there, checksum
// included).
bool travel_take_block(const std::uint8_t* b, std::size_t len, std::size_t n, std::size_t E, std::size_t lim = XT_END)
{
	if (b[0] != XT_MAGIC || b[1] != XT_VERSION || b[2] != n)
		return false;
	const int mode = b[4], nr = b[5];
	if (mode != 0 && mode != 255 && mode > 8)
		return false;
	std::size_t o = 6 + n;
	for (int i = 0; i < nr; ++i)
	{
		if (o + 4 > len || E + o + 4 > lim)
			return false;
		const int rl = b[o + 3];
		if (rl <= 0 || rl > XT_MAXRL || b[o] >= n)
			return false;
		o += xt_rbytes(rl);
	}
	const std::size_t go = o;
	const std::size_t glen = mode == 0 ? n * (n - 1) / 2 : (mode == 255 ? 0 : n * static_cast<std::size_t>(mode) * 2);
	const std::size_t end = go + glen;
	if (end + 2 > len || E + end + 2 > lim)
		return false;
	xt_raw.assign(b, b + end); // one bulk copy; the checksum then reads plain bytes
	int s1 = 0, s2 = 0;
	const std::uint8_t* q = xt_raw.data();
	for (std::size_t i = 0, rl = xt_raw.size(); i < rl; ++i)
	{
		s1 += q[i];
		s2 += s1;
	}
	s1 %= 255;
	s2 %= 255;
	if (s1 != b[end] || s2 != b[end + 1])
	{
		xt_raw.clear();
		xt_raw.shrink_to_fit();
		return false;
	}
	xt_n = static_cast<int>(n);
	xt_scale = std::max<int>(1, b[3]);
	xt_mode = mode;
	xt_nr = nr;
	xt_ro = 6 + n;
	xt_go = go;
	xt_ok = true;
	return true;
}
void travel_decode(const std::uint8_t* m, std::size_t size, std::size_t n, std::size_t na)
{
	if (xt_tried)
		return;
	xt_tried = true;
	const std::size_t E = 16 + 3 * (n + na);
	if (!xt_group_count_ok(n) || E + 8 + n > XT_END)
		return;
	if (dmem::compact_block_present()) // Checked and expanded later, once, where the tables are first needed (dmem::compact_head_expand / compact_block_build).
	{
		xt_n = static_cast<int>(n);
		xt_cx = true;
		xt_ok = true;
		xt_mode = dmem::compact_block_mode(); // for compact_block_build's fuel bar before the header is read (the header sets it again)
		return;
	}
	if (size < E + 8 + n)
		return;
	travel_take_block(m + E, size - E, n, E);
}
} // namespace

bool xt_ready() { return xt_ok; }

// ---------------------------------------------------------------- Draft memory bit stream (plan.h dmem, docs/modules/draft.md)
} // namespace nova
