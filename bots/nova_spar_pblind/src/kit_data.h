#pragma once
// kit_data.h: The roster and Kit: a champion's stats, slots and passive flags, read from the engine's designs.
#include "common_flags.h"
namespace nova {
// Champion handles and physical types of one side, read with raw calls (no champion objects: those cost ~700 fuel each).
struct RosterEntry
{
	std::uint32_t h;
	cambc::champion_type type;
};
std::vector<RosterEntry> roster(team side);

// Static description of a champion kit, read from the engine's design metadata.
struct Kit
{
	cambc::champion_type type{};
	bool valid = false;
	bool ranged = false;
	int range = 1;
	float hp = 0, hp_g = 0, str = 0, str_g = 0, foc = 0, foc_g = 0;
	cambc::passive_type passive{};
	int slot_reset = -1, slot_dmg = -1, slot_aoe = -1, slot_cc = -1, slot_heal = -1, slot_dash = -1, slot_shield = -1;
	float dmg_mod = 0, aoe_mod = 0, cc_mod = 0, heal_mod = 0, dash_mod = 0, shield_mod = 0;
	float dmg_range = 0, aoe_range = 0, cc_range = 0, heal_range = 0, dash_range = 0, aoe_radius = 0, dash_radius = 0;
	bool dmg_excl = false, aoe_excl = false, cc_excl = false;
	bool aoe_stun = false, dash_stun = false, reset_enhanced = false;
	bool cc_on_camps = false, dmg_on_camps = false, aoe_on_camps = false;
	bool stun_immune = false, splash = false, gem_focus = false, bonus_gold = false, remote_shop = false;
	bool missing_hp_bonus = false, kill_reset = false, retaliation = false, health_strength = false;
};

#define PRE_WALL 0
#define RD_SHOP 4
#define RD_HEAL 0
#define EXPLORE 0
#define RD_TRAVEL 0
inline constexpr int RECALL_EXPLORE_TAB[6] = { 0x42373337, PRE_WALL, RD_SHOP, RD_HEAL, EXPLORE, RD_TRAVEL }; // slot 0 magic keeps it out of .bss
#define RDS_V (static_cast<int>(ES_TAB[11]))
#define EXP_V (RECALL_EXPLORE_TAB[4])
#define PW_LEN 10
#define RD_D0 24
#define RD_HURT 65



// Kit for a physical champion type (cached, computed from champion_designs). The filled cache is read inline (fuel: kit_of would
// otherwise be an out-of-line call with two function-local statics, 3.6 calls a turn).
const Kit& kit_of_slow(cambc::champion_type t);
extern const Kit* kit_of_ptr[13];
inline const Kit& kit_of(cambc::champion_type t)
{
	const auto i = static_cast<std::size_t>(t);
	if (i < 13)
		if (const Kit* k = kit_of_ptr[i])
			return *k;
	return kit_of_slow(t);
}

// Rough sustained damage per round against camps, from stats and kit (n = monsters packed together).
float kit_dps(const Kit& k, float str, float foc, int n_pack);

// Stuns per 8 rounds that can land on camps or champions.


// OFS: our side of the focus fix. A sum of our bodies' damage would count every mate in full, but mates split their damage: a body
// counts on foe e at OFS_SH_ONE when e is its known focus (me: team_focus / my lock) or the only foe in its reach, else at the
// measured split share (me OFS_SH_ME, mate at d1 OFS_SH_D1, d2+ OFS_SH_D2, x100). A mate's focus is not carried by comms. One bit
// per site group.
#define OFS_BITS 0
#define OFS_SH_ME 75
#define OFS_SH_D1 57
#define OFS_SH_D2 48
#define OFS_SH_ONE 100
inline constexpr int OFS_TAB[7] = { 0x4F465331, OFS_BITS, OFS_SH_ME, OFS_SH_D1, OFS_SH_D2, OFS_SH_ONE, 0x3153464F }; // magic, bits, shares, end magic
constexpr int OFS_BIT_ASSESS = 1;  // assess f_sq (the fight ratio)
constexpr int OFS_BIT_HELP = 2;    // idle_mate_help_power
constexpr int OFS_BIT_HOLD = 4;    // contested_gem_hold
constexpr int OFS_BIT_COMMIT = 16;
constexpr int OFS_BIT_ALL = 31;
#define PRA_DEC(v) ((v)) // our own or a mate's value -> the raw value
} // namespace nova
