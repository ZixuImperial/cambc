// combat_assess_stance.cc: Assess, part 3: ratios, focus and the base stance.
#include "combat_internal.h"
namespace nova::combat {
namespace stance {
namespace {
// Heals lengthen the fight for the side that has them: a side's power (Lanchester: total health x total
// damage) grows with its heal pool over the fight horizon.
static __attribute__((always_inline)) inline void assess_ratios(AssessCtx& c)
{
	Assessment& a = c.a;
	float e_h = 0;
	e_h = c.e_h;
	float hp_us = support_heal_pool(c.me, tune::HEAL_HORIZON);
	if (!(c.f_h > c.me_h) && W.me.kit && W.me.kit->slot_heal >= 0) // no other friend: my heal has no target
		hp_us -= dmg::heal_of(W.me, W.cd[static_cast<std::size_t>(W.me.kit->slot_heal)], c.me, tune::HEAL_HORIZON);
	hp_us = std::max(0.0f, hp_us);
	const float hp_them = dmg::foe_heal_on_others(c.me, tune::HEAL_HORIZON, a);
	KIT_RULE_FIX_CNT(0, hp_us != support_heal_pool(c.me, tune::HEAL_HORIZON) || hp_them != enemy_heal_pool(c.me, tune::HEAL_HORIZON));
	const float heal_us = 1.0f + (hp_us) / std::max(1.0f, c.f_h);
	const float heal_them = 1.0f + (hp_them) / std::max(1.0f, e_h);
	const float f_sq = c.f_sq;
	auto balance = [&](float e) { return (f_sq * f_sq) * heal_us / std::max(1.0f, e * e * heal_them); };
	a.ratio = balance(c.e_sq);
	a.ratio_near = balance(c.e_near);
	a.ratio_fc = balance(c.e_sq_fc);
}
// ---- focus
// Focus: the team's quickest kill, so allies in the same fight hit the same body; another visible foe that dies to my
// reach this turn takes it (the lowest effective HP first); and no focus next to its own spawn unless it dies this turn.
static __attribute__((always_inline)) inline void assess_pick_focus(AssessCtx& c)
{
	Assessment& a = c.a;
	a.focus = c.ofs_any ? c.ofs_fc : team_focus(tune::FIGHT_R);
	AF_CHECK();
	if (a.focus >= 0 && foe_model::unreachable(assess_enemy(a.focus)))
		a.focus = -1;
	if (a.focus >= 0)
	{
		const auto& f = assess_enemy(a.focus);
		c.kill_now = burst::kills(f, cheb(f.pos, c.me), 0);
	}
	if (!c.kill_now)
	{
		float best_h = 1e9f;
		for (std::size_t i = 0; i < W.enemies.size(); ++i)
		{
			const auto& e = W.enemies[i];
			if (foe_model::unreachable(e))
				continue;
			const float h = eff_hp(e);
			if (h < best_h && burst::kills(e, cheb(e.pos, c.me), 0))
			{
				best_h = h;
				a.focus = static_cast<int>(i);
				c.kill_now = true;
			}
		}
	}
	if (a.focus >= 0 && !c.kill_now)
	{
		const vec2 fp = assess_enemy(a.focus).pos;
		if (mates::enemy_spawn_near(fp, NOCHASE_R))
		{
			c.nc_cleared = a.focus;
			a.focus = -1;
		}
	}
}
// ---- engage and flee bars. Never take an even fight a body down. Outnumbering at a near-even ratio does not pay, so the bar grows
// by EF_B for each body we have over the foes within EF_FOE_R. The bag, link, support and hunt terms apply on top.
static __attribute__((always_inline)) inline void assess_bars_headcount(AssessCtx& c)
{
	const Assessment& a = c.a;
	c.engage = (static_cast<float>(B467_ENGAGE_X100) / 100.0f);
	c.flee_thr = (static_cast<float>(B467_FLEE_X100) / 100.0f);
	if (a.n_foes > a.n_friends)
		c.engage = tune::ENGAGE_OUTNUMBERED;
	else if (a.n_friends > a.n_foes)
		c.engage = tune::ENGAGE_OUTNUMBERING;
	c.efc = mates::lone_fight_counts(a);
	if (a.n_friends >= c.efc.foes12)
	{
		// pow once per exponent (0: not yet; a zero base recomputes, the same value).
		static std::array<float, 16> ef_pow{};
		const int ex = a.n_friends - c.efc.foes12;
		float pw = ex < static_cast<int>(ef_pow.size()) ? ef_pow[static_cast<std::size_t>(ex)] : 0.0f;
		if (pw == 0.0f)
		{
			pw = std::pow(static_cast<float>(EF_B_X100) / 100.0f, static_cast<float>(ex));
			if (ex < static_cast<int>(ef_pow.size()))
				ef_pow[static_cast<std::size_t>(ex)] = pw;
		}
		c.engage = std::max(c.engage, (static_cast<float>(EF_A_X100) / 100.0f) * pw);
	}
}
// A bag raises the bars: dying hands it to the killer, the bigger the more careful. Passive Cassi & Issac: my death also kills my
// linked body and hands over its bag. With our support in the fight, more fights qualify (her heal is in the ratio too); team-fight
// mode already counts her, so her own engage scale applies only outside it, and never twice.
static __attribute__((always_inline)) inline void assess_bars_bag_and_support(AssessCtx& c)
{
	c.linked = linked_slot() >= 0;
	c.bag = c.linked ? linked_bag() : static_cast<int>(W.me.gems);
	if (c.bag >= tune::BAG_MIN) // the stake rise (it replaced the old BAG_ENGAGE / BAG_FLEE rise)
		nova::econ::win_bag_flee::stake_bars(c.bag, c.engage, c.flee_thr);
	if (c.linked && !CI2_FIGHT())
	{
		c.engage += tune::LINKED_ENGAGE;
		c.flee_thr += tune::LINKED_FLEE;
	}
	if (c.tfm)
	{
		c.engage -= tune::TEAM_ENGAGE;
		c.flee_thr -= tune::TEAM_FLEE;
		c.join = tune::TEAM_JOIN;
	}
	c.wsc = c.tfm ? 1.0f : support::engage_scale();
	c.engage *= c.wsc;
	if (c.wsc < 1.0f)
		c.flee_thr *= tune::SUPPORT_FLEE_SCALE;
	c.low = W.me.frac() < ((c.linked && !CI2_FIGHT()) ? tune::LOW_HP_LINKED : tune::LOW_HP); // PASSIVE Cassi & Issac
	if (CI2_FIGHT())
		nova::ci2::death_price_bar(c.engage, nova::ci2::pair_bag()); // CI2 decision 6: the price of death
	else if (c.linked) // Cassi warier, Issac by team gold
		nova::ci::builds::bars(c.engage, c.flee_thr);
	c.engage += strat::policy().engage_bias;
	c.flee_thr += strat::policy().flee_bias;
}
// A carrier as focus is worth a fight at a smaller edge. Both sides priced in gems: a kill swings its bag (x2 for a Prism) plus
// about 22 (CUT_FARMING and 0.1 x a flat 100-gold bounty); my death swings my bag plus the same 22. The bounty is the killer's:
// mine for the gain (Hunter +50, Treasure +10%, VV +33%), the richest among enemies within KILLER_R (else the focus) for my
// death. A linked Cassi & Issac death loses both bodies' farming but pays one bounty. The cut never takes the bar below an even
// fight (CUT_FLOOR): only fights the evaluation says we win.
static __attribute__((always_inline)) inline void assess_carrier_cut(AssessCtx& c)
{
	const Assessment& a = c.a;
	if (a.focus < 0 || c.low)
		return;
	const auto& hf = assess_enemy(a.focus);
	if (static_cast<int>(hf.gems) < tune::CUT_MIN_BAG)
		return; // the cut below needs the bag first
	const unsigned hunter = prism::has_family(rs::F_HUNTER) ? 1u << rs::F_HUNTER : 0u;
	const unsigned treasure = prism::has_family(rs::F_TREASURE) ? 1u << rs::F_TREASURE : 0u;
	const std::uint16_t mine = static_cast<std::uint16_t>(hunter | treasure);
	const int kg_me = rs::kill_gold(mine, vesper_layer::gold_pct(W.me.kit));
	int kg_them = 0;
	for (const auto& e : W.enemies)
		if (cheb(e.pos, W.me.pos) <= tune::KILLER_R)
			kg_them = std::max(kg_them, rs::kill_gold(rs::families(e.h, W.round), vesper_layer::gold_pct(e.kit)));
	if (kg_them == 0)
		kg_them = rs::kill_gold(rs::families(hf.h, W.round), vesper_layer::gold_pct(hf.kit));
	const float gain = tune::CUT_GEM_VALUE * hunt_prize(hf) + tune::CUT_FARMING + tune::CUT_GOLD * static_cast<float>(kg_me);
	const float my_farming = (c.linked && !CI2_FIGHT()) ? 2.0f * tune::CUT_FARMING : tune::CUT_FARMING; // PASSIVE Cassi & Issac (CI2: the death price bar carries it)
	const float loss = (tune::CUT_GEM_VALUE * static_cast<float>(c.bag) + my_farming) + tune::CUT_GOLD * static_cast<float>(kg_them);
	if (static_cast<int>(hf.gems) >= tune::CUT_MIN_BAG && gain > loss)
	{
		const float cut = tune::CUT_MAX * std::min(1.0f, (gain - loss) / tune::CUT_FULL_EDGE);
		c.engage = std::max(std::min(c.engage, tune::CUT_FLOOR), c.engage - cut);
	}
}
// ---- the base stance
// This fight would be started by me: no foe reaches me, I am not caught, I was not hit, and no ally of mine is in contact.
static __attribute__((always_inline)) inline bool assess_nothing_started(const Assessment& a)
{
	return !a.in_reach && !a.caught && !took_damage(tune::RECENT_HIT_ROUNDS) && !memory::ally_in_contact(a);
}
// Clearly stronger: engage what we see; never chase a foe we cannot see. The initiation balance (refit foe kits, unseen
// reinforcements in the middle/enemy third); with an ally in contact, from 8 tiles.
static __attribute__((always_inline)) inline void assess_stance_stronger(const AssessCtx& c)
{
	Assessment& a = c.a;
	a.stance = (a.nearest <= tune::ENGAGE_SIGHT_R) ? FIGHT : CALM;
	// This rule STARTS fights. Unless nothing would be started it needs a committed squad mate in the fight: a visible mate by
	// objective within its attack range + 1 of the focus, or a healthy ally within 3 of me. Otherwise CALM, never FLEE:
	// initiation only (no giving way to equal foes).
	if (a.stance == FIGHT && a.focus >= 0 && assess_nothing_started(a) && (a.ratio_fc) < SQ_STRIKE_SOLO)
	{
		if (!memory::squad_mate_covers_focus(assess_enemy(a.focus).pos))
			a.stance = CALM;
	}
	// a Ryth body starts a fight only at a near balance of RYTH_START_NEAR (kill_now took the branch above); else CALM.
	if (a.stance == FIGHT && ryth_layer::fight_calm_start() && assess_nothing_started(a) && a.ratio_near < ryth_layer::RYTH_START_NEAR)
		a.stance = CALM;
}
// The first test that holds sets the stance.
static __attribute__((always_inline)) inline void assess_base_stance(AssessCtx& c)
{
	Assessment& a = c.a;
	if (c.kill_now)
		a.stance = FIGHT;
	else if ((a.ratio_fc) >= c.engage && !c.low)
		assess_stance_stronger(c);
	else if (a.ratio >= std::min(c.join, c.wsc) && !c.low && memory::ally_in_contact(a))
		a.stance = FIGHT; // an ally is already trading blows next to me: add my weight
	else if (a.caught)
		// Running from a melee chaser hands out free hits (same speed): fight back unless the fight is hopeless or
		// home is a step away.
		a.stance = (!(c.low && !camps::foe_in_basic_range()) && a.ratio_near >= CAUGHT_MIN && !geom::home_close(tune::CAUGHT_HOME_STEPS)) ? FIGHT : FLEE;
	else if (a.in_reach)
	{
		// Standing in their reach without hitting back only feeds them: close in when ahead, else get out.
		const float irb = static_cast<float>(B467_INREACH_X100) / 100.0f;
		a.stance = (a.ratio) >= irb && !c.low ? FIGHT : FLEE; // closing in starts a fight
	}
	else if (a.ratio < c.flee_thr && a.nearest <= tune::FLEE_NEAR_R)
		a.stance = FLEE;
	else if (W.round <= turn_memory.retreat_until && a.nearest <= tune::RETREAT_NEAR_R && a.ratio < c.flee_thr + tune::RETREAT_MARGIN)
	{
		a.stance = FLEE; // committed retreat: do not turn back at the edge of the trigger distance
		c.ct_soft = true;
	}
	else if (a.n_foes > a.n_friends && a.ratio < tune::EVEN_RATIO && a.nearest <= tune::OUTNUMBERED_NEAR_R)
	{
		a.stance = FLEE; // outnumbered and not ahead: leave on first sight, before the first hit
		c.ct_soft = true;
	}
	else
		a.stance = CALM;
}
// Next to a worked group the fight is held below the hold bar only when idle mates within EN_HELP_R make it favourable (they are
// called: HELP); else the body leaves at once.
static __attribute__((always_inline)) inline void assess_hold_fight(const AssessCtx& c)
{
	Assessment& a = c.a;
	if (!mates::fight_beside_worked_group())
		a.stance = FIGHT;
	else if (a.ratio * 100.0f >= static_cast<float>(EN_HOLD_X100))
	{
		a.stance = FIGHT;
		ENG_CNT(0);
	}
	else
	{
		const float k = (c.f_sq + mates::idle_mate_help_power(c.me, c.join_r)) / std::max(1.0f, c.f_sq);
		if (a.ratio * k * k * 100.0f >= static_cast<float>(EN_HOLD_X100))
		{
			a.stance = FIGHT;
			turn_memory.help_round = W.round;
			ENG_CNT(1);
		}
		else
			ENG_CNT(2);
	}
}
// Hysteresis against fight/flee flip-flops (each switch wastes a step): a retreat is not turned into a fight within
// HYST_ROUNDS unless a kill is on, I am caught, or the balance clearly changed; a fight in progress is not abandoned
// for a small dip in the balance. With both timers recent each rule needs its own action to be the latest (a tie counts as a flee).
static __attribute__((always_inline)) inline void assess_hysteresis(const AssessCtx& c)
{
	Assessment& a = c.a;
	const bool fled_recently = W.round - turn_memory.last_flee_round <= tune::HYST_ROUNDS;
	const bool fought_recently = W.round - turn_memory.last_fight_round <= tune::HYST_ROUNDS;
	if (a.stance == FIGHT && fled_recently && !c.kill_now && !a.caught && a.ratio < tune::HYST_TURN_BACK * c.engage &&
		(!fought_recently || turn_memory.last_flee_round >= turn_memory.last_fight_round))
		a.stance = FLEE;
	else if (a.stance == FLEE && fought_recently && (!fled_recently || turn_memory.last_fight_round > turn_memory.last_flee_round) && !c.low && !a.caught &&
		a.ratio * 100.0f >= static_cast<float>(HOLD_MIN_X100) && a.focus >= 0)
		assess_hold_fight(c);
}
} // namespace
} // namespace stance
} // namespace nova::combat
