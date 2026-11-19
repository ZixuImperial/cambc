// Per-champion turn: perception, comms and the decision state machine.
#pragma once
#include "common.h"

#define TD_RATE_PCT 80 // cancel when the rounds left times the damage per round reach 80% of HP + shield
#define TD_LOW_PCT 35  // or when HP + shield < 35% of max HP and still dropping
#define TD_BLOCK_R 20  // after a cancel: no new tribute for up to 20 rounds while hit within the last 2 rounds
#define TD_WIN_R 6
#define TD_LEAVE_R 40
#define TD_LEAVE_BAG 50   // only a carrier with 50+ gems (the bag is what dies)
#define TD_LEAVE_FUEL 40000 // and only with this much fuel left (escape and the guarded walk search)

namespace nova {

void play_turn();
bool spin_on_turn_start(); // First call of a turn: cancels my own spin; true means skip the turn.
void spin_on_turn_end(); // Last call before end_turn: starts a spin when free and safe.

} // namespace nova
