// combat_rules.cc: Kit values and rule numbers for damage.
#include "combat_internal.h"
namespace nova::combat {
namespace kit_rules
{
namespace {
struct LbeSlot
{
	std::uint32_t h = 0;
	int round = -1;
	float m = 1.0f;
};
LbeSlot lbe_c[8];
} // namespace
static float ren_retaliation_of_cast(int slot, std::uint32_t kind, std::uint32_t handle, vec2 p);
// Fight strength of each kit beyond its stats, from the 3v3 engine fight simulations (Bradley-Terry log-odds at equal
// gold: area stuns, shields, burst and passives the health x damage product misses). Champion knowledge, not map
// knowledge. Applied (half weight) in horizon_dps().
float kit_fight_value(cambc::champion_type t)
{
	using C = cambc::champion_type;
	switch (t)
	{
	case C::heart_of_ruin: return 1.43f;
	case C::ryth: return 0.39f;
	case C::stellar: return 0.28f;
	case C::marcella: return -0.14f;
	case C::willow: return -0.13f;
	case C::ren: return -0.32f;
	case C::prism: return -0.32f;
	case C::tavi: return -0.34f;
	case C::cassi:
	case C::issac: return -0.46f;
	case C::varg: return -0.70f;
	case C::vesper_vale: return -0.72f;
	case C::vendetta: return -1.16f;
	default: return 0.0f;
	}
}
// The same slot for ENEMY bodies, refit on live duels: a Bradley-Terry fit of solo kills with each kit's log(health x horizon dps)
// at base stats as an offset, so the fitted value is the kit's residual beyond its stats; ridge-shrunk toward 0 = 'the stats tell it
// all'. Anchored on Heart of Ruin: an enemy Heart of Ruin keeps our own value, so mirror fights are unchanged and every other foe
// kit sits at the fitted distance from it (x4 = slot units, 0.25 damping). Our own bodies use kit_fight_value (foe side only). Cassi
// and Issac use kit_fight_value too (no base-stat line).
float kit_foe_value(cambc::champion_type t)
{
	using C = cambc::champion_type;
	float v = 0.0f;
	switch (t)
	{
	case C::vendetta: v = 3.26f; break;
	case C::tavi: v = 1.88f; break;
	case C::varg: v = 1.71f; break;
	case C::marcella: v = 1.63f; break;
	case C::heart_of_ruin: v = 1.43f; break;
	case C::ren: v = 0.77f; break;
	case C::ryth: v = 0.57f; break;
	case C::vesper_vale: v = 0.34f; break;
	case C::prism: v = -1.80f; break;
	case C::stellar: v = -3.73f; break;
	case C::willow: v = -5.58f; break;
	default: return kit_fight_value(t); // Cassi, Issac
	}
	const int bit = static_cast<int>(t);
	if (bit < 0 || bit > 12 || !((FIGHTCAL_A_MASK >> bit) & 1))
		return kit_fight_value(t); // a kit outside the refit mask keeps kit_fight_value
	return v + FIGHTCAL_FOE_SHIFT;
}
// Our own Skirmish (+10% v champions) and Collectors (+1% per family) multiply our champion damage (my_burst, kill_now, team focus),
// as the foe-side multiplier prices them for foes. A foe on its own spawn is skipped unless this turn's damage kills it (dmg() is
// read only then).
template <class F> static bool skip_unkillable_foe_on_spawn(const Body& e, F dmg)
{
	return bbget(M.enemy_spawn, e.pos) && !(eff_hp(e) <= dmg());
}
static float my_basic_hit() { return W.me.str * passive_mult(W.me); }
float passive_mult(const Body& b)
{
	float m = 1.0f;
	if (b.kit && b.kit->missing_hp_bonus)
		m = heart_layer::damage_mult(b.hp, b.maxhp); // HoR's live factor from current hp / current max hp
	if ((mu::bits & mu::B_FULL) != 0) [[unlikely]] // Skirmish x Collectors v champions, every body
		m *= mu::mo(b);
	return m;
}
// my damage factor on a camp for the wake guards: Heart's live factor x Monster x Collectors, no Skirmish.
static float camp_damage_factor()
{
	return (W.me.kit && W.me.kit->missing_hp_bonus ? heart_layer::damage_mult(W.me.hp, W.me.maxhp) : 1.0f) * mu::my_camp(mu::OUT);
}
namespace {
} // namespace
} // namespace kit_rules
float ren_ret_on(const Body& e);
} // namespace nova::combat
