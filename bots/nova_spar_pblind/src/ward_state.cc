// ward_state.cc: Ward tunables and background analysis state.
#include "ward_internal.h"
namespace nova::ward {
// A camp spawn tile blocks a ward only while a living camp may stand on it; a ward there does not delay the respawn. The flag is
// read only on camp tiles.
static bool camp_tile_blocks_ward(vec2 p)
{
	if (!bbget(M.camp_tiles, p))
		return false;
	if (bbget(W.vis, p) && !bbget(W.occ_camps, p))
	{
		KIT_RULE_FIX_CNT(6, true);
		return false;
	}
	return true;
}

namespace {

enum Kind : std::uint8_t
{
	K_GROUP,
	K_ALTAR,
	K_CHOKE,
	K_BUSH,
	K_N
};

// A hot spot: tiles worth watching and a static weight in gem-equivalents.
struct Spot
{
	vec2 c{};
	std::uint8_t kind = K_GROUP;
	std::uint8_t nk = 0;
	std::int16_t ref = -1; // group or altar index
	int ext = 0;           // largest Chebyshev distance from c to a key tile
	float w0 = 0;
	std::array<vec2, 4> key{};
};

// Placement policy: a fresh charge waits for BAR0 worth of hot spots, accepting less the longer it waits; a placed ward is moved
// when a spot beats it by a margin, its own value fading as our activity moves on.
constexpr float BAR0 = 30.0f;
constexpr float BAR_MIN = 8.0f;
constexpr float BAR_TURNS = 25.0f;
constexpr float GAIN_MIN = 6.0f;   // a new spot must beat the current ward by this much (and by 25%)
constexpr float CUR_FADE = 120.0f; // turns over which the current ward's value fades in that comparison
constexpr float CUR_FLOOR = 0.4f;
// Scout fallback: a charge that found no hot spot for SCOUT_WAIT turns still goes down when my ward is more than SCOUT_FAR tiles
// away, two tiles toward the enemy's approach (so every champion wards all game, and the ward watches where I farm and the way
// enemies would come).
constexpr int SCOUT_WAIT = 20;
constexpr int SCOUT_FAR = 7;
constexpr int BUSH_GAP = 6; // no new bush ward within this of a ward of ours
constexpr int MAX_BUSH = 24;
constexpr int MAX_CHOKE = 6;
constexpr std::size_t KEY_SAMPLE = 16; // tiles of a big bush cluster used for distance tests and key tiles
// Fuel. Loops here cost ~15-80 fuel per iteration and buffer initialisation ~1 fuel per byte: every background step checks a margin
// above its own cost, and act() (up to ~20k: two new coverage lists, ten spot-weight refreshes, the placement) runs only with
// ACT_FUEL left.
constexpr long ACT_FUEL = 55000;
constexpr int MISS_MAX = 2;              // new coverage lists (vision query + spot scan) per act() call
constexpr int WEIGHT_BUDGET = 10;        // spot weight refreshes per act() call
constexpr std::size_t POOL_MAX = 60000;  // coverage entries kept before the cache is rebuilt
constexpr long ACT_FLOOR = 22000;        // act() starts no refresh or new coverage list below this (turn <= ~80k)

std::vector<Spot> spots;
std::vector<Spot> bush_spots; // Best bush clusters found so far (at most MAX_BUSH), appended at the end.
std::size_t n_basic_spots = 0;

// ---------------------------------------------------------------- background analysis state

enum Stage
{
	A_BASIC,     // group and altar spots, one group per step
	A_COV0,      // coverage cache for them (act() can work from here on)
	A_FIELD,     // walking field from the enemy spawn
	A_SCAN,      // route corridor between the spawns, by level
	A_CHOKES,    // narrow corridor levels
	A_BUSH_INIT, // collect the bush tiles, one 8x8 chunk per step
	A_BUSH,      // bush clusters, grown a few tiles per fuel check
	A_FINAL,     // append chokes and bushes, rebuild the coverage cache
	A_DONE
};
int stage = A_BASIC;
std::size_t cursor = 0;
std::unique_ptr<distance_field> fe_own;
const distance_field* fe = nullptr;
std::unique_ptr<distance_field> fe_keep; // The enemy-spawn field, kept after the analysis.
int S = 0, slack = 0;
std::vector<std::uint16_t> width;           // corridor tiles per distance level from the enemy spawn
std::unique_ptr<unsigned char[]> lvl_raw; // v787 WCB WLT1: raw storage for lvl_tiles, no zero-fill (each read slot is written first)
std::array<vec2, 4>* lvl_tiles = nullptr; // first tiles of each level (in lvl_raw)
bitboard corridor;
bool have_corridor = false;
std::vector<vec2> bush_tiles;      // every bush tile, in scan order
TileMap<std::int16_t> bush_lbl;    // per tile: bush cluster label, 0 none yet
std::vector<vec2> cl;              // bush cluster being grown
std::size_t cl_k = 0;              // next tile of cl to expand
bool cl_open = false;
int cl_id = 0;

// ---------------------------------------------------------------- coverage cache

// Static coverage of a ward on a tile, computed on first use (a ward's view from a tile never changes).
struct CovEntry
{
	std::int16_t spot;
	std::uint8_t c; // coverage * 255
};
struct CovRef
{
	std::int32_t off = -1; // first entry in cov_pool, -1 unknown
	std::uint8_t len = 0;
};
TileMap<CovRef> cov_ref;
std::vector<CovEntry> cov_pool;
std::vector<int> sx, sy, srad; // spot centres and vision reach (vision radius + extent), for fast range tests
bitboard scratch;
int misses_left = 0; // new coverage lists allowed in the current act() call

// ---------------------------------------------------------------- my ward and known ally wards

vec2 my_ward{ -1, -1 };
int my_ward_round = -1000;
std::vector<std::uint8_t> watch; // per group: my ward sees a spawn tile
std::uint32_t watch_ver = 0; // Bumped on every write of watch.
int ready_round = 0, ready_since = -1;
int next_check = 0;
vec2 check_pos{ -1, -1 };
std::vector<float> ew; // effective spot weights of the current evaluation (0 for spots out of reach)
struct Bad
{
	vec2 p;
	int until;
};
std::vector<Bad> bad; // tiles that refused a ward recently (usually a mate's ward: sight is not shared)

struct AllyWard
{
	std::uint32_t owner = 0;
	vec2 pos{ -1, -1 };
	int seen = -1000;
};
std::vector<AllyWard> ally;
std::vector<float> acov; // per spot: best coverage by a known ally ward
bool acov_dirty = true;
int ally_scan = -1000;

int vision_r = 6, reach_r = 2, recharge = 10;
bool consts_read = false;

// Debug counters: wards placed, bush wards and value per kind.
int n_bush = 0;
std::array<float, K_N> kind_value{};

int now() { return W.round; }
long cov_cost() { return 2L * G.w * G.h / 64 * 10 + 40L * static_cast<long>(spots.size()) + 5000; }
} // namespace
} // namespace nova::ward
