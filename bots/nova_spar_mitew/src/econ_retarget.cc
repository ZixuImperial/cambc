// econ_retarget.cc: refresh_target: when a body changes its target.
#include "econ_internal.h"
namespace nova::econ {
namespace {
int sq_form_fail = -1000; // the last round my restricted (partner) choice found nothing: no retry for 10 rounds
fg::Cost fg_form; // cost bound of the squad-formation block in refresh_target (travel, best_within, a rating)
// The body is busy, on a filler task, or kept by a commitment (dominant group, opening, vesper, gate): no new choice this turn.
template <int DM>
static __attribute__((always_inline)) inline bool retarget_kept_by_commitment()
{
	if (T.engaged || T.capturing)
		return true;
	if (T.target >= 0 && T.filler_until > now())
		return true; // a filler task between respawns: finish it
	crew_wait_ban_pass();
	bail_ban_lift_lapsed();
	if ((DM & 1) && dom_commit_turn())
		return true; // the dominant-group commitment kept or committed to
	if ((opened ? dc_state == 0 && dc_v >= 0 && ((T.target == dc_v) || (T.target < 0 && dom_commit_turn())) : commit_to_dom_opening())) // D kept until the free slot decides
		return true;
	if (opened && vesper_open::keep())
		return true;
	if (gate_target_turn())
		return true; // the gate kept or committed to
	return false;
}
// b1968 GBF bit 64 RTX1: mates_claims_now with comms::cgroup's state read once (the loop writes only the local array)
static __attribute__((always_inline)) inline std::array<std::uint8_t, 8> gbf_claims_now()
{
	std::array<std::uint8_t, 8> now_claims{};
	const int me = my_slot();
	const bool big = comms::bcl_big, on = comms::bcl_on;
	for (int s = 0; s < comms::CLAIM_SLOTS && s < 8; ++s)
	{
		const int r = comms::V.cg[static_cast<std::size_t>(s)];
		const int g = big ? ((on && r >= 0 && r < 126) ? comms::bcl_list[static_cast<std::size_t>(r)] : -1) : r;
		now_claims[static_cast<std::size_t>(s)] = s == me ? 0 : static_cast<std::uint8_t>(g + 1);
	}
	return now_claims;
}
// RTX1: claims_moved_since_eval with the 8 claim bytes compared as one word
static __attribute__((always_inline)) inline bool gbf_claims_moved(const std::array<std::uint8_t, 8>& now_claims)
{
	std::uint64_t a, e;
	__builtin_memcpy(&a, now_claims.data(), 8);
	__builtin_memcpy(&e, eval_claims.data(), 8);
	const bool ne = a != e;
	bool claims_moved = ne && now() - T.eval_round >= 3;
	if (!claims_moved && T.target >= 0 && now() - T.eval_round >= 1 && ne)
	{
		const std::uint8_t tc = static_cast<std::uint8_t>(T.target + 1);
		for (std::size_t s = 0; s < 8; ++s)
			if (now_claims[s] != eval_claims[s] && (now_claims[s] == tc || eval_claims[s] == tc))
				claims_moved = true;
	}
	return claims_moved;
}
// While linked, Cassi works Issac's claim group; true when this turn is spent on it.
template <int DM>
static __attribute__((always_inline)) inline bool cassi_follows_issac(const std::array<std::uint8_t, 8>& now_claims)
{
	// while linked, Cassi works Issac's claim group (he leads, she follows on the same group).
	const int ag = combat::cassi_adopt_issac_group();
	if (ag >= 0 && ag == T.target)
		return true;
	static int ci_fail = -100;
	if (ag >= 0 && fuel() > PLAN_EVAL_FUEL && now() - ci_fail >= 5)
	{
		ci_fail = now();
		build_team(false);
		if (travel_round != now() || travel_from != W.me.pos)
			compute_travel();
		if (travel[static_cast<std::size_t>(ag)] != UNREACH && reachable_target(ag))
		{
			int cc = 1;
			const Claims cl = claims_for_me();
			ci_adopt_g = ag;
			const float rr = rate_for<DM>(ag, my_slot(), travel[static_cast<std::size_t>(ag)], cl, free_near(), &cc);
			ci_adopt_g = -1;
			if (rr > 0)
			{
				ci_fail = -100;
				eval_claims = now_claims;
				set_target(ag, rr, cc);
				return true;
			}
		}
	}
	return false;
}
// A seed's partner with a target outside its leash takes its best group within the leash; true when it did.
template <int DM>
static __attribute__((always_inline)) inline bool squad_partner_retarget(const std::array<std::uint8_t, 8>& now_claims)
{
	if (FB6_ON(32) && now() - sq_form_fail < 10)
		return false; // FB6 RO6: the cooldown before the squad reads
	const int sd = squad::squad_seed_of_slot(my_slot());
	const int sg = sd >= 0 ? comms::cgroup(sd) : -1;
	if (!(sg >= 0 && sg < M.ng && now() - sq_form_fail >= 10 &&
		(T.target < 0 || cheb(M.groups[static_cast<std::size_t>(T.target)].anchor, M.groups[static_cast<std::size_t>(sg)].anchor) > SQ_FORM_LEASH)))
	{
		return false; // FB1 bit 4 FL3: the trigger first; the fuel reads only for a turn that runs the check
	}
	bool fg_form_ok = true;
	// the partner check waits for a turn that can pay it and the turn's rest (retried next turn).
	if (fg_form.hi > 0 && fuel() < fg_form.hi + FG_TAIL)
	{
		fg_form.hi -= fg_form.hi >> 5;
		fg_form_ok = false;
	}
	const long ffo = fuel();
	const int rfo = fg::rnd();
#define FG_FORM_OK fg_form_ok &&
	if (FG_FORM_OK sg >= 0 && sg < M.ng && now() - sq_form_fail >= 10 &&
		(T.target < 0 || cheb(M.groups[static_cast<std::size_t>(T.target)].anchor, M.groups[static_cast<std::size_t>(sg)].anchor) > SQ_FORM_LEASH))
	{
		build_team(false);
		if (travel_round != now() || travel_from != W.me.pos)
			compute_travel();
		float fr = 0;
		int fc = 1;
		const Claims fcl = claims_for_me();
		int b = best_within<DM>(M.groups[static_cast<std::size_t>(sg)].anchor, SQ_FORM_LEASH, fcl, &fr, &fc); // BB8_ON(4)
		if (b >= 0 && T.target >= 0)
		{
			// partner only when my share there is worth at least SQ_KEEP of my current target
			int cc2 = 1;
			const float cur = rate_for<DM>(T.target, my_slot(), travel[static_cast<std::size_t>(T.target)], fcl, free_near(), &cc2);
			const float sqk = nova::econ::linear_score::lsp_keep(b); // v642 LSP: map-aware keep
			if (cur > 0 && (opened ? (nova::econ::linear_score::rate_cur(3), !nova::econ::linear_score::keep_ok(4, 3, sqk)) : fr < sqk * cur))
				b = -1;
		}
		fg::note(fg_form, fg::fuel_used_since(ffo, rfo));
		if (b >= 0)
		{
			eval_claims = now_claims;
			set_target(b, fr, fc);
			return true;
		}
		sq_form_fail = now();
	}
	return false;
}
// v707 RC5 RTC1: this turn's crew_left event, and the pull-back that keeps it due when the turn makes no choice.
static bool rc5_cl = false;
static void rc5_keep_due()
{
	if (rc5_cl)
		T.eval_round = std::min(T.eval_round, now() - PLAN_EVAL_EVERY);
	rc5_cl = false;
}
// True when no choice is due now, or the body waits at its target for the crew.
static __attribute__((always_inline)) inline bool retarget_not_due(bool claims_moved)
{
	const bool lnr_cl = opened && nova::econ::linear_score::crew_left();
	const bool due = T.target < 0 || (now() - T.eval_round >= PLAN_EVAL_EVERY) || lnr_cl || claims_moved || camp_news_due_take() || (pec_st && pec_stage_ready()); // PEC bit 1: a resumed list is due
	rc5_cl = lnr_cl;
	if (!due)
		return true;
	if (T.target >= 0 && T.wait_since >= 0 && near_target(T.target) &&
		(!claims_moved || siege_group(M.groups[static_cast<std::size_t>(T.target)])))
	{
		rc5_keep_due();
		return true; // waiting at the target for the crew (a siege crew gathers over many rounds)
	}
	return false;
}
// True when this turn has too little fuel for a choice (a bounded choice may run for a target-less body); sets whether this is the opening.
template <int DM>
static __attribute__((always_inline)) inline bool retarget_fuel_short(const std::array<std::uint8_t, 8>& now_claims, bool& opening)
{
	opening = !opened && (W.on_spawn || op_prestepped) && (now() < 30); // b1939 RGF bit 1: round term dropped; // a prestepped body still finishes the simulation
	if (opening && OP.started && drop_pending_opening_sim())
		opening = false;
	if (fuel() < (opening ? OPENING_RESERVE + 6000 : PLAN_EVAL_FUEL)) // fuel for decisions outside the opening
	{
		if (!opening && T.target < 0)
			choose_target_when_starved<DM>(now_claims); // a bounded choice for a body the gate keeps target-less
		return true;
	}
	// a body with a target keeps it without a choice when the choice's work before its rating loop (measured on this body) would leave
	// the turn under FG_TAIL: such a choice rates nothing (the loop stops at the floor), keeps the target and suspends the turn.
	// Retried on the next turn (no eval_round update).
	if (!opening && T.target >= 0 && fg_pre.hi > 0 && fuel() < fg_pre.hi + FG_TAIL && !(pec_st && pec_stage_ready())) // PEC bit 1: a resumed list has no pre-loop work
	{
		fg_pre.hi -= fg_pre.hi >> 5; // the estimate fades while skipped, so a cheaper choice is tried again
		return true;
	}
	return false;
}
// Chooses the new target (opening pick or normal choice); true when the turn ends without applying one.
template <int DM>
static __attribute__((always_inline)) inline bool pick_retarget_choice(const std::array<std::uint8_t, 8>& now_claims, bool opening, float& r, int& crew, int& best)
{
	PROF("pre_choose");
	std::array<std::uint8_t, 8> tds_ec{};
	eval_claims = now_claims;
	if (opening)
	{
		// a simulation pending from an earlier turn: step first, while the turn's fuel is fresh (after the simulation's -2 the step ate
		// the reserve the turn keeps for the rest of its work).
		best = (DM & 2) ? opening_pick<true, ((DM & 2) ? DM : 2)>(&r, &crew) : opening_pick<false>(&r, &crew); // hoard-crew mode 2; DM for BB8_ON(8)
		if (best == -2)
		{
			if (fuel() > OBK_F0 + OBK_FG * static_cast<long>(static_cast<std::size_t>(M.ng)))
				opening_prestep();
			return true; // the opening simulation continues next turn
		}
	}
	else
	{
		gbr_defer = false;
		best = choose_target<DM>(&r, &crew);
		if (gbr_defer && best < 0)
		{
			gbr_defer = false;
			opened = true;
			return true; // the choice resumes next turn (no eval_round update, the target kept)
		}
		gbr_defer = false;
	}
	return false;
}
template <int DM>
static __attribute__((always_inline)) inline void apply_retarget_choice(int best, float r, int crew)
{
	const bool stick = sq_stick_pick; // this choice follows a squad mate out
	sq_stick_pick = false;
	opened = true;
	if (best < 0)
	{
		if (T.target >= 0)
		{
			int cc = 1;
			const Claims cl = claims_for_me();
			float tcs_r = 0;
			if (((tcs_r = rate_for<DM>(T.target, my_slot(), travel[static_cast<std::size_t>(T.target)], cl, free_near(), &cc))) <= 0) // v693 TCS bit 1 keeps the rate
			{
				drop_target(0);
			}
			else
			{
				T.eval_round = now();
				T.crew = cc;
				T.rate = tcs_r;
			}
		}
		return;
	}
	if (best == T.target)
	{
		T.rate = r;
		T.crew = crew;
		T.eval_round = now();
		return;
	}
	if (T.target < 0)
	{
		set_target(best, r, crew);
		return;
	}
	int cc = 1;
	const Claims cl = claims_for_me();
	if (stick)
	{
		set_target(best, r, crew); // follow the squad mate out
		return;
	}
	const float cur = rate_for<DM>(T.target, my_slot(), travel[static_cast<std::size_t>(T.target)], cl, free_near(), &cc);
	float sw = nova::econ::linear_score::lsp_switch(best); // v642 LSP: map-aware switch factor
	if (now() - T.chosen <= MFB_TAB[3] && !T.engaged && !T.capturing && static_cast<int>(travel[static_cast<std::size_t>(best)]) + MFB_TAB[4] <= static_cast<int>(travel[static_cast<std::size_t>(T.target)]))
		sw = 1.0f;
	if (pec_res_r == now() && cur > 0 && !(r * 100.0f > cur * static_cast<float>(PEC_TAB[2])))
	{
		PEC_CNT(3, true); // PEC bit 1: a resumed pick under the margin keeps the target
		T.eval_round = now();
		T.crew = cc;
		T.rate = cur;
		return;
	}
	PEC_CNT(2, pec_res_r == now());
	int lsw = -1;
	if (cur > 0) // switch only when the new score beats the current by the margin
		lsw = nova::econ::linear_score::switch_test(best, sw);
	if (cur <= 0 || (lsw < 0 ? r > cur * sw : lsw > 0)) // v724 DFG bit 4: no switch off the record's group
		set_target(best, r, crew);
	else
	{
		T.eval_round = now();
		T.crew = cc;
		T.rate = cur;
	}
}
// v7xx LAH (b1994): the next target chosen during the capture stand on many-group maps (MCL3 bit 128), taken on the payout turn
// after a re-rate. The stand turns run best_group's work for my own choice (bounds, rating loop, linear pick) in slices: the bounds
// pause through GBR (same tile, next turn), the rating loop keeps its place in lah_ci; no PLAN_EVAL_FLOOR, the turn keeps LAH_FLOOR.
__attribute__((noinline)) bool lah_class() { return (map_class3() & 128) != 0; } // MANYGRP, from the draft's class byte
struct LahCand
{
	int gi, crew;
	float r, a0, b, lm;
};
int lah_phase = 0;                            // 0 start a choice, 1 bounds paused (GBR resumes them), 2 rating
int lah_src = -1, lah_last = -1000;           // the group I capture; the last stand round worked
vec2 lah_at{ -1, -1 };                        // the stand tile
std::vector<std::pair<float, int>> lah_cand;  // this choice's bound list, best first
std::size_t lah_ci = 0;                       // the next candidate to rate
float lah_br = 0;                             // this choice's best ratio so far
int lah_bg = -1, lah_bc = 1;                  // its group and crew
bool lah_hoard = false;                       // the bound list still needs hoard_crew_bounds (DM & 2)
LahCand lah_ev[128];                          // rated candidates for the linear pick (M.ng <= 126)
int lah_nev = 0;
int lah_g = -1, lah_crew = 1, lah_src_done = -1; // the stored pick, its crew, the group whose stand made it
float lah_r = 0;                              // its ratio
vec2 lah_pos_done{ -1, -1 };                  // the tile it was rated from
int lah_paid = -1000;                         // the round the capture of lah_src_done paid
// best_group's linear pick (linear_score::pick) over this choice's rated list; returns the picked index or -1.
__attribute__((noinline)) int lah_linear_pick()
{
	int k0 = -1;
	float s0 = 0;
	for (int k = 0; k < lah_nev; ++k)
	{
		const float sk = lah_ev[k].a0 - lah_ev[k].lm * lah_br * lah_ev[k].b;
		if (k0 < 0 || sk > s0)
		{
			k0 = k;
			s0 = sk;
		}
	}
	return k0;
}
template <int DM>
__attribute__((noinline)) void lah_stand(int gi)
{
	if (lah_last == now())
		return;
	if (lah_src != gi || lah_at != W.me.pos || now() - lah_last > 2)
	{
		lah_src = gi; // a new stand, or the body moved: start over with no stored pick
		lah_at = W.me.pos;
		lah_phase = 0;
		lah_g = -1;
	}
	lah_last = now();
	if (lah_phase < 2)
	{
		if (fuel() < static_cast<long>(LAH_TAB[3]) + 8000) // RC C417: a bounds slice (GBR pauses it at TCF_TAB[2]) starts above the floor
			return;
		if (lah_phase == 0 || !bounds_resume_ready())
			if (travel_from != W.me.pos || now() - travel_round > 2) // the same tile's travel serves the stand (as a staged list)
			{
				compute_travel();
				if (fuel() < static_cast<long>(TCF_TAB[2]) + 5000)
				{
					lah_phase = 0; // RC C417: the bounds wait for the next stand turn
					return;
				}
			}
		tcf_lazy = false;
		gbr_want = true;
		gbr_stop = false;
		group_bounds(my_slot(), travel.data(), false, lah_cand);
		gbr_want = false;
		if (gbr_stop) // the pass goes on next turn from the same tile
		{
			gbr_stop = false;
			lah_phase = 1;
			return;
		}
		if (tcf_lazy)
			bounds_heap_drain(lah_cand);
		lah_hoard = (DM & 2) != 0;
		lah_ci = 0;
		lah_br = 0;
		lah_bg = -1;
		lah_bc = 1;
		lah_nev = 0;
		lah_phase = 2;
	}
	if (fuel() < static_cast<long>(LAH_TAB[3]))
		return; // RC C417: the rating starts on the next stand turn
	if (lah_hoard)
	{
		lah_hoard = false;
		hoard_crew_bounds(lah_cand);
		if (fuel() < static_cast<long>(LAH_TAB[3]))
			return;
	}
	const Claims cl = claims_for_me();
	const int fx = free_near();
	const bool lnr = opened;
	const float pull = (RCB_ON(32) && W.me.kit && willow_layer::me()) ? (1.0f + WL2_PULL_X100 / 100.0f) * (1.0f + WHV_PULL_X100 / 100.0f) : 1.0f;
	while (lah_ci < lah_cand.size())
	{
		const float ub = lah_cand[lah_ci].first;
		const int g2 = lah_cand[lah_ci].second;
		if ((RCB_ON(32) ? ub * pull <= lah_br : ub <= lah_br) || ub <= 0.0f)
			break;
		if (fuel() < static_cast<long>(LAH_TAB[3]))
			return; // the rating goes on next stand turn
		++lah_ci;
		if (g2 == gi)
			continue; // my own group respawns after the payout
		int crew = 1;
		const float r = rate_for<DM>(g2, my_slot(), travel[static_cast<std::size_t>(g2)], cl, fx, &crew);
		float a0 = 0, b = 1, lm = 0;
		if (lnr && r > 0 && lah_nev < 128 && linear_score::parts(g2, &a0, &b, &lm))
			lah_ev[lah_nev++] = { g2, crew, r, a0, b, lm };
		if (r > lah_br)
		{
			lah_br = r;
			lah_bg = g2;
			lah_bc = crew;
		}
	}
	int pg = lah_bg, pc = lah_bc;
	float pr = lah_br;
	if (lnr)
		if (const int k = lah_linear_pick(); k >= 0)
		{
			pg = lah_ev[k].gi;
			pc = lah_ev[k].crew;
			pr = lah_ev[k].r;
		}
	lah_g = pg; // the stored pick (-1: none)
	lah_crew = pc;
	lah_r = pr;
	lah_src_done = gi;
	lah_pos_done = W.me.pos;
	lah_phase = 0; // the next stand turn starts a fresher choice
}
// The payout turn: the stored pick, re-rated from the same tile, is taken when it keeps LAH_KEEP % of its rate.
template <int DM>
__attribute__((noinline)) bool lah_take(const std::array<std::uint8_t, 8>& now_claims)
{
	const int g = lah_g;
	lah_g = -1; // used once
	lah_paid = -1000;
	if (g < 0 || g >= M.ng || lah_pos_done != W.me.pos || travel_from != W.me.pos || mem[static_cast<std::size_t>(g)].fail_until > now() ||
		!reachable_target(g)) // RC C417
		return false;
	int cc = 1;
	const Claims cl = claims_for_me();
	const float r = rate_for<DM>(g, my_slot(), travel[static_cast<std::size_t>(g)], cl, free_near(), &cc);
	if (!(r > 0.0f) || r * 100.0f < lah_r * static_cast<float>(LAH_TAB[4]))
		return false;
	eval_claims = now_claims;
	opened = true;
	set_target(g, r, cc);
	return true;
}
template <int DM>
void refresh_target()
{
	if (retarget_kept_by_commitment<DM>())
		return;
	const std::array<std::uint8_t, 8> now_claims = gbf_claims_now(); // b1968 GBF bit 64 RTX1
	const bool claims_moved = gbf_claims_moved(now_claims);
	if (cassi_follows_issac<DM>(now_claims))
		return;
	if (squad_partner_retarget<DM>(now_claims))
		return;
	if (retarget_not_due(claims_moved))
		return;
	if (lah_paid == now() && lah_take<DM>(now_claims)) // v7xx LAH: the stand's pick, re-rated
		return;
	bool opening;
	if (retarget_fuel_short<DM>(now_claims, opening))
	{
		rc5_keep_due();
		return;
	}
	float r = 0;
	int crew = 1;
	int best = -1;
	if (pick_retarget_choice<DM>(now_claims, opening, r, crew, best))
	{
		if (best < 0) // v707 RC5 RTC1: a deferred choice
			rc5_keep_due();
		return;
	}
	apply_retarget_choice<DM>(best, r, crew);
}
} // namespace
} // namespace nova::econ
