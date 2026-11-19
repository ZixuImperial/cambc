// Planner: a camp-state model for every group, route planning over sequences of groups with spare fuel, and capture routing to the
// stacking champions. Hooks in econ/brain are marked " PLANNER".
#pragma once
#include "common.h"

#define VRK_BITS 0 // Bit 1: Vesper outranks Marcella on a mixed group when her +33% gold beats Marcella's +2 gold/gem. Bit 2: Prism keeps first rank on gem groups. 0 = off.
inline constexpr int VRK_TAB[3] = { 0x56524B31, VRK_BITS, 0x314B5256 };
#define RCY_BITS 1 // Bit 1: a capture goes to the crew body whose kit gains most from it now: damage per 100 gold
                   // x the capture's gold (+2 gold per gem for Marcella), fading with the round; replaces Marcella's and Vesper's
                   // fixed capture bonuses (Prism's gem bonus, C&I and healer terms stay); 0 = off.
#define RCY_K 30 // Rank points per point of damage the capture's gold buys (bit 1).
inline constexpr int RCY_TAB[4] = { 0x52435931, RCY_BITS, RCY_K, 0x31594352 };
#define PLAN_WAIT_DIST 2 // respawn clock: tiles from the nearest spawn tile of the group
#define PLAN_EVAL_EVERY 5 // Rounds between target re-evaluations (fuel for decisions).
#define PLAN_EVAL_FUEL 52000 // Fuel needed to start a re-evaluation.
#define PLAN_EVAL_FLOOR 32000 // Candidates are evaluated while this much fuel remains.

namespace nova::planner {

// ---------------------------------------------------------------- camp-state model
enum CState : std::uint8_t
{
	CS_UNKNOWN = 0, // never seen: assume alive at full HP
	CS_ALIVE,       // living members (hp_left may be below full: camps never regenerate)
	CS_CLEARED,     // every member dead, reward waiting for a capture
	CS_RESPAWN,     // captured, waiting to respawn
};
enum CapBy : std::uint8_t
{
	BY_NONE = 0,
	BY_ME,
	BY_ALLY,  // inferred from an ally's claim moving on after it engaged the group
	BY_ENEMY, // seen captured with no ally claim on it
	BY_SOMEONE,
};
struct Camp
{
	std::uint8_t state = CS_UNKNOWN;
	std::uint8_t by = BY_NONE;
	bool awake = false;
	bool exact = false;      // respawn_at read from the engine timer (else predicted)
	float hp_left = -1;      // living HP when last seen (-1: full)
	int seen = -1000; // Last round a member tile was in vision.
	int captured_at = -1000; // round of the last capture
	int respawn_at = 0;      // predicted round the group is alive again
	int engaged_by = -1;     // ally slot seen engaged on it (claims)
	int engaged_round = -1000;
};

// Per-turn update from vision, allies' claims and (after the merge) ward news. Cheap: groups near me only.
void observe();
// I captured group gi this round.
void on_captured_by_me(int gi);
// News about a group from shared memory (ward events after the merge): kind 1 = taken (captured), 2 = cleared.
const Camp& camp(int gi);
// Round the group is predicted alive again (0 when alive or unknown).

// Spend spare fuel on background planning work while more than `reserve` would remain.
void background(long reserve);

// Value of continuing from a group with the best one or two further groups, as (value, rounds), computed in the
// background from the group-to-group matrix, each group's value and solo clear time for me, respawn timing and the
// allies' claims. Used to rank first targets by the value per round of the whole route.
struct Leg
{
	float v = 0, t = 0;
};
// Leg evaluation supplied by econ: value in gem units for me and my solo clear time; false if I cannot do it alone.
using LegEvalFn = bool (*)(int gi, float* value, float* clear_t);
void set_leg_eval(LegEvalFn fn);
// Best two-group continuation after group gi (t = 0 when unknown).
// Upper bound of the continuation's value per round after group gi (0 when unknown).
// Value per round of a route that starts with group gi (value v1 in t1 rounds, times the target's penalty factor).

// ---------------------------------------------------------------- stacking
// Capture-rank adjustment for a body (lower captures): stacking champions take the rewards they multiply.
int stack_rank_bonus(int slot, int gi);

// ---------------------------------------------------------------- measurement (NOVA_STAT builds print it)
void stat_turn_begin();
void stat_turn_end(bool counted);
void stat_set_target(int gi);
void stat_wasted_trip(int gi, int walked); // arrived at a group respawning for a long time
void stat_wait(int kind); // 0 = waiting for a respawn, 1 = waiting for the crew
void stat_idle(int act); // econ::Act of the idle turn
void stat_capture(int gi, int sharing, int gems, int gold);

} // namespace nova::planner
