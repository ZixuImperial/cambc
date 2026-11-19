// econ_value_helpers.cc: Small valuation helpers shared by value, rate and choice.
#include "econ_internal.h"
namespace nova::econ {
namespace {

std::vector<std::uint16_t> travel;
int travel_round = -1000;
vec2 travel_from{ -1, -1 };
struct CPlan
{
	vec2 L{ -1, -1 }, T{ -1, -1 };
	int cost = UNREACH;
	bool done = false;
	int retry = -1000;
};
std::vector<CPlan> cplans;
int crystal_count = -1, crystal_checked = -1000;
vec2 fL_at{ -1, -1 };
struct SCRoute
{
	int cost = UNREACH; // spawn -> L, the hop (+4), T -> target; UNREACH when no route saves SC_CRY_MIN
	int off = 0;        // walk from our spawn to L
	int save = 0; // rounds it saves over the spawn's walk (written only with RWK_TAB on)
	vec2 L{ -1, -1 }, T{ -1, -1 };
	bool done = false;
};
struct SCTrip
{
	bool on = false, used = false;
	int kind = 0; // 0: group gi, 1: the bank
	int gi = -1;
	vec2 L{ -1, -1 }, T{ -1, -1 };
	int rest = 0;            // the hop (+4) and the walk from T to the target
	int last = -1, until = -1;
};
std::vector<SCRoute> sc_grp;
SCRoute sc_bank_r;
const distance_field* sc_bank_f = nullptr;
std::vector<std::uint16_t> sc_buf, sc_win; // linear w x h: the spawn field (camp tiles unreachable), then window minima
bool rh_any = false; // a route on this map saves RWK_BIG+ rounds (no recall-hop rule does any work before that)
int sc_skip_until = -1;
int rhl_rec = -1, rhl_until = -1; // my last recall-hop recall with no trip since; the block's end
// the chain of full-HP, foe-free recall starts from one spot.
vec2 rcg_pos{ -1, -1 };
int rcg_round = -1000, rcg_last = -1000, rcg_gems = -1, rcg_n = 0, rcg_shop = -1000;
SCTrip SC;
vec2 sc_fl_at{ -1, -1 };                 // ... for this landing
// spawn_crystal_start's refusal tests for group gi's route r from some spawn tile (field f; dasher: a known route). Both callees are called
// through volatile pointers: a new direct call site can change their inlining into compute_travel's fuel-counted dash window, which
// changes the fuel counted there.
static const distance_field* (*volatile rhl_gfr)(int) = mv::group_field_ready;
static int (*volatile rhl_rlen)(int, vec2) = dn::route_len;
std::vector<std::uint16_t> gdn_trav; // compute_travel's neighbour reads on a camp tile
extern int ht_state;
static int starved_map_bits();
#define EXPV (EXP_V | starved_map_bits())
int gate_signal = -1000; // round the enemy last tributed (on a gated map that means the gate is open)
int ring_signal = -1000; // our last tribute (an enemy tribute says nothing about a gap on our side)
// A dasher banks over holes when no altar is walkable (dash routes, built in spare fuel).
// Set once per turn in observe(): bankable() sits in the hot valuation loops and must stay as cheap as before.
bool dash_bank_flag = false;
// a breach of the altar ring is open: one seen free, or a tribute (ours or theirs) in the last 60 rounds.
bool ring_gap = false;
bitboard ring_open_bb;       // breach tiles seen free
distance_field f_ring;       // to the altar neighbours with the open breaches walkable
bool has_ring_field = false, ring_dirty = false;
bool nwc_bank_flag = false; // set once per turn in update_dash_bank, read by bankable()
// a body without a dash, no altar walkable from our spawn, no gate, no ring: the altar's own walk (f_altar) is the bank field.
static inline bool nwc_map() { return !M.any_altar && M.has_altar && M.gate_groups.empty() && !M.ring && !has_ring_field && !dn::dasher(); } // a dasher keeps its dash route
// Altar ring breach: while no breach is seen open, one body hits the breach camp nearest our spawn from the outside tile in its
// range that the fewest ring camps reach, never another ring camp (damage wakes the whole group and opens nothing). It leaves below
// RING_LEAVE (camps do not heal) and returns at 90%. From RING_START, or with 30+ gems. Ranged bodies breach when the team has one;
// the breacher claims the ring group, and the lowest slot claiming it keeps it.
bool ring_breaching = false, ring_resting = false;
int ring_claim = -1;
int ring_last = -1000, ring_prog_round = -1000, ring_prog_d = BIG, ring_pause_until = -1, ring_idle = 0;
vec2 ring_prog_tile{ -1, -1 }; // the tile the ring progress is measured to
vec2 f_breach_at{ -1, -1 };
// Ring entry: outside the enclosure, never walk into the reach of an awake ring camp (wait, or step back home).
int ring_wait_since = -1000, ring_wait_last = -1000, ring_bank_off = -1000;
// Tributed totals every 50 rounds; a low-score game is one where neither team's total plus its rate over the last 200 rounds reaches
// 1000 by r2000 (from round 1000).
std::vector<std::array<int, 3>> eg_hist;
// Gold in gem units. Early gold buys items that speed up every later clear (and wins fights), so it is worth a
// third of a gem until round 400; late in the game it only breaks ties.
// Share of the map's gems outside monolith and golem groups (computed once).
float open_gem_share = 1.0f;
// the map has a big group at all (static, once): on the other maps the big-group checks are skipped and cost no fuel.
int sg_any_v = -1;
std::vector<signed char> gn_band; // per group: a walkable, non-siege gem group inside the contested band
float rf_value = 0, rf_time = 1, rf_pen = 1; // parts of the last rate_for
// Enemy count near a group's anchor from recent sightings (own vision, ward, teammates' reports), cached for two
// rounds (target choice asks for many groups, and sightings age slowly).
std::vector<float> danger_cache;
std::vector<int> danger_round;
// the compactness weight k (map features only, the same on every body), and its value this round.
float crew_k = 0;
// The longest respawn wait a group is worth: own-side elk groups (full at contest 0.45, gone at 0.55) get up to a set number of
// extra rounds in the mode. How long to stay around a camp is map specific, and waiting should be as short as possible: the wait cap
// is the map's typical gap between neighbouring walkable groups (median walk-ish distance, Chebyshev x 4/3, to the nearest other
// group), 3-15 rounds. Where something else is close, never wait; where the next group is far, a short wait beats the walk. WAIT_MAX
// when the map cap is off.
int wm_cap = -1; // the map's cap once wait_cap_compute() has finished
// D while the team is stalled, else -1. Per round (my view; every body reads the same tributed numbers).
int dlk_round = -1000, dlk_v = -1, dlk_dg = -2, dlk_hold = -1, dlk_hold_r = 0, dlk_th = -1, dlk_th_r = -100000;
int ir_start = -1000, ir_last = -1000; // the current run of no-target idle_move rounds
int ir_tgt = -1; // the group my last idle-recruit choice took
int ir_ok_round = -1000; // the round of ir_ok, the groups the idle branch rated with recruits
std::vector<int> ir_ok;
int blf_b = 0; // BLF_TAB[1] read once a turn (econ::observe), so the consumers below read no volatile
#define BLF_B(b) ((blf_b & (b)) != 0)
std::int64_t blf_n[6] = {}; // fire counts: [0] UNKNOWN discounts, [1] CLEARED discounts, [2] CLEARED expiries, [3] foe HP refills, [4] weights < 1, [5] spare
// Whole-team clear check (every body, best camp tank first, 3x HP margin), cached per group for 25 rounds: a group that even the
// whole team cannot clear is never a candidate. This keeps the crew estimates from eating the turn's fuel on walls of 16-18 golems
// before the feasible groups are reached.
std::vector<int> team_ok_round;
std::vector<signed char> team_ok;
int tf_est_round = -1, tf_est_n = 0; // team_feasible: fresh estimates this round
// Gates: groups that a walk from our spawn to group gi must cross (camp tiles block walking while alive), found by
// walking down the camps-passable home field from gi; only for groups unreachable with camps blocking. The walk is
// resumable (a few steps per turn: one step reads 8 field cells and costs ~0.5k fuel) and unknown gates count as open.
std::vector<std::array<int, 3>> gate_of;
std::vector<signed char> gate_done;
struct GateTrace
{
	int gi = -1, n = 0, round = -1000;
	vec2 p{ -1, -1 };
	std::uint16_t cur = UNREACH;
};
GateTrace GT;
// group_bounds computed with less work: bit-identical bounds, the same list order. - The per-call constants are read once
// (gold_weight_in_gems, bankable, sg_any, the crew weight, the gem need, the free-camp sightings, the back-zone gate) instead of
// once per group. - Static map data per group (the same expressions, evaluated once) sits in a table, rebuilt when its inputs change
// (the gate list or the ring, which the ring's deferred scan can extend; the analysis's last stage); until the group distances are
// final (draft memory, or that stage without it) each group's entry is filled on the spot. d_altar, set by the analysis after setup,
// is always read live. - reachable_target runs team_feasible's and gates' own code inline: the same tests in the same order, their
// fuel gates included, refreshes through team_feasible_refresh / gates_step. - The factor passes (free camp, back zone, territory)
// multiply each bound in the same order inside the one loop (they are pure); a factor of exactly 1 is skipped (x * 1.0f == x). No
// new fuel checks.
struct GBS
{
	float hp = 0, hp1 = 1, memb04 = 0, hp2m = 0, ck = -1, gems_f = 0, gold_f = 0, contest = 0;
	vec2 anchor{};
	std::uint16_t fl = 0;
};
enum : std::uint16_t
{
	GB_WALK = 1, GB_ZERO = 2, GB_RGK = 4, GB_SGB = 8, GB_CHAIN = 16, GB_GEMS = 32, GB_GATE = 64, GB_GN = 128, GB_OE = 256,
	GB_TERR = 512, GB_TERRD = 1024, GB_OPP = 2048, GB_SIEGE = 4096
};
std::vector<GBS> gbs_tab;
// The bounds loop of my own choice stops below TCF_GBFLOOR and resumes on the next turn on the same tile. The opening's bounds pass
// keeps its own place; opr_on is set only with the flag on, around the opening choice's call.
bool opr_on = false, opr_stop = false;
int opr_slot = -1, opr_sslot = -1, opr_gi = 0, opr_gi0 = 0, opr_round = -1000;
bool gbr_defer = false; // this turn's choice was deferred (target_turn keeps the target, no eval)
vec2 gbr_pos{ -1, -1 };
// Choice staging: on a big map (e.g. 51 groups) the travel, the bounds and their factors can take the turn's fuel before any
// candidate is rated (~27k left against the 32k floor on every turn), so after their first capture no body would choose a target
// again and all would stand still. A sorted list that no fuel was left to rate is kept, with its travel, and rated on the next turn
// from the same tile without recomputing either.
fg::Cost fg_pre; // choose_target from its start to the end of the bounds (travel, squad stick, bounds)
vec2 st_pos{ -1, -1 };
int nfl_n = -1, nfl_crew = 1, nfl_dng = 0;
float nfl_rb = 0, nfl_tn = 0, nfl_tg2 = 0, nfl_tg = 0, nfl_vn = 0, nfl_vg2 = 0;
// Free bodies that can join a crew I start: visible allies within 8 tiles with no claim, not channeling. Also the rounds running I
// have seen each mate in a recall (observe_unseen_mates), and the last such round.
std::array<int, 8> rcm_rc{}, rcm_rcr{ -9, -9, -9, -9, -9, -9, -9, -9 };
// First choice of the match: every body stands on its spawn and decides in the same few rounds, before any claim
// is visible. Each body simulates the choices of the bodies acting before it (best camp tanks first, base stats,
// spawn distances), so the team spreads over the map consistently without communication.
// Resumable: the simulation of each body is done whole (so every body reaches the same result) when the fuel left
// allows it, and continues on the next turn otherwise (returns -2 until it is finished).
struct Opening
{
	bool started = false;
	Claims cl{};
	std::array<bool, 8> done{};
	int i = 0;
	// The simulation of body TM.by_tank[i] in progress: its candidates, the next one to rate and the best so far.
	// It resumes on the next turn when the fuel runs low, so its result never depends on the fuel (every body
	// reaches the same choices) and no turn is suspended or goes over ~85k.
	bool sim = false;
	std::vector<std::pair<float, int>> cand;
	std::size_t k = 0;
	int best = -1, best_crew = 1, free = 0;
	float best_r = 0;
	int j = 0; // next body (tank order) of the join pass
};
Opening OP;
// Opening reserve is 40k instead of 30k, and each candidate also needs the costliest rating seen so far. Otherwise on a 100x100 map
// the turn that finished the simulation would then walk to the target and use abilities from ~30k, and be suspended at round 6 (both
// sides, once the planner's per-turn observe no longer runs first).
constexpr long OPENING_RESERVE = 40000; // fuel kept for the rest of the turn while the opening simulation runs
// decided once, from base stats and spawn walks, in the opening choice: every body reaches the same group and crew.
int vop_v = -1, vop_crew = 0, vop_n = 0;
std::array<std::uint8_t, 8> eval_claims{}; // claim bytes at my last evaluation
// Re-evaluate the target every 10 rounds, or sooner when the claims changed (a crew mate joined, someone took my group); keep it
// unless something is clearly better. A body fighting, capturing or waiting at its target for the crew stays committed. Prestep: the
// opening simulation resumes over turns for fuel (1.4 rounds per body on the spawn). Meanwhile take one cheap step toward the group
// I am most likely to get: my own simulation's best so far, else my best-bound group that no simulated body holds. Greedy (the
// group's field when built, else Chebyshev), never into a camp's reach, stopping outside the group's reach. The simulation keeps its
// spawn distances and base stats, so its result is the same on every body; the step only shortens my walk afterwards.
bool op_prestepped = false; // off the spawn while the opening simulation runs
// the plausible goals of the two guess stages, and the veto on a step that walks away from one of them.
static std::array<int, 4> om_sg{ { -1, -1, -1, -1 } }, om_op{ { -1, -1, -1, -1 } };
// the tile my last opening step left and its round; opb_first / opb_until: bit 1's first target.
static vec2 opb_prev{ -1, -1 };
static int opb_prev_r = -9, opb_first = -1, opb_until = -1;
// om_blind_step down host walk fields of the stored goals (call only with the bit set). Sidestep: the opening steps' fallback when
// every closer tile is held by a champion. val(n): the step's distance to its goal (-1 unusable), ok(n): the step's own tile tests
// (free of units), held(n): a champion stands there.
vec2 spw_prev{ -1, -1 };
// dc_v is D (or -1), set once by dom_commit_free_slot; everything below runs only in DOM-mode turns.
int dc_v = -1;
int dc_state = 0; // 0 undecided, 1 off, 2 on
// refresh_target<1> (v1): true when this turn keeps D as my target (1) or commits me to it (2).
static bool opn_dc = false; // dom_commit_turn asked before `opened`
// The gate group to siege on a map whose every altar is gated (-1: not such a map, or not decided yet). Static map data, decided
// once the map analysis is done: every body agrees.
int gt_v = -2;
} // namespace
} // namespace nova::econ
