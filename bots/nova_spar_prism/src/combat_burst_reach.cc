// combat_burst_reach.cc: Stun reach, burst timing and the zones built from it.
#include "combat_internal.h"
namespace nova::combat {
namespace burst {
namespace {
// A ready stun of foe e that reaches me at distance d this turn (cc, aoe stun, dash landing stun, enhanced-attack reset).
static bool foe_stun_reaches_me(const Body& e, int d)
{
	if (!e.kit || !e.kit->valid || e.stunned)
		return false;
	const Kit& k = *e.kit;
	auto rdy = [&](int s) { return foe_ready(e, s); };
	if (rdy(k.slot_cc) && d <= static_cast<int>(k.cc_range) + (k.cc_excl ? 0 : 1))
		return true;
	if (k.aoe_stun && rdy(k.slot_aoe) && d <= static_cast<int>(k.aoe_range + k.aoe_radius) + (k.aoe_excl ? 0 : 1))
		return true;
	if (k.dash_stun && rdy(k.slot_dash) && d <= static_cast<int>(k.dash_range + k.dash_radius) + 1)
		return true;
	return k.reset_enhanced && rdy(k.slot_reset) && d <= fk1_armed_reach(e, k);
}
} // namespace
// Foe e's best damage on me over two of its turns, one cast a turn: turn 1 spends slot s (or none), turn 2 (cooldowns one turn on,
// from within its attack range) cannot use s again. t1 = lethal_burst_hit(e, d, 0).
static float foe_two_turn_damage(const Body& e, int d, float t1)
{
	Body x = e;
	float best = t1;
	for (int s = -1; s <= 1; ++s)
	{
		if (s >= 0 && foe_cd(e, s) > 0)
			continue;
		x.cd = e.cd;
		for (int o = 0; o <= 1; ++o)
			if (o != s)
				x.cd[static_cast<std::size_t>(o)] = 99;
		const float a1 = lethal_burst_hit(x, d, 0, nullptr);
		x.cd = e.cd;
		if (s >= 0)
			x.cd[static_cast<std::size_t>(s)] = 99;
		int mvd = (e.kit && s >= 0 && s == e.kit->slot_dash) ? std::max(1, static_cast<int>(e.kit->dash_range)) : (d > e.range ? 1 : 0);
		if (e.kit && s >= 0) // a dash leaves the walk, an exclusive cast takes it
		{
			const Kit& ek = *e.kit;
			if (s == ek.slot_dash)
				mvd += 1;
			else if ((s == ek.slot_dmg && ek.dmg_excl) || (s == ek.slot_cc && ek.cc_excl) || (s == ek.slot_aoe && ek.aoe_excl))
				mvd = 0;
		}
		best = std::max(best, a1 + lethal_burst_hit(x, std::max(1, d - mvd), 1, nullptr));
	}
	return best;
}
namespace {
// Burst test using the crv model; the two-turn sum only when a ready stun reaches me and the one-turn sum is short (fuel). With bit
// 16 also when a foe has two turns before my next turn (reach_burst_turns, once per turn): that foe's two-turn burst (foe_two_turn_damage; a foe whose
// one-turn hit is 0 walks a tile on turn 1 and hits on turn 2 with cooldowns one turn on).
static bool reach_burst_test(float cap)
{
	irb_ed = false;
	const bool imm = marcella_layer::fight_irb_imm();
	float s1 = 0.0f;
	bool stun = false, dbl = false; // dbl: a foe within 9 has two turns before my next
	for (const auto& e : W.enemies)
	{
		const int d = cheb(e.pos, W.me.pos);
		if (d > 9)
			continue;
		dbl = dbl || (reach_burst_turns(e) >= 2);
		if (e.stunned && (reach_burst_turns(e)) <= 1)
			continue; // its next turn is the stunned one: no one-turn burst, and no stun from it
		const float h = lethal_burst_hit(e, d, 0, nullptr);
		if (h <= 0.0f)
			stun = stun || (!imm && foe_stun_reaches_me(e, d)); // CBH 2 ZDS2: a stun-only foe still costs me my turn
		if (h <= 0.0f)
		{
			continue;
		}
		s1 += h;
		stun = stun || (!imm && foe_stun_reaches_me(e, d));
	}
	if (s1 >= cap || (!stun && !dbl))
		return s1 >= cap;
	float s2 = 0.0f, add = 0.0f;
	for (const auto& e : W.enemies)
	{
		const int d = cheb(e.pos, W.me.pos);
		if (d > 9)
			continue;
		const float h = lethal_burst_hit(e, d, 0, nullptr);
		// bit 16: base = the one-turn term (0 for a foe it skips); v = the term with this foe's double turn
		const bool own = h > 0.0f;
		const bool skip1 = e.stunned && (reach_burst_turns(e)) <= 1; // its next turn is the stunned one
		const float base = !own ? 0.0f : (!stun ? (skip1 ? 0.0f : h) : skip1 ? h : foe_two_turn_damage(e, d, h));
		float v = base;
		if (reach_burst_turns(e) >= 2)
		{
			if (e.stunned)
				v = std::max(v, lethal_burst_hit(e, d, 1, nullptr)); // a stunned foe loses its first turn: one turn, cooldowns one on
			else if (own)
				v = stun ? base : foe_two_turn_damage(e, d, h);
			else if (d > 1)
				v = lethal_burst_hit(e, d - 1, 1, nullptr); // out of reach now: a tile walked on turn 1, the hit on turn 2
		}
		const float fsh = 1.0f;
		s2 += v * fsh;
		add += (v - base) * fsh;
	}
	const bool own_fire = stun && s2 - add >= cap;
	irb_ed = s2 >= cap && !own_fire;
	return s2 >= cap;
}
} // namespace
// The in-reach burst test for every body.
void reach_burst_assess(Assessment& a, bool kill_now)
{
	irb_fired = false;
	if (!a.in_reach || kill_now || !W.alive || !W.me.kit || W.me.channeling() || (linked_slot() >= 0 && !CI2_FIGHT())) // a kill-now turn with a bag and a stun on me keeps the test
		return;
	if (a.stance == FLEE)
		return; // already fleeing: nothing to flip
	if (fuel() < IRB_TAB[3])
		return; // a heavy turn keeps its stance (a new flee costs a flee() search: no flip below IRB_FUEL fuel left)
	{
		// assess() runs up to 3 times a turn: the test is cached per turn and state (my tile and HP, the visible foes' tiles and HP)
		static int c_round = -1;
		static std::uint32_t c_me = 0, c_key = 0;
		static bool c_val = false, c_ed = false;
		std::uint32_t key = static_cast<std::uint32_t>(W.me.pos.x * 131 + W.me.pos.y) * 2654435761u ^ static_cast<std::uint32_t>(eff_hp(W.me) * 8.0f);
		for (const auto& e : W.enemies)
			key = key * 16777619u ^ (static_cast<std::uint32_t>(e.pos.x * 131 + e.pos.y) + static_cast<std::uint32_t>(eff_hp(e) * 8.0f) * 97u + (e.stunned ? 7u : 0u));
		if (c_round != W.round || c_me != W.me.h || c_key != key)
		{
			c_val = reach_burst_test(eff_hp(W.me) * static_cast<float>(IRB_TAB[2]) / 100.0f);
			c_ed = irb_ed;
			c_round = W.round;
			c_me = W.me.h;
			c_key = key;
		}
		irb_fired = static_cast<bool>(c_val);
		irb_ed = c_ed;
	}
	if (!irb_fired)
		return;
	if (a.stance != FLEE)
		a.stance = FLEE;
}
namespace {
// see the declaration. Stun is ignored (no credit), as is the foe's path around walls (Chebyshev is a lower bound).
static int foe_turns_to_hit_k(const Body& e, int dist, bool wth)
{
	const Kit* kp = e.kit;
	auto opt = [dist](int k, int reach) { return std::max(k, 1 + std::max(0, dist - reach)); };
	if (!kp || !kp->valid)
		return opt(1, std::max(4, e.range));
	const Kit& k = *kp;
	auto kr = [&](int s) { return (s < 0 || s > 1) ? BIG : wth ? 1 + std::max(0, foe_cd(e, s)) : std::max(1, foe_cd(e, s)); };
	int t = opt(1, k.ranged ? e.range : 2);
	if (k.ranged && k.slot_reset >= 0)
		t = std::min(t, opt(kr(k.slot_reset), e.range + 1));
	if (k.slot_dash >= 0)
		t = std::min(t, opt(kr(k.slot_dash), k.ranged ? e.range + 2 : 4));
	auto sp = [&](int s, float range, bool excl, float radius)
	{
		if (s >= 0 && s <= 1)
			t = std::min(t, opt(kr(s), static_cast<int>(range + radius) + (excl ? 0 : 1)));
	};
	sp(k.slot_dmg, k.dmg_range, k.dmg_excl, 0.0f);
	sp(k.slot_cc, k.cc_range, k.cc_excl, 0.0f);
	sp(k.slot_aoe, k.aoe_range, k.aoe_excl, k.aoe_radius);
	return t;
}
__attribute__((noinline)) void lethal_burst_zones_slow(const Assessment& a, std::vector<std::pair<vec2, int>>& out)
{
	if (!W.alive || !W.me.kit || W.me.channeling())
		return;
	const float cap = lb_cap();
	const int mg = LETHAL_BURST_TAB[3];
	for (const auto& e : W.enemies)
	{
		const int de = cheb(e.pos, W.me.pos);
		if (de > 9)
			continue;
		if (foe_stunned_next_turn(e))
			continue;
		if (KQ_SITE(8, kills(e, de, 0), de <= std::max(W.me.range + 1, 2) && eff_hp(e) <= geom::my_burst(e, de)))
			continue;
		// lethal_burst_hit(e, d) is non-increasing in d when Strength and Focus are >= 0 (every term is a
		// non-negative value gated by d <= a threshold; best = their max), so the largest d in 0..7 with lethal_burst_hit >= cap is found
		// by testing d = 0 first (none: no zone) and a binary search, instead of up to 8 calls from d = 7 down. Same zones.
		const int ce = LETHAL_BURST_TAB[5] + (reach_burst_turns(e) >= 2 ? 1 : 0);
		if (e.str >= 0.0f && e.foc >= 0.0f)
		{
			if (!(lethal_burst_hit(e, 0, ce, nullptr) >= cap))
				continue;
			int lo = 0, hi = 7; // lethal_burst_hit(lo) >= cap holds
			while (lo < hi)
			{
				const int mid = (lo + hi + 1) >> 1;
				if (lethal_burst_hit(e, mid, ce, nullptr) >= cap)
					lo = mid;
				else
					hi = mid - 1;
			}
			if (de <= lo + mg + 2)
				out.emplace_back(e.pos, lo + mg);
			continue;
		}
		for (int d = 7; d >= 0; --d)
			if (lethal_burst_hit(e, d, ce, nullptr) >= cap)
			{
				const int z = d; // as above
				if (z >= 0 && de <= z + mg + 2) // a zone I cannot enter within 2 steps is left out (fuel: guard and path searches)
					out.emplace_back(e.pos, z + mg);
				break;
			}
	}
}
} // namespace
// The most foe e deals me at distance d over its n turns before my next turn. Foe turn k: its cooldowns have ticked k times and it has walked k steps (a stun loses the first turn).
static float foe_damage_over_turns(const Body& e, int d, int n)
{
	if (n >= 2 && VB2_ON(1)) // v7xx VB2 bit 1 ESD1: two turns sum (the two-turn memo), not the max of one hit
	{
		const float h = lethal_burst_hit(e, d, 0, nullptr);
		const float v = lethal_burst_two_turn_hit(e, d, h);
		VB2_CNT(1, v > h);
		return v;
	}
	float best = 0;
	for (int k = e.stunned ? 1 : 0; k < n; ++k)
		best = std::max(best, lethal_burst_hit(e, std::max(0, d - (e.stunned ? k - 1 : k)), k, nullptr));
	return best;
}
static float foes_damage_at_tile(vec2 t, const std::array<int, 12>& nn)
{
	float sum = 0;
	for (std::size_t x = 0; x < W.enemies.size() && x < nn.size(); ++x)
	{
		const Body& e = W.enemies[x];
		if (cheb(e.pos, W.me.pos) <= 9)
			sum += foe_damage_over_turns(e, cheb(e.pos, t), nn[x]);
	}
	return sum;
}
namespace {
static int champion_priority_of(std::uint32_t h, bool next)
{
	std::int32_t v = 0;
	cambc::detail::sdk_bc_champion_priority(h, next ? 1 : 0, &v);
	return v;
}
} // namespace
int ed_prio_hdt(std::uint32_t h, bool next) { return champion_priority_of(h, next); }
namespace {
static __attribute__((always_inline)) inline EdRanks turn_order_ranks()
{
	EdRanks q;
	q.my_start = !enemy_starts(W.round);
	const int pa = PRA_DEC(champion_priority_of(W.me.h, false)), pa2 = PRA_DEC(champion_priority_of(W.me.h, true)); // our values decode
	for (const auto& al : W.allies)
	{
		q.ra += PRA_DEC(champion_priority_of(al.h, false)) > pa ? 1 : 0;
		const int an2 = PRA_DEC(champion_priority_of(al.h, true));
		q.ra2 += an2 > pa2 ? 1 : 0;
		if (q.nan < 8)
			q.an[static_cast<std::size_t>(q.nan++)] = an2; // PHY: kept for the rank swap
	}
	q.m = std::min(W.enemies.size(), q.pb.size());
	for (std::size_t x = 0; x < q.m; ++x)
	{
		q.pb[x] = champion_priority_of(W.enemies[x].h, false);
		q.pb2[x] = champion_priority_of(W.enemies[x].h, true);
	}
	return q;
}
// FB5 RBF1: turn_order_ranks filled into q in place (no 148-byte copy); rows of pb/pb2 at m and above are never read.
static __attribute__((always_inline)) inline void turn_order_ranks_into(EdRanks& q)
{
	q.my_start = !enemy_starts(W.round);
	q.ra = 0;
	q.ra2 = 0;
	q.an = {};
	q.nan = 0;
	const int pa = PRA_DEC(champion_priority_of(W.me.h, false)), pa2 = PRA_DEC(champion_priority_of(W.me.h, true));
	for (const auto& al : W.allies)
	{
		q.ra += PRA_DEC(champion_priority_of(al.h, false)) > pa ? 1 : 0;
		const int an2 = PRA_DEC(champion_priority_of(al.h, true));
		q.ra2 += an2 > pa2 ? 1 : 0;
		if (q.nan < 8)
			q.an[static_cast<std::size_t>(q.nan++)] = an2;
	}
	q.m = std::min(W.enemies.size(), q.pb.size());
	for (std::size_t x = 0; x < q.m; ++x)
	{
		q.pb[x] = champion_priority_of(W.enemies[x].h, false);
		q.pb2[x] = champion_priority_of(W.enemies[x].h, true);
	}
}
static std::array<std::uint32_t, 8> toc_fh{};           // foe roster handles
static std::array<std::int32_t, 8> toc_fc{}, toc_fx{};  // each roster foe's last read value now / next round
static std::array<int, 8> toc_fr{};                     // the round of that read
constexpr int TOC_HK = 3;                               // rounds of each foe's read values kept (its recent highest)
static std::array<std::array<int, TOC_HK>, 8> toc_hr{}, toc_hv{};
static std::array<std::uint32_t, 8> toc_ah{};           // our slots' handles, last read next value, its round
static std::array<std::int32_t, 8> toc_ax{};
static std::array<int, 8> toc_ar{};
} // namespace
// TIS: per foe handle, its last read priority and the round this body saw it change (bit 2).
static int tis_turns(std::uint32_t h, int v, int first)
{
	const int a = 1 + first;
	static std::array<std::uint32_t, 16> th{};
	static std::array<int, 16> tv{}, tc{};
	int k = -1;
	for (int i = 0; i < 16 && k < 0; ++i)
		if (th[static_cast<std::size_t>(i)] == h)
			k = i;
	if (k < 0)
		for (int i = 0; i < 16 && k < 0; ++i)
			if (th[static_cast<std::size_t>(i)] == 0)
			{
				k = i;
				th[static_cast<std::size_t>(i)] = h;
				tv[static_cast<std::size_t>(i)] = v;
				tc[static_cast<std::size_t>(i)] = -1000;
			}
	if (k < 0)
		return 2; // table full: the worst case
	const auto ku = static_cast<std::size_t>(k);
	if (tv[ku] != v)
	{
		tv[ku] = v;
		tc[ku] = W.round;
	}
	return W.round - tc[ku] <= 10 ? 2 : a;
}
static void foe_turn_counts_fill(std::array<int, 12>& nn)
{
	const EdRanks q = turn_order_ranks();
	for (std::size_t x = 0; x < q.m; ++x)
	{
		int rb = 0, rb2 = 0;
		q.foe_rank(x, rb, rb2);
		if (q.still_to_act(rb))
		{
			nn[x] = (!(W.me.kit && W.me.kit->gem_focus)) ? tis_turns(W.enemies[x].h, q.pb[x], q.first_next_round(rb2) ? 1 : 0) : q.turns_if_still(); // the Prism keeps today's count (her tribute start/keep, owner rule)
		}
		else if (q.first_next_round(rb2))
			nn[x] = 1;
		else
		{
			nn[x] = (static_cast<int>(W.enemies.size()) < intel::enemies_alive()) ? 1 : 0; // CIS bit 1
		}
	}
}
namespace {
static EdRanks phy_q;            // PHY: the ranks the turn table was built from
static int phy_q_round = -1000;
static std::uint32_t phy_q_me = 0;
static IrbTurnTab phy_saved;     // PHY: the real table while the swapped one stands
// v699 RCA bit 1 BRM1: unseen foes that may still act = living foes - visible (P.n is our body count and counts dead foes).
static int brm_miss()
{
	return std::max(0, P.n - static_cast<int>(W.enemies.size()));
}
static __attribute__((noinline)) void reach_burst_turns_fill()
{
	IrbTurnTab& b = irb_tab;
	turn_order_ranks_into(phy_q); // PHY: this turn's ranks for the rank swap
	const EdRanks& q = phy_q;
	phy_q_round = W.round;
	phy_q_me = W.me.h;
	b.m = q.m;
	const int miss = brm_miss(); // v699 RCA bit 1 BRM1
	for (std::size_t x = 0; x < q.m; ++x)
	{
		int rb = 0, rb2 = 0;
		q.foe_rank(x, rb, rb2);
		b.hh[x] = W.enemies[x].h;
		const bool still = q.still_to_act(rb + miss);
		const int first = q.first_next_round(rb2) ? 1 : 0;
		b.nn[x] = still ? ((!(W.me.kit && W.me.kit->gem_focus)) ? tis_turns(W.enemies[x].h, q.pb[x], first) : q.turns_if_still()) : first; // the Prism keeps today's count
	}
	b.at_round = W.round;
	b.at_me = W.me.h;
}
} // namespace
// PHY: the turn table with my next-round rank taken at value v (our mates' next values kept from the fill; no new reads). True: swapped.
bool phy_swap_table(int v)
{
	if (irb_tab.at_round != W.round || irb_tab.at_me != W.me.h)
		reach_burst_turns_fill();
	if (phy_q_round != W.round || phy_q_me != W.me.h)
		return false;
	EdRanks q = phy_q;
	int ra2 = 0;
	for (int i = 0; i < q.nan; ++i)
		ra2 += q.an[static_cast<std::size_t>(i)] > v ? 1 : 0;
	if (ra2 == q.ra2)
		return false; // my next rank is the same: the real table answers
	q.ra2 = ra2;
	phy_saved = irb_tab;
	const int miss = brm_miss(); // v699 RCA bit 1 BRM1
	for (std::size_t x = 0; x < q.m; ++x)
	{
		int rb = 0, rb2 = 0;
		q.foe_rank(x, rb, rb2);
		const bool still = q.still_to_act(rb + miss);
		const int first = q.first_next_round(rb2) ? 1 : 0;
		irb_tab.nn[x] = still ? ((!(W.me.kit && W.me.kit->gem_focus)) ? tis_turns(W.enemies[x].h, q.pb[x], first) : q.turns_if_still()) : first; // TIS: the PHY swap takes the same count (the Prism keeps today's)
	}
	return true;
}
void phy_restore_table() { irb_tab = phy_saved; }
int reach_burst_turns(const Body& e)
{
	const IrbTurnTab& b = irb_tab;
	if (b.at_round != W.round || b.at_me != W.me.h)
		reach_burst_turns_fill();
	for (std::size_t x = 0; x < b.m; ++x)
		if (b.hh[x] == e.h)
			return b.nn[x];
	return 2; // a foe not in this turn's list is not certain
}
namespace {
} // namespace
// stunned foe e still has a usable turn before my next (a stun takes only its next turn). Foes only.
bool bh81_stun2(const Body& e) { return e.stunned && !e.ally && (reach_burst_turns(e)) >= 2; }
} // namespace burst
namespace pdk {
// The foe Prism of this turn: a seen one, else the last one seen <= 4 rounds ago (cooldowns aged by the rounds since).
struct Duel
{
	int round = -1000;
	std::uint32_t me_h = 0;
	bool on = false;       // a foe Prism is known and her ready casts take my HP + shield (bit 1's state)
	bool seen = false;     // she is in W.enemies now (idx valid)
	int idx = -1;
	vec2 pos{ -1, -1 };
	int reach = 4;         // 4, or 5 with two turns of hers before my next
	int nt = 0;            // her turns before my next (bit 1's state only)
	float foc = 0;
};
static Duel du;
static int mem_r = -1000, mem_cd0 = -1, mem_cd1 = -1;
static float mem_foc = 0, mem_str = 0;
static const Kit* mem_kit = nullptr;
} // namespace pdk
// foe_stun_reaches_me for callers outside the combat files (the crystal foe bar).
bool rf2_stun_reach(const Body& e, int d) { return burst::foe_stun_reaches_me(e, d); }
int foe_first_hit_turn(const Body& e, int dist)
{
	const bool wth = false;
	const int t = burst::foe_turns_to_hit_k(e, dist, wth);
	SPELL_READY_FIX_CNT(0, t != burst::foe_turns_to_hit_k(e, dist, true));
	return t;
}
// The first early-out test inline at the call site (a call and frame a turn saved), the rest out of line.
__attribute__((always_inline)) void lethal_burst_zones(const Assessment& a, std::vector<std::pair<vec2, int>>& out)
{
	if (!((a.stance == CALM) || (a.stance == FIGHT)) || W.enemies.empty()) // FB5 LBZ1
		return;
	burst::lethal_burst_zones_slow(a, out);
}
} // namespace nova::combat
