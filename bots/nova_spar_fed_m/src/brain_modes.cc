// brain_modes.cc: Mode loops and the spin at turn end.
#include "brain_internal.h"
namespace nova {
// In the free slot (after the turn's last fuel read): a turn the engine suspended ended in a later round.
__attribute__((noinline)) void act_first_mark_overlong_turn()
{
	if (af_turn_round >= 0 && static_cast<int>(round_number_nc()) != af_turn_round)
		af_heavy_round = af_turn_round;
	af_turn_round = -1;
}
// FXR bit 1 (common_flags.h): a stale call (suspended, resumed in a later round) unwinds to fxr_run, which runs the round's turn
// again from spin_on_turn_start. Code from the old round never acts: every action and shared-memory write polls the round first.
extern bool sps_mine;
// The turns of a mode (1 DOM, 2 hoard, 3 DOM + hoard), entered from a free slot; never returns: it ends each turn itself.
template <int DM>
__attribute__((noinline)) void mode_loop()
{
	while (true)
	{
		try
		{
			spin_on_turn_end();
		}
		catch (...)
		{
		}
		cambc::detail::sdk_yield(); // BB8P: as main.cc, no fflush (~50 fuel a turn)
		if (spin_on_turn_start()) // My spin is cancelled before anything else.
			continue;
		try
		{
			planner::stat_turn_begin();
			play_turn_body<DM>();
			planner::stat_turn_end(planned);
			act_first_mark_overlong_turn();
		}
		catch (const std::exception& e)
		{
			NLOG("turn error: %s\n", e.what());
			(void)e;
		}
		catch (...)
		{
			NLOG("turn error: unknown\n");
		}
	}
}
// Entered from play_turn's free slot (after stat_turn_end, the turn's last fuel read) once the trigger fires.
__attribute__((noinline)) void dom_loop()
{
	if (econ::dc_mode() == 3)
		mode_loop<2>(); // Hoard mode (decided with DOM's trigger).
	if (econ::dc_mode() == 4)
		mode_loop<3>(); // DOM plus hoard.
	mode_loop<1>();
}
__attribute__((noinline)) bool dom_commit_switch()
{
	try
	{
		return econ::dom_commit_free_slot();
	}
	catch (...)
	{
		FXR_PASS();
		return false;
	}
}

// Spin. sps_mine = the recall now running is my own spin (never a real recall); sps_idle = the turn that started it took no action
// (a late spin).
bool sps_mine = false;
bool sps_idle = false;

void cancel_pending_spin()
{
	sps_pending = false;
	cambc::detail::sdk_cancel_channel();
}

bool spin_on_turn_start()
{
	sps_pending = false;
	if (!sps_mine)
		return false;
	sps_mine = false;
	const std::uint32_t h = static_cast<std::uint32_t>(cambc::detail::sdk_my_champion());
	cambc::detail::champion_info ci{};
	if (cambc::detail::sdk_champion(h, &ci) != 0)
	{
		cambc::detail::sdk_cancel_channel(); // unreadable: cancel anyway (only my spin can run now; an error if none)
		return false;
	}
	const std::uint32_t st = static_cast<std::uint32_t>(ci.state);
	if (!(st & ST_ALIVE) || !(st & ST_RECALL) || (st & (ST_TRIBUTE | ST_TELEPORT)))
		return false; // damage, a stun or death ended it already
	std::int32_t left = -1;
	const bool timed = cambc::detail::sdk_champion_channel_time(h, &left) == 0;
	if (!planned || !M.ready() || !timed || left < 4)
		cambc::detail::sdk_cancel_channel(); // setup turns, or a spin that ran on (a suspended turn): cancel now
	else
		sps_pending = true; // cancelled by the turn's first action (cancel_spin_before_action), or kept by a recall (pending_spin_becomes_recall)
	return false;
}

static void walk_cast_end()
{
	if (!W.alive || cur_prio >= 38 || W.me.kit == nullptr || fuel() < 3000)
		return;
	const Kit& k = *W.me.kit;
	if (!((k.slot_dmg >= 0 && k.dmg_excl) || (k.slot_aoe >= 0 && k.aoe_excl) || (k.slot_cc >= 0 && k.cc_excl)))
		return;
	const int next = RGB_ON(16) ? static_cast<int>(round_number_nc()) + 1 : W.round + 1; // RGB bit 16: the real round after a resume
	const bool a_starts = (next & 1) != 0; // GameRules :34, :126: team A starts odd rounds
	if (a_starts != (cambc::detail::cached_my_team == 0))
		return;
	cambc::detail::champion_info ci{}; // FB2 FU5: one read gives my position and state (no cambc::self() copy)
	if (cambc::detail::sdk_champion(static_cast<std::uint32_t>(cambc::detail::sdk_my_champion()), &ci) != 0)
		return;
	const vec2 me{ ci.x, ci.y };
	if (me == rx_wc_from || (static_cast<std::uint32_t>(ci.state) & (ST_RECALL | ST_TRIBUTE | ST_TELEPORT)))
		return;
	bool target = false;
	for (const auto& e : W.enemies)
		target |= cheb(e.pos, me) <= 4 && (e.state & 32u) != 0; // 32: completed_turn
	if (!target)
		return;
	for (const auto& vc : W.camps)
		if (vc.awake && cheb(M.camps[static_cast<std::size_t>(vc.ci)].pos, me) <= 5)
			return;
	const auto mh = static_cast<std::uint32_t>(cambc::detail::sdk_my_champion());
	bool bb8_ready = false;
	for (int s : { k.dmg_excl ? k.slot_dmg : -1, k.aoe_excl ? k.slot_aoe : -1, k.cc_excl ? k.slot_cc : -1 })
	{
		std::int32_t cd = 0;
		if (s >= 0)
			cambc::detail::check(cambc::detail::sdk_champion_cooldown(mh, static_cast<std::uint32_t>(s), &cd));
		if (s >= 0 && cd <= 1)
			bb8_ready = true;
	}
	if (!bb8_ready)
		return;
	set_prio(38);
	cur_prio = 38;
}
void spin_on_turn_end()
{
	if (W.alive && W.me.stunned && W.round == static_cast<int>(round_number_nc())) // CB3 bit 4 SHX: nothing to end
	{
		sps_mine = false;
		return;
	}
	try
	{
		walk_cast_end();
	}
	catch (...)
	{
		FXR_PASS();
	}
	if (KS_ON && (W.attacked || W.cast) && W.can_move() && M.ready())
		econ::ks_turn();
	if (BS_ON && M.ready()) // The last act of the turn.
		econ::bank_step_turn();
	if (sps_pending)
	{
		fxr_poll(); // FXR bit 1: the cancel is an action
		sps_pending = false; // a turn with no action and no recall: restart the spin (a fresh 4 left)
		cambc::detail::sdk_cancel_channel();
	}
	const std::uint32_t h = static_cast<std::uint32_t>(cambc::detail::sdk_my_champion());
	cambc::detail::champion_info ci{};
	if (cambc::detail::sdk_champion(h, &ci) != 0)
	{
		sps_mine = false;
		return;
	}
	const std::uint32_t st = static_cast<std::uint32_t>(ci.state);
	if (st & (ST_RECALL | ST_TRIBUTE | ST_TELEPORT))
		return; // a channel runs: a real recall (sps_mine false) or a late spin kept by spin_on_turn_start (true)
	sps_mine = false;
	if (!(st & ST_ALIVE) || !M.ready() || fuel() < SPS_FUEL || ci.x < 0 || ci.y < 0 || bbget(M.my_spawn, vec2{ ci.x, ci.y }) ||
		prism::has_family(rs::F_HOME))
		return;
	sps_idle = !W.moved && !W.attacked && !W.cast;
	fxr_poll(); // FXR bit 1: the spin is an action
	if (cambc::detail::sdk_recall() == 0)
		sps_mine = true;
}
} // namespace nova
