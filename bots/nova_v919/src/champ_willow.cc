// champ_willow.cc: WILLOW LAYER, Willow's rules (hooks: champ_willow.h; flags: champ_willow.h). The team's healer: her partner pick
// (compute), her heal choice (heal_any, wl2_heal), WILLOW_FARM (the bruiser mode), WILLOW_REGEN's healer side
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


} // namespace

int healer_slot()
{
	compute();
	return healer >= 0 ? healer : -1;
}

// b2390 WSS bit 1 (champ_willow.h; the caller read the flag): the heal is ready, no mate in reach took it; a seen mate at heal reach + 1 ..
// WSS_FAR, not recalling, not on our spawn, missing >= 3 x my Focus: one step toward the neediest. True when I moved.
static __attribute__((noinline)) bool wss_step()
{
	const Kit& k = *W.me.kit;
	if (k.slot_heal < 0 || W.cast || W.moved || !combat::ready(k.slot_heal))
		return false;
	const int hr = static_cast<int>(k.heal_range);
	const float need = 3.0f * W.me.foc;
	const Body* best = nullptr;
	for (const auto& al : W.allies)
	{
		const int d = cheb(al.pos, W.me.pos);
		if (al.hp <= 0 || d <= hr || d > WSS_TAB[2] || (al.state & ST_RECALL) != 0 || bbget(M.my_spawn, al.pos) || al.maxhp - al.hp < need)
			continue;
		if (!best || al.maxhp - al.hp > best->maxhp - best->hp)
			best = &al;
	}
	return best && mv::step_to(best->pos, hr, 20);
}
// Passive Willow: the heal first, whatever the turn does next (flee, low HP, capture, bank).
bool heal_any()
{
	if (!W.alive || W.me.channeling() || !W.me.kit || !willow_layer::me())
		return false;
	if (wl2_heal()) // bit 16384 (diagnostic): the old heal rule on the new path
		return true;
	return wss_step() && wl2_heal(); // b2390 WSS bit 1: one step toward a mate a full heal fits, then the heal rule again
}

// WL7: the backline fight turn needs a partner, and partner_slot() was always -1: never taken. healer_slot() still runs compute().
bool fight_turn(const combat::Assessment&)
{
	if (P.my_slot >= 0)
		healer_slot();
	return false;
}
// Fuel use: recursive (no static bound). Measured max 230, mean 59 per call, 721.9 calls per game, 42,591 per game including
// callees.
float engage_scale()
{
	healer_slot(); // runs compute(); scale 1 always: support_slot() was always -1 (WL7; WL2 bit 4096 not shipped)
	return 1.0f;
}
// Fuel use: recursive (no static bound). Measured max 35, mean 35 per call, 51.0 calls per game, 1,787 per game including callees.
const Body* ready_healer_near(int maxd, int maxcd)
{
	const int hs = healer_slot();
	if (hs < 0 || hs == P.my_slot || !W.alive)
		return nullptr;
	const Body* h = W.ally_by_slot(hs);
	if (!h || h->hp <= 0 || !willow_layer::body(*h) || h->channeling() || cheb(h->pos, W.me.pos) > maxd || h->stunned) // WST_ON bit 1: a stunned Willow
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



// ---- WL2 (b1740), decision 4: the heal on cooldown, on whoever needs it. Score min(missing, 3 x Focus) x weight: dies to the next
// round's hits 4, under camp fire 2, under champion fire 1.75, a calm top-up 1 (at least WL2_MIN missing). Never a mate on our spawn or
// recalling (both heal there), never herself (W.allies excludes me).
static __attribute__((noinline)) float tbf_wsh1_eff(const Body& al) { return al.hp + (al.shield_turns >= 1 ? al.shield : 0.0f); }
bool wl2_heal()
{
	const Kit& k = *W.me.kit;
	if (k.slot_heal < 0 || W.cast || !combat::ready(k.slot_heal))
		return false;
	const float amount = k.heal_mod * W.me.foc;
	const int hr = static_cast<int>(k.heal_range);
	const float least = static_cast<float>(WL2_TAB[3]);
	const Body* best = nullptr;
	float best_v = 0;
	const int scan = hr;
	const Body* wvs_next = nullptr;
	float wvs_next_v = 0;
	std::uint32_t wgl_tank = 0; // WGL bit 2 (b1769): on a golem/monolith crew, the crew's tank (the mate nearest the group) is healed first, on cooldown
	bool wgl_on = false, wgl_done = false;
	const auto wgl_find = [&]()
	{
		const int gi = econ::claim_target();
		if (gi >= 0 && gi < M.ng && M.groups[static_cast<std::size_t>(gi)].n_golem + M.groups[static_cast<std::size_t>(gi)].n_mono > 0)
		{
			const vec2 an = M.groups[static_cast<std::size_t>(gi)].anchor;
			int bd = 7;
			for (const auto& al : W.allies)
				if (al.hp > 0 && cheb(al.pos, an) < bd)
				{
					bd = cheb(al.pos, an);
					wgl_tank = al.h;
					wgl_on = true;
				}
			if (wgl_on) // BB34_ON bit 16 WL6: the crew's tank as econ's crew_here picks it (one tank definition)
			{
				const auto hh = econ::crew_here(gi);
				wgl_on = hh.tank != nullptr;
				wgl_tank = wgl_on ? hh.tank->h : 0u;
			}
		}
	};
	for (const auto& al : W.allies)
	{
		if (al.hp <= 0 || cheb(al.pos, W.me.pos) > scan || (al.state & ST_RECALL) != 0 || bbget(M.my_spawn, al.pos))
			continue;
		const float missing = al.maxhp - al.hp;
		if (missing < 1.0f)
			continue;
		float camp = 0; // awake camps that reach it and have no nearer champion (GR:192: a camp hits the nearest champion)
		for (const auto& vc : W.camps)
		{
			if (!vc.awake)
				continue;
			const auto& c = M.camps[static_cast<std::size_t>(vc.ci)];
			const int da = cheb(al.pos, c.pos);
			if (!c.attacks() || da > c.reach || cheb(W.me.pos, c.pos) < da)
				continue;
			if (cheb(W.me.pos, c.pos) == da && !mv::takes_tie(al))
			{
				continue; // WCT bit 1 WCT1: I take this tie
			}
			bool other = false;
			for (const auto& b : W.allies)
				other = other || (b.h != al.h && cheb(b.pos, c.pos) < da);
			for (const auto& e : W.enemies)
				other = other || cheb(e.pos, c.pos) < da;
			if (!other)
				camp += c.str;
		}
		float foe = 0; // visible foes that reach it next turn
		for (const auto& e : W.enemies)
			if (cheb(e.pos, al.pos) <= (combat::foe_next_turn_reach(e))) // v699 TBF bit 64 WRR1
				foe += combat::body_dps(e);
		float w = 1.0f;
		const float wsh = tbf_wsh1_eff(al); // v699 TBF bit 32 WSH1: a live shield absorbs too
		if (camp + foe > 0.0f && wsh <= camp + foe && (wsh + std::min(missing, amount) > camp + foe)) // BB34_ON bit 4 WL3: only a heal that saves it
			w = 4.0f;
		else if (camp > 0.0f)
			w = 2.0f;
		else if (foe > 0.0f)
			w = 1.75f;
		else if (missing < least) // BB34_ON bit 1 WL1: the calm tank keeps the filter
			continue;
		if (!wgl_done)
		{
			wgl_done = true;
			wgl_find();
		}
		if (wgl_on && al.h == wgl_tank) // WGL bit 2: tank first
		{
			w = (w >= 4.0f ? 4.5f : std::min(3.9f, 3.0f * w)); // BB34_ON bit 2 WL2: never over a mate's lethal volley
		}
		const float v = std::min(missing, amount) * w;
		if (v > best_v)
		{
			best_v = v;
			best = &al;
		}
	}
	return best && combat::cast_on_champion(k.slot_heal, *best);
}
// ---- WL2 PRX (bit 1048576): presence. A foe (mine or ward sight) within WL2_PRX_F of a visible mate sets the trigger for WL2_PRX_T
// rounds; while it holds and I stand farther than WL2_PRX_R from that mate, I step to a tile within heal reach of it where it is nearer
// the foe than the tile (a body between me and the foe), out of awake camps' reach. She never starts a fight: this is a CALM step.
namespace {
int prx_round = -1000, prx_slot = -1;
}
// ---- WL2, decision 3: a soft pull toward a working mate. Her own rate of group gi x (1 + WL2_PULL_X100 / 100) when another living
// body claims it (the buffer: works out of sight) or a visible mate stands within 6 of its anchor.
// WHV bit 4/8 (caller read the flag): gi is a heavy group that enough mates work for her to make a crew of 3+ (4+ with bit 8).
static __attribute__((noinline)) bool whv_attach(int gi)
{
	const auto& g = M.groups[static_cast<std::size_t>(gi)];
	if (!(g.n_golem > 0 || g.n_elk >= 2) || (g.n_mono > 0) || g.n_att <= 0 || g.access != ACC_WALK)
		return false;
	if (static_cast<std::size_t>(gi) >= nova::econ::mem.size() || nova::econ::mem[static_cast<std::size_t>(gi)].status != nova::econ::GS_ALIVE)
		return false;
	if (static_cast<int>(W.me.gems) >= WL2_BANK || W.me.frac() < 0.5f || nova::econ::big_group_nearly_dead(gi))
		return false;
	std::uint32_t mates = 0;
	for (int s = 0; s < P.n && s < comms::CLAIM_SLOTS && s < 32; ++s)
		if (s != P.my_slot && alive_slot(s) && comms::cgroup(s) == gi)
			mates |= 1u << s;
	for (const auto& al : W.allies)
		if (al.slot >= 0 && al.slot < 32 && al.slot != P.my_slot && !al.channeling() && cheb(al.pos, g.anchor) <= 6)
			mates |= 1u << al.slot;
	if (__builtin_popcount(mates) < (2))
		return false;
	return nova::econ::siege_enemies_near_group(gi, 15) == 0; // WHVFIRE
}
// b2451 WMC: the mate spot with the most living mates within heal range 4 (bit 2: a mate weighs 10 + 10 x its seen missing HP
// share; an unseen mate, placed at its posted claim's anchor, weighs 10). Cached per round in statics (n <= 8). False: no mate spot.
static vec2 wmc_t{ -1, -1 };
static int wmc_bcnt = 0, wmc_round = -1;
static bool wmc_spot()
{
	if (wmc_round == W.round)
		return wmc_t.x >= 0;
	wmc_round = W.round;
	wmc_t = vec2{ -1, -1 };
	std::array<vec2, 8> sp{};
	std::array<signed char, 8> hurt{};
	std::array<int, 8> wt{};
	int n = 0;
	std::array<int, 8> sl{};
	for (int s = 0; s < P.n && s < 8; ++s)
	{
		if (s == P.my_slot || !alive_slot(s))
			continue;
		vec2 p{ -1, -1 };
		signed char h = 0;
		int w = 10;
		if (const Body* b = W.ally_by_slot(s))
		{
			if (b->channeling())
				continue;
			p = b->pos;
			h = b->frac() < 0.7f ? 1 : 0;
			const float f = b->frac();
			w = 10 + static_cast<int>(10.0f * (1.0f - (f < 0.0f ? 0.0f : f > 1.0f ? 1.0f : f)));
		}
		else if (s < comms::CLAIM_SLOTS)
		{
			const int cg = comms::cgroup(s);
			if (cg >= 0 && cg < M.ng)
				p = M.groups[static_cast<std::size_t>(cg)].anchor;
		}
		if (p.x < 0)
			continue;
		sp[static_cast<std::size_t>(n)] = p;
		hurt[static_cast<std::size_t>(n)] = h;
		wt[static_cast<std::size_t>(n)] = w;
		sl[static_cast<std::size_t>(n)] = s;
		++n;
	}
	if (n == 0)
		return false;
	int best = -1, bc = -1, bh = -1, bcar = -1, bcnt = 0;
	for (int i = 0; i < n; ++i)
	{
		int c = 0, k = 0;
		for (int j = 0; j < n; ++j)
			if (cheb(sp[static_cast<std::size_t>(i)], sp[static_cast<std::size_t>(j)]) <= 4)
			{
				++k;
				c += 1;
			}
		const int h = hurt[static_cast<std::size_t>(i)];
		const int car = sl[static_cast<std::size_t>(i)] == P.carrier_gems ? 1 : 0;
		if (c > bc || (c == bc && (h > bh || (h == bh && car > bcar))))
		{
			best = i;
			bc = c;
			bh = h;
			bcar = car;
			bcnt = k;
		}
	}
	wmc_t = sp[static_cast<std::size_t>(best)];
	wmc_bcnt = bcnt;
	return true;
}
// b2433 WMC bit 1: a living mate works gi (claims it, or a seen mate not channelling stands within 6 of its anchor).
// b2451 bit 8: with my heal more than 2 turns off, also any group whose anchor is within 6 of the mate spot.
bool wmc_mate_group(int gi)
{
	if (gi < 0 || gi >= M.ng)
		return false;
	const auto& g = M.groups[static_cast<std::size_t>(gi)];
	for (int s = 0; s < P.n && s < comms::CLAIM_SLOTS; ++s)
		if (s != P.my_slot && alive_slot(s) && comms::cgroup(s) == gi)
			return true;
	for (const auto& al : W.allies)
		if (!al.channeling() && cheb(al.pos, g.anchor) <= 6)
			return true;
	return false;
}
// b2433 WMC bit 1: with no target, walk to the mate spot with the most living mates within heal range 4. True if the turn is used.
// b2451 bit 4: stay put while my tile covers >= max(1, best count - 1) mates. Bit 8: heal more than 2 turns off -> within 6 of the
// spot the turn goes back to the usual no-target path; farther, walk toward the spot.
bool wmc_follow()
{
	if (!wmc_spot())
		return false;
	const vec2 t = wmc_t;
	if (cheb(W.me.pos, t) <= 2 || !W.can_move() || W.moved)
		return cheb(W.me.pos, t) <= 4;
	return mv::step_to(t, 2, 40, -1);
}
float wl2_pull(int gi, float rate)
{
	if (rate <= 0.0f || gi < 0 || gi >= M.ng)
		return rate;
	const auto& g = M.groups[static_cast<std::size_t>(gi)];
	bool work = false;
	for (int s = 0; s < P.n && s < comms::CLAIM_SLOTS && !work; ++s)
		work = s != P.my_slot && alive_slot(s) && comms::cgroup(s) == gi;
	for (const auto& al : W.allies)
		work = work || (!al.channeling() && cheb(al.pos, g.anchor) <= 6);
	if (work && whv_attach(gi))
	{
		return rate * (1.0f + static_cast<float>(WL2_TAB[2]) / 100.0f) * (1.0f + static_cast<float>(WHV_TAB[2]) / 100.0f); // WHV bit 4
	}
	return work ? rate * (1.0f + static_cast<float>(WL2_TAB[2]) / 100.0f) : rate;
}

} // namespace nova::support
