// contest_play.h: Contested zone: how bodies play it. CONTEST: the play side of the zone plan. On maps whose drafted zone passes the
// swing gate, a crew of the most durable camp tanks leaves at setup for the zone's staging tile S, gathers, enters together, works
// only zone groups (everyone else keeps off them), counts numbers (own and ward sight, a ward on the hold, enemy death windows),
// yields as a team when outnumbered, and hands off to normal play once the first contest is settled. Team decisions go through the
// event slot as type 7. The phase is a function of shared inputs only (draft block, plan, round, type-7 events), so every body
// agrees.
#pragma once
#include "common.h"
#include "contest_zone.h"

namespace nova::combat {
struct Assessment;
}

#define CT_PLAN 1 // Runtime gate (volatile ct_plan_rt, read once): 0 plays the base game on every map.
#define CT_SECURE_ROUNDS 15
                 // 0 = the zone plan as before.
#define CT_ON_WAY_MIN 8
#define CT_FRESH_AFTER 40 // Rounds after the enemy's expected arrival during which the avoid-heavy rule holds.
#define CT_PUSH_DEAD 1
#define CT_PUSH_AHEAD 15
#define CT_RACE_EVERY 4
#define CT_RACE_MAX_SLACK 80
#define CT_BACK_ROUNDS 60
#define CT_BACK_BONUS 1.6f
#define CT_GATHER 6 // Rounds at S before 2 gathered bodies may enter.
#define CT_IDLE_MAX 8 // A crew body with no zone group to work for this many rounds is released to normal play (0: never).
#define CT_GATHER_MAX 15 // Rounds at S facing equal or more enemies before the crew yields.
#define CT_OUT_ROUNDS 3 // Consecutive outnumbered rounds inside before a yield.
#define CT_YIELD_HOLD 30 // Rounds the zone stays excluded for every body after a yield.

namespace nova::zc {

// Setup (after intel::init): decode the block, roles, crew. Identical on every body.
void init();
// Runs every turn after intel::begin_turn (also while dead): reads type-7 events, updates the phase, and posts the ward owner's SEEN
// message.
void begin_turn();
// The plan is running (crew phase).
bool on();
// Slot s is in the zone crew (while ON).
bool is_crew(int s);
// Econ filter for body `self` and group gi: R1 (non-crew bodies keep off zone groups while ON, everyone while YIELDED) and the
// crew's restriction to the zone. True = allowed.
bool allow(int gi, int self);
// Opening: my target at setup when I am crew (the entry group), else -1.
int opening_target();
// Brain, before econ::farm: walk to S, gather, the numbers and yields. True if the turn was used.
bool crew_turn(const combat::Assessment& a);
// Brain, when econ::farm found nothing: crew bodies wait at the hold (instead of idling elsewhere). True if acted.
bool idle_turn();
// Used by combat::assess: crew mates out of my sight that work a zone group (claim + engaged bit), when I am a crew body inside the
// zone; they count as friends in the outnumbered tests.
int unseen_mates_near();
// True when threat_seen should not blacklist group gi: crew bodies keep zone groups while the plan is running.
bool keep_group(int gi);
// ward::act hook with the charge ready: 0 normal ward logic, 1 place the ward at *out (then ward_result), 2 keep the
// charge (pinned ward, or saving it for the hold).
int ward_pin(vec2* out);
void ward_result(bool placed);
// Econ fast path: true while the plan is ON or YIELDED (allow() can say no only then).
extern bool active_;
inline bool allow_fast(int gi, int self) { return !active_ || allow(gi, self); }

float respawn_return_factor(int gi); // Target factor for a zone group shortly after my respawn.
bool back_live(); // True when respawn_return_factor can differ from 1 (the plan is set up and gated in); false: it is 1 for every group.
void track_respawn_round();
bool avoid_heavy(int gi, float clear_t);
bool first_contest_over();
} // namespace nova::zc
