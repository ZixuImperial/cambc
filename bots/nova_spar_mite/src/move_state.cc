// move_state.cc: Move tunables, shared state and board helpers.
#include "move_internal.h"
namespace nova::mv {

// ======== Tunables: the named numbers of moving, one block per module ========
namespace tune
{
inline constexpr int AWAKE_MEM_ROUNDS = 3;        // an awake camp out of sight still counts this long
inline constexpr long FIELD_SLACK = 40000;        // an on-demand group field leaves this much fuel in the turn
inline constexpr long HOME_FIELD_SLACK = 25000;   // the same for the home field
// Step scores: lower wins
inline constexpr int STEP_TILE = 16;              // per tile of walk left
inline constexpr int STEP_LEVEL = 12;             // a step that gains nothing on the field
inline constexpr int GREEDY_AXIS = 2;             // step_greedy: per tile of axis gap (straighter path)
inline constexpr int AWAY_TILE = 20;              // step_away: per tile from the nearest threat
inline constexpr int AWAY_HOME_DIV = 4;           // step_away: walk home / this
// Search budget of step_to_set
inline constexpr long STS_GREEDY_FUEL = 30000;    // below this: greedy step, no search
inline constexpr long STS_R10_FUEL = 45000;       // below this: radius 10
inline constexpr long STS_R20_FUEL = 65000;       // below this: radius 20
inline constexpr int STS_R10 = 10, STS_R20 = 20;
inline constexpr long TD_MIN_FUEL = 12000;        // no travel dash below this
inline constexpr int TD_PLAIN_WALK = 4;           // a plain dasher dashes with this much walk left
inline constexpr int TD_COLLECT_WALK = 3;         // a collection dash pays from here (the dash and a step arrive this turn)
inline constexpr int TD_FOE_R = 10;               // a visible foe this near keeps the dash for the escape
inline constexpr float TD_COLLECT_HP = 0.5f;      // a collection dash with a foe near needs this share of health
inline constexpr int ESC_WIN = 6;                 // safe tiles are looked for this far out
inline constexpr int ESC_SEARCH = 14;             // search radius of an escape walk
inline constexpr long ESC_MIN_FUEL = 30000;       // below this: the cheap step away only
inline constexpr long ESC_AWAY_FUEL = 15000; // below this: not even the cheap step away
inline constexpr long ESC_RALLY_FUEL = 40000;     // escape_toward falls back to escape below this
inline constexpr long RE_NEAR_FUEL = 45000;       // ring_escape: a short search at or below this
inline constexpr int RE_NEAR_SEARCH = 12;
inline constexpr long EP9_MIN_FUEL = 60000;
inline constexpr int EP9_FIELD_R = 18; // Bounds walks EP9_LONGER steps longer than the shortest.
inline constexpr int EP9_LONGER = 4;
inline constexpr float EP9_STEP_SHARE = 50.0f;    // one step weight = max HP / this
inline constexpr float EP9_SAVE_SHARE = 25.0f;    // the walk must save max HP / this
inline constexpr float RETREAT_DANGER = 12.0f;    // per tile inside a reach (plus margin)
inline constexpr float RETREAT_CAMP_DIV = 15.0f;  // camp threat / this
inline constexpr float RETREAT_SCALE = 8.0f;      // float score to the int candidate score
inline constexpr int UNPARK_EVERY = 3;            // one try per this many rounds (a try can cost ~8k on a big map)
inline constexpr int UNPARK_TESTS = 3;            // best candidates tested (each test reads 16 dash landings, ~2k)
inline constexpr int CORRIDOR_OPEN = 2;           // open neighbours of a corridor tile
}

// ======== Shared state and board helpers ======== bbany(b) tests 8 words per step (four v128 loads OR-ed, one any_true): the same
// answer as a word-by-word test.
NOVA_INLINE bool bbany_simd_move(const bitboard& b)
{
	std::int32_t z = 0; // the host's test (~25 + 1 a chunk) unless it errs
	if (cambc::detail::sdk_Bitboard_IsZero(b.ptr(), &z) == 0)
		return z == 0;
	const std::uint64_t* w = b.ptr();
	const int n = G.ch * G.stride;
	int i = 0;
	for (; i + 8 <= n; i += 8)
		if (wasm_v128_any_true(wasm_v128_or(wasm_v128_or(wasm_v128_load(w + i), wasm_v128_load(w + i + 2)),
										   wasm_v128_or(wasm_v128_load(w + i + 4), wasm_v128_load(w + i + 6)))))
			return true;
	for (; i < n; ++i)
		if (w[i])
			return true;
	return false;
}

namespace {
std::vector<std::unique_ptr<distance_field>> gfields;     // per group, camps blocked except own
int gf_n = 0; // static_cast<std::size_t>(gf_n), set beside its only resize()s.
std::vector<std::unique_ptr<distance_field>> gfields_open; // per group, camps passable (gated groups)
std::unique_ptr<distance_field> hfield;
std::vector<vec2> refused; // tiles that refused a move this turn (hidden units)
vec2 rfk_tile[4]; // Tiles an unseen occupant refused, kept for my next turn.
int rfk_until[4] = { -1, -1, -1, -1 };
vec2 trz_tile[2]; // Refused tiles that held a visible teleport reservation.
int trz_until[2] = { -1, -1 };
bitboard dyn_walls;
int dyn_round = -1;
bool dyn_valid = false;
bitboard known_open; // Camp tiles seen free (dead ring camps), walkable while out of sight.
vec2 last_pos{ -1, -1 };
vec2 prev_pos{ -1, -1 };
int prev_round = -1000; // The round prev_pos was set.
bitboard avoid_bb; // Reach of the awake attacking camps while an AvoidCampReach guard is active.
bool avoid_on = false;
bool avoid_foe = false; // The active zone is a foe guard's (camp guards add to it).
int td_need = 0; // Minimum walk left for a travel dash this turn (a dash route needs the dash on arrival).
int td_alive = 0, td_round = -1; // Travel dashes and alive turns (log summary).
int cd_mode = 0; // Collection dash mode of this walk (0 travel only, 1 toward a camp I tank, 2 toward a capture or an altar).

// Awake attacking camps seen lately that are out of sight now (behind a bush or a wall): they keep hitting the nearest
// champion in their reach until they fall asleep, so they still count as danger.
struct AwakeMem
{
	int ci;
	int round;
};
std::vector<AwakeMem> awake_mem;
// camp_threat's awake attackers, built once per state (W.round and ct_ver, which every awake_mem change bumps; W's bodies and camps
// change only in perceive, with the round): the visible awake attackers in W.camps order, then the remembered ones in awake_mem
// order, each with the distance of the nearest other body (dmin) and of the nearest body that takes camp ties (dtie). A camp hits p
// unless another body is nearer (d > dmin) or ties and goes first (d == dtie; any tie-taker nearer than d is already counted by
// dmin), so camp_threat adds the same strengths as a per-call scan of every camp in sight and every body (dozens of each beside a
// wolf pack). The body distances are computed on first need (only camps that reach a queried tile need them: dozens of awake wolves
// times six bodies cost 20-30k a turn). Queries within CT_NEAR of where the list was built scan only the camps that can reach that
// far (Chebyshev triangle inequality), and each (tile, ignored group) is answered once per state (flee turns ask the same 8
// neighbours 3-4 times).
struct CtEntry
{
	vec2 pos;
	int reach;
	float str;
	int group;
	int dmin;
	int dtie; // dmin < 0: not computed yet
};
std::vector<CtEntry> ct_list;
std::vector<std::int32_t> ct_near; // Indices into ct_list, in order: camps within reach + CT_NEAR of ct_me.
std::vector<std::int32_t> ct_near1; // the same within reach + 1 (queries on my tile and its neighbours)
constexpr int CT_NEAR = 3;
vec2 ct_me{ -1, -1 };
int ct_round = -1, ct_built = -1, ct_ver = 0, ct_stamp = 0;
int ct_ps = 0; // fg::pstamp at the last camp_threat_build.
struct CtMemo
{
	vec2 p;
	int ig;
	int stamp;
	float v;
};
std::array<CtMemo, 64> ct_memo{};
} // namespace
vec2 pfa_prev_pos() { return prev_pos; }
int pfa_prev_round() { return prev_round; }
} // namespace nova::mv
