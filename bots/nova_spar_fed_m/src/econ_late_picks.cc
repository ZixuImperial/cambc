// econ_late_picks.cc: Dominant commits, gated team, hoard and hold-group decisions.
#include "econ_internal.h"
namespace nova::econ {
namespace {
int dc_note_round = -1000;
float dc_ratio_v = 0.0f;
int dch_drop = -1; // the round the dc turn last let my target D go
// My estimate of the team's carried gems: my bag + every ally's bag (read when in vision, else its last read within 150 rounds).
std::array<int, 8> gt_bag{}, gt_bag_r{ -1000, -1000, -1000, -1000, -1000, -1000, -1000, -1000 };
// The trigger (static map data: every body agrees). 0 = not ready yet, 1 = off, 2 = on. Nothing is allocated or changed.
int dom_commit_decide()
{
	if (!M.ready() || M.groups.empty() || gmem_size(mem) != static_cast<std::size_t>(M.ng))
		return 0;
	const int ng = M.ng;
	int best = -1, bg = 0;
	for (int gi = 0; gi < ng; ++gi)
	{
		const auto& g = M.groups[static_cast<std::size_t>(gi)];
		if (g.n_mono == 0 && g.gems > bg)
		{
			bg = g.gems;
			best = gi;
		}
	}
	if (best < 0 || bg < DC_MIN_GEMS)
		return 1;
	int tot = 0, nx = 0;
	for (int gi = 0; gi < ng; ++gi)
	{
		const auto& g = M.groups[static_cast<std::size_t>(gi)];
		tot += g.gems;
		if (gi != best)
			nx = std::max(nx, g.gems);
	}
	if (100 * bg < DC_SHARE * tot || bg < DC_RATIO * nx || (100 * bg >= DC_NEAR_TOTAL * tot && !(M.groups[static_cast<std::size_t>(best)].n_att == 0)))
		return 1;
	const auto& g = M.groups[static_cast<std::size_t>(best)];
	if (g.access != ACC_WALK || g.d_home == UNREACH || g.members.empty() || g.n_golem > 0 || g.n_att > DC_MAX_ATT ||
		is_gate(best) || is_big_group_static(g))
		return 1;
	dc_v = best;
	return 2;
}
// My walk to group gi: its field when built, else my last travel table, else Chebyshev x 5/4 + 2.
int dom_commit_walk(int gi)
{
	if (const distance_field* f = mv::group_field_ready(gi))
	{
		const std::uint16_t d = dfget_me(*f);
		if (d != UNREACH)
			return static_cast<int>(d);
	}
	if (travel.size() == static_cast<std::size_t>(M.ng) && travel[static_cast<std::size_t>(gi)] != UNREACH)
		return static_cast<int>(travel[static_cast<std::size_t>(gi)]);
	return cheb(W.me.pos, M.groups[static_cast<std::size_t>(gi)].anchor) * 5 / 4 + 2;
}
// D is up for a body `walk` rounds away: alive or cleared, or back within the walk plus the respawn-wait cap.
bool dom_commit_group_up(int gi, int walk)
{
	const auto& m = mem[static_cast<std::size_t>(gi)];
	return m.status != GS_RESPAWN || static_cast<float>(m.respawn_at - now() - walk) <= crew_wait_limit(M.groups[static_cast<std::size_t>(gi)]);
}
// v1: 2+ enemies near D (sightings within 8 in the last 6 rounds), unless I am within 8 of D with a local assess ratio >= 1.
bool dom_commit_contested(int gi)
{
	if (siege_enemies_near_group(gi, 6) < SG_ABORT_N)
		return false;
	return !(dc_note_round == now() && dc_ratio_v >= 1.0f && cheb(W.me.pos, M.groups[static_cast<std::size_t>(gi)].anchor) <= 8);
}
__attribute__((always_inline)) inline bool dom_commit_turn() // inlined: called every turn
{
	const int gi = dc_v;
	if (gi < 0 || (!opened && !opn_dc) || zc::on() || gmem_size(mem) != static_cast<std::size_t>(M.ng))
		return false;
	const auto& g = M.groups[static_cast<std::size_t>(gi)];
	const int walk = dom_commit_walk(gi);
	const int alt = g.d_altar != UNREACH ? static_cast<int>(g.d_altar) : 30;
	const bool dwk_far = walk >= DWK_TAB[3] && !dn::dasher() && walk * 100 > DWK_TAB[2] * cheb(W.me.pos, g.anchor);
	if (dwk_far || !bankable() || now() + walk + alt + 60 > GAME_END || !dom_commit_group_up(gi, walk) || dom_commit_contested(gi))
	{
		if (T.target == gi)
			dch_drop = now(); // D let go
		return false;
	}
	if (T.target == gi)
		return true; // (1) keep D
	const auto& m = mem[static_cast<std::size_t>(gi)];
	if (my_slot() == TM.sup || (W.me.kit && prism_layer::squad_skip()) || sg_op_group() >= 0 || W.me.frac() < SG_HP ||
		m.fail_until > now() || !zc::allow_fast(gi, my_slot()))
		return false;
	if (dch_drop >= 0 && now() - dch_drop < DCH_HOLD)
		return false; // no re-commit right after letting D go
	set_target(gi, 1.0f, SG_K); // (2) commit to D
	return true;
}
// A mate claiming group gi that is not there yet can walk there within `within` rounds.
bool dom_commit_mate_coming(int gi, int within)
{
	const auto& g = M.groups[static_cast<std::size_t>(gi)];
	const int rad = (g.reach_max > 0 ? g.reach_max : 1) + 4;
	for (int s = 0; s < TM.n && s < 8; ++s)
	{
		if (s == my_slot() || TM.claim[static_cast<std::size_t>(s)] != gi || !siege_ally_alive(s))
			continue;
		const Body* b = W.ally_by_slot(s);
		if (b && cheb(b->pos, g.anchor) <= rad)
			continue; // here already
		if (!b)
			continue; // unseen: its eta would read D's own anchor (0)
		if (siege_slot_arrival_eta(s, gi) <= within)
			return true;
	}
	return false;
}
// v1's hooks key on D itself.
bool dc_is(int gi) { return gi >= 0 && gi == dc_v; }
int gate_group_target()
{
	if (gt_v != -2)
		return gt_v;
	if (!M.done() || M.groups.empty() || gmem_size(mem) != static_cast<std::size_t>(M.ng))
		return -1; // retried on a later turn
	gt_v = -1;
	bool rbg = false; // a ring map whose gate groups include a monolith/golem group
	if (M.ring)
		for (int gi : M.gate_groups)
			rbg |= gi >= 0 && gi < M.ng && M.groups[static_cast<std::size_t>(gi)].n_mono + M.groups[static_cast<std::size_t>(gi)].n_golem > 0;
	if (M.any_altar || M.gate_groups.empty() || (M.ring && !rbg) || !M.has_altar_open)
		return gt_v;
	int best = UNREACH + 1;
	for (int gi : M.gate_groups)
	{
		if (gi < 0 || gi >= M.ng)
			continue;
		const auto& g = M.groups[static_cast<std::size_t>(gi)];
		if (rbg && g.n_mono + g.n_golem == 0)
			continue; // the boss gates only
		if (g.access == ACC_WALK && g.d_home != UNREACH && !g.members.empty() && static_cast<int>(g.d_home) < best)
		{
			best = static_cast<int>(g.d_home);
			gt_v = gi;
		}
	}
	return gt_v;
}
int team_bag_total()
{
	int t = static_cast<int>(W.me.gems);
	for (int s = 0; s < P.n && s < 8; ++s)
	{
		if (s == my_slot() || !siege_ally_alive(s))
			continue;
		std::uint32_t g = 0;
		if (cambc::detail::sdk_champion_gems(P.handle[static_cast<std::size_t>(s)], &g) == 0)
		{
			gt_bag[static_cast<std::size_t>(s)] = static_cast<int>(g);
			gt_bag_r[static_cast<std::size_t>(s)] = now();
		}
		if (now() - gt_bag_r[static_cast<std::size_t>(s)] <= 150)
			t += gt_bag[static_cast<std::size_t>(s)];
	}
	return t;
}
// The crew at the gate may start without estimate()'s feasibility (the clear model has no tank rotation for two strong attackers).
bool gt_go(int gi, int n) { return gi >= 0 && gi == gt_v && n >= GT_K; }
// refresh_target's hook: true when this turn keeps the gate as my target or commits me to it.
bool gate_target_turn()
{
	const int gi = gate_group_target();
	if (gi < 0 || !opened || zc::on() || !W.me.kit || gmem_size(mem) != static_cast<std::size_t>(M.ng))
		return false;
	const auto& m = mem[static_cast<std::size_t>(gi)];
	if (m.status == GS_CLEARED || m.status == GS_RESPAWN)
		return false; // open (bank), or shut until it respawns: normal play
	if (bankable())
		return false; // the altar is bankable another way: no siege
	if (now() + dom_commit_walk(gi) + 60 > GAME_END)
		return false;
	if (T.target == gi)
		return true;
	if (my_slot() == TM.sup || prism_layer::squad_skip() || sg_op_group() >= 0 || W.me.frac() < SG_HP || m.fail_until > now() ||
		!zc::allow_fast(gi, my_slot()))
		return false;
	bool mate = false;
	for (int s = 0; s < TM.n && s < 8; ++s)
		mate |= s != my_slot() && TM.claim[static_cast<std::size_t>(s)] == gi && siege_ally_alive(s);
	if (!mate && team_bag_total() < GT_GEMS)
		return false;
	if (!mate)
	{
		// The whole team (healer and Prism aside) must clear the gate within GT_TMAX rounds: no chipping by a trickle of bodies.
		Crew c;
		for (int i = 0; i < TM.n && i < 8; ++i)
		{
			const int s = TM.by_tank[static_cast<std::size_t>(i)];
			if (s < 0 || s >= 8 || s == TM.sup || !siege_ally_alive(s) || (prism_layer::squad_skip_slot(s)))
				continue;
			c.add(TM.m[static_cast<std::size_t>(s)]);
		}
		const auto& gg = M.groups[static_cast<std::size_t>(gi)];
		const float et = c.n >= GT_K ? estimate_cx(2, gg, m, c).t : 1e9f;
		const int tb = GT_TMAX_BOSS_TAB[1];
		const bool boss = gg.n_mono + gg.n_golem > 0;
		if (c.n < GT_K || et > static_cast<float>(boss ? std::max(tb, GT_TMAX) : GT_TMAX))
			return false;
		if (boss && et > static_cast<float>(GT_TMAX) && siege_enemies_near_group(gi, GT_TMAX_BOSS_TAB[2]) > 0)
			return false; // the long siege only at a quiet gate
	}
	set_target(gi, 1.0f, GT_K);
	return true;
}
} // namespace
} // namespace nova::econ
