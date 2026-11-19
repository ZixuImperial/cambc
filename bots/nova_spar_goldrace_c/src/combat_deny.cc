// combat_deny.cc: Altars, locks and tribute denial.
#include "combat_internal.h"
namespace nova::combat {
namespace deny
{
namespace tune
{
inline constexpr int GD_WIN_TRIBUTE = rs::WIN_TRIBUTE; // the tributed total that ends the game
inline constexpr int GD_OWN_SIGHT = 9; // a foe past this with no gems read is a ward's sighting: its bag is asked of the host
inline constexpr int GD_ALTAR_ADJ = 1;       // a tribute runs this near an altar
inline constexpr int GD_TOO_FAR_SLACK = 6;   // tiles past my turns left at which no walk gets there (cheap bound before the searches)
inline constexpr int GD_LOCK_R = 2;          // a lock goes down from this near the altar
inline constexpr int GD_WALK_SLACK = 2; // tiles past my turns left that the walk searches look at
}
namespace {
int lock_known = -1;                  // locks I carry (-1: unknown)
int lock_checked = -1000;
// The last trigger channel I saw (vision flickers behind walls and bushes: keep walking to it until it can complete).
struct GdMem
{
	std::uint32_t h = 0;
	vec2 pos{ -1, -1 };
	int set = -1000, until = -1000;
	bool ending = false;
};
GdMem gd_mem;
// The channel to cancel and my walk limits.
struct GameDenyGoal
{
	const Kit& k;
	const Body& tgt;
	vec2 alt;
	int dme; // my distance to the channeler
	int L; // my turns before it completes
	int rad; // the walk search's radius
};
// Each way to cancel: the turns I need (this one counts as 1; BIG = not before it completes) and the tiles it works from.
struct GameDenyWays
{
	int t_lock = BIG, t_stun = BIG;
	bitboard g_lock, g_stun;
};
int locks_carried()
{
	if (lock_known >= 0 && W.round - lock_checked < 50)
		return lock_known;
	std::array<std::uint32_t, 4> counts{};
	if (cambc::detail::sdk_champion_consumables(W.me.h, counts.data()) != 0)
		return 0;
	lock_known = static_cast<int>(counts[RAW_LOCK]);
	lock_checked = W.round;
	return lock_known;
}
// a lock is wanted when an enemy bag of GD_LOCKBAG or more was last seen on a living body, or they have tributed GD_LOCKTT or more.
static bool game_deny_lock_wanted()
{
	if (W.tributed_them >= (CB3_TAB[2])) // CB3 bit 4096 LTT: CB3_LOCKTT
		return true;
	const auto& tt = intel::team_table();
	for (std::size_t i = 0; i < tt.size(); ++i)
	{
		if (!tt[i].alive || tt[i].round <= -1000)
			continue;
		const Body* b = intel::team_body(i);
		if (b && static_cast<int>(b->gems) >= (GDB_BAG))
			return true;
	}
	for (const auto& e : W.enemies)
	{
		if (e.gems != 0 || cheb(e.pos, W.me.pos) <= 9)
			continue;
		std::uint32_t wg = 0;
		if (cambc::detail::sdk_champion_gems(e.h, &wg) == 0 && static_cast<int>(wg) >= (GDB_BAG))
			return true;
	}
	return false;
}
// BBL (b1753): our team's lock on the altar, read directly (a second lock of ours is refused: altar_lock_already_locked).
static bool bbl_our_lock_on(vec2 altar)
{
	cambc::detail::altar_lock_info i{};
	cancel_spin_before_action();
	return cambc::detail::sdk_altar_lock(altar.x, altar.y, cambc::detail::absolute_team(cambc::team::ally), &i) == 0;
}
__attribute__((noinline)) bool deny_tribute_slow()
{
	const PosSoA& alw = altar_soa(); // the altars within 2, 8 at a time, in list order
	for (std::size_t alw_k = 0; alw_k < alw.n; alw_k += 8)
	for (unsigned alw_m = pos_within_r_mask(alw, alw_k, W.me.pos, 2); alw_m != 0; alw_m &= alw_m - 1)
	{
		const auto& a = M.altars[alw_k + static_cast<std::size_t>(__builtin_ctz(alw_m))];
		bool enemy_tribute = false, ally_tribute = false;
		for (const auto& e : W.enemies)
			if ((e.state & ST_TRIBUTE) && cheb(e.pos, a.pos) <= 1)
				// a lock is worth 10 gold against a bag of 40+, a game-ending bag, or a smaller
				// one I am about to kill (it cannot tribute again until it breaks the lock); keep it for those.
				if (static_cast<int>(e.gems) >= HUNT_MIN_BAG || W.tributed_them + static_cast<int>(e.gems) >= rs::WIN_TRIBUTE ||
					(e.gems >= 20 && cheb(e.pos, W.me.pos) <= W.me.range + 1))
					enemy_tribute = true;
		if (!enemy_tribute)
			continue;
		for (const auto& al : W.allies)
			if ((al.state & ST_TRIBUTE) && cheb(al.pos, a.pos) <= 1)
				ally_tribute = true;
		if (ally_tribute || locks_carried() <= 0)
			continue;
		if (bbl_our_lock_on(a.pos))
			continue; // BBL (b1753): our lock stands there already (rc altar_lock_already_locked)
		std::int32_t ok = 0;
		cancel_spin_before_action();
		const auto code = cambc::detail::sdk_use_consumable(RAW_LOCK, a.pos.x, a.pos.y, &ok);
		lock_known = -1;
		if (code == 0 && ok)
		{
			NLOG("r%d lock placed on %d,%d (enemy tribute)\n", W.round, a.pos.x, a.pos.y);
			return true;
		}
	}
	return false;
}
int nearest_altar(vec2 p, int& dist)
{
	int bi = -1;
	dist = BIG;
	for (std::size_t i = 0; i < static_cast<std::size_t>(M.na); ++i)
	{
		const int d = cheb(M.altars[i].pos, p);
		if (d < dist)
		{
			dist = d;
			bi = static_cast<int>(i);
		}
	}
	return bi;
}
bool place_lock(vec2 altar)
{
	if (bbl_our_lock_on(altar))
		return false; // BBL (b1753): our lock stands there already
	std::int32_t ok = 0;
	cancel_spin_before_action();
	const auto code = cambc::detail::sdk_use_consumable(RAW_LOCK, altar.x, altar.y, &ok);
	lock_known = -1;
	if (code == 0 && ok)
	{
		NLOG("r%d HUNT lock placed on %d,%d\n", W.round, altar.x, altar.y);
		return true;
	}
	return false;
}
// walk steps from me to the nearest goal tile (dynamic walls; BIG when none within rad or fuel is short).
int game_deny_walk_steps(const bitboard& goals, int rad)
{
	if (bbget(goals, W.me.pos))
		return 0;
	if (fuel() < 30000 || rad <= 0)
		return BIG;
	static bitboard gw, groots, gdest, gvis;
	static distance_field gf;
	gw.clear();
	gw |= mv::blocked();
	bbset(gw, W.me.pos, false);
	groots.clear();
	groots |= goals;
	gvis.clear();
	gvis |= goals;
	gvis &= gw;
	groots ^= gvis; // goals & ~walls
	if (!bbany(groots))
		return BIG;
	gdest.clear();
	bbset(gdest, W.me.pos);
	gvis.clear();
	gf.compute_to(gw, groots, gdest, gvis, static_cast<std::uint16_t>(rad));
	const std::uint16_t d = dfget_me(gf);
	return d == UNREACH ? BIG : static_cast<int>(d);
}
// cast a stun that reaches channeler t from here (cc, area stun, Heart's landing dash). True if cast.
bool game_deny_stun_channeler(const Body& t)
{
	if (!W.me.kit || marcella_layer::fight_stun_wasted(t) || W.cast)
		return false;
	const Kit& k = *W.me.kit;
	const int d = cheb(t.pos, W.me.pos);
	if (k.slot_cc >= 0 && ready(k.slot_cc) && d <= static_cast<int>(k.cc_range) && cast_on_champion(k.slot_cc, t))
		return true;
	if (k.aoe_stun && k.slot_aoe >= 0 && ready(k.slot_aoe) && d <= static_cast<int>(k.aoe_range + k.aoe_radius))
	{
		vec2 c = t.pos;
		if (d > static_cast<int>(k.aoe_range))
			c = { t.pos.x + (W.me.pos.x > t.pos.x ? 1 : (W.me.pos.x < t.pos.x ? -1 : 0)),
				  t.pos.y + (W.me.pos.y > t.pos.y ? 1 : (W.me.pos.y < t.pos.y ? -1 : 0)) };
		if (inb(c) && cast_at(k.slot_aoe, c))
			return true;
	}
	if (k.dash_stun && k.slot_dash >= 0 && ready(k.slot_dash) && d <= static_cast<int>(k.dash_range + k.dash_radius))
	{
		const int dr = static_cast<int>(k.dash_range), rr = std::max(0, static_cast<int>(k.dash_radius));
		int tries = 0;
		for (int dx = -dr; dx <= dr && tries < 4; ++dx)
			for (int dy = -dr; dy <= dr && tries < 4; ++dy)
			{
				const vec2 L{ W.me.pos.x + dx, W.me.pos.y + dy };
				if (L == W.me.pos || !inb(L) || cheb(L, t.pos) > rr || !mv::free_tile(L))
					continue;
				if (bbget(M.enemy_spawn, L))
					continue; // no landing on the enemy spawn
				if (BGX_ON(2) && !dash_legal_between(W.me.pos, L))
				{
					DASH_MIDDLE_CNT(1, true);
					continue;
				}
				++tries;
				if (cast_at(k.slot_dash, L))
					return true;
			}
	}
	return false;
}
// Can body b cancel a channel at tp (altar alt) within L turns: a stun kit whose cooldown (known, else ready) and
// walk (Chebyshev past its reach) land in time on a stunnable channeler, or a carried lock within L of the altar's 2-ring.
static inline bool game_deny_mate_on_altar(vec2 alt); // v679 LCK bit 1
// GDN bit 4 GDS1: a walk-excluding stun casts the turn after the walk ends (INT:28: walk then spell is refused).
void gdn_gds_flip()
{
}
bool gdn_gds_excl(const Kit& k, int slot, int rng)
{
	return (slot == k.slot_cc && rng == static_cast<int>(k.cc_range) && k.cc_excl)
		|| (k.aoe_stun && slot == k.slot_aoe && rng == static_cast<int>(k.aoe_range + k.aoe_radius) && k.aoe_excl);
}
int gdn_gds_walk(int w, int cd, int L)
{
	if (std::max(w, std::max(0, cd) + 1) <= L && std::max(w + 1, std::max(0, cd) + 1) > L)
		gdn_gds_flip();
	return w + 1;
}
// GDN bit 2 GDL1: body b's ready dash reaches the lock ring a dash range sooner (dash, step, lock in one turn, INT:30).
void gdn_gdl_cc_flip()
{
}
bool gdn_cc_dash_lock(const Body& b, bool is_me, vec2 alt, int L)
{
	if (!b.kit || b.kit->slot_dash < 0 || b.kit->slot_dash > 1 || b.kit->dash_range <= 0)
		return false;
	const int cd = is_me ? W.cd[static_cast<std::size_t>(b.kit->slot_dash)] : b.cd[static_cast<std::size_t>(b.kit->slot_dash)];
	if (cd > 0 || std::max(1, cheb(b.pos, alt) - tune::GD_LOCK_R - static_cast<int>(b.kit->dash_range)) > L)
		return false;
	gdn_gdl_cc_flip();
	return true;
}
bool game_deny_can_cancel_channel(const Body& b, bool is_me, vec2 tp, vec2 alt, int L, bool stunnable)
{
	if (b.channeling() || !b.kit)
		return false;
	const Kit& k = *b.kit;
	if (stunnable)
	{
		const int d = cheb(b.pos, tp);
		auto ok = [&](int slot, int rng)
		{
			if (slot < 0 || slot > 1 || rng <= 0)
				return false;
			const int cd = is_me ? W.cd[static_cast<std::size_t>(slot)] : b.cd[static_cast<std::size_t>(slot)];
			return std::max((d - rng > 0 && gdn_gds_excl(k, slot, rng)) ? gdn_gds_walk(d - rng, cd, L) : std::max(1, d - rng), std::max(0, cd) + 1) <= L; // GDN GDS1
		};
		if ((ok(k.slot_cc, static_cast<int>(k.cc_range)) || (k.aoe_stun && ok(k.slot_aoe, static_cast<int>(k.aoe_range + k.aoe_radius)))
				|| (k.dash_stun && ok(k.slot_dash, static_cast<int>(k.dash_range + k.dash_radius)))))
			return true;
	}
	if (alt.x < 0 || (std::max(1, cheb(b.pos, alt) - 2) > L && !(gdn_cc_dash_lock(b, is_me, alt, L)))) // GDN GDL1
		return false;
	if (game_deny_mate_on_altar(alt))
		return false; // v679 LCK bit 1: a mate channels there: no lock option (it would cancel our tribute)
	if (is_me)
		return locks_carried() > 0;
	std::array<std::uint32_t, 4> cnt{};
	return cambc::detail::sdk_champion_consumables(b.h, cnt.data()) == 0 && cnt[RAW_LOCK] > 0;
}
// mates ranked ahead of me for the deny walks: a cancel tool in time first, then a bag of GDB_BAG or more behind, then nearer (ties
// lower slot).
int game_deny_mates_ahead(vec2 tp, vec2 alt, int dme, int L, bool stunnable)
{
	const bool me_t = game_deny_can_cancel_channel(W.me, true, tp, alt, L, stunnable);
	int n = 0;
	for (const auto& al : W.allies)
	{
		if (al.channeling())
			continue;
		const bool al_t = game_deny_can_cancel_channel(al, false, tp, alt, L, stunnable);
		bool ahead;
		if (al_t != me_t)
			ahead = al_t;
		else {
			const int da = cheb(al.pos, tp);
			ahead = da < dme || (da == dme && al.slot < P.my_slot);
		}
		n += ahead ? 1 : 0;
	}
	return n;
}
// no trigger channel in sight now: a remembered one that can still be running is walked to (within 2 of its tile).
bool game_deny_follow_channel(const Assessment& a)
{
	const int now = W.round;
	if (gd_mem.until < now + 1 || gd_mem.pos.x < 0)
		return false;
	for (const auto& e : W.enemies)
		if (e.h == gd_mem.h)
		{
			gd_mem.until = -1000; // in sight and not channelling (a trigger channel would have been taken): it ended
			return false;
		}
	if (intel::foe_died_round(gd_mem.h) >= gd_mem.set || (a.stance == FLEE && !gd_mem.ending) || !W.can_move())
		return false;
	const int dme = cheb(gd_mem.pos, W.me.pos);
	if (dme <= 2)
		return false;
	int nearer = 0;
	{
		int ad = BIG;
		const int ai = nearest_altar(gd_mem.pos, ad);
		nearer = game_deny_mates_ahead(gd_mem.pos, ai >= 0 && ad <= 1 ? M.altars[static_cast<std::size_t>(ai)].pos : vec2{ -1, -1 }, dme, gd_mem.until - now, true);
	}
	if (nearer >= GD_BODIES)
		return false;
	bitboard g;
	g.draw_chebyshev(gd_mem.pos, 2.0f);
	const int left = gd_mem.until - now;
	const int s = game_deny_walk_steps(g, std::min(GD_RAD, left + 2));
	if (s >= BIG || s > left)
		return false;
	const mv::SuspendFoeGuard bbm_sg(false); // BBM MF3: the game-ending deny walk ignores the foe guard
	const bool moved = mv::step_to_set(g, std::min(GD_RAD, left + 2));
	NLOG("r%d slot %d GAME_DENY follow left %d walk %d moved %d\n", now, P.my_slot, left, s, static_cast<int>(moved));
	return moved;
}
// after game_deny's lock or stun the turn ends; hit the lowest eff_hp foe in my reach not on its spawn.
__attribute__((noinline)) void game_deny_hit_after()
{
	if (W.attacked || !W.can_attack())
		return;
	const Body* t = nullptr;
	for (const auto& e : W.enemies)
		if (cheb(e.pos, W.me.pos) <= W.me.range && !kit_rules::skip_unkillable_foe_on_spawn(e, kit_rules::my_basic_hit) && (!t || eff_hp(e) < eff_hp(*t)))
			t = &e;
	if (t)
	{
		const Body target = *t;
		attack_champion(target);
	}
}
// GDN bit 8 EGS (spec_egs_1110): concurrent foe channels all complete, so their SUM is the score they reach (GR:226). Two or more known
// channels whose sum ends (or flips) the game: the altar holding the largest summed bag, its biggest channeler; one lock there cancels
// them all (GR:240). nullptr: no stacked case.
void gdn_egs_flip()
{
}
const Body* gdn_egs_pick(bool& ending)
{
	std::array<int, 16> s_alt{};
	std::array<const Body*, 16> big{};
	std::array<int, 16> big_g{};
	int s_all = 0, n = 0;
	bool any_wdb = false;
	for (const auto& e : W.enemies)
	{
		if (!(e.state & ST_TRIBUTE))
			continue;
		int g = static_cast<int>(e.gems);
		if (g == 0 && cheb(e.pos, W.me.pos) > tune::GD_OWN_SIGHT)
		{
			std::uint32_t wg = 0;
			if (cambc::detail::sdk_champion_gems(e.h, &wg) == 0)
				g = static_cast<int>(wg);
			any_wdb = true;
		}
		int ad = BIG;
		const int ai = nearest_altar(e.pos, ad);
		if (ai < 0 || ai >= 16 || ad > tune::GD_ALTAR_ADJ || g <= 0)
			continue;
		const auto i = static_cast<std::size_t>(ai);
		s_alt[i] += g;
		s_all += g;
		++n;
		if (!big[i] || g > big_g[i])
		{
			big[i] = &e;
			big_g[i] = g;
		}
	}
	if (n < 2)
		return nullptr;
	const bool end = W.tributed_them + s_all >= tune::GD_WIN_TRIBUTE;
	const bool flip = !any_wdb && W.round >= GD_LATE && W.tributed_them <= W.tributed_us && W.tributed_them + s_all >= W.tributed_us + GD_FLIP;
	if (!end && !flip)
		return nullptr;
	int bi = -1;
	for (int i = 0; i < 16; ++i)
		if (big[static_cast<std::size_t>(i)] && (bi < 0 || s_alt[static_cast<std::size_t>(i)] > s_alt[static_cast<std::size_t>(bi)]))
			bi = i;
	if (bi < 0)
		return nullptr;
	gdn_egs_flip();
	ending = end;
	NLOG("r%d slot %d EGS stack %d at altar %d (sum %d, n %d)\n", W.round, P.my_slot, s_alt[static_cast<std::size_t>(bi)], bi, s_all, n);
	return big[static_cast<std::size_t>(bi)];
}
// The channeler to stop: game-ending first, then the biggest bag. ending: it ends the game.
static __attribute__((always_inline)) inline const Body* game_deny_pick(bool& ending)
{
	const Body* t = nullptr;
	int egs_n = 0; // GDN EGS: tributing foes seen this pick
	for (const auto& e : W.enemies)
	{
		if (!(e.state & ST_TRIBUTE))
			continue;
		++egs_n;
		int g = static_cast<int>(e.gems);
		bool wdb = false;
		if (g == 0 && cheb(e.pos, W.me.pos) > tune::GD_OWN_SIGHT)
		{
			std::uint32_t wg = 0;
			if (cambc::detail::sdk_champion_gems(e.h, &wg) == 0)
				g = static_cast<int>(wg);
			wdb = true;
		}
		const bool end = W.tributed_them + g >= tune::GD_WIN_TRIBUTE;
		const bool flip = !wdb && W.round >= GD_LATE && W.tributed_them <= W.tributed_us && W.tributed_them + g >= W.tributed_us + GD_FLIP;
		if (!end && !flip) // only on a seen channel
			continue;
		if (!t || (end && !ending) || (end == ending && g > static_cast<int>(t->gems))) // a flip outranks a big
		{
			t = &e;
			ending = end;
		}
	}
	if (egs_n >= 2 && (!t || !ending)) // GDN EGS: a stack of channels that ends the game together
	{
		bool e2 = false;
		const Body* t2 = gdn_egs_pick(e2);
		if (t2 && (!t || e2))
		{
			t = t2;
			ending = e2;
		}
	}
	return t;
}
// A mate is already channelling at this altar: no lock there.
static __attribute__((always_inline)) inline bool game_deny_mate_on_altar(vec2 alt)
{
	for (const auto& al : W.allies)
		if (cheb(al.pos, alt) <= tune::GD_ALTAR_ADJ && (al.state & ST_TRIBUTE))
			return true;
	return false;
}
vec2 gdn_lock_land{ -1, -1 }; // GDN bit 2: this turn's dash landing for the lock (x < 0: none)
// GDN bit 2 GDL1: a legal landing of my ready dash within GD_LOCK_R + 1 of the altar, a free step from the lock ring when outside it.
void gdn_gdl_flip()
{
}
// GDM bit 1 GDL1a: cast_via_sdk refuses this dash landing (the same four tests), unless the pick ends the game and GDV1 skips them.
bool gdm_landing_vetoed(vec2 Lt)
{
	if (gdm_ending)
		return false;
	const int slot = W.me.kit->slot_dash;
	return kit_rules::ren_retaliation_of_cast(slot, 0u, 0u, Lt) >= eff_hp(W.me) || mv::foe_guarded(Lt) || burst::lethal_burst_landing_bad(Lt) ||
		(sph_pin && !bbget(M.my_spawn, Lt));
}
vec2 gdn_dash_lock_landing(vec2 alt)
{
	vec2 best{ -1, -1 };
	if (!W.me.kit || W.cast || W.me.kit->slot_dash < 0 || !ready(W.me.kit->slot_dash) || W.me.kit->dash_range <= 0)
		return best;
	const int dr = static_cast<int>(W.me.kit->dash_range);
	if (cheb(W.me.pos, alt) > dr + tune::GD_LOCK_R + 1)
		return best;
	int bd = BIG;
	for (int dx = -dr; dx <= dr; ++dx)
		for (int dy = -dr; dy <= dr; ++dy)
		{
			const vec2 Lt{ W.me.pos.x + dx, W.me.pos.y + dy };
			const int da = cheb(Lt, alt);
			if (Lt == W.me.pos || !inb(Lt) || da > tune::GD_LOCK_R + 1 || da >= bd || !mv::free_tile(Lt) || bbget(M.enemy_spawn, Lt))
				continue;
			bool step = da <= tune::GD_LOCK_R;
			for (int sx = -1; sx <= 1 && !step; ++sx)
				for (int sy = -1; sy <= 1 && !step; ++sy)
				{
					const vec2 St{ Lt.x + sx, Lt.y + sy };
					step = inb(St) && cheb(St, alt) <= tune::GD_LOCK_R && mv::free_tile(St);
				}
			if (!step || !dash_legal_between(W.me.pos, Lt))
				continue;
			if (gdm_landing_vetoed(Lt)) // GDM GDL1a: a landing cast_via_sdk would refuse books no lock turn
				continue;
			best = Lt;
			bd = da;
		}
	if (best.x >= 0)
		gdn_gdl_flip();
	return best;
}
static __attribute__((always_inline)) inline void game_deny_lock_way(const GameDenyGoal& p, GameDenyWays& w)
{
	gdn_lock_land = vec2{ -1, -1 };
	if (game_deny_mate_on_altar(p.alt) || locks_carried() <= 0 || cheb(p.alt, W.me.pos) > p.L + tune::GD_WALK_SLACK + tune::GD_LOCK_R)
		return;
	w.g_lock.draw_chebyshev(p.alt, static_cast<float>(tune::GD_LOCK_R));
	const int s = game_deny_walk_steps(w.g_lock, p.rad);
	if (s < BIG)
		w.t_lock = std::max(1, s);
	if (w.t_lock > 1 && (gdn_lock_land = gdn_dash_lock_landing(p.alt)).x >= 0) // GDN GDL1: dash, step, lock this turn
		w.t_lock = 1;
}
// The tiles within dash range of a legal landing tile next to the channeler. False: no landing.
static bool game_deny_dash_tiles(const GameDenyGoal& p, bitboard& g)
{
	const int dr = static_cast<int>(p.k.dash_range), rr = std::max(0, static_cast<int>(p.k.dash_radius));
	bool any = false;
	for (int dx = -rr; dx <= rr; ++dx)
		for (int dy = -rr; dy <= rr; ++dy)
		{
			const vec2 Lt{ p.tgt.pos.x + dx, p.tgt.pos.y + dy };
			if (Lt == W.me.pos || !mv::free_tile(Lt) || bbget(M.enemy_spawn, Lt))
				continue;
			g.draw_chebyshev(Lt, static_cast<float>(std::max(1, dr)));
			any = true;
		}
	if (!any)
		NLOG("r%d slot %d GDF dash no landing\n", W.round, P.my_slot);
	return any;
}
// One stunning slot: the turns until it cancels; kept when it beats the stuns so far.
static void game_deny_stun_way(const GameDenyGoal& p, GameDenyWays& w, int slot, int rng, bool excl, bool dash)
{
	if (slot < 0 || slot > 1 || rng <= 0 || p.dme > p.L + rng + tune::GD_WALK_SLACK)
		return;
	bitboard g;
	if (!dash)
		g.draw_chebyshev(p.tgt.pos, static_cast<float>(rng));
	else if (!game_deny_dash_tiles(p, g))
		return;
	const int s = game_deny_walk_steps(g, p.rad);
	if (s >= BIG)
		return;
	const int tw = (excl && s > 0) ? s + 1 : std::max(1, s);
	const int tt = std::max(tw, W.cd[static_cast<std::size_t>(slot)] + 1);
	if (tt < w.t_stun)
	{
		w.t_stun = tt;
		w.g_stun = g;
	}
}
// Cancel now if I can; game_deny's lock or stun ends the turn, game_deny_hit_after takes the free hit.
static bool game_deny_cancel(const GameDenyGoal& p, bool use_lock)
{
	const bool done = use_lock ? cheb(W.me.pos, p.alt) <= tune::GD_LOCK_R && locks_carried() > 0 && place_lock(p.alt) : game_deny_stun_channeler(p.tgt);
	if (R2G_ON(1) && done && !use_lock && gd_mem.ending && locks_carried() > 0 && cheb(W.me.pos, p.alt) <= tune::GD_LOCK_R && !bbl_our_lock_on(p.alt))
		place_lock(p.alt); // v699 R2G bit 1 GDP1: the stun cancels, our lock blocks the restart the same turn (GR:240, INT:30)
	if (R3G_ON(1) && done && !use_lock && gd_mem.ending && locks_carried() > 0 && cheb(W.me.pos, p.alt) <= tune::GD_LOCK_R && !bbl_our_lock_on(p.alt) && !cast::rga_ally_tributing(p.alt))
		place_lock(p.alt); // v703 R3G bit 1 GDP1 + RGA1: the same-turn lock, never on a mate's running tribute
	if (done)
		game_deny_hit_after();
	return done;
}
// GDN bit 2 GDL1: dash to the landing, step into the lock ring, lock. True when the dash went.
bool gdn_dash_lock_go(const GameDenyGoal& p, const bitboard& ring)
{
	if (!cast_at(W.me.kit->slot_dash, gdn_lock_land))
		return false;
	if (cheb(W.me.pos, p.alt) > tune::GD_LOCK_R && W.can_move())
		mv::step_to_set(ring, 2);
	game_deny_cancel(p, true);
	return true;
}
// DLK 1 (caller read the flag): true when I hold instead of locking (and took the hold step, if any). Lethal = danger_veto's sum (each
// foe's one-turn burst in its reach, its two-turn hit when it has two turns, awake camps) >= my effective HP; the per-foe hit is computed
// once per distance (a small memo), so the up to 34 tiles cost a few calls a foe, not a danger_veto each.
struct DlkFoe
{
	const Foe* f;
	const Body* e;
	int r2;
	float hit[10];
	bool have[10];
};
static float dlk_foe_hit(DlkFoe& x, int dt)
{
	const Foe& f = *x.f;
	if (dt > std::max(f.reach, x.r2))
		return 0.0f;
	const int k = std::min(dt, 9);
	if (x.have[k])
		return x.hit[k];
	float h;
	if (x.r2 >= 0 && x.e && dt > f.reach)
		h = burst::foe_two_turn_damage(*x.e, dt, 0.0f);
	else
		h = x.r2 >= 0 && x.e ? std::max(f.burst, burst::foe_two_turn_damage(*x.e, dt, burst::lethal_burst_hit(*x.e, dt, 0, nullptr))) : f.burst;
	x.hit[k] = h;
	x.have[k] = true;
	return h;
}
static __attribute__((noinline)) bool dlk_hold(const Assessment& a, const GameDenyWays& w, int left, vec2 tp, vec2 alt, int dme, int L, bool stunnable)
{
	if (left <= DLK_TAB[2])
		return false;
	DlkFoe fs[8];
	int nf = 0;
	for (const auto& f : a.foes)
	{
		if (f.reach < 0 || nf >= 8)
			continue;
		DlkFoe& x = fs[nf++];
		x.f = &f;
		x.e = nullptr;
		x.r2 = geom::foe_two_turn_reach(f, &x.e);
		for (bool& h : x.have)
			h = false;
	}
	auto danger = [&](vec2 t)
	{
		float d = mv::camp_threat(t);
		for (int i = 0; i < nf; ++i)
			d += dlk_foe_hit(fs[i], cheb(t, fs[i].f->pos));
		return d;
	};
	const float me = eff_hp(W.me);
	const int r = tune::GD_LOCK_R;
	for (int x = alt.x - r; x <= alt.x + r; ++x)
		for (int y = alt.y - r; y <= alt.y + r; ++y)
		{
			const vec2 t{ x, y };
			if (x < 0 || y < 0 || x >= M.w || y >= M.h || !bbget(w.g_lock, t) || (t != W.me.pos && !mv::free_tile(t)))
				continue;
			if (danger(t) < me)
				return false; // a lock tile I survive on: lock as usual
		}
	if (left <= w.t_lock + 2 && game_deny_mates_ahead(tp, alt, dme, L, stunnable) == 0)
		return false; // nobody else can deny in time
	// Hold: the least dangerous of my tile and its free neighbours, ties to the nearer one to the altar.
	vec2 best = W.me.pos;
	float bd = danger(W.me.pos);
	if (W.can_move() && bd >= me)
		for (int dx = -1; dx <= 1; ++dx)
			for (int dy = -1; dy <= 1; ++dy)
			{
				const vec2 t{ W.me.pos.x + dx, W.me.pos.y + dy };
				if ((dx == 0 && dy == 0) || t.x < 0 || t.y < 0 || t.x >= M.w || t.y >= M.h || !mv::free_tile(t))
					continue;
				const float dv = danger(t);
				if (dv < bd || (dv == bd && cheb(t, alt) < cheb(best, alt)))
				{
					bd = dv;
					best = t;
				}
			}
	if (best != W.me.pos)
		mv::try_move(best);
	return true;
}
__attribute__((noinline)) bool game_deny_slow(const Assessment& a)
{
	bool ending = false;
	const Body* t = game_deny_pick(ending);
	if (!t)
	{
		return (gd_mem.until >= W.round + 1 && game_deny_follow_channel(a)) || nova::combat::deny_memory::act(a);
	}
	if (!ending && a.stance == FLEE)
		return false;
	std::int32_t left = -1;
	if (cambc::detail::sdk_champion_channel_time(t->h, &left) != 0 || left < (0))
	{
		if (!((R2G_ON(1) || R3G_ON(1)) && ending && r2g_stun_h == t->h && r2g_stun_r == W.round)) // v703 R3G bit 1 ESL1 (b)
			return false;
		left = 1; // v699 R2G bit 1 ESL1: the carrier end_stun just stunned: cancelled, noted, and the lock way still taken
	}
	gd_mem.h = t->h;
	gd_mem.pos = t->pos;
	gd_mem.set = W.round;
	gd_mem.until = W.round + static_cast<int>(left) + (RGS_ON(8) && (t->state & FLEE_FIX_ST_ACTED) != 0 ? 1 : 0); // RGS bit 8: a foe that already took its turn lands a round later
	gd_mem.ending = ending;
	const Body tgt = *t;
	int ad = BIG;
	const int ai = nearest_altar(tgt.pos, ad);
	if (ai < 0 || ad > tune::GD_ALTAR_ADJ)
		return false;
	const vec2 alt = M.altars[static_cast<std::size_t>(ai)].pos;
	if (ending)
		nova::combat::deny_memory::note(tgt, alt, gd_mem.until);
	const int dme = cheb(tgt.pos, W.me.pos);
	const int L = std::max(1, static_cast<int>(left) + ((tgt.state & FLEE_FIX_ST_ACTED) != 0 ? 1 : 0));
	if (dme > L + tune::GD_TOO_FAR_SLACK)
		return false;
	// The nearest GD_BODIES bodies go.
	const bool stunnable = !marcella_layer::fight_stun_wasted(tgt) && !(R3G_ON(1) && r2g_stun_h == tgt.h && r2g_stun_r == W.round); // v703 R3G bit 1 RGS1: its stun is pending (no stacking)
	if (game_deny_mates_ahead(tgt.pos, alt, dme, L, stunnable) >= GD_BODIES)
		return false;
	const Kit& k = *W.me.kit;
	const GameDenyGoal p{ k, tgt, alt, dme, L, std::min(GD_RAD, L + tune::GD_WALK_SLACK) };
	GameDenyWays w;
	gdm_ending = ending; // GDM GDL1a: the landing search knows whether GDV1 will skip the vetoes
	game_deny_lock_way(p, w);
	if (stunnable)
	{
		game_deny_stun_way(p, w, k.slot_cc, static_cast<int>(k.cc_range), k.cc_excl, false);
		if (k.aoe_stun)
			game_deny_stun_way(p, w, k.slot_aoe, static_cast<int>(k.aoe_range + k.aoe_radius), k.aoe_excl, false);
		if (k.dash_stun)
			game_deny_stun_way(p, w, k.slot_dash, static_cast<int>(k.dash_range + k.dash_radius), false, true);
	}
	const bool lock_ok = w.t_lock <= L, stun_ok = w.t_stun <= L;
	if (!lock_ok && !stun_ok)
		return false;
	const bool use_lock = lock_ok && (!stun_ok || w.t_lock <= w.t_stun);
	if (ending && use_lock && dlk_hold(a, w, static_cast<int>(left), tgt.pos, alt, dme, L, stunnable))
		return true; // DLK 1: no early lock that kills the placer; hold off its reach
	const bitboard& goal = use_lock ? w.g_lock : w.g_stun;
	gdn_end_cast = ending; // GDN GDV1: a game-ending cancel skips cast_via_sdk's vetoes
	bool acted = game_deny_cancel(p, use_lock); // v683 HLD bit 4
	gdn_end_cast = false;
	if (!acted && use_lock && gdn_lock_land.x >= 0)
	{
		gdn_end_cast = ending;
		if (gdn_dash_lock_go(p, w.g_lock)) // GDN GDL1
			acted = true;
		gdn_end_cast = false;
	}
	const mv::SuspendFoeGuard bbm_sg(false); // BBM MF3: the game-ending deny walk ignores the foe guard
	if (!acted && W.can_move() && !bbget(goal, W.me.pos) && mv::step_to_set(goal, p.rad))
	{
		acted = true;
		gdn_end_cast = ending; // GDN GDV1
		game_deny_cancel(p, use_lock);
		gdn_end_cast = false;
	}
	if (!acted && bbget(goal, W.me.pos) && (nova::combat::deny_hold::hld_hold_lethal(use_lock ? w.t_lock : w.t_stun, tgt.h, ending)))
		return false; // no hold under FLEE, nor on a tile the foes kill me on before the deny is ready
	if (!acted)
		acted = bbget(goal, W.me.pos); // in place and waiting for the cooldown: hold (the turn's other logic would walk away)
	if (acted && !W.attacked) // a hold or a step without the cancel keeps the free hit
		game_deny_hit_after();
	NLOG("r%d slot %d GAME_DENY %s gems %u left %d tl %d ts %d acted %d\n", W.round, P.my_slot,
		use_lock ? "lock" : "stun", tgt.gems, L, w.t_lock, w.t_stun, static_cast<int>(acted));
	return acted;
}
} // namespace
} // namespace deny
int alh_locks() { return deny::locks_carried(); }
void buy_altar_lock()
{
	if (W.gold < 10 || W.round < 40 || M.altars.empty())
		return;
	if (deny::locks_carried() > 0)
		return;
	if (static_cast<int>(W.me.gems) < LL_BAG && !(deny::game_deny_lock_wanted()))
		return; // no bank trip planned (a lock for a big enemy bag)
	cancel_spin_before_action();
	if (cambc::detail::sdk_buy_consumable(RAW_LOCK) == 0)
	{
		W.gold -= 10;
		deny::lock_known = 1;
		deny::lock_checked = W.round;
		NLOG("r%d slot? bought altar lock\n", W.round);
	}
}
// The first early-out test inline at the call site (a call and frame a turn saved), the rest out of line.
__attribute__((always_inline)) bool deny_tribute()
{
	if (M.altars.empty() || W.enemies.empty() || W.me.channeling())
		return false;
	return deny::deny_tribute_slow();
}
bool protect_tribute(vec2 altar, int gems)
{
	// The tribute that ends the game is always locked first (an enemy lock would cancel it).
	const bool winning = W.tributed_us + gems >= rs::WIN_TRIBUTE;
	if ((gems < 30 && !winning) || deny::locks_carried() <= 0)          // winning
		return false;
	const AltarI* ai = nullptr;
	for (const auto& a : M.altars)
		if (a.pos == altar)
			ai = &a;
	if (!ai)
		return false;
	const bool shared = ai->d_home != UNREACH && ai->d_enemy != UNREACH &&
		std::abs(static_cast<int>(ai->d_home) - static_cast<int>(ai->d_enemy)) <= 5;
	if (!shared)
		return false; // CB3 bit 128 PTF (INT:118): our lock does not stop a foe lock; it only blocks foe tributes, and those come at a shared altar
	// A new lock cancels every channel at that altar, ours included.
	for (const auto& al : W.allies)
		if (al.channeling() && cheb(al.pos, altar) <= 1)
			return false;
	try
	{
		if (cambc::vision::has_altar_lock(altar))
			return false; // ours already, or an enemy's (the tribute code breaks it)
	}
	catch (...)
	{
		FXR_PASS();
		return false;
	}
	std::int32_t ok = 0;
	cancel_spin_before_action();
	const auto code = cambc::detail::sdk_use_consumable(RAW_LOCK, altar.x, altar.y, &ok);
	deny::lock_known = -1;
	if (code == 0 && ok)
	{
		NLOG("r%d lock placed on %d,%d (own tribute %d gems)\n", W.round, altar.x, altar.y, gems);
		return true;
	}
	return false;
}
// ---------------------------------------------------------------- HUNT: enemy gem carriers

float hunt_prize(const Body& e)
{
	const float g = static_cast<float>(e.gems);
	if ((ci_layer::type(e.type)))
	{
		// a linked pair dies together and the killer takes BOTH bags (GameRules:438-442)
		const auto want = ci_layer::partner(e.type);
		for (const auto& o : W.enemies)
			if (&o != &e && o.type == want)
			{
				KIT_RULE_FIX_CNT(8, o.gems > 0);
				return g + static_cast<float>(o.gems);
			}
	}
	return prism_layer::type(e.type) ? 2.0f * g : g;
}
// The first early-out test inline at the call site (a call and frame a turn saved), the rest out of line.
__attribute__((always_inline)) bool game_deny(const Assessment& a)
{
	if (!W.alive || W.me.channeling() || M.altars.empty() || !W.me.kit)
		return false;
	return deny::game_deny_slow(a);
}
} // namespace nova::combat

// ---- survival test for holding a deny. Reached only when its flag is on (game_deny_slow).
namespace nova::combat::deny_hold
{
namespace bu = ::nova::combat::burst;
// v683 HLD bits 1/2 (called with the flag read first): hold_lethal without the over-count.
bool hld_hold_lethal(int t, decltype(Body::h) tgt_h, bool ending)
{
	if (ending)
		return false; // bit 1: walking away from a game-ending channel loses anyway (GR:29)
	const int wait = std::min(12, std::max(0, t - 1));
	const float cap = bu::lb_cap();
	float s = 0.0f;
	for (const auto& e : W.enemies)
	{
		if (e.h == tgt_h)
			continue; // bit 1: the channeler hits me only by cancelling its own tribute (GR:275, INT:125)
		const int d = cheb(e.pos, W.me.pos);
		if (d > 9)
			continue;
		for (int k = (bu::foe_stunned_next_turn(e) ? 1 : 0); k <= wait; ++k)
			s += std::max(0.0f, bu::lethal_burst_hit(e, d, k, nullptr));
		if (s >= cap)
			return true;
	}
	return false;
}
} // namespace nova::combat::deny_hold

// ---- keep denying after a game-ending tribute is cancelled. Reached only when its flag is on (game_deny_slow).
namespace nova::combat::deny_memory
{
namespace
{
struct GebMem
{
	std::uint32_t h = 0;
	vec2 alt{ -1, -1 }, pos{ -1, -1 };
	int bag = 0, set = -1000, until = -1000;
};
GebMem m;
} // namespace
void note(const Body& t, vec2 alt, int until)
{
	m.h = t.h;
	m.alt = alt;
	m.pos = t.pos;
	m.bag = static_cast<int>(t.gems);
	m.set = W.round;
	m.until = until + GEB_TAB[2];
}
bool act(const nova::combat::Assessment& a)
{
	using namespace nova::combat::deny;
	const int now = W.round;
	if (m.until < now || m.alt.x < 0)
		return false;
	if (intel::foe_died_round(m.h) >= m.set)
	{
		m.until = -1000;
		return false;
	}
	const Body* k = nullptr;
	for (const auto& e : W.enemies)
		if (e.h == m.h)
			k = &e;
	if (k)
	{
		int g = static_cast<int>(k->gems);
		if (g == 0 && cheb(k->pos, W.me.pos) > 9)
		{
			std::uint32_t wg = 0;
			if (cambc::detail::sdk_champion_gems(k->h, &wg) == 0)
				g = static_cast<int>(wg);
		}
		if (W.tributed_them + g < rs::WIN_TRIBUTE)
		{
			m.until = -1000; // banked, dropped or spent: the entry no longer counts as ending
			return false;
		}
		m.pos = k->pos;
		m.bag = g;
	}
	if (cheb(m.pos, m.alt) > GEB_NEAR || a.stance == nova::combat::FLEE)
		return false;
	const int left = m.until - now;
	const bool stunnable = !k || !marcella_layer::fight_stun_wasted(*k);
	const int dA = cheb(W.me.pos, m.alt);
	if (dA <= 2)
	{
		return false;
	}
	if (!W.can_move())
		return false;
	if (!game_deny_can_cancel_channel(W.me, true, m.pos, m.alt, left, stunnable))
		return false;
	if (game_deny_mates_ahead(m.pos, m.alt, cheb(m.pos, W.me.pos), left, stunnable) >= GD_BODIES)
		return false;
	bitboard g;
	g.draw_chebyshev(m.alt, 2.0f);
	const int s = game_deny_walk_steps(g, std::min(GD_RAD, left + 2));
	if (s >= BIG || (s > left)) // GDN GDL1: a ready dash saves its range; GDM GDL1b: not here
		return false;
	const mv::SuspendFoeGuard bbm_sg(false); // BBM MF3: deny_memory holds game-ending tributes only
	if (!mv::step_to_set(g, std::min(GD_RAD, left + 2)))
		return false;
	NLOG("r%d slot %d GEB walk left %d walk %d\n", now, P.my_slot, left, s);
	return true;
}
} // namespace nova::combat::deny_memory
namespace nova::combat
{
} // namespace nova::combat
namespace nova::combat {
// FB5 TRG1: game_deny_slow's no-pick return can act only while one of these holds.
bool game_deny_memory_live()
{
	return deny::gd_mem.until >= W.round + 1 || (deny_memory::m.until >= W.round && deny_memory::m.alt.x >= 0);
}
} // namespace nova::combat
