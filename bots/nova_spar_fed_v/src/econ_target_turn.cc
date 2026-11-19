// econ_target_turn.cc: One target turn: walk, wait, engage.
#include "econ_internal.h"
namespace nova::econ {
namespace {
int st_gi = -1, st_n = 0; // target_turn (hoisted statics: shared by both instantiations)
static int uw_gi = -1, uw_round = -10; // the group and round of my last walk to an out-of-sight member
int rw_gi = -1; // the group whose out-of-sight member I walk to
int at_gi = -1, at_round = -10;
// a solo chip trip while group wait_gi respawns in `left` rounds: an unclaimed, quiet, own-side (contest <= CR_CONTEST_X100)
// walkable group with living attackers within FRL_WR walk, where my solo share of what is left (estimate()'s clear, cut at the bail
// line and at the budget left + 15 - 2 x walk) is >= 25%. Progress stays in mem.hp_left.
static int frl_chip_gi = -1, frl_chip_until = -1000;
static int lfe_n = 0; // low-fuel turns running with no action
// ---------------------------------------------------------------- the target turn


template <int DM>
void prism_route_to_plan_groups();
bool mate_waits_for_prism_capture(int gi);
static bool pc_keeps_bag(int on);
// a shop or heal is due, so a travel recall pays twice (no enemy within RTS_FOE).
static bool travel_recall_shop_due()
{
	if (GAME_END - now() <= EG_ROUNDS || (W.me.gems > 0 && finish_mode(0)))
		return false;
	if (M.ring && ring_gap && W.me.gems >= 10 && bank_dist_here() <= 8)
		return false; // the bag goes in through the gap first
	for (const auto& e : W.enemies)
		if (cheb(e.pos, W.me.pos) <= RTS_FOE)
			return false;
	const bool shop = !tavi_layer::recall_skip_shop() && static_cast<int>(W.gold) >= RTS_GOLD && !(fsr_blocks_shop(static_cast<int>(W.gold))); // FSR bit 1 (b1769)
	return shop || W.me.frac() * 100.0f < static_cast<float>(RTS_HP100);
}
// No travel recall while my crystal trip to this group is under way: the walk to the launch tile leads away from the group, d grows
// past the spawn's walk and the recall would fire mid-trip. Called only after the old travel-recall test passed. d is my walk in
// group gi's field (other camps blocked); the recall's walk from our spawn must come from the same field: the nearest spawn tile's
// value.
static bool travel_recall_same_field(int gi, int d, int margin)
{
	if (sc_trip_live(0) && SC.gi == gi && now() <= SC.until)
		return false; // the crystal trip is the faster route
	return true;
}
// the crew-incomplete wait of a group with a claimant away goes to the group's rally tile, where every claimant gathers and sees the
// others (crew_here counts allies in sight only). False when the group has no rally tile.
__attribute__((noinline)) bool wait_at_rally_tile(int gi)
{
	if (siege_rally_tile(gi).x < 0)
		return false;
	dbg_path = 46;
	planner::stat_wait(1);
	if (!siege_at_rally(gi) && !siege_walk_to_rally(gi))
		stage_near(gi);
	else
		last_act = ACT_WAIT;
	return true;
}
// target_turn: next to a hidden member and it still is not in sight.
__attribute__((always_inline)) inline bool target_turn_look_from_bush(int gi, GroupMem& m, vec2 best)
{
	// A gold cluster in a bush: from outside a bush nothing sees into it, so a walk "toward" it would stand still next to it, on its
	// partner's spawn tile, where that camp could not respawn either. Look from a bush tile next to it (a body in a bush sees the
	// bush), else step off the member tiles and leave the group for a while.
	st_n = st_gi == gi ? st_n + 1 : 1;
	st_gi = gi;
	// bush clusters link only cardinally (Q44): a cardinal neighbour of the target first, then a diagonal one only with a cardinal bush
	// link between them (else it sees nothing new).
	for (int pass = 0; pass < 2; ++pass)
		for (int di = pass; di < 8; di += 2)
		{
			const vec2 dd = DIRS[static_cast<std::size_t>(di)];
			const vec2 q = best + dd;
			if (!inb(q) || !bbget(M.bushes, q) || !mv::free_tile(q) || cheb(q, W.me.pos) > 1)
				continue;
			if (pass == 1 && !bbget(M.bushes, vec2{ best.x + dd.x, best.y }) && !bbget(M.bushes, vec2{ best.x, best.y + dd.y }))
			{
				KIT_RULE_FIX_CNT(4, true); // A diagonal-only bush sees nothing of the target's.
				continue;
			}
			if (mv::try_move(q))
				return true;
		}
	if (st_n >= 6)
	{
		st_n = 0;
		m.fail_until = std::max(m.fail_until, now() + 60);
		drop_target(0);
		return false;
	}
	respawn_stage(gi);
	return true;
}
// target_turn: the group field ends at the dead members I stand next to: walk toward the nearest member out of sight
// (a long row of clusters is longer than my vision).
__attribute__((always_inline)) inline bool target_turn_walk_to_hidden_member(int gi, const GroupI& g, GroupMem& m)
{
	dbg_path = 30;
	// The group field ends at the dead members I stand next to: walk toward the nearest member out of sight
	// (a long row of clusters is longer than my vision).
	vec2 best{ -1, -1 };
	int bd = BIG;
	const bool rw_keep = rw_gi == gi && rw_tile.x >= 0;
	if (rw_keep && !bbget(W.vis, rw_tile))
	{
		best = rw_tile;
		bd = cheb(rw_tile, W.me.pos);
	}
	else
	{
		int bk = BIG;
		for (int ci : g.members)
		{
			const vec2 p = M.camps[static_cast<std::size_t>(ci)].pos;
			if (bbget(W.vis, p))
				continue;
			const int key = rw_keep ? cheb(p, rw_tile) : cheb(p, W.me.pos); // v2: continue the sweep from the kept member
			if (key < bk)
			{
				bk = key;
				best = p;
			}
		}
		if (best.x >= 0)
			bd = cheb(best, W.me.pos);
	}
	rw_gi = gi;
	rw_tile = best;
	last_act = ACT_WALK;
	if (best.x >= 0 && bd <= 1)
		return target_turn_look_from_bush(gi, m, best);
	const vec2 uw_at = W.me.pos;
	if (best.x >= 0 && mv::step_to(best, 1, 40, gi))
	{
		uw_gi = gi;
		uw_tile = best;
		uw_round = now();
		uw_from = uw_at;
		return true;
	}
	approach_group(gi);
	return true;
}
// a short task that finishes, with the walk back, before the respawn. True when one was taken.
__attribute__((always_inline)) inline bool target_turn_take_filler_task(int gi, int left)
{
	T.filler_check = now();
	float fr = 0;
	const int f = filler_target(gi, left, &fr);
	if (f >= 0)
	{
		ENG_CNT(14);
		NLOG("r%d slot %d filler %d while %d respawns in %d\n", now(), P.my_slot, f, gi, left);
		set_target(f, fr, 1);
		T.filler_until = now() + left + 6;
		return true;
	}
	const int wc = wait_chip_target(gi, left, &fr);
	if (wc >= 0)
	{
		set_target(wc, fr, 1);
		T.filler_until = now() + left + 6;
		frl_chip_gi = wc;
		frl_chip_until = now() + left + 6;
		return true;
	}
	return false;
}
// target_turn: someone captured it: wait nearby if it is due soon, else move on (and leave it until it is due).
__attribute__((always_inline)) inline bool target_turn_wait_for_respawn(int gi, const GroupI& g, GroupMem& m)
{
	// Someone captured it: wait nearby if it is due soon, else move on (and leave it until it is due).
	const int left = m.respawn_at - now();
	if (left - (path_dist(gi)) > crew_wait_limit(g) && !respawn_wait_lifted(gi, my_slot(), static_cast<float>(std::max(0, left - (path_dist(gi)))))) // D stays my target while it respawns
	{
		planner::stat_wasted_trip(gi, now() - T.chosen);
		const int back = m.respawn_at - 20;
		drop_target(0);
		m.fail_until = std::max(m.fail_until, back);
		return false;
	}
	// Waiting is wasted time: tribute the bag if the altar trip fits, or do a short task that finishes (with
	// the walk back) before the respawn.
	if (left >= 6 && W.me.gems >= (LTB_LIGHT(1) ? static_cast<unsigned>(LTB_TAB[2]) : (10u)) && !pc_keeps_bag(PC_WAIT_BANK) && bankable()) // no altar trip for a 5-gem bag
	{
		const std::uint16_t ad = bank_dist_here();
		if (ad != UNREACH && 2 * static_cast<int>(ad) + rs::tribute_rounds(static_cast<int>(W.me.gems), static_cast<bool>(prism::has_family(rs::F_TRIBUTE))) + 2 <= left + 4)
		{
			T.bank_until = now() + left;
			NLOG("r%d slot %d bank while %d respawns in %d\n", now(), P.my_slot, gi, left);
			return bank();
		}
	}
	if (left >= (FRL_TAB[2]) && now() - T.filler_check >= 4 && fuel() > 60000)
	{
		if (target_turn_take_filler_task(gi, left))
			return false;
	}
	dbg_path = 40;
	planner::stat_wait(0);
	respawn_stage(gi);
	return true;
}
// target_turn: every member is dead and it is not respawning: capture it, wait for the carrier, or leave it to a crew mate.
__attribute__((always_inline)) inline bool target_turn_at_dead_group(int gi, const GroupI& g, GroupMem& m)
{
	if (ring_gate_keep(gi))
	{
		drop_target(0); // opened (redirect_to_gate can still send a crew), never captured or marked taken
		m.fail_until = std::max(m.fail_until, now() + 200);
		return false;
	}
	if (mate_waits_for_prism_capture(gi))
		return !(!W.moved && T.target < 0); // the carrier comes for this plan group; a drop with no step re-runs target choice
	if (should_capture(gi))
		return capture(gi);
	// A crew mate captures; move on.
	mark_mate_capture(m, g);
	drop_target(0);
	return false;
}
__attribute__((always_inline)) inline int target_turn_read_hidden_state(int gi, const GroupI& g, GroupMem& m)
{
	// The visible members are dead and the rest is out of sight: the group state (readable while any member tile
	// is visible) tells whether a hidden member still lives. Walk until we see it, or capture.
	const int st = group_state_now(gi);
	if (st == 2)
	{
		CXL_NOTE(m);
		m.status = GS_CLEARED;
	}
	else if (st == 3 && m.status != GS_RESPAWN)
	{
		mark_respawn_timer(m, g);
	}
	return st;
}
// target_turn: the recall plus the walk from spawn beats this walk: take it. True when the recall started.
__attribute__((always_inline)) inline bool target_turn_recall_to_travel(int gi, const GroupI& g, int d)
{
	int home_walk = g.d_home;
	if (ht_state == 1)
		home_walk = std::min(home_walk, spawn_crossing_walk(gi)); // the recall + the hole dash out of the spawn
	const bool fhb_keep = finish_bank_bag();
	if (!fhb_keep && rh_any && T.crew <= 1 && static_cast<std::size_t>(gi) < sc_grp.size() && g.access == ACC_WALK && (now() - S.recall_round >= RT_GAP) && !(recall_hop_blocked()))
	{
		const int rc = recall_hop_cost(sc_grp[static_cast<std::size_t>(gi)], 1); // home, then the hop out
		if (rc != UNREACH && d >= rc + RWK_TAB[2] && recall_safe() && start_recall())
		{
			rhl_rec = now();
			return true;
		}
	}
	if (!fhb_keep && home_walk != UNREACH && d >= CSX_RCT() + home_walk + RECALL_TRAVEL && (now() - S.recall_round >= RT_GAP) && travel_recall_same_field(gi, d, RECALL_TRAVEL) && recall_safe() && start_recall())
		return true;
	// the recall shops or heals too, so it only has to be no slower than the walk.
	if (!fhb_keep && home_walk != UNREACH && d >= CSX_RCT() + home_walk + RTS_MARGIN && d < CSX_RCT() + home_walk + RECALL_TRAVEL && (now() - S.recall_round >= RT_GAP) && travel_recall_shop_due() && travel_recall_same_field(gi, d, RTS_MARGIN) && recall_safe() && start_recall())
		return true;
	return false;
}
// Right after a walk to an out-of-sight member, walk to the nearest living member in sight, else on to that member while it is
// unseen, instead of the group field (its nearest goal can be a dead member behind me).
__attribute__((always_inline)) inline bool target_turn_walk_to_unseen_member(int gi, const GroupI& g)
{
	vec2 uw_goal{ -1, -1 };
	int uw_d = BIG;
	for (int ci : g.members)
	{
		const vec2 p = M.camps[static_cast<std::size_t>(ci)].pos;
		if (inb(p) && bbget(W.vis, p) && bbget(W.occ_camps, p) && cheb(p, W.me.pos) < uw_d)
		{
			uw_d = cheb(p, W.me.pos);
			uw_goal = p;
		}
	}
	if (uw_goal.x < 0 && inb(uw_tile) && !bbget(W.vis, uw_tile))
		uw_goal = uw_tile;
	const vec2 uw_at = W.me.pos;
	if (uw_goal.x >= 0 && inb(uw_from) && cheb(uw_from, uw_at) == 1)
		mv::avoid_tile(uw_from); // no step back: step_to's walls follow my sight, so two tiles' routes can point at each other
	if (uw_goal.x >= 0 && mv::step_to(uw_goal, 1, 40, gi))
	{
		uw_from = uw_at;
		uw_round = now();
		dbg_path = 30;
		last_act = ACT_WALK;
		return true;
	}
	return false;
}
// target_turn: awake attackers next to one of us: we are in this fight (a crew mate or an enemy woke it).
__attribute__((always_inline)) inline void target_turn_join_awake_fight(int gi)
{
	if (!T.engaged && group_awake(gi))
	{
		// Awake attackers next to one of us: we are in this fight (a crew mate or an enemy woke it).
		std::vector<Attacker> la_tmp;
		for (const auto& a : living_attackers_cached(gi, false, la_tmp))
		{
			if (cheb(a.pos, W.me.pos) <= 1)
				T.engaged = true;
			for (const auto& al : W.allies)
				if (cheb(a.pos, al.pos) <= 1 && claims(al.slot, gi))
					T.engaged = true;
		}
	}
}
// read the gathering crew. True while it still waits; sets T.engaged when the crew starts.
__attribute__((always_inline)) inline bool target_turn_read_gathering_crew(int gi, const GroupI& g, const GroupMem& m, int waited)
{
	Crew rc;
	int away = 0;
	rally_present_count(gi, rc, &away);
	const bool started = siege_clear_started(gi); // a claimant already went in (its claim's engaged bit): join it
	bool cfr_wait = !started && away > 0 && waited < CF_RALLY_WAIT;
	if (cfr_wait && no_mate_arrives_in_time(gi, CF_RALLY_WAIT - waited))
		cfr_wait = false; // nobody can come in time
	if (cfr_wait && end_rally_gather_now(gi, g, m, rc))
		cfr_wait = false;
	if (cfr_wait && gi == cw_sg_gi && now() - cw_sg_end <= 5 && now() - cw_sg_arrive >= CF_RALLY_WAIT)
		cfr_wait = false; // my gather here just ended after CF_RALLY_WAIT rounds or more: no second gather
	if (started || (!cfr_wait && (estimate_cx(4, g, m, rc).feasible || gt_go(gi, rc.n))))
	{
		T.engaged = true; // the whole gathered crew starts now; crew_here picks the tank once it is near
		TT_EV("cfrs", gi, rc.n, waited);
	}
	return cfr_wait;
}
// v662 IDL (b1776): the self-start delay and the ok-wait cap.
int idl_s0()
{
	return IDL_TAB[2];
}
int idl_okw()
{
	return IDL_TAB[3];
}
// target_turn: not started: gather, wait for the crew, or give the group up.
template <int DM>
__attribute__((always_inline)) inline bool target_turn_hold_for_crew(int gi, const GroupI& g, int waited, bool ok, bool sg, bool cfr_wait, const Here& here)
{
	if (cfr_wait)
	{
		// gathering: walk to the rally tile and wait on it (stage_near without one).
		dbg_path = 45;
		planner::stat_wait(1);
		if (!siege_at_rally(gi) && !siege_walk_to_rally(gi))
			stage_near(gi);
		else
			last_act = ACT_WAIT;
		return true;
	}
	if (sg)
	{
		dbg_path = 43;
		planner::stat_wait(1);
		if (!siege_at_rally(gi))
			stage_near(gi); // gather outside the camps' reach (on the rally tile when there is one) until the crew is complete
		else                // here or the deadline passes (siege_turn)
			last_act = ACT_WAIT;
		return true;
	}
	if (!ok)
	{
		// Crew incomplete: wait at the rendezvous for a few turns only (claimants on their way get a little
		// longer when one is in sight and close), then farm something else.
		bool coming = false;
		const bool oeg = opening_elk_group(gi); // an own-side elk crew gets longer to gather
		const int crad = oeg ? OE_WAIT : 12;
		for (const auto& a : W.allies)
			if (claims(a.slot, gi) && !a.channeling() && cheb(a.pos, g.anchor) <= crad)
				coming = true;
		const int limit = siege_group(g) ? (coming ? 20 : 10) : oeg ? (coming ? OE_WAIT : 10) : (coming ? 12 : 7); // v660 IDL bit 2
		const bool dcg = (DM & 1) && dc_is(gi); // wait while a committed mate can come
		if (waited >= limit && !(dcg && waited < DC_WAIT && dom_commit_mate_coming(gi, DC_WAIT - waited)) && !(gi == gt_v && waited < GT_WAIT))
		{
			drop_target(dcg ? DC_FAIL : 30);
			crew_wait_ban_mark(gi, dcg ? DC_FAIL : 30);
			return false;
		}
	}
	else if (waited >= (idl_okw())) // v660 IDL bit 1: the ok-wait cap
	{
		drop_target(20);
		return false;
	}
	if (!ok && here.claim_away > 0 && wait_at_rally_tile(gi))
		return true;
	dbg_path = ok ? 42 : 41;
	planner::stat_wait(1);
	PROF("pre_stage");
	stage_near(gi);
	PROF("stage");
	return true;
}
// target_turn: at the group, not engaged yet: decide who starts it, else hold.
template <int DM>
__attribute__((always_inline)) inline TurnStep target_turn_start_or_hold(int gi, const GroupI& g, const GroupMem& m, const Here& here)
{
	if (T.wait_since < 0)
		T.wait_since = now();
	const int waited = now() - T.wait_since;
	const bool sg = SGO.gi == gi; // the crew starts together (siege_crew_ready); the deadline and aborts live in siege_turn
	const bool ok = sg ? siege_crew_ready(gi) : (g.n_att == 0 || (estimate_cx(4, g, m, here.crew).feasible) || gt_go(gi, here.n) || chip_start_partial_clear(gi, here.crew) || (gi == frl_chip_gi && now() < frl_chip_until));
	// Two or more enemies known about an asleep group: they would catch us tanking. Pick something else. A crew on a pack gathers on
	// the group's rally tile (siege_rally_tile: outside every attacker's reach, on our side) and starts when every claimant is there (or after
	// CF_RALLY_WAIT rounds), all in the same round: bodies that walked in 2-9 rounds apart leave the first one to take every attacker's
	// hits.
	const bool cfr = !sg && g.n_att >= 2 &&
		(claimants(gi) >= 1 || (squad::outside(gi) && (squad::mates(my_slot()) & ~(TM.sup >= 0 ? (1u << TM.sup) : 0u)) != 0u)) &&
		!group_awake(gi); // a squad bound for an outside pack gathers too
	bool cfr_wait = false;
	if (cfr)
	{
		cfr_wait = target_turn_read_gathering_crew(gi, g, m, waited);
	}
	else
	if (ok && (here.tank_is_me || g.n_att == 0))
		T.engaged = true;
	else if (ok && W.me.frac() > 0.5f && group_awake(gi) && siege_clear_started(gi) && [&]
		{
			std::vector<Attacker> ow_tmp;
			return in_reach_of(living_attackers_cached(gi, false, ow_tmp), W.me.pos, 0);
		}())
		T.engaged = true; // the fight is on and I stand in its reach: join, don't walk out and back
	else if (ok && (waited >= (idl_s0()) || (((now() <= OEG_TAB[2])) && nontank_joins_elk_opening(gi, here))) && W.me.frac() > 0.5f) // v660 IDL bit 1
	{
		// The better tank here has not started (busy, or it judges otherwise): start it myself.
		T.engaged = true;
		T.self_tank = true;
	}
	if (!T.engaged)
		return target_turn_hold_for_crew<DM>(gi, g, waited, ok, sg, cfr_wait, here) ? TurnStep::Done : TurnStep::Again;
	return TurnStep::Next;
}
// target_turn: engaged: the tank's or a supporter's turn at the group.
__attribute__((always_inline)) inline bool target_turn_engaged_at_group(int gi, const GroupI& g, const Here& here)
{
	const ffg::Meter ffg_m(-1); // the camp turn's measured cost (off: no work)
	bool tank_holds = false;
	std::vector<Attacker> la_tmp2;
	if (here.tank)
		for (const auto& a : living_attackers_cached(gi, false, la_tmp2))
			tank_holds |= cheb(here.tank->pos, a.pos) <= 1;
	if (g.n_att == 0 || here.tank_is_me || (T.self_tank && !tank_holds && now() >= T.bench_until))
		return tank_turn(gi, here) || true;
	return support_turn(gi, here) || true;
}
// target_turn: team table, operations, target choice; ends the turn when the fuel left allows only a cheap step.
template <int DM>
__attribute__((always_inline)) inline TurnStep target_turn_choose_step()
{
	build_team(false);
	prism_route_to_plan_groups<DM>();
	PROF("team");
	// An operation holds my target (no re-evaluation), or I join or call one. On a short turn the operation's checks wait (the target
	// is kept), so they never push the clear or the walk after them over the turn's fuel.
	const bool sg_hold = fuel() > 50000 ? siege_turn<DM>() : siege_cheap_hold(); // V2m (review M2)
	if (!sg_hold)
		refresh_target<DM>();
	if (!sg_hold)
		siege_try_call<DM>(); // on a turn with fuel to spare, call an operation (it replaces the target just chosen)
	PROF("refresh");
	build_team(false);
	if (T.target < 0)
		return TurnStep::Again;
	if (SGO.gi >= 0 && SGO.since == now() && T.target == SGO.gi)
	{
		// the call or join turn ends with one cheap step: the fields the new target needs (group, home, rally) are built on the next
		// turns, with fresh fuel (building them on this turn would exhaust it).
		if (const distance_field* f = mv::group_field_ready(T.target))
		{
			if (dfget_me(*f) > 1)
				mv::step_field(*f, T.target);
		}
		else
			mv::step_greedy(M.groups[static_cast<std::size_t>(T.target)].anchor, T.target);
		return TurnStep::Done;
	}
	if (fuel() < 14000)
		return TurnStep::Done; // the opening simulation used this turn's fuel: move next turn rather than suspend
	if (fuel() < 28000 || (T.eval_round == now() && fuel() < (static_cast<long>(FGT_TAB[2])))) // a choice ran this turn; FGT bit 4
	{
		if (T.engaged && !T.capturing && cheap_camp_hit(T.target))
		{
			lfe_n = 0;
			return TurnStep::Done;
		}
		// Little fuel left this turn (a target choice ran): only a cheap step along the cached field. Not off the spawn (or off the way to
		// the launch) when the target's crystal trip may start or runs.
		if (const distance_field* f = mv::group_field_ready(T.target))
			if (!T.engaged && !T.capturing && dfget_me(*f) > 1 && !spawn_crystal_hold<DM>(T.target))
				mv::step_field(*f, T.target);
		if (!(!T.capturing && !W.moved && ++lfe_n >= LOW_FUEL_EXIT_TAB[2]))
			return TurnStep::Done;
	}
	lfe_n = 0;
	return TurnStep::Next;
}
template <int DM>
bool target_turn()
{
	if (const TurnStep s = target_turn_choose_step<DM>(); s != TurnStep::Next)
		return s == TurnStep::Done;
	const int gi = T.target;
	const auto& g = M.groups[static_cast<std::size_t>(gi)];
	auto& m = mem[static_cast<std::size_t>(gi)];
	track_progress<DM>(gi);
	PROF("track");
	if (T.target < 0)
		return false;
	if (gi == frl_chip_gi && now() >= frl_chip_until && !T.capturing) // the chip budget ended
	{
		frl_chip_gi = -1;
		drop_target(0);
		return false;
	}
	if (T.capturing)
	{
		if (capture(gi) || T.target >= 0)
			return true;
		return false; // the reward came: choose the next target this turn
	}
	if (redirect_to_gate<DM>(gi)) // a living gate between me and the target: clear it first, or leave
		return false;
	int invisible = 0;
	const int alive = living_members_visible(gi, &invisible);
	const bool seen = invisible < g.nm;
	if (seen && alive == 0 && invisible > 0)
	{
		const int st = target_turn_read_hidden_state(gi, g, m);
		if (st == 1 || st == 0)
			return target_turn_walk_to_hidden_member(gi, g, m);
	}
	if (seen && alive == 0 && (invisible == 0 || m.status == GS_CLEARED || m.status == GS_RESPAWN))
	{
		if (m.status == GS_RESPAWN)
			return target_turn_wait_for_respawn(gi, g, m);
		return target_turn_at_dead_group(gi, g, m);
	}
	if (SGO.gi == gi && !T.engaged && siege_walk_to_rally(gi))
		return true; // the crew gathers on the rally tile
	// Walking distance, not Chebyshev: a group behind a wall is far even when it looks close.
	const int d = path_dist(gi);
	const int ring = (g.reach_max > 0 ? g.reach_max : 1) + 2;
	// This gate reads the static group field (every other camp tile blocked), tank_turn steps by the live search (dead clusters
	// passable). At a gap in a cluster wall the two disagree by a tile: the gate would send the body out, tank_turn back in, forever at
	// full health. Once at the group, it stays at the group unless 2 tiles farther.
	const int slack = (at_gi == gi && at_round >= now() - 1) ? 2 : 0;
	const bool sgs_hold = !seen && SGO.gi == gi && !T.engaged && d <= ring + 2 + slack;
	if ((!seen && !sgs_hold) || d > ring + 2 + slack || dasher_walk_past_bar(gi, ring + 2 + slack) || ((starved_map_bits() & 4) != 0 && group_outside_walk(gi)))
	{
		// The recall + the walk from spawn beats this walk by RECALL_TRAVEL+ rounds: take it. d is read from the group field (other camps
		// blocked) and d_home from f_home (camps passable), so both routes come from the same field; otherwise a camp detour makes the
		// recall look shorter than it is and a body could recall, land on the spawn and recall again. No second travel recall within
		// RT_GAP rounds of the last recall.
		if (target_turn_recall_to_travel(gi, g, d))
			return true;
		if (uw_gi == gi && now() - uw_round <= 1)
		{
			if (target_turn_walk_to_unseen_member(gi, g))
				return true;
		}
		dbg_path = 31;
		approach_group(gi);
		return true;
	}
	at_gi = gi;
	at_round = now();
	PROF("pre_here");
	const Here here = crew_here(gi);
	PROF("here");
	target_turn_join_awake_fight(gi);
	if (!T.engaged)
		if (const TurnStep s = target_turn_start_or_hold<DM>(gi, g, m, here); s != TurnStep::Next)
			return s == TurnStep::Done;
	if (T.engaged)
	{
		const int cfc = camp_engaged_check(gi, here);
		if (cfc == 1)
			return true; // aborted and walked out of the reach
		if (cfc == 2)
			return false; // dropped: farm() chooses again this turn
	}
	return target_turn_engaged_at_group(gi, g, here);
}
} // namespace
} // namespace nova::econ
