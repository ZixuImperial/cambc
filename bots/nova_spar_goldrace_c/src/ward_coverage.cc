// ward_coverage.cc: Coverage, watches and known ally wards.
#include "ward_internal.h"
namespace nova::ward {
namespace {
// Spots a ward at p would see, with their coverage. Cached per tile; a new tile costs one vision query plus a scan of the spot list
// (~2-3k), and spends one unit of misses_left.
CovList coverage(vec2 p)
{
	CovRef r = cov_ref.get(p);
	if (r.off < 0)
	{
		if (misses_left <= 0 || cov_pool.size() > POOL_MAX || fuel() < ACT_FLOOR + 8000)
			return { nullptr, -1 };
		--misses_left;
		cambc::ward::visible_tiles_from_into(p, scratch);
		r.off = static_cast<std::int32_t>(cov_pool.size());
		int n = 0;
		const std::size_t ns = spots.size(); // F4: read once (the push_back below hides them from the optimiser)
		const int* const sxp = sx.data();
		const int* const syp = sy.data();
		const int* const srp = srad.data();
		const int qx = p.x, qy = p.y;
		// The box test four spots at a time (wasm SIMD), then the in-box spots in ascending order.
		std::size_t i = 0;
		{
			const v128_t vqx = wasm_i32x4_splat(qx), vqy = wasm_i32x4_splat(qy);
			for (; i + 4 <= ns && n < 255; i += 4)
			{
				const v128_t r4 = wasm_v128_load(srp + i);
				const v128_t ok = wasm_v128_and(wasm_i32x4_le(wasm_i32x4_abs(wasm_i32x4_sub(vqx, wasm_v128_load(sxp + i))), r4),
					wasm_i32x4_le(wasm_i32x4_abs(wasm_i32x4_sub(vqy, wasm_v128_load(syp + i))), r4));
				std::uint32_t mk = wasm_i32x4_bitmask(ok);
				while (mk != 0 && n < 255)
				{
					const std::size_t j = i + static_cast<std::size_t>(__builtin_ctz(mk));
					mk &= mk - 1;
					const float c = cover(spots[j], scratch);
					if (c <= 0)
						continue;
					cov_pool.push_back({ static_cast<std::int16_t>(j), static_cast<std::uint8_t>(c * 255.0f + 0.5f) });
					++n;
				}
			}
		}
		for (; i < ns && n < 255; ++i)
		{
			if (iabs(qx - sxp[i]) > srp[i] || iabs(qy - syp[i]) > srp[i])
				continue;
			const float c = cover(spots[i], scratch);
			if (c <= 0)
				continue;
			cov_pool.push_back({ static_cast<std::int16_t>(i), static_cast<std::uint8_t>(c * 255.0f + 0.5f) });
			++n;
		}
		r.len = static_cast<std::uint8_t>(n);
		cov_ref.at(p) = r;
	}
	return { cov_pool.data() + r.off, r.len };
}

void set_watch(vec2 p, const bitboard& V)
{
	++watch_ver; // Watch changes only here.
	watch.assign(static_cast<std::size_t>(M.ng), 0);
	for (std::size_t gi = 0; gi < static_cast<std::size_t>(M.ng); ++gi)
	{
		const auto& g = M.groups[gi];
		if (cheb(g.anchor, p) > vision_r + 8)
			continue;
		for (int ci : g.members)
			if (bbget(V, M.camps[static_cast<std::size_t>(ci)].pos))
			{
				watch[gi] = 1;
				break;
			}
	}
}
// Best coverage of each spot by the ally wards we know of. Stays dirty while some ward's list is not computed yet.
void rebuild_acov()
{
	acov.assign(spots.size(), 0.0f);
	acov_dirty = false; // An ally's ward lights nothing for me.
	return;
}
// Remember allied wards in our vision; forget those whose tile we now see empty.
void scan_allied_wards()
{
	if (now() - ally_scan < 5)
		return;
	ally_scan = now();
	// F4: the raw records in a kept buffer, ally ones first (cambc::vision::wards(team::ally) builds two vectors per call).
	static std::vector<cambc::detail::ward_info> ws_buf;
	std::size_t ws_n = 0;
	try
	{
		std::uint32_t c = 0;
		cambc::detail::check(cambc::detail::sdk_wards(nullptr, 0, &c));
		if (ws_buf.size() < c)
			ws_buf.resize(c);
		if (c > 0)
		{
			cambc::detail::check(cambc::detail::sdk_wards(ws_buf.data(), c, &c));
			if (c > ws_buf.size())
				c = static_cast<std::uint32_t>(ws_buf.size()); // FX: a fuel cut between the two reads (a new round) can raise the count past the buffer
		}
		for (std::uint32_t i = 0; i < c; ++i)
			if (ws_buf[i].team == static_cast<std::uint32_t>(cambc::detail::cached_my_team))
				ws_buf[ws_n++] = ws_buf[i];
	}
	catch (...)
	{
		FXR_PASS();
		return;
	}
	for (std::size_t i = 0; i < ally.size();)
	{
		bool present = false;
		for (std::size_t k = 0; k < ws_n; ++k)
			if (ws_buf[k].x == ally[i].pos.x && ws_buf[k].y == ally[i].pos.y)
				present = true;
		if ((!present && bbget(W.vis, ally[i].pos)) || now() - ally[i].seen > 300)
		{
			ally.erase(ally.begin() + static_cast<std::ptrdiff_t>(i));
			acov_dirty = true;
		}
		else
			++i;
	}
	for (std::size_t k = 0; k < ws_n; ++k)
	{
		const auto& w = ws_buf[k];
		const std::uint32_t owner = w.owner;
		if (owner == W.me.h)
			continue;
		AllyWard* e = nullptr;
		for (auto& a : ally)
			if (a.owner == owner)
				e = &a;
		if (!e)
		{
			ally.push_back({});
			e = &ally.back();
			e->owner = owner;
		}
		e->seen = now();
		const vec2 wp{ w.x, w.y };
		if (e->pos != wp)
		{
			e->pos = wp;
			acov_dirty = true;
		}
	}
}

// BB14 WRB / WPN (callers read the flag): a tile a ward placement refused is held by a mate's unseen ward (permanent, GR:363): kept with
// the ally wards (owner unknown) until scan_allied_wards sees it empty or 300 rounds pass.
void note_ally_ward_tile(vec2 p)
{
	for (const auto& a : ally)
		if (a.pos == p)
			return;
	ally.push_back({ 0u, p, now() });
	acov_dirty = true;
}
bool ally_ward_at(vec2 p)
{
	for (const auto& a : ally)
		if (a.pos == p)
			return true;
	return false;
}

bool bad_tile(vec2 p)
{
	for (const auto& b : bad)
		if (b.p == p && b.until > now())
			return true;
	return false;
}

void log_ward_coverage_summary()
{
}

} // namespace

vec2 position() { return my_ward; }

const std::vector<std::uint8_t>& watch_flags() { return watch; }
std::uint32_t watch_version() { return watch_ver; }

bool watches_group(int gi)
{
	return gi >= 0 && static_cast<std::size_t>(gi) < watch.size() && watch[static_cast<std::size_t>(gi)] != 0;
}
} // namespace nova::ward
