// combat_flee.cc: The FLEE stance, retreat and refuge.
#include "combat_internal.h"
namespace nova::combat {
namespace flee_turn
{
namespace tune
{
// The numbers of the flee family: dash_away, observe, step_out_of_reach, the parting stuns, retreat_to_spawn_to_heal,
// lethal_burst_flee_turn, flee, continue_retreat. The ally a flee falls back on.
inline constexpr int RALLY_LIMIT = 13; // it stands closer than this
inline constexpr int RALLY_MIN_D = 2; // and at least this far (next to me it is no rally)
inline constexpr float RALLY_MIN_FRAC = 0.5f; // and is healthier than this
inline constexpr int RETREAT_HURT_ROUNDS = 3; // rounds a fresh hit on the way renews the retreat for
inline constexpr int RETREAT_MARGIN = 3; // it walks on while within this of the remembered zones
inline constexpr int FLEE_RETREAT_MARGIN = 2; // flee's own retreat step keeps this far outside the zones
// step_out_of_reach's tile score (lowest wins).
inline constexpr int STEP_RALLY_WEIGHT = 4; // per tile from the rally (with no rally: 1 per step from home)
inline constexpr int STEP_ROOM_CAP = 6; // room from the nearest foe counts up to this
// A parting stun holds the gap only with no remembered foe within max(its reach, this) + 1.
inline constexpr int PARTING_HIDDEN_MIN_REACH = 2;
// flee, out of every reach: the nuke and the shot that come before the walk.
inline constexpr float NUKE_MIN_FRAC = 0.3f;
inline constexpr int SHOT_MIN_RANGE = 3;
inline constexpr float SHOT_MIN_FRAC = 0.5f;
inline constexpr int SHOT_MAX_GEMS = 40; // a body carrying this many walks instead
}
namespace {
// The foes a parting stun answers to. A stunned chaser loses its next turn (no hit, no step), so the gap holds.
struct PartingFoes
{
	std::vector<const Body*> reach_me; // not stunned, they reach me next turn
	std::vector<const Body*> soon; // a step short of reaching me next turn
	bool stunned_chaser = false; // a foe in reach is stunned already
};
// What the pieces of one flee() share.
struct FleeCtx
{
	const Assessment& a;
	const Kit& k;
	std::vector<mv::Threat>& zones;
	std::size_t foe_zones; // the foes' zones come first, camp zones after
	bool acted;
};
} // namespace
// The weakest enemy that passes keep (the first on a tie); nullptr: none.
template <class Keep> static __attribute__((always_inline)) inline const Body* weakest_foe_where(Keep keep)
{
	const Body* best = nullptr;
	for (const auto& e : W.enemies)
		if (keep(e) && (!best || eff_hp(e) < eff_hp(*best)))
			best = &e;
	return best;
}
static __attribute__((always_inline)) inline bool in_my_range(const Body& e) { return cheb(e.pos, W.me.pos) <= W.me.range; }
namespace {
// The nearest ally a flee can fall back on (the RALLY_* tuning), outside the zones. None, or a rich carrier (it rallies on home): x
// < 0.
static vec2 rally_ally(const std::vector<mv::Threat>& zones)
{
	vec2 rally{ -1, -1 };
	if (FARM_RICH_RICH_ON())
		return rally;
	int best = tune::RALLY_LIMIT;
	for (const auto& al : W.allies)
	{
		const int d = cheb(al.pos, W.me.pos);
		if (d < best && d >= tune::RALLY_MIN_D && !al.channeling() && al.frac() > tune::RALLY_MIN_FRAC && !mv::in_threat(zones, al.pos))
		{
			best = d;
			rally = al.pos;
		}
	}
	return rally;
}
// A tile a flee step may end on: free, outside every zone and not vetoed by a foe's danger.
static __attribute__((always_inline)) inline bool flee_tile_out(const Assessment& a, const std::vector<mv::Threat>& zones, vec2 t)
{
	return mv::free_tile(t) && !mv::in_threat(zones, t) && geom::danger_veto(a, t) <= 0;
}
// step_out_of_reach's score of tile t (lowest wins): near the rally (with none, home), room from the nearest foe as a tie-break.
static __attribute__((always_inline)) inline int step_score(const Assessment& a, vec2 t, vec2 rally)
{
	int sc = rally.x >= 0 ? tune::STEP_RALLY_WEIGHT * cheb(t, rally) : mv::home_steps(t);
	int room = tune::STEP_ROOM_CAP;
	for (const auto& f : a.foes)
		room = std::min(room, cheb(t, f.pos));
	sc -= room;
	return sc;
}
static vec2 flee_rally(const std::vector<mv::Threat>& zones); // below (FLR bit 16)
// Step to an adjacent tile outside every danger zone, preferring the flee rally (with none, home). True if moved.
bool step_out_of_reach(const Assessment& a, const std::vector<mv::Threat>& zones)
{
	AF_CHECK();
	if (!W.can_move())
		return false;
	const vec2 rally = flee_rally(zones); // FLR bit 16 FLD1: home near my spawn, as every flee step
	vec2 best{ -1, -1 };
	int best_s = BIG;
	for (const vec2 dd : DIRS)
	{
		const vec2 t = W.me.pos + dd;
		if (!flee_tile_out(a, zones, t))
			continue;
		const int sc = step_score(a, t, rally);
		if (sc < best_s)
		{
			best_s = sc;
			best = t;
		}
	}
	return best.x >= 0 && mv::try_move(best);
}
// TSB 2: I am Tavi, the damaging stun is castable now and free_cast would find a foe for it (its own filter).
static bool tsb_stun_due()
{
	if (!tavi_layer::me() || W.cast || W.me.channeling())
		return false;
	const Kit& k = *W.me.kit;
	if (k.slot_cc < 0 || k.cc_mod <= 0 || k.slot_dmg >= 0 || !ready(k.slot_cc) || (k.cc_excl && W.moved))
		return false;
	for (const auto& e : W.enemies)
		if (cheb(e.pos, W.me.pos) <= static_cast<int>(k.cc_range) && !foe_model::unreachable(e) && !bbget(M.enemy_spawn, e.pos) && !ren_layer::kills_me(e))
			return true;
	return false;
}
// VLC 1 (caller read the flag): an adjacent melee foe exists.
static __attribute__((noinline)) bool vlc_adj_melee()
{
	for (const auto& e : W.enemies)
		if (!(e.kit ? e.kit->ranged : e.range > 1) && cheb(e.pos, W.me.pos) <= 1)
			return true;
	return false;
}
// VLS 1 (caller read the flag): a foe other than an adjacent melee one has me within its next-turn reach (world.cc foe_next_turn_reach).
static __attribute__((noinline)) bool vls_far_reach()
{
	for (const auto& e : W.enemies)
	{
		const int de = cheb(e.pos, W.me.pos);
		const bool ranged = e.kit ? e.kit->ranged : e.range > 1;
		if ((ranged || de > 1) && de <= foe_next_turn_reach(e, false))
			return true;
	}
	return false;
}
bool react_kite()
{
	if (!W.can_attack())
		return false;
	// A ranged foe that follows me must walk and loses its attack, and a melee foe two tiles away misses
	// me if I step; so the hit replaces the escape step only when every foe that reaches me is melee and adjacent, or the
	// shot kills (checked below).
	bool forced = true;
	for (const auto& e : W.enemies)
	{
		const int de = cheb(e.pos, W.me.pos);
		const bool ranged = e.kit ? e.kit->ranged : e.range > 1;
		if ((ranged ? de <= e.range : de <= e.range + 1) && (ranged || de > 1))
			forced = false;
	}
	if (forced && vls_far_reach())
		forced = false; // VLS 1: a dash, spell or walk reach counts as reaching me, as the flee zones do
	if (forced && !vlc_adj_melee())
		forced = false; // VLC 1: no adjacent melee foe, so the shot never replaces the step
	const Body* t = weakest_foe_where([](const Body& e) { return in_my_range(e) && !foe_model::unreachable(e) && !ren_kills_me(e); });
	if (!t)
		return false;
	if (kit_rules::skip_unkillable_foe_on_spawn(*t, kit_rules::my_basic_hit))
	{
		// CBH 16 KSP1: a hit that does not kill a foe on its own spawn heals at its turn end
		t = weakest_foe_where([](const Body& e) { return in_my_range(e) && !foe_model::unreachable(e) && !ren_kills_me(e) && !kit_rules::skip_unkillable_foe_on_spawn(e, kit_rules::my_basic_hit); });
		if (!t)
			return false;
	}
	if ((!forced || (ci_layer::me_cassi() && (!CI2_FIGHT() || CI2_ON(256))) || willow_layer::me()) && !KQ_SITE(1, burst::kills(*t, cheb(t->pos, W.me.pos), KQ_RAW), eff_hp(*t) <= geom::my_burst(*t, cheb(t->pos, W.me.pos))))
		return false; // step away instead; Cassi (30 Str) steps to the rally even when caught
	const Body target = *t;
	const bool tsb_hold = tsb_stun_due(); // TSB 2: the stun, not the reset, takes the cast
	if (tsb_hold)
		bh57_noreset = true;
	const bool hit = attack_champion(target);
	if (tsb_hold)
		bh57_noreset = false;
	if (hit)
		cast::free_cast();
	return hit;
}
// v7xx PTW: flee()'s widened zones while PTW is on (set by flee(), cleared on its return); null otherwise.
static const std::vector<mv::Threat>* ptw_zones = nullptr;
// v7xx PTW bit 1 (+2, +4): no neighbour leaves the zones, so PTS1's refusal of e's stun does not apply.
static bool ptw_no_exit(const Assessment& a, const Body& e, vec2 me)
{
	if (!ptw_zones)
		return false;
	int n = 0;
	for (const auto& g : a.foes)
		n += cheb(g.pos, me) <= g.reach + 1 ? 1 : 0;
	if (n != 1)
		return false;
	for (const vec2 dd : DIRS)
		if (inb(me + dd) && flee_tile_out(a, *ptw_zones, me + dd))
			return false;
	return true;
}
// Fills pf. False when no stun holds the gap: a remembered foe close by, or a chaser I cannot stop (it hits me anyway: keep running).
static bool parting_foes(const Assessment& a, PartingFoes& pf)
{
	const vec2 me = W.me.pos;
	for (const auto& f : a.foes)
	{
		const int d = cheb(f.pos, me);
		if (f.idx < 0 || f.remembered || f.idx >= static_cast<int>(W.enemies.size()))
		{
			if (d <= std::max(f.reach, tune::PARTING_HIDDEN_MIN_REACH) + 1)
				return false;
			continue;
		}
		const Body& e = W.enemies[static_cast<std::size_t>(f.idx)];
		if (!e.stunned && d <= f.reach + 1 && burst::reach_burst_turns(e) >= 2 && !(ptw_no_exit(a, e, me)))
			return false; // CBH 8 PTS1 (PST2): it still acts after a stun before my next turn while the stun pins me; v7xx PTW: not when no step gets out
		if (d <= ((e.stunned) ? foe_of_unstunned(e, f.idx).reach : f.reach)) // CB3 bit 64 R2: a stunned chaser's reach is its kit's
		{
			if (e.stunned)
			{
				if (burst::bh81_stun2(e))
				{
					return false; // PSC bit 1: it still has a turn before mine
				}
				pf.stunned_chaser = true;
			}
			else
				pf.reach_me.push_back(&e);
		}
		else if (d <= f.reach + 1)
			pf.soon.push_back(&e);
	}
	for (const Body* b : pf.reach_me)
		if (!cast::xc_stunnable(*b))
			return false;
	return true;
}
// The nearest stunnable foe within range (the first on a tie); off_spawn: not on its own spawn; only: that foe alone.
static const Body* parting_nearest(int range, bool off_spawn, const Body* only)
{
	const vec2 me = W.me.pos;
	const Body* tgt = nullptr;
	int best = range + 1;
	for (const auto& e : W.enemies)
	{
		const int d = cheb(e.pos, me);
		if (d < best && cast::xc_stunnable(e) && (!off_spawn || !bbget(M.enemy_spawn, e.pos)) && (!only || e.h == only->h))
		{
			best = d;
			tgt = &e;
		}
	}
	return tgt;
}
// A unit stun takes the one foe that reaches me next turn, if it is in range. With none, the nearest stunnable foe in range;
// careful: off its spawn, and only if at most one foe closes in (then that foe).
static const Body* parting_unit_target(const PartingFoes& pf, int range, bool careful)
{
	if (pf.reach_me.size() > 1)
		return nullptr;
	if (pf.reach_me.size() == 1)
		return cheb(pf.reach_me[0]->pos, W.me.pos) <= range ? pf.reach_me[0] : nullptr;
	if (!careful)
		return parting_nearest(range, false, nullptr);
	if (pf.soon.size() > 1)
		return nullptr;
	return parting_nearest(range, true, pf.soon.empty() ? nullptr : pf.soon[0]);
}
static __attribute__((always_inline)) inline bool parting_unit_ready(const Kit& k) { return k.slot_cc >= 0 && k.cc_mod > 0 && ready(k.slot_cc); }
// PASSIVE Prism: every carried gem adds 1.5 Focus, so her stun-nuke (1.5 x Focus and a one-round stun, range 4) is her
// hardest hit and also her escape. When at most one visible foe can reach
// her next turn, and that foe is stunnable within the spell's range (with none, the nearest stunnable foe in range),
// she stuns it instead of stepping: it loses its next turn, so the gap is kept and the nuke lands. Never with a
// remembered foe close by or an awake camp hitting her tile. True if cast.
bool parting_stun(const Assessment& a)
{
	const Kit& k = *W.me.kit;
	if (!prism_layer::fight_parting(k) || !parting_unit_ready(k) || mv::camp_threat(W.me.pos) > 0)
		return false;
	PartingFoes pf;
	if (!parting_foes(a, pf))
		return false;
	const Body* tgt = parting_unit_target(pf, static_cast<int>(k.cc_range), false);
	if (!tgt)
		return false;
	const Body t = *tgt;
	if (!cast_on_champion(k.slot_cc, t))
		return false;
	NLOG("r%d slot %d parting stun at %d,%d gems %u foc %.0f\n", W.round, P.my_slot, t.pos.x, t.pos.y, W.me.gems, W.me.foc);
	return true;
}
// An area stun: one 3x3 covering every foe that can reach me next turn; with none, the stunnable foes a step short of it; with none,
// the nearest stunnable foe the area touches.
static bool parting_area_stun(const Kit& k, const PartingFoes& pf)
{
	std::vector<const Body*> must = pf.reach_me;
	if (must.empty())
	{
		for (const Body* b : pf.soon)
			if (cast::xc_stunnable(*b))
				must.push_back(b);
		if (must.empty())
		{
			const Body* tgt = parting_nearest(static_cast<int>(k.aoe_range + k.aoe_radius), true, nullptr);
			if (!tgt)
				return false;
			must.push_back(tgt);
		}
	}
	const vec2 t = cast::area_tile_covering_all(must, static_cast<int>(k.aoe_range), static_cast<int>(k.aoe_radius));
	return t.x >= 0 && cast_at(k.slot_aoe, t);
}
// the parting stun for every stun kit (Ryth's area stun, Tavi, Ren; Prism keeps parting_stun).
// A stunned chaser loses its next turn (no hit, no step), so the gap holds even though
// these stuns exclude walking. Unit stun: only when the one visible foe that can reach me next turn is in range (none:
// the nearest stunnable foe in range, if at most one foe closes in); area stun: one 3x3 covering every foe that can
// reach me next turn. Never with a remembered foe close by, an unstunnable chaser or an awake camp on my tile.
bool parting_stun_for_stun_kits(const Assessment& a)
{
	const Kit& k = *W.me.kit;
	const bool unit = parting_unit_ready(k);
	const bool area = k.slot_aoe >= 0 && k.aoe_stun && ready(k.slot_aoe);
	if ((!unit && !area) || mv::camp_threat(W.me.pos) > 0)
		return false;
	PartingFoes pf;
	if (!parting_foes(a, pf) || (pf.stunned_chaser && pf.reach_me.empty()))
		return false;
	if (unit)
	{
		const Body* tgt = parting_unit_target(pf, static_cast<int>(k.cc_range), true);
		if (tgt)
		{
			const Body t = *tgt;
			if (cast_on_champion(k.slot_cc, t))
				return true;
		}
	}
	return area && parting_area_stun(k, pf);
}
// a melee body about to step onto its spawn hits the weakest foe in reach now (not on its own spawn, no killing
// retaliation) when no such foe is in reach from dest, where the hit-back below would find it.
static void refuge_hit_check(vec2 dest)
{
	const Body* now = nullptr;
	bool after = false;
	for (const auto& e : W.enemies)
	{
		if (bbget(M.enemy_spawn, e.pos) || (ren_layer::kills_me(e)))
			continue;
		after = after || cheb(e.pos, dest) <= W.me.range;
		if (cheb(e.pos, W.me.pos) <= W.me.range && (!now || eff_hp(e) < eff_hp(*now)))
			now = &e;
	}
	if (now && !after)
	{
		const Body target = *now;
		attack_champion(target);
	}
}
} // namespace
// foe damage a.incoming / danger_at in real HP; danger_at's camp part is real already.
static float sru_in(float foe) { return foe; }
static float tile_danger(const Assessment& a, vec2 t)
{
	const float d = geom::danger_at(a, t);
	return d;
}
// The worst hit a spawn tile may take: SR_BURST_PCT of my full health.
static __attribute__((always_inline)) inline float refuge_burst_cap()
{
	const float full = W.me.maxhp + std::max(0.0f, W.me.shield);
	return 0.01f * static_cast<float>(SR_BURST_PCT) * full;
}
// The free spawn tile next to me with the lowest cost below cap; x < 0: none. no_camp_out: not a tile camp_out would step me off next turn.
// v775 XCF bit 8 RTH1: my spawn's in-board tiles grown by Chebyshev 1, built on first use (the map's spawn never changes).
static const bitboard& xcf_spawn_r1()
{
	static bitboard sr1;
	static bool sr1_ok = false;
	if (!sr1_ok)
	{
		bbforeach(M.my_spawn, [&](vec2 p) {
			if (p.x >= G.w || p.y >= G.h)
				return;
			for (int dx = -1; dx <= 1; ++dx)
				for (int dy = -1; dy <= 1; ++dy)
				{
					const vec2 t{ p.x + dx, p.y + dy };
					if (inb(t))
						bbset(sr1, t);
				}
		});
		sr1_ok = true;
	}
	return sr1;
}
template <class Cost> static __attribute__((always_inline)) inline vec2 refuge_tile(float cap, bool no_camp_out, Cost cost)
{
	vec2 dest{ -1, -1 };
	if (XCF_ON(8) && inb(W.me.pos) && !bbget(xcf_spawn_r1(), W.me.pos)) // v775 XCF bit 8 RTH1: no spawn tile beside me
		return dest;
	float best = cap;
#pragma clang loop unroll(full)
	for (const vec2 d : DIRS)
	{
		const vec2 n = W.me.pos + d;
		if (!inb(n) || !bbget(M.my_spawn, n) || !mv::free_tile(n))
			continue;
		if (no_camp_out && econ::camp_reach_flee_tile(n))
			continue; // the heal is lost to the hits
		const float dg = cost(n);
		if (dg < best)
		{
			best = dg;
			dest = n;
		}
	}
	return dest;
}
// Hit back from the spawn: the weakest foe in reach that does not stand on its own spawn, unless its retaliation would kill me.
static __attribute__((always_inline)) inline void refuge_hit_back()
{
	if (!W.can_attack())
		return;
	const Body* tgt = weakest_foe_where([](const Body& e) { return !ren_kills_me(e) && in_my_range(e) && !kit_rules::skip_unkillable_foe_on_spawn(e, kit_rules::my_basic_hit); });
	if (tgt)
		attack_champion(*tgt);
}
// v757 MBB bit 1 SSH (GR:153): every foe within its range + 1 of me stands on its own spawn (none can step onto mine) and no awake
// camp reaches me: the spawn hold is a stalemate, not a refuge.
static __attribute__((noinline)) bool ssh_foes_home_only()
{
	int n = 0;
	for (const auto& e : W.enemies)
	{
		if (cheb(e.pos, W.me.pos) > e.range + 1)
			continue;
		if (!bbget(M.enemy_spawn, e.pos))
			return false;
		++n;
	}
	if (n == 0)
		return false;
	for (const auto& vc : W.camps)
	{
		if (vc.ci < 0 || static_cast<std::size_t>(vc.ci) >= static_cast<std::size_t>(M.nc))
			continue;
		const auto& c = M.camps[static_cast<std::size_t>(vc.ci)];
		if (vc.awake && c.attacks() && cheb(c.pos, W.me.pos) <= c.reach + 1)
			return false;
	}
	return true;
}
namespace {
bool spawn_refuge(const Assessment& a)
{
	if (!M.ready() || W.me.channeling())
		return false;
	if (!(W.on_spawn) && 100.0f * a.ratio >= static_cast<float>(SR_RATIO_X100)) // FLR bit 4 (BB13 bit 4 re-land): the ratio gate only off spawn
		return false;
	const float cap = refuge_burst_cap();
	if (W.on_spawn)
	{
		if (sru_in(a.incoming) >= cap)
			return false;
		if (MBB_ON(1) && ssh_foes_home_only()) // v757 MBB bit 1 SSH
			return false;
	}
	else
	{
		if (!W.can_move())
			return false;
		const vec2 dest = refuge_tile(cap, false, [&](vec2 n) __attribute__((always_inline))
		{
			return tile_danger(a, n);
		});
		if (dest.x < 0)
			return false;
		if (!W.me.kit->ranged && W.can_attack())
			refuge_hit_check(dest);
		if (!mv::try_move(dest))
			return false;
	}
	refuge_hit_back();
	cast::free_aoe();
	return true;
}
// The ally a flee step falls back toward: healthy, out of the danger; none, or near my spawn: home (x < 0).
static vec2 flee_rally(const std::vector<mv::Threat>& zones)
{
	if (mv::home_steps(W.me.pos) <= SR_HOME_D)
		return vec2{ -1, -1 }; // no ally rally near my spawn; retreat_step goes home
	return rally_ally(zones);
}
// A foe's zone in flee's tile tests beyond what zones_of gave it.
static __attribute__((always_inline)) inline void flee_widen_zones(const Assessment& a, std::vector<mv::Threat>& zones)
{
	for (std::size_t i = 0; i < zones.size() && i < a.foes.size(); ++i)
	{
		const int r2 = geom::foe_two_turn_reach(a.foes[i], nullptr, VBC_ON(16)); // VBC 16
		if (zones[i].reach >= 0 && r2 > zones[i].reach)
			zones[i].reach = r2;
	}
	nova::econ::win_channel::widen(a, zones); // two-turn zones on a win-channel cancel turn
}
// A melee body hits what is next to it.
static __attribute__((always_inline)) inline void flee_melee_hit()
{
	for (const auto& e : W.enemies)
		if (in_my_range(e) && attack_champion(e))
			break;
}
// A parting stun that took the turn's walk ends the flee.
static __attribute__((always_inline)) inline bool flee_stun_and_stay(FleeCtx& c)
{
	if (!parting_stun_for_stun_kits(c.a) || W.can_move())
		return false;
	if (!c.k.ranged) // the stun excludes walking, not attacking: a melee body still hits what is next to it
		flee_melee_hit();
	else if (tavi_layer::me() && !W.moved && W.can_attack()) // TSB 1: an unmoved ranged body still has its attack
		flee_melee_hit();
	return true;
}
// Hit and run: a melee body may attack and walk in the same turn, so it strikes the foe next to it before stepping
// away. An enhanced attack (Marcella's reset) stuns it, and a stunned chaser cannot follow.
static __attribute__((always_inline)) inline void flee_hit_and_run(FleeCtx& c)
{
	const Kit& k = c.k;
	if (k.ranged || !W.can_attack())
		return;
	const Body* adj = fight_turn::flee_hit_target();
	if (!adj)
		return;
	const Body target = *adj;
	bool csx_enh = false;
	const bool can_arm = k.reset_enhanced && k.slot_reset >= 0 && ready(k.slot_reset) && cast::xc_stunnable(target);
	const bool mrs_pre = can_arm;
	const bool csx_hit = attack_champion(target);
	bh57_noreset = false;
	if (mrs_pre && csx_hit && W.cast && W.cd[static_cast<std::size_t>(k.slot_reset)] > 0)
		csx_enh = true; // attack_champion's reset went off, so its second hit was the armed one
	c.acted |= csx_hit;
}
static __attribute__((always_inline)) inline void flee_shield(FleeCtx& c)
{
	if (c.a.in_reach && fight_turn::shield_ready(c.k))
		c.acted |= cast_self(c.k.slot_shield);
}
// PASSIVE Cassi: her stun is walk-compatible: on the way out, the foe with the biggest burst that reaches me next turn
// loses that turn (a stunned chaser neither hits nor follows).
static __attribute__((always_inline)) inline void flee_walking_stun(FleeCtx& c)
{
	const Kit& k = c.k;
	if (!is_caster_champion() || k.slot_cc < 0 || k.cc_excl || !ready(k.slot_cc) || !c.a.in_reach)
		return;
	const Body* st = nullptr;
	float best = 0;
	for (const auto& f : c.a.foes)
	{
		if (f.idx < 0)
			continue;
		const Body& e = W.enemies[static_cast<std::size_t>(f.idx)];
		const int d = cheb(e.pos, W.me.pos);
		if (e.stunned || marcella_layer::fight_stun_wasted(e) || d > static_cast<int>(k.cc_range) || d > f.reach || f.burst <= best)
			continue;
		best = f.burst;
		st = &e;
	}
	if (!st)
		return;
	const bool csx_ok = cast_on_champion(k.slot_cc, *st);
	c.acted |= csx_ok;
}
// The dash is walk-compatible, so the turn's step follows from the landing: out of every reach if one step does it, else
// toward the nearest safe tile on the rally side; already out of reach, one more step of margin.
static __attribute__((always_inline)) inline void flee_step_after_dash(FleeCtx& c)
{
	if (!W.can_move())
		return;
	if (!mv::in_threat(c.zones, W.me.pos))
	{
		mv::retreat_step(c.zones, tune::FLEE_RETREAT_MARGIN, flee_rally(c.zones)); // FLR bit 16 FLD1
	}
	else if (!step_out_of_reach(c.a, c.zones))
		mv::escape_toward(c.zones, react_rally());
}
// First choice: one step that leaves every reach (a chaser at my speed then cannot hit me), toward home or a
// healthy ally. A step that keeps me in reach hands out a free hit, so it is taken only when nothing better
// exists: a dash out, or the path to the nearest safe tile.
static __attribute__((always_inline)) inline void flee_leave_reach(FleeCtx& c)
{
	if (step_out_of_reach(c.a, c.zones))
		c.acted = true;
	else if (c.a.in_reach && geom::dash_away(c.zones))
	{
		c.acted = true;
		flee_step_after_dash(c);
	}
	else if (c.k.ranged && c.a.in_reach && react_kite()) // hit back rather than a step that is hit anyway
		c.acted = true;
	else
		c.acted |= mv::escape_toward(c.zones, react_rally()); // never away from the team
}
// PASSIVE Stellar: out of every reach this turn, a ready damage spell goes on the weakest enemy in range
// (or the area on 2+); it excludes walking, so I stay this turn (nothing can hit me here next turn) and the
// retreat goes on after. True if cast.
static __attribute__((always_inline)) inline bool flee_nuke(const FleeCtx& c)
{
	const Kit& k = c.k;
	if (W.me.frac() < tune::NUKE_MIN_FRAC || W.cast)
		return false;
	const Body* tgt = weakest_foe_where([&](const Body& e) { return cheb(e.pos, W.me.pos) <= static_cast<int>(k.dmg_range) && !bbget(M.enemy_spawn, e.pos); });
	if (!tgt || k.slot_dmg < 0 || !ready(k.slot_dmg) || !cast_on_champion(k.slot_dmg, *tgt))
	{
		if (!(W.me.type == cambc::champion_type::stellar && !W.cast && !W.moved && cast::free_aoe())) // TSB 4: the area on 1+
			return false;
	}
	cast::free_attack();
	return true;
}
// Nothing reaches me here next turn: a healthy ranged body shoots before it would walk off. True if it hit (it stays).
static __attribute__((always_inline)) inline bool flee_shot(const FleeCtx& c)
{
	const Kit& k = c.k;
	if (!k.ranged || W.me.range < tune::SHOT_MIN_RANGE || W.me.frac() < tune::SHOT_MIN_FRAC || W.me.gems >= tune::SHOT_MAX_GEMS || W.attacked || !W.can_attack())
		return false;
	const Body* tgt = weakest_foe_where([](const Body& e) { return in_my_range(e) && !kit_rules::skip_unkillable_foe_on_spawn(e, kit_rules::my_basic_hit); });
	const bool tsb_hold = tsb_stun_due(); // TSB 2: the stun, not the reset, takes the cast
	if (tsb_hold)
		bh57_noreset = true;
	const bool tsb_hit = tgt && attack_champion(*tgt);
	if (tsb_hold)
		bh57_noreset = false;
	if (!tsb_hit)
		return false;
	std::int32_t alive = 1; // no reset spent on a target the first shot killed
	if (!(tsb_hold) && k.slot_reset >= 0 && ready(k.slot_reset) && cambc::detail::sdk_champion_is_alive(tgt->h, &alive) == 0 && alive != 0 &&
		cast_self(k.slot_reset))
		attack_champion(*tgt); // attack again after the reset
	cast::free_cast();
	return true;
}
// an awake camp I see stands within reach + 1 of me, so it explains last round's damage.
static bool awake_camp_explains_damage()
{
	const vec2 me = W.me.pos;
	for (const auto& vc : W.camps)
	{
		const auto& c = M.camps[static_cast<std::size_t>(vc.ci)];
		if (vc.awake && c.attacks() && cheb(c.pos, me) <= c.reach + 1)
			return true;
	}
	return false;
}
__attribute__((noinline)) bool continue_retreat_slow(const Assessment& a)
{
	if (!a.foes.empty())
		return false; // the stance logic handles visible threats
	if (W.round - intel::latest_sighting() >= 2 && W.me.frac() >= (linked_slot() >= 0 ? 0.60f : 0.55f) && econ::ehc_herd_crew(2))
	{
		turn_memory.retreat_until = -1; // EHC bit 1 CRH: no foe for 2 rounds and a crewed awake herd: the stale retreat ends
		return false;
	}
	if (seen.empty() && intel::last_death() >= turn_memory.last_flee_round)
	{
		turn_memory.retreat_until = -1; // no foe remembered and an enemy died since the flee: the retreat is over
		return false;
	}
	if (W.on_spawn)
		return false; // a committed retreat never walks off my spawn
	if (took_damage(1) && !(awake_camp_explains_damage()))
		turn_memory.retreat_until = W.round + tune::RETREAT_HURT_ROUNDS;
	if (!mv::in_threat(turn_memory.retreat_from, W.me.pos, tune::RETREAT_MARGIN))
		return false;
	return mv::retreat_step(turn_memory.retreat_from, tune::RETREAT_MARGIN);
}
__attribute__((noinline)) bool react_guard_slow(const Assessment& a)
{
	const vec2 me = W.me.pos;
	bool hit_by = false;
	for (const auto& e : W.enemies)
		hit_by |= cheb(e.pos, me) <= e.range + 1 && !bbget(M.enemy_spawn, e.pos);
	if (!hit_by)
		return false;
	if (W.can_attack())
	{
		const Body* t = nullptr;
		for (const auto& e : W.enemies)
		{
			if (cheb(e.pos, me) > W.me.range || foe_model::unreachable(e))
				continue;
			if (ren_layer::kills_me(e))
				continue;
			if (!t || eff_hp(e) < eff_hp(*t))
				t = &e;
		}
		if (t && kit_rules::skip_unkillable_foe_on_spawn(*t, kit_rules::my_basic_hit))
		{
			t = nullptr; // CBH 16 KSP1: the weakest foe that is not an unkillable one on its own spawn
			for (const auto& e : W.enemies)
				if (cheb(e.pos, me) <= W.me.range && !foe_model::unreachable(e) && !ren_layer::kills_me(e) && !kit_rules::skip_unkillable_foe_on_spawn(e, kit_rules::my_basic_hit) && (!t || eff_hp(e) < eff_hp(*t)))
					t = &e;
		}
		if (t)
		{
			const Body target = *t;
			const bool r2b_tsg = tsb_stun_due(); // v699 R2T bit 1 TSG1: the stun, not the reset, takes the cast (TSB 2's hold)
			if (r2b_tsg)
				bh57_noreset = true;
			if (attack_champion(target))
			{
				if (r2b_tsg)
					bh57_noreset = false;
				cast::free_cast();
				return true;
			}
			if (r2b_tsg)
				bh57_noreset = false;
		}
	}
	return false;
}
} // namespace
} // namespace flee_turn
// my spawn heals me to full at the end of my turn and no enemy can step onto it.
// A flee that starts on my spawn stays there and hits what it reaches; one that starts next to it steps onto a free spawn
// tile. Not when the foes that reach the tile can deal SR_BURST_PCT of my full health before my next turn (the normal flee).
// the worst damage on tile t between my turn end and my next turn end: each visible foe's next turn (lethal_burst_hit: burst) + one more
// basic hit for a double turn (the starting team swaps, GameRules:122) + the attackers reaching t, awake or of the group I am about to wake.
bool spawn_siege_is_safe(vec2 t, int wake_group)
{
	float sum = burst::lethal_burst_damage_sum(t, 0, nullptr);
	for (const auto& e : W.enemies)
		if (cheb(e.pos, W.me.pos) <= 9 && cheb(e.pos, t) <= e.range + 1)
			sum += e.str * kit_rules::passive_mult(e);
	sum = mu::mult_foe_hit_to_real_hp(sum);
	for (const auto& vc : W.camps)
	{
		const auto& c = M.camps[static_cast<std::size_t>(vc.ci)];
		if (c.attacks() && cheb(c.pos, t) <= c.reach && (vc.awake || c.group == wake_group))
		{
			if (((map_class() & MCL_BIT_SPAWNECON) != 0)) // a mate on my spawn strictly nearer takes it (GameRules:194: a woken monster attacks the nearest champion)
			{
				const int dt = cheb(c.pos, t);
				bool shield = false;
				for (const auto& al : W.allies)
					shield = shield || (bbget(M.my_spawn, al.pos) && cheb(c.pos, al.pos) < dt);
				if (shield)
					continue;
			}
			sum += (c.str * mu::my_camp(mu::IN));
		}
	}
	return sum * 100.0f < static_cast<float>(SS_TAB[3]) * W.me.maxhp;
}
bool flee(const Assessment& a)
{
	AF_CHECK();
	turn_memory.last_flee_round = W.round;
	std::vector<mv::Threat> zones = geom::zones_of(a);
	flee_turn::flee_widen_zones(a, zones);
	const std::size_t foe_zones = zones.size();
	geom::add_camp_zones(zones);
	AF_CHECK();
	fight_turn::note_retreat(zones);
	struct PtwZones // v7xx PTW: parting_foes reads flee()'s zones during this call only
	{
		explicit PtwZones(const std::vector<mv::Threat>* z) { flee_turn::ptw_zones = z; }
		~PtwZones() { flee_turn::ptw_zones = nullptr; }
	} const ptw_z(&zones);
	if (flee_turn::parting_stun(a)) // PASSIVE Prism
	{
		cast::free_attack();
		return true;
	}
	if (flee_turn::spawn_refuge(a))
		return true;
	flee_turn::FleeCtx c{ a, *W.me.kit, zones, foe_zones, false };
	if (flee_turn::flee_stun_and_stay(c))
		return true;
	flee_turn::flee_hit_and_run(c);
	flee_turn::flee_shield(c);
	flee_turn::flee_walking_stun(c);
	if (mv::in_threat(zones, W.me.pos))
	{
		if (fight_turn::crystal_escape_turn(a))
			return true;
		flee_turn::flee_leave_reach(c);
	}
	else
	{
		if (flee_turn::flee_nuke(c) || flee_turn::flee_shot(c))
			return true;
		// Fall back toward a healthy ally that stands outside the danger, else toward home.
		c.acted |= mv::retreat_step(zones, flee_turn::tune::FLEE_RETREAT_MARGIN, flee_turn::flee_rally(zones));
	}
	if (!c.k.ranged) // a melee body that walked can still hit whatever is next to it.
		flee_turn::flee_melee_hit();
	c.acted |= kite_shot_after_move(); // a ranged walk spends the attack; a walk-compatible reset gives it back
	if (!c.acted && !W.moved) // FLZ: a failed flee leaves its foe zones (never one I stand in) for a later walk
	{
		flz_z.clear();
		flz_r = W.round;
		for (std::size_t i = 0; i < foe_zones && i < zones.size(); ++i)
			if (zones[i].reach >= 0 && cheb(W.me.pos, zones[i].pos) > zones[i].reach)
				flz_z.emplace_back(zones[i].pos, zones[i].reach);
	}
	return c.acted || W.moved;
}
// The first early-out test inline at the call site (a call and frame a turn saved), the rest out of line.
__attribute__((always_inline)) bool continue_retreat(const Assessment& a)
{
	if (W.round > turn_memory.retreat_until || turn_memory.retreat_from.empty())
		return false;
	return flee_turn::continue_retreat_slow(a);
}
// The first early-out test inline at the call site (a call and frame a turn saved), the rest out of line.
__attribute__((always_inline)) bool react_guard(const Assessment& a)
{
	if (W.moved || W.attacked || W.cast || W.me.channeling() || W.on_spawn || !took_damage(2) || stance::low_start_blocked())
		return false;
	return flee_turn::react_guard_slow(a);
}
} // namespace nova::combat
