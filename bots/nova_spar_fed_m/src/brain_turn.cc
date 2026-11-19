// brain_turn.cc: The turn: one function per stage; a stage that returns true used the turn.
#include "brain_internal.h"
namespace nova {
namespace {
// A turn that ends here: publish my task's claim, or no claim.
NOVA_INLINE bool end_task()
{
	publish_task();
	return true;
}
NOVA_INLINE bool end_free()
{
	publish(-1, false);
	return true;
}
// Nothing done yet this turn (no move, attack, cast or channel).
NOVA_INLINE bool no_action_yet() { return !W.moved && !W.attacked && !W.cast && !W.me.channeling(); }
// Free for a calm walk of my own.
NOVA_INLINE bool calm_walk_ok(const combat::Assessment& a)
{
	return W.alive && W.can_move() && !W.me.channeling() && a.stance == combat::CALM && !econ::busy_capturing() && fuel() > brain_tune::WALK_FUEL;
}
template <int DM> NOVA_INLINE void threat_note(std::vector<vec2>& from)
{
	if (DM & 1)
		econ::threat_seen_dom(from);
	else
		econ::threat_seen(from);
}

// Everything every body reads first, dead or alive.
NOVA_INLINE void turn_senses()
{
	perceive();
	PROF("perceive");
	comms::read();
	comms::note_seen(W.round); // First-seen round of the event slot's bytes.
	econ::camp_news_read(); // Mates' CAMP entries.
	comms::note_seen(W.round); // Events arrive through the channel's decode.
	squad::begin_turn(); // Objectives from the claims just read.
	prism::track(); // The enemy's tributed history (race deadline).
	intel::begin_turn(); // Team event slot and own sightings (a dead champion sees through its ward).
	try
	{
		zc::begin_turn(); // Type-7 events, the phase, counts and yields (also while dead).
	}
	catch (...)
	{
		FXR_PASS();
	}
	PROF("intel_in");
	mv::begin_turn();
	combat::observe();
	econ::team_quiet_track();
}

NOVA_INLINE void dead_turn()
{
	td_n = 0; // A respawned body starts a fresh history.
	econ::death_reset(); // Forget the engagement; re-rate on the first live turn.
	econ::recall_hop_prebuy();
	econ::shop();
	econ::spawn_crystal_prebuy(); // The dead shop, too, buys the crystal from what the shop left.
	combat::buy_altar_lock();
	// A dead body's stale escape priority would hold the first slot ahead of a walk-then-cast.
	if (P.my_slot >= 0 && cur_prio != P.prio[static_cast<std::size_t>(P.my_slot)])
		adopt_prio(P.prio[static_cast<std::size_t>(P.my_slot)]);
	publish(-1, false);
}

template <int DM> NOVA_INLINE void note_tribute_end()
{
	static int tl_trib_dm = -1000; // My last own turn that started inside a tribute channel.
	int& tl_trib = tl_trib_dm;
	if (W.me.state & ST_TRIBUTE)
		tl_trib = W.round;
	else if (tl_trib == W.round - 1 && W.me.gems > 0)
	{
		td_lost_round = W.round; // The channel ended and the bag is still here: it was cancelled.
	}
	// A channel I held or started last turn is gone, the bag is here, and I did not cancel it: the enemy did.
	if (!(W.me.state & ST_TRIBUTE) && W.me.gems > 0 && (tl_trib == W.round - 1 || b781_trib_start == W.round - 1) && td_cancel_round != W.round - 1 && b781_own_cancel != W.round - 1)
	{
		b781_ec_round = W.round;
		b781_ec_pos = W.me.pos;
		note_channel_ender_foes();
	}
}

NOVA_INLINE void early_ring_escape()
{
	// I lost HP since my last own turn, which neither attacked nor cast (it stood or stepped deeper) or lost so much that RE_DOOM_R
	// more such rounds kill me, and >= RE_MIN_CAMPS awake camps (not my target's) reach me: walk out of their reach first, before the
	// turn's heavy work. Inside an altar's awake camp ring, perception and the assessment can leave 9-25k, so camp_out's escape would
	// take its no-fuel branch or the early action step would bail while a dead-camp gap led out. Off on a capture that pays first. Only
	// on altar-ring maps (M.ring: the altars enclosed by camps); no work unless the HP test passes.
	const float lost = re_hp - W.me.hp;
	const bool hit = re_round == W.round - 1 && lost > 0.0f && (!re_acted || lost * static_cast<float>(RE_DOOM_R) >= W.me.hp);
	re_round = W.round;
	re_hp = W.me.hp;
	re_acted = false;
	if (hit && M.ring && W.can_move() && !W.me.channeling() && fuel() > RE_FUEL_EARLY)
	{
		float rs = 0;
		const int rin = mv::ring_in(econ::claim_target(), rs); // not my target's camps: its walk in and clear are target_turn's
		const int pay = rin >= RE_MIN_CAMPS ? econ::capture_pay_in() : -1;
		if (rin >= RE_MIN_CAMPS && !(pay >= 0 && rs * static_cast<float>(econ::camp_hits_before_capture_pay(pay)) < W.me.hp - 0.15f * W.me.maxhp))
		{
			econ::abort_ring_bank_walk();
			mv::ring_escape();
		}
	}
}

NOVA_INLINE void arm_act_first()
{
	// Armed once per turn, after the perception, on a heavy turn with an enemy within AF_R.
	af_turn_round = W.round;
	if (!W.me.channeling())
	{
		int af_n = 0;
		for (const auto& e : W.enemies)
			af_n += cheb(e.pos, W.me.pos) <= AF_R ? 1 : 0;
		if (af_n > 0)
		{
			bool heavy = W.round - af_heavy_round <= AF_HEAVY_KEEP || fuel() < (AF_ARM_FUEL);
			if (!heavy && af_n >= AF_ARM_FOES)
			{
				int aw = 0;
				for (const auto& vc : W.camps)
					if (vc.awake && ++aw >= AF_ARM_CAMPS)
						break;
				heavy = aw >= AF_ARM_CAMPS;
			}
			if (heavy)
			{
				af_armed = true;
				af_floor = AF_FLOOR;
			}
		}
	}
}

// The channel state changed under me: re-read myself; true if the turn may go on (I am no longer channelling).
NOVA_INLINE bool resumed()
{
	refresh_self();
	return !W.me.channeling();
}
// My kept recall's ticks left, then econ's test (a winning bag nearer the altar than home + walk).
static int wbr2_round = -1000;
static int wbr2_free_sum = 1 << 30; // gems + tributed_us on my last free (not channelling) turn: the recall started from there
static __attribute__((noinline)) bool winning_bag_recall_cancel_ok()
{
	// Only a bag that grew during the recall (a capture paid, a mate banked): a recall started with the winning bag already in hand was
	// bank()'s own choice, and cancelling it ping-pongs.
	if (static_cast<int>(W.me.gems) + W.tributed_us <= wbr2_free_sum)
		return false;
	std::int32_t left = -1;
	if (cambc::detail::sdk_champion_channel_time(static_cast<std::uint32_t>(cambc::detail::sdk_my_champion()), &left) != 0)
		return false;
	return econ::cancel_recall_for_winning_bag(static_cast<int>(left));
}
// A channel runs at my turn's start. True: it goes on, the turn ends.
NOVA_INLINE bool channel_holds()
{
	// A recall that damage will cancel before it completes is lost anyway: cancel it and use this turn.
	bool resume = false;
	if ((W.me.state & ST_RECALL) && !(W.me.state & ST_TRIBUTE))
	{
		const combat::Assessment ca = combat::assess();
		fxr_poll(); // FXR bit 1: the cancels below are actions
		if (combat::recall_doomed(ca) && !(econ::recall_safe()) && cambc::detail::sdk_cancel_channel() == 0)
		{
			resume = resumed();
		}
		else if (willow_recall_cancel_ok(ca) && cambc::detail::sdk_cancel_channel() == 0)
		{
			NLOG("r%d slot %d WR cancel recall hp %.0f\n", W.round, P.my_slot, W.me.hp);
			resume = resumed();
		}
		else if (W.me.gems > 0 && winning_bag_recall_cancel_ok() && cambc::detail::sdk_cancel_channel() == 0)
		{
			wbr2_round = W.round; // early_stages' bank_winning_bag takes this turn.
			resume = resumed();
			CODE_ERR_FIX_CNT(1, true);
		}
	}
	if (!resume && (W.me.state & ST_TRIBUTE))
		fxr_poll(); // FXR bit 1: the cancels below are actions
	// A long tribute channel with an enemy champion known within PC_CHAN_R is cancelled (a stun, a lock or the kill would end it
	// anyway; the hazard of dying in a channel near an enemy is high); the turn goes on.
	if (!resume && (W.me.state & ST_TRIBUTE) && prism_layer::chan_doom_cancel() && prism::channel_doomed() &&
		cambc::detail::sdk_cancel_channel() == 0)
	{
		b781_own_cancel = W.round; // My own cancel, not the enemy's.
		resume = resumed();
	}
	if (!resume && (W.me.state & ST_TRIBUTE) && tribute_doomed() && cambc::detail::sdk_cancel_channel() == 0)
	{
		td_cancel_round = W.round;
		td_cancel_left = td_left;
		NLOG("r%d slot %d trib-doom cancel gems %u hp %d\n", W.round, P.my_slot, W.me.gems, static_cast<int>(W.me.hp));
		resume = resumed();
		td_n = 0;
	}
	if (resume)
		return false;
	publish(((W.me.state & ST_TELEPORT)) ? econ::claim_target() : -1, false); // A hop keeps its claim.
	return true;
}

NOVA_INLINE void spawn_purchases()
{
	if (W.on_spawn && W.gold >= 10)
		cancel_spin_before_action(); // The spin blocks every purchase below.
	if (W.on_spawn)
		econ::recall_hop_prebuy();
	if (W.on_spawn || tavi_layer::shop_anywhere())
		econ::shop();
	if (W.on_spawn)
		econ::spawn_crystal_prebuy(); // The crystal only from what the shop left.
	if (W.on_spawn)
		combat::buy_altar_lock();
	if (W.on_spawn)
		econ::buy_crystal();
}

// The foes a calm walk keeps out of reach of this turn.
NOVA_INLINE std::vector<std::pair<vec2, int>> latched_foes(const combat::Assessment& a)
{
	std::vector<std::pair<vec2, int>> lg_foes;
	// A latched calm turn walks outside known foe reach.
	if (combat::sf_latched == W.round && W.alive)
		for (const auto& f : a.foes)
			if (f.reach >= 0)
				lg_foes.emplace_back(f.pos, f.reach);
	if (W.alive && a.stance == combat::CALM && a.ratio < static_cast<float>(CWG_TAB[2]) / 100.0f && econ::capture_pay_in() < 0)
		for (const auto& f : a.foes)
			if (f.reach >= 0 && !f.remembered)
				lg_foes.emplace_back(f.pos, f.reach);
	if (GSP_TAB[1] != 0)
		gsp_lf = static_cast<int>(lg_foes.size()); // GSP: the lethal zones follow
	if (W.alive)
		combat::lethal_burst_zones(a, lg_foes); // Walks keep out of a lethal foe's reach.
	return lg_foes;
}

NOVA_INLINE void calm_act_first(const combat::Assessment& a)
{
	if (af_armed && a.stance == combat::CALM)
	{
		// CALM: the fallback could only hit a champion in range. Without one a bail would end the turn with no action (and a chain of them
		// would freeze a farming body), so the turn plays normally.
		bool in_range = false;
		if (W.can_attack())
			for (const auto& e : W.enemies)
				if (cheb(e.pos, W.me.pos) <= W.me.range)
				{
					in_range = true;
					break;
				}
		if (in_range)
			af_floor = AF_FLOOR_CALM;
		else
			af_armed = false;
	}
}

NOVA_INLINE void set_dynamic_turn_priority(const combat::Assessment& a)
{
	rx_wc_from = W.me.pos;
	// Initiative for the body that needs it next round; the camp-tank order otherwise.
	const int base = mv::turn_order_base();
	int want = base;
	if (W.alive && mv::camp_threat(W.me.pos) <= 0)
	{
		if (a.stance == combat::FLEE || (W.me.frac() < 0.5f && a.nearest <= 6))
			want = 40; // escape first
		else if (a.stance == combat::FIGHT && a.focus >= 0 && W.enemies[static_cast<std::size_t>(a.focus)].frac() < 0.35f)
			want = 35; // finish first
		if (want < 40 && combat::visible_foes_lethal_next_turn())
		{
			want = 40; // the foes in reach kill me next turn: I move before my mates
			CODE_ERR_FIX_CNT(12, true);
		}
	}
	if (W.alive && ci_layer::me_issac()) // Issac acts before Cassi on camp ties.
	{
		if (CI2_FARM()) // CI2 decision 9
			want = nova::ci2::issac_order(want);
		else
			want = nova::ci::builds::issac_tie(want);
	}
	if (want != cur_prio)
		adopt_prio(want);
}

// Before the stances: holds, wins and captures that outrank a flee or a fight.
template <int DM> NOVA_INLINE bool early_stages(const combat::Assessment& a, bool en_help)
{
	econ::altar_hold_note();
	if (END_HOLD_ON && econ::end_hold_turn()) // A lead-flipping bag with a foe near holds at home.
		return end_free();
	if (!(W.tributed_us + static_cast<int>(W.me.gems) >= 1000 && a.stance == combat::FIGHT && a.focus >= 0 && W.me.kit && !prism_layer::fight_skip_ffw() && !prism::tribute_start_allowed(static_cast<int>(W.me.gems))) && econ::bank_winning_bag()) // A refused bag fights first.
		return end_free();
	CODE_ERR_FIX_CNT(3, wbr2_round == W.round);
	if (combat::game_deny(a))
		return end_free();
	if (econ::ss_pending && W.round >= 40 && M.ready()) // not on a setup turn: the gate read fuel exhaustions 1.19x with the scan on the first ready turn
		econ::spawn_siege_find_groups(); // Once; off the band ss_live stays false, so the flag runs the same instructions either way and the game does not reshuffle.
	if (econ::ss_live && ((a.stance == combat::FLEE && econ::spawn_siege_turn(true)))) // Spawn siege; bit 2 COUNTER.
		return end_task();
	if (combat::retreat_to_spawn_to_heal(a))
		return end_task();
	if (a.stance == combat::FLEE && combat::lethal_burst_flee_turn(a))
	{
		if (DM & 1)
			econ::threat_seen_dom(a.threats);
		else
			econ::threat_seen(a.threats);
		return end_task();
	}
	if (en_help)
	{
		help_post(); // The code between the decision and here neither changes nor reads what help_post uses.
		ENG_CNT_IF(help_last_post == W.round, 5);
	}
	else if (econ::fight_help::fight_call(a)) // A losing FIGHT under fire calls its idle mates.
	{
		help_post();
		if (help_last_post == W.round)
			econ::fight_help::trip_call();
	}
	if (hold_capture(a))
		return end_task();
	if (contest_capture_turn(a))
		return end_task();
	if (a.stance == combat::FLEE && econ::altar_hold_turn()) // Under FLEE too, the game ends otherwise.
		return end_task();
	// A nearly cleared target group is finished instead of fleeing, when rule A and the hits allow.
	if (a.stance == combat::FLEE && finish_first(a))
		return end_task();
	// A carrier near an altar banks before the flee and fight branches when no foe can interrupt it.
	if ((a.stance == combat::FLEE) && (W.me.gems >= 10) && !a.foes.empty())
	{
		std::vector<vec2> fp;
		std::vector<int> fr;
		for (const auto& f : a.foes)
		{
			fp.push_back(f.pos);
			fr.push_back(f.remembered && f.reach < 0 ? -1 : f.reach);
		}
		if (econ::bank_first(fp, fr))
			return end_free();
	}
	if (combat::escape_dash_turn(a))
	{
		if (DM & 1)
			econ::threat_seen_dom(a.threats);
		else
			econ::threat_seen(a.threats);
		return end_task();
	}
	return false;
}

// A body that only flees wastes actions and gets backed into a corner. After FLEE_STREAK flee turns in a row: recall when nothing
// can reach me during the channel; turn and fight when cornered (the enemy no farther than when the flee began and able to hit me).
// Every flee turn under fire calls the team (HELP, event type 4, my cell).
NOVA_INLINE bool flee_streak(const combat::Assessment& a)
{
	streak = (W.round - last_r <= 1) ? streak + 1 : 1;
	last_r = W.round;
	if (streak == 1)
		start_d = a.nearest;
	if (streak >= (FLEE_STREAK) && !a.in_reach && a.nearest >= FLEE_RECALL_D && !W.on_spawn && !(flee_recall_skip_for_willow(a)) && econ::recall_safe() && econ::start_recall())
	{
		streak = 0;
		return end_free();
	}
	return false;
}

// FLZ: the guard a failed flee leaves for the rest of the turn, and the scope that ends it with the turn.
std::optional<mv::AvoidFoeReach> flz_guard;
struct FlzScope
{
	~FlzScope()
	{
		flz_guard.reset();
	}
};
template <int DM> NOVA_INLINE bool flee_stage(const combat::Assessment& a)
{
	if (a.stance != combat::FLEE)
		return false;
	NLOG("r%d slot %d flee ratio %.2f nearest %d hp %.0f\n", W.round, P.my_slot, a.ratio, a.nearest, W.me.hp);
	const ffg::Meter ffg_m(-1); // The branch's measured cost.
	if (flee_streak(a))
		return true;
	// Leave the farming target near what I run from (also foes just out of sight), so I do not walk back.
	std::vector<vec2> from = a.threats;
	for (const auto& f : a.foes)
		if (f.remembered)
			from.push_back(f.pos);
	threat_note<DM>(from);
	if (combat::flee(a))
		return end_task();
	if (combat::flz_r == W.round && !combat::flz_z.empty() && !flz_guard)
		flz_guard.emplace(combat::flz_z, true); // FLZ: the later stages walk outside flee's zones
	return false;
}

// Calm or undecided: a bush probe, a chain, a walk to a joined mate.
NOVA_INLINE bool probe_stage(const combat::Assessment& a)
{
	if (W.alive && !econ::busy_capturing() && (a.stance == combat::CALM || (a.stance == combat::FIGHT && a.focus < 0)) && fuel() > brain_tune::PROBE_FUEL)
	{
		const vec2 bt = combat::bush_chase_target(a);
		if (bt.x >= 0 && mv::step_to(bt, 0, 20))
		{
			NLOG("r%d slot %d BKC probe (%d,%d)\n", W.round, P.my_slot, bt.x, bt.y);
			if (fuel() > brain_tune::PROBE_FUEL)
			{
				const bool bm = W.moved, ba = W.attacked, bc = W.cast, bn = W.no_move;
				perceive(); // The bush's view after the step.
				W.moved = bm;
				W.attacked = ba;
				W.cast = bc;
				W.no_move = bn;
				if (RGB_ON(4)) // RGB bit 4: the memoised move mask predates this perceive
					mv::occ_changed();
				const combat::Assessment a2 = combat::assess();
				if (a2.stance == combat::FIGHT && a2.focus >= 0)
					combat::fight(a2);
			}
			return end_task();
		}
	}
	if (a.stance == combat::CALM && combat::vendetta_chain_calm_focus(a))
		return end_task();
	if (a.stance == combat::FIGHT && a.focus >= 0)
		combat::bush_chase_note_focus(static_cast<int>(W.enemies[static_cast<std::size_t>(a.focus)].h));
	return false;
}

NOVA_INLINE bool fight_stage(const combat::Assessment& a)
{
	if (a.stance != combat::FIGHT)
		return false;
	// The healer fights from the backline next to its partner (champ_willow.cc).
	const ffg::Meter ffg_m(-1); // The branch's measured cost.
	if (support::fight_turn(a))
	{
		NLOG("r%d slot %d WILLOW fight ratio %.2f\n", W.round, P.my_slot, a.ratio);
		return end_task();
	}
	if (combat::fight(a))
	{
		NLOG("r%d slot %d fight ratio %.2f\n", W.round, P.my_slot, a.ratio);
		return end_task();
	}
	return false;
}

// Out of the fight: low health, hidden fire, a retreat under way.
NOVA_INLINE bool retreat_stage(const combat::Assessment& a)
{
	combat::hd_hold(true); // No landing dash inside the retreat and low-HP branches.
	if (econ::ss_live && econ::spawn_siege_turn(a.stance == combat::FLEE))
		return end_task();
	if ((!econ::engaged_now() || (nova::econ::threat_checks::cex_round == W.round)) && combat::hidden_fire()) // Farming under hidden fire too.
		return end_task();
	if (econ::capture_pay_in() < 0 && combat::continue_retreat(a)) // Not off a capture that pays.
		return end_task();
	if (handle_low_hp(a))
		return end_free();
	combat::hd_hold(false);
	return false;
}

// The missing-HP share of max HP above which a body on its spawn stays a turn (a lower bar with a foe near; else .97).
NOVA_INLINE float spawn_stay_missing_hp_bar(const combat::Assessment& a)
{
	return 0.001f * static_cast<float>(1000 - (SPH_TAB[5]));
}
// SPH bit 2 CAMP: on my spawn under awake camp reach, the camps' hits before my next turn land after the turn-end heal. Stay this
// turn when one round of them is below my healed HP and staying carries more HP into next turn than leaving now.
NOVA_INLINE bool spawn_camp_stay(const combat::Assessment& a)
{
	if (!W.on_spawn || a.nearest <= 4)
		return false;
	const float ct = mv::camp_threat(W.me.pos);
	if (ct <= 0.0f || ct >= W.me.maxhp + W.me.shield)
		return false; // no camp (the plain bar's case), or one round of camp hits kills even a healed body: camp_out leaves
	const float gain = W.me.maxhp - std::max(0.0f, ct - W.me.shield) - W.me.hp;
	return gain > spawn_stay_missing_hp_bar(a) * W.me.maxhp;
}

// Errands before the walk to a target: camp reach, healing, shop, bank.
NOVA_INLINE bool errand_stage(const combat::Assessment& a)
{
	if (spawn_camp_stay(a))
	{
		SPH_CNT(2, true);
		econ::spawn_step();
		return end_task();
	}
	// An awake camp of another group hits me and I am not engaged on my target: walk out of its reach before the spawn wait, a shop or
	// heal recall, banking or the walk to a target. Not the healer (her positioning weighs it).
	if (!support::me_active() && econ::camp_out())
		return end_task();
	// Heal to full before leaving spawn (healing happens at turn end on spawn). Not on a spawn tile an awake camp reaches (its hits
	// come back every round, so 97% never comes).
	if (((W.on_spawn && W.me.frac() < 0.97f && (BB13_ON(2) || a.nearest > 4) && (mv::camp_threat(W.me.pos) <= 0)))) // BB13 bit 2: the heal hold with a foe near too
	{
		SPH_CNT(3, false);
		econ::spawn_step();
		return end_task();
	}
	if (shop_recall(a))
		return end_free();
	if (econ::wants_heal() && a.nearest > 6 && (hold_near_willow(a) || econ::go_home())) // Hold at Willow.
		return end_free();
	// The healer follows its partner instead of farming alone (champ_willow.cc); a big bag is banked first.
	(void)(W.me.kit && willow_layer::me() && WL2_ON(1048576));
	if (support::me_active())
	{
		if (econ::want_bank() && econ::bank())
			return end_free();
		if (support::turn(a))
			return true;
	}
	if (combat::support_move(a))
	{
		combat::try_heal();
		return end_task();
	}
	if (econ::want_bank())
	{
		const mv::AvoidCampReach eo_guard(econ::camp_escape_guard_on()); // The bank walk keeps out of the reach just left.
		econ::pcf_calm = W.round;
		if (econ::bank())
			return end_free();
		if (econ::pcf_hold())
		{
			bool pcf_reach = false; // A foe with me in reach: the fallback may step away.
			for (const auto& f : a.foes)
				pcf_reach = pcf_reach || (f.reach >= 0 && cheb(f.pos, W.me.pos) <= f.reach);
			if (!pcf_reach)
				W.no_move = true; // the rest of the turn may hit from here; no step off the tile for bank_i to walk back
		}
	}
	if (econ::ring_breach_turn()) // One body opens the altar ring.
		return end_task();
	return false;
}

// The mate in contact to walk to, nearest first.
NOVA_INLINE const Body* defend_mate()
{
	const Body* best = nullptr;
	int bd = BIG;
	for (const auto& al : W.allies)
	{
		if (al.channeling())
			continue;
		const int d = cheb(al.pos, W.me.pos);
		if (d < 3 || d > DT_RADIUS)
			continue;
		int foes = 0;
		bool contact = false;
		for (const auto& e : W.enemies)
		{
			const int de = cheb(e.pos, al.pos);
			foes += de <= 8 ? 1 : 0;
			contact |= de <= 2;
		}
		if (!contact)
			continue;
		int ours = 1; // me, converging
		for (const auto& o : W.allies)
			ours += (!o.channeling() && cheb(o.pos, al.pos) <= 8) ? 1 : 0; // includes the ally itself
		if (ours < foes)
			continue;
		if (d < bd)
		{
			bd = d;
			best = &al;
		}
	}
	return best;
}

// CB3 bit 16384 PGW (owner replay 01a1bd3f, Ryth r563-569): the guard's step_to ping-pongs when a hole line parts it from the Prism,
// and ending the turn there blocks defend_mate and help_join. Once dz has not fallen for 2 guard turns in a row, a step down the
// walk field of her claimed group (approach's fields) when that field brings me near her; else no guard step, the later stages run.
static __attribute__((noinline)) bool pgw_guard_step(vec2 pz, int dz)
{
	static int pgw_round = -10, pgw_dz = -1, pgw_stall = 0;
	pgw_stall = (pgw_round == W.round - 1 && dz >= pgw_dz) ? pgw_stall + 1 : 0;
	pgw_round = W.round;
	pgw_dz = dz;
	if (pgw_stall < 2)
		return mv::step_to(pz, PG_NEAR, 30);
	const int pg = comms::cgroup(prism::prism_slot());
	const distance_field* f = pg >= 0 ? mv::group_field_ready(pg) : nullptr;
	if (!f || dfget_me(*f) == UNREACH || dfget(*f, pz) == UNREACH || static_cast<int>(dfget(*f, pz)) > PG_NEAR)
		return false;
	return mv::step_field(*f, pg);
}
// Team moves of a calm body: guard, defend, link, tie seek, help, contest.
NOVA_INLINE bool team_stage(const combat::Assessment& a)
{
	// A threatened rich Prism that a mate out of her sight learnt of through team memory: her guard walks back to her once more than
	// PG_FAR away (until within PG_NEAR), before any defending, crew or farming move.
	if (calm_walk_ok(a))
	{
		const vec2 pz = prism::guard_post();
		const int dz = pz.x >= 0 ? cheb(pz, W.me.pos) : -1;
		if (dz < 0 || dz <= PG_NEAR)
			pg_walk = false;
		else if (dz > PG_FAR)
			pg_walk = true;
		if (pg_walk && pgw_guard_step(pz, dz)) // CB3 bit 16384 PGW
			return end_task();
	}
	// Defend together: a calm body walks to an ally 3-DT_RADIUS tiles away that is in contact (a visible foe within 2 of it) when our
	// bodies near that ally, me included, are at least the foes near it; the fight logic engages once I am there.
	if (calm_walk_ok(a))
	{
		const Body* best = defend_mate();
		if (a.converge.x >= 0 && cheb(a.converge, W.me.pos) > 1 && mv::step_to(a.converge, 1, 20))
			return end_task(); // Join the ally in contact instead of fleeing.
		if (best && mv::step_to(best->pos, 1, 20))
			return end_task();
	}
	if (W.alive && combat::cassi_issac_link_step(a))
		return end_task(); // Cassi closes on Issac while linked.
	if (tie_seek_turn(a))
		return end_task();
	if (econ::altar_hold_turn())
		return end_task();
	// A calm, healthy, free body answers a mate's fresh HELP call within EN_HELP_R, after defending a mate, so the order pairs ->
	// defend -> strikes -> mid post stands.
	if (help_join(a))
	{
		ENG_CNT(6);
		return end_task();
	}
	if (combat::spell_poke(a) && W.no_move)
	{
		combat::mfb_free_attack();
		return end_task(); // A walk-excluding spell stands this turn.
	}
	// The zone crew walks to S, gathers and enters together (then econ works the zone's groups only).
	if (zc::crew_turn(a))
		return end_task();
	return false;
}

// The farm step and what closes a turn.
template <int DM> NOVA_INLINE void farm_and_end_turn_stage(const combat::Assessment& a, bool healed_first)
{
	if (W.round <= FARM_RICH_ROUNDS && fuel() < FARM_RICH_FARM_MIN)
		return; // Too little fuel for the farm step on a setup round: end the turn instead of suspending.
	PROF("pre_farm");
	if (!(DM == 3 ? econ::farm_hc3() : DM == 2 ? econ::farm_hc2() : DM ? econ::farm_dom() : econ::farm()) && !zc::idle_turn() && !econ::idle_bank()) // Idle time goes to the altar first; the zone crew waits at the hold.
		econ::idle_move();
	combat::kite_shot_after_move(); // A calm walk can still end with a reset + shot at a champion in range.
	econ::leave_respawn_tile();
	// Never end a turn idle where an awake camp will hit me (unless holding a capture that is due). Not on the last 22k of a turn:
	// after a target choice and a camp hold this escape could spend the turn's last 18k and suspend it.
	if (fuel() > brain_tune::END_ESCAPE_FUEL && !W.moved && !W.attacked && (!W.cast || healed_first) && mv::camp_threat(W.me.pos) > 0 &&
		(!econ::busy_capturing() || W.me.frac() < 0.4f) && !(econ::idle_escape_holds_capture()))
	{
		const auto z = mv::camp_threats_near(7);
		if (!z.empty() && mv::escape(z))
			econ::note_camp_escape();
	}
	// An idle body with no target never ends its turn on a dash launch tile: a teammate's dash starts or lands there. Step off,
	// homeward.
	if (fuel() > brain_tune::UNPARK_FUEL && no_action_yet() && econ::claim_target() < 0 &&
		!econ::busy_capturing() && mv::launch_tile(W.me.pos))
		mv::unpark();
	// A stuck ally whose path runs through my tile gets it (1-wide corridors: bodies block each other).
	mate_yield(fuel() > MY_FUEL && no_action_yet() && !econ::busy_capturing());
	// Never end a turn idle while an enemy champion hits me (a capture in progress holds its region).
	if (fuel() > brain_tune::REACT_FUEL && !econ::busy_capturing())
		combat::react_guard(a);
	if (fuel() > brain_tune::REACT_FUEL)
		combat::heart_dash_end(); // A calm turn's end: the landing dash on a champion (or awake camps), then the basic attack.
	// Rounds 1..START_ROUNDS, a turn that did nothing near our spawn (the opening simulation pending, a fuel skip, a target with no
	// field built yet, no target) ends with one cheap step toward my target or the start goal.
	if (no_action_yet() && W.round <= START_ROUNDS && fuel() > brain_tune::LAST_STEP_FUEL)
		econ::start_step();
	PROF("farm");
	if (no_action_yet() && !W.on_spawn)
		planner::stat_idle(econ::last_act);
	publish_task();
}

template <int DM>
void turn()
{
	turn_senses();
	if (!W.alive)
	{
		dead_turn();
		return;
	}
	if (W.me.stunned)
	{
		// CB3 bit 4 SHX: a stunned body's every action is refused (INT:38; set_priority and comms still work): observe, set the priority,
		// post the claim, and a FIGHT held on idle mates or a losing one under fire still calls them (HELP).
		econ::observe();
		note_tribute_end<DM>();
		re_acted = false;
		combat::Assessment a_st = combat::assess();
		combat::apply_flee_latch_and_history(a_st);
		tm2_stance = a_st.stance == combat::FIGHT ? 1 : a_st.stance == combat::FLEE ? 2 : 0;
		set_dynamic_turn_priority(a_st);
		if (combat::help_called_this_round())
			help_post();
		else if (econ::fight_help::fight_call(a_st))
		{
			help_post();
			if (help_last_post == W.round)
				econ::fight_help::trip_call();
		}
		publish_task();
		return;
	}
	econ::tavi_sell_emblems_buy_greed();
	econ::observe();
	PROF("observe");
	fxr_poll(); // FXR bit 1: a cut inside observe restarts before any action
	note_tribute_end<DM>();
	early_ring_escape();
	const bool afa_ch = W.me.channeling(); // BB14 AFA
	arm_act_first();
	if (W.me.channeling() && channel_holds())
		return;
	if (afa_ch && !W.me.channeling() && !af_armed) // BB14 AFA: a cancelled channel and the turn goes on: act-first arms now
	{
		BB14_CNT(32, true);
		arm_act_first();
	}
	if (!W.me.channeling())
		wbr2_free_sum = static_cast<int>(W.me.gems) + W.tributed_us; // The bag a recall started this turn holds.
	if (!W.me.channeling())
		wr_pre_frac = W.me.frac(); // WILLOW_REGEN: health when a recall starts this turn
	spawn_purchases();
	// r3: an enemy tributing at an altar within 2: a lock cancels the channel (free action).
	if (!combat::deny_tribute())
		combat::end_stun();
	if (ward::ward_bush_by_vanished_foe(combat::vanished_foe_last_tile()))
	{
		// The ward in the bush the foe just entered feeds this turn.
		perceive();
		if (RGB_ON(4)) // RGB bit 4: the memoised move mask predates this perceive
			mv::occ_changed();
	}
	combat::Assessment a_sf = combat::assess();
	fxr_poll(); // FXR bit 1: a cut inside assess restarts before any action
	combat::apply_flee_latch_and_history(a_sf);
	nova::econ::win_channel::force_flee(a_sf); // Flee on a win-channel cancel turn.
	const combat::Assessment& a = a_sf;
	tm2_stance =a.stance == combat::FIGHT ? 1 : a.stance == combat::FLEE ? 2 : 0;
	fight_layer_turn(a);
	combat::linked_pair_cast(8);
	std::vector<std::pair<vec2, int>> lg_foes = latched_foes(a);
	const mv::AvoidFoeReach lg_guard(lg_foes, !lg_foes.empty());
	const FlzScope flz_scope; // FLZ: a failed flee's guard ends with this turn
	combat::heart_dash_arm(a.stance != combat::FLEE);
	combat::act_first_note_assessment(a);
	calm_act_first(a);
	AF_CHECK();
	if (DM & 1)
		econ::dom_commit_note(a.ratio);
	combat::self_shield_after_hit_turn();
	// The fight held on the strength of idle mates calls them (HELP event). Decided here, posted below the win-bank return, so a body
	// that banks to win this turn calls no one.
	const bool en_help = W.alive && combat::help_called_this_round();
	set_dynamic_turn_priority(a);
	PROF("assess");
	// The healer heals first in every branch (the heal is walk-compatible).
	const bool healed_first = support::heal_any();
	// A bag that wins the game banks before hold_capture, the flee and fight branches, the retreats and the recalls when a tribute tile
	// is within EB_WIN_D walk tiles (econ::bank_winning_bag).
	nova::econ::win_bag_flee::note(a.stance == combat::FLEE);
	if (early_stages<DM>(a, en_help) || flee_stage<DM>(a) || probe_stage(a) || fight_stage(a) || retreat_stage(a) || errand_stage(a) || team_stage(a))
		return;
	farm_and_end_turn_stage<DM>(a, healed_first);
}

} // namespace

namespace {
template <int DM>
__attribute__((noinline)) void play_turn_body();
} // namespace
} // namespace nova
