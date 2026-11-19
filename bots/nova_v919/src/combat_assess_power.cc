// combat_assess_power.cc: Assess, part 2: summing the power of both sides.
#include "combat_internal.h"
// b2315 HP2S bit 2 DMC1: the engine says this mate slot is dead now (one host call; called only with the flag on).
static inline bool hp2s_dead_ca(int s)
{
	std::int32_t al = 1;
	return cambc::detail::sdk_champion_is_alive(nova::P.handle[static_cast<std::size_t>(s)], &al) == 0 && al == 0;
}
namespace nova::combat {
namespace stance {
namespace {
// The visible foe at index i.
static __attribute__((always_inline)) inline const Body& assess_enemy(int i)
{
	return W.enemies[static_cast<std::size_t>(i)];
}
// The lock's memory runs on every turn with a foe in sight; the race only when its result could be used
// (fuel: 7-10k on peak turns without this).
static __attribute__((always_inline)) inline void hunt_track_lock()
{
	if (hold_state.lock_handle < 0)
		return;
	if (W.round - hold_state.lock_seen > 3) // v699 RCH bit 1 HL1: a lock unseen 4+ rounds (my death, recall, a lost foe) ends
	{
		hold_state.lock_handle = -1;
		return;
	}
	for (const auto& e : W.enemies)
		if (static_cast<int>(e.h) == hold_state.lock_handle)
		{
			hold_state.lock_seen = W.round;
			hd_lock_pos = e.pos;
		}
}
static __attribute__((always_inline)) inline void hunt_add_team_body(HdaCtx& c, const Body& b, bool isme, std::size_t k)
{
	if (b.channeling())
		return;
	const int tbr = std::max(b.range, b.kit ? static_cast<int>(std::max(b.kit->dmg_range, b.kit->cc_range)) : 1);
	const int reach = tbr;
	c.team[static_cast<std::size_t>(c.n_team++)] = { &b, b.pos, reach + tune::HD_TEAM_STEPS, k, isme };
}
// The first foe in range: the bodies with me, the foes' damage on me, my side's bodies.
static __attribute__((always_inline)) inline void hunt_first_contact(HdaCtx& c)
{
	c.nm = 1;
	for (const auto& al : W.allies)
		c.nm += cheb(al.pos, c.me) <= tune::HD_MATES_R;
	c.inc_me = 0.0f;
	for (const auto& f : c.a.foes)
	{
		if (cheb(f.pos, c.me) > f.reach + tune::HD_REACH_STEPS)
			continue;
		c.inc_me += (c.fs_foe ? dmg::foe_hd_dps(f) * dmg::dps_fs_foe(cheb(f.pos, c.me)) : dmg::foe_hd_dps(f));
	}
	hunt_add_team_body(c, W.me, true, 0);
	std::size_t k = 1;
	for (const auto& al : W.allies)
		if (c.n_team < 9)
			hunt_add_team_body(c, al, false, k++);
		else
			++k;
}
// What stands beside the target i: ne = the other foes there, inc += the damage of those that do not reach me yet.
static __attribute__((always_inline)) inline void hunt_foes_at_target(const HdaCtx& c, const Body& e, std::size_t i, int& ne, float& inc)
{
	for (const auto& f : c.a.foes)
	{
		if (cheb(f.pos, e.pos) > tune::HD_TARGET_FOES_R)
			continue;
		if (cheb(f.pos, c.me) > f.reach + tune::HD_REACH_STEPS)
			inc += (c.fs_foe ? dmg::foe_hd_dps(f) * dmg::dps_fs_foe(cheb(f.pos, c.me)) : dmg::foe_hd_dps(f));
		if (f.idx != static_cast<int>(i))
			++ne;
	}
}
// One body's damage rate, through team_focus's memo (same bodies, same W).
static __attribute__((always_inline)) inline float hunt_body_dps(const HdaTeamBody& te)
{
	if (te.k >= hold_state.memo.size())
		return dmg::horizon_dps1(*te.b, te.me);
	float& m = hold_state.memo[te.k];
	if (m < 0.0f)
		m = dmg::horizon_dps1(*te.b, te.me);
	return m;
}
static __attribute__((always_inline)) inline float hunt_team_dps(const HdaCtx& c, const Body& e)
{
	float tdps = 0.0f;
	for (int q = 0; q < c.n_team; ++q)
	{
		const HdaTeamBody& te = c.team[static_cast<std::size_t>(q)];
		if (cheb(te.p, e.pos) > te.r)
			continue;
		const float m = hunt_body_dps(te);
		tdps += c.fs_our ? m * dmg::dps_fs_ours(te.me, cheb(te.p, e.pos)) : m;
	}
	return tdps;
}
// The target's score, lowest first (the channel bonus comes after: it needs a fresh_recall).
static __attribute__((always_inline)) inline float hunt_target_score(const Body& e, int d, int ne, float kt, bool lock)
{
	const int steps = std::max(0, d - W.me.range);
	int bag = static_cast<int>(e.gems);
	if (ci_layer::type(e.type)) // a kill on either linked body takes both bags (GameRules:381)
		for (const auto& o : W.enemies)
			if (&o != &e && o.type == ci_layer::partner(e.type))
				bag += static_cast<int>(o.gems);
	const int gems = std::min<int>(tune::HD_GEM_CAP, bag);
	float s = kt + tune::HD_STEP_COST * static_cast<float>(steps) + tune::HD_FOE_COST * static_cast<float>(ne);
	s -= (ne == 0 ? tune::HD_ALONE_BONUS : 0.0f) + tune::HD_GEM_BONUS * static_cast<float>(gems) + (lock ? tune::HD_LOCK_BONUS : 0.0f);
	return s;
}
// The foe with a won race and the lowest score (-1: none).
static __attribute__((always_inline)) inline int hunt_pick_target(HdaCtx& c)
{
	const Assessment& a = c.a;
	int best_i = -1;
	float best = 1e9f;
	const int nen = static_cast<int>(W.enemies.size());
	const int first = c.any_will_do && a.focus < nen ? a.focus : 0; // order only matters for ties in the choice, which isn't used in that case
	for (int q = 0; q < nen; ++q)
	{
		const std::size_t i = static_cast<std::size_t>(q == 0 ? first : (q <= first ? q - 1 : q));
		const auto& e = W.enemies[i];
		const int d = cheb(e.pos, c.me);
		if (d > tune::HD_RANGE)
			continue;
		if (c.nm < 0)
			hunt_first_contact(c);
		int ne = 0;
		float inc = c.inc_me;
		hunt_foes_at_target(c, e, i, ne, inc);
		const bool fh_e = c.fh && e.frac() <= tune::HD_FINISH_FOE_HP && d <= my_next_hit_reach(); // this foe can be a finish
		if (c.fh && a.ratio < tune::HD_FLEE_RATIO && !fh_e)
			continue;
		if (ne >= c.nm + (e.frac() < tune::HD_WEAK_FOE_EXTRA ? 1 : 0))
			continue;
		const float tdps = hunt_team_dps(c, e);
		const float kt = eff_hp(e) / std::max(1.0f, std::max(tune::HD_MIN_TEAM_DPS, tdps));
		const float lt = c.my_ehp / std::max(1.0f, inc);
		const bool lock = static_cast<int>(e.h) == hold_state.lock_handle && (W.round - hold_state.lock_seen <= 3); // v699 RCH bit 1 HL1
		const float margin = (PSV_HDRACE + (lock ? tune::HD_LOCK_MARGIN : 0.0f)) / 100.0f;
		if (kt > lt * margin + 1.0f)
			continue; // whole turns and turn order
		if (c.fh && a.ratio < tune::HD_FLEE_RATIO && kt * 10.0f > static_cast<float>(FH_TAB[2]))
			continue;
		float s = hunt_target_score(e, d, ne, kt, lock);
		const bool ch = e.channeling();
		if (ch && !foe_model::fresh_recall(e))
			s -= tune::HD_CHANNEL_BONUS;
		if (s < best && (ch || (!mates::enemy_spawn_near(e.pos, NOCHASE_R) && (d <= W.me.range || spz_kill_in_hand(e, kt))))) // the spawn test last: it is the costly one; v854 SPZ bit 1 form B: no hunt out of reach without the kill in hand
		{
			best = s;
			best_i = static_cast<int>(i);
			if (c.any_will_do)
				break;
		}
	}
	return best_i;
}
// A fight with a focus keeps its target (the lock takes it if free); anything else turns on the chosen foe.
static __attribute__((always_inline)) inline void hunt_apply_target(Assessment& a, int best_i)
{
	if (a.stance == FIGHT && a.focus >= 0)
	{
		if (hold_state.lock_handle < 0)
		{
			hold_state.lock_handle = static_cast<int>(assess_enemy(a.focus).h);
			hold_state.lock_seen = W.round; // v699 RCH bit 1 HL1: a new lock is fresh
		}
		hold_state.active_round = W.round;
		return;
	}
	a.stance = FIGHT;
	a.focus = best_i;
	hold_state.lock_handle = static_cast<int>(assess_enemy(best_i).h);
	hold_state.lock_seen = W.round;
	hd_lock_pos = assess_enemy(best_i).pos;
	hold_state.active_round = W.round;
}
// HUNT LEASH: per turn, a kill race on each visible foe: the team's turns to kill it against my turns to live next to what is near it.
// A won race keeps (or takes) the target through a chase, CALM or soft FLEE. Never into more bodies than are with me, never at a
// low HP or a big bag.
void hunt_leash_assess(Assessment& a)
{
	if (W.enemies.empty() || !W.alive || !W.me.kit || W.me.channeling() || willow_layer::hunt_skip() || fuel() < HUNT_TAB[2])
		return;
	const float fr = W.me.frac();
	const int bag = static_cast<int>(W.me.gems);
	hunt_track_lock();
	if (a.stance == FLEE && lethal_spot.round == W.round)
		return; // the leash doesn't undo LETHAL_BURST's flee
	if (a.stance == FLEE && ele_round == W.round)
		return; // nor this one
	const float my_ehp = eff_hp(W.me);
	const bool fh = a.stance == FLEE && flee_race_allowed(a, fr, bag, my_ehp);
	if (bag >= static_cast<int>(PS_TAB[17]) || fr < tune::HD_LOW_HP || a.incoming >= my_ehp ||
		(a.stance == FLEE && a.ratio < tune::HD_FLEE_RATIO && !fh))
		return;
	const bool any_will_do = a.stance == FIGHT && a.focus >= 0 && fr >= PSV_HDFR / 100.0f;
	if (hold_state.memo_round != W.round)
	{
		hold_state.memo.fill(-1.0f);
		hold_state.memo_round = W.round;
	}
	HdaCtx c(a, W.me.pos, my_ehp, fh, any_will_do, DPS_TAB[1]);
	const int best_i = hunt_pick_target(c);
	if (best_i < 0 || fr < (assess_enemy(best_i).frac() < tune::HD_WEAK_FOE_HP ? tune::HD_LOW_HP : PSV_HDFR / 100.0f))
		return;
	hunt_apply_target(a, best_i);
}
// The focus k still dies to my reach this turn (assess's kill_now test, re-read: a rule after it may
// have moved the focus).
static bool focus_still_killable(int k, int kreach)
{
	if (k < 0 || k >= static_cast<int>(W.enemies.size()))
		return false;
	const Body& f = W.enemies[static_cast<std::size_t>(k)];
	const int d = cheb(f.pos, W.me.pos);
	return KQ_SITE(1, burst::kills(f, d, 0), (d <= kreach && eff_hp(f) <= geom::my_burst(f, d) && burst::dash_kill_reachable(f, d)) || burst::spell_alone_kills(f, d));
}
// a foe stands in my attack range now.
static bool foe_in_attack_range(vec2 me)
{
	for (const auto& e : W.enemies)
		if (cheb(e.pos, me) <= W.me.range && !foe_model::unreachable(e) && !bbget(M.enemy_spawn, e.pos))
			return true;
	return false;
}
// One body's term in a side's strength: sqrt(health x damage). Equal bodies give Lanchester's square law, and a nearly dead
// body adds little.
static __attribute__((always_inline)) inline float assess_power(float h, float d)
{
	return std::sqrt(std::max(1.0f, h) * std::max(1.0f, d));
}
static __attribute__((always_inline)) inline float assess_foe_power(const Foe& f)
{
	return assess_power(f.ehp, f.dps);
}
// Damage from awake camps comes off the health a body brings to a fight.
static __attribute__((always_inline)) inline float assess_drained(float h, float camp_hits)
{
	return std::max(1.0f, h - camp_hits * tune::CAMP_DRAIN);
}
static __attribute__((always_inline)) inline float assess_worst_ratio(const Assessment& a)
{
	return std::min(a.ratio, a.ratio_near);
}
// The foe can join the fight soon.
static __attribute__((always_inline)) inline bool assess_soon_in_reach(const Foe& f, int d)
{
	return d <= std::max(f.reach, tune::SOON_REACH_MIN) + tune::SOON_REACH_STEPS;
}
static __attribute__((always_inline)) inline float assess_bag_share(int bag)
{
	return std::min(1.0f, static_cast<float>(bag) / tune::BAG_FULL);
}
// The rule's fight on this focus, which also ends a convergence.
static __attribute__((always_inline)) inline void assess_fight_on(Assessment& a, int focus)
{
	a.stance = FIGHT;
	a.focus = focus;
	a.converge = { -1, -1 };
}
// A flee that a rule stops: fight back when a foe has me in reach, else stay calm.
static __attribute__((always_inline)) inline Stance assess_stand_stance(const Assessment& a)
{
	return (a.in_reach && a.focus >= 0) ? FIGHT : CALM;
}
static __attribute__((always_inline)) inline bool assess_unreachable_pick(const Foe& f)
{
	return static_cast<bool>(foe_model::unreachable(assess_enemy(f.idx)));
}
static __attribute__((always_inline)) inline void assess_push_foe(Assessment& a, const Foe& f)
{
	if (a.foes.empty())
		a.foes.reserve(tune::FOE_RESERVE);
	a.foes.push_back(f);
}
// ---- gather the foes
static __attribute__((always_inline)) inline void assess_gather_visible(Assessment& a, vec2 me)
{
	const int crdx_fs = CRDX_TAB[1]; // CRDX: foe sight radius (shipped v753: 11)
	const int crdx_tr = CRDX_TAB[2]; // CRDX: threat radius (shipped v753: 4)
	for (std::size_t i = 0; i < W.enemies.size(); ++i)
	{
		const auto& e = W.enemies[i];
		const int d = cheb(e.pos, me);
		const bool ur = d <= crdx_fs && foe_model::unreachable(e); // CRDX_FS
		if (d > crdx_fs || ur) // CRDX_FS
			continue;
		Foe f = foe_of(e, static_cast<int>(i));
		a.nearest = std::min(a.nearest, d);
		assess_push_foe(a, f);
		if (!ur)
			AF_CHECK();
		if (d <= crdx_tr) // CRDX_TR
		{
			if (a.threats.empty())
				a.threats.reserve(tune::FOE_RESERVE);
			a.threats.push_back(e.pos);
		}
	}
}
// Enemies that left vision a moment ago near me (bushes, around a corner) still count, where last seen.
static __attribute__((always_inline)) inline void assess_gather_remembered(Assessment& a, vec2 me)
{
	const int now = W.round;
	for (const auto& s : seen)
	{
		if (s.round == now || now - s.round > tune::MEMORY_ROUNDS || cheb(s.foe.pos, me) > tune::MEMORY_R)
			continue;
		bool visible = false;
		for (const auto& e : W.enemies)
			if (e.h == s.h)
				visible = true;
		if (visible)
			continue;
		Foe f = ttc_remembered(s, now - s.round); // b2387 TTCX bit 1: cooldowns run out since the sighting
		if (bbget(M.enemy_spawn, f.pos)) // v7xx MBB7 RHS1 (RC X474): last seen on its spawn, healed to full since (GR:124/153)
			f.ehp = s.ehp_full;
		f.idx = -1;
		f.remembered = true;
		// Only a very recent sighting can threaten me next turn; older ones still weigh in the fight balance.
		f.reach = now - s.round <= tune::MEMORY_REACH_ROUNDS ? f.reach + (now - s.round) : -1;
		assess_push_foe(a, f);
	}
}
// ---- the two sides' strength. Foes get the discounts ally_commit_weight gives a farming ally (else two of ours against two of theirs, all
// farming, score ~0.5 and we flee): a symmetric-fight discount with none of us within SYM_CONTACT_R of it, CAMP_BUSY_W more while it
// stands next to an awake camp.
static __attribute__((always_inline)) inline float assess_foe_weight(const Assessment& a, const Foe& f, int d)
{
	int dn = d;
	if (W.round - turn_memory.last_flee_round <= tune::HYST_ROUNDS) // SFS bit 1: a foe the tile I just left touched keeps full weight
		dn = std::min(dn, cheb(f.pos, turn_memory.sfs_from));
	for (const auto& al : W.allies)
	{
		dn = std::min(dn, cheb(f.pos, al.pos));
		if (dn <= tune::SYM_CONTACT_R)
			return 1.0f;
	}
	if (dn <= tune::SYM_CONTACT_R)
		return 1.0f;
	float fw = (static_cast<float>(B467_SYM_X100) / 100.0f);
	if (assess_soon_in_reach(f, d))
	{
		int pack = 0;
		for (const auto& g : a.foes)
		{
			pack += cheb(g.pos, f.pos) <= tune::PACK_R ? 1 : 0;
			if (pack >= tune::PACK_N)
				break;
		}
		if (pack >= tune::PACK_N)
			fw = 1.0f; // a foe that can reach me soon counts in full; BEF bit 64 (row 685): a lone one too
	}
	for (const int q : memory::awake_slots()) // the awake camps only, same order
		if (cheb(M.camps[static_cast<std::size_t>(W.camps[static_cast<std::size_t>(q)].ci)].pos, f.pos) <= tune::CAMP_BUSY_R)
			return fw * tune::CAMP_BUSY_W;
	return fw;
}
// BB13 bit 1: a melee foe cannot hit me on my spawn tile t unless it can stand on a free non-spawn tile within its range of t this turn
// (its move allowance = reach - range). Remembered foes are left as they are.
static __attribute__((noinline)) bool bb13_spawn_shield(const Foe& f, vec2 t)
{
	if (!f.melee || f.remembered || f.idx < 0)
		return false;
	return burst::bb13_body_shielded(assess_enemy(f.idx), t);
}
// Fight strength of a side: (sum of sqrt(health x damage))^2. This sums the foes' side, counts them, and reads who has me in reach.
static __attribute__((always_inline)) inline void assess_sum_foes(AssessCtx& c)
{
	Assessment& a = c.a;
	for (const auto& f : a.foes)
	{
		const int d = cheb(f.pos, c.me);
		if (d > tune::FIGHT_R)
			continue;
		++a.n_foes;
		const float fw = assess_foe_weight(a, f, d);
		const float v = fw * assess_foe_power(f);
		c.e_h += fw * std::max(1.0f, f.ehp);
		const float v_fc = fw * assess_power(f.ehp, f.dps_fc); // the refit foe kits (and unseen reinforcements)
		c.e_sq += v;
		c.e_sq_fc += v_fc;
		if (assess_soon_in_reach(f, d))
			c.e_near += v;
		if (CI2_FIGHT()) // CI2 decision 6: a foe pair counts once, the lower health and both damages (the difference to the lines above)
		{
			const Foe* pf = nullptr;
			if (f.idx >= 0 && ci_layer::type(W.enemies[static_cast<std::size_t>(f.idx)].type))
				for (const auto& g : a.foes)
					if (g.idx >= 0 && W.enemies[static_cast<std::size_t>(g.idx)].type == ci_layer::partner(W.enemies[static_cast<std::size_t>(f.idx)].type) && cheb(g.pos, c.me) <= tune::FIGHT_R)
					{
						pf = &g; // champions are unique per team (GameRules.md:63): at most one partner
						break;
					}
			if (pf)
			{
				const bool first = f.idx < pf->idx;
				const float fe = std::min(f.ehp, pf->ehp);
				const float dv = (first ? fw * assess_power(fe, f.dps + pf->dps) : 0.0f) - v;
				c.e_sq += dv;
				c.e_sq_fc += (first ? fw * assess_power(fe, f.dps_fc + pf->dps_fc) : 0.0f) - v_fc;
				if (assess_soon_in_reach(f, d))
					c.e_near += dv;
			}
		}
		if (d <= f.reach && bb13_spawn_shield(f, c.me)) // BB13 bit 1: no hit onto my spawn tile from here
			continue;
		if (d <= f.reach)
		{
			BH81_CNT(0, f.idx >= 0 && !f.remembered && assess_enemy(f.idx).stunned);
			a.in_reach = true;
			a.incoming += (f.burst);
		}
		if (!f.remembered && f.melee && d + 1 <= f.reach)
			a.caught = true;
	}
}
// With a support near, allies a little further away still join (the pack fights around her).
static __attribute__((always_inline)) inline void assess_team_mode(AssessCtx& c)
{
	c.tfm = team_fight_mode(c.me);
	c.join_r = c.tfm ? tune::JOIN_R_TEAM : tune::JOIN_R;
}
// team_focus moves up here (it reads W only), and is not called again below.
static __attribute__((always_inline)) inline void assess_fight_shares(AssessCtx& c)
{
	c.ofs_any = mates::ofs_want(OFS_BIT_ALL);
	c.ofs_fc = c.ofs_any ? team_focus(tune::FIGHT_R) : -1;
	if (c.ofs_any)
	{
		focus_share.round = W.round;
		focus_share.focus_handle = c.ofs_fc >= 0 ? static_cast<int>(assess_enemy(c.ofs_fc).h) : -1;
	}
	c.oe = !mates::ofs_want(OFS_BIT_ASSESS) ? nullptr : c.ofs_fc >= 0 ? &assess_enemy(c.ofs_fc) : mates::nearest_foe_to(c.me);
}
static __attribute__((always_inline)) inline void assess_add_power(AssessCtx& c, float w, float h, float d)
{
	c.f_sq += w * assess_power(h, d);
	c.f_h += w * std::max(1.0f, h);
}
static const Body* ci2_merged = nullptr; // CI2: the partner counted in assess_sum_me this assess
static __attribute__((always_inline)) inline void assess_sum_me(AssessCtx& c)
{
	float h = 0, d = 0;
	mates::add_friend(W.me, h, d);
	ci2_merged = nullptr;
	if (CI2_FIGHT())
	{
		h = nova::ci2::link_friend_h(W.me, h, c.a); // CI2 decision 6: the lower of the pair's health
		if (const Body* pb = nova::ci2::merged_partner(static_cast<float>(c.join_r))) // the pair counts once: the lower health, both bodies' damage
		{
			float ph = 0, pd = 0;
			mates::add_friend(*pb, ph, pd);
			if (::nova::combat::retreating_mates::retreating(*pb)) // MPR: a partner posting FLEE
			{
				ci2_merged = pb; // RC C609 MPR-F1: still merged, so assess_sum_allies does not re-add it (bit 1: it counts 0)
			}
			else
			{
				d += pd;
				ci2_merged = pb;
			}
		}
	}
	mates::scale_by_focus_share(OFS_BIT_ASSESS, W.me, true, c.oe, d, 1.0f);
	h = assess_drained(h, mu::mult_camp_hit_to_eff_hp(mv::camp_threat(c.me)));
	AF_CHECK();
	assess_add_power(c, 1.0f, h, d);
	c.me_h = h;
}
static __attribute__((always_inline)) inline void assess_sum_allies(AssessCtx& c)
{
	Assessment& a = c.a;
	for (const auto& al : W.allies)
	{
		if (al.channeling() || cheb(al.pos, c.me) > c.join_r)
			continue;
		if (CI2_FIGHT() && &al == ci2_merged)
			continue; // CI2: merged into my own strength above
		float h = 0, d = 0;
		mates::add_friend(al, h, d);
		AF_CHECK();
		const float ch = mu::mult_mate_camp_hit_to_eff_hp(al, mates::camp_hit_strength_on_body(al, true));
		if (ch > 0)
		{
			h = assess_drained(h, ch);
			ENG_CNT(15);
		}
		const float w = mates::ally_commit_weight(al, a);
		mates::scale_by_focus_share(OFS_BIT_ASSESS, al, false, c.oe, d, w);
		assess_add_power(c, w, h, d);
		++a.n_friends;
	}
}
// A mate on its way, out of my sight, as a Body at p: its kit grown by round, or what I last saw of it.
static __attribute__((always_inline)) inline void assess_coming_body(Body& mb, int s, const Kit& k, vec2 p)
{
	const float gf = 1.0f; // b2140 CGW1: no round growth (fallback, post-death floor)
	mb.ally = true;
	mb.slot = s;
	mb.type = P.type[static_cast<std::size_t>(s)];
	mb.kit = &k;
	mb.pos = p;
	mb.maxhp = k.hp * ((1.0f - tune::GROW_HP_SHARE) + tune::GROW_HP_SHARE * gf);
	mb.str = k.str * gf;
	mb.foc = k.foc * gf;
	if (mu::bits != 0)
	{
		float ls_s = 0, ls_f = 0, ls_h = 0;
		bool ls_d = false;
		if (econ::mul_mate_ls(s, ls_s, ls_f, ls_h, ls_d)) // b2140 CGW1: last-seen, not round-grown
		{
			// last-seen stats are exact until a shop (spawn or death; GameRules.md:279); seen dead since: no less than last seen, the growth
			// model as a floor
			mb.maxhp = ls_d ? std::max(mb.maxhp, ls_h) : ls_h;
			mb.str = ls_d ? std::max(mb.str, ls_s) : ls_s;
			mb.foc = ls_d ? std::max(mb.foc, ls_f) : ls_f;
		}
		if (mu::on(mu::B_PAIR | mu::B_FULL)) // its emblem multipliers, as a visible body
		{
			mb.h = P.handle[static_cast<std::size_t>(s)];
			mu::fill(mb, W.round, false); // not a sighting
		}
	}
	mb.hp = mb.maxhp * tune::COMING_HP;
	mb.range = k.range;
}
// A fresh HELP call: the mates who claim they are coming, at the tile their claim gives, join my side within join_r.
static __attribute__((always_inline)) inline void assess_sum_coming_mates(AssessCtx& c)
{
	const comms::Event ev = comms::ev();
	const int eage = (W.round - ev.stamp) & comms::STAMP_MASK;
	if (ev.subject < 0 || ev.type != comms::EV_TYPE_HELP || eage > tune::HELP_AGE)
		return;
	const int hc = comms::help_c(), cw = (G.w + hc - 1) / hc;
	const vec2 at{ std::min<int>((ev.subject % cw) * hc + hc / 2, G.w - 1), std::min<int>((ev.subject / cw) * hc + hc / 2, G.h - 1) };
	static constexpr int ox[8] = { 1, 1, 0, -1, -1, -1, 0, 1 }, oy[8] = { 0, 1, 1, 1, 0, -1, -1, -1 };
	for (int s = 0; s < P.n && s < comms::CLAIM_SLOTS; ++s)
	{
		if (s == P.my_slot || comms::ckind(s) != tune::COMING_CLAIM || W.ally_by_slot(s))
			continue;
		const int v = comms::cval(s);
		if ((v >> 4) > comms::FL_TAB[6] || (v & 1) != 0)
			continue;
		const int o = (v >> 1) & 7, dd0 = (v >> 4) == 0 ? tune::COMING_NEAR : tune::COMING_FAR;
		const vec2 p{ std::clamp(at.x + dd0 * ox[o], 0, G.w - 1), std::clamp(at.y + dd0 * oy[o], 0, G.h - 1) };
		if (cheb(p, c.me) > c.join_r)
			continue;
		if (hp2s_dead_ca(s))
			continue; // b2315 HP2S bit 2 DMC1: a mate killed after its turn is not coming
		const Kit& k = kit_of(P.type[static_cast<std::size_t>(s)]);
		Body mb{};
		assess_coming_body(mb, s, k, p);
		float h = 0, dd = 0;
		mates::add_friend(mb, h, dd);
		const float w = static_cast<float>(comms::FL_TAB[5]) / 100.0f;
		mates::scale_by_focus_share(OFS_BIT_ASSESS, mb, false, c.oe, dd, w);
		assess_add_power(c, w, h, dd);
	}
}
} // namespace
} // namespace stance
} // namespace nova::combat
