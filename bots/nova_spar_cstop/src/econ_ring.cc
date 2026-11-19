// econ_ring.cc: Ring altar maps.
#include "econ_internal.h"
namespace nova::econ {
namespace {
bitboard ring_bad; // attack tiles that landed no hit (the camp unseen from there)
std::unique_ptr<distance_field> f_breach; // walk field to the attack tile at any distance
int rbf_bc = -1, rbf_r = -1; // the breach camp and range of rbf_n
std::vector<int> rbf_n; // ring-group members reaching each candidate tile (-1: not counted yet)
// no group outside the ring groups is walkable from my spawn with camps blocked (static map data; once).
static int srb_seal = -1;
void ring_observe()
{
	if (!M.ring)
		return;
	for (int ci : M.ring_camps)
	{
		const vec2 p = M.camps[static_cast<std::size_t>(ci)].pos;
		if (!bbget(W.vis, p))
		{
			// a gap out of sight shuts when its group's known respawn comes (our capture, or one seen taken)
			const int g = M.camps[static_cast<std::size_t>(ci)].group;
			if (bbget(ring_open_bb, p) && g >= 0 && g < static_cast<int>(gmem_size(mem)) &&
				mem[static_cast<std::size_t>(g)].status == GS_RESPAWN && now() >= mem[static_cast<std::size_t>(g)].respawn_at)
			{
				bbset(ring_open_bb, p, false);
				ring_dirty = true;
			}
			continue;
		}
		const bool free = !bbget(W.occ_camps, p);
		if (free != bbget(ring_open_bb, p))
		{
			bbset(ring_open_bb, p, free);
			ring_dirty = true;
		}
	}
	if (ring_dirty && fuel() > 3L * G.w * G.h + 33000)
	{
		ring_dirty = false;
		has_ring_field = bbany(ring_open_bb);
		if (has_ring_field)
		{
			bitboard visited;
			f_ring.compute(M.block_camps & ~ring_open_bb, M.altar_adj, visited);
		}
		mv::set_known_open(ring_open_bb);
	}
	ring_gap = bbany(ring_open_bb) || now() - ring_signal < 60;
}
static bool ring_map_sealed()
{
	if (srb_seal >= 0)
		return srb_seal == 1;
	const distance_field* hcb = mv::home_field_cb();
	if (!hcb)
		return false;
	srb_seal = 1;
	for (int gi = 0; gi < M.ng && srb_seal == 1; ++gi)
		if (std::find(M.gate_groups.begin(), M.gate_groups.end(), gi) == M.gate_groups.end() &&
			M.group_dist_blocked(*hcb, M.groups[static_cast<std::size_t>(gi)]) != UNREACH)
			srb_seal = 0;
	return srb_seal == 1;
}
bool ring_breach()
{
	ring_breaching = false;
	if (!M.ring || bbany(ring_open_bb) || !W.alive || W.me.channeling() || T.capturing || !M.has_home)
		return false;
	if (T.target >= 0 && T.target == gate_group_target())
		return false; // Committed to the boss gate siege: no solo chip.
	// not off an engaged clear or a capture about to start; not from inside the enclosure (a dash or crystal put me there and no walk
	// leads out to an attack tile); not while paused after a stall.
	if (engaged_now() || about_to_capture() || dfget_me(M.f_altar) != UNREACH || now() < ring_pause_until)
		return false;
	if (now() < RING_START && W.me.gems < 30 && !(ring_map_sealed()))
		return false;
	if (ring_resting && W.me.frac() < 0.9f)
		return false;
	ring_resting = false;
	// leave on the damage, not on a flat share: what the awake camps in reach deal until I am out of every reach, plus a margin (the
	// melee tile can be in reach of 15 wolves, 300 a round, 3 steps from safety).
	const float inc = mv::camp_threat(W.me.pos);
	const int out_steps = inc > 0 ? mv::escape_steps(mv::camp_threats_near(7), W.me.pos) : 0;
	if (W.me.frac() < RING_LEAVE || (inc > 0 && W.me.hp < inc * static_cast<float>(out_steps + 1) + 0.1f * W.me.maxhp))
	{
		ring_resting = true;
		return false;
	}
	const Kit& mk = *W.me.kit;
	if (!mk.ranged)
		for (int s = 0; s < P.n; ++s)
			if (s != my_slot() && s != support::healer_slot() && kit_of(P.type[static_cast<std::size_t>(s)]).ranged &&
				W.ally_by_slot(s))
				return false; // a living ranged team mate breaches (not the healer: support::turn keeps her off this hook)
	int bc = -1;
	std::uint16_t bd = UNREACH;
	for (int ci : M.ring_camps)
	{
		const std::uint16_t d = dfget(M.f_home, M.camps[static_cast<std::size_t>(ci)].pos);
		if (d < bd)
		{
			bd = d;
			bc = ci;
		}
	}
	if (bc < 0)
		return false;
	const auto& bcp = M.camps[static_cast<std::size_t>(bc)];
	if ((bcp.type == cambc::camp_type::monolith || bcp.type == cambc::camp_type::golem) &&
		W.me.hp < (bcp.str * mu::my_camp(mu::IN)) * static_cast<float>(std::max(1, bcp.reach - std::max(1, W.me.range) + 2)) + 0.1f * W.me.maxhp)
		return false;
	const int gi = M.camps[static_cast<std::size_t>(bc)].group;
	for (int s = 0; s < std::min(P.n, comms::CLAIM_SLOTS) && s < my_slot(); ++s)
		if (s != support::support_slot() && comms::cgroup(s) == gi) // not the following healer
			return false; // a lower slot breaches (the claim bytes: TM is rebuilt only on farm turns, never while breaching)
	for (const auto& e : W.enemies)
		if (cheb(e.pos, W.me.pos) <= 8 || cheb(e.pos, M.camps[static_cast<std::size_t>(bc)].pos) <= 8)
			return false; // never with enemy champions about
	// The attack tile: outside the enclosure, within my range of the breach camp, reached by the fewest ring camps; then
	// the farthest from the camp, then the nearest to me.
	const vec2 c = M.camps[static_cast<std::size_t>(bc)].pos;
	const auto& mem_g = M.groups[static_cast<std::size_t>(gi)].members;
	const BView vblock = bview(mv::blocked());
	const distance_field* hcb = mv::home_field_cb(); // camps blocked (f_home lets camps pass)
	const distance_field& fh = hcb ? *hcb : M.f_home;
	vec2 best{ -1, -1 };
	int best_s = BIG;
	const int r = std::max(1, W.me.range);
	if ((rbf_bc != bc || rbf_r != r))
	{
		// a new breach camp or range: forget the member counts
		rbf_bc = bc;
		rbf_r = r;
		rbf_n.assign(static_cast<std::size_t>((2 * r + 1) * (2 * r + 1)), -1);
	}
	for (int dy = -r; dy <= r; ++dy)
		for (int dx = -r; dx <= r; ++dx)
		{
			const vec2 t{ c.x + dx, c.y + dy };
			if (!inb(t) || bbget(M.block, t) || bbget(M.camp_tiles, t) || dfget(M.f_altar, t) != UNREACH ||
				dfget(fh, t) == UNREACH || bbget(ring_bad, t) || (t != W.me.pos && vblock(t)))
				continue;
			const auto rk = static_cast<std::size_t>((dy + r) * (2 * r + 1) + (dx + r));
			int n = rbf_n[rk]; // the members reaching t, counted once per (breach camp, range)
			if (n < 0)
			{
				n = 0;
				for (int ci : mem_g)
				{
					const auto& cp = M.camps[static_cast<std::size_t>(ci)];
					n += cheb(cp.pos, t) <= cp.reach ? 1 : 0;
				}
				rbf_n[rk] = n;
			}
			const int sc = n * 10000 + (r - cheb(t, c)) * 100 + std::min(99, cheb(t, W.me.pos));
			if (sc < best_s)
			{
				best_s = sc;
				best = t;
			}
		}
	if (best.x < 0)
		return false;
	// stall guard: no step closer to the tile and no hit for 30 breach turns pauses me for 100 rounds.
	if (now() - ring_last > 1 || best != ring_prog_tile)
	{
		ring_prog_d = BIG;
		ring_prog_tile = best;
	}
	ring_last = now();
	if (cheb(W.me.pos, best) < ring_prog_d)
	{
		ring_prog_d = cheb(W.me.pos, best);
		ring_prog_round = now();
	}
	else if (now() - ring_prog_round > 30)
	{
		ring_pause_until = now() + 100;
		return false;
	}
	ring_breaching = true;
	ring_claim = gi;
	if (W.me.pos != best && W.can_move())
	{
		bitboard goal;
		bbset(goal, best);
		if (!mv::step_to_set(goal, 40))
		{
			// Beyond step_to_set's radius (40; 20 below 65k fuel, 10 below 45k) walk a field to the tile (built once per tile), else a greedy
			// step; walking home and parking there would never reach it.
			if (!(f_breach && f_breach_at == best) && fuel() > 3L * G.w * G.h + 40000)
			{
				auto f = std::make_unique<distance_field>();
				bitboard visited, root;
				bbset(root, best);
				f->compute(M.block_camps & ~root, root, visited);
				f_breach = std::move(f);
				f_breach_at = best;
			}
			if (!(f_breach && f_breach_at == best && dfget_me(*f_breach) != UNREACH && mv::step_field(*f_breach)))
				mv::step_greedy(best);
		}
	}
	if (cheb(W.me.pos, c) <= W.me.range)
	{
		combat::camp_abilities(bc, true); // shield, stun, damage spells on the breach camp, not only hits
		if (W.can_attack() || W.moved)
		{
			const bool could = W.can_attack(); // a body that walked and cannot attack is not "out of sight"
			if (combat::hit_camp(bc)) // with the attack reset
			{
				ring_idle = 0;
				ring_prog_round = now();
			}
			else if (could && W.me.pos == best && ++ring_idle >= 3)
			{
				bbset(ring_bad, best); // no hit from here: the camp is out of my sight (wall corner, bush)
				ring_idle = 0;
			}
		}
	}
	return true;
}
bool ring_wait()
{
	if (!M.ring || dfget_me(M.f_altar) != UNREACH)
		return false;
	// per awake attacking ring camp, by its own reach (elk/golem 4, monolith 5): > 0 = I am in its reach, 0 = one step outside it.
	// Waiting at 4 from any camp would stand in an elk's reach, so the camp would never sleep.
	int worst = -BIG;
	for (int gi : M.gate_groups)
		for (int ci : M.groups[static_cast<std::size_t>(gi)].members)
		{
			const auto& cp = M.camps[static_cast<std::size_t>(ci)];
			if (!cp.attacks() || !bbget(W.awake, cp.pos))
				continue; // a gold or gem cluster never hits; a sleeping camp lets us pass
			worst = std::max(worst, cp.reach + 1 - cheb(cp.pos, W.me.pos));
		}
	if (worst < 0)
		return false;
	if (now() - ring_wait_last > 1)
		ring_wait_since = now();
	ring_wait_last = now();
	if (now() - ring_wait_since > 30)
		ring_bank_off = now() + 40; // someone keeps the ring awake: farm for 40 rounds (want_bank), then retry
	if (worst > 0 && W.can_move())
	{
		const auto z = mv::camp_threats_near(7);
		if (z.empty() || !mv::escape(z))
			mv::step_field(M.f_home);
	}
	return true;
}
bool is_gate(int gi) { return std::find(M.gate_groups.begin(), M.gate_groups.end(), gi) != M.gate_groups.end(); }
// A one-camp ring gate is our way in: a capture starts its respawn and shuts the gap. Bigger ring groups stay targets (excluding
// gold-cluster rings would cut our gold sharply).
bool ring_gate_keep(int gi)
{
	return M.ring && gi >= 0 && M.groups[static_cast<std::size_t>(gi)].members.size() <= 1 && is_gate(gi);
}
} // namespace
bool ring_breach_turn() { return ring_breach(); }
} // namespace nova::econ
