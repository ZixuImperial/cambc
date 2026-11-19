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
		const v128_t lane = wasm_i16x8_make(0, 1, 2, 3, 4, 5, 6, 7);
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
	mh_pays = true;
	if (!have)
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
		return false; // CDX bit 2: hold on the spawn this turn
	}
	return spawn_crystal_step(bank_field());
}
} // namespace
} // namespace nova::econ
