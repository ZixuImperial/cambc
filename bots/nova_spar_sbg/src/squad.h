// squad.h: Squads per objective: which bodies work together, chosen each turn from their objectives. Top bots are alone about 48% of
// body-rounds and in packs of 3+ about 26%; partners are not fixed, they regroup per objective. So the unit here is a SQUAD PER
// OBJECTIVE, never a permanent partner slot and never chosen by champion identity: two bodies are squad mates while their objectives
// (the groups their claim bytes name) lie within SQ_LEASH tiles of each other. Every body computes the same squads from the claim
// bytes (team memory), so squads form, merge (3+ bodies at one contested objective) and dissolve with the claims. API:
// squad::objective(s) slot s's objective (its claimed group; mine is econ's target), -1 none; squad::outside(gi) group gi lies
// outside our own third (contest > SQ_OUT); squad::mates(s) bit mask of slot s's squad mates (objectives within SQ_LEASH of s's);
// squad::mates_near_group(gi, self) bodies other than self whose objective lies within SQ_LEASH of group gi; squad::near_mate() the
// nearest visible squad mate of mine (nullptr if none in sight); squad::committed_near(p, r) visible squad mates of mine within r of
// tile p (not channelling); squad::zone(p) walk share between the spawns at p (0 ours, 1 theirs).
#pragma once
#include "common.h"
#include "world.h"

// Switches: integers are #if switches; floats are only read at run time (never #if on them). A body's objective is worth SQ_BONUS
// more (leashed farming: two adjacent groups, no value split); a lone trip there (no mate's objective near, crew of one, not my
// current target) is worth SQ_LONE; a second body may join a lone claimant outside our own third (the solo rule's exemption).
#define SQ_OUT 0.40f // a group lies outside our own third above this contest (our walk / both walks)
#define SQ_LEASH 6 // tiles between two objectives' anchors that make their bodies one squad
#define SQ_BONUS 1.0f // rate factor of an outside group within SQ_LEASH of a mate's objective (in group_bounds' bound)
#define SQ_LONE 1.0f // rate factor of a lone outside trip
                    // Squad waiting: a body whose sight walks (claim not engaged), is more than a set number of tiles away and
                    // farther from the objective, waits at most a set number of rounds a trip (the leader never walks into the
                    // middle alone ahead of its mate). Strike gate: a fight it would start (nothing reaches me, not caught, not hit
                    // in 2 rounds, no ally of mine in contact, balance below SQ_STRIKE_SOLO) needs a committed squad mate at the
                    // focus (within its range + 1) or a healthy ally within 3 of me; else CALM (never FLEE). Finishers, caught and
                    // in-reach fights are not gated.
#define SQ_STRIKE_SOLO 2.5f // at this initiation balance or more a body may strike alone (a much weaker lone foe)
                  // Squad formation: our own third with no other body's objective within SQ_LEASH; each seed (slot order) takes as
                  // partner the nearest pool body (living, not the healer, objective inside our own third, claim not engaged;
                  // distance between the two objectives' anchors, at most SQ_FORM_R). The partner's next target choice is restricted
                  // to groups within SQ_LEASH of the seed's objective (its own group included).
#define SQ_FORM_R 30
#define SQ_FORM_FROM 40 // formation: no partner is pulled before this round (the opening's drafted crews stand)
#define SQ_FORM_LEASH 6 // formation: the partner's candidates lie within this many tiles of the seed's objective (0: the seed's group only)
                   // Squad follow: a slot whose claim changed in the last SQ_STICK_AGE rounds to a group outside our own third: I
                   // take that group too (a squad that leaves together stays together), if rate_for allows it (it may join a lone
                   // claimant).
#define SQ_STICK_R 4
#define SQ_STICK_LEASH 6 // follow: the follower takes its best group within this many tiles of the leader's new group (0: that group itself; > 0: leashed farming, the leader's group included)
                         // rounds a claim change still counts for following (leashed farming: the leader's group included when the
                         // leash is above 0)
#define SQ_STICK_AGE 6
#define SQ_KEEP 0.7f // follow / formation: follow or partner only when my rate there is at least this share of my own best choice (follow) or of my current target (formation); 0 = always
                     // Trio rule: a seed on a monolith or golem group takes two partners (a squad of 3). Central rule: follow only
                     // groups with contest 0.40-0.60, elks or gem clusters, no monolith or golem, and enough gems; otherwise any
                     // group outside our own third.
#define SQ_WITHIN_MAX 8 // work cap: a partner's or follower's leash choice rates at most this many groups (nearest anchors first)
#define SQ_HOT 1 // squads only where they are needed: a seed and a follow need at least SQ_HOT enemies known within SQ_HOT_R of the objective in the last SQ_HOT_AGE rounds (intel::danger: own, ward and team sightings); 0 = always
                 // SQ_HOT_R of the objective in the last SQ_HOT_AGE rounds (intel::danger: own, ward and team sightings); 0 = always
#define SQ_HOT_R 10
#define SQ_HOT_AGE 25
                  // Edge wait: wait for a squad mate (by objective, or my assigned partner) that is still walking (claim not
                  // engaged) and not within a set gap + 1 of me, at most a set number of rounds a trip; a mate already engaged at
                  // its objective is joined at once.

namespace nova::squad {

void begin_turn();             // once a turn, after comms::read (claims)
void background(long reserve); // spare fuel: the walk field from the enemy spawn (zone of a tile), once
int objective(int s);
bool outside(int gi);
float zone(vec2 p);
unsigned mates(int s);
int mates_near_group(int gi, int self);
// the partner the formation gives seed s, and the seed slot s is the partner of (-1: none). Once a round.
int squad_seed_of_slot(int s);
bool alive(int s);
// SQ_HOT: enough enemies known near group gi lately for a squad (always true with SQ_HOT 0).
bool hot(int gi);
// A squad objective: outside our own third, a central prize when the central rule is on, hot when SQ_HOT is on (seeds and follows).
bool objective_ok(int gi);
// the squad size a seed on group gi forms (2; 3 on central elk / gem-cluster groups when the trio rule is on). Static map data only
// (identical on every body).
int want(int gi);
// the round slot s's claim byte last changed (-1000 if never seen to change) and its claimed group now.
int claim_changed(int s);

struct Diag
{
	int waits = 0, trips = 0, bonus = 0, lone = 0, joins = 0, refused = 0, partnered = 0, edge = 0, stuck = 0;
};
Diag& diag();

} // namespace nova::squad
