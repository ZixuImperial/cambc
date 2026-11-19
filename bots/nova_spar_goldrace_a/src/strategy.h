#pragma once
// strategy.h: whole-game strategies. A strategy is a Policy: a small struct of knobs and optional functions, read by the shared code
// at a few decision points. Its fields default to "no change", and BASE is all defaults, so the shared code stays the single source
// of normal play. TO ADD A STRATEGY: (1) add its name to enum Mode, before NMODES; (2) create strategy_NAME.cc defining its Policy,
// copying strategy_altar.cc; (3) add it to strategy_registry.cc and to the single compiled file (nova_all.cpp), after the other
// strategy_*.cc. To test it set STRAT_FORCE to its Mode. It is picked in real games only when it defines select_score. DECISION
// POINTS a Policy can change (to add one: a field here, defaulting to no change, read at the decision): select_score draft: which
// strategy this game plays. The highest score above 0 wins, else BASE. Draft-time map features only (no map identity, no enemy
// picks); pick_bias draft: added to a champion's pick value; item_plan shop: changes to the build (econ_items.cc upitm_post);
// gem_value, gold_value target choice: x the gems and gold of a group (econ_value.cc); engage_bias, flee_bias combat: added to the
// engage and flee bars (combat_assess_stance.cc). The strategy can change during a game through the Plan below (phases by round,
// rules by score); every body works out the same answer. STRATEGY: one whole-game plan per game, switching per map type based on map
// features. The draft chooses it from map features (never map identity) and writes it to draft-memory byte 15; every champion reads
// it at setup (plan_*.cc decode_memory). Strategy code branches on strat::mode() at run time, so one build carries every strategy.
// BASE is the plain default behaviour. ORCHESTRATION: the draft (about 8M spare fuel on its first turn) may hand over a plan instead
// of one mode, in draft-memory bytes 768-831 (free: group and altar data end by byte 736, the zone block starts at 832): - a
// schedule: up to MAX_PHASES phases (mode, last round); - score rules: up to MAX_RULES (mode, lead or deficit of at least `thr`
// submitted gems, from round `min_round`), which override the schedule while they hold (both teams' submitted gems are public, so
// every champion agrees); - NPARAM parameter bytes for the strategies (e.g. precomputed target groups). Every champion evaluates the
// plan from the round number and the public score, so the team switches together without messages.
#include <cstddef>
#include <cstdint>
#include <vector>
namespace nova { struct Kit; }
namespace nova::mapfeat { struct Feats; }
#define STRAT_FORCE -1 // -1 = the draft's choice; 0..NMODES-1 = that strategy on every map (strategy-locked test builds).
namespace nova::strat {
enum Mode : std::uint8_t
{
	BASE = 0, // The default strategy.
	CENTER = 1, // take and hold the middle's heavy groups with a crew or pack
	ECON = 2,   // farm our side, bank on tempo, contest only what is free
	SIEGE = 3,  // team sieges of bosses and the heaviest groups
	RAID = 4,   // pressure in their half: pick-offs and denial (e.g. pressing a lead)
	ALTAR = 5,  // altar control: locks, banking behind them, denying theirs
	NMODES = 6
};
constexpr std::size_t BLOCK_AT = 768, BLOCK_END = 832;
constexpr int MAX_PHASES = 4, MAX_RULES = 2, NPARAM = 16;
struct Phase
{
	Mode mode = BASE;
	std::uint16_t until = 0xFFFF; // last round of the phase (0xFFFF = to the end)
};
enum RuleKind : std::uint8_t
{
	R_NONE = 0,
	R_LEAD = 1,    // our submitted gems minus theirs >= thr
	R_DEFICIT = 2  // their submitted gems minus ours >= thr
};
struct Rule
{
	Mode mode = BASE;
	RuleKind kind = R_NONE;
	std::uint16_t thr = 0;       // gems (stored /4, up to 1020)
	std::uint16_t min_round = 0; // from this round (stored /8, up to 2040)
};
struct Plan
{
	int n = 0; // phases in use (0 = no schedule: the single mode of byte 15)
	Phase ph[MAX_PHASES];
	int nr = 0; // score rules in use
	Rule rule[MAX_RULES];
	std::uint8_t param[NPARAM]{}; // strategy parameters, meaning set by the strategy that uses them
};

// What a strategy changes. Every default means "as the shared code".
struct Policy
{
	const char* name = "";
	float (*select_score)(const mapfeat::Feats&) = nullptr;
	float (*pick_bias)(int champion) = nullptr;
	void (*item_plan)(const Kit& k, int stat, bool healer) = nullptr;
	float gem_value = 1.0f, gold_value = 1.0f;
	float engage_bias = 0.0f, flee_bias = 0.0f;
};
extern const Policy POLICY_BASE;
extern const Policy* const POLICIES[NMODES]; // Defined in strategy_registry.cc.
extern const Policy* active_policy;
inline const Policy& policy_of(Mode m) { return *POLICIES[m]; }
inline const Policy& policy() { return *active_policy; } // this turn's strategy (set by begin_turn)

void begin_turn();             // once at the top of every turn: works out this turn's strategy
Mode mode(); // This game's strategy now: STRAT_FORCE, else an active score rule, else the schedule at the current round.
void set_mode(std::uint8_t m); // From draft-memory byte 15 (out-of-range values give BASE).
void set_block(const std::uint8_t* b, std::size_t n); // From draft-memory bytes BLOCK_AT..BLOCK_END-1 (ignored if invalid).

void choose(const mapfeat::Feats& f); // first draft turn, once the map features exist
std::uint8_t draft_choice(); // The mode for byte 15 (STRAT_FORCE, else the first phase of the plan, else the single choice).
void write_block(std::vector<std::uint8_t>& mem); // Grows mem to BLOCK_END if needed and writes the plan (no-op without one).
float pick_bias(Mode m, int champion); // additive pick-score bias of a strategy (0 until a strategy defines one)
} // namespace nova::strat
