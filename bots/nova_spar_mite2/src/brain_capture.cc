// brain_capture.cc: Capture holds and contests.
#include "brain_internal.h"
namespace nova {
// v716 ACX: the map's class bits (1 CLUSTER, 2 GOLDFREE) from map_class() (draft-written, MCL 64 / 128), and the largest walkable gem
// group (static map data). Callers read the flag first.
int acx_classes()
{
	if (acx_map.bits >= 0)
		return acx_map.bits;
	if (M.ng <= 0)
		return 0;
	int big = 0;
	for (const auto& g : M.groups)
		if (g.access == ACC_WALK)
			big = std::max(big, static_cast<int>(g.gems));
	const int mc = map_class();
	acx_map.bits = ((mc & MCL_BIT_CLUSTER) ? 1 : 0) | ((mc & MCL_BIT_GOLDFREE) ? 2 : 0);
	acx_map.big = big;
	return acx_map.bits;
}
// v716 ACX bit 1 ACC: a cluster-class group worth contesting (half the largest walkable gem group, at least 21 gems).
static __attribute__((noinline)) bool acx_cc_gate(int gems)
{
	return (acx_classes() & 1) && gems >= std::max(21, acx_map.big / 2);
}
namespace {
// Rule A: the foes within 8 of the place (visible, or just out of sight) are no more than our bodies there (allies counted by
// distance, not by commitment), their health no more than ours, and mine at least half. `dist` measures from the place.
template <class D>
bool region_outnumber_check(const combat::Assessment& a, D dist)
{
	if (W.me.frac() < 0.5f)
		return false;
	int enemies_at_zone = 0, n_us = 1;
	float hp_them = 0, hp_us = mu::mult_my_health_eff_hp(32); // My health in the unit of f.ehp and the mates' mu::ehp.
	for (const auto& f : a.foes)
		if (dist(f.pos) <= 8)
		{
			++enemies_at_zone;
			hp_them += f.ehp;
		}
	for (const auto& al : W.allies)
		if (al.hp > 0 && !al.channeling() && dist(al.pos) <= 8)
		{
			++n_us;
			hp_us += mu::ehp(al);
		}
	return enemies_at_zone <= n_us && hp_them <= hp_us;
}

// The health a capture keeps in hand: rule A's bar, hold_capture's and the contest's.
NOVA_INLINE float keep_bar() { return std::max(brain_tune::KEEP_SHARE * W.me.maxhp, brain_tune::KEEP_MIN); }

// damage the foes (and the camps) can deal me here in the next k rounds (hold_capture's estimate).
float damage_in(const combat::Assessment& a, int k, float camp_per_round)
{
	const vec2 me = W.me.pos;
	float dmg = camp_per_round * static_cast<float>(k);
	for (const auto& f : a.foes)
	{
		if (f.reach < 0)
			continue;
		const int t = std::max(0, cheb(f.pos, me) - f.reach);
		if (t < k)
			dmg += mu::mult_foe_hit_to_real_hp(f.burst + f.dps * static_cast<float>(k - 1 - t));
	}
	return dmg;
}
// A FLEE turn next to my target group that pays soon (<= 25% health or dead in <= 3 rounds) keeps clearing it under rule A at the
// group when the hits until it dies plus the capture's first round leave a quarter of my health (150 at least). True if the turn was
// used.
bool finish_first(const combat::Assessment& a)
{
	vec2 at{};
	float camp_in = 0;
	const int r = econ::finish_rounds(&at, &camp_in);
	if (r < 0)
		return false;
	if (!region_outnumber_check(a, [&](vec2 p) { return cheb(p, at); }))
		return false;
	const float dmg = damage_in(a, r + 1, camp_in);
	const float ehp = W.me.hp + W.me.shield;
	return dmg <= ehp - keep_bar() && econ::farm(); // DOM mode keeps its farm.
}
// Step onto (or hold) the region of a cleared rich group an enemy is capturing.
bool contest_capture_turn_slow(const combat::Assessment& a);
// Inlined: the first early-out test sits at the call site, the rest is out of line.
__attribute__((always_inline)) bool contest_capture_turn(const combat::Assessment& a)
{
	if (!W.alive || W.me.channeling() || W.enemies.empty() || !M.groups_ready())
		return false;
	if (W.tributed_them >= CCE_T0 && nova::econ::capture_end::end_turn(a, keep_bar())) // Contest a game-ending capture.
		return true;
	if (W.me.frac() < 0.5f || a.n_foes > a.n_friends)
		return false;
	return contest_capture_turn_slow(a);
}
__attribute__((noinline)) bool contest_capture_turn_slow(const combat::Assessment& a)
{
	int gi = -1;
	for (const auto& e : W.enemies)
	{
		if (cheb(e.pos, W.me.pos) > CC_D + 2)
			continue;
		const int ci = M.camp_index(e.pos);
		if (ci < 0 || ci >= M.nc)
			continue;
		const int g = M.camps[static_cast<std::size_t>(ci)].group;
		if (g >= 0 && g < M.ng && (M.groups[static_cast<std::size_t>(g)].gems >= CC_GEMS || (nova::econ::capture_end::low_ok(M.groups[static_cast<std::size_t>(g)].gems)) || (acx_cc_gate(static_cast<int>(M.groups[static_cast<std::size_t>(g)].gems))))) // Contest a group with at least CC_GEMS gems, or one that low_ok allows.
		{
			std::uint32_t st1 = 0;
			if (cambc::detail::sdk_camp_group_state(M.groups[static_cast<std::size_t>(g)].handle, &st1) != 0 || st1 != 2)
				continue;
			gi = g;
			break;
		}
	}
	if (gi < 0)
		return false;
	const auto& g = M.groups[static_cast<std::size_t>(gi)];
	std::uint32_t st = 0;
	if (cambc::detail::sdk_camp_group_state(g.handle, &st) != 0 || st != 2)
		return false;
	bool on = false, any = false;
	bitboard goals;
	for (int ci : g.members)
	{
		const vec2 p = M.camps[static_cast<std::size_t>(ci)].pos;
		if (p == W.me.pos)
			on = true;
		else if (cheb(p, W.me.pos) <= CC_D && mv::free_tile(p) && mv::camp_threat(p) <= 0.0f)
		{
			bbset(goals, p);
			any = true;
		}
	}
	if (!on && (!any || !W.can_move()))
		return false;
	float dmg = 0;
	for (const auto& f : a.foes)
		if (f.reach >= 0 && cheb(f.pos, W.me.pos) <= f.reach + 2)
			dmg += (f.burst + (f.dps));
	if (mu::mult_foe_hit_to_real_hp(dmg) > W.me.hp + W.me.shield - keep_bar()) // dmg is foe hits only.
		return false;
	if (!on && !mv::step_to_set(goals, 8, gi))
		return false;
	for (const auto& e : W.enemies)
		if (cheb(e.pos, W.me.pos) <= W.me.range && combat::attack_champion(e))
			break;
	return true;
}

// A capture pays at the 6th round start after stepping on and damage does not stop it, so hold the region while (1) nothing can kill
// me (or leave me too weak to get away) before the payout, and (2) no enemy can step onto the region before it, unless we have the
// numbers to contest it. True if the turn was used. A visible foe in a recall channel that cannot hit me now leaves before my
// capture pays.
bool foe_leaves_before_payout(const combat::Foe& f, int d)
{
	if (f.idx < 0 || f.idx >= static_cast<int>(W.enemies.size()))
		return false;
	const std::uint32_t st = W.enemies[static_cast<std::size_t>(f.idx)].state;
	return (st & ST_RECALL) && !(st & (ST_TRIBUTE | ST_TELEPORT)) && (f.reach < 0 || d > f.reach);
}
// I keep a running capture although the k-round worst case failed, when no foe reaches me next turn, none can stand on the region
// next round, two rounds of damage leave the keep bar, and no lower-slot mate out of every foe's reach stands on the region (that
// mate keeps it).
bool keep_running_capture(const combat::Assessment& a, int arrive, float ehp, float keep)
{
	if (a.in_reach || arrive < 1)
		return false;
	if (damage_in(a, 2, mv::camp_threat(W.me.pos)) > ehp - keep)
		return false;
	const int ci = M.camp_index(W.me.pos);
	if (ci < 0 || ci >= M.nc)
		return false;
	const int gi = M.camps[static_cast<std::size_t>(ci)].group;
	for (const auto& al : W.allies)
	{
		if (al.slot < 0 || al.slot >= P.my_slot)
			continue;
		const int cj = M.camp_index(al.pos);
		if (cj < 0 || cj >= M.nc || M.camps[static_cast<std::size_t>(cj)].group != gi)
			continue;
		bool reached = false;
		for (const auto& f : a.foes)
			reached |= f.reach >= 0 && cheb(f.pos, al.pos) <= f.reach;
		if (!reached)
			return false;
	}
	return true;
}

// Did visible foe idx take its turn before mine this round? Turns interleave by team (rank j of the starting team, then rank j of
// the other); a rank counts the visible bodies of that team ahead in current priority, then draft order (allies by slot, foes by
// handle). Bodies out of sight (and dead ones, which still take a turn) are not counted. Priorities are read once a round.
static int turn_order_rank_of(std::uint32_t h)
{
	std::int32_t v = 0;
	cambc::detail::sdk_bc_champion_priority(h, 0, &v);
	return v;
}
bool foe_acted_before_me(int idx)
{
	if (idx < 0 || idx >= static_cast<int>(W.enemies.size()) || idx >= 12)
		return false;
	static int rnd = -1000, ra = 0;
	static std::array<int, 12> pb{};
	if (rnd != W.round)
	{
		rnd = W.round;
		const int pa = PRA_DEC(turn_order_rank_of(W.me.h)); // Our values decode.
		ra = 0;
		for (const auto& al : W.allies)
		{
			const int p = PRA_DEC(turn_order_rank_of(al.h));
			ra += (p > pa || (p == pa && al.slot >= 0 && al.slot < P.my_slot)) ? 1 : 0;
		}
		for (std::size_t x = 0; x < W.enemies.size() && x < pb.size(); ++x)
			pb[x] = turn_order_rank_of(W.enemies[x].h);
	}
	const auto ux = static_cast<std::size_t>(idx);
	int rb = 0;
	for (std::size_t y = 0; y < W.enemies.size() && y < pb.size(); ++y)
		rb += (pb[y] > pb[ux] || (pb[y] == pb[ux] && W.enemies[y].h < W.enemies[ux].h)) ? 1 : 0;
	return enemy_starts(W.round) ? rb <= ra : rb < ra;
}
// Rounds until the payout from the engine's own countdown. ally_capturing carries the remaining timer, and the capture phase pays at
// the start of round now + timer. capture_pay_in reads one more when I killed the last camp standing on the region, because its
// region clock starts at my first turn that sees the group cleared. Only ever lowers k.
int engine_payout_rounds(int k)
{
	const int ci = M.camp_index(W.me.pos);
	if (ci < 0 || ci >= M.nc)
		return k;
	const int gi = M.camps[static_cast<std::size_t>(ci)].group;
	if (gi < 0 || gi >= M.ng)
		return k;
	cambc::detail::camp_group_capture_state cs{};
	if (cambc::detail::sdk_camp_group_capture_state(M.groups[static_cast<std::size_t>(gi)].handle, &cs) != 0)
		return k;
	return (cs.state == 1 && cs.timer >= 1 && cs.timer < k) ? static_cast<int>(cs.timer) : k; // camp_group_capture_type::ally_capturing
}
bool hold_capture_slow(const combat::Assessment& a, int k);
// Inlined: the capture_pay_in test sits at the call site, the rest is out of line.
__attribute__((always_inline)) bool hold_capture(const combat::Assessment& a)
{
	const int k = econ::capture_pay_in();
	if (k < 1 || k > 6)
		return false;
	return hold_capture_slow(a, k);
}
__attribute__((noinline)) bool hold_capture_slow(const combat::Assessment& a, int k)
{
	k = engine_payout_rounds(k);
	if (a.stance == combat::CALM && a.foes.empty())
		return false; // the normal capture turn holds (and may time its recall to the payout)
	const vec2 me = W.me.pos;
	float dmg = mv::camp_threat(me) * static_cast<float>(k - 1); // Camp damage over the k - 1 rounds before the payout.
	int arrive = BIG;
	for (const auto& f : a.foes)
	{
		const int d = cheb(f.pos, me);
		if (foe_leaves_before_payout(f, d))
			continue; // A foe in a recall channel that cannot hit me now leaves before the payout.
		if (f.reach >= 0)
		{
			const int t = std::max(0, d - f.reach); // rounds before it can hit me
			const int n = (foe_acted_before_me(f.idx)) ? k - 1 : k; // Count only the foe's turns before the payout.
			if (t < n)
				dmg += mu::mult_foe_hit_to_real_hp(f.burst + f.dps * static_cast<float>(n - 1 - t));
		}
		// Rounds before it can stand on the region (one step per round; a dasher a few more).
		const int dr = econ::capture_region_dist(f.pos);
		arrive = std::min(arrive, std::max(0, dr - (f.reach >= 4 ? 3 : 1)));
	}
	const float ehp = W.me.hp + W.me.shield;
	const float keep = keep_bar();
	const bool safe = dmg <= ehp - keep;
	// Rule A at the region also holds.
	bool clean = arrive >= k || a.ratio_near >= 1.0f;
	if (!clean && safe && region_outnumber_check(a, [](vec2 p) { return econ::capture_region_dist(p); }))
	{
		clean = true;
	}
	NLOG("r%d slot %d HOLD? k %d dmg %.0f ehp %.0f arrive %d ratio %.2f/%.2f stance %d -> %d\n", W.round, P.my_slot, k, dmg, ehp,
		arrive, a.ratio, a.ratio_near, static_cast<int>(a.stance), (int)(safe && clean));
	// A safe capture in progress is kept while no foe can hit me next turn; a foe that comes into reach (or onto the region) ends it.
	// This stops a loop of stepping off and on when a foe is 5-8 tiles away.
	bool cap_keep = !clean && safe && !a.in_reach;
	if (cap_keep)
		clean = true;
	if ((!safe || !clean) && !(keep_running_capture(a, arrive, ehp, keep)))
		return false;
	const Kit& kit = *W.me.kit;
	if (a.in_reach && kit.slot_shield >= 0 && combat::ready(kit.slot_shield) && W.me.shield <= 0 HSL_OK(false))
		combat::cast_self(kit.slot_shield);
	combat::cast_damage_spell_on_foe();
	return econ::hold_region();
}

// Gold only helps once spent: go home and shop when the next emblem is affordable and nothing can interrupt the
// recall (walk when home is close).
} // namespace
} // namespace nova
