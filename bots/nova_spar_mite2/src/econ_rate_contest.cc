// econ_rate_contest.cc: Rate of a group, part 2: contest, denial and hoard modifiers.
#include "econ_internal.h"
namespace nova::econ {
namespace {
// Rate (value per body-round) of body `self` working on group gi, with the crew it needs: the bodies already claiming it plus at
// most `max_extra` more (free bodies close enough to join). *crew_out: bodies assumed. opening_pack_factor: combat::group_pack_factor as a body on
// the spawn sees it at the opening (its team mates at the spawn, no claims yet): the same for every body, so every row of the
// opening simulation can use it.
float opening_pack_factor(int gi)
{
	if (gi < 0 || gi >= M.ng || !combat::fight_map())
		return 1.0f;
	if (cheb(M.groups[static_cast<std::size_t>(gi)].anchor, M.home_anchor) > 8)
		return 1.0f;
	return 1.0f + 0.25f * static_cast<float>(std::clamp(P.n - 1, 0, 2));
}
// Low-health steal: a heavy group (monolith, golem, or high-health such as elks) last seen at or below a set fraction of its health
// within a set number of rounds: we finish it, or catch the bodies it has worn down. Free camp: a middle or enemy-side group with no
// enemy seen near it in the last few rounds while our sightings in that time account for every living enemy.
float opportunity_factor(const GroupI& g, const GroupMem& m)
{
	float f = 1.0f;
	if (g.contest > 0.45f && opened)
	{
		const int alive = intel::enemies_alive();
		if (alive > 0 && intel::count_near(g.anchor, FREE_R, FREE_AGE) == 0 && intel::count_near(g.anchor, 1000, FREE_AGE) >= alive)
			f *= FREE_BONUS;
	}
	return f;
}
// every living foe is accounted for (seen within FREE_AGE) and none near the group (opportunity_factor's free-camp test), or none alive.
bool foes_accounted_for_and_far(const GroupI& g)
{
	const int alive = intel::enemies_alive();
	return alive <= 0 || (intel::count_near(g.anchor, FREE_R, FREE_AGE) == 0 && intel::count_near(g.anchor, 1000, FREE_AGE) >= alive);
}
// The capture term of the rate formulas (6 rounds for everyone by default) is 4 when slot `self` holds a Capture emblem (mine from
// my items; an ally's read through the SDK when in sight, else its last known items). Cached per slot and round: the rate loops call
// it per group.
float cap_term(int self)
{
	static int at[8] = { -1, -1, -1, -1, -1, -1, -1, -1 };
	static float val[8] = {};
	if (self < 0 || self >= 8 || self >= P.n)
		return 6.0f;
	const auto s = static_cast<std::size_t>(self);
	if (at[s] != now())
	{
		at[s] = now();
		const bool h = self == P.my_slot ? prism::has_family(rs::F_CAPTURE) : rs::has(rs::families(P.handle[s], now()), rs::F_CAPTURE);
		val[s] = static_cast<float>(rs::capture_pay(h));
	}
	return val[s];
}
// Rounds until an enemy capture of group g pays (6 by default): 4 when an enemy within 5 of its anchor holds a Capture emblem.
int enemy_cap_pay(const GroupI& g)
{
	bool h = false;
	for (const auto* lst : { &W.enemies, &W.enemies_far })
		for (const auto& e : *lst)
			if (!h && cheb(e.pos, g.anchor) <= 5 && rs::has(rs::families(e.h, now()), rs::F_CAPTURE))
				h = true;
	RSD(if (h) ++rsd::c[8];);
	return rs::capture_pay(h);
}
// An own-side heavy group a lone body may chip (static map data: an elk or a golem and no monolith, walkable, on our side, not an
// altar gate, not a lone boss of a siege map: those are sieged).
bool chip_candidate_group(const GroupI& g)
{
	return g.access == ACC_WALK && g.n_att > 0 && g.n_mono == 0 && g.n_elk + g.n_golem > 0 && g.d_home != UNREACH && g.contest * 100.0f <= static_cast<float>(CR_CONTEST_X100) && !is_gate(g.idx) && !(siege_map() && siege_group(g));
}
// No enemy champion known within CR_ENEMY_R of group gi's anchor in the last CR_QUIET rounds: the team's latest sighting of each
// living enemy (my sight, my ward, a teammate's report: its cell's centre) and my own memory of the group.
bool chip_group_is_quiet(int gi)
{
	const auto& g = M.groups[static_cast<std::size_t>(gi)];
	if (now() - mem[static_cast<std::size_t>(gi)].enemy_seen < CR_QUIET)
		return false;
	for (const auto& s : intel::team_table())
		if (s.alive && s.round > now() - CR_QUIET && cheb(s.pos, g.anchor) <= CR_ENEMY_R)
			return false;
	return true;
}
// a lower-slot ally I can see stands on g's region (not channelling): that body holds the pin, not me.
bool mate_pins_group(const GroupI& g)
{
	for (const auto& al : W.allies)
	{
		if (al.slot < 0 || al.slot >= my_slot() || al.channeling())
			continue;
		for (int ci : g.members)
			if (M.camps[static_cast<std::size_t>(ci)].pos == al.pos)
				return true;
	}
	return false;
}
// v7xx MBB7 bit 1 RWL1 (caller reads the flag): a mate that cannot walk to the respawn now (channelling or stunned, GR:118).
static __attribute__((noinline)) bool rwl1_not_free(const Body& a, int)
{
	return a.channeling() || a.stunned;
}
bool respawn_wait_lifted(int gi, int self, float wait)
{
	if (self != my_slot() || !opened || gi < 0 || gi >= M.ng || gi >= static_cast<int>(gmem_size(mem)) || wait > static_cast<float>(RC_WAIT))
		return false;
	const auto& g = M.groups[static_cast<std::size_t>(gi)];
	const auto& m = mem[static_cast<std::size_t>(gi)];
	const int left = m.respawn_at - now();
	if (m.status != GS_RESPAWN || left <= 0 || left > RC_SOON || g.access != ACC_WALK ||
		g.contest * 100.0f > static_cast<float>(RC_CONTEST_X100) || (g.gems == 0 && g.gold == 0) || dc_is(gi)) // the respawn rally's, not mine
		return false;
	// An enemy champion known near it lately (my memory of the group, else the team table).
	bool foe = now() - m.enemy_seen <= RC_AGE;
	if (!foe)
	{
		for (const auto& e : intel::team_table())
			if (e.alive && e.src >= 1 && e.src <= 3 && e.round >= now() - RC_AGE &&
				cheb(e.pos, g.anchor) <= RC_ENEMY_R)
			{
				foe = true;
				break;
			}
	}
	if (!foe)
		return false;
	if (gi == T.target)
		return true; // I hold it already
	if (claimants(gi, self, TM.claim) > 0)
		return false; // another body has it
	// The nearest free body: no visible unengaged ally (not the Willow healer) nearer to its anchor; ties to the lower slot.
	const int dme = cheb(W.me.pos, g.anchor);
	for (const auto& a : W.allies)
	{
		if (a.slot < 0 || a.slot >= TM.n || a.slot >= 8 || TM.busy[static_cast<std::size_t>(a.slot)])
			continue;
		if (rwl1_not_free(a, gi)) // v7xx MBB7 RWL1 (RC X475): a channelling or stunned mate is not free
			continue;
		const int da = cheb(a.pos, g.anchor);
		if (da < dme || (da == dme && a.slot < self))
			return false;
	}
	return true;
}
// The share of group g's remaining health crew c (me as its tank) takes off before my bail line, on estimate()'s clear model
// (attackers die lowest health first while the living ones hit; stuns, heals and shields soak). tank_turn bails when my health falls
// under the hits of the walk out of reach + 1.5 rounds + 8% of my max, and a lone body with no enemy near leaves at 30% (brain
// handle_low_hp); the hits drop as attackers die. The result is 1 when every attacker dies before that.
float chip_clear_share(const GroupI& g, const GroupMem& m, const Crew& c)
{
	if (g.att.empty())
		return 1.0f;
	const float scale = (m.status == GS_ALIVE && m.hp_left >= 0) ? clampf(m.hp_left / std::max(1.0f, g.hp), 0.02f, 1.0f) : 1.0f;
	float dps = c.dps(g.pack) * 0.85f;
	if (c.ret_tank > 0 || c.ret_hold > 0)
	{
		// passive Ren, as estimate()
		const int n_att = static_cast<int>(g.att.size());
		const int held = std::min(n_att - 1, std::max(0, c.n_melee - 1));
		dps += 0.6f * (c.ret_tank * static_cast<float>(n_att - held) + (n_att >= 2 ? c.ret_hold : 0.0f));
	}
	dps = std::max(10.0f, dps);
	const float cm = (mu::on(mu::B_CAMP) ? mu::my_camp(mu::IN) : mu::rule(mu::own_fam(own.jungle, false, false), mu::CAMP, mu::IN)); // the camps' hits on me (Jungle; Durability), as member_of
	const int stand = W.me.kit->ranged ? std::clamp(W.me.range, 1, std::max(1, g.reach_max)) : 1;
	const float esc = static_cast<float>(std::max(1, g.reach_max - stand + 1)) + 1.5f; // tank_turn: escape steps + 1.5
	float ko1_st8 = c.stuns8, ko1_x = 0;
	if (ko1_any(c)) // As estimate(): the same tests for bits 2 and 4.
		ko1_x = stun_soak_cancel(c, g, &ko1_st8);
	const float soak = std::min(1.0f, ko1_st8 / static_cast<float>(rs::slot_cooldown())) * g.str_max + ko1_x + (c.heal8 + c.shield8) / static_cast<float>(rs::slot_cooldown());
	// the living attackers at their own HP, as estimate() (the note from the hp_left observation).
	const std::pair<float, float>* att_b = g.att.data();
	const std::pair<float, float>* att_e = att_b + (g.att.size());
	const float att_scale = scale;
	float s = 0;
	for (const auto* ap = att_b; ap != att_e; ++ap)
		s += ap->second;
	float dmg = 0, gone = 0;
	for (const auto* ap = att_b; ap != att_e; ++ap)
	{
		const auto& a = *ap;
		const float line = std::max(0.30f * W.me.maxhp, s * cm * esc + 0.08f * W.me.maxhp);
		const float budget = std::max(0.0f, W.me.hp - line) / cm; // camp damage units, as Member::budget
		const float hp_a = a.first * att_scale;
		const float rate = std::max(0.0f, s - soak);
		const float dt = hp_a / dps;
		if (dmg + rate * dt > budget)
		{
			gone += rate > 0.0f ? std::max(0.0f, budget - dmg) / rate * dps : 0.0f;
			return clampf(gone / std::max(1.0f, g.hp * scale), 0.0f, 1.0f);
		}
		dmg += rate * dt;
		gone += hp_a;
		s -= a.second;
	}
	return 1.0f;
}
// Start a partial clear at group gi now (target_turn, with the crew here): nobody else claims it, it is quiet and the crew here
// takes CR_MIN_PCT % of its remaining health off before my bail line.
bool chip_start_partial_clear(int gi, const Crew& c)
{
	if (!opened)
		return false;
	if ((prism_layer::cr_rich() || static_cast<int>(W.me.gems) >= CR_BAG))
		return false; // a bag is not chipped with: a rich Prism or a body carrying many gems does not start a partial clear
	const auto& g = M.groups[static_cast<std::size_t>(gi)];
	const auto& m = mem[static_cast<std::size_t>(gi)];
	const bool ok = chip_candidate_group(g) && m.status != GS_CLEARED && m.status != GS_RESPAWN && claimants(gi) == 0 && !gem_need_crew_group(gi) &&
		chip_group_is_quiet(gi) && chip_clear_share(g, m, c) * 100.0f >= static_cast<float>(CR_MIN_PCT);
	if (ok)
		NLOG("r%d slot %d CHIP start %d hp_left %.0f of %.0f\n", now(), P.my_slot, gi, m.hp_left, g.hp);
	return ok;
}
// is rate_for's recruit branch open to my choice for group gi?
bool idle_recruit_open(int gi)
{
	const auto& g = M.groups[static_cast<std::size_t>(gi)];
	if (g.access != ACC_WALK || g.contest > 0.6f)
		return false;
	if (T.target >= 0)
		return gi == T.target && gi == ir_tgt; // the target an idle-recruit choice took keeps its rating
	const int run = now() - ir_start;
	if (ir_last < now() - 1 || run < IR_WAIT || (run - IR_WAIT) % IR_WAIT != 0 || fuel() < IR_FUEL_MIN)
		return false;
	if (ir_near_round != now())
	{
		// the IR_K nearest candidates, once per due round
		ir_near_round = now();
		ir_near.fill(-1);
		std::array<int, IR_K> nd{};
		nd.fill(BIG);
		for (std::size_t gj = 0; gj < static_cast<std::size_t>(M.ng) && gj < gmem_size(mem); ++gj)
		{
			const auto& h = M.groups[gj];
			if (h.access != ACC_WALK || h.contest > 0.6f || h.gems + h.gold == 0 || mem[gj].fail_until > now())
				continue;
			int d = cheb(h.anchor, W.me.pos);
			int k = static_cast<int>(gj);
			for (int i = 0; i < IR_K; ++i)
				if (d < nd[static_cast<std::size_t>(i)])
				{
					std::swap(d, nd[static_cast<std::size_t>(i)]);
					std::swap(k, ir_near[static_cast<std::size_t>(i)]);
				}
		}
	}
	for (const int k : ir_near)
		if (k == gi)
			return true;
	return false;
}
// PHM (common.h): the target-choice terms for a low-bag Prism (bit 1) and her mates (bit 2).
static bool phm_own_group(const GroupI& g) { return g.gems > 0 && g.n_att == 0 && g.contest < 0.5f && g.access == ACC_WALK; }
static bool own_free_group_exists()
{
	static int r = -1;
	static bool v = false;
	if (r == now())
		return v;
	r = now();
	v = false;
	for (int gi = 0; gi < M.ng && !v; ++gi)
	{
		const auto& m = mem[static_cast<std::size_t>(gi)];
		v = phm_own_group(M.groups[static_cast<std::size_t>(gi)]) && m.status != GS_RESPAWN && m.fail_until <= now();
	}
	return v;
}
static float prism_mate_factor(const GroupI& g, int gi)
{
	(void)gi;
	if (!W.me.kit || !opened)
		return 1.0f;
	if (prism_layer::phm())
	{
		if (static_cast<int>(W.me.gems) >= PHM_TAB[2])
			return 1.0f;
		if (phm_own_group(g))
			return static_cast<float>(PHM_TAB[3]) / 100.0f;
		return g.contest >= 0.5f && own_free_group_exists() ? static_cast<float>(PHM_TAB[4]) / 100.0f : 1.0f;
	}
	return 1.0f;
}
static float prism_mate_bound(const GroupI& g)
{
	return W.me.kit && prism_layer::phm() && opened && static_cast<int>(W.me.gems) < PHM_TAB[2] && phm_own_group(g) ? static_cast<float>(PHM_TAB[3]) / 100.0f : 1.0f;
}
// CTW (the contest factor steepened with walk) was stripped: returns x unchanged.
static float contest_walk_factor(float x, std::uint16_t trav, int self)
{
	return x;
}
} // namespace
} // namespace nova::econ
