// econ_clear_estimate.cc: Time and damage to clear a camp group.
#include "econ_internal.h"
namespace nova::econ {
namespace {
// At the observation that sets a group's hp_left (hidden members at full, as hp_left counts them; dead 0), the living attackers'
// clear sums, so estimate() prices them in O(1): with hp h_k lowest first and H_k = h_1 + .. + h_k, tc x dps = H_n and dmg x dps =
// the sum over attackers of strength_k x H_k. bgx_gn < 0: never noted.
static std::vector<float> bgx_s1, bgx_s2;
static void note_attackers_clear_sums(const GroupI& g, std::size_t gi)
{
	if (bgx_gn.size() != static_cast<std::size_t>(M.ng))
	{
		if (!M.ready())
			return; // fuel: M.groups still grows during map analysis; allocate once, at its final size
		bgx_gn.assign(static_cast<std::size_t>(M.ng), -1);
		bgx_s1.assign(static_cast<std::size_t>(M.ng), 0.0f);
		bgx_s2.assign(static_cast<std::size_t>(M.ng), 0.0f);
	}
	alignas(std::pair<float, float>) unsigned char a_raw[16 * sizeof(std::pair<float, float>)]; // No zeroing; only [0, n) is used.
	std::pair<float, float>* const a = reinterpret_cast<std::pair<float, float>*>(a_raw);
	constexpr int a_cap = 16;
	int n = 0;
	bool over = false;
	for (int ci : g.members)
	{
		const auto& c = M.camps[static_cast<std::size_t>(ci)];
		if (!c.attacks())
			continue;
		float h = c.hp;
		if (bbget(W.vis, c.pos))
		{
			if (!bbget(W.occ_camps, c.pos))
				continue; // dead
			const VisCamp* vc = visible_camp(ci);
			h = vc ? vc->hp : c.hp;
		}
		if (h <= 0.0f)
			continue;
		if (n == a_cap)
		{
			over = true;
			break;
		}
		a[static_cast<std::size_t>(n++)] = { h, c.str };
	}
	if (over)
	{
		bgx_gn[gi] = -1; // more attackers than the buffer: not noted
		return;
	}
	for (int i = 1; i < n; ++i) // insertion sort: a handful of attackers
		for (int j = i; j > 0 && a[static_cast<std::size_t>(j)].first < a[static_cast<std::size_t>(j - 1)].first; --j)
			std::swap(a[static_cast<std::size_t>(j)], a[static_cast<std::size_t>(j - 1)]);
	float H = 0, s2 = 0;
	for (int i = 0; i < n; ++i)
	{
		H += a[static_cast<std::size_t>(i)].first;
		s2 += a[static_cast<std::size_t>(i)].second * H;
	}
	bgx_s1[gi] = H;
	bgx_s2[gi] = s2;
	bgx_gn[gi] = static_cast<std::int8_t>(n);
}
__attribute__((always_inline)) ClearEst estimate(const GroupI& g, const GroupMem& m, const Crew& c)
{
	ClearEst e;
	if (m.status == GS_CLEARED)
	{
		e.feasible = true;
		return e;
	}
	const float scale = (m.status == GS_ALIVE && m.hp_left >= 0) ? clampf(m.hp_left / std::max(1.0f, g.hp), 0.02f, 1.0f) : 1.0f;
	float dps = c.dps(g.pack) * 0.85f;
	// Passive Ren: every attacker that hits Ren takes 0.2 x Focus back, with no action of his. The tank takes the hits of the attackers
	// the other melee bodies do not hold (each holds one of a pack); about 60% of them live on average over the clear.
	if (!g.att.empty() && (c.ret_tank > 0 || c.ret_hold > 0))
	{
		const int n_att = static_cast<int>(g.att.size());
		const int held = std::min(n_att - 1, std::max(0, c.n_melee - 1));
		dps += 0.6f * (c.ret_tank * static_cast<float>(n_att - held) + (n_att >= 2 ? c.ret_hold : 0.0f));
	}
	dps = std::max(10.0f, dps);
	e.t = g.hp * scale / dps + 0.4f * static_cast<float>(static_cast<std::size_t>(g.nm));
	// Vendetta: a cluster group (no attackers): each kill refunds the reset, so every turn is attack + reset; one hit per cluster (str
	// >= its health) kills two a turn, two hits one a turn. The rest of the crew adds its damage in clusters per turn.
	if (c.chain > 0 && g.n_att == 0 && !g.members.empty())
	{
		const float hm = g.hp / static_cast<float>(static_cast<std::size_t>(g.nm));
		const float kpt = c.chain >= hm ? 2.0f : (2.0f * c.chain >= hm ? 1.0f : 0.0f);
		if (kpt > 0)
		{
			const float others = std::max(0.0f, dps - 0.85f * c.chain_dps1);
			const float rate = kpt + others / std::max(1.0f, hm);
			const float tc = static_cast<float>(static_cast<std::size_t>(g.nm)) * scale / rate + 0.4f * static_cast<float>(static_cast<std::size_t>(g.nm));
			e.t = std::min(e.t, tc);
		}
	}
	float tc = 0, dmg = 0;
	int n_att = static_cast<int>(g.att.size());
	if (!g.att.empty() && m.status == GS_ALIVE && m.hp_left >= 0 && static_cast<std::size_t>(g.idx) < bgx_gn.size() && bgx_gn[static_cast<std::size_t>(g.idx)] >= 0)
	{
		const std::size_t bgx_gi = static_cast<std::size_t>(g.idx);
		tc = bgx_s1[bgx_gi] / dps;
		dmg = bgx_s2[bgx_gi] / dps;
		n_att = bgx_gn[bgx_gi];
	}
	else
	{
		tc = 0;
		dmg = 0;
		for (const auto& a : g.att)
		{
			tc += a.first * scale / dps;
			dmg += a.second * tc;
		}
	}
	if (n_att > 0)
	{
		// Each stun cancels one hit of the strongest attacker (at most every hit).
		if (ko1_any(c))
		{
			float ko1_st8 = 0;
			const float ko1_x = stun_soak_cancel(c, g, &ko1_st8);
			dmg -= (std::min(1.0f, ko1_st8 / static_cast<float>(rs::slot_cooldown())) * g.str_max + ko1_x) * tc;
		}
		else
			dmg -= std::min(1.0f, c.stuns8 / static_cast<float>(rs::slot_cooldown())) * tc * g.str_max;
		dmg -= (c.heal8 + c.shield8) / static_cast<float>(rs::slot_cooldown()) * tc;
		KIT_RULE_FIX_CNT(3, c.heal_first > 0); // Bit 8 of the rule fixes: a solo healer's own heal is not counted.
	}
	e.dmg = std::max(0.0f, dmg);
	if (g.n_mono + g.n_golem > 0 && g.contest <= 0.45f)
		e.dmg *= static_cast<float>(HVY_TAB[2]) / 100.0f; // v647 HVY CAL: own-half heavy groups take ~.55 of the modelled camp damage
	const int he_m = HE_TAB[1]; // mode bits, then the heavy-group test
	const int he = (n_att > 0 && he_group(g)) ? he_m : 0;
	const auto& cb = (he & 1) ? c.budget_he : c.budget;
	float budget = c.n_melee > 0 ? cb[0] : 0.0f;
	if (n_att >= 2)
		for (int i = 1; i < std::min(n_att, c.n_melee); ++i)
			budget += 0.85f * cb[static_cast<std::size_t>(i)];
	else if (n_att == 1 && c.n_melee >= 2)
	{
		// A lone attacker hits only its nearest champion: melee bodies take it in turns (a hurt tank steps out of
		// reach and the next one holds it). Strong lone camps (monoliths, golems) are cleared this way.
		const float w = g.str_max >= 100.0f ? 0.8f : 0.6f;
		const int k = g.str_max >= 100.0f ? c.n_melee : 2;
		for (int i = 1; i < k; ++i)
			budget += w * cb[static_cast<std::size_t>(i)];
	}
	if (c.n >= 2)
		budget *= 1.0f + CREW_RESV * crew_group_k(g); // crews on own-side gem camps accept more camp risk in the mode
	e.feasible = n_att == 0 || e.dmg <= budget;
	e.budget = budget;
	if ((he & 2) && !e.feasible && budget > 0.0f && heavy_multi_trip_ok(g, m))
	{
		// the clear over several trips (budget renewed by a recall; the camps keep their damage).
		const int tmax = OP_PLAY != 0 ? 1 : HE_TAB[2];
		const float cyc = 5.0f + static_cast<float>(g.d_home) + 2.0f; // recall, the walk back, the sleep
		const float tr = e.dmg <= budget * static_cast<float>(tmax) ? std::ceil(e.dmg / budget) : 1e9f; // no int cast of a huge ratio
		const float t2 = e.t + (tr - 1.0f) * cyc;
		if (tr <= static_cast<float>(tmax) && static_cast<float>(now()) + t2 + 40.0f <= GAME_END_F)
		{
			e.feasible = true;
			e.t = t2;
		}
	}
	return e;
}
inline ClearEst estimate_cx(int cx, const GroupI& g, const GroupMem& m, const Crew& c)
{
	cxc_ctx = cx;
	return estimate(g, m, c);
}
} // namespace
} // namespace nova::econ
