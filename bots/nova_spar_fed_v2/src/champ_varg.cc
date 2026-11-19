// champ_varg.cc: VARG LAYER, Varg's own functions (hooks and flags: champ_varg.h). Unity build: one translation unit, so combat's
// helpers are in scope.
#include "combat.h"
#include "champions.h"
// Varg's combat rules.
namespace nova::combat {
// ---- TARGETS: a splash on camp ci wakes no sleeping neighbour (prestep_hit_before_move_slow)
bool prestep_splash_ok(int ci)
{
	const vec2 p = M.camps[static_cast<std::size_t>(ci)].pos;
	for (const auto& v2 : W.camps)
		if (!v2.awake && v2.ci >= 0 && v2.ci != ci && cheb(M.camps[static_cast<std::size_t>(v2.ci)].pos, p) <= 1)
			return false;
	return true;
}
} // namespace nova::combat

// ---------------------------------------------------------------- how much Varg's splash reaches at a group See champ_varg.h (VSR).
// Reached only from econ_*.cc spawn_siege_kill_dps when VSR_ON(VSR_BIT_GEOM).
#include <vector>
namespace nova::econ::splash_geometry
{
static float adjacent_camp_mean_compute(const GroupI& g)
{
	const std::size_t nm = g.members.size();
	int sum = 0;
	for (std::size_t a = 0; a < nm; ++a)
	{
		const vec2 pa = M.camps[static_cast<std::size_t>(g.members[a])].pos;
		for (std::size_t b = 0; b < nm; ++b)
			if (b != a && cheb(pa, M.camps[static_cast<std::size_t>(g.members[b])].pos) <= 1)
				++sum;
	}
	return nm == 0 ? 0.0f : static_cast<float>(sum) / static_cast<float>(nm);
}
float adjacent_camp_mean(const GroupI& g)
{
	static std::vector<float> cache; // by M.groups index (groups are built at map load); -1 = not yet
	static std::vector<int> cache_nm; // the member count it was taken with (a rebuild re-takes it)
	const std::size_t ng = M.groups.size();
	if (ng == 0 || &g < M.groups.data() || &g >= M.groups.data() + ng)
		return adjacent_camp_mean_compute(g); // not one of M.groups: uncached
	const std::size_t gi = static_cast<std::size_t>(&g - M.groups.data());
	if (cache.size() != ng)
	{
		cache.assign(ng, -1.0f);
		cache_nm.assign(ng, -1);
	}
	if (cache[gi] < 0 || cache_nm[gi] != static_cast<int>(g.members.size()))
	{
		cache[gi] = adjacent_camp_mean_compute(g);
		cache_nm[gi] = static_cast<int>(g.members.size());
	}
	return cache[gi];
}
} // namespace nova::econ::splash_geometry

// ---- FIGHT: a foe Varg's splash reaching tile t through a mate of mine
namespace nova::combat::burst {
// a foe Varg out of reach of t still hits t by splash (Str on every other body within 1 of its target, GameRules:784) through a mate
// within 1 of t that its basic reaches: one hit, two with the reset, one after a dash.
float splash_through_mate(const Body& e, vec2 t, int cdh)
{
	const Kit& k = *e.kit;
	auto rdy = [&](int s) { return foe_ready(e, s, cdh); }; // the single cooldown source
	const int R = e.range, dr = rdy(k.slot_dash) ? static_cast<int>(k.dash_range) : -BIG;
	int hits = 0;
	for (const auto& al : W.allies)
	{
		if (cheb(al.pos, t) != 1)
			continue;
		const int dm = cheb(e.pos, al.pos);
		const bool walk = dm <= (k.ranged ? R : R + 1);
		const int hm = walk ? (rdy(k.slot_reset) ? 2 : 1) : (dm <= (k.ranged ? R + dr : R + dr + 1) ? 1 : 0);
		hits = std::max(hits, hm);
	}
	KIT_RULE_FIX_CNT(10, hits > 0);
	return hits > 0 ? static_cast<float>(hits) * e.str * kit_rules::passive_mult(e) : 0.0f;
}
} // namespace nova::combat::burst
