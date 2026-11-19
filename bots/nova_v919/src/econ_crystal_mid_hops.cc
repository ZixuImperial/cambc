// econ_crystal_mid_hops.cc: Mid-map crystal hops and crystal trips to a bank.
#include "econ_internal.h"
namespace nova::econ {
namespace {
// Best landing within 3 of a tile on field f (mid-route hop).
static int mid_hop_best_landing(vec2 p, const FView& v, vec2* out)
{
	int bv = UNREACH;
	if (v.p)
	{
		// the same scan (rows, then x ascending) on cell rows of 8 lanes: the candidates are the in-box on-map tiles off block_camps with
		// dv < bv (u16), taken low lane first; free_tile is called for exactly the tiles the loop below calls it for, and each new bv
		// narrows the row's remaining candidates. Same calls, same answer.
		const int y0 = std::max(p.y - 3, 0), y1 = std::min(p.y + 3, G.h - 1), x0 = std::max(p.x - 3, 0), x1 = std::min(p.x + 3, G.w - 1);
		const std::uint64_t* const bw = M.block_camps.ptr();
		for (int y = y0; y <= y1; ++y)
			for (int cx = x0 >> 3; cx <= (x1 >> 3); ++cx)
			{
				const std::uint16_t* rp = v.p + ((y >> 3) * v.cw + cx) * 64 + ((y & 7) << 3);
				const int lo = std::max(x0 - cx * 8, 0), hi = std::min(x1 - cx * 8, 7);
				std::uint32_t okm = ((0xffu << lo) & (0xffu >> (7 - hi))) &
					~static_cast<std::uint32_t>((bw[(y >> 3) * G.stride + cx] >> ((y & 7) << 3)) & 0xffu);
				if (y == p.y && (p.x >> 3) == cx)
					okm &= ~(1u << (p.x & 7)); // the centre tile
				const v128_t dvv = wasm_v128_load(rp);
				std::uint32_t mk = okm & wasm_i16x8_bitmask(wasm_u16x8_lt(dvv, wasm_u16x8_splat(static_cast<std::uint16_t>(bv))));
				while (mk != 0)
				{
					const int k = __builtin_ctz(mk);
					mk &= mk - 1;
					const vec2 t{ cx * 8 + k, y };
					if (mv::free_tile(t))
					{
						bv = rp[k];
						if (out)
							*out = t;
						mk &= wasm_i16x8_bitmask(wasm_u16x8_lt(dvv, wasm_u16x8_splat(static_cast<std::uint16_t>(bv))));
					}
				}
			}
		return bv;
	}
	for (int dy = -3; dy <= 3; ++dy)
		for (int dx = -3; dx <= 3; ++dx)
		{
			const vec2 t{ p.x + dx, p.y + dy };
			if ((dx == 0 && dy == 0) || !inb(t) || bbget(M.block_camps, t))
				continue;
			const int dv = v(t);
			if (dv < bv && mv::free_tile(t))
			{
				bv = dv;
				if (out)
					*out = t;
			}
		}
	return bv;
}
static bool mid_hop_try(const distance_field& f, int gi)
{
	if (!W.alive || (SC.on && !SC.used) || W.me.channeling())
		return false;
	if (gi >= 0 && gi != T.target)
		return false; // IDM bit 1: only a walk to my target hops
	const int bit = dn::dasher() ? 2 : 1;
	if ((MH_TAB[1] & bit) == 0)
		return false;
	const vec2 me = W.me.pos;
	const FView v = fview(f);
	const int here = v(me);
	const int bar = MH_TAB[2];
	if (here == UNREACH || here < bar + 4)
		return false;
	const bool have = crystals_carried() > 0;
	if (!have)
		return false;
	// Most turns no tile within 3 is close enough: one field read per tile, before the free-tile and block tests of mid_hop_best_landing.
	const int need = here - bar - 3;
	const int y0 = std::max(me.y - 3, 0), y1 = std::min(me.y + 3, G.h - 1), x0 = std::max(me.x - 3, 0), x1 = std::min(me.x + 3, G.w - 1);
	bool mh_close = false;
	if (v.p && need >= 0 && need < 65535)
	{
		// the same existence test a cell row (8 tiles) at a time: lanes in [x0, x1] whose value <= need (u16)
		const v128_t vn = wasm_u16x8_splat(static_cast<std::uint16_t>(need));
		const v128_t lane = wasm_i16x8_make(0, 1, 2, 3, 4, 5, 6, 7);
		for (int y = y0; y <= y1 && !mh_close; ++y)
			for (int cx = x0 >> 3; cx <= (x1 >> 3) && !mh_close; ++cx)
			{
				const std::uint16_t* rp = v.p + ((y >> 3) * v.cw + cx) * 64 + ((y & 7) << 3);
				const int lo = std::max(x0 - cx * 8, 0), hi = std::min(x1 - cx * 8, 7);
				const v128_t in = wasm_v128_and(wasm_i16x8_ge(lane, wasm_i16x8_splat(static_cast<std::int16_t>(lo))), wasm_i16x8_le(lane, wasm_i16x8_splat(static_cast<std::int16_t>(hi))));
				mh_close = wasm_v128_any_true(wasm_v128_and(in, wasm_u16x8_le(wasm_v128_load(rp), vn)));
			}
	}
	else
	for (int y = y0; y <= y1 && !mh_close; ++y)
		for (int x = x0; x <= x1; ++x)
			if (v(vec2{ x, y }) <= need)
			{
				mh_close = true;
				break;
			}
	if (!mh_close || fuel() < 25000)
		return false;
	vec2 best{ -1, -1 };
	const int bv = mid_hop_best_landing(me, v, &best);
	const int mh_hop = rs::crystal_hop(bv); // only bv 0 moves
	if (bv == UNREACH || here - mh_hop < bar)
		return false;
	int when = mh_hop;
	if (gi >= 0)
	{
		const auto& m = mem[static_cast<std::size_t>(gi)];
		if (m.status == GS_RESPAWN)
			when = std::max(when, m.respawn_at - now()); // up only then: the walk loses nothing up to there
		if (here - when < bar)
			return false;
	}
	// One step along the walk may reach a better launch: go on while it gains (the walk itself loses nothing).
	for (int dy = -1; dy <= 1; ++dy)
		for (int dx = -1; dx <= 1; ++dx)
		{
			const vec2 n{ me.x + dx, me.y + dy };
			if ((dx == 0 && dy == 0) || !inb(n) || v(n) != here - 1 || !mv::free_tile(n))
				continue;
			if (mid_hop_best_landing(n, v, nullptr) < bv - 1)
				return false;
		}
	if (dn::dasher()) // CDW bit 4 (common.h): a thin-hole skip no slower than the hop
	{
		vec2 ca{ -1, -1 }, ct{ -1, -1 };
		if (mv::thin_hole_plan(f, gi, ca, ct) <= when)
		{
			CDW_CNT(6, true);
			mv::thin_hole_skip_crystal_set(&f, ca); // the walk on f takes the skip (step_field)
			return false;
		}
	}
	const int fr = MH_TAB[3];
	for (const auto* e : { &W.enemies, &W.enemies_far })
		for (const auto& o : *e)
			if ((cheb(o.pos, me) <= fr) || cheb(o.pos, best) <= fr)
				return false;
	if (cdx_hot_landing(best))
		return false; // CDX bit 4: a contested landing: walk instead
	std::int32_t ok = 0;
	cancel_spin_before_action();
	if (cambc::detail::sdk_use_consumable(RAW_CRYSTAL, best.x, best.y, &ok) == 0 && ok)
	{
		crystal_count = 0;
		crystal_checked = now();
		refresh_self(); // the channel: later steps of this turn see it
		NLOG("r%d slot %d mid hop %d,%d -> %d,%d g%d save %d\n", now(), P.my_slot, me.x, me.y, best.x, best.y, gi, here - mh_hop);
		return true;
	}
	return false;
}
// bank: a crystal trip to the altar from the spawn. The bank trip from where I stand, with the crystal already in hand. Third price
// beside the walk and the recall + hop: true walk to the launch + hop tail. Cheap Chebyshev bound first; the launch field is
// spawn_crystal_step's own, built once.
static bool bank_hop_from_here()
{
	const SCRoute& r = sc_bank_r;
	if (!sc_any_r || W.on_spawn || prism_layer::route_skip_bh89() || r.cost == UNREACH || now() < sc_skip_until || !W.can_move() || crystals_carried() <= 0)
		return false;
	const distance_field& f = bank_field();
	const int dt = dfget(f, r.T);
	if (dt == UNREACH)
		return false;
	const vec2 me = W.me.pos;
	const int walk = dfget(f, me), rc = recall_hop_cost(r, 2), tail = sc_hop(dt);
	const auto beats = [&](int c) { return (walk == UNREACH || walk - c >= SC_CRY_MIN) && (rc == UNREACH || c <= rc); };
	if (!beats(std::max(0, cheb(me, r.T) - 3) + tail))
		return false;
	if (!(sc_fl && sc_fl_at.x == r.T.x && sc_fl_at.y == r.T.y))
	{
		if (fuel() <= 3L * G.w * G.h + 30000)
			return false;
		bitboard goals;
		goals.draw_chebyshev(r.T, 3.0f);
		goals &= ~M.block_camps;
		auto fl = std::make_unique<distance_field>();
		bitboard visited;
		fl->compute(M.block_camps & ~goals, goals, visited);
		sc_fl = std::move(fl);
		sc_fl_at = r.T;
	}
	const int wl = dfget(*sc_fl, me);
	if (wl == UNREACH || !beats(wl + tail))
		return false;
	if (dn::dasher())
	{
		const int rl = dn::route_len(dn::GOAL_ALTAR, me);
		if (rl != UNREACH && rl <= wl + tail)
			return false; // the dash route is as fast
	}
	sc_end();
	SC.on = true;
	SC.kind = 1;
	SC.gi = -1;
	SC.L = r.L;
	SC.T = r.T;
	SC.rest = tail;
	SC.last = now();
	SC.until = now() + 2 * wl + 8;
	return true;
}
bool spawn_crystal_bank_trip()
{
	if (SC.on && (SC.kind != 1 || now() - SC.last > 2))
		sc_end();
	if ((!M.any_altar && !nwc_map()) || sc_bank_f != &bank_field())
		return false;
	if (!SC.on && !(sc_any_r && W.on_spawn && sc_can() && spawn_crystal_start(1, -1, sc_bank_r, bank_field())) && !(bank_hop_from_here()))
	{
		return false; // no crystal trip this turn (CDX bit 2 is off)
	}
	return spawn_crystal_step(bank_field());
}
// v7xx HPG bit 1 v2: the one-hop launch field of a group no walk reaches (static map: built once per group, in spare fuel). Launch tiles
// are standable tiles off the group's walk region with a legal landing within 3 on it; each costs 3 + the landing's walk to the group.
// The field walks to the launches within 2 of the best one; the price from a tile is that walk + 3 + the best landing walk.
struct HpgLaunch
{
	std::unique_ptr<distance_field> lf;
	std::vector<std::uint16_t> c; // the launch costs while the scan runs (freed when done)
	int cmin = UNREACH, scan_y = -1, scan_x = -1; // scan_x: the next tile of row scan_y (-1: the row's start)
	int goal_y = -1; // HPG fuel adaptation (b1821): the goals pass, resumable by row
	bitboard goals;
	bool done = false;
};
std::vector<HpgLaunch> hpg_l;
// Resumable: the scan of landing rows runs while the turn has fuel to spare (HPG_SCAN_FUEL), and continues on later turns.
const HpgLaunch* hpg_launch(int gi)
{
	if (gi < 0 || gi >= M.ng)
		return nullptr;
	if (hpg_l.size() != static_cast<std::size_t>(M.ng))
	{
		hpg_l.clear();
		hpg_l.resize(static_cast<std::size_t>(M.ng));
	}
	HpgLaunch& h = hpg_l[static_cast<std::size_t>(gi)];
	if (h.done)
		return h.lf ? &h : nullptr;
	const distance_field* f = mv::group_field_ready(gi);
	if (!f)
		return nullptr;
	const auto& g = M.groups[static_cast<std::size_t>(gi)];
	const int R = 14; // landings within this box of the group's members
	const int x0 = std::max(0, g.bx0 - R), x1 = std::min(G.w - 1, g.bx1 + R), y0 = std::max(0, g.by0 - R), y1 = std::min(G.h - 1, g.by1 + R);
	if (h.scan_y < 0)
	{
		h.c.assign(static_cast<std::size_t>(G.w) * static_cast<std::size_t>(G.h), static_cast<std::uint16_t>(UNREACH));
		h.scan_y = y0;
	}
	const FView v = fview(*f);
	for (; h.scan_y <= y1; ++h.scan_y, h.scan_x = -1)
	{
		const int y = h.scan_y;
		for (int x = h.scan_x >= 0 ? h.scan_x : x0; x <= x1; ++x)
		{
			if (fuel() < HPG_SCAN_FUEL) // HPG fuel adaptation (b1821): checked per tile, not per row (a row ran ~49 x width checks past the floor)
			{
				h.scan_x = x;
				return nullptr; // resume on a later turn
			}
			const vec2 t{ x, y };
			const int ft = v(t);
			if (ft == UNREACH || bbget(M.block_camps, t) || bbget(M.enemy_spawn, t))
				continue;
			for (int dy = -3; dy <= 3; ++dy)
				for (int dx = -3; dx <= 3; ++dx)
				{
					const vec2 l{ x + dx, y + dy };
					if (!inb(l) || bbget(M.block_camps, l) || v(l) != UNREACH)
						continue; // a launch stands off the group's walk region
					std::uint16_t& cv = h.c[static_cast<std::size_t>(l.y) * static_cast<std::size_t>(G.w) + static_cast<std::size_t>(l.x)];
					if (ft < cv)
						cv = static_cast<std::uint16_t>(ft);
					h.cmin = std::min(h.cmin, ft);
				}
		}
	}
	if (h.cmin != UNREACH)
	{
		// HPG fuel adaptation (b1821): the goals pass covers only the scan box + 3 (every launch cost lies there; c is UNREACH outside it)
		// and runs by row above HPG_SCAN_FUEL, resumable (the whole-map pass cost ~17 fuel a tile, past the field guard)
		const int gx0 = std::max(0, x0 - 3), gx1 = std::min(G.w - 1, x1 + 3), gy1 = std::min(G.h - 1, y1 + 3);
		if (h.goal_y < 0)
			h.goal_y = std::max(0, y0 - 3);
		for (; h.goal_y <= gy1; ++h.goal_y)
		{
			if (fuel() < HPG_SCAN_FUEL)
				return nullptr; // resume on a later turn
			const int y = h.goal_y;
			for (int x = gx0; x <= gx1; ++x)
				if (h.c[static_cast<std::size_t>(y) * static_cast<std::size_t>(G.w) + static_cast<std::size_t>(x)] <= h.cmin + 2)
					bbset(h.goals, vec2{ x, y });
		}
	}
	if (fuel() < 3L * G.w * G.h + 4000 + HPG_SCAN_FUEL)
		return nullptr; // the field next turn
	h.done = true;
	if (h.cmin != UNREACH)
	{
		h.lf = std::make_unique<distance_field>();
		bitboard visited;
		h.lf->compute(M.block_camps, h.goals, visited);
	}
	std::vector<std::uint16_t>().swap(h.c);
	return h.lf ? &h : nullptr;
}
// The hop price of group gi from tile p (walk to a launch + 3 + the landing's walk), or UNREACH.
int hpg_price(int gi, vec2 p)
{
	const HpgLaunch* h = hpg_launch(gi);
	if (!h)
		return UNREACH;
	const int w = dfget(*h->lf, p);
	return w == UNREACH ? UNREACH : w + 3 + h->cmin;
}
// v7xx HPG bit 16 RETURN: the full one-hop field to the bank, h(x) = min(f(x), 3 + c(x)) relaxed by walking (c(x) = the best legal landing's
// bank walk within 3 of x). Static while the bank field is the same; built over several turns in spare fuel (HPG_SCAN_FUEL).
struct HopField
{
	const distance_field* src = nullptr;
	std::vector<std::uint16_t> rmin, c, h;
	std::vector<std::vector<int>> bq; // Dijkstra buckets (unit steps)
	int phase = 0, row = 0, bk = 0;
	bool done = false;
};
HopField hpg_bank_f;
} // namespace
// v846 SPZ: their spawn rectangle, the foe memory and the home balance (econ_flags.h).
namespace
{
int spz_x0 = -2, spz_y0 = 0, spz_x1 = -1, spz_y1 = -1; // -2: not built
void spz_rect()
{
	if (spz_x0 != -2)
		return;
	spz_x0 = -1;
	bbforeach(M.enemy_spawn, [&](vec2 p) // the set tiles only (a whole-map scan cut turns off on big maps)
	{
		if (spz_x0 < 0)
		{
			spz_x0 = spz_x1 = p.x;
			spz_y0 = spz_y1 = p.y;
		}
		spz_x0 = std::min(spz_x0, p.x);
		spz_x1 = std::max(spz_x1, p.x);
		spz_y0 = std::min(spz_y0, p.y);
		spz_y1 = std::max(spz_y1, p.y);
	});
}
} // namespace
int spz_espawn_d(vec2 p)
{
	spz_rect();
	if (spz_x0 < 0)
		return BIG;
	const int dx = p.x < spz_x0 ? spz_x0 - p.x : (p.x > spz_x1 ? p.x - spz_x1 : 0);
	const int dy = p.y < spz_y0 ? spz_y0 - p.y : (p.y > spz_y1 ? p.y - spz_y1 : 0);
	return std::max(dx, dy);
}
} // namespace nova::econ

