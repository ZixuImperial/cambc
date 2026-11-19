// dashnav.cc: Dash routes (pathological-map fix): goal-directed travel for champions with a dash, over ground that walking
#include "dashnav.h"
#include <wasm_simd128.h>

#include "combat.h"
#include "mapinfo.h"
#include "move.h"
#include "world.h"

#include <array>
#include <map>

namespace nova::dn {
// bbany(b) with 8 words tested per step (four v128 loads OR-ed, then one test for any set bit).
NOVA_INLINE bool bbany_simd_dashnav(const bitboard& b)
{
	std::int32_t z = 0; // the host's test (~25 + 1 a chunk) unless it errs
	if (cambc::detail::sdk_Bitboard_IsZero(b.ptr(), &z) == 0)
		return z == 0;
	const std::uint64_t* w = b.ptr();
	const int n = G.ch * G.stride;
	int i = 0;
	for (; i + 8 <= n; i += 8)
		if (wasm_v128_any_true(wasm_v128_or(wasm_v128_or(wasm_v128_load(w + i), wasm_v128_load(w + i + 2)),
										   wasm_v128_or(wasm_v128_load(w + i + 4), wasm_v128_load(w + i + 6)))))
			return true;
	for (; i < n; ++i)
		if (w[i])
			return true;
	return false;
}

namespace {

constexpr int KMAX = 10; // layers (dashes) per route
constexpr int DASH_TURNS = rs::slot_cooldown();

// Route lengths asked this round (the target choice asks for every dash-only group, several times a turn; uncached this is costly on
// maps with many dash-only groups).
struct LenMemo
{
	int round = -1, len = UNREACH;
	vec2 p{ -1, -1 };
	std::size_t layers = 0;
};
struct Route
{
	LenMemo memo;
	bool done = false; // No further layer exists (or KMAX reached).
	std::vector<distance_field> f; // f[k]: walk distance to the layer-k roots (camp tiles blocked)
	std::vector<bitboard> area;    // area[k]: tiles that reach the layer-k roots on foot
	bitboard all;                  // union of the areas
	bitboard all8;                 // b2046 XDE DCV1: all and its 8-neighbours (set beside every all write while bit 16 is on)
	std::size_t ctc_layers = 0;    // DNB bit 16: layers when ctc was measured
	float ctc = -1.0f;             // DNB bit 16: contest along the route (-1: home not on it)
};
// Indexed by goal + 1 (GOAL_ALTAR = -1, then group indices), null until the route exists. Routes stay on the heap, so a Route& stays
// valid as the table grows.
std::vector<Route*> rt_tab;
unsigned rt_n = 0;
NOVA_INLINE Route* route_find(int goal)
{
	const unsigned k = static_cast<unsigned>(goal + 1);
	return k < rt_n ? rt_tab[k] : nullptr;
}
Route& route_at(int goal) // map::operator[]: an empty route when absent
{
	if (Route* const r = route_find(goal))
		return *r;
	const unsigned k = static_cast<unsigned>(goal + 1);
	if (k >= rt_n)
	{
		rt_tab.resize(k + 1, nullptr);
		rt_n = k + 1;
	}
	rt_tab[k] = new Route();
	return *rt_tab[k];
}

int sx = 0, sy = 0; // bitboard shift directions (+1/-1), calibrated once
bitboard stand, mid_ok;
std::array<bitboard, 9> mid_pre; // mid_pre[(my + 1) * 3 + mx + 1]: tiles p with p + (mx, my) a legal middle
bool base_ready = false;
// mids[i]: the union of the legal middles of dash offset i (calibrate order); scratch boards, reused by every launch(). Allocated in
// calibrate only: a map without dash layers allocates none.
struct FlBoards
{
	std::array<bitboard, 16> mids;
	std::array<vec2, 16> off;
	std::array<bitboard, 5> x; // x[dx + 2]: land shifted for column offset dx (dx = 0: land itself)
	bitboard t, out;
};
FlBoards* fl = nullptr; // Never freed (one per game).

bitboard pre(const bitboard& b, int dx, int dy);
void calibrate()
{
	bitboard t{};
	bbset(t, vec2{ 1, 1 });
	const bitboard r = t.shift_right(1), u = t.shift_up(1);
	sx = bbget(r, vec2{ 2, 1 }) ? 1 : -1;
	sy = bbget(u, vec2{ 1, 2 }) ? 1 : -1;
	stand = ~M.block_camps;
	mid_ok = ~(M.walls | M.camp_tiles);
	mid_ok &= ~M.enemy_spawn;
	for (int mx = -1; mx <= 1; ++mx)
		for (int my = -1; my <= 1; ++my)
			if (mx != 0 || my != 0)
				mid_pre[static_cast<std::size_t>((my + 1) * 3 + mx + 1)] = pre(mid_ok, mx, my);
	base_ready = true;
}
// The boards and middle unions, built at the first launch() (a map that only calibrates allocates none).
void launch_boards_init()
{
	if (fl != nullptr)
		return;
	{
		fl = new FlBoards();
		auto& fl_mids = fl->mids;
		auto& fl_off = fl->off;
		// The dash offsets in launch()'s order (dx outer, dy inner) with their middle unions.
		std::size_t i = 0;
		for (int dx = -2; dx <= 2; ++dx)
			for (int dy = -2; dy <= 2; ++dy)
			{
				if (std::max(iabs(dx), iabs(dy)) != 2 || i >= fl_mids.size())
					continue;
				bitboard mids{};
				for (int mx = -1; mx <= 1; ++mx)
					for (int my = -1; my <= 1; ++my)
					{
						if ((mx == 0 && my == 0) || iabs(dx - mx) > 1 || iabs(dy - my) > 1)
							continue;
						mids |= mid_pre[static_cast<std::size_t>((my + 1) * 3 + mx + 1)];
					}
				fl_off[i] = vec2{ dx, dy };
				fl_mids[i] = std::move(mids);
				++i;
			}
	}
}
// Tiles p with p + (dx, dy) in b.
bitboard pre(const bitboard& b, int dx, int dy)
{
	bitboard out = b;
	if (dx != 0)
		out = out.shift_right(-dx * sx);
	if (dy != 0)
		out = out.shift_up(-dy * sy);
	return out;
}
// Tiles from which one dash (two steps, a middle tile that is not a wall or camp) lands in `a`.
bitboard launch(const bitboard& a)
{
	if (base_ready)
		launch_boards_init();
	if (base_ready && fl != nullptr)
	{
		auto& fl_x = fl->x;
		const auto& fl_off = fl->off;
		const auto& fl_mids = fl->mids;
		bitboard& fl_t = fl->t;
		bitboard& fl_out = fl->out;
		// The same union as below: pre(land, dx, dy) shifts columns, then rows; the column shifts are shared.
		bitboard& land = fl_x[2];
		land.clear();
		land |= a;
		land &= stand;
		for (int dx = -2; dx <= 2; ++dx)
			if (dx != 0)
				land.shift_right_into(-dx * sx, fl_x[static_cast<std::size_t>(dx + 2)]);
		fl_out.clear();
		// Offsets with dy == 0 (dx = -2, 2) AND their column board in place: done after every other use of it.
		for (int pass = 0; pass < 2; ++pass)
			for (std::size_t i = 0; i < fl_off.size(); ++i)
			{
				const vec2 o = fl_off[i];
				if ((o.y == 0) != (pass == 1))
					continue;
				bitboard& col = fl_x[static_cast<std::size_t>(o.x + 2)];
				if (o.y != 0)
				{
					col.shift_up_into(-o.y * sy, fl_t);
					fl_t &= fl_mids[i];
					fl_out |= fl_t;
				}
				else
				{
					col &= fl_mids[i];
					fl_out |= col;
				}
			}
		return fl_out & stand;
	}
	bitboard out{};
	const bitboard land = a & stand;
	for (int dx = -2; dx <= 2; ++dx)
		for (int dy = -2; dy <= 2; ++dy)
		{
			if (std::max(iabs(dx), iabs(dy)) != 2)
				continue;
			bitboard mids{};
			bool any = false;
			for (int mx = -1; mx <= 1; ++mx)
				for (int my = -1; my <= 1; ++my)
				{
					if ((mx == 0 && my == 0) || iabs(dx - mx) > 1 || iabs(dy - my) > 1)
						continue;
					const bitboard& mp = mid_pre[static_cast<std::size_t>((my + 1) * 3 + mx + 1)];
					if (!any)
						mids = mp;
					else
						mids |= mp;
					any = true;
				}
			if (any)
				out |= pre(land, dx, dy) & mids;
		}
	return out & stand;
}
bitboard dash_goal_root_tiles(int goal)
{
	bitboard roots{};
	if (goal == GOAL_ALTAR)
	{
		roots = M.altar_adj_all & stand;
		if (!bbany_simd_dashnav(roots))
			roots = M.altar_adj_all;
		return roots;
	}
	if (goal < 0 || goal >= M.ng)
		return roots;
	for (const int ci : M.groups[static_cast<std::size_t>(goal)].members)
	{
		const vec2 c = M.camps[static_cast<std::size_t>(ci)].pos;
		for (const vec2 d : DIRS)
		{
			const vec2 q = c + d;
			if (inb(q) && bbget(stand, q))
				bbset(roots, q);
		}
	}
	return roots;
}

// A layer costs 5-7k when its walk area is a small island and 46-70k when it covers the mainland (the host distance field grows with
// the area): plan for 1.25 x the worst layer seen, at least 22 x the board (on a 60x60 map that leaves big layers to dead or light
// turns).
long worst_layer = 0;
// A root layer (k == 0) costs 5-7k and a launch layer (k >= 1) 46-65k on a 60x60 board (8-10k and 64-86k on 100x100). The dead bar
// is per kind.
long worst_root = 0, worst_launch = 0;
// v757 DNB (move_flags.h): a layer is one launch() (about 60 whole-board ops at G.cw * G.ch fuel each) plus one host distance field,
// which the host charges at most 40000.
long dnb_bound() { return 44000L + 64L * G.cw * G.ch; }
long layer_cost() { return std::max(std::min(22L * M.w * M.h + 4000, dnb_bound()), worst_layer + worst_layer / 4); } // v757 DNB bit 1
long lc_c = 0; // b2046 XDE LCB1: layer_cost() since worst_layer last grew (0: not cached)
// b2046 XDE LCB1: layer_cost() cached (M.w, M.h and the grid are fixed; a worst_layer write clears it).
long layer_cost_c()
{
	if (!lc_c && M.w > 0)
		lc_c = layer_cost();
	return lc_c ? lc_c : layer_cost();
}
// p or a neighbour on the route (on_route(r, p).x >= 0) with one view: on_route() costs ~2k per route when p is off the route (a
// body on a camp tile while capturing), which made background()'s scan expensive with 22-41 routes.
// b2046 XDE DCV1: r.all8 = r.all dilated by one tile (a row pass, then a column pass: the 3x3 square).
void xde_dilate(Route& r)
{
	const bitboard h = r.all | r.all.shift_right(1) | r.all.shift_right(-1);
	r.all8 = h | h.shift_up(1) | h.shift_up(-1);
}
bool covers(const Route& r, vec2 p)
{
	return inb(p) && bbget(r.all8, p); // b2046 XDE DCV1
}
bool build_layer(int goal, Route& r)
{
	if (r.done)
		return false;
	const long f0 = fuel(); // Cost of this layer (see layer_cost).
	const int r0 = static_cast<int>(round_number_nc());
	const std::size_t k = r.f.size();
	const bitboard roots = k == 0 ? dash_goal_root_tiles(goal) : (launch(r.all) & ~r.all);
	if (!bbany_simd_dashnav(roots))
	{
		r.done = true;
		return false;
	}
	distance_field f;
	bitboard vis{};
	f.compute(M.block_camps, roots, vis);
	if (k == 0)
		r.all = vis;
	else
		r.all |= vis;
	xde_dilate(r); // b2046 XDE DCV1
	r.f.push_back(std::move(f));
	r.area.push_back(vis);
	// A build that ran out of fuel resumed next round: it cost what was left then plus what this round used (f0 - fuel() spans two
	// turns).
	const long used = static_cast<int>(round_number_nc()) != r0 ? f0 + (100000 - FXR_FUEL()) : f0 - FXR_FUEL();
	worst_layer = std::max(worst_layer, used);
	lc_c = 0; // b2046 XDE LCB1
	long& wk = k == 0 ? worst_root : worst_launch;
	wk = std::max(wk, used);
	if (static_cast<int>(r.f.size()) >= KMAX)
		r.done = true;
	return true;
}
int layer_of(const Route& r, vec2 p)
{
	if (!inb(p) || !bbget(r.all, p))
		return -1;
	for (std::size_t k = 0; k < r.area.size(); ++k)
		if (bbget(r.area[k], p))
			return static_cast<int>(k);
	return -1;
}
// A tile of the route at p, or at its best neighbour when p itself is blocked (a camp spawn tile after a capture).
vec2 on_route(const Route& r, vec2 p)
{
	if (layer_of(r, p) >= 0)
		return p;
	vec2 best{ -1, -1 };
	long long best_s = 1LL << 40;
	for (const vec2 d : DIRS)
	{
		const vec2 q = p + d;
		const int k = layer_of(r, q);
		if (k < 0)
			continue;
		const long long s = static_cast<long long>(k) * 100000LL + dfget(r.f[static_cast<std::size_t>(k)], q);
		if (s < best_s)
		{
			best_s = s;
			best = q;
		}
	}
	return best;
}

// A landing in an awake camp's reach (the route's own group excepted) or within a visible foe's next-turn reach (its range, a step,
// its dash, one spare), as travel_dash checks.
int ds_goal = -1;
vec2 dpx_land{ -1, -1 }; // v7xx DPX bit 1: my last route dash's landing (cleared by the exit dash)
bool landing_unsafe(vec2 u)
{
	if (mv::camp_threat(u, ds_goal) > 0)
		return true;
	for (const auto& e : W.enemies)
		if (cheb(e.pos, u) <= e.range + 2 + ((e.kit && e.kit->slot_dash >= 0) ? 2 : 0))
			return true;
	return false;
}

bool try_dash_once(const Route& r, int k);
// A landing an unseen occupant refused is marked (cast_via_sdk) and the next best one tried, up to 3 casts.
bool try_dash(const Route& r, int k)
{
	for (int i = 0; i < 3; ++i)
	{
		const int n0 = mv::refused_landings();
		if (try_dash_once(r, k))
			return true;
		if (mv::refused_landings() == n0) // no landing, or a refusal of another kind: nothing new to try
			return false;
	}
	return false;
}
bool try_dash_once(const Route& r, int k)
{
	const Kit& kit = *W.me.kit;
	if (kit.slot_dash < 0 || !combat::ready(kit.slot_dash))
		return false;
	const vec2 me = W.me.pos;
	vec2 best{ -1, -1 };
	long long best_s = 1LL << 40;
	for (int dx = -2; dx <= 2; ++dx)
		for (int dy = -2; dy <= 2; ++dy)
		{
			if (std::max(iabs(dx), iabs(dy)) != 2)
				continue;
			const vec2 u{ me.x + dx, me.y + dy };
			if (!inb(u) || !mv::free_tile(u))
				continue;
			const int lu = layer_of(r, u);
			if (lu < 0 || lu >= k)
				continue;
			if (landing_unsafe(u))
				continue;
			if (kit.dash_mod > 0 && combat::lw_bad(u, std::max(1, static_cast<int>(kit.dash_radius)), ds_goal))
				continue;
			bool mid = false;
			for (int mx = -1; mx <= 1 && !mid; ++mx)
				for (int my = -1; my <= 1 && !mid; ++my)
				{
					if ((mx == 0 && my == 0) || iabs(dx - mx) > 1 || iabs(dy - my) > 1)
						continue;
					const vec2 m{ me.x + mx, me.y + my };
					mid = inb(m) && bbget(mid_ok, m);
				}
			if (!mid)
				continue;
			const long long s = static_cast<long long>(lu) * 100000LL + dfget(r.f[static_cast<std::size_t>(lu)], u);
			if (s < best_s)
			{
				best_s = s;
				best = u;
			}
		}
	if (best.x < 0)
		return false;
	const bool dpx_ok = combat::cast_at(kit.slot_dash, best);
	if (dpx_ok)
		dpx_land = best; // v7xx DPX bit 1: the tile a route dash put me on (a pocket's way back out)
	return dpx_ok;
}
// Walking is blocked (an ally in a 1-wide corridor): dash forward along my own layer, over the blocker when needed.
bool dash_ahead(const Route& r, int k)
{
	const Kit& kit = *W.me.kit;
	if (kit.slot_dash < 0 || !combat::ready(kit.slot_dash))
		return false;
	const vec2 me = W.me.pos;
	const distance_field& f = r.f[static_cast<std::size_t>(k)];
	const std::uint16_t here = dfget(f, me);
	if (here == UNREACH || here < 2)
		return false;
	vec2 best{ -1, -1 };
	std::uint16_t best_v = static_cast<std::uint16_t>(here - 1);
	for (int dx = -2; dx <= 2; ++dx)
		for (int dy = -2; dy <= 2; ++dy)
		{
			if (std::max(iabs(dx), iabs(dy)) != 2)
				continue;
			const vec2 u{ me.x + dx, me.y + dy };
			if (!inb(u) || !mv::free_tile(u) || layer_of(r, u) != k)
				continue;
			const std::uint16_t v = dfget(f, u);
			if (v >= best_v)
				continue;
			if (landing_unsafe(u))
				continue;
			if (kit.dash_mod > 0 && combat::lw_bad(u, std::max(1, static_cast<int>(kit.dash_radius)), ds_goal))
				continue;
			bool mid = false;
			for (int mx = -1; mx <= 1 && !mid; ++mx)
				for (int my = -1; my <= 1 && !mid; ++my)
				{
					if ((mx == 0 && my == 0) || iabs(dx - mx) > 1 || iabs(dy - my) > 1)
						continue;
					const vec2 m{ me.x + mx, me.y + my };
					mid = inb(m) && bbget(mid_ok, m);
				}
			if (!mid)
				continue;
			best_v = v;
			best = u;
		}
	if (best.x < 0)
		return false;
	return combat::cast_at(kit.slot_dash, best);
}

} // namespace

bool dasher() { return W.me.kit && W.me.kit->slot_dash >= 0; }

// v7xx DPX bit 1: the best legal dash landing out of a pocket (no walk home here): a free, safe tile two steps away that walks home, with a
// legal middle (no wall, camp tile, enemy spawn or visible foe; holes pass), nearest to tf's goal when tf reaches it, else to home.
vec2 exit_landing(const distance_field* tf)
{
	const vec2 me = W.me.pos;
	const Kit& kit = *W.me.kit;
	ds_goal = -1;
	vec2 best{ -1, -1 };
	long long best_s = 1LL << 40;
	for (int dx = -2; dx <= 2; ++dx)
		for (int dy = -2; dy <= 2; ++dy)
		{
			if (std::max(iabs(dx), iabs(dy)) != 2)
				continue;
			const vec2 u{ me.x + dx, me.y + dy };
			if (!inb(u) || !mv::free_tile(u))
				continue;
			const std::uint16_t hu = dfget(M.f_home, u);
			if (hu == UNREACH || landing_unsafe(u))
				continue;
			if (kit.dash_mod > 0 && combat::lw_bad(u, std::max(1, static_cast<int>(kit.dash_radius)), -1))
				continue;
			bool mid = false;
			for (int mx = -1; mx <= 1 && !mid; ++mx)
				for (int my = -1; my <= 1 && !mid; ++my)
				{
					if ((mx == 0 && my == 0) || iabs(dx - mx) > 1 || iabs(dy - my) > 1)
						continue;
					const vec2 m{ me.x + mx, me.y + my };
					if (!inb(m) || bbget(M.walls, m) || bbget(M.camp_tiles, m) || bbget(M.enemy_spawn, m))
						continue;
					bool foe = false;
					for (const auto& e : W.enemies)
						foe |= e.pos.x == m.x && e.pos.y == m.y;
					mid = !foe;
				}
			if (!mid)
				continue;
			const std::uint16_t tu = tf ? dfget(*tf, u) : UNREACH;
			const long long sc = tu != UNREACH ? static_cast<long long>(tu) : 100000LL + hu;
			if (sc < best_s)
			{
				best_s = sc;
				best = u;
			}
		}
	return best;
}
vec2 entry_land() { return dpx_land; }
bool exit_dash(const distance_field* tf)
{
	if (!dasher() || !combat::ready(W.me.kit->slot_dash))
		return false;
	const vec2 u = exit_landing(tf);
	if (u.x < 0 || !combat::cast_at(W.me.kit->slot_dash, u))
		return false;
	dpx_land = vec2{ -1, -1 }; // out: the old landing is no way back any more
	return true;
}

// Launch blocked by a teammate on every landing tile.
int blocked_n = 0, blocked_last = -10;
int blocked_rounds() { return blocked_last >= W.round - 1 ? blocked_n : 0; }

int route_len_raw(const Route& r, vec2 p);
int route_len(int goal, vec2 p)
{
	Route* const rp = route_find(goal);
	if (!rp)
		return UNREACH;
	LenMemo& m = rp->memo;
	const int now_r = W.round;
	// Valid for 5 rounds within 2 tiles of where it was measured (a raw length can cost up to ~1k on island maps).
	if (now_r - m.round <= 5 && m.layers == rp->f.size() && inb(m.p) && (cheb(m.p, p) <= 2)) // BB8 bit 4096: the memo only adds
		return m.len == UNREACH ? UNREACH : m.len + cheb(m.p, p);
	m.round = now_r;
	m.p = p;
	m.layers = rp->f.size();
	m.len = route_len_raw(*rp, p);
	return m.len;
}

// v757 DNB bit 16 DNBC: the walk groups' contest (mapinfo.cc:416) from the route's own home and enemy spawn travel; -1 while home is off it.
float route_contest(int goal)
{
	Route* const rp = route_find(goal);
	if (!rp || rp->f.empty())
		return -1.0f;
	if (rp->ctc_layers != rp->f.size())
	{
		rp->ctc_layers = rp->f.size();
		const int rh = route_len_raw(*rp, M.home_anchor);
		const int re = inb(M.enemy_anchor) ? route_len_raw(*rp, M.enemy_anchor) : UNREACH;
		rp->ctc = rh == UNREACH ? -1.0f : re != UNREACH ? static_cast<float>(rh) / std::max(1.0f, static_cast<float>(rh + re)) : inb(M.enemy_anchor) ? 0.0f : 0.5f;
	}
	return rp->ctc;
}
int route_len_raw(const Route& r, vec2 p)
{
	if (!inb(p) || r.f.empty())
		return UNREACH;
	// Quick reject (one view): neither p nor a neighbour is on the route.
	if (!bbget(r.all8, p))
		return UNREACH; // b2046 XDE DCV1
	const vec2 q = on_route(r, p);
	const int k = layer_of(r, q);
	if (k < 0)
		return UNREACH;
	const std::uint16_t d = dfget(r.f[static_cast<std::size_t>(k)], q);
	if (d == UNREACH)
		return UNREACH;
	return static_cast<int>(d) + (q == p ? 0 : 1) + k * (DASH_TURNS + 4);
}
bool prepare(int goal, vec2 p, long reserve)
{
	try
	{
		if (!M.ready() || M.w <= 0)
			return false;
		if (!base_ready)
		{
			if (fuel() < reserve + 20000)
				return false;
			calibrate();
		}
		Route& r = route_at(goal);
		while (on_route(r, p).x < 0)
		{
			if (r.done || fuel() < reserve + (layer_cost_c())) // b2046 XDE LCB1
				return false;
			if (!build_layer(goal, r))
				return false;
		}
		return true;
	}
	catch (const std::exception&)
	{
		return false;
	}
}
bool step(int goal)
{
	try
	{
		if (!dasher() || !W.alive)
			return false;
		const Route* const rp = route_find(goal);
		if (!rp)
			return false;
		const Route& r = *rp;
		const vec2 me = W.me.pos;
		const int k = layer_of(r, me);
		ds_goal = (goal >= 0 && goal < M.ng) ? goal : -1;
		if (k < 0)
		{
			// Off the route (standing on a camp tile): step onto it.
			const vec2 q = on_route(r, me);
			return q.x >= 0 && W.can_move() && !W.moved && mv::free_tile(q) && mv::try_move(q);
		}
		const distance_field& f = r.f[static_cast<std::size_t>(k)];
		if (k == 0)
			return (W.can_move() && !W.moved && mv::step_field(f)) || dash_ahead(r, 0);
		if (dfget(f, me) > 0)
		{
			mv::travel_dash_need(DASH_TURNS + 3); // Keep the dash for the launch tile unless it is back by then.
			const bool walked = W.can_move() && !W.moved && mv::step_field(f);
			mv::travel_dash_need(0);
			if (!walked)
				return dash_ahead(r, k);
			const int k2 = layer_of(r, W.me.pos);
			if (k2 > 0 && dfget_me(r.f[static_cast<std::size_t>(k2)]) == 0)
				try_dash(r, k2);
			return true;
		}
		// On a launch tile: dash when ready, else hold here for the cooldown.
		if (try_dash(r, k))
			return true;
		const bool cooling = W.me.kit->slot_dash >= 0 && W.cd[static_cast<std::size_t>(W.me.kit->slot_dash)] > 0;
		if (!cooling && blocked_last != W.round) // Ready, but every landing is taken.
		{
			blocked_n = blocked_last == W.round - 1 ? blocked_n + 1 : 1;
			blocked_last = W.round;
		}
		return cooling;
	}
	catch (const std::exception&)
	{
		return false;
	}
}

// A layer of the altar route as stages, each with its own bar.
struct FbJob
{
	std::size_t k = 0;
	bool have = false;
	bitboard roots{};
};
FbJob* fbj = nullptr; // allocated at the first use, on an eligible map only
long fb_w_init = 0, fb_w_launch = 0, fb_w_field = 0;
long fb_used(long f0, int r0) { return static_cast<int>(round_number_nc()) != r0 ? f0 + (100000 - FXR_FUEL()) : f0 - FXR_FUEL(); }
long fb_bar(long worst, long prior) { return worst > 0 ? worst + worst / 4 : prior; }
__attribute__((always_inline)) bool altar_route_stage(long res)
{
	// Eligibility first: the same test as background()'s prepare(GOAL_ALTAR). No other map does any work here.
	if (M.any_altar || !(M.gate_groups.empty() || M.ring) || !dasher() || !M.ready())
		return false;
	const long tiles = static_cast<long>(M.w) * M.h;
	if (fuel() < res + 20000)
		return false;
	const vec2 from = W.alive ? W.me.pos : M.home_anchor;
	if (!inb(from))
		return false;
	try
	{
		const long f0 = fuel();
		const int r0 = static_cast<int>(round_number_nc());
		if (!base_ready)
		{
			calibrate();
			return true;
		}
		Route& r = route_at(GOAL_ALTAR);
		if (r.done || r.f.size() >= 5 || covers(r, from))
			return false;
		if (fbj == nullptr)
			fbj = new FbJob();
		FbJob& j = *fbj;
		const std::size_t k = r.f.size();
		if (k > 0 && (!j.have || j.k != k))
		{
			if (fl == nullptr)
			{
				if (fuel() < res + fb_bar(fb_w_init, 3L * tiles + 5000))
					return false;
				launch_boards_init();
				fb_w_init = std::max(fb_w_init, fb_used(f0, r0));
				return true;
			}
			if (fuel() < res + fb_bar(fb_w_launch, 3L * tiles + 10000))
				return false;
			j.roots = launch(r.all) & ~r.all;
			j.k = k;
			j.have = true;
			fb_w_launch = std::max(fb_w_launch, fb_used(f0, r0));
			if (!bbany_simd_dashnav(j.roots))
				r.done = true;
			return true;
		}
		if (fuel() < res + fb_bar(fb_w_field, 35L * tiles / 10 + 5000))
			return false;
		const bitboard roots = k == 0 ? dash_goal_root_tiles(GOAL_ALTAR) : j.roots;
		if (!bbany_simd_dashnav(roots))
		{
			r.done = true;
			return false;
		}
		distance_field f;
		bitboard vis{};
		f.compute(M.block_camps, roots, vis);
		if (k == 0)
			r.all = vis;
		else
			r.all |= vis;
		xde_dilate(r); // b2046 XDE DCV1
		r.f.push_back(std::move(f));
		r.area.push_back(vis);
		fb_w_field = std::max(fb_w_field, fb_used(f0, r0));
		if (static_cast<int>(r.f.size()) >= KMAX)
			r.done = true;
		return true;
	}
	catch (const std::exception&)
	{
	}
	return false;
}

std::size_t bgd_all_n = static_cast<std::size_t>(-1);
// b2046 XDE DBC1: the groups dn::background's scan does not skip by static data (not ACC_WALK, a reward), built once M.done().
std::vector<int> bgd_cand;
int bgd_cand_ng = -1;
bool background(long reserve)
{
	if (!dasher() || !M.ready())
		return false;
	if (W.alive && !M.any_altar && (M.gate_groups.empty() || M.ring)) // A gated altar opens on foot once its gate dies; a ring may take long.
		prepare(GOAL_ALTAR, W.me.pos, reserve);
	// Routes to the dash-only groups with a reward, nearest first, one group per turn, so the target choice can rate them (econ
	// dash_group). A route that needs more than 4 dashes from here is not worth it. While dead (a turn of spare fuel) the routes grow
	// from the spawn, where I come back.
	const vec2 from = W.alive ? W.me.pos : M.home_anchor;
	if (!inb(from))
		return false;
	if (bgd_all_n == static_cast<std::size_t>(M.ng))
		return false; // b2046 XDE LCB1: the latch below, before the pure fuel bar
	// The rest of the turn's background work checks its own fuel: 12k is enough after a layer.
	const long keep = std::min(reserve, 12000L);
	// The living bar does not depend on the group: check it before the scan (on 60x60+ boards it is never met).
	if (W.alive && (fuel() < static_cast<long>(DNB_TAB[2]) + (worst_layer > 0 ? worst_layer + worst_layer / 4 : layer_cost()))) // v757 DNB bit 8: spare fuel only, the layer at its measured cost
		return false;
	if (bgd_all_n == static_cast<std::size_t>(M.ng))
		return false; // The scan below would find no group (every route done or full; routes only grow).
	try
	{
		int best = -1, bd = BIG;
		std::size_t bk = 0;
		bool perm = true; // Every group skipped for a reason that never changes.
		if (M.done())
		{
			// b2046 XDE DBC1: access, gems and gold are final once M.done(); the same ascending order and tests as the scan below
			if (bgd_cand_ng != M.ng)
			{
				bgd_cand.clear();
				for (int gi = 0; gi < M.ng; ++gi)
				{
					const auto& g = M.groups[static_cast<std::size_t>(gi)];
					if (!(g.access == ACC_WALK || g.gems + g.gold == 0))
						bgd_cand.push_back(gi);
				}
				bgd_cand_ng = M.ng;
			}
			for (const int gi : bgd_cand)
			{
				const Route* const rp = route_find(gi);
				if (rp && (rp->done || rp->f.size() >= 5))
					continue;
				perm = false;
				if (rp && covers(*rp, from))
					continue;
				const int d = cheb(M.groups[static_cast<std::size_t>(gi)].anchor, from);
				if (d < bd)
				{
					bd = d;
					best = gi;
					bk = !rp ? 0 : rp->f.size();
				}
			}
		}
		else
		for (std::size_t gi = 0; gi < static_cast<std::size_t>(M.ng); ++gi)
		{
			const auto& g = M.groups[gi];
			if (g.access == ACC_WALK || g.gems + g.gold == 0)
				continue;
			const Route* const rp = route_find(static_cast<int>(gi));
			if (rp && (rp->done || rp->f.size() >= 5))
				continue;
			perm = false;
			if (rp && covers(*rp, from))
				continue;
			const int d = cheb(g.anchor, from);
			if (d < bd)
			{
				bd = d;
				best = static_cast<int>(gi);
				bk = !rp ? 0 : rp->f.size();
			}
		}
		if (best < 0)
		{
			if (perm)
				bgd_all_n = static_cast<std::size_t>(M.ng);
			return false;
		}
		long need = layer_cost_c(); // b2046 XDE LCB1
		if (!W.alive)
		{
			// A dead body's turn has nothing else to pay for: the bar of the layer about to be built is its kind's worst cost + 1/8
			// (uncapped: a layer no dead turn can afford is never started), the board prior (at most 80k) until one is measured. A launch
			// layer (k >= 1) is launch() (~32k + 2.5 per tile) and a walk field (~3 per tile reached), more early in the game: up to 65k on
			// 60x60 and 99k on 100x100. Where none can fit a dead turn, build nothing.
			const long launch_prior = std::min(9L * M.w * M.h + 32000, dnb_bound()); // v757 DNB bit 2
			if (worst_launch == 0 && launch_prior + launch_prior / 8 > 88000)
				return false;
			const long w = bk == 0 ? worst_root : worst_launch;
			need = w > 0 ? w + w / 8 : bk == 0 ? std::min(80000L, 22L * M.w * M.h + 4000) : launch_prior;
		}
		if (fuel() < keep + need)
			return false;
		Route& r = route_at(best);
		if (!base_ready)
			calibrate();
		return !r.done && r.f.size() < 5 && build_layer(best, r);
	}
	catch (const std::exception&)
	{
	}
	return false;
}

} // namespace nova::dn
