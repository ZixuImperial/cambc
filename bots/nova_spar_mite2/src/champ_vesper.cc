// champ_vesper.cc: VESPER LAYER, Vesper Vale's rules (hooks and flags: champ_vesper.h). Holds the dash into range
// (fight_vesper_dash). Unity build: one translation unit, so combat's helpers are in scope.
#include "combat.h"
#include "champions.h"
// Vesper Vale's combat rules.
namespace nova::combat {
namespace fight_turn {
namespace {
// ---- FIGHT: the dash into range (VV_DASH, VV_INIT) Vesper Vale (ranged, range 3) dashes 2 steps to bring a focus 4-5 tiles away
// into range for this turn's basic attack (the dash is a cast, not the ranged move/attack allowance), on the same focus as
// Vendetta's, onto the landing the fewest other enemies can reach.
static __attribute__((always_inline)) inline void fight_vesper_dash(FightCtx& c)
{
	const Body& f = c.f;
	bool vv_init = false; // the dash fires only through the healthy-focus alternative
	if (!vesper_layer::fight_dash() || !slot_up(c.k.slot_dash) || !W.can_attack())
		return;
	if (c.d <= W.me.range || c.d > W.me.range + c.dash_r)
		return;
	if (!burst::kills(f, W.me.range, KQ_DASH) && !fight_weak_focus(f) && !(vv_init = geom::engage_dash_ok(c.a, f)))
		return;
	if (ren_layer::kills_me(f))
		return; // FAC bit 128 KIT2: Ren's retaliation kills me, attack_champion refuses the hit (GR:752): keep the dash
	int best_s = 1 << 30;
	const vec2 best = geom::dash_landing_tile(f, vv_init, best_s);
	if (best.x >= 0 && best_s <= vesper_layer::VV_LANDING_CROWD && cast_at(c.k.slot_dash, best))
		fight_moved(c);
}
} // namespace
} // namespace fight_turn
} // namespace nova::combat

// ---------------------------------------------------------------- a team with Vesper Vale opens together See champ_vesper.h (VOP).
// Unity build: after econ_*.cc, whose file-local state (M, TM, P, T, mem, opened) is in scope. Only reached when VOP_ON(...) is true
// at the hook.
namespace nova::econ::vesper_open
{
namespace
{
int v = -1, crew = 0, n = 0; // decided once, from base stats and spawn walks: every body reaches the same group and crew
int ch[4] = { -1, -1, -1, -1 }, nch = 0, ck = 0; // VOC: the chain v[0..nch-1] (ch[0] = v, same on every body) and my link
// VOC: the chain from v0 under bits (2: four links, else two; 4: elk links), each link VOP's loop with the walk from the previous
// link's anchor (1.25 x cheb: no group-to-group table at the first turn), earlier links excluded, own side only. Base stats only.
int chain_build(int v0, int bits, float dps, int* out)
{
	const int kmax = (bits & 2) ? 4 : 2;
	out[0] = v0;
	int nc = 1;
	while (nc < kmax)
	{
		const vec2 from = M.groups[static_cast<std::size_t>(out[nc - 1])].anchor;
		int best = -1;
		float best_r = 0;
		for (int gi = 0; gi < M.ng; ++gi)
		{
			bool used = false;
			for (int j = 0; j < nc; ++j)
				used |= out[j] == gi;
			const auto& g = M.groups[static_cast<std::size_t>(gi)];
			const int gmin = ((bits & 4) && g.n_elk > 0) ? VOC_ELK_GMIN : VOP_TAB[2];
			if (used || g.gold < gmin || g.n_mono > 0 || g.n_golem > 0 || g.access != ACC_WALK || g.d_home == UNREACH || static_cast<int>(g.d_home) > VOP_TAB[3] ||
				g.d_home > g.d_enemy || 100.0f * g.contest > static_cast<float>(VOP_TAB[4]))
				continue;
			const float t = 1.25f * static_cast<float>(cheb(from, g.anchor)) + g.hp / std::max(1.0f, dps) + 6.0f;
			if (t > static_cast<float>(VOP_TAB[5]))
				continue;
			const float r = static_cast<float>((bits & 4) ? g.gold + 2 * g.gems : g.gold) / t;
			if (r > best_r)
			{
				best_r = r;
				best = gi;
			}
		}
		if (best < 0)
			break;
		out[nc++] = best;
	}
	return nc;
}
bool in_chain(int gi)
{
	for (int k = 0; k < nch; ++k)
		if (ch[k] == gi)
			return true;
	return false;
}
void decide()
{
	static bool done = false;
	if (done)
		return;
	done = true;
	const int vs = P.carrier_gold;
	if (vs < 0 || vs >= TM.n)
		return;
	int cr = 1 << vs, k = 1;
	const Kit& x65_vk = kit_of(P.type[static_cast<std::size_t>(vs)]);
	float dps = kit_dps(x65_vk, x65_vk.str, x65_vk.foc, 1); // X65 bit 8 VOP1: spells and passives count
	for (int i = 0; i < TM.n && k < VOP_TAB[6]; ++i)
	{
		const int s = TM.by_tank[static_cast<std::size_t>(i)];
		const Kit& kt = kit_of(P.type[static_cast<std::size_t>(s)]);
		if (s == vs || kt.slot_heal >= 0 || (kt.gem_focus && prism::carry_on()))
			continue;
		cr |= 1 << s;
		++k;
		dps += (kit_dps(kt, kt.str, kt.foc, 1)); // X65 bit 8 VOP1
	}
	int best = -1;
	float best_r = 0;
	for (int gi = 0; gi < M.ng; ++gi)
	{
		const auto& g = M.groups[static_cast<std::size_t>(gi)];
		if (g.gold < VOP_TAB[2] || g.n_mono > 0 || g.n_golem > 0 || g.access != ACC_WALK || g.d_home == UNREACH || static_cast<int>(g.d_home) > VOP_TAB[3] ||
			100.0f * g.contest > static_cast<float>(VOP_TAB[4]))
			continue;
		const float t = static_cast<float>(g.d_home) + g.hp / std::max(1.0f, dps) + 6.0f;
		if (t > static_cast<float>(VOP_TAB[5]))
			continue;
		const float r = static_cast<float>(g.gold) / t;
		if (r > best_r)
		{
			best_r = r;
			best = gi;
		}
	}
	if (best < 0)
		return;
	v = best;
	crew = cr;
	n = k;
	if (VOC_ON(1))
		nch = chain_build(v, VOC_TAB[1], dps, ch);
}
// VOC: refresh_target's hold on my chain link. A link is done for a member once cleared, for the carrier once her capture paid; then
// I move on to the next link, or leave the crew after the last. Links end by state (bit 2: no round limit after v[0]).
bool keep_chain(int s)
{
	const bool her = s == P.carrier_gold;
	{
		const int gi = ch[ck];
		const auto& m = mem[static_cast<std::size_t>(gi)];
		if (m.status == GS_RESPAWN || (!her && m.status == GS_CLEARED))
		{
			if (ck + 1 >= nch || (VOC_ON(2) && cheb(W.me.pos, M.groups[static_cast<std::size_t>(gi)].anchor) > VOC_WITH))
			{
				crew &= ~(1 << s);
				return false;
			}
			++ck;
		}
	}
	const int gi = ch[ck];
	const auto& g = M.groups[static_cast<std::size_t>(gi)];
	const auto& m = mem[static_cast<std::size_t>(gi)];
	int foes = 0;
	for (const auto& e : W.enemies)
		foes += cheb(e.pos, g.anchor) <= 8 ? 1 : 0;
	const bool later = ck > 0 && VOC_ON(2);
	if ((!later && now() > VOP_TAB[7]) || m.status == GS_RESPAWN || m.fail_until > now() || foes >= 2 ||
		(later && (static_cast<int>(W.me.gems) >= B467_BANKB || W.me.frac() < SG_HP)))
	{
		crew &= ~(1 << s);
		return false;
	}
	if (W.me.frac() < SG_HP)
		return false;
	if (T.target != gi)
		set_target(gi, 1.0f, n);
	T.eval_round = now();
	return true;
}
} // namespace
void claim(std::array<int, 8>& cl, std::array<bool, 8>& done)
{
	decide();
	if (v < 0)
		return;
	for (int s = 0; s < TM.n && s < 8; ++s)
		if ((crew >> s) & 1)
		{
			cl[static_cast<std::size_t>(s)] = v;
			done[static_cast<std::size_t>(s)] = true;
		}
}
void rate(int choice, float* out_rate, int* out_crew)
{
	if (choice >= 0 && choice == v && ((crew >> my_slot()) & 1) != 0)
	{
		*out_rate = 1.0f;
		*out_crew = n;
	}
}
bool keep()
{
	const int s = my_slot();
	if (v < 0 || s < 0 || s >= 8 || ((crew >> s) & 1) == 0 || gmem_size(mem) != static_cast<std::size_t>(M.ng))
		return false;
	if (VOC_ON(1) && nch > 1)
		return keep_chain(s);
	const auto& g = M.groups[static_cast<std::size_t>(v)];
	const auto& m = mem[static_cast<std::size_t>(v)];
	int foes = 0;
	for (const auto& e : W.enemies)
		foes += cheb(e.pos, g.anchor) <= 8 ? 1 : 0;
	if (now() > VOP_TAB[7] || m.status == GS_RESPAWN || m.fail_until > now() || foes >= 2 || (m.status == GS_CLEARED && s != P.carrier_gold))
	{
		crew &= ~(1 << s);
		return false;
	}
	if (W.me.frac() < SG_HP)
		return false;
	if (T.target != v)
		set_target(v, 1.0f, n);
	T.eval_round = now();
	return true;
}
int rank(int gi, int slot)
{
	if (VOC_ON(1) && slot == P.carrier_gold && gi != v && in_chain(gi))
		return (now() > VOP_TAB[7] && !VOC_ON(2)) ? 0 : -5000; // VOC: every chain link (bit 1 alone: until VOP_END; RC C222)
	return (gi == v && slot == P.carrier_gold) ? -5000 : 0; // her first capture
}
bool hold_off(int gi)
{
	const int s = my_slot(), vs = P.carrier_gold;
	if (v < 0 || nch < 2 || s < 0 || s >= 8 || s == vs || ((crew >> s) & 1) == 0 || !in_chain(gi))
		return false;
	const auto& g = M.groups[static_cast<std::size_t>(gi)];
	for (const auto& e : W.enemies)
		if (cheb(e.pos, g.anchor) <= 8)
			return false; // a foe near the region: holding off could hand it the capture (RC C222 HOF1b)
	for (const auto& a : W.allies)
		if (a.slot == vs)
		{
			if (on_group_spawn_tile(g, W.me.pos) && !on_group_spawn_tile(g, a.pos))
				return false; // I hold the region and she is not on it yet: leaving would reset the capture (GR:198; RC C222 HOF1)
			return !a.channeling() && a.frac() >= SG_HP && cheb(a.pos, g.anchor) <= VOC_NEAR; // she is in sight, up and near: her tile
		}
	return false;
}
} // namespace nova::econ::vesper_open
