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
// What each mate claims now (group + 1, 0 for none or myself).
static __attribute__((always_inline)) inline std::array<std::uint8_t, 8> mates_claims_now()
{
	std::array<std::uint8_t, 8> now_claims{};
	for (int s = 0; s < comms::CLAIM_SLOTS && s < 8; ++s)
		now_claims[static_cast<std::size_t>(s)] = s == my_slot() ? 0 : static_cast<std::uint8_t>(comms::cgroup(s) + 1);
	return now_claims;
}
// A claim change since the last evaluation that is worth a new one.
static __attribute__((always_inline)) inline bool claims_moved_since_eval(const std::array<std::uint8_t, 8>& now_claims)
{
	bool claims_moved = now_claims != eval_claims && now() - T.eval_round >= 3;
	if (!claims_moved && T.target >= 0 && now() - T.eval_round >= 1 && now_claims != eval_claims)
	{
		// a mate newly claims my target or leaves it: re-evaluate now
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
	opening = !opened && (W.on_spawn || op_prestepped) && now() < 30; // a prestepped body still finishes the simulation
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
// Applies the choice: keep, drop, follow a squad mate, or switch when the new rating beats the current by the margin.
// v712 JNS bit 1: a mate's claim on my target newer than my pick, or changed within JNS_ROUNDS.
static bool jns_mate_joined()
{
	if (T.target < 0 || T.engaged || T.capturing)
		return false;
	for (int s = 0; s < TM.n && s < 8; ++s)
		if (s != my_slot() && TM.claim[static_cast<std::size_t>(s)] == T.target &&
			(squad::claim_changed(s) > T.chosen || now() - squad::claim_changed(s) <= JNS_TAB[2]))
			return true;
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
				drop_target(0);
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
	if (JNS_ON(1) && sw == 1.0f && jns_mate_joined()) // v712 JNS bit 1: a mate just joined my target: the margin stands
		sw = nova::econ::linear_score::lsp_switch(best);
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
	if (cur <= 0 || (lsw < 0 ? r > cur * sw : lsw > 0))
		set_target(best, r, crew);
	else
	{
		T.eval_round = now();
		T.crew = cc;
		T.rate = cur;
	}
}
template <int DM>
void refresh_target()
{
	if (retarget_kept_by_commitment<DM>())
		return;
	const std::array<std::uint8_t, 8> now_claims = mates_claims_now();
	const bool claims_moved = claims_moved_since_eval(now_claims);
	if (cassi_follows_issac<DM>(now_claims))
		return;
	if (squad_partner_retarget<DM>(now_claims))
		return;
	if (retarget_not_due(claims_moved))
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
