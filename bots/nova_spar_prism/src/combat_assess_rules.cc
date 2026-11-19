// combat_assess_rules.cc: Assess, part 4: the override rules and assess itself.
#include "combat_internal.h"
namespace nova::combat {
namespace stance {
namespace {
// ---- stance rules, in the order assess() runs them
// Channels. An enemy recalling (any hit cancels it) or tributing (a stun cancels it, and it cannot answer)
// within my reach this turn is hit; an enemy on one of our channelling allies is peeled off.
static __attribute__((always_inline)) inline void assess_rule_channels(const AssessCtx& c)
{
	Assessment& a = c.a;
	if (c.low || a.stance == FIGHT)
		return;
	const int ct = channel_target();
	if (ct >= 0 && a.ratio >= tune::CHANNEL_MIN_RATIO &&
		(!(W.me.gems >= tune::CHANNEL_BIG_BAG && a.ratio < tune::EVEN_RATIO) || prism::race_deny())) // a big bag blocks it at a below-even ratio, unless prism::race_deny
	{
		assess_fight_on(a, ct);
		return;
	}
	const int th = channel_threat();
	if (th >= 0 && a.ratio >= (c.tfm ? tune::CHANNEL_PEEL_RATIO_TEAM : tune::CHANNEL_PEEL_RATIO) &&
		cheb(assess_enemy(th).pos, c.me) <= tune::CHANNEL_PEEL_R)
		assess_fight_on(a, th);
}
// Hit by an enemy champion this round or last with the attacker in my reach this turn: hit back unless the exchange is hopeless
// (ratio_near counts the allies near me; a bag raises the bar; a kill always goes). A body that steps away is followed and hit again.
static __attribute__((always_inline)) inline void assess_rule_hit_back(const AssessCtx& c)
{
	Assessment& a = c.a;
	if (a.stance == FIGHT || W.me.channeling())
		return;
	const int at = react_attacker();
	if (at < 0)
		return;
	const Body& e = assess_enemy(at);
	float hope = REACT_HOPE;
	if (a.n_foes > a.n_friends)
		hope = std::max(hope, tune::REACT_OUTNUMBERED);
	if (c.bag >= tune::BAG_MIN)
		hope += tune::BAG_REACT + tune::BAG_REACT_SLOPE * assess_bag_share(c.bag);
	const bool kill = burst::kills(e, cheb(e.pos, c.me), static_cast<unsigned int>(KQ_RAW)); // KTB4: the reach-gated kill test
	if ((kill || (!c.low && assess_worst_ratio(a) >= hope)) && !(at == c.nc_cleared && !kill))
		assess_fight_on(a, at);
}
// With a team mate dead (respawning), a fight against two or more enemies is left unless it is clearly won or a kill this turn.
static __attribute__((always_inline)) inline void assess_rule_mate_dead(const AssessCtx& c)
{
	Assessment& a = c.a;
	if (a.stance == FIGHT && a.n_foes >= tune::MATE_DEAD_FOES && !c.kill_now && !a.in_reach && !a.caught && assess_worst_ratio(a) < FULL_TEAM_RATIO &&
		memory::team_dead() > 0) // not into a team fight; one already in contact is fought out (leaving it costs more)
		a.stance = FLEE;
}
static __attribute__((always_inline)) inline void assess_rule_ci_safe(const AssessCtx& c);
static __attribute__((always_inline)) inline void assess_rule_ci_melee_gap(const AssessCtx& c);
// Local power = (sum of health) x (sum of strength + focus) within LOCAL_POWER_R, ours against the foes I know (seen, or seen a
// moment ago). A fight starts only at POWER_ENGAGE or better, or with a kill this turn; a body already caught is exempt. A calm body
// below POWER_LEAVE with a known foe within its reach + LOCAL_POWER_STEPS leaves before the contact. It stays while a.ratio reads
// level or ahead.
static __attribute__((always_inline)) inline void assess_rule_local_power(const AssessCtx& c)
{
	Assessment& a = c.a;
	if (XOA_ON(2)) // v775 XOA bit 2 XOA2: return when none of the three rules below can fire (POWER_ENGAGE 0: power < 0 never holds)
	{
		const bool lp_bag = a.stance == FIGHT && !c.kill_now && !a.caught && c.bag >= (BSF_TAB[2]) && W.round - turn_memory.last_flee_round <= tune::HYST_ROUNDS && !(W.round - turn_memory.last_fight_round <= tune::HYST_ROUNDS && turn_memory.last_flee_round < turn_memory.last_fight_round);
		if (!lp_bag)
		{
			if (a.stance != CALM)
				return;
			bool xoa_nr = false; // CALM: only the leave on a foe near its reach can fire
			for (const auto& f : a.foes)
			{
				const int d = cheb(f.pos, c.me);
				if (d <= tune::LOCAL_POWER_R && f.reach >= 0 && d <= f.reach + tune::LOCAL_POWER_STEPS)
				{
					xoa_nr = true;
					break;
				}
			}
			if (!xoa_nr)
				return;
		}
	}
	float uh = eff_hp(W.me), us = W.me.str + W.me.foc; // v8xx EHO: our side in eff_hp units as the foes'
	for (const auto& al : W.allies)
		if (!al.channeling() && cheb(al.pos, c.me) <= tune::LOCAL_POWER_R)
		{
			if (nova::combat::retreating_mates::retreating(al)) // a retreating mate counts 0
				continue;
			uh += (eff_hp(al)); // v8xx EHO
			us += al.str + al.foc;
		}
	float th = 0, ts = 0, vis_s = 0;
	int vis_n = 0;
	const auto fb11_avg = [&]() {
		for (const auto& f : a.foes)
			if (f.idx >= 0)
			{
				const auto& e = assess_enemy(f.idx);
				vis_s += e.str + e.foc;
				++vis_n;
			}
		return vis_n > 0 ? vis_s / static_cast<float>(vis_n) : (W.me.str + W.me.foc);
	};
	float avg_s = 0.0f;
	bool avg_ok = false;
	bool near_reach = false;
	for (const auto& f : a.foes)
	{
		const int d = cheb(f.pos, c.me);
		if (d > tune::LOCAL_POWER_R)
			continue;
		th += std::max(1.0f, f.ehp);
		if (f.idx < 0 && !avg_ok)
		{
			avg_s = fb11_avg();
			avg_ok = true;
		}
		ts += f.idx >= 0 ? assess_enemy(f.idx).str + assess_enemy(f.idx).foc : avg_s;
		near_reach |= f.reach >= 0 && d <= f.reach + tune::LOCAL_POWER_STEPS;
	}
	if (th > 0)
	{
		const float power = (uh * us) / std::max(1.0f, th * ts);
		if (a.stance == FIGHT && !c.kill_now && !a.caught && c.bag >= (BSF_TAB[2]) && power < (POWER_LEAVE * nova::econ::win_bag_flee::bsf_stake(c.bag)) && W.round - turn_memory.last_flee_round <= tune::HYST_ROUNDS && !(W.round - turn_memory.last_fight_round <= tune::HYST_ROUNDS && turn_memory.last_flee_round < turn_memory.last_fight_round)) // BFP 1: the flee came last
			a.stance = near_reach ? FLEE : CALM; // BSF 1: a fleeing carrier does not turn back into a fight it should leave
		if (a.stance == FIGHT && !c.kill_now && !a.caught && power < POWER_ENGAGE)
			a.stance = a.in_reach ? FLEE : CALM;
		if (a.stance == CALM && near_reach && power < POWER_LEAVE && !(a.ratio >= tune::EVEN_RATIO)) // b2164 LPR1: level or ahead stays
			a.stance = FLEE;
	}
}
// The ally has a foe in contact and our bodies near it (me included) are at least DT2_MIN of the foes near it.
static __attribute__((always_inline)) inline bool assess_converge_worth(const Body& al)
{
	int foes = 0;
	bool contact = false;
	for (const auto& e : W.enemies)
	{
		const int de = cheb(e.pos, al.pos);
		foes += de <= tune::CONVERGE_R ? 1 : 0;
		contact |= de <= tune::CONVERGE_CONTACT_R;
	}
	if (!contact)
		return false;
	int ours = 1, weak = 0; // weak = near bodies below the mate's own bar (CONVERGE_ALLY_HP)
	for (const auto& o : W.allies)
	{
		const bool near = !o.channeling() && cheb(o.pos, al.pos) <= tune::CONVERGE_R;
		ours += near ? 1 : 0;
		weak += (near && o.frac() < tune::CONVERGE_ALLY_HP) ? 1 : 0;
	}
	CODE_ERR_FIX_CNT(4, weak > 0 && !(static_cast<float>(ours) < DT2_MIN * static_cast<float>(foes)) && static_cast<float>(ours - weak) < DT2_MIN * static_cast<float>(foes));
	return !(static_cast<float>(ours - weak) < DT2_MIN * static_cast<float>(foes));
}
// Bystanders 6-8 tiles from a team mate's fight get pushed into FLEE by the same foes and walk away, and the victim dies:
// a flee that is not caught and not in reach, with an ally in contact within CONVERGE_R, becomes a convergence on that ally.
static __attribute__((always_inline)) inline void assess_rule_converge(const AssessCtx& c)
{
	Assessment& a = c.a;
	if (a.stance != FLEE || a.caught || a.in_reach || W.me.frac() < tune::CONVERGE_MY_HP ||
		!(100.0f * a.ratio >= static_cast<float>(DT2_RATIO_X100))) // no convergence while carrying a big bag
		return;
	int bd = BIG;
	for (const auto& al : W.allies)
	{
		if (al.channeling() || al.frac() < tune::CONVERGE_ALLY_HP)
			continue;
		const int d = cheb(al.pos, c.me);
		if (d > tune::CONVERGE_R || d >= bd || !assess_converge_worth(al))
			continue;
		bd = d;
		a.converge = al.pos;
	}
	if (a.converge.x >= 0)
		a.stance = CALM;
}
// Our strength for a commit rule: me and the allies within r of at, each by its fight share against oc. camp_drain: awake camps
// hitting a body drain what it brings.
static __attribute__((always_inline)) inline float assess_commit_power(const Body* oc, vec2 at, int r, bool camp_drain)
{
	float fs = 0;
	{
		float h = 0, dd = 0;
		mates::add_friend(W.me, h, dd);
		mates::scale_by_focus_share(OFS_BIT_COMMIT, W.me, true, oc, dd, 1.0f);
		if (camp_drain)
			h = assess_drained(h, mu::mult_camp_hit_to_eff_hp(mv::camp_threat(W.me.pos)));
		fs += assess_power(h, dd);
	}
	for (const auto& o : W.allies)
		if (!o.channeling() && cheb(o.pos, at) <= r)
		{
			if (nova::combat::retreating_mates::retreating(o)) // a retreating mate counts 0
				continue;
			float h = 0, dd = 0;
			mates::add_friend(o, h, dd);
			if (camp_drain)
				h = assess_drained(h, mu::mult_mate_camp_hit_to_eff_hp(o, mates::camp_hit_strength_on_body(o, true)));
			mates::scale_by_focus_share(OFS_BIT_COMMIT, o, false, oc, dd, 1.0f);
			fs += assess_power(h, dd);
		}
	return fs;
}
// A mate within CT_R that was hit and hit back within COMMIT_ROUNDS (null: none).
static __attribute__((always_inline)) inline const Body* assess_trading_mate(vec2 me)
{
	for (const auto& al : W.allies)
	{
		if (al.slot < 0 || al.slot >= 8 || al.channeling() || cheb(al.pos, me) > CT_R)
			continue;
		const auto i = static_cast<std::size_t>(al.slot);
		if (W.round - peel_hit[i] <= tune::COMMIT_ROUNDS && W.round - ct_back[i] <= tune::COMMIT_ROUNDS)
			return &al;
	}
	return nullptr;
}
// A mate within CT_R hit and hitting back is not left alone.
static __attribute__((always_inline)) inline void assess_rule_commit_to_mate(const AssessCtx& c)
{
	Assessment& a = c.a;
	if (!((a.stance == FLEE && c.ct_soft) || a.stance == CALM) || a.caught || W.me.channeling() ||
		!(W.me.frac() * 100.0f >= static_cast<float>(CT_HP_PCT)) || static_cast<int>(W.me.gems) >= CR_BAG)
		return;
	const Body* mate = assess_trading_mate(c.me);
	if (!mate)
		return;
	const Body* oc = mates::ofs_want(OFS_BIT_COMMIT) ? mates::nearest_foe_to(mate->pos) : nullptr;
	const float fs = assess_commit_power(oc, c.me, CT_R, false);
	float es = 0;
	int fi = -1, fd = BIG;
	for (const auto& f : a.foes)
	{
		if (cheb(f.pos, c.me) > CT_R)
			continue;
		es += assess_foe_power(f);
		const int dm = cheb(f.pos, mate->pos);
		if (f.idx >= 0 && f.idx < static_cast<int>(W.enemies.size()) && dm < fd)
		{
			fd = dm;
			fi = f.idx;
		}
	}
	if (es > 0 && fi >= 0 && fs * fs * 100.0f >= static_cast<float>(CT_MIN_X100) * es * es)
		assess_fight_on(a, a.focus < 0 ? fi : a.focus);
}
// The rounds I have stood on this tile (runs every turn: the clock must see each round).
static __attribute__((always_inline)) inline int assess_rounds_on_tile(vec2 me)
{
	static vec2 sth_my_pos{ -1, -1 };
	static int sth_my_since = 0, sth_my_last = -10;
	if (sth_my_pos != me || sth_my_last < W.round - 1)
	{
		sth_my_pos = me;
		sth_my_since = W.round;
	}
	sth_my_last = W.round;
	return W.round - sth_my_since;
}
// The still foe e stands alone and we outweigh it there.
static __attribute__((always_inline)) inline bool assess_outweigh_still_foe(const Assessment& a, const Body& e)
{
	int others = 0;
	for (const auto& o : W.enemies)
		others += (o.h != e.h && o.hp > 0 && cheb(o.pos, e.pos) <= tune::STILL_ALONE_R) ? 1 : 0;
	if (others > 0)
		return false;
	const float fs = assess_commit_power(mates::ofs_want(OFS_BIT_COMMIT) ? &e : nullptr, e.pos, tune::STILL_ALONE_R, false);
	float es = 0;
	for (const auto& f : a.foes)
		if (cheb(f.pos, e.pos) <= tune::STILL_ALONE_R)
			es += assess_foe_power(f);
	return es > 0 && fs * fs >= es * es;
}
// Close on a lone foe that has not moved for several rounds (a recall spinner) when we outweigh it.
static __attribute__((always_inline)) inline void assess_rule_still_foe(const AssessCtx& c)
{
	Assessment& a = c.a;
	const int stood = assess_rounds_on_tile(c.me);
	if (stood < STH_SELF || a.stance == FIGHT || W.me.channeling() || W.me.frac() < tune::STILL_MY_HP ||
		static_cast<int>(W.me.gems) >= CR_BAG)
		return;
	for (std::size_t ei = 0; ei < W.enemies.size(); ++ei)
	{
		const auto& e = W.enemies[ei];
		if (e.hp <= 0 || cheb(e.pos, c.me) > STH_R || bbget(M.enemy_spawn, e.pos) || foe_model::still_rounds(e) < STH_ROUNDS)
			continue;
		if (assess_outweigh_still_foe(a, e))
		{
			assess_fight_on(a, static_cast<int>(ei));
			return;
		}
	}
}
// A low team mate with a visible foe that reaches it.
static __attribute__((always_inline)) inline bool assess_mate_chased(const Assessment& a, const Body& al)
{
	bool chased = false;
	if (al.frac() < PEEL2)
		for (const auto& f : a.foes)
			chased |= !f.remembered && f.reach >= 0 && cheb(f.pos, al.pos) <= f.reach;
	return chased;
}
// The foes' strength at the ally, and its nearest attacker I may pick (fi -1: none).
static __attribute__((always_inline)) inline void assess_peel_foes(const Assessment& a, const Body& al, float& es, int& fi)
{
	int fd = BIG;
	for (const auto& f : a.foes)
	{
		const int de = cheb(f.pos, al.pos);
		if (de > tune::PEEL_R)
			continue;
		es += (de <= tune::PEEL_NEXT_TO_R ? 1.0f : tune::PEEL_FAR_W) * assess_foe_power(f);
		if (f.idx >= 0 && de < fd && !assess_unreachable_pick(f))
		{
			fd = de;
			fi = f.idx;
		}
	}
}
// With an ally within PEEL_R under fire, the fight is judged at the ally's tile (our bodies within PEEL_R of it in full, foes within
// PEEL_R of it, those not next to it at PEEL_FAR_W) and at PEEL_MIN or better I FIGHT its nearest attacker; no later rule overrides
// this.
static __attribute__((always_inline)) inline void assess_rule_peel(const AssessCtx& c)
{
	Assessment& a = c.a;
	if (a.stance == FIGHT || W.me.frac() < tune::PEEL_MY_HP || W.me.channeling())
		return;
	int best_i = -1, best_d = BIG;
	int en_c = -1;        // fight_beside_worked_group(), computed on first need
	bool en_best = false; // the chosen peel holds on the strength of idle mates
	for (const auto& al : W.allies)
	{
		if (al.slot < 0 || al.slot >= 8 || al.channeling())
			continue;
		const int d = cheb(al.pos, c.me);
		const bool hit_now = W.round - peel_hit[static_cast<std::size_t>(al.slot)] <= tune::PEEL_HIT_ROUNDS;
		if (d > tune::PEEL_R || d >= best_d || (!hit_now && !assess_mate_chased(a, al)))
			continue;
		const Body* oc = mates::ofs_want(OFS_BIT_COMMIT) ? mates::nearest_foe_to(al.pos) : nullptr;
		const float fs = assess_commit_power(oc, al.pos, tune::PEEL_R, true);
		float es = 0;
		int fi = -1;
		assess_peel_foes(a, al, es, fi);
		const bool ally_low = al.frac() < PEEL2;
		const float pbar = ally_low ? PEEL2_MIN : PEEL_MIN;
		if (es <= 0 || fi < 0 || (fs * fs) < pbar * es * es)
			continue;
		if (ally_low && !hit_now && cheb(assess_enemy(fi).pos, c.me) > W.me.range + tune::PEEL_CHASER_STEPS)
			continue; // I cannot reach the chaser within two turns
		// next to a worked group, a peel below the hold bar needs idle mates within EN_HELP_R of the ally to make it favourable (they are
		// called: HELP); else no peel.
		bool helped = false;
		if (fs * fs * 100.0f < static_cast<float>(EN_HOLD_X100) * es * es)
		{
			if (en_c < 0)
				en_c = mates::fight_beside_worked_group() ? 1 : 0;
			if (en_c == 1)
			{
				const float fh = fs + mates::idle_mate_help_power(al.pos, tune::PEEL_R);
				if (fh * fh * 100.0f < static_cast<float>(EN_HOLD_X100) * es * es)
				{
					ENG_CNT(3);
					continue;
				}
				helped = true;
			}
		}
		en_best = helped;
		best_d = d;
		best_i = fi;
	}
	if (best_i >= 0 && !(::nova::econ::fight_help::peel_vetoes_target(assess_worst_ratio(a)))) // no mutual peel at a bad ratio
	{
		assess_fight_on(a, best_i);
		if (en_best)
		{
			turn_memory.help_round = W.round;
			ENG_CNT(4);
		}
	}
}
// With an enemy within PG_THREAT of our Prism carrying PG_BAG+ gems, a mate within PG_R of her with PG_MYHP_X100+ % health
// fights the enemy nearest her, at any power ratio.
static __attribute__((always_inline)) inline void assess_rule_prism_guard(const AssessCtx& c)
{
	Assessment& a = c.a;
	if (a.stance == FIGHT || W.me.channeling() || !(W.me.frac() * 100.0f >= static_cast<float>(PG_MYHP_X100)))
		return;
	const int ps = prism::prism_slot();
	const vec2 pz = (ps >= 0 && ps != P.my_slot && prism::bag_of_prism() >= PG_BAG) ? prism::pos_of_prism() : vec2{ -1, -1 };
	if (pz.x < 0 || cheb(pz, c.me) > PG_R)
		return;
	int fi = -1, fd = BIG;
	for (const auto& f : a.foes)
	{
		const int de = cheb(f.pos, pz);
		if (f.idx >= 0 && de <= PG_THREAT && de < fd && !assess_unreachable_pick(f))
		{
			fd = de;
			fi = f.idx;
		}
	}
	if (fi >= 0)
		assess_fight_on(a, fi);
}
// Camp-first rules 1-2: fleeing my live target at even power captures less than staying calm: engaged on my camp at the camp-first
// bar or better, not caught and not low, a flee becomes calm farming, or a fight back when a foe has me in reach.
static __attribute__((always_inline)) inline void assess_rule_camp_first(const AssessCtx& c)
{
	Assessment& a = c.a;
	if (a.stance == FLEE && !a.caught && W.me.frac() >= tune::CAMP_FIRST_MY_HP && econ::engaged_now() &&
		assess_worst_ratio(a) >= CAMP_FIRST_MIN)
		a.stance = assess_stand_stance(a);
}
// My reach this turn with a ready dash (no landing damage) or a ranged walk + reset.
static __attribute__((always_inline)) inline int assess_finish_reach(const Kit& kk)
{
	int reach = W.me.range + (kk.ranged ? 0 : 1);
	if (kk.ranged && kk.slot_reset >= 0 && ready(kk.slot_reset))
		reach = std::max(reach, W.me.range + 1);
	if (kk.slot_dash >= 0 && kk.dash_mod <= 0 && ready(kk.slot_dash))
		reach = std::max(reach, W.me.range + static_cast<int>(kk.dash_range) + (kk.ranged ? 0 : 1));
	return reach;
}
// Below an even balance only a foe I finish this turn, with at most FINISH_MAX_OTHERS other enemies next to it. fight() spends one
// cast a turn (a ready stun goes first, a dash or the reset buys reach, a damage spell replaces the reset hit), so commit only
// to a foe already in my attack range, with the turn's one cast counted once.
static __attribute__((always_inline)) inline bool assess_finish_sure(const Kit& kk, const Body& e, int de, int reach)
{
	if (de > reach || de > W.me.range)
		return false;
	float burst = W.me.str;
	if (!(kk.slot_cc >= 0 && ready(kk.slot_cc) && kk.cc_mod <= 0))
	{
		float extra = (kk.slot_reset >= 0 && ready(kk.slot_reset)) ? W.me.str : 0.0f;
		if (kk.slot_dmg >= 0 && ready(kk.slot_dmg) && de <= static_cast<int>(kk.dmg_range))
			extra = std::max(extra, kk.dmg_mod * W.me.foc);
		burst += extra;
	}
	if (burst * kit_rules::passive_mult(W.me) < eff_hp(e))
		return false;
	int others = 0;
	for (const auto& o : W.enemies)
		others += (&o != &e && cheb(o.pos, e.pos) <= tune::FINISH_NEXT_TO_R) ? 1 : 0;
	return others <= tune::FINISH_MAX_OTHERS;
}
// A visible foe below FINISH_LOW_HP within FINISH_R, with the balance even or better, me not low and carrying
// under FINISH_MAX_BAG gems, is the focus and a fight.
static __attribute__((always_inline)) inline void assess_rule_finish_low(const AssessCtx& c)
{
	Assessment& a = c.a;
	const bool fl_ratio = assess_worst_ratio(a) >= tune::EVEN_RATIO;
	if (W.me.frac() < tune::FINISH_MY_HP || W.me.gems >= tune::FINISH_MAX_BAG || W.me.channeling())
		return;
	if (!fl_ratio && W.me.frac() < tune::FINISH_ANY_RATIO_HP)
		return;
	if (c.kill_now && focus_still_killable(a.focus, burst::kill_now_reach()))
		return; // the kill this turn stands
	const Kit& kk = *W.me.kit;
	const int reach = assess_finish_reach(kk);
	int bi = -1;
	float bf = FINISH_LOW_HP;
	int fiar = -1; // foe_in_attack_range(c.me), loop-invariant: asked once (-1: not yet)
	for (std::size_t i = 0; i < W.enemies.size(); ++i)
	{
		const auto& e = W.enemies[i];
		const int de = cheb(e.pos, c.me);
		if (de > tune::FINISH_R || (XIC_ON(4) ? (e.frac() >= bf || foe_model::unreachable(e)) : (foe_model::unreachable(e) || e.frac() >= bf)))
			continue; // v723 XIC bit 4 FLR1: the HP share before unreachable() (pure tests, same result)
		if (de > reach && fiar < 0)
			fiar = foe_in_attack_range(c.me) ? 1 : 0;
		if (de > reach && fiar == 1)
			continue;
		if (!fl_ratio && !assess_finish_sure(kk, e, de, reach))
			continue;
		bf = e.frac();
		bi = static_cast<int>(i);
	}
	if (bi >= 0)
		assess_fight_on(a, bi);
}
// At my contested gem target, a non-caught FLEE of a healthy body holds while our side matches theirs there.
static __attribute__((always_inline)) inline void assess_rule_contest_hold(const AssessCtx& c)
{
	Assessment& a = c.a;
	if (a.stance == FLEE && !a.caught && W.me.frac() >= CTH_HP && !W.me.channeling() && mates::contested_gem_hold())
		a.stance = assess_stand_stance(a);
}
// No lone 1v3+ unless the kill lands now and I outlast their summed bursts.
static __attribute__((always_inline)) inline void assess_rule_no_lone_fight(const AssessCtx& c)
{
	Assessment& a = c.a;
	if (a.stance != FLEE && c.efc.allies4 == 0 && c.efc.near5 >= tune::LONE_NEAR5_MIN && !(c.kill_now && eff_hp(W.me) > c.efc.burst5))
		a.stance = FLEE;
}
static __attribute__((always_inline)) inline void assess_rule_hurt_outnumbered(const AssessCtx& c)
{
	Assessment& a = c.a;
	if (outnumbered_hurt_flee_wanted(a, c.kill_now))
	{
		a.stance = FLEE;
		if (W.round > ele_until)
			ele_until = W.round + ELE_TAB[6];
		ele_round = W.round;
	}
}
} // namespace
namespace {
// CB3 bit 8 KWS: a recall or tribute owner can cancel and act the same turn (GameRules.md:273-275), a teleport cannot. A recall stays a
// window when my hit lands this turn (damage interrupts it); a tribute only when I can stop it now: a stun that reaches and holds,
// a lock on its altar (within 2, GameRules.md:328; a walk first), or a kill.
static __attribute__((noinline)) bool kill_window_kws(const Body& f)
{
	if (f.stunned || (f.state & ST_TELEPORT))
		return true;
	if (!W.me.kit || !W.me.kit->valid)
		return false;
	const int d = cheb(f.pos, W.me.pos);
	if (f.state & ST_RECALL)
		return geom::my_burst(f, d) > 0.0f;
	if (!(f.state & ST_TRIBUTE))
		return false;
	const Kit& k = *W.me.kit;
	const int wk = W.can_move() ? 1 : 0;
	if (!W.cast && marcella_layer::fight_stun_holds(f) &&
		((k.slot_cc >= 0 && ready(k.slot_cc) && d <= static_cast<int>(k.cc_range) + (k.cc_excl ? 0 : wk)) ||
		 (k.aoe_stun && k.slot_aoe >= 0 && ready(k.slot_aoe) && d <= static_cast<int>(k.aoe_range + k.aoe_radius) + (k.aoe_excl ? 0 : wk)) ||
		 (k.dash_stun && k.slot_dash >= 0 && ready(k.slot_dash) && d <= static_cast<int>(k.dash_range + k.dash_radius) + wk)))
		return true;
	if (deny::locks_carried() > 0)
		for (const auto& al : M.altars)
			if (cheb(al.pos, f.pos) <= 1 && cheb(al.pos, W.me.pos) <= 2 + wk)
				return true;
	return burst::kills(f, d, 0);
}
} // namespace
// The focus is stunned or channelling (it cannot answer this turn): stepping in is free.
bool kill_window(const Body& f)
{
	if (!f.stunned && (f.state & (ST_TRIBUTE | ST_TELEPORT)) != 0) // bk5 KWC bit 1 (combat_flags.h): flag first
	{
		std::int32_t left = 0; // the channel completes at round + left (+1 when its owner already acted this round); unreadable: it holds
		if (cambc::detail::sdk_champion_channel_time(f.h, &left) == 0 && left >= 0 &&
			W.round + static_cast<int>(left) + ((f.state & FLEE_FIX_ST_ACTED) != 0 ? 1 : 0) <= W.round + 1)
			return false;
	}
	return kill_window_kws(f);
}
// The focus stands in the reach of an awake heavy camp (str >= CCH_STR) of a group that is not my
// target, and I stand outside that reach.
bool focus_under_other_heavy_camp(const Body& f)
{
	return false; // FB1 bit 16 CK2: the loop's result was never used (a baked flag-0 leftover)
}
// a CALM-side hit below the near balance bar starts a fight we lose, unless a foe in my reach is in a
// kill window or has a mate of ours within 3.
bool low_start_blocked()
{
	if (ls_ratio_near * 100.0f >= static_cast<float>(LOW_START_X100))
		return false;
	const int reach = std::max(W.me.range, W.me.kit ? static_cast<int>(std::max(W.me.kit->dmg_range, W.me.kit->cc_range)) : 1);
	for (const auto& e : W.enemies)
	{
		if (cheb(e.pos, W.me.pos) > reach + 1)
			continue;
		if (kill_window(e))
			return false;
		for (const auto& al : W.allies)
			if (cheb(al.pos, e.pos) <= 3)
				return false;
	}
	return true;
}
} // namespace stance
// The priority-message channel. Every function here runs only with its PRA bit set. msg17: bit 16 ASSIST (I am in FIGHT and count a
// mate within 6 with no visible foe within its range + 2), bits 15-13 foes I see within 8 (cap 7), bits 12-9 my HP fraction (16
// buckets), bits 8-0 their eff HP / 100 (cap 511).
int pra_raw = 0, pra_last = 0, pra_msg_turn = 0, pra_walk_r = -1000;
std::array<int, 6> pra_n{}; // diag: 0 ASSIST posts, 1 joins into FIGHT, 2 joins by walking, 3 merges, 4 mates decoded, 5 ASSIST seen
// The stance of this turn: gather what is near, weigh the two sides, pick the focus, set the bars, take the base stance, then the
// rules in order: each may override what came before it, so the order is part of the rules.
namespace cast { bool support_hold_back(const Body& f, int d); } // combat_cast.cc (WHB bit 1)
// CKF bit 1: the peel or the hunt leash turned Cassi's kite FLEE back to FIGHT; her stun is down and a melee foe is near, so she flees.
static void ckf_kite_flee(Assessment& a) { a.stance = FLEE; }
// CKF bit 2 (b1820, the one adaptation): bit 1's override only while a melee foe within the kite reach has a one-turn burst on
// Cassi (lethal_burst_hit, cooldowns as now; 0 if a stun takes its next turn) >= CKF_BURST_PCT % of her HP + shield.
constexpr int CKF_BURST_PCT = 25;
static __attribute__((noinline)) bool ckf_burst_heavy()
{
	const float cap = static_cast<float>(CKF_BURST_PCT) / 100.0f * (W.me.hp + std::max(0.0f, W.me.shield));
	const int g = nova::ci2::kite_reach();
	for (const auto& e : W.enemies)
	{
		if (!e.kit || e.kit->ranged)
			continue;
		const int d = cheb(e.pos, W.me.pos);
		if (d > g || burst::stun_takes_next_turn(e))
			continue;
		if (burst::lethal_burst_hit(e, d, 0, nullptr) >= cap)
			return true;
	}
	return false;
}
Assessment assess()
{
	AF_CHECK();
	Assessment a;
	const vec2 me = W.me.pos;
	turn_memory.help_round = -1000; // only the turn's last assessment calls for help
	stance::ls_ratio_near = 99.0f; // no balance from an old fight (a full assess writes this turn's below)
	stance::assess_gather_visible(a, me);
	stance::assess_gather_remembered(a, me);
	if (a.foes.empty())
		return a;
	stance::AssessCtx c{ a, me };
	stance::assess_sum_foes(c);
	stance::assess_team_mode(c);
	stance::assess_fight_shares(c);
	stance::assess_sum_me(c);
	stance::assess_sum_allies(c);
	stance::assess_sum_coming_mates(c);
	stance::assess_ratios(c);
	stance::assess_pick_focus(c);
	stance::assess_bars_headcount(c);
	stance::assess_bars_bag_and_support(c);
	stance::assess_carrier_cut(c);
	stance::assess_base_stance(c);
	if (a.stance == FIGHT && W.me.kit && willow_layer::me() && !c.kill_now && !a.in_reach && !a.caught && !took_damage(stance::tune::RECENT_HIT_ROUNDS) && !mates::ally_in_contact_within(a, static_cast<int>(W.me.kit->heal_range))) // WL2 decision 10: she never starts a fight, joins only in heal reach
		a.stance = CALM;
	stance::assess_hysteresis(c);
	stance::assess_rule_channels(c);
	stance::assess_rule_hit_back(c);
	stance::assess_rule_mate_dead(c);
	if (!CI2_FIGHT())
	{
		stance::assess_rule_ci_safe(c);
		stance::assess_rule_ci_melee_gap(c);
	}
	else if (a.stance != FLEE && !c.kill_now && nova::ci2::kite_now()) // CI2 KITE
		a.stance = FLEE;
	stance::assess_rule_local_power(c);
	stance::assess_rule_converge(c);
	stance::assess_rule_commit_to_mate(c);
	stance::assess_rule_still_foe(c);
	stance::assess_rule_peel(c);
	stance::assess_rule_prism_guard(c);
	stance::assess_rule_camp_first(c);
	stance::assess_rule_finish_low(c);
	stance::assess_rule_contest_hold(c);
	stance::assess_rule_no_lone_fight(c);
	if (a.stance == FIGHT && W.me.kit && willow_layer::me() && !c.kill_now && !a.in_reach && !a.caught && !took_damage(stance::tune::RECENT_HIT_ROUNDS) && !mates::ally_in_contact_within(a, static_cast<int>(W.me.kit->heal_range))) // BB34_ON bit 8 WL5: the override after the rules that raise FIGHT
		a.stance = CALM;
	if (!c.kill_now)
		burst::lethal_burst_assess(a);
	stance::assess_rule_hurt_outnumbered(c);
	stance::hunt_leash_assess(a);
	if (CI2_FIGHT() && a.stance != FLEE && !c.kill_now && nova::ci2::kite_now() && ckf_burst_heavy()) // CKF bit 2: only under a 25% burst
		ckf_kite_flee(a);
	burst::reach_burst_assess(a, c.kill_now);
	stance::ls_ratio_near = a.ratio_near;
	return a;
}
} // namespace nova::combat
