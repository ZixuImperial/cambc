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
void decide()
{
	static bool done = false;
	if (done)
		return;
	done = true;
	const int vs = P.carrier_gold;
	if (vs < 0 || vs >= TM.n || zc::on())
		return;
	int cr = 1 << vs, k = 1;
	float dps = kit_of(P.type[static_cast<std::size_t>(vs)]).str;
	for (int i = 0; i < TM.n && k < VOP_TAB[6]; ++i)
	{
		const int s = TM.by_tank[static_cast<std::size_t>(i)];
		const Kit& kt = kit_of(P.type[static_cast<std::size_t>(s)]);
		if (s == vs || s == TM.sup || kt.slot_heal >= 0 || (kt.gem_focus && prism::carry_on()))
			continue;
		cr |= 1 << s;
		++k;
		dps += kt.str;
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
	return (gi == v && slot == P.carrier_gold) ? -5000 : 0; // her first capture
}
} // namespace nova::econ::vesper_open
