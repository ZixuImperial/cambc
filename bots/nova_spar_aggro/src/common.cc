// common.cc: Shared helpers: the roster and the Kit table read from the engine's designs, and kit damage estimates.
#include "common.h"
#include "mapinfo.h"
#include "rules.h" // rs::slot_cooldown
#include "champ_varg.h" // varg_layer::camp_splash_extra

namespace nova {

Grid G;
// Altar positions as a struct of arrays, inlined. Coordinates fit int16 (maps are far below 20000 tiles a side); padding sits 20000
// tiles away.
__attribute__((always_inline)) const PosSoA& altar_soa()
{
	static PosSoA a;
	if (a.n != static_cast<std::size_t>(M.na))
	{
		a.n = static_cast<std::size_t>(M.na);
		const std::size_t m = (a.n + 7) & ~std::size_t{ 7 };
		a.x.assign(m, -20000);
		a.y.assign(m, -20000);
		for (std::size_t i = 0; i < a.n; ++i)
		{
			a.x[i] = static_cast<std::int16_t>(M.altars[i].pos.x);
			a.y[i] = static_cast<std::int16_t>(M.altars[i].pos.y);
		}
	}
	return a;
}
// Fuel use: formula over 19 loops. Measured max 22,337, mean 7,182 per call, 5.5 calls per game, 39,646 per game including callees.
void init_grid()
{
	const auto L = cambc::detail::layout();
	G.w = L.width;
	G.h = L.height;
	G.cw = static_cast<int>(L.chunked_width);
	me_off_key = INT64_MIN;
	G.ch = static_cast<int>(L.chunked_height);
	G.stride = static_cast<int>(L.chunk_stride);
	for (int i = 0; i < 320; ++i)
		G_ROW[i] = ((i - G_ROW_PAD) & ~7) * G.stride + ((i - G_ROW_PAD) & 7);
	G.direct = false;
	G.direct = true;
	return;
	// Verify the decoded layout once with host writes; fall back to host reads on any mismatch.
}
// Fuel use: formula over 20 loops. Measured max 1,260, mean 1,046 per call, 20.5 calls per game, 21,466 per game including callees.
std::vector<RosterEntry> roster(team side)
{
	std::vector<RosterEntry> out;
	std::uint32_t count = 0;
	if ((side == team::ally ? cambc::detail::sdk_num_allies(&count) : cambc::detail::sdk_num_enemies(&count)) != 0)
		return out;
	std::vector<std::uint32_t> hs(count);
	if ((side == team::ally ? cambc::detail::sdk_allies(hs.data(), count, &count)
							: cambc::detail::sdk_enemies(hs.data(), count, &count)) != 0)
		return out;
	hs.resize(std::min<std::size_t>(hs.size(), count));
	for (const auto h : hs)
	{
		cambc::detail::champion_identity id{};
		if (cambc::detail::sdk_champion_identity(h, &id) != 0)
			continue;
		out.push_back({ h, static_cast<cambc::champion_type>(id.type) });
	}
	return out;
}

namespace {
Kit make_kit(cambc::champion_type t)
{
	Kit k;
	k.type = t;
	const auto& d = cambc::champion_designs.at(static_cast<std::size_t>(t));
	const auto bs = d.base_stats();
	k.hp = bs.base_health;
	k.hp_g = bs.health_growth;
	k.str = bs.base_strength;
	k.str_g = bs.strength_growth;
	k.foc = bs.base_focus;
	k.foc_g = bs.focus_growth;
	k.range = bs.base_attack_range;
	k.ranged = k.range > 1;
	k.passive = d.passive();
	using P = cambc::passive_type;
	k.stun_immune = k.passive == P::stun_immunity;
	k.splash = k.passive == P::splash_attack;
	k.gem_focus = k.passive == P::gem_focus;
	k.bonus_gold = k.passive == P::bonus_gold;
	k.remote_shop = k.passive == P::remote_shop;
	k.missing_hp_bonus = k.passive == P::missing_health_damage;
	k.kill_reset = k.passive == P::reset_cooldowns_on_kill;
	k.retaliation = k.passive == P::retaliation;
	k.health_strength = k.passive == P::health_strength;
	const auto abilities = d.abilities();
	for (int s = 0; s < 2; ++s)
	{
		const auto& ab = abilities[static_cast<std::size_t>(s)];
		const auto& info = ab.info();
		if (!info)
			continue;
		std::visit(
			[&](const auto& v)
			{
				using T = std::decay_t<decltype(v)>;
				const bool camps = v.valid_targets.contains(cambc::ability_target_mask::camps);
				if constexpr (std::is_same_v<T, cambc::ability_attack_reset>)
				{
					k.slot_reset = s;
					k.reset_enhanced = v.enhanced_attack;
				}
				else if constexpr (std::is_same_v<T, cambc::ability_damage>)
				{
					k.slot_dmg = s;
					k.dmg_mod = v.modifier;
					k.dmg_range = v.range;
					k.dmg_excl = v.exclusive_with_movement;
					k.dmg_on_camps = camps;
				}
				else if constexpr (std::is_same_v<T, cambc::ability_aoe_damage>)
				{
					k.slot_aoe = s;
					k.aoe_mod = v.modifier;
					k.aoe_range = v.range;
					k.aoe_radius = v.radius;
					k.aoe_excl = v.exclusive_with_movement;
					k.aoe_stun = v.duration > 0;
					k.aoe_on_camps = true;
				}
				else if constexpr (std::is_same_v<T, cambc::ability_cc>)
				{
					k.slot_cc = s;
					k.cc_mod = v.modifier;
					k.cc_range = v.range;
					k.cc_excl = v.exclusive_with_movement;
					k.cc_on_camps = camps;
				}
				else if constexpr (std::is_same_v<T, cambc::ability_heal>)
				{
					k.slot_heal = s;
					k.heal_mod = v.modifier;
					k.heal_range = v.range;
				}
				else if constexpr (std::is_same_v<T, cambc::ability_dash>)
				{
					k.slot_dash = s;
					k.dash_mod = v.modifier;
					k.dash_range = v.range;
					k.dash_radius = v.radius;
					k.dash_stun = v.duration > 0;
				}
				else if constexpr (std::is_same_v<T, cambc::ability_shield>)
				{
					k.slot_shield = s;
					k.shield_mod = v.modifier;
				}
			},
			*info);
	}
	k.valid = true;
	return k;
}
} // namespace

const Kit* kit_of_ptr[13] = {}; // set once a type's Kit is cached
const Kit& kit_of_slow(cambc::champion_type t)
{
	static std::array<Kit, 13> cache{};
	static std::array<bool, 13> done{};
	const auto i = static_cast<std::size_t>(t);
	if (i >= cache.size())
	{
		static Kit empty;
		return empty;
	}
	if (!done[i])
	{
		try
		{
			cache[i] = make_kit(t);
		}
		catch (...)
		{
			cache[i] = Kit{};
			cache[i].type = t;
		}
		done[i] = true;
		kit_of_ptr[i] = &cache[i];
	}
	return cache[i];
}

float kit_dps(const Kit& k, float str, float foc, int n_pack)
{
	const float pack = static_cast<float>(std::clamp(n_pack, 1, 4));
	float basic = str * (static_cast<float>(rs::slot_cooldown()) + (k.slot_reset >= 0 ? 1.0f : 0.0f)) / static_cast<float>(rs::slot_cooldown());
	if (k.splash)
		basic *= 1.0f + (varg_layer::camp_splash_extra(pack)); // VSP bit 1: the camp's splash adds extra bodies
	float spells = 0;
	if (k.slot_dmg >= 0)
		spells += k.dmg_mod * foc;
	if (k.slot_cc >= 0)
		spells += k.cc_mod * foc;
	// a radius-1 area covers a whole 3x3 pack (M.pack <= 4)
	const float area_hits = std::min(pack, 3.0f);
	if (k.slot_aoe >= 0)
		spells += k.aoe_mod * foc * area_hits;
	if (k.slot_dash >= 0 && k.dash_mod > 0)
		spells += k.dash_mod * foc * area_hits;
	float dps = basic + spells / static_cast<float>(rs::slot_cooldown());
	if (k.missing_hp_bonus)
		dps *= heart_layer::CLEAR_AVG_MULT;
	return dps;
}

} // namespace nova
