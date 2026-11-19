// Planner: capture routing to the stacking champions (stack_rank_bonus) and turn measurement (stat_*); the target timing
// constants PLAN_* are read by econ.
#pragma once
#include "common.h"

// STRIPPED (FL6): no reader of VRK_TAB in this tree; deadstrip.py find VRK before arming.
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

// ---------------------------------------------------------------- stacking
// Capture-rank adjustment for a body (lower captures): stacking champions take the rewards they multiply.
int stack_rank_bonus(int slot, int gi);

// ---------------------------------------------------------------- measurement (counters only: nothing in this tree prints them)
void stat_set_target(int gi);
void stat_wasted_trip(int gi, int walked); // arrived at a group respawning for a long time
void stat_wait(int kind); // 0 = waiting for a respawn, 1 = waiting for the crew
void stat_idle(int act); // econ::Act of the idle turn
void stat_capture(int gi, int sharing, int gems, int gold);

} // namespace nova::planner
