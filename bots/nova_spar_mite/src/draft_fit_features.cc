// draft_fit_features.cc: Map features for the draft, computed at runtime from MapInfo (mapinfo.h) plus a forward dash closure that uses dashnav's dash
#include "draft_fit_features.h"

#include "mapinfo.h"

namespace nova::fitfeat {

const char* const NAMES[NF] = { "k", "gem_pc", "gold_pc", "clu_gem", "clu_gold", "heavy", "mono", "dash_only", "tp_only",
	"no_walk_altar", "dash_altar", "recall", "s2s", "central", "density", "n_altar", "safe_altar", "near_altar", "gem_total_pc",
	"fight", "gated" };

namespace {

bool member_in(const GroupI& g, const bitboard& b)
{
	for (const int ci : g.members)
	{
		const vec2 c = M.camps[static_cast<std::size_t>(ci)].pos;
		if (bbget(b, c))
			return true;
		for (const vec2 d : DIRS)
		{
			const vec2 q = c + d;
			if (inb(q) && bbget(b, q))
				return true;
		}
	}
	return false;
}

} // namespace
Result compute(int team_size, long reserve)
{
	Result R;
	const long f0 = fuel();
	if (!M.done() || !M.has_home || f0 < reserve + 8000)
		return R;
	auto& v = R.v;
	const int k = std::max(1, team_size);
	const float champs = 2.0f * static_cast<float>(k);
	v[F_K] = static_cast<float>(k);

	// Access: walk from f_home (camps passable); dash closure only when something is not walkable.
	const std::size_t ng = static_cast<std::size_t>(M.ng);
	std::vector<std::uint8_t> acc(ng, 0); // 0 walk, 1 dash, 2 crystal only, 3 none (dv3; dv2 had 2 = neither)
	bool need_closure = false;
	for (std::size_t i = 0; i < ng; ++i)
		if (M.groups[i].d_home == UNREACH)
		{
			acc[i] = 2;
			need_closure = true;
		}
	int walk_altars = 0, open_altars = 0;
	float near = 1e9f;
	bool safe = false;
	for (const auto& a : M.altars)
	{
		if (a.d_home == UNREACH)
			continue;
		if (!a.gated)
			++open_altars;
		++walk_altars;
		near = std::min(near, static_cast<float>(a.d_home));
		if (a.d_home <= 30 && a.d_enemy != UNREACH && a.d_enemy >= 20 && static_cast<int>(a.d_enemy) - static_cast<int>(a.d_home) >= 10)
			safe = true;
		if (a.d_enemy == UNREACH && a.d_home <= 30)
			safe = true;
	}
	const bool no_walk_altar = walk_altars == 0;
	if (no_walk_altar)
		need_closure = true;
	bool dash_altar = false;
	if (need_closure)
	{
		const long field = 3L * M.w * M.h + 4000;
		if (fuel() > reserve + 2 * field + 20000)
		{
			const bitboard stand = ~M.block; // camps can be killed: their tiles count as standable (as f_home)
			const bitboard mid_ok = ~(M.walls | M.camp_tiles); // dashnav's middle-tile rule
			auto nb8 = [](const bitboard& b)
			{
				const bitboard x = b | b.shift_right(1) | b.shift_right(-1);
				return x | x.shift_up(1) | x.shift_up(-1);
			};
			distance_field f;
			bitboard A{};
			f.compute(M.block, M.my_spawn, A);
			for (int it = 0; it < 8; ++it)
			{
				if (fuel() < reserve + field + 30000)
					break;
				const bitboard L = nb8(nb8(A) & mid_ok) & stand & ~A;
				if (!bbany(L))
					break;
				bitboard vis{};
				f.compute(M.block, L, vis);
				A |= vis;
				++R.dash_iters;
			}
			for (std::size_t i = 0; i < ng; ++i)
				if (acc[i] == 2 && member_in(M.groups[i], A))
					acc[i] = 1;
			if (no_walk_altar && bbany(M.altar_adj_all & A))
				dash_altar = true;
			// Crystal reach: a standable tile within Chebyshev 3 of the walk/dash set. Used only for the game-length feature, which counts
			// every group we can reach somehow.
			bitboard T = nb8(nb8(nb8(A)));
			T = T & stand & ~A;
			for (std::size_t i = 0; i < ng; ++i)
				if (acc[i] == 2)
				{
					bool tp = false;
					for (const int ci : M.groups[i].members)
						tp |= bbget(T, M.camps[static_cast<std::size_t>(ci)].pos);
					acc[i] = tp ? 2 : 3;
				}
			R.closure = true;
		}
	}
	for (std::size_t i = 0; i < ng; ++i)
		if (acc[i] == 2 && !R.closure)
			acc[i] = 3; // closure skipped (fuel): unwalkable groups count as unreachable

	float gem_r = 0, gold_r = 0, clu_gem = 0, clu_gold = 0, heavy = 0, central = 0;
	float tot_gems = 0, mono_g = 0, dash_g = 0, tp_g = 0, rc_w = 0, rc_d = 0;
	const bool alt_w = walk_altars > 0, alt_d = alt_w || dash_altar; // alt_w: a walkable altar exists. alt_d: an altar this class can reach by walking or dashing.
	for (std::size_t i = 0; i < ng; ++i)
	{
		const GroupI& g = M.groups[i];
		const float gems = static_cast<float>(g.gems), gold = static_cast<float>(g.gold);
		tot_gems += gems;
		if (g.n_mono > 0)
			mono_g += gems;
		if (acc[i] == 1)
			dash_g += gems;
		else if (acc[i] >= 2)
			tp_g += gems;
		if (acc[i] >= 2 || g.n_mono > 0)
			continue;
		const float cyc = static_cast<float>(std::max(10, g.respawn + 10)) + g.hp / 150.0f;
		const float gr = gems / cyc, dr = gold / cyc;
		{
			// Value per class (walk groups for walkers, walk and dash groups for dashers).
			const float vw = acc[i] == 0 ? (alt_w ? gr : 0.0f) + REACH_GOLD * dr : 0.0f;
			const float vd = (alt_d ? gr : 0.0f) + REACH_GOLD * dr;
			R.reach_vw += vw;
			R.reach_vd += vd;
			if (vd > vw + 1e-6f)
				++R.reach_nd;
		}
		gem_r += gr;
		gold_r += dr;
		if (acc[i] == 0 && g.contest >= 0.4f && g.contest <= 0.6f)
			central += gr;
		continue;
	}
	v[F_GEM_PC] = 100.0f * gem_r / champs;
	v[F_GOLD_PC] = 100.0f * gold_r / champs;
	v[F_CLU_GEM] = gem_r > 0 ? clu_gem / gem_r : 0.0f;
	v[F_CLU_GOLD] = gold_r > 0 ? clu_gold / gold_r : 0.0f;
	v[F_HEAVY] = gem_r > 0 ? heavy / gem_r : 0.0f;
	v[F_CENTRAL] = gem_r > 0 ? central / gem_r : 0.0f;
	const float tg = std::max(1.0f, tot_gems);
	v[F_MONO] = mono_g / tg;
	v[F_DASH_ONLY] = dash_g / tg;
	v[F_TP_ONLY] = tp_g / tg;
	v[F_NO_WALK_ALTAR] = no_walk_altar ? 1.0f : 0.0f;
	v[F_GATED] = (walk_altars > 0 && open_altars == 0) ? 1.0f : 0.0f;
	v[F_DASH_ALTAR] = dash_altar ? 1.0f : 0.0f;
	v[F_RECALL] = rc_w > 0 ? rc_d / rc_w : 0.0f;
	// Spawn to spawn: walking distance from our spawn to the tiles around theirs.
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
	v[F_S2S] = s2s == UNREACH ? 150.0f : static_cast<float>(s2s);
	R.meet_walk = s2s != UNREACH;
	const float area = static_cast<float>(M.w * M.h);
	const float passable = std::max(1.0f, area - static_cast<float>((M.walls | M.holes).count()));
	v[F_DENSITY] = passable / champs;
	v[F_N_ALTAR] = static_cast<float>(walk_altars);
	v[F_SAFE_ALTAR] = safe ? 1.0f : 0.0f;
	v[F_NEAR_ALTAR] = near > 1e8f ? 200.0f : near;
	v[F_GEM_TOTAL_PC] = tot_gems / champs;
	const float close = s2s == UNREACH ? 0.0f : clampf((70.0f - v[F_S2S]) / 50.0f, 0.0f, 1.0f);
	const float dens = clampf((350.0f - v[F_DENSITY]) / 250.0f, 0.0f, 1.0f);
	v[F_FIGHT] = s2s == UNREACH ? 0.0f : 0.35f * close + 0.3f * v[F_CENTRAL] + 0.15f * (safe ? 0.0f : 1.0f) + 0.2f * dens;
	R.acc = std::move(acc);
	R.ok = true;
	R.fuel_used = f0 - fuel();
	return R;
}

} // namespace nova::fitfeat
