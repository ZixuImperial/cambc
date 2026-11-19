// Dash routes (pathological-map fix): goal-directed travel for champions with a dash, over ground that walking
// cannot cross (hole lines, bent and knight-shaped dashes around wall corners). Map features only.
//
// A route to a goal is a stack of layers: layer 0 is the walk field to the goal tiles (camp tiles blocked);
// layer k is the walk field to the tiles from which one dash lands in a lower layer. A champion walks downhill in
// its layer and dashes from a launch tile (waiting there for the cooldown). Layers are built lazily, one host
// distance field each, in spare fuel, and kept (terrain is static).
#pragma once
#include "common.h"


namespace nova::dn {

constexpr int GOAL_ALTAR = -1; // every standable altar neighbour; other goals are group indices

// My kit has a dash.
bool dasher();
// Estimated turns from p to the goal (walk steps + 8 per dash), from the layers built so far; UNREACH if none reaches p.
int route_len(int goal, vec2 p);
// Build missing layers (while p is not covered and more than `reserve` fuel would remain). True when p is covered.
bool prepare(int goal, vec2 p, long reserve);
// One move along the route: walk, or dash from a launch tile when ready. True if I moved or dashed, or I am
// holding on a launch tile for the cooldown.
bool step(int goal);
// Background work in spare fuel (the altar route for dashers on maps without a walkable altar). True when a layer was built.
bool background(long reserve);
// One stage of the altar route in what is left of the turn, down to res. True when a stage ran.
bool altar_route_stage(long res);
// Consecutive rounds (up to now) in which I stood on a launch tile with my dash ready and every landing of my route was taken (a
// teammate parks there).
int blocked_rounds();

} // namespace nova::dn
