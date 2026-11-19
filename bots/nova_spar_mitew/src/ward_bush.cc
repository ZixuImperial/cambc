// ward_bush.cc: Placing wards on bushes.
#include "ward_internal.h"
namespace nova::ward {
namespace {
// With the charge ready, ward a bush tile within reach that nobody on the team watches yet (not in my vision, no ward of ours within
// BUSH_GAP), away from the enemy base; prefer bushes 3-6 tiles from the group I farm or head to, the altar I bank at, or a contested
// group (contest .35-.65, within 6 of p). A ward in a bush sees its whole cluster, so enemies waiting there to ambush the farm are
// revealed; it is also hidden from enemies outside the cluster. Costs a few hundred fuel: 24 bit tests and the scores of the few
// bush tiles found. Returns the board the 'unlit bush' tests read. W.vis is perceive's; after a step or dash this turn it shows the
// old tile's view, so my vision is read again (one host call, kept while my tile and perceive's stamp hold).
const bitboard& my_current_vision()
{
	if (W.me.pos == bh67_vpos)
		return W.vis;
	static bitboard lb{ cambc::uninitialized };
	static vec2 lp{ -1, -1 };
	static int ls = -1;
	if (lp != W.me.pos || ls != fg::pstamp)
	{
		if (cambc::detail::sdk_vision(lb.ptr()) != 0)
			return W.vis;
		lp = W.me.pos;
		ls = fg::pstamp;
	}
	return lb;
}
bool bush_place(const cambc::champion& self, vec2 me)
{
	// F4: M.bushes never changes: no bush within reach of me (one bit test on the board dilated by reach_r) has no candidate,
	// and nothing below writes state before a candidate exists. Built once (16 host calls) on the first call that sees a bush.
	static bitboard nb_near, nb_t, nb_h;
	static bool nb_ok = false;
	static bool nb_none = false; // A map without bushes (M.bushes is fixed once the map is ready) answers at once.
	if (nb_none)
		return false;
	if (!nb_ok)
	{
		if (!bbany(M.bushes))
		{
			if (M.ready())
				nb_none = true;
			return false;
		}
		nb_h = M.bushes;
		for (int k = 1; k <= reach_r; ++k)
		{
			M.bushes.shift_right_into(k, nb_t);
			nb_h |= nb_t;
			M.bushes.shift_right_into(-k, nb_t);
			nb_h |= nb_t;
		}
		nb_near = nb_h;
		for (int k = 1; k <= reach_r; ++k)
		{
			nb_h.shift_up_into(k, nb_t);
			nb_near |= nb_t;
			nb_h.shift_up_into(-k, nb_t);
			nb_near |= nb_t;
		}
		nb_ok = true;
	}
	if (inb(me) && !bbget(nb_near, me))
		return false;
	if (XIB_ON(16384) && my_ward.x >= 0 && cheb(my_ward, me) <= BUSH_GAP - reach_r) // v726 XIB BWX1: every box tile is within BUSH_GAP of my ward
		return false;
	int tg = -1; // F4: target and altar read at the first candidate tile
	vec2 tgt{ -1, -1 }, alt{ -1, -1 };
	bool head_read = false;
	vec2 best{ -1, -1 };
	float best_s = 0;
	int bg_n = -1; // Contested anchors, read at the first candidate.
	alignas(vec2) unsigned char bg_raw[64 * sizeof(vec2)]; // only [0, min(bg_n, 64)) is written and read (no zero-fill)
	vec2* const bg_a = reinterpret_cast<vec2*>(bg_raw);
	const BView vb = bview(M.bushes); // F4: on-map tiles of the same scan order, one view
	const int y0 = std::max(me.y - reach_r, 0), y1 = std::min(me.y + reach_r, G.h - 1);
	const int x0 = std::max(me.x - reach_r, 0), x1 = std::min(me.x + reach_r, G.w - 1);
	// The box scan row by row on the chunk words: a row's bush & ~camp & ~vision bits (byte (y & 7) of each chunk word, bit = x & 7)
	// clipped to [x0, x1], then the set bits low to high: the same tiles in the same (y, then x) order.
	(void)vb;
	const std::uint64_t* const bpw = M.bushes.ptr();
	const std::uint64_t* const cpw = M.camp_tiles.ptr();
	const std::uint64_t* const vpw = my_current_vision().ptr(); // W.vis when the WLT bit is off.
	const int gstr = G.stride, cx0 = x0 >> 3, cx1 = x1 >> 3;
	for (int py = y0; py <= y1; ++py)
		for (int cx = cx0; cx <= cx1; ++cx)
		{
			const std::size_t wk = static_cast<std::size_t>((py >> 3) * gstr + cx);
			const int lo = std::max(x0 - cx * 8, 0), hi = std::min(x1 - cx * 8, 7);
			std::uint32_t row = static_cast<std::uint32_t>(((bpw[wk] & ~cpw[wk] & ~vpw[wk]) >> ((py & 7) << 3)) & 0xffu);
			row &= (0xffu << lo) & (0xffu >> (7 - hi));
			for (; row != 0; row &= row - 1)
		{
			const vec2 p{ cx * 8 + __builtin_ctz(row), py };
			if (my_ward.x >= 0 && cheb(my_ward, p) <= BUSH_GAP)
				continue; // A bush my ward lights is already out (W.vis above).
			if ((cheb(p, M.enemy_anchor) <= 8))
				continue;
			if (bad_tile(p) || ally_ward_at(p))
				continue;
			if (!head_read)
			{
				head_read = true;
				tg = econ::claim_target();
				if (tg >= 0 && static_cast<std::size_t>(tg) < static_cast<std::size_t>(M.ng))
					tgt = M.groups[static_cast<std::size_t>(tg)].anchor;
				if (W.me.gems >= 10)
				{
					int bd = BIG;
					for (const auto& a : M.altars)
						if (cheb(a.pos, me) < bd)
						{
							bd = cheb(a.pos, me);
							alt = a.pos;
						}
				}
			}
			float sc = 1.0f;
			if (tgt.x >= 0)
			{
				const int d = cheb(p, tgt);
				sc += d >= 3 && d <= 6 ? 2.0f : (d <= 9 ? 1.0f : 0.0f);
			}
			if (alt.x >= 0 && cheb(p, alt) <= 6)
				sc += 1.0f;
			// The contested groups' anchors listed once per call (first candidate), then the same existence test (any anchor within 6) over
			// the list.
			if (bg_n < 0)
			{
				bg_n = 0;
				for (const auto& g : M.groups)
					if (g.contest >= 0.35f && g.contest <= 0.65f)
					{
						if (bg_n < 64)
							bg_a[bg_n] = g.anchor;
						++bg_n;
					}
			}
			{
				bool hit = false;
				if (bg_n <= 64)
				{
					for (int k = 0; k < bg_n && !hit; ++k)
						hit = cheb(p, bg_a[k]) <= 6;
				}
				else
					for (const auto& g : M.groups)
						if (g.contest >= 0.35f && g.contest <= 0.65f && cheb(p, g.anchor) <= 6)
						{
							hit = true;
							break;
						}
				if (hit)
					sc += 0.5f;
			}
			sc += 0.1f * static_cast<float>(cheb(p, me)); // farther extends the view more
			if (sc > best_s)
			{
				best_s = sc;
				best = p;
			}
		}
		}
	if (best.x < 0)
		return false;
	bool ok = false;
	bool wbn_thr = false; // WBN bit 4: the call threw
	try
	{
		cancel_spin_before_action();
		ok = self.place_ward(best);
	}
	catch (const cambc::error& e)
	{
		wbn_thr = true;
		if (e.code() == cambc::error_code::invalid_action_place_ward_ally_ward_present)
			note_ally_ward_tile(best); // WBN bit 4 (row 768): a mate's ward holds the tile (rc 117, permanent)
		NLOG("r%d slot %d bush ward %d,%d error %s\n", now(), P.my_slot, best.x, best.y, e.what());
	}
	catch (const std::exception& e)
	{
		wbn_thr = true;
		NLOG("r%d slot %d bush ward %d,%d error %s\n", now(), P.my_slot, best.x, best.y, e.what());
		(void)e;
	}
	if (!ok && !wbn_thr)
		note_ally_ward_tile(best); // WBN bit 4 (row 768): a silent false is a mate's permanent ward (INT:149)
	if (!ok)
	{
		bad.push_back({ best, now() + 40 }); // a mate's ward holds the tile (sight is not shared)
		return false;
	}
	NLOG("r%d slot %d WARD bush %d,%d (me %d,%d) score %.1f target %d\n", now(), P.my_slot, best.x, best.y, me.x, me.y,
		best_s, tg);
	++n_bush;
	placed_at(best);
	return true;
}
} // namespace
} // namespace nova::ward
