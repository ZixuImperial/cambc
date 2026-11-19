// econ_bank_walk.cc: Walking to an altar and starting the tribute channel.
#include "econ_internal.h"
namespace nova::econ {
// The recall-bank saves walk only if the walk from our spawn, in the field I walk, is more than 8 shorter than mine. Called only
// when the old test (camps-passable a.d_home) already passed.
static int recall_bank_spawn_margin(const distance_field& f)
{
	int best = UNREACH;
	bbforeach(M.my_spawn, [&](vec2 p) { best = std::min<int>(best, dfget(f, p)); });
	return best;
}
static bool recall_bank_saves_walk(std::uint16_t d, int ha)
{
	const vec2 me = W.me.pos;
	if (prism_layer::bank_safe_altar() && GAME_END - now() > 150)
		if (const distance_field* f = prism::safe_altar_field())
		{
			const std::uint16_t ds = dfget(*f, me);
			if (ds != UNREACH && ds <= d + 25) // the Prism altar's walk applies (bank() below): compare in its field
			{
				const int hs = recall_bank_spawn_margin(*f);
				return hs != UNREACH && static_cast<int>(ds) > hs + 8;
			}
		}
	const int hb = recall_bank_spawn_margin(bank_field());
	return hb != UNREACH && static_cast<int>(d) > std::max(ha, hb) + 8;
}
namespace {
static void note_winning_bag_refusal()
{
	if (wbf_r == now())
		return; // one count a round (bank() tries every altar in range, twice with FINISH)
	if (now() - wbf_r == 1)
	{
		wbf_r = now(); // refused again on the tile: waiting there is not the flip-flop (82_B: it banked when the foe left)
		return;
	}
	wbf_n = now() - wbf_r <= WBF_TAB[3] ? wbf_n + 1 : 1;
	wbf_r = now();
}
const Body* nearest_ally(vec2 me)
{
	const Body* mate = nullptr;
	for (const auto& al : W.allies)
		if (!mate || cheb(al.pos, me) < cheb(mate->pos, me))
			mate = &al;
	return mate;
}
// bank: the ways there other than the walk: ring wait, crystal hop, recall hop, recall.
__attribute__((always_inline)) inline TurnStep bank_trip_instead()
{
	if (bag_too_late_to_bank(static_cast<int>(W.me.gems)))
		return TurnStep::Again; // this bag cannot finish by r2000
	if (!wb2_go && ring_wait())
		return TurnStep::Done; // the ring is awake (its camps' damage is in the safety test)
	if (spawn_crystal_bank_trip())
		return TurnStep::Done; // from the spawn to the altar by a crystal hop
	if (M.any_altar && (crystal_count != 0) && !sc_trip_live(1) && mid_hop_try(bank_field(), -1))
		return TurnStep::Done; // the bank walk
	const vec2 me = W.me.pos;
	if (rh_any && sc_bank_f == &bank_field())
	{
		const int rc = recall_hop_cost(sc_bank_r, 2); // home, then the hop to the altar
		const std::uint16_t d0 = dfget(bank_field(), me);
		if (rc != UNREACH && (d0 == UNREACH || static_cast<int>(d0) >= rc + RWK_TAB[2]) && !(pc_hold_why == 6 && d0 != UNREACH) && recall_safe() && start_recall()) // a team bank walks to the altar
			return TurnStep::Done;
	}
	if (walled_in() && !W.on_spawn && dfget(bank_field(), me) == UNREACH)
		return recall_safe() && start_recall() ? TurnStep::Done : TurnStep::Again; // walled in after a crystal trip: the recall takes the bag home
	// Far from every altar but the spawn has one close by: a recall (five turns) is the faster way there, and it
	// heals and lets us shop on the way.
	{
		const std::uint16_t d = dfget(bank_field(), me);
		const int ha = home_altar_dist();
		// Tavi shops anywhere, but the recall still saves the walk to a far altar.
		if (d != UNREACH && ha != UNREACH && static_cast<int>(d) > ha + 8 && !W.on_spawn && !(pc_hold_why == 6 && prism_layer::recall_hold6()) && recall_bank_saves_walk(d, ha) && recall_safe() && start_recall())
		{
			NLOG("r%d slot %d recall-bank gems %u altar %d home-altar %d\n", now(), P.my_slot, W.me.gems, (int)d, ha);
			return TurnStep::Done;
		}
	}
	return TurnStep::Next;
}
__attribute__((always_inline)) inline bool bank_leave_camps(vec2 me, bool& td_walk)
{
	if ((W.round - std::max(td_cancel_round, td_lost_round) < TD_LEAVE_R || (W.round - cc_round < CC_WAIT)) && W.me.gems >= TD_LEAVE_BAG && W.can_move() && fuel() > TD_LEAVE_FUEL)
	{
		auto z = mv::camp_threats_near(7);
		if (!z.empty())
		{
			bool inside = false;
			for (auto& t : z)
				if (t.reach >= 0)
				{
					inside = inside || cheb(t.pos, me) <= t.reach;
					t.reach += 1; // the escape lands past reach + 1
				}
			if (inside && mv::escape(z))
			{
				NLOG("r%d slot %d td-leave escape gems %u\n", now(), P.my_slot, W.me.gems);
				return true;
			}
			td_walk = !inside;
		}
	}
	return false;
}
__attribute__((always_inline)) inline bool bank_channel_camp_move(const AltarI& a, vec2 me)
{
	const int ticks = rs::tribute_turns(static_cast<int>(W.me.gems), prism::has_family(rs::F_TRIBUTE));
	const float inc = incoming_at(me, nullptr);
	if (inc > 0.0f && inc * static_cast<float>(ticks) >= 0.5f * W.me.hp && W.can_move())
		for (const vec2 dd : DIRS)
		{
			const vec2 q = me + dd;
			if (!inb(q) || cheb(q, a.pos) > cambc::constants::submit_gems_range || !mv::free_tile(q) || incoming_at(q, nullptr) > 0.0f)
				continue;
			if (mv::try_move(q))
			{
				NLOG("r%d slot %d chan-camp step gems %u incoming %d ticks %d\n", now(), P.my_slot, W.me.gems, static_cast<int>(inc), ticks);
				return true;
			}
		}
	// No safe tile beside the altar: leave the awake camps' reach and let them sleep (2 rounds with nobody in reach); the leave guard
	// keeps the walk out of the reach and holds outside it, for at most CC_WAIT rounds an episode. Not for a winning bag whose HP
	// covers the camp damage, nor with an enemy known within CC_FOE.
	const bool cc_win = bag_wins_with_mates(static_cast<int>(W.me.gems)) && inc /* EBK bit 1 */ * static_cast<float>(ticks) < W.me.hp;
	if (inc > 0.0f && inc * static_cast<float>(ticks) >= 0.5f * W.me.hp && W.can_move() && !cc_win && prism::nearest_known_enemy() > CC_FOE)
	{
		if (W.round - cc_round >= 2 * CC_WAIT)
			cc_round = W.round; // a new wait episode
		if (W.round - cc_round < CC_WAIT)
		{
			auto z = mv::camp_threats_near(7);
			for (auto& t : z)
				if (t.reach >= 0)
					t.reach += 1; // the escape lands past reach + 1
			if (!z.empty() && mv::escape(z))
			{
				NLOG("r%d slot %d chan-camp wait gems %u incoming %d ticks %d\n", now(), P.my_slot, W.me.gems, static_cast<int>(inc), ticks);
				return true;
			}
		}
	}
	return false;
}
__attribute__((always_inline)) inline bool bank_channel_unsafe(vec2 me)
{
	NLOG("r%d slot %d chan-safe keeps %u gems\n", now(), P.my_slot, W.me.gems);
	const Body* mate = nearest_ally(me);
	if (mate && cheb(mate->pos, me) <= PCSF_MATE + 3 && W.can_move() && mv::step_to(mate->pos, 1)) // a mate close by: join him
		return true;
	if (pcf_calm == W.round)
	{
		pcf_ref = W.round; // brain keeps her here
		return false;
	}
	return go_home(); // the bag stays; toward spawn
}
__attribute__((always_inline)) inline bool bank_tribute_refused(vec2 me)
{
	if (bag_wins_with_mates(static_cast<int>(W.me.gems)))
	{
		note_winning_bag_refusal(); // a winning bag refused at the altar
		if (wbf_n >= WBF_TAB[2] && W.can_move())
		{
			const Body* mate = nearest_ally(me); // as with the Prism's refusal, join a mate close by, else home
			if (mate && cheb(mate->pos, me) <= PCSF_MATE + 3 && cheb(mate->pos, me) >= 2 && mv::step_to(mate->pos, 1))
				return true;
			return go_home();
		}
	}
	return false; // the same rule for the other carriers (a 6+ turn channel next to an enemy champion died 18% of the time)
}
// bank: the rules that refuse a channel at this altar. Next: it may start.
__attribute__((always_inline)) inline TurnStep bank_channel_gate(const AltarI& a, vec2 me)
{
	if (END_HOLD_ON && end_hold_blocks_bank(static_cast<int>(W.me.gems)))
	{
		eh_last = now(); // no long channel here now; home and hold
		return go_home() ? TurnStep::Done : TurnStep::Again;
	}
	if (prism_layer::chan_guard() && !prism::channel_start_ok(static_cast<int>(W.me.gems)))
	{
		if (pcf_calm == W.round)
			pcf_ref = W.round;
		return TurnStep::Again; // never open a long channel with an enemy champion within PC_CHAN_R
	}
	// No long channel on a tile an awake camp hits for half my HP over the channel; step to a tile next to the same altar that no camp
	// reaches and open there next turn. No such tile (or I cannot move): channel as usual.
	if (prism_layer::chan_camp_move() && static_cast<int>(W.me.gems) >= PC_CHAN_BAG)
	{
		if (bank_channel_camp_move(a, me))
			return TurnStep::Done;
	}
	if (prism_layer::chan_safe() && prism_channel_unsafe())
		return bank_channel_unsafe(me) ? TurnStep::Done : TurnStep::Again;
	if (!(prism_layer::chan_skip_trib_ok()) && !wb2_lc && !prism::tribute_start_allowed(static_cast<int>(W.me.gems)))
		return bank_tribute_refused(me) ? TurnStep::Done : TurnStep::Again;
	if (!wb2_lc && new_tribute_blocked())
		return TurnStep::Again; // The damage that doomed the last channel goes on.
	return TurnStep::Next;
}
// bank: open the channel at this altar. False: locked, or the engine refused it.
__attribute__((always_inline)) inline bool bank_open_tribute_at(const AltarI& a)
{
	try
	{
		if (cambc::vision::has_altar_lock(a.pos))
		{
			const auto lock = cambc::vision::altar_lock_at(a.pos);
			cambc::detail::altar_lock_info lkb{};
			if (lock.is_enemy() || enemy_altar_lock_direct(a.pos, lkb))
			{
				return false; // an unlocked altar in range gets the tribute first; the lock is hit below
			}
		}
		combat::protect_tribute(a.pos, static_cast<int>(W.me.gems)); // r3: our lock first (it blocks foe tributes at this altar, not enemy locks, and it cancels any channel of ours there; dr rules audit pass 2, engine 2.0.0 probe)
		RSD(rsd::trib_at = now(); rsd::trib_g = static_cast<int>(W.me.gems); rsd::trib_n = rs::tribute_turns(rsd::trib_g, prism::has_family(rs::F_TRIBUTE)););
		RSD(const int t0 = std::max(1, (rsd::trib_g + 9) / 10); rsd::trib_o = prism::has_tribute() ? std::max(1, (2 * t0 + 2) / 3) : t0; if (prism::has_family(rs::F_TRIBUTE)) ++rsd::c[2]; if (rsd::trib_o != rsd::trib_n) ++rsd::c[3];);
		cancel_spin_before_action();
		cambc::self().submit_gems(a.pos);
		b781_trib_start = now();
		NLOG("r%d slot %d tribute %u gems\n", now(), P.my_slot, W.me.gems);
		return true;
	}
	catch (const std::exception& e)
	{
		NLOG("r%d tribute error %s\n", now(), e.what());
	}
	return false;
}
__attribute__((always_inline)) inline const distance_field* bank_carrier_field(vec2 me)
{
	const distance_field* pc_af = nullptr;
	if (prism_layer::bank_safe_altar() && GAME_END - now() > 150)
		if (const distance_field* f = prism::safe_altar_field())
		{
			const std::uint16_t ds = dfget(*f, me), dn = dfget(bank_field(), me);
			if (ds != UNREACH && (dn == UNREACH || ds <= dn + 25))
				pc_af = f;
		}
	return pc_af;
}
__attribute__((always_inline)) inline bool bank_gate_walk(vec2 me)
{
	bitboard open_adj{};
	int n_gate = 0, n_open = 0;
	// the gates my memory holds dead.
	for (const auto& al : M.altars)
		for (const vec2 dd : DIRS)
		{
			const vec2 p = al.pos + dd;
			const int ci = M.camp_index(p);
			if (ci < 0 || !bbget(M.altar_adj_all, p))
				continue;
			++n_gate;
			const int gi = M.camps[static_cast<std::size_t>(ci)].group;
			if (gi < 0 || gi >= static_cast<int>(gmem_size(mem)))
				continue;
			const auto& m = mem[static_cast<std::size_t>(gi)];
			if (m.status == GS_CLEARED || (m.status == GS_RESPAWN && m.respawn_at - now() > 15))
			{
				bbset(open_adj, p);
				++n_open;
			}
		}
	// step_to_set reads every camp tile out of sight as a wall, so a far open gate would never be reached and the walk would fall back
	// to the nearest (shut) gate tile. Walk down a field to the open tiles instead; wait near a mate-held tile.
	if (n_open > 0 && n_open < n_gate)
		if (const distance_field* gf = gate_mate_bank_field(open_adj))
		{
			const std::uint16_t dg = dfget(*gf, me);
			if (dg != UNREACH && dg > 0)
			{
				if (mv::step_field(*gf))
				{
					mv::collect_dash(0);
					if (!W.me.kit->ranged)
						lock_hit(false);
					return true;
				}
				bool held = false;
				bbforeach(open_adj, [&](vec2 q) { held = held || (cheb(q, me) <= 2 && bbget(W.occ_units, q)); });
				if (held && dg <= 2)
					return true; // a mate channels on the open tile: wait for it here, not at the shut gate
			}
		}
	if (n_open > 0 && n_open < n_gate && mv::step_to_set(open_adj, 60))
	{
		mv::collect_dash(0);
		if (!W.me.kit->ranged)
			lock_hit(false);
		return true;
	}
	return false;
}
__attribute__((always_inline)) inline bool bank_safe_altar_walk()
{
	// The altar tiles no awake camp in sight reaches (another altar, or the same one once its camps sleep); none reachable: hold here,
	// outside the reach, with the bag.
	bitboard safe = M.any_altar ? M.altar_adj : M.altar_adj_all;
	for (const auto& t : mv::camp_threats_near(7))
		if (t.reach >= 0)
		{
			bitboard r;
			r.draw_chebyshev(t.pos, static_cast<float>(t.reach));
			safe &= ~r;
		}
	if (!bbany(safe))
	{
		NLOG("r%d slot %d td-leave hold gems %u\n", now(), P.my_slot, W.me.gems);
		return true;
	}
	if (mv::step_to_set(safe, 60))
	{
		mv::collect_dash(0);
		return true;
	}
	// a far safe tile: the bank walk below, still kept out of the reach by the guard
	return false;
}
__attribute__((always_inline)) inline bool bank_hole_dash(vec2 me)
{
	const int wd = dfget(M.f_altar, me);
	vec2 na{ -1, -1 };
	for (const auto& a : M.altars)
		if (na.x < 0 || cheb(a.pos, me) < cheb(na, me))
			na = a.pos;
	if (na.x >= 0 && (bank_shortcut_trigger(wd, na) || (hs3_commit_g == hsb_alt() && wd != UNREACH)) && (rsw(RSW_HS_BANK) & 1))
	{
		hsb_req_r = now();
		if (hole_shortcut_turn(hsb_alt(), M.f_altar))
		{
			NLOG("r%d slot %d hs-bank gems %u walk %d\n", now(), P.my_slot, W.me.gems, wd);
			if (!W.me.kit->ranged)
				lock_hit(false);
			return true;
		}
	}
	return false;
}
bool bank_i()
{
	AF_CHECK();
	if (const TurnStep s = bank_trip_instead(); s != TurnStep::Next)
		return s == TurnStep::Done;
	const vec2 me = W.me.pos;
	// a recently cancelled tribute beside awake camps: out of their reach first, then keep out of it.
	bool td_walk = false;
	if (bank_leave_camps(me, td_walk))
		return true;
	mv::AvoidCampReach td_guard(td_walk); // active only when I stand outside every awake camp's reach
	// an altar where no teammate channels first (pass 0): an enemy lock cancels every channel at one altar.
	for (int pass = 0; pass < 2; ++pass)
	for (const auto& a : M.altars)
	{
		if (cheb(a.pos, me) > cambc::constants::submit_gems_range)
			continue;
		if (const TurnStep s = bank_channel_gate(a, me); s != TurnStep::Next)
			return s == TurnStep::Done;
		if (pass == 0)
		{
			bool shared = false;
			for (const auto& al : W.allies)
				shared |= (al.state & ST_TRIBUTE) && cheb(al.pos, a.pos) <= 1;
			if (shared)
				continue;
		}
		if (bank_open_tribute_at(a))
			return true;
	}
	// No tribute was possible from here. An enemy lock on an altar within my basic attack range is hit now (a ranged body from 3 tiles;
	// five hits break it); a melee body still steps toward the altar this turn and may hit after the step.
	if (nova::econ::twin_altar::walk_to_free_twin_altar(me)) // a free twin altar within 3 steps first
		return true;
	if (lock_hit(false))
	{
		if (W.me.kit->ranged || bank_dist_here() == 0)
			return true;
		mv::step_field(bank_field());
		return true;
	}
	const bool ring_dash = M.ring && !has_ring_field && !wb2_go; // no gap known: the dash route, not the camps-passable walk (the winning-bag walk has its own)
	if ((bank_dist_here() == UNREACH || ring_dash) && dash_bankable() && dn::step(dn::GOAL_ALTAR))
		return true;
	// as in approach_group: a stranded carrier whose launch a teammate blocks recalls (banks from home).
	if (bank_dist_here() == UNREACH && stranded() && dn::blocked_rounds() >= 4 && recall_safe() && start_recall())
		return true;
	mv::collect_dash(2); // the altar walk dashes from 3 tiles out (and with foes in sight when it lands out of reach)
	// the carrier walks to the plan's safest altar (the enemy's walk longest) unless it is a long detour or late.
	const distance_field* pc_af = bank_carrier_field(me);
	// the open-altar field leads to the nearest gate tile, open or not; walk to a tile whose gate group is dead.
	if (!pc_af && !wb2_go && !M.any_altar && M.has_altar_open && !(M.ring))
	{
		if (bank_gate_walk(me))
			return true;
	}
	if (td_guard.active && bank_safe_altar_walk())
		return true;
	// The carrier's walk to the altar takes the single hole dash that beats it (hole_shortcut_turn: field + cooldown wait + walk after the dash;
	// foe-within-10 safety rule). Only when a hole lies between me and the nearest altar and the walk detours round it; the field is
	// built in background fuel after the request.
	if (!pc_af && M.any_altar && M.has_altar && W.can_move() && !W.moved && !td_guard.active)
	{
		if (bank_hole_dash(me))
			return true;
	}
	if (mv::step_field(pc_af ? *pc_af : bank_field()))
	{
		if (M.ring)
			pf_bw_round = now();
		mv::collect_dash(0);
		if (!W.me.kit->ranged)
			lock_hit(false); // melee walks and hits in one turn
		return true;
	}
	const bool walked = mv::step_to_set(M.any_altar ? M.altar_adj : M.altar_adj_all, 60);
	mv::collect_dash(0);
	if (!walked && td_guard.active)
		return true; // hold outside the reach with the bag
	return walked;
}
} // namespace
bool bank()
{
	const vec2 p0 = W.me.pos;
	const bool ok = bank_i();
	if (ok && !(W.me.pos == p0))
		bs_mark = now();
	return ok;
}
} // namespace nova::econ

// ---------------------------------------------------------------- walk to the twin altar when the near one is locked: walk to a
// free twin altar instead of a lock hit. Unity build: after econ_*.cc.
namespace nova::econ::twin_altar
{
namespace
{
// Firing counter (firecount puts one at each function entry): the walk to the free twin replaces a lock hit.
void twin_walk_firing_counter()
{
}
// An enemy lock stands on the altar (the engine's read; both teams' locks may stand, so theirs is read directly too).
bool enemy_locked(vec2 p)
{
	try
	{
		if (!cambc::vision::has_altar_lock(p))
			return false;
		return cambc::vision::altar_lock_at(p).is_enemy() || nova::econ::enemy_lock_on(p);
	}
	catch (...)
	{
		return true; // unread: not free
	}
}
} // namespace
bool walk_to_free_twin_altar(vec2 me)
{
	if (W.me.gems == 0u || W.attacked || W.moved || !W.can_move() || !W.alive || !M.has_altar)
		return false;
	const int r = std::max(1, W.me.range);
	bool lk = false; // lock_hit would hit an enemy lock from here
	for (const auto& a : M.altars)
		if (cheb(a.pos, me) <= r && enemy_locked(a.pos))
			lk = true;
	if (!lk)
		return false;
	vec2 best{ -1, -1 };
	int bd = 1 << 20;
	for (const auto& a : M.altars)
	{
		const int c = cheb(a.pos, me);
		if (c <= 1 || c > ALT_TWIN_R || c >= bd || !bbget(W.own_vis, a.pos) || enemy_locked(a.pos))
			continue;
		best = a.pos;
		bd = c;
	}
	if (best.x < 0)
		return false;
	bitboard goals;
	goals.draw_chebyshev(best, 1.0f);
	goals &= M.altar_adj;
	if (!mv::step_to_set(goals, 30))
		return false;
	twin_walk_firing_counter();
	return true;
}
} // namespace nova::econ::twin_altar
