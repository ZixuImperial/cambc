// Map features for the draft, computed at runtime from MapInfo (mapinfo.h) plus a forward dash closure that uses dashnav's dash
// model (two-step dash, bent and knight-shaped, middle tile not a wall or a camp), not the straight thin-hole model. No map identity
// anywhere. The draft's coefficient table uses these values.
#pragma once
#include "common.h"

namespace nova::fitfeat {

enum Feat
{
	F_K,             // team size
	F_GEM_PC,        // farmable gem supply, gems per 100 rounds per champion (walk or dash reachable, no monolith)
	F_GOLD_PC,       // farmable gold supply, gold per 100 rounds per champion
	F_CLU_GEM,       // pure-cluster share of the farmable gem supply
	F_CLU_GOLD,      // pure-cluster share of the farmable gold supply
	F_HEAVY,         // elk/golem-guarded share (group strength >= 60) of the farmable gem supply
	F_MONO,          // monolith share of all gems on the map
	F_DASH_ONLY,     // share of all gems reachable only with dashes
	F_TP_ONLY,       // share of all gems reachable neither on foot nor by dash
	F_NO_WALK_ALTAR, // 1 when no altar can be reached on foot (camps passable: a gated altar is walkable)
	F_DASH_ALTAR,    // 1 when no altar is walkable but one is reachable by dash
	F_RECALL,        // supply-weighted walk from spawn to farmable groups on our half and the centre (contest <= 0.6)
	F_S2S,           // walk distance between the spawns (150 when they never meet)
	F_CENTRAL,       // share of the farmable gem supply in central groups (contest 0.4..0.6)
	F_DENSITY,       // passable tiles per champion on the map (both teams)
	F_N_ALTAR,       // walkable altars (gated included)
	F_SAFE_ALTAR,    // 1 when a walkable altar is within 30 of our spawn, 10+ nearer to us than to them, 20+ from theirs
	F_NEAR_ALTAR,    // walk to the nearest walkable altar (200 when none)
	F_GEM_TOTAL_PC,  // all gems on the map per champion (monoliths included)
	F_FIGHT,         // fight likelihood 0..1: spawn closeness, central share, no safe altar, density
	F_GATED,         // 1 when every walkable altar is gated (its approach tiles are camp tiles: kill the gate first)
	NF
};

extern const char* const NAMES[NF];

struct Result
{
	bool ok = false;
	std::array<float, NF> v{};
	long fuel_used = 0;
	int dash_iters = 0;
	bool closure = false; // the dash closure ran (dv3)
	// Per-group reach for us, indexed like M.groups: 0 walk, 1 dash (fitfeat closure), 2 teleport crystal only (a standable tile within
	// Chebyshev 3 of the walk/dash set), 3 none. Unwalkable groups stay 3 when the closure was skipped for fuel.
	std::vector<std::uint8_t> acc;
	// What each mobility class can turn into score, from the reach classes above. A walker realises the gems of walk groups only when
	// it can walk to an altar, a dasher those of walk and dash groups when it can walk or dash to one; gold needs no altar (weight
	// REACH_GOLD per gold). Farmable groups as the features (no monolith), rates per respawn cycle.
	float reach_vw = 0.0f, reach_vd = 0.0f; // walker / dasher realisable value rate (gem-equivalents per round)
	int reach_nd = 0;                       // farmable groups whose value only a dasher realises (solo dash trips)
	bool meet_walk = false;                 // the spawns meet on foot (camps passable): walkers can fight
};

constexpr float REACH_GOLD = 0.1f; // Gem-equivalents per gold (gems win, gold is the tiebreak and the shop).

// Requires M.done() (f_home and f_enemy computed). Returns ok=false (and does nothing heavy) when less than
// `reserve` plus the estimated cost would remain. Cost: about 2-6k on maps where every group and an altar are walkable;
// one distance field per dash layer otherwise (3*w*h + 4000 each, at most 8 layers) plus 8 bitboard shifts per layer.
Result compute(int team_size, long reserve);

} // namespace nova::fitfeat
