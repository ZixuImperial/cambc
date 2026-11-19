// combat_camps.cc: Camps and camp casts.
#include "combat_internal.h"
namespace nova::combat {
namespace camps
{
namespace tune
{
inline constexpr float TANK_SHIELD_BELOW_FRAC = 0.92f; // a tank shields below this health; above it only with an awake attacker on it
inline constexpr float CAMP_SPELLS_FREE_BELOW = 0.5f;  // below this health the stun and nuke go on camps with an enemy about
inline constexpr float NUKE_KEPT_FROM_MOD = 2.0f;      // a nuke this strong stays for champions (Marcella's burst)
inline constexpr int CAMP_DASH_MIN_CAMPS = 2;          // a dash landing on camps must cover this many
}
namespace {
// once per perceive (on the first call), a compact copy of W.camps (position; group, or -1 when
// the camp, its group or the group's attackers are missing) with per-group chains in W.camps order. Per group, lazily: awake
// (any visible member awake), the strength of attackers whose nearest ally already brings them (amin <= lim, lim =
// min(reach, nearest foe)) and the attackers that count only when the call's me_after is within lim. Camp strengths are
// whole numbers (wolf 20 ... monolith 200), so the regrouped float sums are exact.
struct NwG
{
	int st = -1, head = -1, tail = -1, fin = -1;
	bool awake = false;
	float base = 0;
	int c0 = 0, c1 = 0;
	int mfin = -1; // this perceive's sum for one me_after
	vec2 mme{ -1, -1 };
	float mstr = 0;
};
struct NwCond
{
	vec2 pos{};
	int lim = 0;
	float str = 0;
};
std::vector<NwG> nwg;
std::vector<NwCond> nw_cond;
std::vector<vec2> nw_pos;
std::vector<int> nw_grp, nw_next;
int nw_cst = -1;
// The first call of a perceive takes the direct scan (most turns ask once); the second and later ones build the
// per-perceive table once and read it.
int nw_pst = -1, nw_cnt = 0;
void no_wake_build_cache()
{
	nw_cst = fg::pstamp;
	nw_cond.clear();
	if (nwg.size() != static_cast<std::size_t>(M.ng))
		nwg.assign(static_cast<std::size_t>(M.ng), NwG{});
	const std::size_t n = W.camps.size();
	nw_pos.resize(n);
	nw_grp.resize(n);
	nw_next.resize(n);
	for (std::size_t k = 0; k < n; ++k)
	{
		nw_grp[k] = -1;
		nw_next[k] = -1;
		const int ci = W.camps[k].ci;
		if (ci < 0 || static_cast<std::size_t>(ci) >= static_cast<std::size_t>(M.nc))
			continue;
		const auto& cp = M.camps[static_cast<std::size_t>(ci)];
		nw_pos[k] = cp.pos;
		const int g = cp.group;
		if (g < 0 || static_cast<std::size_t>(g) >= static_cast<std::size_t>(M.ng))
			continue;
		NwG& q = nwg[static_cast<std::size_t>(g)];
		if (q.st != fg::pstamp)
		{
			q.st = fg::pstamp;
			q.head = static_cast<int>(k);
			q.fin = -1;
		}
		else
			nw_next[static_cast<std::size_t>(q.tail)] = static_cast<int>(k);
		q.tail = static_cast<int>(k);
		if (M.groups[static_cast<std::size_t>(g)].n_att > 0)
			nw_grp[k] = g;
	}
}
const NwG& no_wake_group_state(int g)
{
	NwG& q = nwg[static_cast<std::size_t>(g)];
	if (q.fin == fg::pstamp)
		return q;
	q.fin = fg::pstamp;
	q.awake = false;
	q.base = 0;
	q.c0 = q.c1 = static_cast<int>(nw_cond.size());
	for (int k = q.head; k >= 0; k = nw_next[static_cast<std::size_t>(k)])
		if (W.camps[static_cast<std::size_t>(k)].awake)
		{
			q.awake = true;
			return q;
		}
	for (int k = q.head; k >= 0; k = nw_next[static_cast<std::size_t>(k)])
	{
		const auto& cp = M.camps[static_cast<std::size_t>(W.camps[static_cast<std::size_t>(k)].ci)];
		if (!cp.attacks())
			continue;
		int amin = 1 << 30;
		for (const auto& o : W.allies)
			amin = std::min(amin, cheb(cp.pos, o.pos));
		int emin = 1 << 20;
		for (const auto& o : W.enemies)
			emin = std::min(emin, cheb(cp.pos, o.pos));
		for (const auto& o : W.enemies_far)
			emin = std::min(emin, cheb(cp.pos, o.pos));
		const int lim = std::min(cp.reach, emin);
		if (amin <= lim)
			q.base += cp.str;
		else if (lim >= 0)
			nw_cond.push_back({ cp.pos, lim, cp.str });
	}
	q.c1 = static_cast<int>(nw_cond.size());
	return q;
}
} // namespace
static inline bool nw_ci_ok(int ci) { return ci >= 0 && static_cast<std::size_t>(ci) < static_cast<std::size_t>(M.nc); }
// Group g has attackers, and the caller does not skip it.
static inline bool group_has_attackers(int g, int skip_g)
{
	return g >= 0 && g != skip_g && static_cast<std::size_t>(g) < static_cast<std::size_t>(M.ng) && M.groups[static_cast<std::size_t>(g)].n_att > 0;
}
namespace {
// The spell kills a foe in the area: a wake is then worth it (kill_dmg 0 asks nothing).
static inline bool spell_kills_in_area(vec2 c, int r, float kill_dmg)
{
	if (kill_dmg > 0)
		for (const auto& e : W.enemies)
			if (cheb(e.pos, c) <= r && eff_hp(e) <= kill_dmg)
				return true;
	return false;
}
} // namespace
// The sleeping attacker cp counts toward a wake: one of us (me at me_after) is in its reach and no foe stands nearer it than we do.
static inline bool sleeping_attacker_counts(const CampI& cp, vec2 me_after)
{
	int dus = cheb(cp.pos, me_after);
	for (const auto& o : W.allies)
		dus = std::min(dus, cheb(cp.pos, o.pos));
	if (dus > cp.reach)
		return false;
	int den = 1 << 20;
	for (const auto& e : W.enemies)
		den = std::min(den, cheb(cp.pos, e.pos));
	for (const auto& e : W.enemies_far)
		den = std::min(den, cheb(cp.pos, e.pos));
	return dus <= den;
}
static inline bool nw_wakes_at(float str) { return str >= static_cast<float>(NW_STR); }
namespace {
bool wakes_other_group_cached(vec2 c, int r, vec2 me_after, int skip_g, float kill_dmg)
{
	if (nw_cst != fg::pstamp || nw_grp.size() != W.camps.size() || nwg.size() != static_cast<std::size_t>(M.ng))
		no_wake_build_cache();
	NwGroups gl;
	const std::size_t n = nw_grp.size();
	bool nwm_win = false; // the (2r+1)^2 tiles through M.camp_index / W.camp_slot; the answer is an OR over the groups
	if (r >= 0 && r <= 3 && !M.camp_at.empty())
	{
		nwm_win = true;
		for (int y = c.y - r; y <= c.y + r && nwm_win; ++y)
			for (int x = c.x - r; x <= c.x + r; ++x)
			{
				const int ci = M.camp_index(vec2{ x, y });
				if (ci < 0 || static_cast<std::size_t>(ci) >= W.camp_slot.size())
					continue;
				const int k = W.camp_slot[static_cast<std::size_t>(ci)];
				if (k < 0 || static_cast<std::size_t>(k) >= n || W.camps[static_cast<std::size_t>(k)].ci != ci)
					continue;
				const int g = nw_grp[static_cast<std::size_t>(k)];
				if (g < 0 || g == skip_g || gl.has(g))
					continue;
				if (gl.full())
				{
					nwm_win = false; // 7+ groups: the direct scan decides which six count
					gl.ng = 0;
					break;
				}
				gl.push(g);
			}
	}
	if (!nwm_win)
		for (std::size_t k = 0; k < n; ++k)
		{
			const int g = nw_grp[k];
			if (g < 0 || g == skip_g || cheb(nw_pos[k], c) > r)
				continue;
			gl.add(g);
		}
	if (gl.ng == 0 || spell_kills_in_area(c, r, kill_dmg))
		return false;
	for (int i = 0; i < gl.ng; ++i)
	{
		const NwG& q = no_wake_group_state(gl.gs[static_cast<std::size_t>(i)]);
		if (q.awake)
			continue;
		NwG& qm = nwg[static_cast<std::size_t>(gl.gs[static_cast<std::size_t>(i)])];
		if (qm.mfin == fg::pstamp && qm.mme == me_after) // same perceive, same me_after
		{
			if (nw_wakes_at(qm.mstr))
				return true;
			continue;
		}
		float str = q.base;
		for (int j = q.c0; j < q.c1; ++j)
		{
			const NwCond& e = nw_cond[static_cast<std::size_t>(j)];
			if (cheb(e.pos, me_after) <= e.lim)
				str += e.str;
		}
		qm.mfin = fg::pstamp;
		qm.mme = me_after;
		qm.mstr = str;
		if (nw_wakes_at(str))
			return true;
	}
	return false;
}
bool no_wake_repeat_call()
{
	if (nw_pst != fg::pstamp)
	{
		nw_pst = fg::pstamp;
		nw_cnt = 0;
	}
	return ++nw_cnt >= 2;
}
} // namespace
bool wakes_other_group(vec2 c, int r, vec2 me_after, int skip_g, float kill_dmg)
{
	if (no_wake_repeat_call() || W.camps.size() >= static_cast<std::size_t>(FFG_NWM_CAMPS)) // a heavy view skips the direct scan
		return wakes_other_group_cached(c, r, me_after, skip_g, kill_dmg);
	NwGroups gl;
	for (const auto& vc : W.camps)
	{
		if (!nw_ci_ok(vc.ci))
			continue;
		const auto& cp = M.camps[static_cast<std::size_t>(vc.ci)];
		if (cheb(cp.pos, c) <= r && group_has_attackers(cp.group, skip_g))
			gl.add(cp.group);
	}
	if (gl.ng == 0 || spell_kills_in_area(c, r, kill_dmg))
		return false;
	for (int i = 0; i < gl.ng; ++i)
	{
		const int g = gl.gs[static_cast<std::size_t>(i)];
		bool awake = false;
		float str = 0;
		for (const auto& vc : W.camps)
		{
			if (!nw_ci_ok(vc.ci))
				continue;
			const auto& cp = M.camps[static_cast<std::size_t>(vc.ci)];
			if (cp.group != g)
				continue;
			if (vc.awake)
			{
				awake = true;
				break;
			}
			if (cp.attacks() && sleeping_attacker_counts(cp, me_after))
				str += cp.str;
		}
		if (!awake && nw_wakes_at(str))
			return true;
	}
	return false;
}
// Our Vendetta's kill (champion or camp) sets both her cooldowns to 0 at once. After any
// hit of hers, re-read them (refresh_cooldowns: the engine knows the kill; our bare-Str kill guesses miss Monster/Collectors).
static inline bool cdm_vkr() { return false; }
// an area stun whose square holds only stun-immune foes (a lone Marcella) is held unless it kills one of
// them or no stunnable foe is visible within 8 (it keeps the stun for one that loses its turn).
static bool hold_area_stun_on_immune_foes(vec2 t, int r, float dmg)
{
	bool any = false;
	for (const auto& e : W.enemies)
		if (cheb(e.pos, t) <= r)
		{
			if (!marcella_layer::fight_stun_wasted(e) || eff_hp(e) <= dmg)
				return false;
			any = true;
		}
	if (!any)
		return false;
	for (const auto& e : W.enemies)
		if (marcella_layer::fight_stun_holds(e) && !e.stunned && cheb(e.pos, W.me.pos) <= 8)
			return true;
	return false;
}
// a foe stands within my basic range.
static bool foe_in_basic_range()
{
	for (const auto& e : W.enemies)
		if (cheb(e.pos, W.me.pos) <= W.me.range)
			return true;
	return false;
}
// this camp lives right now (engine read; out of sight counts as alive: the caller's own view stands).
static bool camp_alive_in_engine(int ci)
{
	std::uint32_t v = 1;
	if (cambc::detail::sdk_camp_state(M.camps[static_cast<std::size_t>(ci)].handle, &v) != 0)
		return true;
	return v != 0;
}
namespace {
// The living camp in basic reach after `skip` died: its group first, then an awake or harmless one, lowest HP first.
static int next_camp_after_kill(int skip)
{
	if (varg_layer::route_skip_rtg())
		return -1; // Varg: a splash may wake a neighbour (next_camp_in_reach's own scoring)
	const int gi = M.camps[static_cast<std::size_t>(skip)].group;
	int best = -1;
	float best_s = 1e9f;
	for (const auto& vc : W.camps)
	{
		const auto& c = M.camps[static_cast<std::size_t>(vc.ci)];
		if (vc.ci == skip || cheb(W.me.pos, c.pos) > W.me.range)
			continue;
		if (c.group != gi && !vc.awake && c.group >= 0 && M.groups[static_cast<std::size_t>(c.group)].n_att > 0)
			continue;
		const float s = vc.hp + (c.group == gi ? 0.0f : 5000.0f);
		if (s < best_s && camp_alive_in_engine(vc.ci))
		{
			best_s = s;
			best = vc.ci;
		}
	}
	return best;
}
} // namespace
// Re-read my cooldowns from the engine (a kill resets Vendetta's mid-turn; the local copy would say "not ready").
void refresh_cooldowns()
{
	for (int s = 0; s < 2; ++s)
	{
		std::int32_t cd = 0;
		if (cambc::detail::sdk_champion_cooldown(W.me.h, static_cast<std::uint32_t>(s), &cd) == 0)
			W.cd[static_cast<std::size_t>(s)] = cd;
	}
}
namespace {
// Living visible camp in basic-attack reach other than `skip`: the one closest to dying, same group first.
int next_camp_in_reach(int skip)
{
	const int gi = skip >= 0 ? M.camps[static_cast<std::size_t>(skip)].group : -1;
	int best = -1;
	float best_s = 1e9f;
	for (const auto& vc : W.camps)
	{
		if (vc.ci == skip)
			continue;
		const auto& c = M.camps[static_cast<std::size_t>(vc.ci)];
		if (cheb(W.me.pos, c.pos) > W.me.range)
			continue;
		// Never the second hit on a sleeping camp of another group with attackers: damage wakes the whole group
		// (a reset hit on a monolith beside a gold cluster woke a 20,000-HP, 200-strength camp that killed two bodies in 9 rounds).
		if (c.group != gi && !vc.awake && c.group >= 0 && M.groups[static_cast<std::size_t>(c.group)].n_att > 0)
			continue;
		float s = vc.hp + (c.group == gi ? 0.0f : 5000.0f);
		// PASSIVE Varg: the reset's second hit also goes where the splash reaches the most living camps (never a
		// sleeping other group's).
		if (varg_layer::reset_splash_aim())
			for (const auto& v2 : W.camps)
			{
				if (v2.ci == vc.ci || v2.ci == skip || cheb(M.camps[static_cast<std::size_t>(v2.ci)].pos, c.pos) > 1)
					continue;
				if (M.camps[static_cast<std::size_t>(v2.ci)].group == c.group)
					s -= PASSIVE_VARG_NBR;
				else if (!v2.awake)
					s += 50000.0f;
			}
		if (s < best_s)
		{
			best_s = s;
			best = vc.ci;
		}
	}
	return best;
}
// does a visible foe make the free hit unsafe? (bit 0 of the table off: always)
__attribute__((noinline)) bool prestep_blocked(vec2 dest)
{
	const int my_reach = foe_next_turn_reach(W.me);
	const int eta_min = FREE_HIT_THREAT_TAB[2];
	for (const auto& e : W.enemies)
	{
		if (!e.kit || !e.kit->valid)
			return true;
		if (cheb(e.pos, W.me.pos) <= my_reach)
			return true; // I might hit it this turn
		const int eta = 1 + std::max(0, cheb(e.pos, dest) - foe_next_turn_reach(e));
		if (eta < eta_min)
			return true;
	}
	return false;
}
__attribute__((noinline)) void prestep_hit_before_move_slow(vec2 dest)
{
	const int r = std::max(1, W.me.range);
	int best = -1;
	float best_hp = 1e9f;
	for (const auto& vc : W.camps)
	{
		if (vc.ci < 0 || vc.ci >= M.nc || vc.hp <= 0.0f)
			continue;
		const auto& c = M.camps[static_cast<std::size_t>(vc.ci)];
		if (cheb(c.pos, dest) <= r)
			return;
		if (!vc.awake || cheb(c.pos, W.me.pos) > r || (varg_layer::prestep_splash() && !prestep_splash_ok(vc.ci)) || prestep_hit_wakes_group(vc.ci))
			continue;
		if (vc.hp < best_hp)
		{
			best_hp = vc.hp;
			best = vc.ci;
		}
	}
	if (best >= 0)
		prestep_hit_camp(best);
}
static bool foe_on_group_camp(const Body& e, int gi)
{
	if (gi < 0)
		return true;
	for (int ci : M.groups[static_cast<std::size_t>(gi)].members)
		if (M.camps[static_cast<std::size_t>(ci)].pos == e.pos)
			return true;
	return false;
}
// free_cast's target filters.
static bool free_cast_target_ok(const Body& e)
{
	return !bbget(M.enemy_spawn, e.pos) && !(ren_layer::kills_me(e));
}
// The weakest foe of the group within range that free_cast may hit and ok passes.
template <class Ok>
static const Body* weakest_foe_in_range_of_group(int range, int gi, Ok&& ok)
{
	const Body* best = nullptr;
	for (const auto& e : W.enemies)
		if (!foe_model::unreachable(e) && cheb(e.pos, W.me.pos) <= range && foe_on_group_camp(e, gi) && ok(e) && free_cast_target_ok(e) && (!best || eff_hp(e) < eff_hp(*best)))
			best = &e;
	return best;
}
// after a basic hit this turn, the area spell is cast only if a camp still lives within the radius of the tile:
// W.camps is the turn-start view, so the camp the hit just killed still scored there and the cast landed on nothing.
static bool area_spell_camp_alive(vec2 t, int r)
{
	for (const auto& c : W.camps)
		if (cheb(M.camps[static_cast<std::size_t>(c.ci)].pos, t) <= r && camp_alive_in_engine(c.ci))
			return true;
	return false;
}
// after camp_abilities' landing, the basic hit on the focus if it lives in reach, else on the lowest-HP living
// camp of the focus group in reach (the landing woke the group; never another group's camp).
static void landing_hit_camp(int focus_ci)
{
	if (W.attacked || !W.can_attack())
		return;
	const int gi = M.camps[static_cast<std::size_t>(focus_ci)].group;
	int ci = -1;
	if (cheb(M.camps[static_cast<std::size_t>(focus_ci)].pos, W.me.pos) <= W.me.range && camp_alive_in_engine(focus_ci))
		ci = focus_ci;
	else
	{
		float bh = 1e9f;
		for (const auto& vc : W.camps)
		{
			if (vc.ci < 0 || static_cast<std::size_t>(vc.ci) >= static_cast<std::size_t>(M.nc))
				continue;
			const auto& c = M.camps[static_cast<std::size_t>(vc.ci)];
			if (c.group != gi || cheb(c.pos, W.me.pos) > W.me.range || vc.hp >= bh || !camp_alive_in_engine(vc.ci))
				continue;
			bh = vc.hp;
			ci = vc.ci;
		}
	}
	if (ci >= 0)
		attack_camp(ci);
}
// true when the focus group has no living attacker and the area spell (cast now, on the tile camp_abilities'
// area block picks) removes more HP than the cc slot on the focus.
static bool area_before_cc(const Kit& k, int focus_ci)
{
	if (k.slot_aoe < 0 || !ready(k.slot_aoe) || k.aoe_mod <= 0)
		return false;
	const int gi = M.camps[static_cast<std::size_t>(focus_ci)].group;
	if (gi < 0 || gi >= M.ng)
		return false;
	for (int ci : M.groups[static_cast<std::size_t>(gi)].members)
	{
		const auto& c = M.camps[static_cast<std::size_t>(ci)];
		if (!c.attacks())
			continue;
		bool seen = false, alive = false;
		for (const auto& vc : W.camps)
			if (vc.ci == ci)
			{
				seen = true;
				alive = vc.hp > 0;
			}
		if (alive || !seen)
			return false; // a living (or unseen) attacker: a stun can save a hit
	}
	float fhp = -1;
	for (const auto& vc : W.camps)
		if (vc.ci == focus_ci)
			fhp = vc.hp;
	if (fhp <= 0)
		return false;
	const int r = std::max(0, static_cast<int>(k.aoe_radius));
	AreaGrid grid;
	grid.build(gi, r);
	int n = 0;
	const vec2 at = grid.best(W.me.pos, static_cast<int>(k.aoe_range), false, &n, gi, r);
	if (at.x < 0 || (W.attacked && !area_spell_camp_alive(at, r)))
		return false;
	const float pm = kit_rules::passive_mult(W.me);
	const float ad = k.aoe_mod * W.me.foc * pm, cd = k.cc_mod * W.me.foc * pm;
	float av = 0;
	for (const auto& vc : W.camps)
	{
		const auto& c = M.camps[static_cast<std::size_t>(vc.ci)];
		if (c.group == gi && vc.hp > 0 && cheb(c.pos, at) <= r)
			av += std::min(ad, static_cast<float>(vc.hp));
	}
	const bool yes = av > std::min(cd, fhp);
	bh65c_n += yes ? 1 : 0;
	return yes;
}
// An awake attacker has me in its reach.
static __attribute__((always_inline)) inline bool camp_abilities_attacked()
{
	for (const auto& vc : W.camps)
	{
		const auto& c = M.camps[static_cast<std::size_t>(vc.ci)];
		if (vc.awake && c.attacks() && cheb(c.pos, W.me.pos) <= c.reach)
			return true;
	}
	return false;
}
// The focus died this turn: the healthiest living camp of its group within range; -1 when there is none.
static __attribute__((always_inline)) inline int camp_abilities_next_camp(int focus_ci, int range)
{
	const int gi = M.camps[static_cast<std::size_t>(focus_ci)].group;
	int best = -1;
	float nh = 0;
	for (const auto& vc : W.camps)
		if (cast::camp_ci_ok(vc.ci) && vc.ci != focus_ci && M.camps[static_cast<std::size_t>(vc.ci)].group == gi && vc.hp > nh &&
			cheb(M.camps[static_cast<std::size_t>(vc.ci)].pos, W.me.pos) <= range && camp_alive_in_engine(vc.ci))
		{
			nh = vc.hp;
			best = vc.ci;
		}
	return best;
}
// Stun the strongest awake attacker in reach of the cast: it cancels that monster's next hit. Cassi's nuke on the focus goes before
// the camp stun (one cast a turn).
static __attribute__((always_inline)) inline void camp_abilities_stun(const Kit& k, int focus_ci)
{
	if (!k.cc_on_camps || !slot_up(k.slot_cc))
		return;
	const int cc_r = static_cast<int>(k.cc_range);
	int best = -1;
	float best_str = 0;
	const bool ccl = (W.attacked || W.cast); // only after my own hit or cast
	for (const auto& vc : W.camps)
	{
		const auto& c = M.camps[static_cast<std::size_t>(vc.ci)];
		if (!vc.awake || !c.attacks() || cheb(c.pos, W.me.pos) > cc_r)
			continue;
		if (c.str > best_str && !(ccl && !camp_alive_in_engine(vc.ci)))
		{
			best_str = c.str;
			best = vc.ci;
		}
	}
	if (best < 0 && k.cc_mod > 0 && focus_ci >= 0 && cheb(M.camps[static_cast<std::size_t>(focus_ci)].pos, W.me.pos) <= cc_r)
		best = focus_ci;
	if (ccl && best >= 0 && best == focus_ci && !camp_alive_in_engine(focus_ci))
		best = camp_abilities_next_camp(focus_ci, cc_r);
	if (best >= 0 && best == focus_ci && area_before_cc(k, focus_ci))
		best = -1;
	if (best >= 0)
		cast_on_camp(k.slot_cc, best);
}
// The nuke on the focus, or on the next camp of its group when this turn's hit killed the focus.
static __attribute__((always_inline)) inline void camp_abilities_nuke(const Kit& k, int focus_ci)
{
	const int dmg_r = static_cast<int>(k.dmg_range);
	if (!camp_alive_in_engine(focus_ci))
	{
		const int nk = camp_abilities_next_camp(focus_ci, dmg_r);
		if (nk >= 0)
			cast_on_camp(k.slot_dmg, nk);
	}
	else if (cheb(M.camps[static_cast<std::size_t>(focus_ci)].pos, W.me.pos) <= dmg_r)
		cast_on_camp(k.slot_dmg, focus_ci);
}
// A dash landing on two or more camps of the group (a kit whose landing is not heart_dash_try's). A refused tile is now blocked (cast_via_sdk):
// the next landing that still hits two camps, once.
static __attribute__((always_inline)) inline void camp_abilities_dash(const Kit& k, AreaGrid& grid)
{
	const int reach = cast::heart_dash_reach(k);
	int n = 0;
	const vec2 best = grid.best(W.me.pos, reach, true, &n);
	if (best.x < 0 || n < tune::CAMP_DASH_MIN_CAMPS || cast_at(k.slot_dash, best) || !ready(k.slot_dash))
		return;
	int n2 = 0;
	const vec2 b2 = grid.best(W.me.pos, reach, true, &n2);
	if (b2.x >= 0 && !(b2 == best) && n2 >= tune::CAMP_DASH_MIN_CAMPS)
		cast_at(k.slot_dash, b2);
}
// Area hit and landing: the tile that covers the most living camps of the focus group (clusters die to one area hit or one landing
// each, so a patch is cleared in a turn or two). PASSIVE Stellar: never onto another group's sleeping attackers (damage wakes a whole group).
static __attribute__((always_inline)) inline void camp_abilities_area(const Kit& k, int focus_ci, bool tanking)
{
	const bool aoe_ok = slot_up(k.slot_aoe);
	const bool dash_ok = k.dash_mod > 0 && slot_up(k.slot_dash) && tanking && !k.dash_stun; // Heart's landing is heart_dash_try's
	if ((!aoe_ok && !dash_ok) || focus_ci < 0)
		return;
	const int gi = M.camps[static_cast<std::size_t>(focus_ci)].group;
	const int r = aoe_ok ? static_cast<int>(k.aoe_radius) : static_cast<int>(k.dash_radius);
	const int r0 = std::max(0, r);
	AreaGrid grid;
	grid.build(gi, r0);
	if (aoe_ok)
	{
		int n = 0;
		const vec2 best = grid.best(W.me.pos, static_cast<int>(k.aoe_range), false, &n, gi, r0);
		if (best.x >= 0 && !(W.attacked && !area_spell_camp_alive(best, r0)))
			cast_at(k.slot_aoe, best);
	}
	if (dash_ok && !W.cast)
	{
		if (static_cast<int>(k.dash_radius) != r)
			grid.build(gi, std::max(0, static_cast<int>(k.dash_radius)));
		camp_abilities_dash(k, grid);
	}
}
} // namespace
} // namespace camps
namespace {
// Effective HP: health / Durability's .9; shields absorb the reduced hit.
float eff_hp(const Body& b) { return mu::ehp(b); }
} // namespace
bool attack_camp(int ci)
{
	if (ci < 0)
		return false;
	const auto& c = M.camps[static_cast<std::size_t>(ci)];
	if (cheb(W.me.pos, c.pos) > W.me.range)
		return false;
	const bool hd = heart_dash_try(c.pos); // the landing first (it keeps the camp in range)
	if (cheb(W.me.pos, c.pos) > W.me.range)
		return hd;
	if (W.can_attack() && !camps::camp_alive_in_engine(ci))
	{
		const int nx = camps::next_camp_after_kill(ci);
		return (nx >= 0 && cast::attack_via_sdk(KIND_CAMP, M.camps[static_cast<std::size_t>(nx)].handle)) || hd;
	}
	return cast::attack_via_sdk(KIND_CAMP, c.handle) || hd;
}
bool camp_hit_plain(int ci)
{
	return cast::attack_via_sdk(KIND_CAMP, M.camps[static_cast<std::size_t>(ci)].handle);
}
bool cast_on_champion(int slot, const Body& b) { return cast::cast_via_sdk(slot, KIND_CHAMPION, b.h, { -1, -1 }); }
bool cast_on_camp(int slot, int ci)
{
	if (ci < 0)
		return false;
	return cast::cast_via_sdk(slot, KIND_CAMP, M.camps[static_cast<std::size_t>(ci)].handle, { -1, -1 });
}
// one plain hit; a Vendetta kill refunds her cooldowns.
bool prestep_hit_camp(int ci)
{
	const VisCamp* vc = W.camp_by_index(ci);
	const float hp0 = vc ? vc->hp : 1e9f;
	if (!cast::attack_via_sdk(KIND_CAMP, M.camps[static_cast<std::size_t>(ci)].handle))
		return false;
	if (vendetta_layer::camp_kill_refresh() && (camps::cdm_vkr() || hp0 <= (W.me.str))) // the engine knows the kill
		camps::refresh_cooldowns();
	return true;
}
bool mfb_free_attack() { return cast::free_attack(); }
bool prestep_splash_ok(int ci);
// a hit on camp ci wakes a sleeping attacker of its group that has me in reach (damage wakes the group, GameRules.md:208).
bool prestep_hit_wakes_group(int ci)
{
	const int gi = M.camps[static_cast<std::size_t>(ci)].group;
	for (const auto& v2 : W.camps)
	{
		if (v2.awake || v2.ci < 0 || v2.ci == ci)
			continue;
		const auto& c2 = M.camps[static_cast<std::size_t>(v2.ci)];
		if (c2.group == gi && c2.attacks() && cheb(c2.pos, W.me.pos) <= c2.reach)
			return true;
	}
	return false;
}
__attribute__((always_inline)) void prestep_hit_before_move(vec2 dest)
{
	if (W.attacked || !W.alive || !W.me.kit || W.me.kit->ranged || W.me.channeling() || (!W.enemies.empty() && camps::prestep_blocked(dest)) || !W.can_attack())
		return;
	camps::prestep_hit_before_move_slow(dest);
}
// Basic attack on a camp, with the attack reset for a second hit. A kill with Vendetta resets her cooldowns, so on a
// cluster patch (120 HP, attack + reset = 2 hits) she kills one cluster per turn and the reset is ready again the next
// turn; when the first hit already kills, the reset goes to the next camp in reach.
bool hit_camp(int ci)
{
	if (ci < 0)
		return false;
	const Kit& k = *W.me.kit;
	const auto& c = M.camps[static_cast<std::size_t>(ci)];
	if (cheb(W.me.pos, c.pos) > W.me.range)
		return false;
	if (!W.can_attack() && W.moved && k.slot_reset >= 0 && ready(k.slot_reset))
		cast_self(k.slot_reset);
	const VisCamp* vc = W.camp_by_index(ci);
	const float hp0 = vc ? vc->hp : 1e9f;
	if (!attack_camp(ci))
		return false;
	const bool dead = !camps::camp_alive_in_engine(ci);
	if ((dead || camps::cdm_vkr()) && vendetta_layer::camp_kill_reset(k))
		camps::refresh_cooldowns();
	if (k.slot_reset < 0 || !ready(k.slot_reset))
		return true;
	if (!dead)
	{
		// the second hit can kill too, and Vendetta's kill refunds every cooldown; re-read them, or the
		// refunded reset and dash look spent for the rest of the turn.
		if (cast_self(k.slot_reset) && attack_camp(ci) && vendetta_layer::camp_kill_reset(k)) // re-read on any second hit
			camps::refresh_cooldowns();
		return true;
	}
	const int next = camps::next_camp_in_reach(ci);
	if (next >= 0 && cast_self(k.slot_reset))
	{
		const VisCamp* nv = W.camp_by_index(next);
		const float hp1 = nv ? nv->hp : 1e9f;
		if (attack_camp(next) && vendetta_layer::camp_kill_reset(k)) // re-read on any hit
			camps::refresh_cooldowns();
	}
	return true;
}
bool cast_damage_spell_on_foe(int gi)
{
	const Kit& k = *W.me.kit;
	if (W.cast || W.me.channeling() || W.enemies.empty())
		return false;
	if (k.slot_dmg >= 0 && k.dmg_mod > 0 && ready(k.slot_dmg))
	{
		const Body* best = camps::weakest_foe_in_range_of_group(static_cast<int>(k.dmg_range), gi, [](const Body&) { return true; });
		if (best && cast_on_champion(k.slot_dmg, *best))
			return true;
	}
	if (k.slot_cc >= 0 && k.cc_mod > 0 && ready(k.slot_cc))
	{
		const Body* best = camps::weakest_foe_in_range_of_group(static_cast<int>(k.cc_range), gi, [](const Body& e) { return !marcella_layer::fight_stun_wasted(e); });
		if (best && cast_on_champion(k.slot_cc, *best))
			return true;
	}
	if (k.slot_aoe >= 0 && k.aoe_mod > 0 && ready(k.slot_aoe))
	{
		int bn = 0;
		const vec2 bt = cast::aoe_best_tile(static_cast<int>(k.aoe_range), static_cast<int>(k.aoe_radius), bn, [&](const Body& e) { return camps::foe_on_group_camp(e, gi); }, [](vec2) { return true; });
		if (bn >= 1 && cast_at(k.slot_aoe, bt))
			return true;
	}
	return false;
}
void camp_abilities(int focus_ci, bool tanking)
{
	const Kit& k = *W.me.kit;
	try_heal();
	// a full-HP tank shields too, while an awake attacker has me in its reach (the shield is effective HP)
	const bool in_reach = tanking && W.me.frac() >= camps::tune::TANK_SHIELD_BELOW_FRAC && slot_up(k.slot_shield) && camps::camp_abilities_attacked();
	if (k.dash_stun && cast::camp_ci_ok(focus_ci) && heart_dash_try(M.camps[static_cast<std::size_t>(focus_ci)].pos)) // the landing before the shield
		camps::landing_hit_camp(focus_ci); // the basic hit after the landing
	// With an enemy champion seen lately the camp shield is kept for the champion fight (as the stun and nuke below), unless I am below
	// CAMP_SPELLS_FREE_BELOW.
	if (tanking && slot_up(k.slot_shield) && (W.me.frac() < camps::tune::TANK_SHIELD_BELOW_FRAC || in_reach))
		cast_self(k.slot_shield);
	// With an enemy seen within 10 in the last 8 rounds, every kit keeps its stun and single-target nuke for champions, unless it is
	// below half health. The carrier stacks from her spells on camps: she keeps her slot 0 only with an enemy champion known within
	// PC_SPELL_R. The hold pays only with a foe near; not Prism (her spell-free rule) nor Cassi / Issac.
	const bool cu_free = cast_uptime_walk_in_free();
	const bool spell_hold = !cu_free && !seen.empty() && W.me.frac() >= camps::tune::CAMP_SPELLS_FREE_BELOW &&
		!(prism_layer::fight_spell_free(k) && prism::spell_free());
	if (!spell_hold)
		camps::camp_abilities_stun(k, focus_ci);
	// PASSIVE Stellar / Cassi: the single-target nuke is kept for champions (else it is on cooldown at first contact).
	const bool hold_nuke = !cu_free && !seen.empty() && k.dmg_mod >= camps::tune::NUKE_KEPT_FROM_MOD;
	if (focus_ci >= 0 && k.dmg_on_camps && slot_up(k.slot_dmg) && !hold_nuke && !spell_hold)
		camps::camp_abilities_nuke(k, focus_ci);
	camps::camp_abilities_area(k, focus_ci, tanking);
}
} // namespace nova::combat
