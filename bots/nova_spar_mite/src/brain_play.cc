// brain_play.cc: play_turn: analysis, the turn, its tail and background work.
#include "brain_internal.h"
namespace nova {
void play_turn()
{
	strat::begin_turn();
	play_turn_body<0>();
	act_first_mark_overlong_turn();
	if (rsw(RSW_DOM_COMMIT) && dom_commit_switch()) // The free slot decides the trigger once.
		dom_loop();
}

namespace {
// A map-analysis or setup turn with no fuel for turn logic still steps toward the start goal; no step is taken that a long analysis
// stage left no fuel for (the fast opening path runs instead).
NOVA_INLINE void prestep_turn()
{
	if (fuel() > FG_PRESTEP_MIN)
		econ::start_prestep();
	else
		econ::om_blind_step();
}
// Map analysis and the setup, spread over the first turns. True: no fuel left for a turn this round.
template <int DM> NOVA_INLINE bool setup_stage()
{
	if (!M.ready())
	{
		// Static analysis is spread over the first turns; champions wait on spawn meanwhile.
		M.lean = true;
		M.pause_at_ready = true;
		M.init(25000);
		PROF("init");
		if (!M.ready())
		{
			prestep_turn();
			return true;
		}
	}
	if (!planned)
	{
		// The setup costs 18-29k fuel; 50k keeps over 20k spare.
		if (fuel() < brain_tune::FIRST_SETUP_FUEL)
		{
			econ::start_prestep(); // A turn waiting for the setup's fuel steps toward the start goal.
			return true;
		}
		setup();
		M.pause_at_ready = false;
		PROF("setup");
		// Act in this turn when the fuel allows: the opening simulation keeps its own reserve and resumes next turn.
		if (fuel() < SPD_TAB[2])
		{
			prestep_turn();
			return true;
		}
	}
	return false;
}
NOVA_INLINE bool attack_left() { return W.alive && !W.attacked && fuel() > brain_tune::FREE_ACT_FUEL; }
// SRL bit 4 SHK1: gold a kill brought this turn arrives after the turn-start shop; a body still on its spawn buys now (GR:110).
static __attribute__((noinline)) void srl_kill_gold_shop()
{
	if (!M.ready() || !bbget(M.my_spawn, W.me.pos))
		return;
	const std::uint32_t g = cambc::self().gold_count();
	if (g < 30u || g < W.gold + 10u)
		return;
	W.gold = g;
	econ::shop();
}
// After the turn's choice: what an unused move, attack or heal can still do.
NOVA_INLINE void turn_tail()
{
	if (mv::bsh_hold_r == W.round)
		combat::bush_hold_turn();
	if (deadend_yield_pre()) // Call deadend_yield only when an ally can pass its first tests.
		deadend_yield();
	re_acted = W.attacked || W.cast; // An early bail returns above and counts as no action.
	PROF("turn");
	if (attack_left())
		hit_champion_before_lock();
	// An attack not used this turn breaks an enemy lock on an altar in range (five hits remove one).
	if (attack_left())
		econ::lock_hit(true);
	// A basic attack still unused hits a living cluster of a harmless group my team works on.
	if (attack_left())
		econ::hit_claimed_camp_in_range();
	// Stellar and Cassi: any turn with no walk and no cast (a capture, a wait, an idle turn) puts a ready damage spell on an awake camp
	// an ally holds.
	if (W.alive && !W.moved && !W.cast && !W.me.channeling() && fuel() > brain_tune::FREE_ACT_FUEL)
		combat::assist_cast();
	// Willow: a heal not cast yet this turn is tried again where the turn ended (the heal is walk-compatible, so a walk may have
	// brought an ally into range).
	if (W.alive && !W.cast && !W.me.channeling() && support::heal_any_may() && fuel() > brain_tune::FREE_ACT_FUEL) // FB5 HAW1
		support::heal_any();
	if (W.on_spawn && W.alive && !W.me.channeling() && fuel() > brain_tune::FREE_ACT_FUEL)
		srl_kill_gold_shop();
}
// Background analysis with whatever fuel is left this turn: map stages first, then the per-group path fields.
NOVA_INLINE void background_work()
{
	// Ward work waits for the map stages.
	if (!M.done() && M.groups_ready() && fuel() > brain_tune::MAP_INIT_FUEL)
		econ::pre_tables(); // v7xx PRE2: the groups are final at ST_GROUPS; bodies camp before the map stages finish
	if (!M.done() && fuel() > brain_tune::MAP_INIT_FUEL)
		M.init(brain_tune::MAP_INIT_KEEP);
	else if (!M.done() && W.round >= SRB_TAB[4] && fuel() > (static_cast<long>(SRB_TAB[2])) + SRB_TAB[3])
		M.init(static_cast<long>(SRB_TAB[2])); // FGD BGO: keep the fuel the turn's last acts need
	else if (M.done() && fuel() > brain_tune::BG_FUEL)
	{
		combat::fc_background(45000); // Once: the walk field from the enemy spawn (zone of a tile).
		if (M.ring_todo || M.open_todo)
			M.gate_step(35000); // The deferred ring scan and open field.
		// DEAD_BG: a dead body's turn (the background block runs while dead too, after intel::end_turn has posted its ward news) builds up
		// to three dash layers from the spawn; dashnav's dead bar makes them fit.
		for (int i = 0, n = W.alive || !DEAD_BG ? 1 : 3; i < n && fuel() > brain_tune::BG_FUEL; ++i)
			if (!dn::background(30000))
				break;
		econ::pre_tables(); // v7xx PRE1: once, before the first camp turn needs them
		econ::build_bg(); // The shop list in spare fuel.
		econ::dead_end_cache_fill(35000);
		econ::hs3_bg(HS3_RESERVE); // Before the other group fields (it needs only its own group's field).
		if (!xt_dense())
			travel_table_build(30000);
		travel_close_step(40000);
		mv::build_fields(25000);
	}
	PROF("bg");
	// Then the ward, where we ended up (path fields come first: on a big map each costs ~30k and farming walks badly without them).
	// ward::act checks its own fuel.
	if (!(W.alive && W.me.stunned)) // CB3 bit 4 SHX: a stunned ward is refused and bans the tile 40 rounds
		ward::act();
	PROF("ward");
	// Ward and intel analysis steps check their own cost. They stop at 24k rather than 16k, because suspended turns could end a few k
	// over the budget at the very end of the turn.
	if (M.done() && fuel() > brain_tune::ANALYSE_FUEL && econ::recall_hop_early())
		econ::spawn_crystal_background(brain_tune::ROUTE_KEEP); // The routes before the analyses.
	if (M.done() && fuel() > brain_tune::ANALYSE_FUEL)
	{
		intel::analyse(brain_tune::ANALYSE_KEEP);
		ward::analyse(brain_tune::ANALYSE_KEEP);
	}
	PROF("bg2");
	// The spawn crystal routes from our spawn, after the fields, the ward and the analyses.
	if (M.done() && fuel() > brain_tune::ANALYSE_FUEL)
		econ::spawn_crystal_background(brain_tune::ROUTE_KEEP);
	if (W.alive && fuel() > brain_tune::ANALYSE_FUEL)
		econ::crystal_plan_background();
	if (M.done())
		for (int i = 0; i < 4 && dn::altar_route_stage(econ::FB_TAB[2]); ++i) // Last, out of what is really left.
		{
		}
}

// BB14 AFC (caller read the flag): after an act-first bail, next round's priority as set_dynamic_turn_priority sets it from what is
// known (no stance: CALM, the nearest visible foe); with little fuel left the base order. Then
// re_acted and the task post the bail skipped.
static __attribute__((noinline)) void afc_after_bail()
{
	combat::Assessment fa;
	for (const auto& e : W.enemies)
		fa.nearest = std::min(fa.nearest, cheb(e.pos, W.me.pos));
	const int before = cur_prio;
	if (fuel() > BB14_TAB[2])
		set_dynamic_turn_priority(fa);
	else
	{
		int want = mv::turn_order_base();
		if (want != cur_prio)
			adopt_prio(want);
	}
	BB14_CNT(16, cur_prio != before);
	re_acted = W.attacked || W.cast;
	publish_task();
}
template <int DM>
__attribute__((noinline)) void play_turn_body()
{
	PROF("start");
	(void)0;
	struct R2sEnd // v699 R2S bit 1 SRT: the stale-call poll covers this play call only
	{
		~R2sEnd()
		{
		}
	} r2s_end;
	(void)r2s_end;
	mv::fxr_entry_resets(); // FXR: hand-set toggles an unwound call left set
	if (setup_stage<DM>())
		return;
	// A check point below AF_FLOOR unwinds here: the cheap fallback, then the turn ends (no background).
	try
	{
		turn<DM>();
	}
	catch (const AfBail&)
	{
		af_armed = false;
		af_heavy_round = W.round;
		// Never on stale state: a turn the engine suspended and resumed in a later round issues no fallback.
		if (static_cast<int>(round_number_nc()) == W.round)
		{
			combat::act_first_fallback(false);
			afc_after_bail();
		}
		return;
	}
	catch (...)
	{
		af_armed = false;
		throw;
	}
	if (spd_split) // Set only with the flag: the first turn ended after econ::observe.
	{
		spd_split = false;
		if (fuel() > FG_PRESTEP_MIN)
			econ::start_prestep(); // The split turn still steps toward the start goal.
		return;
	}
	if (af_armed)
	{
		af_armed = false;
		// A fight turn that ends with no action and little fuel still hits a champion in range.
		if (W.alive && !W.moved && !W.attacked && !W.cast && fuel() < af_floor && static_cast<int>(round_number_nc()) == W.round)
			combat::act_first_fallback(true);
	}
	if (combat::hpr_pending()) // v7xx NBF bit 128 HPR1: floor 2k
		combat::hpr_refresh(); // v699 HPR bit 1: my hits lower the foe memory's HP
	if (!(W.alive && W.me.stunned)) // CB3 bit 4 SHX: a stunned turn has no tail
		turn_tail();
	if (combat::hpr_pending()) // v7xx NBF bit 128 HPR1: floor 2k
		combat::hpr_refresh(); // HPU HPRT1: the tail's champion hits lower the foe memory too
	// Team news after the turn's actions (~2k).
	if (fuel() > brain_tune::INTEL_END_FUEL)
		intel::end_turn();
	PROF("intel");
	background_work();
}
} // namespace
} // namespace nova
