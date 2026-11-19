// ward_act.cc: Placing a ward this turn: scout, react, hold and act.
#include "ward_internal.h"
namespace nova::ward {
namespace {
bool awr_117 = false; // AWR bit 1: the last placement was refused with rc 117
// Bookkeeping after a successful placement.
void placed_at(vec2 p)
{
	my_ward = p;
	my_ward_round = now();
	cambc::ward::visible_tiles_from_into(p, scratch);
	set_watch(p, scratch);
	ready_round = now() + recharge;
	ready_since = -1;
	next_check = 0;
}
// RFA bit 16: a ward error that is about me (stunned, no charge, can't act), not about the tile.
static bool rfa_own_error(cambc::error_code code)
{
	return code == cambc::error_code::invalid_action_place_ward_cant_place ||
		code == cambc::error_code::invalid_action_place_ward_no_charges || code == cambc::error_code::invalid_action_cant_act;
}
// Scout fallback (see SCOUT_WAIT): the legal tile at full reach (else nearer) closest to the enemy spawn by walking distance, or by
// straight distance where the field does not reach. No vision query is needed to choose it.
void scout(const cambc::champion& self, vec2 me)
{
	vec2 best{ -1, -1 };
	int bd = BIG;
#pragma clang loop unroll(full)
	for (const vec2 d : DIRS)
		for (int r = reach_r; r >= 1; --r)
		{
			const vec2 p{ me.x + d.x * r, me.y + d.y * r };
			if (!inb(p) || bbget(M.block, p) || camp_tile_blocks_ward(p) || ally_ward_at(p) || bad_tile(p))
				continue;
			// A champion never writes M.f_enemy (it reads 0 everywhere): use the straight-distance fallback.
			const std::uint16_t fd = (!M.has_enemy) ? static_cast<std::uint16_t>(UNREACH) : dfget(M.f_enemy, p);
			const int dd = (fd != UNREACH ? static_cast<int>(fd) : 2 * cheb(p, M.enemy_anchor) + 50) - r;
			if (dd < bd)
			{
				bd = dd;
				best = p;
			}
			break;
		}
	if (best.x < 0)
		return;
	bool ok = false;
	bool rfa_own = false, rfa_thrown = false; // RFA bit 16
	try
	{
		cancel_spin_before_action();
		ok = self.place_ward(best);
	}
	catch (const std::exception& e)
	{
		NLOG("r%d slot %d scout ward %d,%d error %s\n", now(), P.my_slot, best.x, best.y, e.what());
		(void)e;
		rfa_thrown = true;
		{
			const auto* ce = dynamic_cast<const cambc::error*>(&e);
			if (ce)
			{
				rfa_own = rfa_own_error(ce->code());
			}
		}
		{
			const auto* ce = dynamic_cast<const cambc::error*>(&e);
			if (ce && ce->code() == cambc::error_code::invalid_action_place_ward_ally_ward_present)
			{
				note_ally_ward_tile(best); // RFA bit 128 WAB1
				awr_117 = true; // AWR bit 1: retry the next tile this turn
			}
		}
	}
	if (!ok)
	{
		if (!rfa_thrown && best.x >= 0) // scout (best.x >= 0 here)
		{
			note_ally_ward_tile(best);
		}
		if (!rfa_own)
		{
			bad.push_back({ best, now() + 40 });
		}
		next_check = now() + 1;
		return;
	}
	NLOG("r%d slot %d WARD scout %d,%d (me %d,%d)\n", now(), P.my_slot, best.x, best.y, me.x, me.y);
	placed_at(best);
}
} // namespace
// With the charge ready, ward the nearest bush tile within reach that I do not see (a hidden attacker sits in an unlit bush; a ward
// in a bush sees its whole cluster). need_hit: only on a turn that starts with champion damage from no visible source (no enemy
// within 4 of me in my or my ward's sight, no camp reach). A tile refused by a hidden occupant reveals it for the round; the next
// nearest tile is tried (at most 3).
bool react(bool need_hit)
{
	if (!W.alive || P.my_slot < 0 || W.me.channeling() || !bbany(M.bushes))
		return false;
	if (need_hit)
	{
		if (!combat::took_damage(1))
			return false;
		for (const auto* lst : { &W.enemies, &W.enemies_far })
			for (const auto& e : *lst)
				if (cheb(e.pos, W.me.pos) <= 4)
					return false;
		if (mv::camp_threat(W.me.pos) > 0)
			return false;
	}
	const int t = now();
	if (t < ready_round)
		return false;
	try
	{
		read_consts();
		const auto& self = cambc::self();
		const int cd = self.ward_cooldown();
		if (cd > 0)
		{
			ready_round = t + cd;
			return false;
		}
		const vec2 me = W.me.pos;
		const bitboard& lit = my_current_vision(); // W.vis when the WLT bit is off.
		vec2 c[3] = { { -1, -1 }, { -1, -1 }, { -1, -1 } };
		int cdist[3] = { BIG, BIG, BIG };
		for (int dy = -reach_r; dy <= reach_r; ++dy)
			for (int dx = -reach_r; dx <= reach_r; ++dx)
			{
				const vec2 p{ me.x + dx, me.y + dy };
				if (!inb(p) || !bbget(M.bushes, p) || bbget(M.camp_tiles, p) || bbget(lit, p) || bad_tile(p) || ally_ward_at(p))
					continue;
				int d = cheb(p, me);
				vec2 q = p;
				for (int k = 0; k < 3; ++k)
					if (d < cdist[k])
					{
						std::swap(d, cdist[k]);
						std::swap(q, c[k]);
					}
			}
		for (int k = 0; k < 3 && c[k].x >= 0; ++k)
		{
			bool ok = false;
			bool rfa_own = false, rfa_thrown = false; // RFA bit 16
			int rfa_code = -1;
			(void)rfa_code;
			try
			{
				cancel_spin_before_action();
				ok = self.place_ward(c[k]);
			}
			catch (const cambc::error& e)
			{
				FXR_PASS();
				ok = false;
				rfa_thrown = true;
				rfa_code = static_cast<int>(e.code());
				rfa_own = static_cast<bool>(rfa_own_error(e.code()));
				if (e.code() == cambc::error_code::invalid_action_place_ward_ally_ward_present)
				{
					note_ally_ward_tile(c[k]); // RFA bit 128 WAB1
				}
			}
			catch (...)
			{
				FXR_PASS();
				ok = false;
				rfa_thrown = true;
			}
			if (ok)
			{
				NLOG("r%d slot %d WARD react %d,%d (me %d,%d)\n", t, P.my_slot, c[k].x, c[k].y, me.x, me.y);
				++n_bush;
				placed_at(c[k]);
				return true;
			}
			if (!rfa_thrown)
			{
				note_ally_ward_tile(c[k]);
			}
			if (rfa_own)
			{
				break; // RFA bit 16: the next tile fails the same way; no ban
			}
			bad.push_back({ c[k], t + 40 });
		}
	}
	catch (...)
	{
		FXR_PASS();
	}
	return false;
}
// An unlit tile within my reach of the bush cluster next to `at` (a foe's last tile) gets my ward, the one nearest to `at`. Clusters
// come from the background analysis labels (bush_lbl); before a tile is labelled only the bush tiles next to `at` count. Nothing
// when I stand in that cluster (I see all of it). Fuel: at most 9 + 25 tile reads (flooding up to 441 tiles every ready turn would
// cut turns on bush mazes). A refused tile is marked bad, the next tried (3).
bool ward_bush_by_vanished_foe(vec2 at)
{
	if (at.x < 0 || !W.alive || P.my_slot < 0 || W.me.channeling() || fuel() < BSX_TAB[4])
		return false;
	const int t = now();
	if (t < ready_round)
		return false;
	try
	{
		read_consts(); // reach_r (once per game)
		const vec2 me = W.me.pos;
		std::int16_t lb[9];
		int nl = 0;
		bool any_bush = false;
		for (int dx = -1; dx <= 1; ++dx)
			for (int dy = -1; dy <= 1; ++dy)
			{
				const vec2 q{ at.x + dx, at.y + dy };
				if (!inb(q) || !bbget(M.bushes, q))
					continue;
				any_bush = true;
				const std::int16_t l = bush_lbl.get(q);
				bool dup = l == 0;
				for (int i = 0; i < nl && !dup; ++i)
					dup = lb[i] == l;
				if (!dup)
					lb[nl++] = l;
			}
		if (!any_bush)
			return false;
		auto in_target = [&](vec2 p) {
			const std::int16_t l = bush_lbl.get(p);
			if (l != 0)
			{
				for (int i = 0; i < nl; ++i)
					if (lb[i] == l)
						return true;
				return false;
			}
			return cheb(p, at) <= 1; // not labelled yet: only the bush tiles next to the foe's last tile
		};
		if (bbget(M.bushes, me) && in_target(me))
		{
			// v683 BVX bit 1: go on; my own cluster is lit, so the lit filter below drops its tiles and the other cluster is warded
		}
		else if (bbget(M.bushes, me) && in_target(me))
			return false; // I stand in this cluster: I see all of it
		const bitboard& lit = my_current_vision(); // W.vis when the WLT bit is off.
		vec2 c[3] = { { -1, -1 }, { -1, -1 }, { -1, -1 } };
		int cdist[3] = { BIG, BIG, BIG };
		for (int dy = -reach_r; dy <= reach_r; ++dy)
			for (int dx = -reach_r; dx <= reach_r; ++dx)
			{
				const vec2 p{ me.x + dx, me.y + dy };
				if (!inb(p) || !bbget(M.bushes, p) || bbget(lit, p) || bbget(M.camp_tiles, p) || !in_target(p) || bad_tile(p) || ally_ward_at(p))
					continue;
				int d = cheb(p, at);
				vec2 q = p;
				for (int k = 0; k < 3; ++k)
					if (d < cdist[k])
					{
						std::swap(d, cdist[k]);
						std::swap(q, c[k]);
					}
			}
		if (c[0].x < 0)
			return false;
		const auto& self = cambc::self();
		const int cd = self.ward_cooldown();
		if (cd > 0)
		{
			ready_round = t + cd;
			return false;
		}
		for (int k = 0; k < 3 && c[k].x >= 0; ++k)
		{
			bool ok = false;
			bool rfa_own = false, rfa_thrown = false; // RFA bit 16
			int rfa_code = -1;
			(void)rfa_code;
			try
			{
				cancel_spin_before_action();
				ok = self.place_ward(c[k]);
			}
			catch (const cambc::error& e)
			{
				FXR_PASS();
				ok = false;
				rfa_thrown = true;
				rfa_code = static_cast<int>(e.code());
				rfa_own = static_cast<bool>(rfa_own_error(e.code()));
				if (e.code() == cambc::error_code::invalid_action_place_ward_ally_ward_present)
				{
					note_ally_ward_tile(c[k]); // RFA bit 128 WAB1
				}
			}
			catch (...)
			{
				FXR_PASS();
				ok = false;
				rfa_thrown = true;
			}
			if (ok)
			{
				NLOG("r%d slot %d WARD bsx %d,%d (me %d,%d at %d,%d)\n", t, P.my_slot, c[k].x, c[k].y, me.x, me.y, at.x, at.y);
				++n_bush;
				placed_at(c[k]);
				return true;
			}
			if (!rfa_thrown)
			{
				note_ally_ward_tile(c[k]);
			}
			if (rfa_own)
			{
				break; // RFA bit 16: the next tile fails the same way; no ban
			}
			bad.push_back({ c[k], t + 40 });
		}
	}
	catch (...)
	{
		FXR_PASS();
	}
	return false;
}
// Bit 1: hold the ready charge for a bush instead of spending it on an open-ground coverage spot. Called only with the flag on and a
// ward of mine standing. Bush board dilated by WKB_BR built once (static map data).
static bool hold_charge_for_bush(int t)
{
	static bitboard wb_near;
	static int wb_ok = 0; // 0 unbuilt, 1 bushes, 2 no bushes
	if (wb_ok == 0)
	{
		if (!bbany(M.bushes))
			wb_ok = 2;
		else
		{
			const int br = WKB_TAB[4];
			bitboard h = M.bushes, tmp;
			for (int k = 1; k <= br; ++k)
			{
				M.bushes.shift_right_into(k, tmp);
				h |= tmp;
				M.bushes.shift_right_into(-k, tmp);
				h |= tmp;
			}
			wb_near = h;
			for (int k = 1; k <= br; ++k)
			{
				h.shift_up_into(k, tmp);
				wb_near |= tmp;
				h.shift_up_into(-k, tmp);
				wb_near |= tmp;
			}
			wb_ok = 1;
		}
	}
	if (wb_ok != 1)
		return false;
	const vec2 me = W.me.pos;
	if (cheb(my_ward, me) > WKB_TAB[3])
		return false; // stale ward: a moving body is not left blind
	if (inb(my_ward) && bbget(M.bushes, my_ward))
		return true; // Never replace a standing bush ward with an open one within WKB_FAR.
	if (t - ready_since >= WKB_TAB[2])
		return false;
	const bool near_me = inb(me) && bbget(wb_near, me);
	if (near_me)
		return true;
	const int tg = econ::claim_target();
	bool near_t = false;
	if (tg >= 0 && static_cast<std::size_t>(tg) < static_cast<std::size_t>(M.ng))
	{
		const vec2 a = M.groups[static_cast<std::size_t>(tg)].anchor;
		near_t = inb(a) && bbget(wb_near, a);
	}
	return near_t;
}
inline long wfs_actf()
{
	return ACT_FUEL;
}

using Self = std::remove_cvref_t<decltype(cambc::self())>;

// Wait out the ward cooldown and any channel; false when this turn places nothing.
static __attribute__((always_inline)) inline bool wait_for_ready_charge(const Self& self, int t)
{
const int cd = self.ward_cooldown();
if (cd > 0)
{
	ready_round = t + cd;
	return false;
}
PROF("w_cd");
refresh_self();
if (W.me.channeling() || (W.me.state & ST_ALIVE) == 0)
	return false;
if (ready_since < 0)
	ready_since = t;
	return true;
}

// Bushes along the farm first (top teams put every ward on a bush tile near the group they farm).
// False when a bush ward was placed or the charge is kept for the next bush.
static __attribute__((always_inline)) inline bool place_on_bush(const Self& self, int t)
{
// Bushes along the farm first (top teams put every ward on a bush tile near the group they farm).
if (bush_place(self, W.me.pos))
	return false;
// On a map with bushes, keep the charge for the next bush.
if (my_ward.x >= 0 && hold_charge_for_bush(t))
	return false; // Keep the charge for a bush; the standing ward keeps watching.
	return true;
}

// False while the background is still building the spot cache (analyse).
static __attribute__((always_inline)) inline bool spot_cache_ready()
{
if (spots.empty() || !cache_ready())
{
	// No spot cache yet and no ward ever placed: the scout fallback after SCOUT_WAIT.
	return false; // the background is still building it (analyse)
}
	return true;
}

// False when the last check was recent and I have barely moved.
static __attribute__((always_inline)) inline bool recheck_due(int t)
{
if (t < next_check && cheb(W.me.pos, check_pos) < 3)
	return false;
	return true;
}

// Reset the budgets, refresh the allied-ward coverage and mark this check; returns my tile.
static __attribute__((always_inline)) inline vec2 prepare_check(int t)
{
misses_left = MISS_MAX;
weight_budget = WEIGHT_BUDGET;
scan_allied_wards();
PROF("w_scan");
if (acov_dirty || acov.size() != spots.size())
	rebuild_acov();
PROF("w_acov");
const vec2 me = W.me.pos;
next_check = t + 4;
check_pos = me;
	return me;
}

// Weights of the spots a ward within reach could see; returns their sum.
static __attribute__((always_inline)) inline float reachable_weights(vec2 me)
{
if (ew.size() != spots.size())
	ew.assign(spots.size(), 0.0f);
float upper = 0;
{
	const std::size_t ns = spots.size(); // F4: read once (weight_cached's calls hide them from the optimiser)
	const int* const sxp = sx.data();
	const int* const syp = sy.data();
	const int* const srp = srad.data();
	float* const ewp = ew.data();
	const float* const acp = acov.data();
	const int rr0 = reach_r, mx = me.x, my = me.y;
	// The reach box test four spots at a time; in-reach spots in ascending order.
	std::size_t i = 0;
	{
		const v128_t vmx = wasm_i32x4_splat(mx), vmy = wasm_i32x4_splat(my), vr0 = wasm_i32x4_splat(rr0);
		for (; i + 4 <= ns; i += 4)
		{
			const v128_t r4 = wasm_i32x4_add(vr0, wasm_v128_load(srp + i));
			const v128_t ok = wasm_v128_and(wasm_i32x4_le(wasm_i32x4_abs(wasm_i32x4_sub(vmx, wasm_v128_load(sxp + i))), r4),
				wasm_i32x4_le(wasm_i32x4_abs(wasm_i32x4_sub(vmy, wasm_v128_load(syp + i))), r4));
			std::uint32_t mk = wasm_i32x4_bitmask(ok);
			// The 4 zeros in one store, then the in-reach lanes in ascending order.
			wasm_v128_store(ewp + i, wasm_f32x4_splat(0.0f));
			for (; mk != 0; mk &= mk - 1)
			{
				const std::size_t j = i + static_cast<std::size_t>(__builtin_ctz(mk));
				ewp[j] = weight_cached(j) * (1.0f - acp[j]);
				upper += ewp[j];
			}
		}
	}
	for (; i < ns; ++i)
	{
		const int rr = rr0 + srp[i];
		if (iabs(mx - sxp[i]) > rr || iabs(my - syp[i]) > rr)
		{
			ewp[i] = 0;
			continue;
		}
		ewp[i] = weight_cached(i) * (1.0f - acp[i]);
		upper += ewp[i];
	}
}
	return upper;
}

struct PlaceGate
{
	float waited;
	float need;
};

// How long this ward charge has waited and the coverage a new ward must reach.
static __attribute__((always_inline)) inline PlaceGate place_gate(int t)
{
float cur = 0;
if (my_ward.x >= 0)
{
	const CovList cl = coverage(my_ward);
	for (int k = 0; k < cl.n; ++k)
	{
		const auto i = static_cast<std::size_t>(cl.e[k].spot);
		cur += weight_cached(i) * (1.0f - acov[i]) * static_cast<float>(cl.e[k].c) / 255.0f;
	}
}
cur *= std::max(CUR_FLOOR, 1.0f - static_cast<float>(t - my_ward_round) / CUR_FADE);
const float waited = static_cast<float>(t - ready_since);
const float bar = std::max(BAR_MIN, BAR0 * (1.0f - waited / BAR_TURNS));
const float need = std::max(bar, cur + std::max(GAIN_MIN, 0.25f * cur));
PROF("w_near");
	return { waited, need };
}

// Scout once the wait is long enough and no standing ward is near; true when it did.
static __attribute__((always_inline)) inline bool scout_if_idle(const Self& self, vec2 me, float waited)
{
	if (waited >= SCOUT_WAIT && (my_ward.x < 0 || cheb(my_ward, me) > SCOUT_FAR))
	{
		awr_117 = false;
		scout(self, me);
		if (awr_117) // AWR bit 1: one retry on the next tile (the refused one is now an ally ward)
		{
			awr_117 = false;
			scout(self, me);
		}
		return true;
	}
	return false;
}

struct PlaceChoice
{
	vec2 best;
	float best_v;
	bool skipped;
};

// The best tile among the 8 full-reach tiles and my own, by the coverage it adds.
static __attribute__((always_inline)) inline PlaceChoice pick_ward_tile(vec2 me, int t, float need)
{
bad.erase(std::remove_if(bad.begin(), bad.end(), [&](const Bad& b) { return b.until <= t; }), bad.end());
// Candidates: the 8 tiles at full reach in each direction (they extend our view most; the nearer tile of
// that direction when the far one is blocked) and our own tile. New tiles cost a vision query each and are
// limited per call; the rest wait for the next check.
vec2 best{ -1, -1 };
float best_v = 0;
bool skipped = false;
auto consider = [&](vec2 p)
{
	if (!inb(p) || bbget(M.block, p) || camp_tile_blocks_ward(p) || p == my_ward || ally_ward_at(p) || bad_tile(p))
		return false; // Never on a camp spawn tile (unless seen without its camp): an occupied spawn tile holds back the group's respawn.
	const CovList cl = coverage(p);
	if (cl.n < 0)
	{
		skipped = true;
		return true; // legal, but not evaluated this time
	}
	float v = 0;
	for (int k = 0; k < cl.n; ++k)
		v += ew[static_cast<std::size_t>(cl.e[k].spot)] * static_cast<float>(cl.e[k].c);
	v /= 255.0f;
	if (v > best_v)
	{
		best_v = v;
		best = p;
	}
	return true;
};
for (const vec2 d : DIRS)
{
	bool done = false;
	for (int r = reach_r; r >= 1 && !done; --r)
		done = consider(vec2{ me.x + d.x * r, me.y + d.y * r });
}
consider(me);
PROF("w_cands");
	return { best, best_v, skipped };
}

// Place the ward; a refused tile is ruled out for a while.
static __attribute__((always_inline)) inline void place_chosen_ward(const Self& self, int t, vec2 best, float best_v)
{
// False: a mate's ward holds the tile (sight is not shared). An error that is about us (stunned, no charge) means
// trying again next turn; any other (e.g. an ally ward there) rules the tile out for a while.
bool ok = false, bad_spot = true;
bool wbn_thr = false; // WBN bit 1: the call threw
try
{
	cancel_spin_before_action();
	ok = self.place_ward(best);
}
catch (const cambc::error& e)
{
	wbn_thr = true;
	const auto code = e.code();
	bad_spot = code != cambc::error_code::invalid_action_place_ward_cant_place &&
		code != cambc::error_code::invalid_action_place_ward_no_charges &&
		code != cambc::error_code::invalid_action_cant_act;
	if (code == cambc::error_code::invalid_action_place_ward_ally_ward_present)
	{
		note_ally_ward_tile(best); // RFA bit 128 WAB1: permanent, not a 40-round ban
		awr_117 = true; // AWR bit 1: retry the next pick this turn
	}
	NLOG("r%d slot %d ward place %d,%d error %s\n", t, P.my_slot, best.x, best.y, e.what());
}
catch (const std::exception& e)
{
	wbn_thr = true;
	NLOG("r%d slot %d ward place %d,%d error %s\n", t, P.my_slot, best.x, best.y, e.what());
	(void)e;
}
if (!ok && !wbn_thr)
	note_ally_ward_tile(best); // WBN bit 1 WPC1: a silent false is a mate's permanent ward (INT:149)
if (!ok && bad_spot)
	bad.push_back({ best, t + 40 });
if (!ok)
{
	next_check = t + 1;
	return;
}
placed_at(best);
}

__attribute__((always_inline)) void act()
{
	log_ward_coverage_summary();
	if (!W.alive || P.my_slot < 0)
		return;
	const int t = now();
	if (t < ready_round || fuel() < wfs_actf())
	{
		// Read only after the fuel test failed. The first ward needs no spot cache.
		return;
	}
	long wfl_f0 = 0;
	try
	{
		read_consts();
		scan_allied_wards();
		const auto& self = cambc::self();
		if (!wait_for_ready_charge(self, t))
		{
			return;
		}
		const bool wfl_bush = place_on_bush(self, t);
		if (!wfl_bush)
			return;
		if (!spot_cache_ready())
			return;
		if (!recheck_due(t))
			return;
		const vec2 me = prepare_check(t);
		const float upper = reachable_weights(me);
		const PlaceGate gate = place_gate(t);
		if (upper < gate.need)
		{
			scout_if_idle(self, me, gate.waited);
			return;
		}
		const PlaceChoice pick = pick_ward_tile(me, t, gate.need);
		if (pick.best.x < 0 || pick.best_v < gate.need)
		{
			if (!scout_if_idle(self, me, gate.waited) && pick.skipped)
				next_check = t + 1;
			return;
		}
		awr_117 = false;
		place_chosen_ward(self, t, pick.best, pick.best_v);
		if (awr_117) // AWR bit 1: one retry, same turn, on the next pick (the refused tile is now an ally ward)
		{
			awr_117 = false;
			const vec2 me2 = prepare_check(t);
			if (reachable_weights(me2) >= gate.need)
			{
				const PlaceChoice pick2 = pick_ward_tile(me2, t, gate.need);
				if (pick2.best.x >= 0 && pick2.best_v >= gate.need)
				{
					place_chosen_ward(self, t, pick2.best, pick2.best_v);
					return;
				}
			}
			next_check = t + 1; // no retry placed: recheck next turn, as after the refusal
		}
	}
	catch (const RestartTurn&)
	{
		throw;
	}
	catch (const std::exception& e)
	{
		NLOG("r%d slot %d ward act error %s\n", t, P.my_slot, e.what());
		(void)e;
		ready_round = t + 1;
	}
}

} // namespace nova::ward
