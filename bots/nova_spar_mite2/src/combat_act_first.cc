// combat_act_first.cc: The act-first fallback.
#include "combat_internal.h"
namespace nova::combat {
namespace actfirst
{
namespace tune
{
inline constexpr int AF_CAMPS_FALLBACK = 16;      // camps the fallback step weighs
inline constexpr int AF_AWAY_CAP = 12;            // tiles of distance from the foes past which the fallback sees no gain
inline constexpr int AF_TILE_COST = 20;           // fallback cost of a tile of distance to the foes
inline constexpr int AF_STEP_TRIES = 3;           // refused steps before the fallback gives up
inline constexpr int AF_STANCE_ROUNDS = 3;        // the last stance guides the fallback this long
inline constexpr float AF_LOW_HP = 0.45f;         // below this HP share the fallback steps away
}
namespace {
int af_stance = -1, af_round = -100;
std::uint32_t af_focus_h = 0;
// Awake attacking camps that could reach a neighbouring tile (no camp_threat_build: its cost is what ran out). Fills near, returns the count.
template <std::size_t N>
static int act_first_near_camps(std::array<int, N>& near)
{
	int nn = 0;
	for (std::size_t k = 0; k < W.camps.size() && nn < static_cast<int>(N); ++k)
	{
		const auto& vc = W.camps[k];
		if (!vc.awake || vc.ci < 0 || static_cast<std::size_t>(vc.ci) >= static_cast<std::size_t>(M.nc))
			continue;
		const auto& c = M.camps[static_cast<std::size_t>(vc.ci)];
		if (c.attacks() && cheb(c.pos, W.me.pos) <= c.reach + 1)
			near[static_cast<std::size_t>(nn++)] = vc.ci;
	}
	return nn;
}
// What the camps in near would hit p for, weighted.
template <std::size_t N>
static int act_first_camp_cost(const std::array<int, N>& near, int nn, vec2 p, int weight)
{
	int v = 0;
	for (int k = 0; k < nn; ++k)
	{
		const auto& c = M.camps[static_cast<std::size_t>(near[static_cast<std::size_t>(k)])];
		if (cheb(p, c.pos) <= c.reach)
			v += (static_cast<int>(c.str) + 1) * weight;
	}
	return v;
}
// Tries the neighbours cheaper than staying, cheapest first. True when one was taken.
template <class Cost>
static bool act_first_step_down(Cost&& cost)
{
	const int stay = cost(W.me.pos);
	std::array<std::pair<int, int>, 8> cand{};
	int nc = 0;
	for (int k = 0; k < 8; ++k)
	{
		const vec2 n = W.me.pos + DIRS[static_cast<std::size_t>(k)];
		// Per-tile reads of dynamic_walls' sources (its whole-board rebuild costs ~4k; a refused step tries the next one).
		if (!inb(n) || bbget(M.block, n) || bbget(W.occ_units, n) || bbget(W.occ_camps, n) || (bbget(M.camp_tiles, n) && !bbget(W.vis, n)))
			continue;
		const int v = cost(n);
		if (v < stay)
			cand[static_cast<std::size_t>(nc++)] = { v, k };
	}
	std::sort(cand.begin(), cand.begin() + nc);
	for (int k = 0; k < nc && k < tune::AF_STEP_TRIES; ++k)
		if (mv::try_move(W.me.pos + DIRS[static_cast<std::size_t>(cand[static_cast<std::size_t>(k)].second)]))
			return true;
	return false;
}
} // namespace
} // namespace actfirst
void act_first_note_assessment(const Assessment& a)
{
	actfirst::af_stance = static_cast<int>(a.stance);
	actfirst::af_round = W.round;
	actfirst::af_focus_h = a.focus >= 0 && static_cast<std::size_t>(a.focus) < W.enemies.size() ? W.enemies[static_cast<std::size_t>(a.focus)].h : 0;
}
void act_first_fallback(bool attack_only)
{
	if (!W.alive || W.me.channeling() || W.enemies.empty())
		return;
	const int st = W.round - actfirst::af_round <= actfirst::tune::AF_STANCE_ROUNDS ? actfirst::af_stance : -1;
	bool hit = W.attacked;
	if (!W.attacked && W.can_attack())
	{
		const Body* best = nullptr;
		float bh = 1e30f;
		for (const auto& e : W.enemies)
		{
			if (cheb(W.me.pos, e.pos) > W.me.range)
				continue;
			float h = eff_hp(e);
			if (st >= 0 && actfirst::af_focus_h != 0 && e.h == actfirst::af_focus_h)
				h -= 1e9f;
			if (h < bh)
			{
				bh = h;
				best = &e;
			}
		}
		if (best)
			hit = attack_champion(*best);
	}
	if (attack_only || W.moved || !W.can_move() || fuel() < AF_MOVE_MIN)
		return;
	const bool away = st == FLEE || W.me.frac() < actfirst::tune::AF_LOW_HP || (!hit && st != FIGHT && st != CALM);
	const bool toward = !away && !hit && st == FIGHT;
	if (!away && !toward)
		return;
	const Body* tgt = nullptr;
	int td = BIG;
	for (const auto& e : W.enemies)
	{
		const int d = cheb(W.me.pos, e.pos);
		if (toward && actfirst::af_focus_h != 0 && e.h == actfirst::af_focus_h)
		{
			tgt = &e;
			break;
		}
		if (d < td)
		{
			td = d;
			tgt = &e;
		}
	}
	if (!tgt)
		return;
	std::array<int, actfirst::tune::AF_CAMPS_FALLBACK> near{};
	const int nn = actfirst::act_first_near_camps(near);
	auto cost = [&](vec2 p)
	{
		int v = actfirst::act_first_camp_cost(near, nn, p, 1);
		if (away)
		{
			int md = BIG;
			for (const auto& e : W.enemies)
				md = std::min(md, cheb(p, e.pos));
			v -= std::min(md, actfirst::tune::AF_AWAY_CAP) * actfirst::tune::AF_TILE_COST;
			if (M.has_home)
			{
				const std::uint16_t hv = dfget(M.f_home, p);
				if (hv != UNREACH)
					v += static_cast<int>(hv) / 4;
			}
		}
		else
			v += cheb(p, tgt->pos) * actfirst::tune::AF_TILE_COST;
		return v;
	};
	actfirst::act_first_step_down(cost);
}
} // namespace nova::combat

namespace nova {
// out of line, so each AF_CHECK point stays a load, a compare and a call.
[[noreturn]] __attribute__((noinline)) void af_throw()
{
	throw AfBail{};
}
// FXR bit 1: a stale call (resumed in a later round) unwinds to fxr_run.
[[noreturn]] __attribute__((noinline)) void fxr_throw()
{
	fxr_stale = true;
	fxr_inflight = true;
	throw RestartTurn{};
}
} // namespace nova
// macros local to this module end here
#undef KQ_SITE
