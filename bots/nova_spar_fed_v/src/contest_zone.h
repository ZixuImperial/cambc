// contest_zone.h: Contested zone: computed in the draft from the map layout; memory block. CONTEST: the contested zone of the map,
// computed by the draft from the map layout only (no map identity) and handed to the champions in draft memory bytes 832-1023.
// Zones: complete-linkage clusters (walk diameter 10) of contested groups (|d_enemy - d_home| <= 8, no monolith), hold tile =
// minimax walk to the members. Gate (swing): ON iff 2 x DS x take(K0) >= (1 + RHO) x cost(K0), where take(K) is what K crew bodies
// farm in the zone and cost(K) the own-side harvest they leave. S / E: the tiles within R+3 of the hold that our / the enemy's spawn
// reaches first (where each side's crew arrives).
#pragma once
#include "common.h"

#define CT_DS 0.35f // Expected shift of our share of the zone's harvest (gate).
#define CT_RHO 0.25f // Risk premium on the own-side cost (gate).
#define CT_WG 0.3f // Gold in gem units (gate).
                 // The gate cost counts our-half groups nearer than the zone, and the gate needs net > 0; zones beyond s2s +
                 // ZG_REACH_S2S are skipped, and no plan runs when the spawns are under ZG_S2S_MIN apart. A group whose span is
                 // wider than the zone diameter has its nearest camp a few steps from both spawns, so the one-walk-per-group zone
                 // model would score it contested and build the zone on it. Such groups are never zone candidates nor zone groups;
                 // they are farmed as normal groups. 0 = off.
#define ZG_SPAN_MAX 10 // Widest camp extent (Chebyshev, tiles) a zone group may have (the zone's walk diameter).
#define ZG_S2S_MIN 20
#define ZG_REACH_S2S 10

namespace nova::zone {

constexpr std::size_t BLOCK_AT = 832, BLOCK_END = 1024;
constexpr std::uint8_t BLOCK_MAGIC = 0x43, BLOCK_VERSION = 1;
constexpr int MAXM = 12;

struct ZoneB
{
	bool valid = false;
	vec2 hold{}, S{}, E{};
	int R = 0, entry = -1, n = 0;
	int members[MAXM]{};
	int dA = 0, dB = 0, margin = 0, dSH = 0, dHS = 0, cycle = 0; // dSH walk S-hold, dHS walk home-S
	float swing = 0, cost = 0, orate = 0;
};

struct Block
{
	bool ok = false, gate = false;
	int T = 0, K0 = 0, Kf = 0, Kmax = 0;
	int nz = 0, ncand = 0; // zones found, candidates passing margin/reach (diagnostics)
	ZoneB z;
};

// Draft side: advance the zone model while more than `reserve` fuel remains (resumable over draft turns). True once
// the block is ready (then write_block can append it).
bool draft_step(long reserve, int T);
bool ready();
// Draft side: put the block at bytes 832-1023 of the draft memory buffer (grows it to 1024). True if written.
bool write_block(std::vector<std::uint8_t>& mem);

} // namespace nova::zone
