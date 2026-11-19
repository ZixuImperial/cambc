#include "champ_prism.h"
// Prism's carry plan from the map's layout, for the draft. Map features only (groups, camps, altars and their walks from M); no
// tables, no cache.
#include <algorithm>
#include "mapinfo.h"
#include "draft_flags.h"

namespace nova::prism {
MapPlan plan_for_map()
{
	MapPlan p;
	if (!M.done() || !M.has_home)
		return p;
	const long f0 = fuel();
	p.ok = true;
	// The safest altars as the Prism plan chooses them (champ_prism.cc write_plan): walkable from our spawn, not gated; the enemy's
	// walk longest, ours shorter. Safe turns: the enemy spawn's walk minus 4 (her stunner's spell range).
	int best[2] = { -1, -1 };
	float bs[2] = { -1e9f, -1e9f };
	for (std::size_t i = 0; i < static_cast<std::size_t>(M.na) && i < 255; ++i)
	{
		const auto& a = M.altars[i];
		if (a.d_home == UNREACH || a.gated || a.access != ACC_WALK)
			continue;
		++p.n_alt;
		const float de = a.d_enemy == UNREACH ? 400.0f : static_cast<float>(a.d_enemy);
		const float s = de - 0.5f * static_cast<float>(a.d_home);
		if (s > bs[0])
		{
			bs[1] = bs[0];
			best[1] = best[0];
			bs[0] = s;
			best[0] = static_cast<int>(i);
		}
		else if (s > bs[1])
		{
			bs[1] = s;
			best[1] = static_cast<int>(i);
		}
	}
	auto safe_t = [](int ai)
	{
		if (ai < 0)
			return 0;
		const auto& a = M.altars[static_cast<std::size_t>(ai)];
		return a.d_enemy == UNREACH ? 254 : std::clamp(static_cast<int>(a.d_enemy) - 4, 0, 254);
	};
	p.t_safe = safe_t(best[0]);
	p.t_safe2 = safe_t(best[1]);
	p.cap = best[0] >= 0 ? 10 * std::clamp(p.t_safe, PC_CAP_TMIN, PC_CAP_TMAX) : PC_CAP_DEFAULT;
	p.cap_trib = p.cap * 3 / 2;
	p.cap_kill = best[0] >= 0 ? std::min(1000, 15 * (rs::champ_respawn_rounds() + p.t_safe)) : 0;
	// Her groups: walkable from our spawn, on our side or the middle (as the Prism plan's), monolith groups counted apart.
	const float side = static_cast<float>(PZD_SIDE_PCT) / 100.0f;
	int dmin = 255;
	float rate = 0.0f, rate_max = 0.0f;
	for (const auto& g : M.groups)
	{
		if (g.access != ACC_WALK || g.d_home == UNREACH)
			continue;
		p.gems_all += g.gems;
		if (g.contest > side)
			continue;
		p.gold += g.gold;
		if (g.gems <= 0)
			continue;
		if (g.n_mono > 0)
		{
			p.mono += g.gems;
			continue;
		}
		++p.n_groups;
		p.gems += g.gems;
		for (const int ci : g.members)
			if (ci >= 0 && ci < M.nc && M.camps[static_cast<std::size_t>(ci)].type == cambc::camp_type::gem_cluster)
				p.clu += 7; // a gem cluster's gems (GameRules monster table, engine 2.0.0)
		const float resp = static_cast<float>(std::max(1, g.respawn));
		rate += static_cast<float>(g.gems) * 100.0f / (resp + static_cast<float>(PZD_WALK) + g.hp / static_cast<float>(PZD_DPS));
		rate_max += static_cast<float>(g.gems) * 100.0f / resp;
		if (g.gems >= PC_ROUTE_GEMS)
			dmin = std::min(dmin, static_cast<int>(g.d_home));
	}
	p.rate = static_cast<int>(rate + 0.5f);
	p.rate_max = static_cast<int>(rate_max + 0.5f);
	p.d_first = dmin;
	// Her farm under carry: PZD_FA_PCT % of her groups' rate from her first walk on; her bag holds it up to the Tribute cap.
	auto farm = [&](int t) { return dmin >= 255 ? 0 : static_cast<int>(rate * static_cast<float>(PZD_FA_PCT) / 10000.0f * static_cast<float>(std::max(0, t - dmin))); };
	p.farm250 = farm(250);
	p.farm500 = farm(500);
	p.bag250 = std::min(p.farm250, p.cap_trib);
	p.bag500 = std::min(p.farm500, p.cap_trib);
	// Gold-free map: every camp is a gem cluster (no gold cluster, wolf, elk, golem or monolith): gold comes only from kills.
	p.gold_free = !M.camps.empty();
	for (const auto& c : M.camps)
		if (c.type != cambc::camp_type::gem_cluster)
		{
			p.gold_free = false;
			break;
		}
	p.viable = p.gold_free; // She carries where no camp gives gold.
	if (!p.viable)
	{
		float gem_rate = 0.0f, gold_rate = 0.0f;
		int gems_tot = 0, gems_heavy = 0;
		for (const auto& g : M.groups)
		{
			const float resp = static_cast<float>(std::max(1, g.respawn));
			gem_rate += static_cast<float>(g.gems) / resp;
			gold_rate += static_cast<float>(g.gold) / resp;
			gems_tot += g.gems;
			if (g.n_elk + g.n_golem + g.n_mono > 0)
				gems_heavy += g.gems;
		}
		p.viable = gold_rate > 0.0f && gem_rate * 100.0f >= static_cast<float>(PZD_GG_X100) * gold_rate &&
			gems_heavy * 100 <= PZD_HEAVY_PCT * std::max(1, gems_tot);
	}
	if (!p.viable && !(nova::drafting::vgf_gate())) // v696 PKT bit 1: no pocket route on a gold-dominant map
	{
		// Reachable, uncontested cluster gems near our spawn (the pocket term in champ_prism.h).
		float pocket = 0.0f;
		for (const auto& g : M.groups)
			if (g.access == ACC_WALK && g.d_home != UNREACH && static_cast<int>(g.d_home) <= PZ_POCKET_W && g.n_att == 0 && g.n_mono == 0 &&
				g.contest <= 0.5f && g.gems > 0)
				pocket += static_cast<float>(g.gems) * 100.0f / static_cast<float>(std::max(1, g.respawn));
		p.viable = pocket >= static_cast<float>(PZ_POCKET_MIN);
	}
	p.fuel = f0 - fuel();
	return p;
}

// Draft-memory bytes 748-758 (b[0..10]; the Prism plan's block 736-759 and its checksum hold them). 748 flags: bit0 computed, bit1
// viable (she is our first pick), bit2 slot-1 one-shot (bag500 >= 20 and 14+ cluster gems), bit3 bag250 >= 20 (3.0.0's Prism bag; was 27 on 2.0.0; nothing reads these bits), bit4 gold-free map.
// 749 bag250 / 2, 750 bag500 / 2, 751 farm500 / 4, 752 our-side cluster gems / 2, 753 cap_trib / 4, 754 cap_kill / 4, 755 rate / 4
// (gems per 100 rounds), 756 d_first, 757 t_safe2, 758 layout version 1.
void plan_bytes(const MapPlan& p, std::uint8_t* b)
{
	auto u8 = [](int v) { return static_cast<std::uint8_t>(std::clamp(v, 0, 255)); };
	int fl = 0;
	if (p.ok)
		fl |= 1;
	if (p.viable)
		fl |= 2;
	if (p.bag500 >= 20 && p.clu >= 14)
		fl |= 4;
	if (p.bag250 >= 20)
		fl |= 8;
	if (p.gold_free)
		fl |= 16;
	b[0] = u8(fl);
	b[1] = u8(p.bag250 / 2);
	b[2] = u8(p.bag500 / 2);
	b[3] = u8(p.farm500 / 4);
	b[4] = u8(p.clu / 2);
	b[5] = u8(p.cap_trib / 4);
	b[6] = u8(p.cap_kill / 4);
	b[7] = u8(p.rate / 4);
	b[8] = u8(p.d_first);
	b[9] = u8(p.t_safe2);
	b[10] = 1;
}

} // namespace nova::prism
