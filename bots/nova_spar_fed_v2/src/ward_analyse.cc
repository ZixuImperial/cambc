// ward_analyse.cc: Background analysis of where wards go.
#include "ward_internal.h"
namespace nova::ward {
// Stage A_BASIC: one spot per group, then the altar spots.
// Returns false when the stage must wait for a later turn.
static __attribute__((always_inline)) inline bool stage_basic_spots(long reserve)
{
	if (!M.ready())
		return false;
	if (cursor == 0)
		spots.clear();
	std::vector<vec2> pts;
	while (cursor < static_cast<std::size_t>(M.ng))
	{
		if (fuel() < reserve + 6000)
			return false;
		add_group_spot(M.groups[cursor], pts);
		++cursor;
	}
	if (fuel() < reserve + 3000L + 300L * static_cast<long>(static_cast<std::size_t>(M.na)))
		return false;
	add_altar_spots();
	n_basic_spots = spots.size();
	cursor = 0;
	stage = A_COV0;
	return true;
}

// Stage A_COV0: empty the coverage cache once before the field work.
// Returns false when the stage must wait for a later turn.
static __attribute__((always_inline)) inline bool stage_coverage_reset(long reserve)
{
	if (fuel() < reserve + cov_cost())
		return false;
	ward_coverage_cache_reset();
	stage = A_FIELD;
	return true;
}

// Stage A_FIELD: the spawn-to-spawn distance and the corridor width arrays.
// Returns false when the stage must wait for a later turn.
static __attribute__((always_inline)) inline bool stage_spawn_fields(long reserve)
{
	if (!M.has_home)
		return false;
	if (M.has_enemy)
		fe = &M.f_enemy;
	else
	{
		if (fuel() < reserve + 4L * G.w * G.h + 8000)
			return false;
		fe_own = std::make_unique<distance_field>();
		bitboard visited;
		fe_own->compute(M.walls | M.holes | M.altars_bb | M.my_spawn, M.enemy_spawn, visited);
		fe = fe_own.get();
	}
	if (fuel() < reserve + 10000)
		return false;
	int s2s = BIG;
	const FView vh0 = fview(M.f_home), ve0 = fview(*fe);
	bbforeach(M.enemy_spawn,
		[&](vec2 p)
		{
#pragma clang loop unroll(full)
			for (const vec2 d : DIRS)
			{
				const vec2 q = p + d;
				if (!inb(q) || bbget(M.enemy_spawn, q))
					continue;
				const int a = vh0(q), b = ve0(q);
				if (a != UNREACH && b != UNREACH)
					s2s = std::min(s2s, a + b);
			}
		});
	if (s2s >= BIG || s2s < 4)
	{
		fe_own.reset();
		fe = nullptr;
		cursor = 0;
		stage = A_BUSH_INIT;
		return true;
	}
	S = s2s;
	slack = std::max(6, S / 6);
	width.assign(static_cast<std::size_t>(S + slack + 1), 0);
	lvl_tiles.assign(static_cast<std::size_t>(S + slack + 1), {});
	corridor = bitboard{};
	cursor = 0;
	stage = A_SCAN;
	return true;
}

// Stage A_SCAN: corridor tiles and per-level widths, one chunk per fuel check.
// Returns false when the stage must wait for a later turn.
static __attribute__((always_inline)) inline bool stage_corridor_scan(long reserve)
{
	// Corridor: tiles on near-shortest routes between the spawns (f_home + f_enemy <= S + slack).
	const std::size_t nch = static_cast<std::size_t>(G.ch) * static_cast<std::size_t>(G.cw);
	const FView vh = fview(M.f_home), ve = fview(*fe);
	const int lim = S + slack;
	while (cursor < nch)
	{
		if (fuel() < reserve + 5000)
			return false;
		const int cy = static_cast<int>(cursor) / G.cw, cx = static_cast<int>(cursor) % G.cw;
		// F4: in the direct layout chunk tile i is cell (cy * cw + cx) * 64 + i of both fields (order unchanged).
		const std::uint16_t* pa = vh.p ? vh.p + (cy * G.cw + cx) * 64 : nullptr;
		const std::uint16_t* pb = ve.p ? ve.p + (cy * G.cw + cx) * 64 : nullptr;
		const bool direct2 = pa && pb;
		if (direct2 && lim < 65535)
		{
			// 8 tiles at a time: a + b (saturating u16) <= lim is exactly 'a, b reachable and a + b <= lim' (UNREACH = 65535 > lim); the
			// passing tiles in ascending i as below.
			const v128_t vl = wasm_u16x8_splat(static_cast<std::uint16_t>(lim));
			std::uint64_t cm = 0; // the chunk's corridor bits (bit i = tile i, as bbset), OR-ed in once below
			for (int i8 = 0; i8 < 64; i8 += 8)
			{
				std::uint32_t mk = wasm_i16x8_bitmask(wasm_u16x8_le(wasm_u16x8_add_sat(wasm_v128_load(pa + i8), wasm_v128_load(pb + i8)), vl));
				for (; mk != 0; mk &= mk - 1)
				{
					const int i = i8 + __builtin_ctz(mk);
					const vec2 q{ cx * 8 + (i & 7), cy * 8 + (i >> 3) };
					if (q.x >= G.w || q.y >= G.h)
						continue;
					const int b = pb[i];
					auto& wv = width[static_cast<std::size_t>(b)];
					if (wv < 4)
						lvl_tiles[static_cast<std::size_t>(b)][wv] = q;
					++wv;
					cm |= std::uint64_t{ 1 } << i;
				}
			}
			if (cm != 0)
				corridor.ptr()[cy * G.stride + cx] |= cm;
			++cursor;
			continue;
		}
		for (int i = 0; i < 64; ++i)
		{
			int a = 0, b = 0;
			if (direct2)
			{
				a = pa[i];
				if (a == UNREACH)
					continue;
				b = pb[i];
				if (b == UNREACH || a + b > lim)
					continue;
			}
			const vec2 q{ cx * 8 + (i & 7), cy * 8 + (i >> 3) };
			if (q.x >= G.w || q.y >= G.h)
				continue;
			if (!direct2)
			{
				a = vh(q);
				if (a == UNREACH)
					continue;
				b = ve(q);
				if (b == UNREACH || a + b > lim)
					continue;
			}
			auto& wv = width[static_cast<std::size_t>(b)];
			if (wv < 4)
				lvl_tiles[static_cast<std::size_t>(b)][wv] = q;
			++wv;
			bbset(corridor, q);
		}
		++cursor;
	}
	have_corridor = true;
	cursor = 0;
	stage = A_CHOKES;
	return true;
}

// Stage A_CHOKES: choke spots from the corridor widths.
// Returns false when the stage must wait for a later turn.
static __attribute__((always_inline)) inline bool stage_chokes(long reserve)
{
	if (fuel() < reserve + 15000L + 60L * static_cast<long>(width.size()))
		return false;
	build_chokes();
	width.clear();
	width.shrink_to_fit();
	lvl_tiles.clear();
	lvl_tiles.shrink_to_fit();
	fe_own.reset();
	fe = nullptr;
	cursor = 0;
	stage = A_BUSH_INIT;
	return true;
}

// Stage A_BUSH_INIT: collect the bush tiles one 8x8 chunk per fuel check.
// Returns false when the stage must wait for a later turn.
static __attribute__((always_inline)) inline bool stage_bush_tiles(long reserve)
{
	if (!bbany(M.bushes))
	{
		stage = A_FINAL;
		return true;
	}
	// Collect the bush tiles one 8x8 chunk per fuel check.
	if (cursor == 0)
	{
		if (fuel() < reserve + 8000)
			return false;
		bush_tiles.clear();
		bush_lbl.reset();
	}
	const std::size_t nch = static_cast<std::size_t>(G.ch) * static_cast<std::size_t>(G.cw);
	while (cursor < nch)
	{
		if (fuel() < reserve + 6000)
			return false;
		const int cy = static_cast<int>(cursor) / G.cw, cx = static_cast<int>(cursor) % G.cw;
		if (NOVA_GDIRECT)
		{
			// F4: bit i of the chunk's word is tile i of the loop below: set bits only, low to high (same order).
			std::uint64_t word = M.bushes.ptr()[cy * G.stride + cx];
			while (word)
			{
				const int i = __builtin_ctzll(word);
				word &= word - 1;
				const vec2 q{ cx * 8 + (i & 7), cy * 8 + (i >> 3) };
				if (q.x < G.w && q.y < G.h)
					bush_tiles.push_back(q);
			}
		}
		else
		for (int i = 0; i < 64; ++i)
		{
			const vec2 q{ cx * 8 + (i & 7), cy * 8 + (i >> 3) };
			if (q.x < G.w && q.y < G.h && bbget(M.bushes, q))
				bush_tiles.push_back(q);
		}
		++cursor;
	}
	cursor = 0;
	cl.clear();
	cl_k = 0;
	cl_open = false;
	cl_id = 0;
	stage = A_BUSH;
	return true;
}

// Stage A_BUSH: cardinally connected bush clusters and their scoring.
// Returns false when the stage must wait for a later turn.
static __attribute__((always_inline)) inline bool stage_bush_clusters(long reserve)
{
	// Cardinally connected bush clusters (a ward inside sees its whole cluster), grown 16 tiles per check.
	while (true)
	{
		if (fuel() < reserve + 8000)
			return false;
		if (bs.active)
		{
			if (!bush_score_step(reserve, n_basic_spots))
				return false;
			continue;
		}
		if (cl_open)
		{
			for (int k = 0; k < 16 && cl_k < cl.size(); ++k, ++cl_k)
				for (int d = 0; d < 8; d += 2)
				{
					const vec2 q = cl[cl_k] + DIRS[static_cast<std::size_t>(d)];
					if (!inb(q) || !bbget(M.bushes, q) || bush_lbl.get(q) != 0)
						continue;
					bush_lbl.at(q) = static_cast<std::int16_t>(cl_id);
					cl.push_back(q);
				}
			if (cl_k < cl.size())
				continue;
			if (fuel() < reserve + 4000L + 40L * static_cast<long>(cl.size()))
				return false;
			bush_score_begin(cl_id, cl);
			cl_open = false;
			continue;
		}
		// Next unlabelled bush tile seeds a cluster (64 tiles per fuel check).
		const std::size_t stop = std::min(bush_tiles.size(), cursor + 64);
		while (cursor < stop && bush_lbl.get(bush_tiles[cursor]) != 0)
			++cursor;
		if (cursor >= bush_tiles.size())
			break;
		if (cursor == stop)
			continue;
		const vec2 p = bush_tiles[cursor++];
		cl_id = std::min(cl_id + 1, 30000);
		bush_lbl.at(p) = static_cast<std::int16_t>(cl_id);
		cl.clear();
		cl.push_back(p);
		cl_k = 0;
		cl_open = true;
	}
	stage = A_FINAL;
	return true;
}

// Stage A_FINAL: publish the bush spots and rebuild the coverage cache.
// Returns false when the stage must wait for a later turn.
static __attribute__((always_inline)) inline bool stage_finish(long reserve)
{
	if (fuel() < reserve + cov_cost() + 2000L * MAX_BUSH)
		return false;
	for (const auto& s : bush_spots)
	{
		spots.push_back(s);
		NLOG("ward bush at %d,%d keys %d w %.1f\n", s.c.x, s.c.y, s.nk, s.w0);
	}
	bush_spots.clear();
	bush_spots.shrink_to_fit();
	corridor = bitboard{};
	have_corridor = false;
	ward_coverage_cache_reset();
	stage = A_DONE;
	NLOG("ward analysis done: %zu spots (S %d)\n", spots.size(), S);
	return true;
}

__attribute__((always_inline)) void analyse(long reserve)
{
	if (stage == A_DONE)
	{
		// A long game can fill the coverage cache: rebuild it here, where the fuel is spare.
		if (cov_pool.size() > POOL_MAX && fuel() > reserve + cov_cost())
			ward_coverage_cache_reset();
		return;
	}
	try
	{
		read_consts();
		while (stage != A_DONE)
		{
			switch (stage)
			{
			case A_BASIC:
				if (!stage_basic_spots(reserve))
					return;
				break;
			case A_COV0:
				if (!stage_coverage_reset(reserve))
					return;
				break;
			case A_FIELD:
				if (!stage_spawn_fields(reserve))
					return;
				break;
			case A_SCAN:
				if (!stage_corridor_scan(reserve))
					return;
				break;
			case A_CHOKES:
				if (!stage_chokes(reserve))
					return;
				break;
			case A_BUSH_INIT:
				if (!stage_bush_tiles(reserve))
					return;
				break;
			case A_BUSH:
				if (!stage_bush_clusters(reserve))
					return;
				break;
			case A_FINAL:
				if (!stage_finish(reserve))
					return;
				break;
			default:
				stage = A_DONE;
				break;
			}
		}
	}
	catch (const std::exception& e)
	{
		NLOG("ward analyse error stage %d: %s\n", stage, e.what());
		(void)e;
		cursor = 0;
		cl_open = false;
		bs.active = false;
		stage = stage + 1 <= A_DONE ? stage + 1 : A_DONE;
		if (stage == A_DONE && !cache_ready())
			stage = A_FINAL; // the spot list changed: the cache must be rebuilt before act() uses it
	}
}

namespace {
void placed_at(vec2 p);
} // namespace
} // namespace nova::ward
