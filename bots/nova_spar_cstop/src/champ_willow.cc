// champ_willow.cc: WILLOW LAYER, Willow's rules (hooks: champ_willow.h; flags: champ_willow.h). The team's healer: her partner pick
// (compute), escort and positioning, her heal choice (heal, heal_any), WILLOW_FARM (the bruiser mode), WILLOW_REGEN's healer side
// (ready_healer_near, wr_hurt_mate) and the capture penalty her partner pays (cap_penalty). The base asks her hooks at its sites; the
// WILLOW_REGEN rules her hurt mates run (hold_near_willow, flee_recall_skip_for_willow, willow_recall_cancel_ok) stay in brain_*.cc.
#include "champ_willow.h"
#include "multipliers.h"

#include "combat.h"
#include "comms.h"
#include "mapinfo.h"
#include "move.h"
namespace nova::combat {  }
#include "plan.h"
#include "champions.h"

namespace nova::support {

namespace {

int healer = -2;            // cached healer slot (-2: not computed yet)
std::array<int, 8> order{}; // partner order (ally slots), healer excluded
int n_order = 0;
// Fuel use: recursive (no static bound). Measured max 216, mean 15 per call, 8,752.3 calls per game, 132,015 per game including
// callees. The once-only body is out of line and the cached test is inline (about 10k calls a game would each pay a stack frame).
__attribute__((noinline)) void compute_slow();
NOVA_INLINE void compute()
{
	if (healer != -2 || P.n <= 0)
		return;
	compute_slow();
}
void compute_slow()
{
	healer = -1;
	for (int i = 0; i < P.n; ++i)
		if (willow_layer::kit(kit_of(P.type[static_cast<std::size_t>(i)])))
		{
			healer = i;
			break;
		}
	n_order = 0;
	if (healer < 0)
		return;
	// Partner by role and kit: Heart of Ruin (tanks, dives, hits harder while hurt: her heal keeps it in the fight),
	// then Prism (the gem carry), then the best camp tanks, melee first.
	std::array<float, 8> score{};
	for (int i = 0; i < P.n && n_order < 8; ++i)
	{
		if (i == healer)
			continue;
		const auto si = static_cast<std::size_t>(i);
		const Kit& k = kit_of(P.type[si]);
		float s = 100.0f - 5.0f * static_cast<float>(P.tank_order[si]);
		if (!k.ranged)
			s += 20.0f;
		if (heart_layer::kit(k))
			s += 400.0f;
		else if (prism_layer::kit(k))
			s += 300.0f;
		score[si] = s;
		order[static_cast<std::size_t>(n_order++)] = i;
	}
	std::stable_sort(order.begin(), order.begin() + n_order,
		[&](int a, int b) { return score[static_cast<std::size_t>(a)] > score[static_cast<std::size_t>(b)]; });
}

// Visible body of an ally slot (allies out of my vision are not visible: vision is per champion).
const Body* visible_ally_body_of_slot(int s)
{
	if (s < 0)
		return nullptr;
	if (s == P.my_slot)
		return W.alive ? &W.me : nullptr;
	return W.ally_by_slot(s);
}

// Liveness of an ally slot (known out of vision too), cached per turn.
std::array<std::int8_t, 8> alive_c{};
int alive_round = -1;
bool alive_slot(int s)
{
	if (s < 0 || s >= P.n || s >= 8)
		return false;
	if (s == P.my_slot)
		return W.alive;
	if (alive_round != W.round)
	{
		alive_round = W.round;
		alive_c.fill(-1);
	}
	auto& c = alive_c[static_cast<std::size_t>(s)];
	if (c < 0)
	{
		if (W.ally_by_slot(s))
			c = 1;
		else
		{
			std::int32_t a = 0;
			c = (cambc::detail::sdk_champion_is_alive(P.handle[static_cast<std::size_t>(s)], &a) == 0 && a != 0) ? 1 : 0;
		}
	}
	return c == 1;
}

// Where each ally was last seen by me.
std::array<vec2, 8> seen_pos{};
std::array<int, 8> seen_round{};
void note_seen()
{
	for (const auto& al : W.allies)
		if (al.slot >= 0 && al.slot < 8)
		{
			seen_pos[static_cast<std::size_t>(al.slot)] = al.pos;
			seen_round[static_cast<std::size_t>(al.slot)] = W.round;
		}
}


// The ally I escort this turn: my partner when I see it, else (out of sight) the nearest visible ally while the
// partner has no target to walk to. nullptr: walk to the partner's target or its last known place.
const Body* escort(int ps, int gi)
{
	if (const Body* p = visible_ally_body_of_slot(ps))
		return p;
	if (gi >= 0)
		return nullptr;
	const Body* best = nullptr;
	int bd = 9;
	for (const auto& al : W.allies)
	{
		const int d = cheb(al.pos, W.me.pos);
		if (!al.channeling() && d < bd)
		{
			bd = d;
			best = &al;
		}
	}
	return best;
}

// Damage an ally takes at the next round start and from the visible enemies that reach it.
float incoming_on(const Body& al)
{
	float d = 0;
	const float wck = 1.0f; // what lands on the mate
	for (const auto& vc : W.camps)
	{
		if (!vc.awake)
			continue;
		const auto& c = M.camps[static_cast<std::size_t>(vc.ci)];
		if (!c.attacks())
			continue;
		const int da = cheb(al.pos, c.pos);
		if (da > c.reach)
			continue;
		bool other = cheb(W.me.pos, c.pos) < da;
		for (const auto& b : W.allies)
			if (b.h != al.h && cheb(b.pos, c.pos) < da)
				other = true;
		for (const auto& e : W.enemies)
			if (cheb(e.pos, c.pos) < da)
				other = true;
		if (!other)
			d += c.str * wck;
	}
	for (const auto& e : W.enemies)
	{
		const int reach = std::max(e.range <= 1 ? 2 : e.range + 1, combat::foe_next_turn_reach(e)); // the foe's next-turn reach (foe_next_turn_reach, which includes area spells) widens the reach
		if (cheb(e.pos, al.pos) <= reach)
			d += 1.5f * combat::body_dps(e);
	}
	return d;
}

// The partner's target group as I see it this turn, built once per turn (a group can hold dozens of camps, and a
// per-tile scan of members x visible camps cost tens of thousands of fuel).
struct Member
{
	int ci;
	vec2 pos;
	float hp, str;
	int reach;
	bool awake;
};
struct GroupView
{
	int gi = -1;
	bool hittable = false;     // no attackers, or awake already (someone holds it): its camps may be hit
	std::vector<Member> live;  // visible living members
	std::vector<vec2> tiles;   // every member tile (the capture region)
};
GroupView gv;
int gv_round = -1;
// Fuel use: formula over 21 loops. Not called in the measured games.
const GroupView& group_view(int gi)
{
	if (gv_round == W.round && gv.gi == gi)
		return gv;
	gv_round = W.round;
	gv.gi = gi;
	gv.hittable = false;
	gv.live.clear();
	gv.tiles.clear();
	if (gi < 0 || gi >= M.ng)
		return gv;
	const auto& g = M.groups[static_cast<std::size_t>(gi)];
	bool awake = false;
	for (const auto& vc : W.camps)
	{
		const auto& c = M.camps[static_cast<std::size_t>(vc.ci)];
		if (c.group != gi)
			continue;
		gv.live.push_back({ vc.ci, c.pos, vc.hp, c.str, c.reach, vc.awake });
		awake |= vc.awake;
	}
	for (int ci : g.members)
		gv.tiles.push_back(M.camps[static_cast<std::size_t>(ci)].pos);
	gv.hittable = g.n_att == 0 || awake;
	return gv;
}

// Camp damage I would draw on tile t: awake camps that would pick me, and the asleep attackers of the partner's
// target that I stand nearer to than the partner (they wake when it attacks).
float camp_hazard(vec2 t, const Body& p, const GroupView& g)
{
	float h = mv::camp_threat(t);
	const float wck = 1.0f; // camp_threat's unit
	for (const auto& m : g.live)
	{
		if (m.str <= 0 || m.awake)
			continue;
		const int d = cheb(t, m.pos);
		if (d <= m.reach && d < cheb(p.pos, m.pos))
			h += 0.5f * m.str * wck;
	}
	return h;
}

bool enemy_in_range_from(vec2 t, int focus)
{
	if (focus >= 0 && cheb(W.enemies[static_cast<std::size_t>(focus)].pos, t) <= W.me.range)
		return true;
	for (const auto& e : W.enemies)
		if (cheb(e.pos, t) <= W.me.range && !(bbget(M.enemy_spawn, e.pos)))
			return true;
	return false;
}

bool camp_in_range_from(vec2 t, const GroupView& g)
{
	if (!g.hittable)
		return false;
	for (const auto& m : g.live)
		if (cheb(m.pos, t) <= W.me.range)
			return true;
	return false;
}

// my partner is the gem carrier (Prism); gate mode 2: my lineup holds Prism and no Heart of Ruin (static).
bool willow_farm_lineup_gate()
{
	bool gem = false, hor = false;
	for (int i = 0; i < P.n && i < 8; ++i)
	{
		const Kit& k = kit_of(P.type[static_cast<std::size_t>(i)]);
		gem |= prism_layer::kit(k);
		hor |= heart_layer::kit(k);
	}
	return gem && !hor;
}
bool willow_farm_gated()
{
	const int ps = partner_slot();
	return willow_farm_lineup_gate() || (ps >= 0 && ps < P.n && prism_layer::kit(kit_of(P.type[static_cast<std::size_t>(ps)])));
}
// Fuel use: recursive (no static bound). Not called in the measured games. One step (or none) to the best backline tile next to
// partner p: within heal range of it, out of enemy melee reach and of more enemy reaches than it, never the nearest champion to a
// camp, behind it relative to the enemies (else to its target group), and within attack range of a target when there is one.
void position(const combat::Assessment& a, const Body& p, int gi, bool fight, int focus)
{
	if (!W.can_move())
		return;
	const vec2 me = W.me.pos;
	const Kit& k = *W.me.kit;
	const int hr = std::max(2, static_cast<int>(k.heal_range));
	const int dp = cheb(me, p.pos);
	// In heal range across a wall is not beside the partner (Willow could stand 4 walk from the spawn, 3 tiles from a partner 16 walk
	// out). Walk around, along the partner's target field, else a path search; heals still go out on the way (heal range ignores
	// walls).
	if (dp > hr + 2)
	{
		// Travel to the partner: short search, else along the partner's target field, else greedy.
		if (mv::step_to(p.pos, 2, 40))
			return;
		if (gi >= 0)
			if (const distance_field* f = mv::group_field_ready(gi))
				if (dfget(*f, me) != UNREACH && mv::step_field(*f))
					return;
		mv::step_greedy(p.pos);
		return;
	}
	// Threat centre: enemies around the partner, else the partner's target group.
	float cx = 0, cy = 0;
	int cn = 0;
	for (const auto& e : W.enemies)
		if (cheb(e.pos, p.pos) <= 9)
		{
			cx += static_cast<float>(e.pos.x);
			cy += static_cast<float>(e.pos.y);
			++cn;
		}
	// Willow farm: no enemy near the partner (cn) or within WF_ENEMY_R of me.
	bool wf_quiet = cn == 0;
	for (const auto& e : W.enemies)
		if (cheb(e.pos, me) <= WF_ENEMY_R)
			wf_quiet = false;
	if (cn == 0 && gi >= 0)
	{
		const auto& g = M.groups[static_cast<std::size_t>(gi)];
		cx = static_cast<float>(g.anchor.x);
		cy = static_cast<float>(g.anchor.y);
		cn = 1;
	}
	else if (cn > 0)
	{
		cx /= static_cast<float>(cn);
		cy /= static_cast<float>(cn);
	}
	auto cdist = [&](vec2 t) { return std::max(std::fabs(static_cast<float>(t.x) - cx), std::fabs(static_cast<float>(t.y) - cy)); };
	const float ehp = std::max(1.0f, mu::mult_my_health_eff_hp(64)); // the unit of f.burst
	int np = 0;
	for (const auto& f : a.foes)
		if (f.reach >= 0 && cheb(p.pos, f.pos) <= f.reach)
			++np;
	const GroupView& gvw = group_view(gi);
	bool wf = !fight && wf_quiet && gvw.hittable; // Willow farm: farm the partner's group from in range
	if (wf && willow_farm_gated())
		wf = false;
	vec2 best = me;
	float best_s = -1e9f;
	for (int i = -1; i < 8; ++i)
	{
		const vec2 t = i < 0 ? me : me + DIRS[static_cast<std::size_t>(i)];
		if (i >= 0 && !mv::free_tile(t))
			continue;
		float s = 0;
		const int d = cheb(t, p.pos);
		if (d > hr)
			s -= 30.0f + 10.0f * static_cast<float>(d - hr);
		else if (d <= 1)
			s -= 3.0f;
		else if (d == hr)
			s -= 0.5f;
		s -= 0.5f * camp_hazard(t, p, gvw);
		float eh = 0;
		int nt = 0;
		for (const auto& f : a.foes)
		{
			if (f.reach < 0 || cheb(t, f.pos) > f.reach)
				continue;
			eh += (f.burst); // add the burst to the sum
			++nt;
			if (f.melee)
				eh += 0.3f * ehp;
		}
		s -= 40.0f * eh / ehp;
		if (nt > np)
			s -= 8.0f * static_cast<float>(nt - np);
		if (cn > 0 && !wf)
			s += 1.5f * clampf(cdist(t) - cdist(p.pos), -3.0f, 2.0f);
		const bool tgt = enemy_in_range_from(t, focus) || (!fight && camp_in_range_from(t, gvw));
		if (tgt)
			s += fight ? 6.0f : (wf ? static_cast<float>(WF_CAMP) : 3.0f);
		if (t == me)
			s += tgt ? 3.0f : 1.5f; // standing still keeps the attack allowance (attack, reset, attack)
		for (const vec2 rt : gvw.tiles)
			if (rt == t)
			{
				s -= 6.0f; // the partner's capture region: do not split its reward
				break;
			}
		if (s > best_s)
		{
			best_s = s;
			best = t;
		}
	}
	if (best != me)
		mv::try_move(best);
}
// Fuel use: recursive (no static bound). Not called in the measured games. Basic attacks: the focus enemy (else the weakest enemy in
// range), else the camps of the partner's target once they are awake; after a walk the reset restores the attack allowance.
void attack(int gi, int focus)
{
	const Kit& k = *W.me.kit;
	const Body* tgt = nullptr;
	if (focus >= 0 && cheb(W.enemies[static_cast<std::size_t>(focus)].pos, W.me.pos) <= W.me.range)
		tgt = &W.enemies[static_cast<std::size_t>(focus)];
	else
		for (const auto& e : W.enemies)
			if (cheb(e.pos, W.me.pos) <= W.me.range && !bbget(M.enemy_spawn, e.pos) && (!tgt || mu::ehp(e) < mu::ehp(*tgt)))
				tgt = &e;
	if (tgt)
	{
		const Body t = *tgt;
		if (!W.can_attack() && k.slot_reset >= 0 && combat::ready(k.slot_reset))
			combat::cast_self(k.slot_reset);
		if (combat::attack_champion(t) && k.slot_reset >= 0 && combat::ready(k.slot_reset) && mu::ehp(t) > (W.me.str))
			if (combat::cast_self(k.slot_reset))
				combat::attack_champion(t);
		return;
	}
	const GroupView& g = group_view(gi);
	int best = -1;
	float best_s = 1e9f;
	if (g.hittable)
		for (const auto& m : g.live)
		{
			if (cheb(m.pos, W.me.pos) > W.me.range)
				continue;
			const float s = m.hp + (m.str > 0 ? 0.0f : 3000.0f);
			if (s < best_s)
			{
				best_s = s;
				best = m.ci;
			}
		}
	if (best >= 0)
		combat::hit_camp(best);
}

} // namespace

int healer_slot()
{
	compute();
	return healer >= 0 ? healer : -1;
}

namespace {
int cache_round = -1, cache_partner = -1, cache_support = -1;
// Willow farm bruiser (the healer's own body): the last round an enemy was in sight within the farm's enemy radius of me.
int wf_enemy_round = -1000;
bool willow_farms_as_bruiser()
{
	for (const auto& e : W.enemies)
		if (cheb(e.pos, W.me.pos) <= WF2_ENEMY_R)
			wf_enemy_round = W.round;
	for (const auto& e : W.enemies_far)
		if (cheb(e.pos, W.me.pos) <= WF2_ENEMY_R)
			wf_enemy_round = W.round;
	if (!W.alive || W.round < WF_FROM || W.me.channeling())
		return false;
	bool mate = false;
	for (const auto& al : W.allies)
	{
		if (al.hp <= 0 || cheb(al.pos, W.me.pos) > WF_ALLY_R)
			continue;
		if (al.hp * 100.0f < static_cast<float>(WF_ALLY_PCT) * al.maxhp)
			return false; // a hurt mate beside me: heal and follow
		mate = true;
	}
	return mate || W.round - wf_enemy_round >= WF_QUIET; // farm beside a mate, or alone while no foe was seen near
}
// A mate's view: the healer farms on her own while her claim names a group other than her partner's (a follower
// mirrors the partner's claim every turn).
bool mate_sees_willow_farming(int hs, int ps)
{
	const int ng = M.ng;
	const int hg = comms::cgroup(hs);
	const int pg = comms::cgroup(ps);
	return W.round >= WF_FROM && hg >= 0 && hg < ng && hg != pg;
} // Fuel use: recursive (no static bound). Measured max 219, mean 32 per call, 6,691.4 calls per game, 216,752 per game including callees.
__attribute__((noinline)) void refresh_slow();
NOVA_INLINE void refresh() // inlined: the per-round cached test is inline, the rebuild is out of line
{
	if (cache_round == W.round && W.round > 0)
		return;
	refresh_slow();
}
void refresh_slow()
{
	compute();
	cache_round = W.round;
	cache_partner = cache_support = -1;
	if (healer < 0)
		return;
	for (int i = 0; i < n_order; ++i)
	{
		const int s = order[static_cast<std::size_t>(i)];
		if (alive_slot(s))
		{
			cache_partner = s;
			break;
		}
	}
	if (cache_partner >= 0 && alive_slot(healer))
		cache_support = healer;
	if (cache_support >= 0 && !(willow_farm_gated()) &&
		(P.my_slot == healer ? willow_farms_as_bruiser() : mate_sees_willow_farming(healer, cache_partner)))
		cache_support = -1; // she farms like any body this round
}
} // namespace

int partner_slot()
{
	refresh();
	return cache_partner;
}

int support_slot()
{
	refresh();
	return cache_support;
}

__attribute__((always_inline)) bool me_active() { return P.my_slot >= 0 && P.my_slot == healer_slot() && W.alive && partner_slot() >= 0 && support_slot() >= 0; }
// Fuel use: recursive (no static bound). Not called in the measured games.
bool heal()
{
	const Kit& k = *W.me.kit;
	if (k.slot_heal < 0 || !combat::ready(k.slot_heal))
		return false;
	const float amount = k.heal_mod * W.me.foc;
	const int hr = static_cast<int>(k.heal_range);
	const int ps = partner_slot();
	const Body* best = nullptr;
	float best_v = 0;
	const float nsk_tmin = static_cast<float>(NSK_TAB[2]) * 0.01f * amount;
	bool enemy_sight10 = false; // true when an enemy is in sight within 10 (passive Willow tops up only while none is)
	for (const auto& e : W.enemies)
		enemy_sight10 |= cheb(e.pos, W.me.pos) <= 10;
	for (const auto& al : W.allies)
	{
		if (cheb(al.pos, W.me.pos) > hr || al.hp <= 0 || bbget(M.my_spawn, al.pos))
			continue;
		const float missing = al.maxhp - al.hp;
		if (missing < 1.0f)
			continue; // never a full ally
		const float inc = incoming_on(al);
		bool fight = false;
		for (const auto& e : W.enemies)
			if (cheb(e.pos, al.pos) <= 5)
				fight = true;
		const bool dying = (inc > 0 || fight) && al.hp <= 1.3f * inc + 0.12f * al.maxhp;
		// Heart of Ruin hits harder while hurt: keep it alive, do not top it up.
		if (heart_layer::heal_hold(al) && al.frac() > 0.5f && !dying)
		{
			// PASSIVE Willow: a heal that lands in full adds more fight over its life than the missing-health bonus loses. Mode 2: only while
			// no enemy is in sight within 10 (in a fight the heal is kept for an ally below 50%).
			if (!(!enemy_sight10 && missing >= nsk_tmin) && (missing < WILLOW_TOPUP_MIN * amount))
				continue;
		}
		if (inc <= 0 && !fight)
		{
			// No damage coming: hold the heal, unless it lands in full on a badly hurt ally (it would leave to heal). Passive Willow: any
			// hurt ally once it lands in full (the cooldown restarts at once), while no enemy is in sight within 10 (a fight may need the
			// heal soon).
			if (!enemy_sight10) // top up, overheal allowed
			{
				if (missing < nsk_tmin)
					continue;
			}
			else if ((!(!enemy_sight10) && al.frac() >= 0.5f) ||
				missing < ((!enemy_sight10 && al.frac() >= 0.5f) ? WILLOW_TOPUP_MIN : 0.9f) * amount)
				continue;
		}
		else if (missing < (nsk_tmin) && !dying)
			continue;
		float v = std::min(missing, amount);
		if (dying)
			v *= 3.0f;
		else if (inc > 0 || fight)
			v *= 1.5f;
		if (al.kit && prism_layer::kit(*al.kit))
		{
			std::uint32_t ag = al.gems;
			v *= 1.0f + std::min(1.0f, static_cast<float>(ag) / 100.0f);
		}
		if (al.slot == ps)
			v *= 1.2f;
		if (v > best_v)
		{
			best_v = v;
			best = &al;
		}
	}
	if (!best)
		return false;
	NLOG("r%d slot %d WILLOW heal slot %d hp %.0f/%.0f\n", W.round, P.my_slot, best->slot, best->hp, best->maxhp);
	return combat::cast_on_champion(k.slot_heal, *best);
}

// Passive Willow: the heal first, whatever the turn does next (flee, low HP, capture, bank).
bool heal_any()
{
	if (!W.alive || W.me.channeling() || !W.me.kit || !willow_layer::me())
		return false;
	refresh(); // the bruiser test (and its enemy-seen clock) runs every live turn of the healer
	return heal();
}

// Fuel use: recursive (no static bound). Not called in the measured games.
bool turn(const combat::Assessment& a)
{
	if (!me_active())
		return false;
	note_seen();
	const int ps = partner_slot();
	auto claim_of = [](int s)
	{
		const int g = comms::cgroup(s);
		return g < M.ng ? g : -1;
	};
	const int gi = claim_of(ps);
	comms::write_claim(P.my_slot, gi, comms::cengaged(ps));
	const Body* p = escort(ps, gi);
	const vec2 me = W.me.pos;
	// An escort that dashed onto ground I cannot walk to (or a dash-only target) is out of my reach: following it would park me in the
	// 1-wide corridor or on the launch tile it needs to come back.
	bool cut = false;
	if (p && !mv::home_walkable(p->pos))
	{
		p = nullptr;
		cut = true;
	}
	if (p)
	{
		const Body partner = *p; // a copy: W.allies stays put this turn, but be safe
		const int pgi = partner.slot == ps ? gi : claim_of(partner.slot);
		heal();
		position(a, partner, pgi, false, a.focus);
		heal();
		attack(pgi, a.focus);
		return true;
	}
	heal();
	if (gi >= 0 && M.groups[static_cast<std::size_t>(gi)].access != ACC_WALK)
		cut = true; // DASHBLOCK: no walk leads to that target
	else if (gi >= 0)
	{
		// The partner is out of sight: walk to its target and wait outside the camps' reach until it shows up.
		const auto& g = M.groups[static_cast<std::size_t>(gi)];
		const int ring = (g.reach_max > 0 ? g.reach_max : 1) + 2;
		if (mv::camp_threat(me) > 0)
		{
			const auto z = mv::camp_threats_near(7);
			if (!z.empty())
				mv::escape(z);
		}
		else if (cheb(me, g.anchor) > ring)
		{
			bool moved = false;
			if (const distance_field* f = mv::group_field_ready(gi))
				if (dfget(*f, me) != UNREACH)
					moved = mv::step_field(*f);
			if (!moved && !mv::step_to(g.anchor, ring, 40))
				mv::step_greedy(g.anchor);
		}
		attack(gi, a.focus);
		return true;
	}
	const auto sp = static_cast<std::size_t>(ps);
	if (seen_round[sp] > 0 && !mv::home_walkable(seen_pos[sp]))
		cut = true; // DASHBLOCK: last seen where no walk leads
	else if (seen_round[sp] > 0 && cheb(seen_pos[sp], me) > 2)
	{
		if (!mv::step_to(seen_pos[sp], 2, 40))
			mv::step_greedy(seen_pos[sp]);
		return true;
	}
	// DASHBLOCK: not following (out of my reach): first out of a launch tile or a 1-wide corridor, homeward, so the dashers' route
	// stays open; then farm like any body.
	if (cut && W.can_move() && (mv::launch_tile(me) || mv::open_neighbour_count(me) <= 2))
	{
		if (mv::unpark())
			return true;
		if (M.has_home && dfget(M.f_home, me) != UNREACH && dfget(M.f_home, me) > 0 && mv::step_field(M.f_home))
			return true;
	}
	return false; // lost the partner with nothing to walk to: farm this turn
}
// Fuel use: recursive (no static bound). Measured max 42, mean 42 per call, 264.9 calls per game, 11,124 per game including callees.
bool fight_turn(const combat::Assessment& a)
{
	if (!(P.my_slot >= 0 && P.my_slot == healer_slot() && W.alive && partner_slot() >= 0))
		return false; // a farming healer still fights from the backline
	note_seen();
	const Body* p = visible_ally_body_of_slot(partner_slot());
	if (!p || p->channeling() || cheb(p->pos, W.me.pos) > 7 || !mv::home_walkable(p->pos)) // skip an escort that is channelling, farther than 7, or on ground I cannot walk to
	{
		// Fight next to the nearest ally instead.
		p = nullptr;
		int bd = 8;
		for (const auto& al : W.allies)
		{
			const int d = cheb(al.pos, W.me.pos);
			if (!al.channeling() && d < bd && mv::home_walkable(al.pos)) // a candidate must not be channelling and must stand on ground I can walk to
			{
				bd = d;
				p = &al;
			}
		}
	}
	if (!p)
		return false;
	const Body partner = *p;
	// Retreat first when focused: hit this round and the next volley would hurt.
	const float ehp = mu::mult_my_health_eff_hp(128); // the unit of a.incoming
	if (a.in_reach && combat::took_damage(1) && (a.incoming >= 0.3f * ehp || W.me.frac() < 0.5f))
	{
		heal();
		if (combat::flee(a))
			return true;
	}
	heal();
	position(a, partner, -1, true, a.focus);
	heal();
	attack(-1, a.focus);
	return true;
}
// Fuel use: recursive (no static bound). Measured max 230, mean 59 per call, 721.9 calls per game, 42,591 per game including
// callees.
float engage_scale()
{
	const int hs = support_slot();
	if (hs < 0)
		return 1.0f;
	if (hs == P.my_slot)
	{
		const Body* p = visible_ally_body_of_slot(partner_slot());
		return (p && cheb(p->pos, W.me.pos) <= 4) ? WILLOW_ENGAGE : 1.0f;
	}
	const Body* h = W.ally_by_slot(hs);
	if (!h || h->channeling() || h->frac() < 0.3f || cheb(h->pos, W.me.pos) > 5)
		return 1.0f;
	return WILLOW_ENGAGE;
}
// Fuel use: recursive (no static bound). Measured max 35, mean 35 per call, 51.0 calls per game, 1,787 per game including callees.
const Body* ready_healer_near(int maxd, int maxcd)
{
	const int hs = healer_slot();
	if (hs < 0 || hs == P.my_slot || !W.alive)
		return nullptr;
	const Body* h = W.ally_by_slot(hs);
	if (!h || h->hp <= 0 || !willow_layer::body(*h) || h->channeling() || cheb(h->pos, W.me.pos) > maxd)
		return nullptr;
	const auto sl = static_cast<std::size_t>(h->kit->slot_heal);
	if (sl >= h->cd.size())
		return nullptr;
	std::int32_t cd = h->cd[sl];
	if (cd < 0) // allies' cooldowns are read only near enemies: ask the host
	{
		std::int32_t c2 = -1;
		if (cambc::detail::sdk_champion_cooldown(h->h, static_cast<std::uint32_t>(sl), &c2) == 0)
			cd = c2;
	}
	if (cd < 0 || cd > maxcd)
		return nullptr;
	return h;
}

bool no_foe_reach_within_margin(const combat::Assessment& a, int margin)
{
	for (const auto& f : a.foes)
		if (f.reach >= 0 && cheb(f.pos, W.me.pos) <= f.reach + margin)
			return false;
	return true;
}


int cap_penalty(int slot)
{
	const int hs = healer_slot();
	if (hs >= 0 && slot == hs && support_slot() < 0 && partner_slot() >= 0)
		return 0; // a farming healer captures like any body
	return (hs >= 0 && slot == hs) ? 3000 : 0;
}

} // namespace nova::support
