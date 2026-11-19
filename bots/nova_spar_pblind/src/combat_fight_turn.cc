// combat_fight_turn.cc: FIGHT turn variants and the fight entry point.
#include "combat_internal.h"
namespace nova::combat {
namespace fight_turn {
namespace {
__attribute__((noinline)) bool retreat_to_spawn_to_heal_slow(const Assessment& a)
{
	if (!W.alive || !M.ready() || W.me.channeling() || econ::capture_pay_in() >= 0)
		return false;
	const int bits = SP_TAB[1];
	const float cap = flee_turn::refuge_burst_cap();
	if (W.on_spawn)
	{
		if (flee_turn::sru_in(a.incoming) >= cap)
			return false;
	}
	else
	{
		if ((bits & (a.nearest <= tune::SP_NEAR_D ? 1 : 4)) == 0 || !W.can_move())
			return false;
		for (const auto& e : W.enemies)
			if (KQ_SITE(2, burst::kills(e, cheb(e.pos, W.me.pos), KQ_BASIC), cheb(e.pos, W.me.pos) <= W.me.range && eff_hp(e) <= W.me.str))
				return false; // a kill from here goes first (x passive_mult, with the attack allowance)
		const vec2 dest = flee_turn::refuge_tile(cap, true, [&](vec2 n) __attribute__((always_inline)) { return flee_turn::tile_danger(a, n); });
		if (dest.x < 0 || !mv::try_move(dest))
			return false;
	}
	flee_turn::refuge_hit_back();
	if (W.on_spawn && econ::ss_live && W.can_attack())
		econ::spawn_siege_turn(false);
	cast::free_aoe();
	return true;
}
} // namespace
// The foe a body hits on its way out: the weakest in my range whose retaliation would not kill me.
static __attribute__((always_inline)) inline const Body* flee_hit_target()
{
	return flee_turn::weakest_foe_where([](const Body& e) { return flee_turn::in_my_range(e) && !ren_kills_me(e); });
}
// What a flee leaves for continue_retreat.
static __attribute__((always_inline)) inline void note_retreat(const std::vector<mv::Threat>& zones)
{
	turn_memory.retreat_from = zones;
	turn_memory.retreat_until = W.round + tune::RETREAT_ROUNDS;
}
static __attribute__((always_inline)) inline bool shield_ready(const Kit& k) { return k.slot_shield >= 0 && ready(k.slot_shield) && W.me.shield <= 0; }
namespace {
static __attribute__((always_inline)) inline float escape_dash_damage_at(const EdCtx& c, vec2 t)
{
	float sum = 0;
	for (std::size_t x = 0; x < W.enemies.size() && x < c.nn.size(); ++x)
	{
		const Body& e = W.enemies[x];
		const int d = cheb(e.pos, t);
		if (cheb(e.pos, c.me) > tune::ED_FOE_R || d > tune::ED_HIT_DISTS - 1)
			continue;
		float& v = c.hit[x][static_cast<std::size_t>(d)];
		if (v < 0)
			v = burst::foe_damage_over_turns(e, d, c.nn[x]);
		sum += v;
	}
	return sum;
}
// A safe step home exists: the usual branches walk it.
static __attribute__((always_inline)) inline bool escape_dash_can_walk(const EdCtx& c)
{
	for (const vec2 dd : DIRS)
	{
		const vec2 t = c.me + dd;
		if (!mv::free_tile(t) || escape_dash_damage_at(c, t) >= c.cap || mv::camp_threat(t) > 0)
			continue;
		if (mv::home_steps(t) < BIG)
			return true;
	}
	return false;
}
// The safe tile nearest home at the end of a dash + step, not one of the bad ones.
static __attribute__((always_inline)) inline vec2 escape_dash_end_tile(const EdCtx& c, int rr, const std::array<vec2, tune::ED_TRIES>& bad)
{
	int best = BIG;
	vec2 u{ -1, -1 };
	for (int dx = -rr; dx <= rr; ++dx)
		for (int dy = -rr; dy <= rr; ++dy)
		{
			const vec2 t{ c.me.x + dx, c.me.y + dy };
			if (std::max(std::abs(dx), std::abs(dy)) < tune::ED_END_MIN_R || !mv::free_tile(t) || t == bad[0] || t == bad[1] || t == bad[2])
				continue;
			if (!(escape_dash_damage_at(c, t) < c.cap))
				continue;
			const int g = mv::home_steps(t);
			if (g < best)
			{
				best = g;
				u = t;
			}
		}
	return u;
}
// The first landing one step from u that the dash reaches.
static __attribute__((always_inline)) inline vec2 escape_dash_landing(const EdCtx& c, vec2 u, int r)
{
	for (int dx = -1; dx <= 1; ++dx)
		for (int dy = -1; dy <= 1; ++dy)
		{
			const vec2 t{ u.x + dx, u.y + dy };
			const int d = cheb(t, c.me);
			if (d < 1 || d > r || !mv::free_tile(t) || (d == 2 && !geom::dash_middle_tile_ok(c.me, t)))
				continue;
			return t;
		}
	return { -1, -1 };
}
// The tile I end on (dash + step), then a landing for it; the dearer checks only for the choice. False: no escape found.
static __attribute__((always_inline)) inline bool escape_dash_find(const EdCtx& c, vec2& land, vec2& step)
{
	const Kit& k = c.k;
	const int r = std::max(1, static_cast<int>(k.dash_range));
	std::array<vec2, tune::ED_TRIES> bad;
	bad.fill({ -1, -1 });
	for (int tries = 0; tries < tune::ED_TRIES && fuel() > tune::ED_TRY_MIN_FUEL; ++tries)
	{
		const vec2 u = escape_dash_end_tile(c, r + 1, bad);
		if (u.x < 0)
			return false;
		const vec2 l = escape_dash_landing(c, u, r);
		if (l.x >= 0 && mv::camp_threat(u) <= 0 && mv::camp_threat(l) <= 0 &&
			!(k.dash_mod > 0 && camps::wakes_other_group(l, static_cast<int>(k.dash_radius), l, -1, 0.0f)))
		{
			land = l;
			step = u;
			return true;
		}
		bad[static_cast<std::size_t>(tries)] = u;
	}
	return false;
}
// Sets the retreat the dash starts and takes the parting hit first (not on a Ren whose retaliation would kill me).
static __attribute__((always_inline)) inline void escape_dash_leave(const EdCtx& c, bool ed_dash = true)
{
	turn_memory.last_flee_round = W.round;
	std::vector<mv::Threat> zones = geom::zones_of(c.a);
	geom::add_camp_zones(zones);
	turn_memory.retreat_from = zones;
	turn_memory.retreat_until = W.round + tune::ED_RETREAT_ROUNDS;
	if (c.k.ranged || !W.can_attack())
		return;
	const Body* adj = nullptr;
	for (const auto& e : W.enemies)
		if (cheb(e.pos, c.me) <= W.me.range && !(ren_layer::kills_me(e)) && (!adj || eff_hp(e) < eff_hp(*adj)))
			adj = &e;
	if (adj)
	{
		const Body target = *adj;
		bh57_noreset = static_cast<bool>(ed_dash); // the dash needs the turn's cast (ed_dash false: the walk)
		attack_champion(target);
		bh57_noreset = false;
	}
}
__attribute__((noinline)) bool escape_dash_turn_slow(const Assessment& a)
{
	if (!slot_up(W.me.kit->slot_dash))
		return false;
	if (a.stance != FLEE && W.me.frac() >= static_cast<float>(B438_LOWHP_X100) / 100.0f)
		return false;
	std::array<int, 12> nn;
	nn.fill(tune::ED_WORST_FOE_TURNS);
	const float cap = burst::lb_cap();
	const vec2 me = W.me.pos;
	if (burst::foes_damage_at_tile(me, nn) < cap)
		return false; // the worst case of turn order is not lethal here
	burst::foe_turn_counts_fill(nn);
	if (fuel() < tune::ED_MIN_FUEL || burst::foes_damage_at_tile(me, nn) < cap)
		return false;
	const Kit& k = *W.me.kit;
	EdHits hit;
	for (auto& h : hit)
		h.fill(-1.0f);
	const EdCtx c{ a, k, me, cap, nn, hit };
	if (escape_dash_can_walk(c) || fuel() < tune::ED_SEARCH_MIN_FUEL)
		return false;
	vec2 land{ -1, -1 }, step{ -1, -1 };
	if (!escape_dash_find(c, land, step))
		return false;
	escape_dash_leave(c);
	if (!cast_at(k.slot_dash, land))
		return false;
	if (!(step == land) && W.can_move())
		mv::try_move(step);
	return true;
}
static __attribute__((always_inline)) inline void crystal_escape_near_foes(CrxNear& n)
{
	for (const auto& e : W.enemies)
	{
		const int d = cheb(e.pos, W.me.pos);
		n.d_min = std::min(n.d_min, d);
		if (d > tune::CRX_NEAR_R)
			continue;
		if (n.nn < tune::CRX_NEAR_N)
			n.near[static_cast<std::size_t>(n.nn++)] = &e;
		else
		{
			std::size_t far = 0;
			for (std::size_t i = 1; i < n.near.size(); ++i)
				if (cheb(n.near[i]->pos, W.me.pos) > cheb(n.near[far]->pos, W.me.pos))
					far = i;
			if (d < cheb(n.near[far]->pos, W.me.pos))
				n.near[far] = &e;
		}
	}
}
// Each near foe's walk: a dash that is ready in time crosses holes. My spawn is closed to foes, theirs open.
static __attribute__((always_inline)) inline void crystal_escape_fields(const CrxNear& n, CrxFields& ff)
{
	const bitboard b_walls = M.walls | M.altars_bb | M.my_spawn;
	const bitboard b_holes = b_walls | M.holes;
	for (int i = 0; i < n.nn; ++i)
	{
		const Body& e = *n.near[static_cast<std::size_t>(i)];
		const int sd = e.kit && e.kit->valid ? e.kit->slot_dash : -1;
		const bool dasher = !e.kit || !e.kit->valid || foe_ready(e, sd, tune::CRX_DASH_READY_TURNS);
		bitboard visited, root;
		bbset(root, e.pos);
		auto f = std::make_unique<distance_field>();
		f->compute((dasher ? b_walls : b_holes) & ~root, root, visited);
		ff[static_cast<std::size_t>(i)] = std::move(f);
	}
}
// The steps the nearest of them needs to t.
static __attribute__((always_inline)) inline int crystal_escape_walk(const CrxFields& ff, int nn, vec2 t)
{
	int best = BIG;
	for (int i = 0; i < nn; ++i)
	{
		const int v = dfget(*ff[static_cast<std::size_t>(i)], t);
		best = std::min(best, v == UNREACH ? tune::CRX_UNREACHED : v);
	}
	return best;
}
// What a landing at t is worth, given the extra steps the foes need to it.
static __attribute__((always_inline)) inline int crystal_escape_score(const Assessment& a, vec2 t, int extra, int h0)
{
	int score = tune::CRX_SCORE_PER_STEP * std::min(extra, tune::CRX_SCORE_STEPS_MAX);
	for (const auto& f : a.foes)
		if (cheb(f.pos, t) <= f.reach)
			score -= tune::CRX_SCORE_IN_REACH; // still in a known foe's reach on landing
	const int h = mv::home_steps(t);
	if (h != UNREACH && h0 != UNREACH)
		score += std::max(-tune::CRX_SCORE_HOME_MAX, std::min(tune::CRX_SCORE_HOME_MAX, h0 - h)); // toward home
	if (bbget(M.my_spawn, t))
		score += tune::CRX_SCORE_MY_SPAWN;
	for (const auto& al : W.allies)
		if (al.frac() > tune::CRX_MATE_FRAC && cheb(al.pos, t) <= tune::CRX_MATE_R)
		{
			score += tune::CRX_SCORE_MATE; // toward a healthy mate
			break;
		}
	return score;
}
// The best landing first; one a hidden body refuses is dropped and the next tried.
static __attribute__((always_inline)) inline bool crystal_escape_jump(std::array<CrxLand, tune::CRX_LANDINGS_MAX>& land, int nl)
{
	for (int tries = 0; tries < tune::CRX_TRIES && nl > 0; ++tries)
	{
		int b = 0;
		for (int i = 1; i < nl; ++i)
			if (land[static_cast<std::size_t>(i)].score > land[static_cast<std::size_t>(b)].score)
				b = i;
		const vec2 t = land[static_cast<std::size_t>(b)].t;
		bool hidden = false;
		if (econ::use_crystal_consumable(t, &hidden))
		{
			turn_memory.retreat_until = W.round + tune::CRX_RETREAT_ROUNDS;
			NLOG("r%d slot %d CRX %d,%d -> %d,%d hp %.0f\n", W.round, P.my_slot, W.me.pos.x, W.me.pos.y, t.x, t.y, W.me.hp);
			return true;
		}
		if (!hidden)
			return false;
		land[static_cast<std::size_t>(b)] = land[static_cast<std::size_t>(--nl)];
	}
	return false;
}
} // namespace
// The crystal escape. Flag read by the caller; the cheap tests first, then one host field per near foe.
static bool crystal_escape_turn(const Assessment& a)
{
	const Kit* kp = W.me.kit;
	if (!kp || W.on_spawn || W.me.channeling() || W.me.stunned || W.me.frac() * 100.0f >= static_cast<float>(CRX_TAB[2]))
		return false;
	CrxNear n;
	crystal_escape_near_foes(n);
	if (n.d_min > tune::CRX_CAUGHT_R || n.nn == 0)
		return false;
	float camp_dmg = 0;
	if (!econ::crystal_use_ready(&camp_dmg) || (fuel() < tune::CRX_FUEL_PER_TILE * n.nn * G.w * G.h + tune::CRX_FUEL_FLOOR && (nbf_fc_4(), true)) || !channel_safe(0, VBC_ON(8) ? 3 : tune::CRX_BUS_TICKS, camp_dmg, true)) // v7xx NBF bit 4 CRF1: :297's test first
		return false;
	if (fuel() < tune::CRX_FUEL_PER_TILE * n.nn * G.w * G.h + tune::CRX_FUEL_FLOOR)
		return false;
	// The free landings outside camp threat first (they need no field): none, no field is built.
	const std::vector<mv::Threat> camps = mv::camp_threats_near(tune::CRX_CAMP_R);
	std::array<vec2, tune::CRX_LANDINGS_MAX> cand;
	int nc = 0;
	for (int dx = -tune::CRX_JUMP_R; dx <= tune::CRX_JUMP_R; ++dx)
		for (int dy = -tune::CRX_JUMP_R; dy <= tune::CRX_JUMP_R; ++dy)
		{
			const vec2 t{ W.me.pos.x + dx, W.me.pos.y + dy };
			if ((dx == 0 && dy == 0) || !inb(t) || !mv::free_tile(t) || mv::in_threat(camps, t))
				continue;
			cand[static_cast<std::size_t>(nc++)] = t;
		}
	if (nc == 0)
		return false;
	CrxFields ff;
	crystal_escape_fields(n, ff);
	const int w0 = crystal_escape_walk(ff, n.nn, W.me.pos);
	const int h0 = mv::home_steps(W.me.pos);
	std::array<CrxLand, tune::CRX_LANDINGS_MAX> land{};
	int nl = 0;
	for (int i = 0; i < nc; ++i)
	{
		const vec2 t = cand[static_cast<std::size_t>(i)];
		const int extra = crystal_escape_walk(ff, n.nn, t) - w0;
		if (extra >= CRX_TAB[3])
			land[static_cast<std::size_t>(nl++)] = CrxLand{ t, crystal_escape_score(a, t, extra, h0) };
	}
	return crystal_escape_jump(land, nl);
}
namespace {
__attribute__((noinline)) bool self_shield_after_hit_turn_slow()
{
	const Kit& k = *W.me.kit;
	if (k.slot_shield < 0 || heart_layer::fight_skip_vsh(k) || !took_damage(1) || W.me.shield > 0 || W.me.channeling() || !ready(k.slot_shield))
		return false;
	bool hit = false;
	for (const auto& s : seen)
	{
		const int age = W.round - s.round;
		if (age < 0 || age > 1)
			continue;
		if (cheb(s.foe.pos, W.me.pos) <= std::max(0, s.foe.reach) + 1)
		{
			hit = true;
			break;
		}
	}
	if (!hit)
		return false;
	return cast_self(k.slot_shield);
}
} // namespace
} // namespace fight_turn
// v695 BHW bit 1: the refused step turned 45 degrees each way, after the hold is released.
static bool bhw_resume()
{
	if (!W.alive || W.me.channeling() || W.moved || !W.can_move() || static_cast<int>(round_number_nc()) != W.round)
		return false;
	const int dx = mv::bsh_tile.x - W.me.pos.x, dy = mv::bsh_tile.y - W.me.pos.y;
	if (std::max(std::abs(dx), std::abs(dy)) != 1)
		return false;
	const auto sg = [](int v) { return v > 0 ? 1 : (v < 0 ? -1 : 0); };
	const vec2 r1{ W.me.pos.x + sg(dx - dy), W.me.pos.y + sg(dx + dy) }, r2{ W.me.pos.x + sg(dx + dy), W.me.pos.y + sg(dy - dx) };
	for (const vec2 t : { r1, r2 })
		if (inb(t) && mv::free_tile(t) && mv::try_move(t))
			return true;
	return false;
}
void bush_hold_turn()
{
	mv::bush_hold_release();
	if (!W.alive || W.me.channeling() || fuel() < BSH_TAB[2] || static_cast<int>(round_number_nc()) != W.round)
	{
		if (W.alive && !W.me.channeling() && fuel() < BSH_TAB[2] && W.can_attack() && static_cast<int>(round_number_nc()) == W.round)
		{
			Body b;
			if (foe_body_at(mv::bsh_tile, b))
				attack_champion(b);
		}
		bhw_resume(); // v695 BHW bit 1
		return;
	}
	const bool lm = W.moved, la = W.attacked, lc = W.cast, ln = W.no_move;
	perceive(); // perceive clears the turn's action flags
	W.moved = lm;
	W.attacked = la;
	W.cast = lc;
	W.no_move = ln;
	mv::bush_hold_release();
	// The next turn's assess remembers the foe even if it stays out of sight (observe's sighting record).
	for (const auto& e : W.enemies)
	{
		if (cheb(e.pos, W.me.pos) > 10)
			continue;
		Seen* s = nullptr;
		for (auto& x : seen)
			if (x.h == e.h)
				s = &x;
		if (!s)
		{
			seen.push_back({});
			s = &seen.back();
			s->h = e.h;
		}
		s->round = W.round;
		s->rec = (e.state & ST_RECALL) != 0;
		s->foe = (e.stunned) ? foe_of_unstunned(e, -1) : foe_of(e, -1); // CB3 bit 32 R1
	}
	const Assessment a = assess();
	if (a.stance == FIGHT && a.focus >= 0)
		fight(a);
	else if (a.stance == FLEE)
		flee(a);
	else bhw_resume(); // v695 BHW bit 1: a calm read resumes the walk
	if (W.can_attack())
	{
		for (const auto& e : W.enemies)
			if (cheb(e.pos, W.me.pos) <= W.me.range && attack_champion(e))
				break;
	}
}
// the last tile of a foe seen 1..BSX_AGE rounds ago within 8 of me that is out of sight now and stood on or next to a bush tile I do
// not see (the nearest such foe). {-1,-1}: none.
vec2 vanished_foe_last_tile()
{
	vec2 best{ -1, -1 };
	if (seen.empty() || memory::bkc_bushy == 0) // FB5 WBV1: no sighting, or no bush on the map
		return best;
	if (!W.alive || W.me.channeling() || fuel() < BSX_TAB[4])
		return best;
	int bd = 99;
	const vec2 me = W.me.pos;
	for (const auto& s : seen)
	{
		const int age = W.round - s.round;
		const int d = cheb(s.foe.pos, me);
		if (age < 1 || age > BSX_TAB[2] || d > 8 || d >= bd)
			continue;
		bool vis = false;
		for (const auto& e : W.enemies)
			vis = vis || e.h == s.h;
		if (vis)
			continue;
		bool unlit = false;
		for (int dx = -1; dx <= 1 && !unlit; ++dx)
			for (int dy = -1; dy <= 1 && !unlit; ++dy)
			{
				const vec2 q{ s.foe.pos.x + dx, s.foe.pos.y + dy };
				unlit = inb(q) && bbget(M.bushes, q) && !bbget(W.vis, q);
			}
		if (!unlit)
			continue;
		bd = d;
		best = s.foe.pos;
	}
	return best;
}
bool fight(const Assessment& a)
{
	AF_CHECK();
	if (a.focus < 0)
		return false;
	const int bbm_lfr = turn_memory.last_fight_round; // BBM MF2: restored when the turn did nothing
	turn_memory.last_fight_round = W.round;
	const Kit& k = *W.me.kit;
	const Body f = W.enemies[static_cast<std::size_t>(a.focus)];
	fight_turn::FightCtx c{ a, k, f, cheb(W.me.pos, f.pos), static_cast<int>(k.cc_range), static_cast<int>(k.dash_range), static_cast<int>(k.dmg_range) };
	// Hurt on my spawn, the heal at my turn end beats any walk off it: fight from the spawn (hits from the tile, spawn steps and
	// landings) unless the fight is sure or my burst kills the focus.
	const bool sph_p = false && W.on_spawn && (W.me.maxhp - W.me.hp) * 100.0f >= static_cast<float>(SPH_TAB[3]) * W.me.maxhp &&
		a.ratio * 100.0f < static_cast<float>(SPH_TAB[4]) && !burst::kills(f, c.d, KQ_RAW);
	SPH_CNT(4, sph_p);
	const SphPinGuard sph_g(sph_p);
	c.acted |= try_heal();
	fight_turn::fight_shield(c);
	fight_turn::fight_stun(c);
	fight_turn::fight_walk_for_dash(c);
	fight_turn::fight_heart_dash(c);
	fight_turn::fight_gap_dash(c);
	fight_turn::fight_vesper_dash(c);
	const vec2 area = fight_turn::fight_area_tile(c);
	bb12_akill = area.x >= 0 && cheb(area, f.pos) <= static_cast<int>(k.aoe_radius) && eff_hp(f) <= k.aoe_mod * burst::spell_on(burst::spell_base(), f); // BB12 AKILL
	fight_turn::fight_nuke(c);
	fight_turn::fight_stun_nuke_other(c);
	fight_turn::fight_threat_stun(c);
	if (slot_up(k.slot_aoe) && area.x >= 0)
		c.acted |= cast_at(k.slot_aoe, area);
	if (fight_turn::fight_stay_on_camp(c))
	{
		if (!c.acted && !W.moved)
			turn_memory.last_fight_round = bbm_lfr;
		return false;
	}
	fight_turn::fight_choose_hold(c);
	if (!c.hold && c.d > W.me.range && W.can_move() && !CI2_FIGHT()) // guard step, ranged-reach hold
		if (const int cr = nova::ci::fight_weights::walk(a, f, c.d); cr != 0)
			cr == 1 ? void(c.hold = true) : fight_turn::fight_moved(c);
	c.d_before_walk = c.d;
	bool fac4 = false;
	if (c.d > W.me.range && !c.hold && fight_turn::fac_shot_gate(c))
		fac4 = true; // FAC4: the shot before the walk keeps the allowance: no perch step
	if (c.d > W.me.range && !c.hold && !(fac4) && fight_turn::bush_perch_step(a, f, c.d)) // the walk-in step's tile; FAC4
		fight_turn::fight_moved(c);
	fight_turn::fight_walk_in(c);
	fight_turn::fight_heart_after_walk(c);
	if (vendetta_layer::fight_ve_dash() && W.moved && c.d_before_walk == c.dash_r + 2 && c.d == c.dash_r + 1) // CB3 bit 2048 VDR: the walk
		fight_turn::fight_gap_dash(c); // brought the focus to the gap dash's 3 tiles; the dash is walking-compatible (GameRules.md:638)
	if (!k.ranged && c.d <= W.me.range && W.can_attack() && fight_turn::bush_perch_step(a, f, c.d)) // step and hit
		fight_turn::fight_moved(c);
	if (c.d <= W.me.range)
		fight_turn::fight_hit_focus(c);
	else
		fight_turn::fight_hit_nearby(c);
	fight_turn::fight_step_from_camp(c);
	if (c.path_failed && !c.acted)
	{
		if (!W.moved)
			turn_memory.last_fight_round = bbm_lfr;
		return false;
	}
	if (c.hold && !c.acted)
		return true; // a hold ends the turn here (farming walks would step into their reach); past FSH_N held turns it falls through
	if (!c.acted && !W.moved)
		turn_memory.last_fight_round = bbm_lfr;
	return c.acted;
}
// The first early-out test inline at the call site (a call and frame a turn saved), the rest out of line.
__attribute__((always_inline)) bool retreat_to_spawn_to_heal(const Assessment& a)
{
	if (W.me.frac() * 100.0f >= static_cast<float>(SP_TAB[2]))
		return false;
	return fight_turn::retreat_to_spawn_to_heal_slow(a);
}
// the lethal flee assess() found takes its non-lethal tile: a melee body (or any body that
// dashes) first hits the weakest foe in range, then walks or dashes there; a ready self-shield goes up if the turn's cast
// is free. Brain calls it before hold_capture; false leaves the turn to the usual FLEE branch.
bool lethal_burst_flee_turn(const Assessment& a)
{
	if (lethal_spot.round != W.round || a.stance != FLEE || !W.alive || !W.me.kit || lb_tile.x < 0)
		return false;
	if (cheb(lb_tile, W.me.pos) > fight_turn::tune::LB_TILE_MAX_D || !mv::free_tile(lb_tile))
		return false;
	const Kit& k = *W.me.kit;
	if (lethal_spot.by_dash ? (k.slot_dash < 0 || !ready(k.slot_dash)) : !W.can_move())
		return false;
	turn_memory.last_flee_round = W.round;
	std::vector<mv::Threat> zones = geom::zones_of(a);
	geom::add_camp_zones(zones);
	fight_turn::note_retreat(zones);
	if ((lethal_spot.by_dash || !k.ranged) && W.can_attack() && !(k.ranged && lb_step.x >= 0)) // lb_step: a ranged attack takes the walk (p57 rc 36), so it comes after
	{
		const Body* adj = fight_turn::flee_hit_target();
		if (adj)
		{
			const Body target = *adj;
			bh57_noreset = static_cast<bool>(lethal_spot.by_dash) || fight_turn::shield_ready(k); // the dash below needs the turn's cast; BB14 LBS: so does the shield
			attack_champion(target);
			bh57_noreset = false;
		}
	}
	const bool moved = lethal_spot.by_dash ? cast_at(k.slot_dash, lb_tile) : mv::try_move(lb_tile);
	if (!moved)
		return false; // the usual FLEE branch runs (a hit already made stays)
	if (lethal_spot.by_dash && lb_step.x >= 0 && W.can_move()) // the step past the landing
	{
		mv::try_move(lb_step);
		if (k.ranged)
			cast::free_attack();
	}
	if (fight_turn::shield_ready(k))
		cast_self(k.slot_shield);
	return true;
}
// The first early-out test inline at the call site (a call and frame a turn saved), the rest out of line.
__attribute__((always_inline)) bool escape_dash_turn(const Assessment& a)
{
	// The gap this closes: nothing reaches me by the one-turn, ready-slots model (a.in_reach is flee()'s own dash branch). A body with
	// no dash ready and bit 2 off does no work.
	if (a.stance == FIGHT || a.in_reach || !W.alive || !W.me.kit || W.on_spawn || W.me.channeling() || W.enemies.empty() || !W.can_move() || fuel() < 40000)
		return false;
	return fight_turn::escape_dash_turn_slow(a);
}
// The first early-out test inline at the call site (a call and frame a turn saved), the rest out of line. The assessment's foes,
// kept for the turn end.
static std::vector<Foe> shk_foes;
__attribute__((always_inline)) bool self_shield_after_hit_turn()
{
	if (!W.alive || !W.me.kit)
		return false;
	return fight_turn::self_shield_after_hit_turn_slow();
}
} // namespace nova::combat
