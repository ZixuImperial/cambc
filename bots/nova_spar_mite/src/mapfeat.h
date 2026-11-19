// Draft map features. The nine features of the REPL table, computed once on the first draft turn from MapInfo plus fitfeat's
// per-group reach. Farmable group: walk or dash reachable, no monolith; cyc = max(10, respawn + 10) + hp / 150. Marcella's splash
// feature has three tiers, each fitted separately: 0 exact greedy splash simulation on every farmable group, 1 exact for groups of
// <= 10 members and the neighbour proxy above, 2 the neighbour proxy on every group. The tier is chosen once from the fuel budget
// before the loop, so the value is never a mix the fit did not see.
#pragma once
#include "common.h"
#include "draft_value_table.h"

namespace nova::mapfeat {

struct Feats
{
	bool ok = false;
	int tier = 2;                   // Marcella's splash tier (0 exact, 1 cap10, 2 proxy)
	bool altar_field = false;       // own walk field to the altars (camps passable), else MapInfo's d_altar
	std::array<float, dv3::NF> x{}; // raw feature values (before log1p, clip and standardisation)
	long fuel_used = 0, fuel_splash = 0, est_splash = 0, fuel_field = 0, fuel_loop = 0;
	int n_farm = 0, max_members = 0;
	std::array<long, 3> dbg{}; // Fuel in tank load, splash, walks.
};

// Requires M.done() and fitfeat's per-group reach `acc` (indexed like M.groups). `reserve` = fuel that must stay for the
// draft's other work; the exact splash tiers run only within the budget above it.
Feats compute(int team_size, const std::vector<std::uint8_t>& acc, long reserve);

} // namespace nova::mapfeat
