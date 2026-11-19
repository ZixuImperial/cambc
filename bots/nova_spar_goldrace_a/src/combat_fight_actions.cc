// combat_fight_actions.cc: The actions of a FIGHT turn.
#include "combat_internal.h"
namespace nova::combat {
namespace fight_turn {
namespace {
// I changed tile: the turn counts as acted and the distance is new.
static __attribute__((always_inline)) inline void fight_moved(FightCtx& c)
{
	c.acted = true;
	c.d = cheb(W.me.pos, c.f.pos);
}
// A known foe my stun works on.
static __attribute__((always_inline)) inline bool fight_stunnable(const Body& e)
{
	return !e.stunned && marcella_layer::fight_stun_holds(e);
}
// The stun can go out now: a walk-excluding one only if I have not moved.
static __attribute__((always_inline)) inline bool fight_stun_castable(const Kit& k)
{
	return slot_up(k.slot_cc) && (!k.cc_excl || !W.moved);
}
// A ranged damaging stun (Tavi slot 1, Prism slot 0) on a kit with no damage slot takes the damage spell's place.
static __attribute__((always_inline)) inline bool fight_stun_nuke_up(const Kit& k)
{
	return k.ranged && k.slot_dmg < 0 && k.cc_mod > 0 && fight_stun_castable(k);
}
// The easier focus Vendetta and Vesper Vale dash at without a kill: stunned or weak.
static __attribute__((always_inline)) inline bool fight_weak_focus(const Body& f)
{
	return f.stunned || f.frac() < tune::WEAK_FOCUS_FRAC;
}
// The weakest enemy within range I can reach. skip_focus: not the focus. stunned_last: unstunned ones first.
static __attribute__((always_inline)) inline const Body* fight_weakest_in(const FightCtx& c, int range, bool skip_focus, bool stunned_last)
{
	const Body* o = nullptr;
	float oh = tune::NO_TARGET_HP;
	for (const auto& e : W.enemies)
	{
		if ((skip_focus && e.h == c.f.h) || foe_model::unreachable(e) || cheb(e.pos, W.me.pos) > range)
			continue;
		float h = eff_hp(e);
		if (stunned_last && e.stunned)
			h += tune::STUNNED_LAST;
		if (h < oh)
		{
			oh = h;
			o = &e;
		}
	}
	return o;
}
// Shield when something can hit me next turn, unless the kill needs this turn's one cast.
static bool fk1_hlf_held = false; // this turn's shield waits for Heart's landing
static __attribute__((always_inline)) inline void fight_shield(FightCtx& c)
{
	fk1_hlf_held = false;
	if (slot_up(c.k.slot_shield) && W.me.shield <= 0 && ((c.a.in_reach || c.d <= tune::SHIELD_FOE_DIST)) && !cast::kill_needs_dash(c.f, c.d))
	{
		if (c.k.dash_mod > 0 && slot_up(c.k.slot_dash) && c.d <= c.dash_r + 1 && geom::heart_landing(c.k, c.f).x >= 0) [[unlikely]]
		{
			fk1_hlf_held = true; // the landing (damage + stun on the focus) takes the one cast; fight_heart_dash shields if it is refused
			return;
		}
		c.acted |= cast_self(c.k.slot_shield);
	}
}
static __attribute__((always_inline)) inline const Body* fight_linked_stun(const FightCtx& c);
// Stun a channelling enemy first (it cancels a recall or tribute), else the focus.
static __attribute__((always_inline)) inline void fight_stun(FightCtx& c)
{
	if (!fight_stun_castable(c.k)) // v693 FST1: a walk-excluding stun after a move cannot go out (fuel only)
		return;
	const Body* st = nullptr;
	for (const auto& e : W.enemies)
		if (e.channeling() && fight_stunnable(e) && cheb(e.pos, W.me.pos) <= c.cc_r)
			st = &e;
	if (!st)
		st = fight_linked_stun(c);
	if (!st && c.d <= c.cc_r && fight_stunnable(c.f))
		st = &c.f;
	if (!st && !c.k.ranged && cast::stun_cast_for_damage_only(c.f, c.d)) // ranged kits reach her through the damaging stun below
		st = &c.f;
	if (st)
		c.acted |= cast_on_champion(c.k.slot_cc, *st);
}
// A foe one step beyond the dash that the dash-in finishes: the free walk first, then the dash below lands next to it (Heart of
// Ruin's landing hit and stun included) and the basic attack follows. Or a mates' fight.
static __attribute__((always_inline)) inline void fight_walk_for_dash(FightCtx& c)
{
	const Kit& k = c.k;
	if (k.ranged || !slot_up(k.slot_dash) || !W.can_move() || !W.can_attack() || c.d != W.me.range + c.dash_r + 1)
		return;
	if (!burst::kills(c.f, c.d, KQ_RAW) && !(k.dash_mod <= 0 && (geom::mate_hit_focus_dash_ok(c.f) || geom::healthy_focus_dash_ok(c.a, c.f))))
		return;
	const vec2 st = geom::dash_step_for(c.f); // only a step whose dash lands
	if (st.x >= 0 && mv::try_move(st))
		fight_moved(c);
}
// Heart of Ruin style dash: land next to the focus, hitting everything around the landing tile.
static __attribute__((always_inline)) inline void fight_heart_dash(FightCtx& c)
{
	const Kit& k = c.k;
	if (k.dash_mod <= 0 || !slot_up(k.slot_dash) || c.d > c.dash_r + 1)
		return;
	const vec2 best = geom::heart_landing(k, c.f);
	bool landed = best.x >= 0 && cast_at(k.slot_dash, best);
	if (!landed && best.x >= 0 && ready(k.slot_dash)) // the refused tile is out, the next landing is tried once
	{
		const vec2 next = geom::heart_landing_next(k, c.f, best);
		landed = next.x >= 0 && cast_at(k.slot_dash, next);
	}
	if (landed)
		fight_moved(c);
	else if (fk1_hlf_held && slot_up(k.slot_shield)) [[unlikely]] // the landing was refused: the shield goes up
		c.acted |= cast_self(k.slot_shield);
}
// PASSIVE Issac: his dash (2 steps, walk-compatible, no landing effect) closes the gap a walk cannot: from 3 tiles it lands next to
// the focus and the basic attack follows this turn (fewest other enemies around the landing). Vendetta's closes the gap the same way
// for a focus she can finish, a stunned one or a weak one, any melee plain dash (Ren, Vendetta) for a kill, each onto a landing
// no more crowded than the kill dash's bar. When those gates refuse: a focus my mate is hitting (only the weak-focus gate is dropped).
static __attribute__((always_inline)) inline void fight_gap_dash(FightCtx& c)
{
	const Kit& k = c.k;
	const Body& f = c.f;
	const bool issac = ci_layer::me_issac();
	if (FB6_ON(4) && (k.ranged || k.dash_mod > 0 || !slot_up(k.slot_dash) || c.d != c.dash_r + 1 || !W.can_attack()))
		return; // FB6 RO3: the gate before the kill tests
	const bool ve_dash = vendetta_layer::fight_ve_dash() && (burst::kills(f, 1, KQ_DASH) || fight_weak_focus(f)); // the dash is the cast
	const bool fr_dash = burst::kills(f, c.d, KQ_RAW);
	if (k.ranged || k.dash_mod > 0 || !slot_up(k.slot_dash) || c.d != c.dash_r + 1 || !W.can_attack())
		return;
	bool ve_init = false; // the dash fires only through the healthy-focus alternative
	const bool md_dash = !(issac || ve_dash || fr_dash) && (geom::mate_hit_focus_dash_ok(f) || (ve_init = geom::healthy_focus_dash_ok(c.a, f)));
	const bool crowd_bar = ve_dash || fr_dash || md_dash; // plain Issac alone takes any landing
	if (!issac && !crowd_bar)
		return;
	int best_s = 1 << 30;
	const vec2 best = geom::plain_land(f, ve_init, best_s);
	const int kdg_here = cast::kill_dash_crowd_bar(f, fr_dash, best, best_s);
	if (best.x >= 0 && (!crowd_bar || best_s <= kdg_here) && cast_at(k.slot_dash, best))
		fight_moved(c);
}
static __attribute__((always_inline)) inline void fight_vesper_dash(FightCtx& c);
// One centre for the area spell: better than the best so far (a stunned body under an area stun counts half), never waking a
// sleeping attacker (damage wakes its whole group).
// FAC bit 64 KIT1, caller read the flag: the weight of the foes in the area on their own spawn that the area doesn't kill (a stun kit
// keeps them: the stun holds).
static __attribute__((noinline)) int fac_kit_spawn_weight(const Kit& k, vec2 t)
{
	int w = 0;
	for (const auto& e : W.enemies)
	{
		if (cheb(e.pos, t) > static_cast<int>(k.aoe_radius))
			continue;
		if (!k.aoe_stun && bbget(M.enemy_spawn, e.pos) && eff_hp(e) > k.aoe_mod * burst::spell_on(burst::spell_base(), e))
			w += tune::AREA_WEIGHT_FRESH;
		else if (k.aoe_stun && !e.stunned && marcella_layer::fight_stun_wasted(e))
			w += tune::AREA_WEIGHT_FRESH - tune::AREA_WEIGHT_STUNNED; // VMR bit 4: a stun on her is wasted (GR:658), weighed as a stunned body
	}
	return w;
}
static __attribute__((always_inline)) inline void fight_area_try(const Kit& k, vec2 t, vec2& best, int& best_w)
{
	if (!inb(t) || cheb(t, W.me.pos) > static_cast<int>(k.aoe_range))
		return;
	int nw = 0;
	for (const auto& e : W.enemies)
		if (cheb(e.pos, t) <= static_cast<int>(k.aoe_radius))
			nw += (k.aoe_stun && e.stunned) ? tune::AREA_WEIGHT_STUNNED : tune::AREA_WEIGHT_FRESH;
	nw -= fac_kit_spawn_weight(k, t); // FAC bit 64 KIT1: a foe on its own spawn heals to full (GR:153): it counts only when killed
	if (nw <= best_w || camps::wakes_other_group(t, std::max(1, static_cast<int>(k.aoe_radius)), W.me.pos, -1, -k.aoe_mod)) // BB12 KPAIR: -mod = per-champion pricing
		return;
	if (kit_rules::ren_retaliation_of_cast(k.slot_aoe, 0u, 0u, t) >= eff_hp(W.me))
		return; // BB12 RENT
	best_w = nw;
	best = t;
}
// PASSIVE Stellar: the area spell's 3x3 with the most enemies, the focus in it. Chosen before the nuke, cast after the stuns.
static __attribute__((always_inline)) inline vec2 fight_area_tile(const FightCtx& c)
{
	const Kit& k = c.k;
	vec2 best{ -1, -1 };
	if (!slot_up(k.slot_aoe))
		return best;
	int best_w = 0;
	fight_area_try(k, c.f.pos, best, best_w);
	for (const vec2 dd : DIRS)
		fight_area_try(k, c.f.pos + dd, best, best_w);
	if (k.aoe_stun && best.x >= 0 && camps::hold_area_stun_on_immune_foes(best, static_cast<int>(k.aoe_radius), k.aoe_mod * W.me.foc * kit_rules::passive_mult(W.me)))
		best = { -1, -1 };
	return best;
}
// The damage spell on the focus; with no damage slot the damaging stun takes its place, stunned or not. A focus beyond the spell
// (and, for a walk-excluding spell, beyond a step and a hit): the weakest other enemy in range takes it.
static __attribute__((always_inline)) inline void fight_nuke(FightCtx& c)
{
	const Kit& k = c.k;
	if (slot_up(k.slot_dmg) && c.d <= c.dmg_r)
		c.acted |= cast_on_champion(k.slot_dmg, c.f);
	else if (fight_stun_nuke_up(k) && c.d <= c.cc_r && !cast::stun_threat_instead_of_focus(c.f)) // the kill's cast is not kept back
		c.acted |= cast_on_champion(k.slot_cc, c.f);
	else if (k.dmg_mod > 0 && slot_up(k.slot_dmg) && (!k.dmg_excl || c.d > W.me.range + 1) && !(bb12_akill)) // BB12 AKILL
	{
		const Body* o = fight_weakest_in(c, c.dmg_r, false, false);
		if (o)
			c.acted |= cast_on_champion(k.slot_dmg, *o);
	}
}
// The focus is out of the damaging stun's range: the weakest other enemy in range takes it (unstunned first).
static __attribute__((always_inline)) inline void fight_stun_nuke_other(FightCtx& c)
{
	if (!fight_stun_nuke_up(c.k) || bb12_akill) // BB12 AKILL
		return;
	if (cast::stun_threat_instead_of_focus(c.f))
		return; // FAC2: the threat stun decides (combat_cast.cc stun-immune focus)
	const Body* o = fight_weakest_in(c, c.cc_r, true, true);
	if (o)
		c.acted |= cast_on_champion(c.k.slot_cc, *o);
}
// A stun on an enemy that has one of our bodies in its reach (it loses the hit it was about to make).
static __attribute__((always_inline)) inline void fight_threat_stun(FightCtx& c)
{
	if (!fight_stun_castable(c.k))
		return;
	if (bb12_akill)
		return; // FAC1: the cast goes to the area kill on the focus
	for (const auto& e : W.enemies)
	{
		if (e.stunned || marcella_layer::fight_stun_wasted(e) || foe_model::unreachable(e) || cheb(e.pos, W.me.pos) > c.cc_r)
			continue;
		bool threat = cheb(e.pos, W.me.pos) <= std::max(1, e.range);
		for (const auto& al : W.allies)
			threat |= cheb(e.pos, al.pos) <= std::max(1, e.range);
		if (!threat && cast::thr_melee_threat(e)) // THR bit 1: a melee foe's step + hit
			threat = true;
		if (threat && cast_on_champion(c.k.slot_cc, e))
		{
			c.acted = true;
			break;
		}
	}
}
// Engaged on my camp, a foe out of my range is not chased (the farm step captures more than a step toward a foe; spells already cast
// this turn stand). A kill that still needs the walk and a nearly dead focus are chased.
static __attribute__((always_inline)) inline bool fight_stay_on_camp(const FightCtx& c)
{
	return hold_state.active_round != W.round && c.d > W.me.range && econ::engaged_now() && !stance::kill_window(c.f) && !(c.f.frac() < FINISH_LOW_HP);
}
// Never take a free volley: a step that cannot be followed by a hit this turn must not enter a dangerous reach I am outside of now.
static __attribute__((always_inline)) inline bool fight_volley_veto(const FightCtx& c)
{
	const bool hit_after = (c.d - 1 <= W.me.range) && (!c.k.ranged || slot_up(c.k.slot_reset));
	if (hit_after)
		return false;
	if (const float dh = geom::danger_veto(c.a, W.me.pos); !(dh <= 0)) // here unsafe but not lethal, every closer step lethal: veto
	{
		const float me_ehp = eff_hp(W.me);
		if (dh >= me_ehp)
			return false;
		for (const vec2 dd : DIRS)
		{
			const vec2 t = W.me.pos + dd;
			if (mv::free_tile(t) && cheb(t, c.f.pos) < c.d && geom::danger_veto(c.a, t) < me_ehp)
				return false;
		}
		return true;
	}
	for (const vec2 dd : DIRS)
	{
		const vec2 t = W.me.pos + dd;
		if (mv::free_tile(t) && cheb(t, c.f.pos) < c.d && geom::danger_veto(c.a, t) < tune::WALK_IN_VETO_FRAC * eff_hp(W.me))
			return false;
	}
	return true;
}
// Counts held turns in a row against this focus; past FSH_N of them the hold is over (with bit 2 the walk-in step goes ahead).
static __attribute__((always_inline)) inline bool fight_hold_outlasted(const Body& f)
{
	static int fsh_round = -1000, fsh_n = 0;
	static std::uint32_t fsh_h = 0;
	if (fsh_round == W.round && fsh_h == f.h)
		return fsh_n > FSH_TAB[2]; // FAC8: a second fight() this round doesn't recount
	fsh_n = (fsh_round == W.round - 1 && fsh_h == f.h) ? fsh_n + 1 : 1;
	fsh_round = W.round;
	fsh_h = f.h;
	return fsh_n > FSH_TAB[2];
}
// v699 R2B bit 4 CFS1: a ready stun counts only when fight_stun would cast it on this focus (not stun-immune GR:658, not stunned).
static bool cfs_cassi_ready(const Kit& k, const Body& f)
{
	return ci_layer::me_cassi() && ((k.slot_dmg >= 0 && ready(k.slot_dmg)) || (k.slot_cc >= 0 && ready(k.slot_cc) && fight_stunnable(f)));
}
// Whether this turn holds instead of walking at the focus.
static __attribute__((always_inline)) inline void fight_choose_hold(FightCtx& c)
{
	// The kill still needs the walk: neither the farm step nor a support's hold-back takes it.
	if (hold_state.active_round != W.round && c.d > W.me.range && W.can_move() && !stance::kill_window(c.f))
		c.hold = fight_volley_veto(c);
	if (c.hold && fight_hold_outlasted(c.f))
		c.hold = false;
	// r3: a support (Willow) stays behind its front line: it steps toward the focus only while an ally stands nearer to it, so it is
	// never the first body the enemies (or camps) reach.
	if (!c.hold && c.d > W.me.range && willow_layer::fight_hold_back(c.k) && cast::support_hold_back(c.f, c.d))
		c.hold = true;
}
// The weakest foe in my reach that is not on its spawn.
static __attribute__((always_inline)) inline const Body* fight_weakest_in_reach()
{
	const Body* t = nullptr;
	for (const auto& e : W.enemies)
		if (cheb(e.pos, W.me.pos) <= W.me.range && !bbget(M.enemy_spawn, e.pos) && (!t || eff_hp(e) < eff_hp(*t)))
			t = &e;
	return t;
}
// Before a long walk at a focus I cannot hit this turn: a melee body hits whatever stands in reach, the weakest not on its spawn.
static __attribute__((always_inline)) inline void fight_hit_before_walk(FightCtx& c)
{
	const Kit& k = c.k;
	return;
}
// Before a walk at a focus out of reach, a ranged body shoots the weakest in reach and stays (GameRules.md:100: a ranged body walks
// or shoots). Not when the walk lands in reach with a reset ready.
static __attribute__((always_inline)) inline bool fight_shot_before_walk(FightCtx& c)
{
	const Kit& k = c.k;
	if (!k.ranged || W.attacked || !W.can_attack() || (c.d - 1 <= W.me.range && k.slot_reset >= 0 && ready(k.slot_reset)))
		return false;
	const Body* t = fight_weakest_in_reach();
	if (!t || !attack_champion(*t))
		return false;
	c.acted = true;
	return true;
}
// FAC4, caller read the flag: fight_shot_before_walk's gate passes (a ranged body shoots the weakest in reach and stays).
static __attribute__((noinline)) bool fac_shot_gate(const FightCtx& c)
{
	const Kit& k = c.k;
	if (!k.ranged || W.attacked || !W.can_attack() || (c.d - 1 <= W.me.range && k.slot_reset >= 0 && ready(k.slot_reset)))
		return false;
	return fight_weakest_in_reach() != nullptr;
}
// Close the distance if needed (melee can still attack after walking).
static __attribute__((always_inline)) inline void fight_walk_in(FightCtx& c)
{
	const Kit& k = c.k;
	if (c.d <= W.me.range || !W.can_move() || c.hold)
		return;
	const bool cfh = cfs_cassi_ready(k, c.f); // v699 R2B bit 4 CFS1; b1802 CFH bit 1: Cassi stops at range CFH_R while a spell is ready
	if (cfh && c.d <= CFH_TAB[2])
		return;
	const bool shot = fight_shot_before_walk(c);
	fight_hit_before_walk(c);
	const mv::AvoidCampReach cch_guard(stance::focus_under_other_heavy_camp(c.f));
	if (cfh)
	{
		if (shot || !mv::step_to(c.f.pos, CFH_TAB[2], tune::WALK_IN_SEARCH))
			c.path_failed = true;
		else
			fight_moved(c);
		return;
	}
	if (shot || !mv::step_to(c.f.pos, W.me.range, tune::WALK_IN_SEARCH))
	{
		c.path_failed = true;
		return;
	}
	fight_moved(c);
}
// The walk brought a focus that was one step out of Heart of Ruin's dash into it.
static __attribute__((always_inline)) inline void fight_heart_after_walk(FightCtx& c)
{
	const Kit& k = c.k;
	if (k.dash_mod <= 0 || !W.moved || !slot_up(k.slot_dash) || c.d > c.dash_r + 1 || c.d < 2 || c.d_before_walk != c.dash_r + 2)
		return;
	const vec2 best = geom::heart_landing(k, c.f);
	if (best.x >= 0 && cast_at(k.slot_dash, best))
		fight_moved(c);
}
// The focus is in reach: the reset gives back an attack the walk spent, and a second hit on a focus the first one left alive.
static __attribute__((always_inline)) inline void fight_hit_focus(FightCtx& c)
{
	const Kit& k = c.k;
	if (!W.can_attack() && slot_up(k.slot_reset))
		cast_self(k.slot_reset);
	if (!attack_champion(c.f))
		return;
	c.acted = true;
	std::int32_t alive = 1;
	if (slot_up(k.slot_reset) && cambc::detail::sdk_champion_is_alive(c.f.h, &alive) == 0 && alive != 0 && cast_self(k.slot_reset))
		attack_champion(c.f);
	if (alive == 0 && slot_up(k.slot_reset))
	{
		// RGS bit 4: the first hit killed the focus: reset and hit the next foe in reach.
		const Body* n = fight_weakest_in(c, W.me.range, true, false);
		if (n && !ren_layer::kills_me(*n) && cast_self(k.slot_reset)) // KTB2: a living foe
			attack_champion(*n);
	}
}
// Out of reach of the focus: hit whatever enemy is in reach.
static __attribute__((always_inline)) inline void fight_hit_nearby(FightCtx& c)
{
	if (!W.can_attack() && slot_up(c.k.slot_reset))
		for (const auto& e : W.enemies)
			if (cheb(e.pos, W.me.pos) <= W.me.range)
			{
				cast_self(c.k.slot_reset); // the walk spent the attack; the reset gives it back
				break;
			}
	for (const auto& e : W.enemies)
		if (cheb(e.pos, W.me.pos) <= W.me.range && attack_champion(e))
		{
			c.acted = true;
			break;
		}
}
// Melee hits, then steps out of an awake camp's reach (GameRules:100).
static __attribute__((always_inline)) inline void fight_step_from_camp(FightCtx& c)
{
	if (c.k.ranged || !W.can_move() || cheb(W.me.pos, c.f.pos) > W.me.range)
		return;
	const vec2 t = geom::safe_in_range_step(c.a, c.f);
	if (t.x >= 0 && mv::try_move(t))
		c.acted = true;
}
} // namespace
} // namespace fight_turn
} // namespace nova::combat
