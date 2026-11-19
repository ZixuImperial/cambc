// Team intelligence: enemy sightings and camp-group news, from this champion's own vision (which includes its ward, also while the
// champion is dead) and from teammates through the team event (comms bytes 6-7 of the image; the TM2 channel carries it), plus
// enemy deaths, which the engine reports for every enemy body whether it is in vision or not. Vision is per champion, so anything a
// ward sees reaches allies only through that slot. One event fits at a time: a subject (camp group, or an altar after the groups),
// a type and a 5-bit round stamp.
// Every ally reads the slot at the start of each of its turns, so an event is protected for HOLD rounds (all allies have had a turn)
// and may only be overwritten earlier by a more urgent one.
#pragma once
#include "common.h"

namespace nova {
struct Body;
}

namespace nova::intel {

enum EventType : int
{
	EV_ENEMY = 0,   // one enemy seen near the subject (group or altar)
	EV_ENEMIES = 1, // two or more enemies seen near the subject
	EV_TAKEN = 2, // the subject group was captured at the stamped round (our own captures too: mates learn the respawn)
	EV_CLEARED = 3, // enemies cleared the subject group at the stamped round; their capture is pending
};

// Setup turn (spare fuel): read the enemy roster and size the tables, so the first play turn stays cheap.
void init();
// After perceive() and comms::read(): decode the team event and record own sightings (a dead champion still sees
// through its ward).
void begin_turn();
// After the turn's actions: post the most useful pending event, if the slot may be overwritten (~2k fuel).
void end_turn();
// Background: precompute the tile -> nearest subject map in fuel-bounded steps.
void analyse(long reserve);

// Group news observed by this champion (called from econ::observe).
void record_group_taken(int gi, int capture_round);
void record_group_cleared(int gi);

// Enemies near p: the larger of own sightings (each enemy's last seen tile, widened by how far it may have walked) and
// teammates' reports, counting sightings no older than max_age rounds. Sightings of an enemy that has died since are
// dropped; with every enemy dead the answer is 0. ~1k fuel per call.
float danger(vec2 p, int radius, int max_age);
bool danger_shared_any(vec2 p, int radius, int max_age); // danger_shared(...) >= 1, first match

// Tile of an event subject.
vec2 subject_pos(int subject);

// Enemy bodies alive now (deaths are visible from anywhere), and in total.
int enemies_alive();
int enemies_total();
// Kill window: the round the first dead enemy body can be back on its spawn (far in the future when none is dead).
int earliest_respawn();
// WINBANK: rounds until any enemy body (living: last own sighting widened by its walk since; dead: its spawn after respawn) can
// stand within reach of p, at spd_x100/100 tiles a round.
int reach_rounds(vec2 p, int reach, vec2 spawn, int spd_x100);
// the round my turn last saw enemy body h dead after being alive (-1000: never died, or unknown).
int foe_died_round(std::uint32_t h);
// the latest round any enemy body was seen to die (-1000: none).
int last_death();
// Round of the latest enemy sighting known to me: mine (ward included) or a teammate's report (-1000 if none).
int latest_sighting();
// CONTEST: distinct living enemies seen (own or ward sight, at most `age` rounds ago) within r of c.
int count_near(vec2 c, int r, int age);
// BOUNDS: the tiles of count_near's sightings (own or ward sight, at most `age` rounds old) in its order, up to cap; returns how
// many there are (more than cap: only the first cap were written).
int recent_own(vec2* out, int cap, int age);
// CONTEST: enemies that can stand `walk` rounds from their spawn by round t (living + respawned in time).
int possible_at(int t, int walk);

// FIGHTCAL: the last known place of each living enemy body: my latest own or ward sighting (at_spawn false), else its spawn
// (at_spawn true; the caller supplies the tile) from its respawn round (a death 60 rounds earlier; a death voids the sighting) or
// from round 0 if it was never seen. Dead bodies are left out.
struct Known
{
	std::uint32_t h = 0;
	vec2 pos{};
	int round = 0;
	bool at_spawn = false;
};

// TEAM INTEL: my latest knowledge of each enemy body, in roster(team::enemy) order: my own sight (src 1), my ward (src 2, also
// while dead) or its spawn (src 4). A death clears the entry (round -1000) until the body is seen again or respawns. Empty before
// init(). Teammates' sightings (src 3, EV_SIGHT) need TI_SIGHT, which is 0: src 3 is never set.
struct TeamSeen
{
	std::uint32_t h = 0;
	vec2 pos{ -1, -1 };
	int round = -1000;
	int src = 0; // 1 my sight, 2 my ward, 4 its spawn (round 1, or its respawn); 3 (a teammate's EV_SIGHT) never with TI_SIGHT 0
	bool alive = true;
	cambc::champion_type type{};
};
const std::vector<TeamSeen>& team_table();
std::uint32_t team_ver(); // v8xx ALHV1: bumped at every team-table write (with ALHV_ON(1))
// The last Body I read for enemy i of the table (own sight or ward: stats, health at that time); nullptr if never.
const Body* team_body(std::size_t i);
// the round team_body(i) was last refreshed by my sight or ward (-1000 never, or since its death).
int team_body_round(std::size_t i);
void team_body_pred(std::size_t i, int now, Body& b); // MUL bit 2048 (intel.cc): b (a copy of team_body(i)) at its own growth

struct Stats
{
	int ward_sightings = 0; // enemy-turns seen beyond our own vision radius (only the ward sees that far)
	int dead_sightings = 0; // enemy-turns seen while dead (through the ward)
	int posted[4]{}, received[4]{};
	int sight_posted = 0, sight_read = 0; // EV_SIGHT messages written / read as new
};

} // namespace nova::intel
