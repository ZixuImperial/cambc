// econ_state.cc: Economy tunables, shared types and per-game state; the cached list of items I own.
#include "econ_internal.h"
namespace nova::econ {
// Modules of this file, in order (each owns one job; shared types, state and tunables come first):
//   Group memory: camp and group status memory, ownership, quiet tracking, group awake and living members
//   Team model: kit damage, member stats, team table, claims, crew size for a group
//   Clear estimate: time and damage to clear a group
//   Crystals: crystal plans, the spawn crystal route, buying and stepping, mid hops
//   Travel: walk cost to groups: gated, recall, stored travel, gate state
//   Ring: ring altar maps
//   Value: reward of a group in gems: weights, game phase, need
//   Rate: value per round, every modifier
//   Choice: bounds, best group, choose_target, join, filler
//   Opening: first pick, prestep and start walks
//   Dominant and late picks: dom commit, gated team, hoard and hold-group decisions
//   Re-choice: refresh_target
//   Focus: which camp to hit
//   Hole shortcut: dash shortcut fields
//   Approach: walk to the group, progress, crew present
//   Capture: who captures, recall off a capture, leave or hold
//   Tank and support: play at the group
//   Staging: near and respawn stage
//   Team ops: SG3
//   Target turn: walk, wait, engage
//   Items: build order and emblems
//   Threat sense: sense, threats, blacklists
//   Team comms: shared memory fields, foe and map posts
//   Observe: per-turn memory update and intel
//   Shop: buying at the shop
//   Bank: when and how to bank, wins, escorts, locks
//   Idle and side walks: idle moves, side scouts, camp-out, capture pay-in
//   Recall and heal: heal, shop and recall rules

// ======== Tunables: the named numbers of the economy, one block per family ========
namespace {
} // namespace

// ======== Shared types and state: what more than one module reads ========
int last_act = ACT_NONE;
int dbg_path = 0;
// team quiet tracker. qk_own: my own sight (ward too) or unseen hit; qk_mate: mates' last-seen reports in shared memory; qk_teamv:
// the team value on the channel (decoded or posted by me).
int qk_hit = -1000, qk_own = -1000, qk_mate = -1000, qk_teamv = -1000, qk_r = -1, qk_rbase = 0;
namespace {
std::vector<GroupMem> mem;
int fxp_exp_lo = -2147483647 - 1; // no GS_RESPAWN group has respawn_at below this
int cxl_lo = -2147483647 - 1; // every CLEARED group has max(seen, state_checked) + respawn >= this (seen and state_checked only rise)
#define CXL_NOTE(m) do { if (FUEL_CUTS_ON(FUEL_CUTS_BIT_CXL) && (m).status != GS_CLEARED) cxl_lo = -2147483647 - 1; } while (0) // a new CLEARED group: full pass next
// gmem_size(mem) kept as an int beside the two assign()s of mem, so the size is not recomputed as (end - begin) / sizeof(GroupMem)
// on every read; gmem_size takes only this vector's type, so a local `mem` of another type does not compile.
int mem_n = 0;
// The last round of the game (GameRules.md).
constexpr int GAME_END = 2000;
constexpr float GAME_END_F = 2000.0f;
// The group this body works on. Crews form per target: every body that claims a group in shared memory works on it, the best camp
// tank of those present tanks, one of them captures and the others move on.
struct Task
{
	int target = -1;
	int chosen = -1000;
	float rate = 0;
	int crew = 1;             // bodies the choice assumed (me included)
	bool engaged = false;     // the target is awake and we fight it
	int wait_since = -1;      // round we started waiting near the target
	bool capturing = false;
	int cap_start = 0;
	int cap_on = -1;          // first round on the region during this capture
	std::uint32_t cap_gems = 0, cap_gold = 0;
	int eval_round = -1000;
	int best_d = BIG;         // closest approach to the target so far
	bool best_path = false; // best_d is a path distance (walk field, dash route, hole shortcut), not Chebyshev
	int progress = 0;         // round of the last approach progress
	int tracked = -1000;      // last round we walked toward the target
	int focus = -1;           // camp index we are hitting
	int bench_until = -1000;  // handed the camps to a healthier crew mate: support only until then
	bool self_tank = false;   // the better tank here did not start: I tank
	int filler_until = -1000; // a short task done while the main target respawns: keep it until then
	int filler_check = -1000; // last round we looked for such a task
	int bank_until = -1000;   // tribute the bag while the target respawns (until this round)
};
Task T;
int ci_adopt_g = -1; // the group Cassi is rating for adoption (rate_for lets her join Issac there)
bool opened = false; // the opening choice is made
bool sq_stick_pick = false; // the last choose_target followed a squad mate (refresh_target takes it at once)
// What this body felt recently, for recall safety: any damage (even into a shield) cancels a recall.
struct Sense
{
	float hp = -1, shield = 0;
	int hp_round = -10;
	int hurt = -1000;        // last round we lost health or shield
	int hurt_unseen = -1000; // ... with no visible attacker that could explain it
	int enemy_close = -1000; // last round a visible enemy could reach us within a recall channel
	bool recalling = false;
	int recall_round = -1000;
	int recall_cancel = -1000;
	vec2 cancel_pos{ -1, -1 };
};
Sense S;
std::vector<cambc::item_type> build;
bool build_ready = false;
// Visible living camp by camp index, through a per-turn index (W.camp_by_index is a linear search).
std::vector<std::int16_t> vis_idx;
std::size_t vis_n = 0;
// Each camp's spawn tile as (board word, bit mask) in the engine's 8x8-chunk layout, so a member's vision / occupancy test is one
// load and one AND instead of bbget's index arithmetic. Camps never move; rebuilt only if the camp list changes size. Same bits as
// bbget (direct layout: nova::G, verified in init_grid).
struct CampBit
{
	int k = 0;
	float hp = 0; // M.camps[i].hp (static spawn health)
	std::uint64_t m = 0;
};
// ---------------------------------------------------------------- items I own (cached)

struct Owned
{
	int checked = -1000;
	bool jungle = false, monster = false, home = false;
	bool treasure = false;
	int shards = 0;
	bool durab = false;
};
Owned own;
// One body's numbers for crew estimates.
struct Member
{
	float dps1 = 0, dps3 = 0, stuns = 0, heal = 0, shield = 0;
	float budget = 0; // HP it can spend holding camps (camp damage units)
	float budget_he = 0; // the same with the hit-size correction (heavy groups)
	float ret = 0; // retaliation per camp hit taken
	float chain = 0; // a kill-reset melee body's hit on camps (Vendetta: str x Monster), 0 for other kits
	float ko1_area = 0, ko1_land = 0; // area stuns (Ryth) / landing stuns (Heart) per 8 rounds (also in stuns)
	float ko1_cc = 0, ko1_ccp = 0; // cc-slot camp stuns a Prism's spell hold can keep (ko1_ccp: a spell Prism's; also in stuns)
	bool melee = false;
};
// The team as this body sees it, rebuilt once per turn: member numbers, claims and who is fighting.
struct TeamView
{
	int round = -1;
	bool base = false;             // members from base kit stats (opening: identical on every body)
	int n = 0;
	std::array<Member, 8> m{};
	std::array<int, 8> claim{};    // claimed group per slot (-1 none); my slot holds my current target
	std::array<bool, 8> busy{};    // fighting its claimed group right now
	std::array<int, 8> by_tank{};  // slots, best camp tank first
	// The healer while it follows a partner (its claims mirror the partner's; it joins crews as support only), its partner, and whether
	// it is with me (cached here: these are read in the hot crew loops).
	int sup = -1, partner = -1;
	bool sup_near = false;
};
TeamView TM;
int crew_epoch = 0; // crew_for's memo holds for this build of the team view
struct Crew
{
	// Copies by v128 moves (crew_for returns a Crew by value from its memo: a 92-byte memory.copy); the same bytes as the implicit
	// copy. Default construction is unchanged (all members 0).
	Crew() = default;
	Crew(const Crew& o);
	Crew& operator=(const Crew& o);
	float dps1 = 0, dps3 = 0;
	float stuns8 = 0, heal8 = 0, shield8 = 0;
	float ko1_area8 = 0, ko1_land8 = 0, ko1_cc8 = 0, ko1_ccp8 = 0; // Member's parts of stuns8
	float heal_first = 0; // the first body's heal, held back until a second body joins (it heals others only)
	float ret_tank = 0, ret_hold = 0; // retaliation per hit of the tank / of the other melee holders
	float chain = 0, chain_dps1 = 0; // the best kill-reset hit in the crew, and that body's own dps1
	int n = 0, n_melee = 0;
	std::array<float, 6> budget{}; // melee budgets, best first
	std::array<float, 6> budget_he{}; // the same members' corrected budgets (same order)
	float dps(int pack) const
	{
		if (pack <= 1)
			return dps1;
		// kit_dps is linear in the pack up to 4, so the line through dps1 and dps3 gives pack 4 too.
		return dps1 + (dps3 - dps1) * std::min(1.0f, static_cast<float>(pack - 1) / 2.0f);
	}
	// the same with a fractional pack (members that matter, weighted by their health).
	float dpsf(float pack) const
	{
		if (pack <= 1.0f)
			return dps1;
		return dps1 + (dps3 - dps1) * std::min(1.0f, (pack - 1.0f) / 2.0f);
	}
	// The healer following its partner adds damage, stuns and heals, but takes no capture share and holds no camp.
	void add_support(const Member& x)
	{
		dps1 += x.dps1;
		dps3 += x.dps3;
		stuns8 += x.stuns;
		ko1_area8 += x.ko1_area;
		ko1_land8 += x.ko1_land;
		ko1_cc8 += x.ko1_cc;
		ko1_ccp8 += x.ko1_ccp;
		heal8 += x.heal;
		heal8 += heal_first;
		heal_first = 0;
	}
	// Bodies are added best camp tank first: the first one tanks and counts its self-shield.
	void add(const Member& x)
	{
		dps1 += x.dps1;
		dps3 += x.dps3;
		stuns8 += x.stuns;
		ko1_area8 += x.ko1_area;
		ko1_land8 += x.ko1_land;
		ko1_cc8 += x.ko1_cc;
		ko1_ccp8 += x.ko1_ccp;
		if (n == 0)
			heal_first = x.heal;
		else
		{
			heal8 += x.heal + heal_first;
			heal_first = 0;
		}
		if (n == 0)
			shield8 += x.shield;
		if (n == 0)
			ret_tank += x.ret; // the tank takes the attackers' hits
		else if (x.melee)
			ret_hold += x.ret; // a melee crew mate holds one attacker of a pack
		if (x.chain > chain)
		{
			chain = x.chain;
			chain_dps1 = x.dps1;
		}
		if ((x.melee || n == 0) && n_melee < 6)
		{
			int i = n_melee++;
			while (i > 0 && budget[static_cast<std::size_t>(i - 1)] < x.budget)
			{
				budget[static_cast<std::size_t>(i)] = budget[static_cast<std::size_t>(i - 1)];
				budget_he[static_cast<std::size_t>(i)] = budget_he[static_cast<std::size_t>(i - 1)];
				--i;
			}
			budget[static_cast<std::size_t>(i)] = x.budget;
			budget_he[static_cast<std::size_t>(i)] = x.budget_he;
		}
		++n;
	}
};
inline Crew& Crew::operator=(const Crew& o)
{
	if (this != &o)
		vmove_n<sizeof(Crew)>(reinterpret_cast<unsigned char*>(this), reinterpret_cast<const unsigned char*>(&o));
	return *this;
}

using Claims = std::array<int, 8>;
struct ClearEst
{
	float t = 0, dmg = 0;
	bool feasible = false;
	float budget = 0; // the camp-damage budget the feasibility test used
};
static std::vector<std::int8_t> bgx_gn;
static std::vector<std::array<std::pair<float, float>, 16>> bgx_att; // the living attackers (hp, str), lowest hp first
// Clear time and camp damage for a crew: attackers die one by one (lowest HP first) while the living ones hit;
// stuns cancel hits of the strongest, heals and the tank's shield soak. Each melee body can hold one attacker; a
// single attacker can be handed over once to a second melee body.
inline int cxc_ctx = 0; // consumer class of the current estimate() call
int hdc_nu = 0, hdc_feas = 0, hdc_pmu[4] = { 0, 0, 0, 0 }, hdc_su[4] = { -1, -1, -1, -1 }; // the last hold-chance read: uncertain members, feasible subsets
} // namespace
} // namespace nova::econ
