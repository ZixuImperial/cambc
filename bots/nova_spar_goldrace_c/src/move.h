// Pathing with SDK distance fields (cached per target), safe stepping and short dynamic searches.
#pragma once
#include "common.h"
#include "world.h"

namespace nova::mv {

// Free to stand on now: passable terrain, no visible champion, no visible living camp, not a tile that refused us.
bool free_tile(vec2 p);
// Every tile that is not free now (the mask behind free_tile), for whole-board operations.
const bitboard& blocked();

// Strength of the awake camps that would hit me at round start if I ended my turn on p
// (I am the nearest champion in their reach). Camps of `ignore_group` are skipped.
float camp_threat(vec2 p, int ignore_group = -1);
// CIB bit 8: an awake camp in reach ties me with the body at q (same distance) and no body is nearer.
bool camp_tie_with(vec2 q);

// Path field to a group: every camp tile blocked except the group's own. nullptr when unaffordable this turn.
const distance_field* group_field(int gi);
// The group's field if it is already computed (no work), with the camps-passable fallback when I am cut off.
const distance_field* group_field_ready(int gi);
const distance_field* group_field_build(int gi, long reserve); // Build the group's walk field now if affordable.
// dfget(*group_field_ready(gi), W.me.pos), or UNREACH without a field (one read when the group field reaches me).
std::uint16_t group_dist_here(int gi);
std::uint16_t field_nb(const distance_field& f, vec2 p);
// Walk from p to group gi's camps from its built field (no work); -1 unknown, FP_NOWALK no walk.
constexpr int FP_NOWALK = 999;
int group_walk_at(int gi, vec2 p);
// The group's cached field (camps blocked except its own) as built, or nullptr (no work).
const distance_field* group_field_raw(int gi);
// Compute missing group fields, nearest groups first, while more than `reserve` fuel would remain. Returns the
// number built.
int build_fields(long reserve);
// Path field home (camps blocked). nullptr when unaffordable.
const distance_field* home_field();
const distance_field* home_field_cb(); // camps blocking; nullptr until built

// Downhill step on a field, avoiding camp danger when there is a choice. True if moved. Dashers also dash 2 tiles down the field
// first when the trip is long and no enemy is in sight (travel dash).
bool step_field(const distance_field& f, int ignore_group = -1);
// This turn's travel dashes need at least `steps` of walk left (a dash route needs the dash at a launch tile: it must be off
// cooldown on arrival). Reset every turn.
void travel_dash_need(int steps);
bool swd_dash(const distance_field& f, int gi); // SWD bit 2: the plain travel dash down a caller's field
// The best thin-hole skip from me toward field f (walk to launch a, dash to t, walk on), as rounds to arrive (cooldown wait
// included), or UNREACH when none saves HOLE_SHORT_GAIN over the walk or a foe is near. Callers check the flag. rad: launch tiles
// within this Chebyshev distance of me (0: the default window).
int thin_hole_plan(const distance_field& f, int ignore_group, vec2& a, vec2& t, int rad = 0);
// Bit 1: spawn_crystal_start skipped the crystal for field f: this body's walks on f take the skip (bit 2 takes it on every field).
void thin_hole_skip_crystal_set(const distance_field* f, vec2 a);
// Landing kits (Heart) travel-dash from TDX_HOR_NEED tiles left (the landing must still hit no camp). Slots after [2] have no reader
// left.
#define TRAVEL_DASH 1
#define TDX_HOR_NEED 8
#define TDX_FOE_R 12
#define TDX_FOE_AGE 4
inline constexpr int TRAVEL_DASH_TAB[5] = { 0x54445836, TRAVEL_DASH, TDX_HOR_NEED, TDX_FOE_R, TDX_FOE_AGE };
// The walks until the next call (or the turn's end) are collection walks: 1 = toward a camp I tank, 2 = toward a capture region or
// an altar. step_to_set and step_field then dash when 3+ tiles remain, landing out of awake camps' and visible foes' reach (foes in
// sight: only above half health). 0 = travel dashes only.
void collect_dash(int mode);
void collect_dash_only(bool on); // CB3 bit 8192 VFD: step_to_set may dash with the walk spent (no walk follows)
void fxr_entry_resets();          // FXR bits 1/2: hand-set toggles an unwound call left set
// One step that reduces the Chebyshev distance to target (no search; walls can trap it). True if moved.
bool step_greedy(vec2 target, int ignore_group = -1);
// Greedy step toward the nearest tile of a set (no search). True if moved.
bool step_greedy_set(const bitboard& goals, int ignore_group = -1);
// Step toward the nearest goal tile using a short search with visible units blocked. True if moved.
bool step_to_set(const bitboard& goals, int max_search = 40, int ignore_group = -1);
// Step toward a tile until within `stop` (Chebyshev). True if moved.
bool step_to(vec2 target, int stop, int max_search = 40, int ignore_group = -1);
// Step that maximises the distance from the given points (ties: lower camp threat). True if moved.
bool step_away(const std::vector<vec2>& from, int min_gain = 1);
// Move to an adjacent tile; false (allowance kept) when it was refused.
bool try_move(vec2 dest);
// A visible teleport-crystal reservation blocks its landing tile for the 3-turn channel, but perceive's occupancy
// (champion_tiles_into) leaves it out, so a body would re-try the same refused step every turn. Bit 1: a refused step or dash
// landing on a tile I see with no unit, wall or camp on it (a reservation; cxe has no has_teleport import, so no engine call) stays
// blocked on my next TRZ_AGE rounds. Runtime data flag, read first; 0 = off.
#define TRZ_BITS 1
#define TRZ_AGE 2
inline constexpr int TRZ_TAB[3] = { 0x54525A31, TRZ_BITS, TRZ_AGE };
void note_teleport_reservation(vec2 p);
extern vec2 bsh_tile; // The tile of the refused step that set bsh_hold_r.
extern int bsh_hold_r; // The round a refused step revealed a foe; steps wait for the re-read.
void bush_hold_release();
// The occupancy boards changed mid-turn: rebuild the move mask at its next read (caller reads the flag).
void occ_changed();
bool foe_guarded(vec2 p); // p lies in an active AvoidFoeReach zone.

// Threat for escapes: a position and the reach to stay out of.
struct Threat
{
	vec2 pos;
	int reach;
};
// retreat_step rates a rally by WALK distance (one bounded host field from the rally tile, once per round) instead of Chebyshev, so
// a flee toward a mate across holes or walls does not walk into a pocket. 0 = Chebyshev.
#define FRW_BITS 1
#define FRW_R 24 // Field radius (steps); beyond it a tile reads FRW_R + 1.
inline constexpr int FRW_TAB[4] = { 0x46525731, FRW_BITS, FRW_R, 0x31575246 };
#define PX_LIMIT 24 // tiles the true walk looks
int safe_tile_walk_steps(const std::vector<Threat>& threats); // True walk out of every listed and awake reach; 99 = no way within PX_LIMIT.
bool escape_to_safe_tile(const std::vector<Threat>& threats); // one step along it; true if moved
// Shortest way to a tile outside every threat's reach (falls back to step_away). True if moved.
bool escape(const std::vector<Threat>& threats);
// escape() to a safe tile no farther (Chebyshev) from `rally` than I am now; plain escape() if none.
bool escape_toward(const std::vector<Threat>& threats, vec2 rally);
// A carrier with >= FARM_RICH_RICH gems rallies on home (walk), not on the nearest ally in the fight.
#define FARM_RICH_RICH 50
#define FARM_RICH_RICH_ON() (W.me.gems >= FARM_RICH_RICH)
#define RE_MIN_CAMPS 4 // the ring signature (02the-pack: 14-31 in reach); 2 fired on 74 of 105 scan maps
#define RE_WIN 12
#define RE_SEARCH 20
#define RE_FUEL_MIN 25000 // ring_escape: no search below this (a 12-step search below 45k)
#define RE_FUEL_EARLY 40000 // the turn-start escape needs this much fuel left
#define MY_FUEL 30000
#define EOX_ROUNDS 8
#define EOX_FOE 6
extern bool eox_escaping; // Set inside escape()/escape_toward().
#define RE_DOOM_R 3 // the turn-start escape also after an acting turn when 3 more rounds of that HP loss kill me
bool ring_escape();
// Awake camps (not of group skip_group) whose reach covers me; str = their summed strength.
int ring_in(int skip_group, float& str);
// Steps needed to get out of every threat's reach from p (0 if already out).
int escape_steps(const std::vector<Threat>& threats, vec2 p);

// True if ally/enemy body b would take a camp's hit instead of me at equal distance (turn order).
bool takes_tie(const Body& b);
// HP tier with hysteresis, my base priority this round, a slot's priority at the next camp phase.
int hp_order_tier(float frac, int t0);
int turn_order_base();
int tie_prio(int s);
void awake_mem_threats(vec2 p, std::vector<Threat>& th);
bool awake_known(int ci); // Camp ci is in the remembered-awake list camp_threat reads.

// Visible (or recently seen) awake attacking camps within `radius` of me.
std::vector<Threat> camp_threats_near(int radius);
// Every own spawn tile lies inside an awake attacking camp's reach (the AvoidCampReach zone).
bool spawn_in_camp_reach();
// True if p lies within `margin` tiles of some threat's reach.
bool in_threat(const std::vector<Threat>& threats, vec2 p, int margin = 0);
// One retreat step: out of the threats' reach (plus a margin), then toward home (or toward `rally`); never back to
// the previous tile. True if moved.
bool retreat_step(const std::vector<Threat>& threats, int margin = 2, vec2 rally = vec2{ -1, -1 });
// Walking distance home from p (static field, camps passable), or a Chebyshev estimate.
int home_steps(vec2 p);
// A camp that may be awake out of sight (unexplained damage near it): treat it as awake for a few rounds.
void note_awake(int ci);
// Camp tiles known free (a ring breach seen open), walkable while out of sight.
void avoid_tile(vec2 p); // Blocked for the rest of this turn.
void refuse_landing(vec2 p); // A refused cast landing, this turn and next.
int refused_landings(); // Landings refused so far (a counter).
void set_known_open(const bitboard& b);
// While a guard is alive, move_best never steps into, and step_to_set never paths through, the reach of an awake attacking camp
// (every one, whoever is nearest to it). It is active only when I stand outside all of them: getting out of a reach is escape's job.
// A low-health retreat that steps back into the reach it just left would die there (a step out, then go_home's homeward path back
// in, A-B-A until dead).
struct AvoidCampReach
{
	explicit AvoidCampReach(bool on = true);
	~AvoidCampReach();
	AvoidCampReach(const AvoidCampReach&) = delete;
	AvoidCampReach& operator=(const AvoidCampReach&) = delete;
	bool active = false; // true: this guard set the zone (I am outside every awake camp's reach, and one is near)
	bool merged = false; // Added to a foe guard's zone (restored on exit).
	std::unique_ptr<bitboard> prev; // Allocated only when merged (a guard is built on every walk, mostly off).
};

// While I stand outside every given foe reach (tile, distance), steps and paths keep out of them; camp guards opened inside add the
// camps' reach to the zone.
// BBM MF3: while alive, steps and paths ignore an active foe guard's zone (a game-ending deny walk must reach the channeler).
struct SuspendFoeGuard
{
	explicit SuspendFoeGuard(bool on);
	~SuspendFoeGuard();
	SuspendFoeGuard(const SuspendFoeGuard&) = delete;
	SuspendFoeGuard& operator=(const SuspendFoeGuard&) = delete;
	bool active = false;
};
struct AvoidFoeReach
{
	AvoidFoeReach(const std::vector<std::pair<vec2, int>>& foes, bool on);
	~AvoidFoeReach();
	AvoidFoeReach(const AvoidFoeReach&) = delete;
	AvoidFoeReach& operator=(const AvoidFoeReach&) = delete;
	bool active = false;
};

// p is a dash launch tile between the walkable home area and dash-only ground: one legal dash from p lands on a
// standable tile on the other side (out of the home area, or back into it). 16 tile tests.
bool launch_tile(vec2 p);
// Standable neighbours of p (terrain, camp tiles excluded): 2 or fewer is a 1-wide corridor or a dead end.
int open_neighbour_count(vec2 p);
// Step off a launch tile (or out of a corridor), to a free neighbour that is neither, homeward first. True if moved.
bool unpark();

// Turn bookkeeping: reset per-turn state at the start of a turn.
void begin_turn();

} // namespace nova::mv
