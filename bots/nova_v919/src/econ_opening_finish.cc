// econ_opening_finish.cc: The opening: leaving it, spawn step and start recall.
#include "econ_internal.h"
namespace nova::econ {
namespace {
// true when this body has just committed to D. Call only with the bit set, before `opened`.
static bool commit_to_dom_opening()
{
	static bool done = false;
	if (done || dc_state != 0)
		return false;
	const int d = dom_commit_decide();
	if (d == 0)
		return false; // analysis not ready: ask again next turn
	done = true;
	if (d != 2)
		return false;
	build_team(true);
	opn_dc = true;
	const bool k = dom_commit_turn();
	opn_dc = false;
	if (!k || T.target != dc_v)
		return false;
	opened = true;
	return true;
}
template <int DM>
void choose_target_when_starved(const std::array<std::uint8_t, 8>& now_claims)
{
	if (pes_last == now()) // b2392 PSO bit 1 (RC X910): one starved search a round
		return;
	pes_n = pes_last == now() ? pes_n : (pes_last == now() - 1 ? pes_n + 1 : 1);
	pes_last = now();
	if (pes_n < PES_K || fuel() < PES_FUEL)
		return;
	pes_n = 0;
	build_team(false);
	if (travel_round != now() || travel_from != W.me.pos)
		compute_travel();
	std::array<int, PES_N> ng{};
	std::array<int, PES_N> nd{};
	ng.fill(-1);
	nd.fill(BIG);
	for (std::size_t gj = 0; gj < static_cast<std::size_t>(M.ng) && gj < travel.size() && gj < gmem_size(mem); ++gj)
	{
		const auto& h = M.groups[gj];
		if (h.access != ACC_WALK || travel[gj] == UNREACH || h.gems + h.gold == 0 || mem[gj].fail_until > now())
			continue;
		int d = static_cast<int>(travel[gj]);
		int k = static_cast<int>(gj);
		for (int i = 0; i < PES_N; ++i)
			if (d < nd[static_cast<std::size_t>(i)])
			{
				std::swap(d, nd[static_cast<std::size_t>(i)]);
				std::swap(k, ng[static_cast<std::size_t>(i)]);
			}
	}
	const Claims cl = claims_for_me();
	const int fn = free_near();
	float best_r = 0;
	int best = -1, best_c = 1;
	nova::econ::linear_score::begin();
	for (const int k : ng)
	{
		if (k < 0 || fuel() < PES_FLOOR)
			break;
		if (!reachable_target(k))
			continue;
		int cc = 1;
		const float rr = rate_for<DM>(k, my_slot(), travel[static_cast<std::size_t>(k)], cl, fn, &cc);
		if (rr > 0)
			nova::econ::linear_score::cand(k, cc, rr);
		if (rr > best_r)
		{
			best_r = rr;
			best = k;
			best_c = cc;
		}
	}
	nova::econ::linear_score::pick(-1, &best, &best_c, &best_r);
	if (best < 0)
		return;
	NLOG("r%d slot %d PEF_STARVE choice %d rate %.3f fuel %ld\n", now(), P.my_slot, best, best_r, fuel());
	eval_claims = now_claims;
	opened = true;
	set_target(best, best_r, best_c);
}
// drop a pending opening simulation for the ordinary choice.
static bool drop_pending_opening_sim()
{
	if (now() >= OPX_TAB[2])
		return true;
	for (const auto& e : W.enemies)
		if (cheb(e.pos, W.me.pos) <= 8)
			return true;
	return false;
}
} // namespace
bool start_prestep() { return start_prestep_i(); }
bool start_step() { return start_step_i(); }
bool om_blind_step() { return opening_blind_step_i(); }
void om_write(std::vector<std::uint8_t>& mem) { write_draft_opening_values(mem); }
// Bit 7 of the claim byte: fighting the claimed group right now.
bool claim_engaged() { return T.engaged && T.target >= 0; }
// on the spawn-heal turn, one step to a free spawn tile nearer my target (still heals).
// v7xx LDS bit 1 (caller reads the flag): spawn_step's candidates, every free own-spawn neighbour strictly lower in my target's group
// field, best (lowest) first; returns how many (<= 8).
int lds_spawn_steps(vec2* out)
{
	const int gi = T.target;
	if (gi < 0 || !W.can_move())
		return 0;
	const distance_field* f = mv::group_field_ready(gi);
	if (!f)
		return 0;
	const std::uint16_t cur = dfget_me(*f);
	if (cur == UNREACH)
		return 0;
	std::uint16_t dv[8];
	int n = 0;
	for (int dy = -1; dy <= 1; ++dy)
		for (int dx = -1; dx <= 1; ++dx)
		{
			const vec2 t{ W.me.pos.x + dx, W.me.pos.y + dy };
			if ((dx == 0 && dy == 0) || !mv::free_tile(t) || !bbget(M.my_spawn, t))
				continue;
			const std::uint16_t d = dfget(*f, t);
			if (d >= cur)
				continue;
			int k = n++;
			while (k > 0 && dv[k - 1] > d) // insertion by field value, stable (spawn_step's scan order on ties)
			{
				dv[k] = dv[k - 1];
				out[k] = out[k - 1];
				--k;
			}
			dv[k] = d;
			out[k] = t;
		}
	return n;
}
bool spawn_step()
{
	const int gi = T.target;
	if (gi < 0 || !W.can_move())
		return false;
	const distance_field* f = mv::group_field_ready(gi);
	if (!f)
		return false;
	const std::uint16_t cur = dfget_me(*f);
	if (cur == UNREACH)
		return false;
	vec2 best{ -1, -1 };
	std::uint16_t bd = cur;
	for (int dy = -1; dy <= 1; ++dy)
		for (int dx = -1; dx <= 1; ++dx)
		{
			const vec2 n{ W.me.pos.x + dx, W.me.pos.y + dy };
			if ((dx == 0 && dy == 0) || !mv::free_tile(n) || !bbget(M.my_spawn, n))
				continue;
			const std::uint16_t d = dfget(*f, n);
			if (d < bd)
			{
				bd = d;
				best = n;
			}
		}
	return best.x >= 0 && mv::try_move(best);
}
bool start_recall()
{
	fxr_poll(); // FXR bit 1 (not shipped, FXR_BITS 2): a no-op
	if (W.on_spawn)
		return false;
	if (altar_hold_pinned(true))
		return false; // the recall would leave a finishing foe bag's altar unheld
	const int rcg = recall_loop_guard();
	if (rcg == 0)
		return false;
	try
	{
		if (!pending_spin_becomes_recall()) // a running spin is my recall already
		{
			cambc::self().recall();
			if (VB2_ON(128)) // v7xx VB2 bit 128 BB7 row 432 (RC X324/C116): refresh after a fresh recall too (leave_respawn_tile rc 34)
			{
				VB2_CNT(128, true);
				refresh_self();
			}
		}
		else refresh_self();
		recall_loop_guard_record(rcg); // a kept spin counts: it is a real recall now
		on_recall();
		NLOG("r%d slot %d recall hp %.0f gold %u\n", W.round, P.my_slot, W.me.hp, W.gold);
		return true;
	}
	catch (const std::exception& e)
	{
		NLOG("r%d recall failed %s\n", W.round, e.what());
		return false;
	}
}
} // namespace nova::econ
