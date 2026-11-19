// champ_ren.cc: REN LAYER, Ren's functions (hooks: champ_ren.h). Holds his retaliation per hit (ren_ret_on), the retaliation a cast
// of mine triggers (ren_retaliation_of_cast, used by cast_via_sdk's REN guard) and the lethal-retaliation test that brain and the flee
// turn call (ren_kills_me = champ_ren.h kills_me). Unity build: one translation unit, so combat's helpers are in scope.
#include "combat.h"
#include "champions.h"
// Kit rules for Ren in combat.
namespace nova::combat {
namespace kit_rules {
// ---- FIGHT: the Ren retaliation my cast triggers The Ren retaliation my cast at p (or on champion `handle`) triggers, summed over
// the Rens it hits.
static float ren_retaliation_of_cast(int slot, std::uint32_t kind, std::uint32_t handle, vec2 p)
{
	const Kit& k = *W.me.kit;
	int rad = -1; // area radius around p; -1: single target (handle)
	if (slot == k.slot_aoe && k.aoe_mod > 0)
		rad = std::max(0, static_cast<int>(k.aoe_radius));
	else if (slot == k.slot_dash && k.dash_mod > 0)
		rad = std::max(1, static_cast<int>(k.dash_radius));
	else if (!((slot == k.slot_dmg && k.dmg_mod > 0) || (slot == k.slot_cc && k.cc_mod > 0)) || kind != KIND_CHAMPION)
		return 0.0f;
	float ret = 0.0f;
	for (const auto& o : W.enemies)
		if (o.kit && o.kit->retaliation && (rad < 0 ? o.h == handle : (p.x >= 0 && cheb(o.pos, p) <= rad)))
			ret += ren_ret_on(o);
	return ret;
}
} // namespace kit_rules
} // namespace nova::combat
namespace nova::combat {
// ---- FIGHT: Ren e's retaliation per instance (rs::ren_ret x his outgoing factor)
float ren_ret_on(const Body& e) { return ren_layer::retaliation_damage(e.foc) * (mu::mo(e)); }
// ---- FIGHT: that retaliation takes my effective HP (the base guards ask champ_ren.h kills_me inline)
bool ren_kills_me(const Body& e) { return ren_layer::kills_me(e); }
} // namespace nova::combat
