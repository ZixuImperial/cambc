// combat_lethal_burst.cc: The lethal-burst model: incoming nukes and escape tiles.
#include "combat_internal.h"
namespace nova::combat {
namespace burst {
// BB13 bit 1 (v2, Rule Checker 9 Nov): a melee foe can't hit my spawn tile t when no ready spell reaches t from where it stands (range +
// radius) and it can't stand on a free non-spawn tile within its range of t after its walk (1) or a ready dash (GR:153, 161; INT:134).
__attribute__((noinline)) bool bb13_body_shielded(const Body& e, vec2 t)
{
	if (!e.kit || !e.kit->valid || e.kit->ranged || !bbget(M.my_spawn, t))
		return false;
	const Kit& k = *e.kit;
	const int d = cheb(e.pos, t);
	auto sp = [&](int slot, float range, float radius) { return slot >= 0 && kit_rules::slot_ready(e, slot) && d <= static_cast<int>(range + radius); };
	if (sp(k.slot_dmg, k.dmg_range, 0.0f) || sp(k.slot_cc, k.cc_range, 0.0f) || sp(k.slot_aoe, k.aoe_range, k.aoe_radius))
		return false;
	const int R = std::max(1, e.range);
	const int mvr = 1 + ((k.slot_dash >= 0 && kit_rules::slot_ready(e, k.slot_dash)) ? static_cast<int>(k.dash_range) : 0);
	for (int dy = -R; dy <= R; ++dy)
		for (int dx = -R; dx <= R; ++dx)
		{
			const vec2 q{ t.x + dx, t.y + dy };
			if (!inb(q) || bbget(M.my_spawn, q) || bbget(M.walls, q) || bbget(M.holes, q) || bbget(M.altars_bb, q))
				continue;
			if (q != e.pos && bbget(W.occ_units, q))
				continue;
			if (cheb(e.pos, q) <= mvr)
				return false;
		}
	return true;
}
float lethal_burst_hit(const Body& e, int d, int cdh, bool* cast)
{
	if (cast)
		*cast = false;
	if (!e.kit || !e.kit->valid)
		return d <= std::max(2, e.range + 1) ? e.str : 0.0f;
	const Kit& k = *e.kit;
	auto rdy = [&](int s) { return foe_ready(e, s, cdh); };
	const int R = e.range;
	const bool hit_stay = d <= R;
	const bool hit_walk = !k.ranged && d <= R + 1;
	float best = (hit_stay || hit_walk) ? e.str : 0.0f;
	bool bc = false;
	auto take = [&](float v, bool c)
	{
		if (v > best)
		{
			best = v;
			bc = c;
		}
	};
	if (rdy(k.slot_reset))
	{
		if (hit_stay || hit_walk)
			take(2.0f * e.str, false);
		else if (k.ranged && d <= R + 1)
			take(e.str, false);
	}
	if (rdy(k.slot_dash))
	{
		const int dr = static_cast<int>(k.dash_range);
		const float land = k.dash_mod > 0 ? k.dash_mod * e.foc : 0.0f;
		float v = 0;
		if (d <= (k.ranged ? R + dr : R + dr + 1))
			v += e.str;
		if (land > 0 && d <= dr + static_cast<int>(k.dash_radius) + 1)
			v += land;
		take(v, land > 0);
	}
	auto spell = [&](int s, float mod, float range, bool excl, float radius)
	{
		if (!rdy(s) || mod <= 0)
			return;
		const int rr = static_cast<int>(range + radius);
		if (excl)
		{
			if (d <= rr)
				take(mod * e.foc + (hit_stay ? e.str : 0.0f), true);
		}
		else if (d <= rr + 1)
			take(mod * e.foc + ((hit_stay || hit_walk) ? e.str : 0.0f), true);
	};
	spell(k.slot_dmg, k.dmg_mod, k.dmg_range, k.dmg_excl, 0.0f);
	spell(k.slot_cc, k.cc_mod, k.cc_range, k.cc_excl, 0.0f);
	spell(k.slot_aoe, k.aoe_mod, k.aoe_range, k.aoe_excl, k.aoe_radius);
	if (cast)
		*cast = bc && best > 0;
	if (mu::bits != 0 && best > 0 && mu::on(mu::B_PAIR | mu::B_FULL)) // the net pair factor
		return best * kit_rules::passive_mult(e) * mu::pair(e, W.me);
	return best * kit_rules::passive_mult(e);
}
// The lost-turn model (interactions.md:34, 36): a stun costs a foe exactly its next turn. When that is the only turn it has before
// my next one it is no threat in that window; when it has a further turn, that turn is a full one.
bool stun_takes_next_turn(const Body& e) { return e.stunned && (reach_burst_turns(e)) <= 1; }
int stunned_foe_reach(const Body& e, int reach) { return stun_takes_next_turn(e) ? 0 : reach; }
float stunned_foe_burst(const Body& e, float one_turn_burst) { return stun_takes_next_turn(e) ? 0.0f : one_turn_burst; }
namespace {
// the visible foes' summed next-turn damage on tile t (foes within 9 of me). `skip_kill`: leave out a foe my basic hit (+ a dash
// landing) kills from t (a kill dash). Foe e's next turn is the stunned one.
static bool foe_stunned_next_turn(const Body& e) { return stun_takes_next_turn(e); }
// a foe's two-turn hit depends only on the distance while its body and my acts stand (escape_dash_turn_slow's memo): each pair once.
static float lethal_burst_two_turn_hit(const Body& e, int d, float h)
{
	static int m_ps = -1, m_r = -1, m_act = -1;
	static std::uint32_t m_me = 0;
	static std::array<std::array<float, 12>, 12> m_v;
	const int act = (W.cast ? 1 : 0) + (W.attacked ? 2 : 0);
	if (m_ps != fg::pstamp || m_r != W.round || m_me != W.me.h || m_act != act)
	{
		m_ps = fg::pstamp;
		m_r = W.round;
		m_me = W.me.h;
		m_act = act;
		for (auto& row : m_v)
			row.fill(-1.0f);
	}
	const std::ptrdiff_t x = &e - W.enemies.data();
	float* slot = (x >= 0 && x < 12 && x < static_cast<std::ptrdiff_t>(W.enemies.size()) && d >= 0 && d < 12) ? &m_v[static_cast<std::size_t>(x)][static_cast<std::size_t>(d)] : nullptr;
	if (slot && *slot >= 0.0f)
		return *slot;
	const float v = e.stunned ? std::max(h, lethal_burst_hit(e, d, 1, nullptr)) : h > 0.0f ? foe_two_turn_damage(e, d, h) : d > 1 ? lethal_burst_hit(e, d - 1, 1, nullptr) : h;
	if (slot)
		*slot = v;
	return v;
}
} // namespace
float lethal_burst_damage_sum(vec2 t, int cdh, bool* cast, bool skip_kill = false)
{
	float sum = 0;
	bool any = false;
	const Kit* mk = W.me.kit;
	const float my_hit = W.me.str * kit_rules::passive_mult(W.me) + (skip_kill && mk && mk->dash_mod > 0 ? mk->dash_mod * W.me.foc * kit_rules::passive_mult(W.me) : 0.0f);
	for (const auto& e : W.enemies)
	{
		if (cheb(e.pos, W.me.pos) > 9)
			continue;
		if (foe_stunned_next_turn(e))
			continue;
		const int d = cheb(e.pos, t);
		const auto dash_kills = [&](const Body& b, int db) { return db <= W.me.range && KQ_SITE(16, kills(b, db, KQ_DASH), eff_hp(b) <= my_hit * mu::pair(W.me, b)); };
		if (skip_kill && dash_kills(e, d))
			continue;
		if (skip_kill && (ci_layer::type(e.type))) [[unlikely]]
		{
			const auto want = ci_layer::partner(e.type);
			bool dies = false;
			for (const auto& p : W.enemies)
				dies = dies || (p.type == want && dash_kills(p, cheb(p.pos, t))); // the dash kills its linked partner: it dies too (GameRules.md:442)
			if (dies)
				continue;
		}
		bool c = false;
		float h = lethal_burst_hit(e, d, cdh, &c);
		sum += h;
		any |= c;
		if (h <= 0.0f && e.kit && e.kit->valid && e.kit->splash)
			sum += splash_through_mate(e, t, cdh);
	}
	if (cast)
		*cast = any;
	return sum;
}
// X3I bits 2/4 (from b1825 PEM bits 4/8, X179 LBM1 + LBE1): lethal_burst_damage_sum(t, 0, nullptr) for the escape scan, with lethal_burst_hit memoised per
// (enemy index, distance) for the scan (memo: 144 floats, -1 = not yet; null = no memo) and the sum returned once it reaches stop_at
// (every term is >= 0, and the caller only tests v >= cap). Same terms in the same order: bit-identical below stop_at.
static float pem_damage_sum(vec2 t, float* memo, float stop_at)
{
	float sum = 0;
	std::size_t ei = 0;
	for (const auto& e : W.enemies)
	{
		const std::size_t idx = ei++;
		if (cheb(e.pos, W.me.pos) > 9)
			continue;
		if (foe_stunned_next_turn(e))
			continue;
		const int d = cheb(e.pos, t);
		float h;
		float* slot = (memo && idx < 12 && d >= 0 && d < 12) ? &memo[idx * 12 + static_cast<std::size_t>(d)] : nullptr;
		if (slot && *slot >= 0.0f)
			h = *slot;
		else
		{
			bool c = false;
			h = lethal_burst_hit(e, d, 0, &c);
			if (slot)
				*slot = h;
		}
		sum += h;
		if (h <= 0.0f && e.kit && e.kit->valid && e.kit->splash)
			sum += splash_through_mate(e, t, 0);
		if (sum >= stop_at)
			return sum;
	}
	return sum;
}
// FLR bit 8: my effective HP after the spawn heals me to full at my turn end (GR:153), before the foes act.
static float flr_healed_ehp()
{
	Body h = W.me;
	h.hp = h.maxhp;
	return mu::ehp(h);
}
float lb_cap() { return eff_hp(W.me) * static_cast<float>(LETHAL_BURST_TAB[2]) / 100.0f; }
// a dash landing on a tile where the foes' next-turn damage kills me, from a tile where it does not.
bool lethal_burst_landing_bad(vec2 p)
{
	if (!W.alive || !inb(p))
		return false;
	const float cap = lb_cap();
	const float bb13_stay = (W.on_spawn) ? flr_healed_ehp() * static_cast<float>(LETHAL_BURST_TAB[2]) / 100.0f : cap; // FLR bit 8 (BB13 bit 8 re-land): on spawn I heal to full first
	if (lethal_burst_damage_sum(W.me.pos, 0, nullptr) >= bb13_stay) // FLR bit 8
		return false; // already in a lethal spot: the landing is no worse a choice than staying
	const bool bad1 = lethal_burst_damage_sum(p, 0, nullptr, true) >= cap;
	return bad1;
}
namespace {
// The nearest healthy mate within LB_RALLY_R; (-1, -1): none, so an escape heads home.
static vec2 lethal_burst_rally_tile()
{
	const vec2 me = W.me.pos;
	vec2 rally{ -1, -1 };
	int rd = tune::LB_RALLY_R + 1;
	for (const auto& al : W.allies)
	{
		if (al.h == W.me.h || al.frac() < tune::LB_RALLY_FRAC || al.channeling())
			continue;
		const int d = cheb(al.pos, me);
		if (d < rd)
		{
			rd = d;
			rally = al.pos;
		}
	}
	return rally;
}
static inline int lb_rally_gap(vec2 t, vec2 rally) { return rally.x >= 0 ? cheb(t, rally) : mv::home_steps(t); }
// fn(tile) on each free step around me, when I can move.
template <class Fn>
static __attribute__((always_inline)) inline void lethal_burst_each_step(Fn&& fn)
{
	if (!W.can_move())
		return;
	const vec2 me = W.me.pos;
	for (int dx = -1; dx <= 1; ++dx)
		for (int dy = -1; dy <= 1; ++dy)
		{
			const vec2 t{ me.x + dx, me.y + dy };
			if ((dx != 0 || dy != 0) && inb(t) && mv::free_tile(t))
				fn(t);
		}
}
// FAC bit 32 KHK, caller read the flag: a landing-effect dash (Heart) onto t wakes another group's sleeping camp, as every other Heart
// dash site tests.
static __attribute__((noinline)) bool fac_khk_wakes(vec2 t)
{
	const Kit* k = W.me.kit;
	return k && k->dash_mod > 0 && camps::wakes_other_group(t, static_cast<int>(k->dash_radius), t, -1, 0.0f);
}
// fn(tile) on each free tile my dash lands on within r.
template <class Fn>
static __attribute__((always_inline)) inline void lethal_burst_each_dash(int r, Fn&& fn)
{
	const vec2 me = W.me.pos;
	for (int dx = -r; dx <= r; ++dx)
		for (int dy = -r; dy <= r; ++dy)
		{
			const vec2 t{ me.x + dx, me.y + dy };
			if (t == me || !inb(t) || !mv::free_tile(t) || (cheb(t, me) == 2 && !geom::dash_middle_tile_ok(me, t)))
				continue;
			if (fac_khk_wakes(t))
				continue; // FAC bit 32 KHK: a Heart landing beside a sleeping camp of another group wakes it
			fn(t);
		}
}
bool lethal_burst_escape_tile(float cap, vec2& out, bool& dash)
{
	const vec2 rally = lethal_burst_rally_tile();
	float best_s = 1e30f;
	float pem_memo[144]; // X3I bit 2: lethal_burst_hit per (enemy, distance) for this scan
	std::fill(pem_memo, pem_memo + 144, -1.0f);
	auto consider = [&](vec2 t)
	{
		const float v = pem_damage_sum(t, pem_memo, cap); // X3I bits 2/4
		if (v >= cap)
			return;
		const float sc = static_cast<float>(lb_rally_gap(t, rally)) * tune::LB_GAP_WEIGHT + v;
		if (sc < best_s)
		{
			best_s = sc;
			out = t;
		}
	};
	auto scan = [&]() -> bool
	{
		best_s = 1e30f;
		out = { -1, -1 };
		lethal_burst_each_step(consider);
		dash = false;
		if (out.x >= 0)
			return true;
		const Kit& k = *W.me.kit;
		if (k.slot_dash < 0 || !ready(k.slot_dash))
			return false;
		lethal_burst_each_dash(geom::dash_tiles(k), consider);
		dash = out.x >= 0;
		return dash;
	};
	return scan();
}
} // namespace
// a FIGHT spot where the foes' next turn kills me becomes a FLEE when a tile I reach is safe.
void lethal_burst_assess(Assessment& a)
{
	if (!((a.stance == FIGHT)))
		return;
	if (!W.alive || W.me.channeling() || !W.me.kit)
		return;
	const float cap = lb_cap();
	float cap_here = cap; // staying on my spawn tile, the heal at my turn end lands before the foes' hits
	if (W.on_spawn)
	{
		Body full = W.me;
		full.hp = full.maxhp;
		cap_here = eff_hp(full) * static_cast<float>(LETHAL_BURST_TAB[2]) / 100.0f;
	}
	[[maybe_unused]] const float lbs_base = cap_here;
	if (VB2_ON(8) && W.me.kit->slot_shield >= 0 && W.me.kit->slot_dash < 0 && ready(W.me.kit->slot_shield)) // v7xx VB2 bit 8 LBS1: a ready self-shield on the stay tile
		cap_here += mu::mult_shield_to_eff_hp(W.me, W.me.kit->shield_mod * W.me.foc) * static_cast<float>(LETHAL_BURST_TAB[2]) / 100.0f;
	bool c = false;
	const float here = lethal_burst_damage_sum(W.me.pos, 0, &c);
	VB2_CNT(8, c && here >= lbs_base && here < cap_here);
	if (here < cap_here || !c)
	{
		SPH_CNT(1, c && here >= cap);
		return;
	}
	vec2 t{ -1, -1 };
	bool dash = false;
	if (!lethal_burst_escape_tile(cap, t, dash))
		return; // no way out this turn: trading back beats a free burst
	NLOG("r%d slot %d lethal-burst %s -> FLEE to %d,%d%s hp %.0f\n", W.round, P.my_slot, a.stance == FIGHT ? "FIGHT" : "CALM", t.x, t.y, dash ? " dash" : "", W.me.hp);
	a.stance = FLEE;
	lethal_spot.round = W.round;
	lb_tile = t;
	lethal_spot.by_dash = dash;
}
namespace {
// The reach of an enhanced-attack reset stun (Marcella): the reset arms the next basic, so walk + armed hit (GameRules.md:662,
// :680).
static int fk1_armed_reach(const Body& e, const Kit& k) { return e.range + (k.ranged ? 0 : 1); }
} // namespace
} // namespace burst
} // namespace nova::combat
