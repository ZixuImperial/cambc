// Per-turn perception snapshot shared by brain, econ, combat and move.
#pragma once
#include "common.h"

namespace nova {

// An enemy recall counts as a channel only when its remaining time is CR2_REAL_T or less (a restart shows 4) and is not the same or
// more than at my previous turn (a Home emblem restart shows 2 each time; first sighting real only at <= 1; an unchanged timer keeps
// the last verdict); else an enemy recall counts only once it has survived a turn (seen recalling at my previous turn too). Tributes
// count at once.
#define CR2_REAL_T 3
constexpr std::uint32_t ST_ALIVE = 1u << 0, ST_RECALL = 1u << 1, ST_TRIBUTE = 1u << 2, ST_CAN_MOVE = 1u << 3,
						ST_CAN_ATTACK = 1u << 4, ST_CAN_CAST = 1u << 11, ST_TELEPORT = 1u << 12;

struct Body
{
	std::uint32_t h = 0;
	int slot = -1; // ally slot (allies only)
	bool ally = false;
	cambc::champion_type type{};
	const Kit* kit = nullptr;
	vec2 pos{};
	float hp = 0, maxhp = 1, str = 0, foc = 0;
	int range = 1;
	std::uint32_t state = 0;
	std::uint32_t gems = 0;
	bool stunned = false;
	// the body's champion-damage emblem code (Durability bit 0, Skirmish bit 1, Collectors' family count << 2), written once per turn
	// by mu::perceive_fill; mu::mi / mu::mo look its multipliers up. In stunned's padding: no size change.
	std::uint8_t mc = 0;
	float shield = 0;
	int shield_turns = 0; // turns the current shield lasts
	std::array<int, 2> cd{ -1, -1 }; // ability cooldowns: every foe in W.enemies; allies within 8 when a foe is within 9 (-1: unknown)
	bool channeling() const { return (state & (ST_RECALL | ST_TRIBUTE | ST_TELEPORT)) != 0; }
	float frac() const { return maxhp > 0 ? hp / maxhp : 0; }
};

// The single source of an enemy's slot cooldown: Body.cd as perceive() read it from the engine this turn (-1 unknown = ready).
// Every enemy cooldown reader uses these two.
inline int foe_cd(const Body& b, int s) { return b.cd[static_cast<std::size_t>(s)]; }
inline bool foe_ready(const Body& b, int s, int h = 0) { return s >= 0 && s <= 1 && foe_cd(b, s) <= h; }

struct VisCamp
{
	int ci = -1; // index into M.camps
	float hp = 0, maxhp = 0;
	bool awake = false;
};

struct World
{
	int round = 0;
	bool alive = false;
	Body me;
	std::uint32_t gold = 0;
	std::array<int, 2> cd{ 0, 0 };
	bool on_spawn = false;
	std::vector<Body> enemies; // in own_vis (my sight plus my ward's), or within WARD_NEAR of me
	std::vector<Body> enemies_far; // WARD: seen only through my ward (or while dead); intel and group news use them
	bitboard own_vis; // WARD: my own sight plus my ward's tiles (bc_champion_vision includes the ward; INT:177, world.cc read_enemies)
	std::vector<Body> allies;  // visible, excluding me
	std::vector<VisCamp> camps; // living camps (occ_camps) within 9 of me
	bitboard occ_units, occ_camps, awake, vis;
	int tributed_us = 0, tributed_them = 0;
	bool moved = false, attacked = false, cast = false; // actions taken this turn
	bool no_move = false; // a cast that excludes walking happened this turn
	std::vector<std::int16_t> camp_slot; // WARD: camp index -> position in camps (-1 when not read this turn)
	const VisCamp* camp_by_index(int ci) const
	{
		if (ci < 0 || static_cast<std::size_t>(ci) >= camp_slot.size())
			return nullptr;
		const int k = camp_slot[static_cast<std::size_t>(ci)];
		return k >= 0 ? &camps[static_cast<std::size_t>(k)] : nullptr;
	}
	const Body* ally_by_slot(int slot) const
	{
		for (const auto& a : allies)
			if (a.slot == slot)
				return &a;
		return nullptr;
	}
	bool can_move() const { return (me.state & ST_CAN_MOVE) != 0 && !no_move; }
	bool can_attack() const { return (me.state & ST_CAN_ATTACK) != 0; }
	bool can_cast() const { return (me.state & ST_CAN_CAST) != 0; }
};

extern World W;
inline vec2 bh67_vpos{ -1, -1 }; // BH67 bit 4: my tile when perceive read W.vis

// dfget(f, W.me.pos) with the chunk offset memoised (common.h me_off_key); about 70 call sites use it. Relies on vec2 being 8 bytes.
static_assert(sizeof(vec2) == 8, "FX3-ME: vec2 layout");
NOVA_INLINE std::uint16_t dfget_me(const distance_field& f)
{
	std::int64_t k;
	__builtin_memcpy(&k, &W.me.pos, 8);
	if (__builtin_expect(k != me_off_key, 0))
	{
		const vec2 q = W.me.pos;
		me_off_key = k;
		me_off_v = ((q.y >> 3) * G.cw + (q.x >> 3)) * 64 + ((q.y & 7) << 3) + (q.x & 7);
	}
	return f.ptr()[me_off_v];
}

// One-time setup of persistent champion handles.
void world_init();
bool enemy_starts(int round);
// Fill W for this turn.
void perceive();
bool foe_read_at(vec2 p); // a living foe the engine now shows me on tile p
bool foe_body_at(vec2 p, Body& b); // BSF bit 2: that foe as a Body (kit set)
// Refresh only my own state flags and position (after an action).
void refresh_self();
// BH58 bit 1 DASHOCC (caller reads the flag): re-read the unit occupancy (W.occ_units) after my position changed by a dash.
void reread_units();

} // namespace nova
