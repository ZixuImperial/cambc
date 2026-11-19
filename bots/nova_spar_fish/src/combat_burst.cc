// combat_burst.cc: One-turn kill estimates.
#include "combat_internal.h"
namespace nova::combat {
namespace burst
{
namespace tune
{
inline constexpr int LB_RALLY_R = 12;              // a healthy mate within this draws my escape
inline constexpr float LB_RALLY_FRAC = 0.5f;       // a mate below this HP share draws nothing
inline constexpr float LB_GAP_WEIGHT = 100000.0f;  // an escape's score per tile from the rally: above any damage sum
inline constexpr std::size_t ED_FOES_ALL_SEEN = 6; // with this many foes in sight no unseen foe can shift a rank
}
namespace {
// lb_two is set only around lethal_burst_escape_tile's and lethal_burst_landing_bad's own sums, so every other lethal_burst_damage_sum caller reads the one-turn sum.
// lethal_burst_two_turn_hit: foe e's hit at d over its two turns before my next, reach_burst_test's term: stunned = one turn, cooldowns one on; in reach =
// foe_two_turn_damage; out of reach = a tile walked on turn 1, the hit on turn 2.
static bool lb_two = false;
// irb_* hold the last evaluation (diag copies read them).
int irb_round = -1, irb_n0 = -1, irb_nb = -1; // the round of the last flip; foes reaching me here, at its tile (-1: none)
bool irb_fired = false;
float irb_s1 = 0.0f, irb_s2 = 0.0f;
bool irb_stun = false;
bool irb_ed = false; // true when the last test fired only because a foe has double turns (diag copies read it)
float irb_sed = 0.0f; // the part of irb_s2 that came from double turns over the one-turn-per-foe sum
// The turn-order ranks this round and next: each priority read once. ra, ra2: my rank among us; pb, pb2: the foes' priorities.
struct EdRanks
{
	bool my_start = false;
	int ra = 0, ra2 = 0;
	std::size_t m = 0;
	std::array<int, 12> pb, pb2; // rows below m are filled, the rest never read
	__attribute__((always_inline)) void foe_rank(std::size_t x, int& rb, int& rb2) const
	{
		rb = 0;
		rb2 = 0;
		for (std::size_t y = 0; y < m; ++y)
		{
			rb += pb[y] > pb[x] ? 1 : 0;
			rb2 += pb2[y] > pb2[x] ? 1 : 0;
		}
	}
	bool still_to_act(int rb) const { return my_start ? rb >= ra : rb > ra; }
	bool first_next_round(int rb2) const { return my_start ? rb2 <= ra2 : rb2 < ra2; }
	int turns_if_still() const { return 1 + ((my_start || ra2 >= 1) ? 1 : 0); }
};
// Never in a FIGHT and never on my spawn; only a fleeing body or one below the low-HP line. Fuel: one sum per such turn unless it
// reads lethal. The most turns foe e can take before my next turn (unseen foes' rank shifts the worst way); filled once per turn on
// the first call (only a stunned foe asks); a handle not in the turn's list counts 2. irb_nnstd[x] = a still-to-act foe's
// standing-order count (1 + before me next round by its current ordering value); irt_*: per foe handle, priority changes seen on its
// danger rounds (stunned or < 45% HP at the read before).
static std::array<int, 12> irb_nnstd{};
static std::array<std::uint32_t, 12> irt_h{};
static std::array<int, 12> irt_r{}, irt_v{}, irt_dt{}, irt_ch{};
static std::array<bool, 12> irt_dg{};
// This turn's table: the near foes' handles and turn counts.
struct IrbTurnTab
{
	int at_round = -1;
	std::uint32_t at_me = 0;
	std::array<int, 12> nn{};
	std::array<std::uint32_t, 12> hh{};
	std::size_t m = 0;
};
static IrbTurnTab irb_tab;
} // namespace
// my_burst_m with the turn's allowances honoured. A basic hit needs the attack left (GameRules.md:100-102); with none left a ready reset
// restores it, as the turn's one cast (interactions.md:25). A melee body that must step to reach cannot also cast a spell that
// excludes walking (GameRules.md:430, interactions.md:27): the walk-and-hit keeps the walk-compatible casts, tested from the tile it
// steps to, and an excluding spell counts alone, from here.
static __attribute__((noinline)) float my_burst_allowances(const Body& f, int d)
{
	const Kit& k = *W.me.kit;
	const float pm = kit_rules::passive_mult(W.me) * mu::pair(W.me, f);
	float dash_in = 0;
	if (!k.ranged && d > W.me.range + 1 && k.slot_dash >= 0 && ready(k.slot_dash) && !W.cast && W.can_attack() && d <= W.me.range + static_cast<int>(k.dash_range) + (W.can_move() ? 1 : 0))
		dash_in = (W.me.str + (k.dash_mod > 0 ? k.dash_mod * W.me.foc : 0.0f)) * pm;
	const bool basic_left = W.can_attack() && !(k.ranged && W.moved);
	const auto usable = [&](int s, bool walking) { return s >= 0 && ready(s) && !(walking && kit_rules::slot_excl(s)); };
	// the turn's one damaging cast at this distance, in my_burst_m's order
	const auto one_spell = [&](int dist, bool walking) -> float
	{
		if (usable(k.slot_dmg, walking) && dist <= static_cast<int>(k.dmg_range))
			return k.dmg_mod * W.me.foc;
		if (usable(k.slot_cc, walking) && k.cc_mod > 0 && dist <= static_cast<int>(k.cc_range))
			return k.cc_mod * W.me.foc;
		if (usable(k.slot_aoe, walking) && dist <= static_cast<int>(k.aoe_range + k.aoe_radius))
			return k.aoe_mod * W.me.foc;
		if (usable(k.slot_dash, walking) && k.dash_mod > 0 && dist <= static_cast<int>(k.dash_range) + 1)
			return k.dash_mod * W.me.foc;
		return 0.0f;
	};
	// the turn's damage with the basic hit in reach or not: the reset's hit and the spell share the one cast
	const auto turn = [&](bool in_reach, int dist, bool walking) -> float
	{
		const float spell = one_spell(dist, walking);
		const float reset_hit = in_reach && usable(k.slot_reset, walking) ? W.me.str : 0.0f;
		const float hit = in_reach && basic_left ? W.me.str : 0.0f;
		return hit + std::max(reset_hit, spell);
	};
	const bool stepping = !k.ranged && d > W.me.range && d <= W.me.range + 1 && W.can_move();
	const float burst = stepping ? std::max(turn(true, d - 1, true), one_spell(d, false)) : turn(d <= W.me.range, d, false);
	return std::max(burst * pm, dash_in);
}
float my_burst_m(const Body& f, int d, bool oc)
{
	return my_burst_allowances(f, d);
}
// The first early-out test inline at the call site (a call and frame a turn saved), the rest out of line.
static __attribute__((always_inline)) bool spell_alone_kills(const Body& e, int d)
{
	const Kit& k = *W.me.kit;
	if (k.ranged || (ren_layer::kills_me(e)))
		return false;
	return spell_kills_foe_slow(e, d);
}
// The damage of one point of spell mod on f (my_burst's factor): spell_base() once, spell_on(base, f) per foe.
static inline float spell_base() { return W.me.foc * kit_rules::passive_mult(W.me); }
static inline float spell_on(float base, const Body& f) { return base * mu::pair(W.me, f); }
namespace {
static __attribute__((noinline)) bool spell_kills_foe_slow(const Body& e, int d)
{
	const Kit& k = *W.me.kit;
	const float dmg = spell_on(spell_base(), e);
	const float h = eff_hp(e);
	if (k.slot_dmg >= 0 && k.dmg_mod > 0 && ready(k.slot_dmg) && d <= static_cast<int>(k.dmg_range) && h <= k.dmg_mod * dmg)
		return true;
	if (k.slot_cc >= 0 && k.cc_mod > 0 && ready(k.slot_cc) && d <= static_cast<int>(k.cc_range) && !e.stunned && h <= k.cc_mod * dmg)
		return true; // fight() casts the stun on an unstunned focus
	return k.slot_aoe >= 0 && k.aoe_mod > 0 && ready(k.slot_aoe) && d <= static_cast<int>(k.aoe_range + k.aoe_radius) && h <= k.aoe_mod * dmg;
}
} // namespace
// Beyond a step and a hit, a kill counts only with a landing that works (from here, or after the
// free step).
bool dash_kill_reachable(const Body& f, int d)
{
	const Kit& k = *W.me.kit;
	if (d <= std::max(W.me.range + 1, 2) || k.ranged)
		return true;
	if (d <= W.me.range + static_cast<int>(k.dash_range))
		return geom::landing_from(W.me.pos, f).x >= 0;
	return W.can_move() && d == W.me.range + static_cast<int>(k.dash_range) + 1 && geom::dash_step_for(f).x >= 0;
}
namespace {
// The one call point for the pair factor on my hit on f in kill_dmg's own sums (KQ_BASIC / KQ_STEP / KQ_DASH). Mode 0 is my_burst,
// whose own factor line (mu::pair in my_burst_m) prices it there: not twice. Bit 32: my own Skirmish / Collectors multipliers
// (passive_mult already counts them).
static float kill_damage_pair_factor(const Body& f)
{
	(void)f;
	return 1.0f;
}
} // namespace
// kill_now's reach: a melee body with a ready dash reaches a kill one step + the dash + its range away (assess's kreach).
static int kill_now_reach()
{
	const Kit& k = *W.me.kit;
	return (!k.ranged && k.slot_dash >= 0 && ready(k.slot_dash) && !W.cast && W.can_attack()) ?
		std::max(std::max(W.me.range + 1, 2), W.me.range + static_cast<int>(k.dash_range) + (W.can_move() ? 1 : 0)) :
		std::max(W.me.range + 1, 2);
}
namespace {
static bool kq_can_hit() { return W.can_attack() && !W.attacked && !(W.me.kit->ranged && W.moved); }
} // namespace
static float kill_dmg(const Body& f, int d, unsigned mode)
{
	if ((mode & (KQ_BASIC | KQ_STEP | KQ_DASH)) == 0)
		return geom::my_burst(f, d); // its factor is my_burst's (see kill_damage_pair_factor)
	const Kit& k = *W.me.kit;
	const float pm = kit_rules::passive_mult(W.me) * kill_damage_pair_factor(f);
	if (mode & KQ_STEP)
		return d <= W.me.range + ((k.ranged) ? 0 : 1) ? W.me.str * pm : 0.0f; // a ranged body walks or hits
	if (mode & KQ_BASIC)
		return d <= W.me.range && kq_can_hit() ? W.me.str * pm : 0.0f;
	const float hit = d <= W.me.range && kq_can_hit() ? W.me.str : 0.0f;
	const float land = k.dash_mod > 0 && d <= std::max(1, static_cast<int>(k.dash_radius)) ? k.dash_mod * W.me.foc : 0.0f;
	return (hit + land) * pm;
}
static bool kills(const Body& f, int d, unsigned mode)
{
	const float h = eff_hp(f);
	if (mode != 0)
		return h <= kill_dmg(f, d, mode);
	return (d <= kill_now_reach() && h <= kill_dmg(f, d, 0) && dash_kill_reachable(f, d)) || spell_alone_kills(f, d);
}
} // namespace burst
} // namespace nova::combat
