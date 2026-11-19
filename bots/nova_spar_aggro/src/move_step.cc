// move_step.cc: One step, travel dashes and stepping down a field.
#include "move_internal.h"
namespace nova::mv {
bool foe_guarded(vec2 p) { return avoid_foe && avoid_on && inb(p) && bbget(avoid_bb, p); }

int bsh_hold_r = -1;
vec2 bsh_tile{ -1, -1 };
void occ_changed() { dyn_valid = false; }
void bush_hold_release()
{
	bsh_hold_r = -1;
	dyn_valid = false; // the mask reads the units perceive just rebuilt
}
bool try_move(vec2 dest)
{
	if (bsh_hold_r == W.round)
		return false;
	if (!W.can_move() || !inb(dest) || cheb(dest, W.me.pos) != 1)
		return false;
	if (sph_pin && !bbget(M.my_spawn, dest))
	{
		SPH_CNT(6, true);
		return false; // A hurt body fighting from its spawn steps only onto spawn tiles.
	}
	if (foe_guarded(dest))
		return false; // Direct steps keep out of a foe guard's zone too.
	if (!eox_escaping && econ::keep_out_of_escaped_reach(dest))
		return false;
	if (!W.attacked && !W.moved)
		combat::prestep_hit_before_move(dest);
	bool ok = false;
	try
	{
		cancel_spin_before_action();
		ok = cambc::self().move_absolute(dest);
	}
	catch (const cambc::error& e)
	{
		NLOG("r%d move error %s\n", W.round, e.what());
		avoid_tile(dest);
		if (e.code() == cambc::error_code::invalid_action_move_bad_destination) // Only the engine's bad-destination error.
			note_teleport_reservation(dest);
		return false;
	}
	catch (const std::exception& e)
	{
		NLOG("r%d move error %s\n", W.round, e.what());
		avoid_tile(dest);
		return false;
	}
	if (!ok)
	{
		avoid_tile(dest);
		if (foe_read_at(dest)) // The refusal revealed a foe.
		{
			note_refused_tile(dest);
			bsh_hold_r = W.round;
			bsh_tile = dest;
		}
		return false;
	}
	W.moved = true;
	refresh_self();
	return true;
}

namespace {
struct Cand
{
	vec2 p;
	int score;
};

// A fixed buffer for the <= 8 step candidates (one per direction), sorted like a vector.
struct CandList
{
	// Raw storage (Cand is an implicit-lifetime aggregate): avoids a 96-byte zeroing (a memory.fill, one fuel a byte); only [0, n) is
	// ever written or read.
	alignas(Cand) unsigned char raw[8 * sizeof(Cand)];
	int n = 0;
	Cand* data() { return reinterpret_cast<Cand*>(raw); }
	void push_back(const Cand& c)
	{
		if (n < 8)
			data()[n++] = c;
	}
	bool empty() const { return n == 0; }
	Cand* begin() { return data(); }
	Cand* end() { return data() + n; }
};
// A move_best candidate may be stepped on: free, and outside an active guard's zone (never back into an awake camp's reach during a
// guarded retreat).
NOVA_INLINE bool step_open(vec2 t) { return free_tile(t) && !(avoid_on && bbget(avoid_bb, t)); }

bool move_best(CandList& cands)
{
	// A unique minimum is element 0 after any correct sort, so it is tried first without sorting. Only if it fails does the sort run,
	// and the loop continues from index 1: the same calls in the same order. Scores are ints.
	Cand* const fx_b = cands.begin();
	const int fx_n = static_cast<int>(cands.end() - fx_b);
	int fx_from = 0;
	if (fx_n >= 2)
	{
		int fx_mi = 0, fx_ms = fx_b[0].score;
		bool fx_tie = false;
		for (int i = 1; i < fx_n; ++i)
		{
			const int sc = fx_b[i].score;
			if (sc < fx_ms)
			{
				fx_ms = sc;
				fx_mi = i;
				fx_tie = false;
			}
			else if (sc == fx_ms)
				fx_tie = true;
		}
		if (!fx_tie)
		{
			const vec2 t = fx_b[fx_mi].p;
			if (step_open(t) && try_move(t))
				return true;
			fx_from = 1;
		}
		std::sort(fx_b, fx_b + fx_n, [](const Cand& a, const Cand& b) { return a.score < b.score; });
	}
	for (int i = fx_from; i < fx_n; ++i)
	{
		const Cand& c = fx_b[i];
		if (step_open(c.p) && try_move(c.p))
			return true;
	}
	return false;
}
} // namespace

// ======== Travel dash ======== Travel dash: top teams dash along their route every 16-20 alive turns. A dash plus the walk covers 3
// tiles in a turn. Kits with a landing effect (Heart of Ruin) only on long trips, so the landing is back off cooldown on arrival,
// and never where the landing would hit a camp (it wakes the camp's whole group). Never with a visible enemy within 10 tiles: the
// dash is kept to escape.
namespace {
// A legal dash middle from `a` to `b` (Chebyshev 2): a tile next to both that is not a wall or a camp tile (holes can be crossed;
// walls cannot). Same rule as dashnav's launch model.
bool dash_mid_ok(vec2 a, vec2 b)
{
	for (int mx = -1; mx <= 1; ++mx)
		for (int my = -1; my <= 1; ++my)
		{
			if (mx == 0 && my == 0)
				continue;
			const vec2 m{ a.x + mx, a.y + my };
			if (!inb(m) || cheb(m, b) != 1 || bbget(M.walls, m) || bbget(M.camp_tiles, m))
				continue;
			if (bbget(M.enemy_spawn, m))
				continue;
			return true;
		}
	return false;
}
// The walk left below which this dash does not pay. Landing kits start from TDX_HOR_NEED tiles.
NOVA_INLINE int travel_dash_min_walk(const Kit& k, bool col)
{
	const int base = col ? tune::TD_COLLECT_WALK : k.dash_mod > 0 ? std::max(3, static_cast<int>(TRAVEL_DASH_TAB[2])) : tune::TD_PLAIN_WALK;
	return std::max(td_need, base);
}
// t is out of each visible foe's reach next turn (its range, a step, its dash, one spare).
NOVA_INLINE bool landing_out_of_foe_reach(vec2 t)
{
	bool unsafe = false;
	for (const auto& e : W.enemies)
		unsafe |= cheb(e.pos, t) <= (std::max(e.range + 2 + ((e.kit && e.kit->slot_dash >= 0) ? 2 : 0), combat::foe_next_turn_reach(e) + 1));
	return !unsafe;
}
// A landing effect hits every camp within its radius and wakes the camp's group. The cleared group I capture (cleared_group >= 0)
// has no living camp to wake.
NOVA_INLINE bool landing_wakes_camp(vec2 t, int land_r, int cleared_group)
{
	for (int ax = -land_r; ax <= land_r; ++ax)
		for (int ay = -land_r; ay <= land_r; ++ay)
		{
			const vec2 q{ t.x + ax, t.y + ay };
			if (!inb(q) || !bbget(M.camp_tiles, q))
				continue;
			if (cleared_group < 0)
				return true;
			const int ci = M.camp_at[static_cast<std::size_t>(q.y * M.w + q.x)];
			if (ci < 0 || M.camps[static_cast<std::size_t>(ci)].group != cleared_group)
				return true;
		}
	return false;
}
// The dash from me to t (at dash range r) is legal.
NOVA_INLINE bool travel_dash_legal(vec2 me, vec2 t, int r)
{
	if (r < 2)
		return true;
	if (!combat::dash_legal_between(me, t))
		return false;
	return !(BGX_ON(2) && !combat::dash_legal_between(me, t));
}

bool travel_dash(const distance_field& f, int ignore_group)
{
	if (!W.alive || !W.me.kit || fuel() < tune::TD_MIN_FUEL)
		return false;
	const Kit& k = *W.me.kit;
	if (k.slot_dash < 0 || !combat::ready(k.slot_dash))
		return false;
	const vec2 me = W.me.pos;
	const std::uint16_t cur = dfget(f, me);
	if (cur == UNREACH)
		return false;
	// A collection dash (the last leg to a camp I tank, a capture region or an altar) pays from 3 tiles out: the dash and the step
	// arrive this turn instead of in three. Landing kits (Heart of Ruin) keep their landing for the camps (camp_abilities) on a camp
	// approach.
	const bool col = cd_mode > 0 && !(cd_mode == 1 && k.dash_mod > 0);
	if (static_cast<int>(cur) < travel_dash_min_walk(k, col))
		return false;
	// While a top group's hole shortcut is still being worked out, only a dash that crosses something (a walk gain of HOLE_SHORT_GAIN
	// or more) goes; a plain 2-tile travel dash would leave the dash on cooldown at the launch.
	const bool opd_hold = !mcl_off(MCL_TAB[5]) && !col && static_cast<int>(W.round) <= OPD_TAB[2] && econ::hs3_pending_x(ignore_group); // Off on the masked map.
	bool foe_near = false;
	for (const auto& e : W.enemies)
		if (cheb(e.pos, me) <= tune::TD_FOE_R)
			foe_near = true;
	// Travel dashes are kept for escapes while a foe is in sight; a collection dash goes when I am healthy and it lands out of every
	// visible foe's next-turn reach.
	if (foe_near && (!col || W.me.frac() < tune::TD_COLLECT_HP))
		return false;
	const int r = std::max(1, static_cast<int>(k.dash_range));
	const int land_r = k.dash_mod > 0 ? std::max(1, static_cast<int>(k.dash_radius)) : -1;
	const int cleared_group = col && cd_mode == 2 ? ignore_group : -1;
	vec2 best{ -1, -1 };
	int best_v = static_cast<int>(cur) - (opd_hold ? HOLE_SHORT_GAIN - 1 : 1); // Must gain at least 2 tiles; when holding, a crossing.
	for (int dx = -r; dx <= r; ++dx)
		for (int dy = -r; dy <= r; ++dy)
		{
			const vec2 t{ me.x + dx, me.y + dy };
			if (cheb(t, me) != r || !inb(t) || !free_tile(t))
				continue;
			const std::uint16_t v = dfget(f, t);
			if (v == UNREACH || static_cast<int>(v) >= best_v)
				continue;
			if (!travel_dash_legal(me, t, r) || camp_threat(t, ignore_group) > 0)
				continue;
			if (col && foe_near && !landing_out_of_foe_reach(t))
				continue;
			if (land_r >= 0 && landing_wakes_camp(t, land_r, cleared_group))
				continue;
			best_v = static_cast<int>(v);
			best = t;
		}
	if (best.x < 0)
		return false;
	if (!combat::cast_at(k.slot_dash, best))
		return false;
	++td_count;
	NLOG("DASH travel r%d slot %d to %d,%d left %d mode %d\n", W.round, P.my_slot, best.x, best.y, best_v, col ? cd_mode : 0);
	return true;
}
// ======== Steps: down a field, greedy, short search ======== An interior tile whose 8 neighbours lie in its own 8x8 chunk (and on
// the board) reads every neighbour's wall bit from one board word and its field value at a constant offset from one chunk base: the
// same values inb + BView + FView give, without the per-neighbour bounds and index arithmetic.
struct Nb8
{
	bool ok = false;
	int o = 0;                         // the tile's bit / slot inside its chunk
	std::uint64_t wall = 0;            // the walls word of the chunk
	const std::uint16_t* fp = nullptr; // the field chunk's 64 values
};
NOVA_INLINE Nb8 nb8(vec2 me, const FView& fv, const BView& bw)
{
	Nb8 r;
	const int lx = me.x & 7, ly = me.y & 7;
	if (!fv.p || !bw.w || lx < 1 || lx > 6 || ly < 1 || ly > 6 || me.x < 1 || me.y < 1 || me.x + 1 >= G.w || me.y + 1 >= G.h)
		return r;
	r.ok = true;
	r.o = (ly << 3) | lx;
	r.wall = bw.w[(me.y >> 3) * bw.stride + (me.x >> 3)];
	r.fp = fv.p + ((me.y >> 3) * fv.cw + (me.x >> 3)) * 64;
	return r;
}
// Each neighbour of me not walled in bw: fn(tile, direction, field value). Unrolled: no loop counter, constant offsets.
template <class Fn> NOVA_INLINE void each_neighbour8(vec2 me, const FView& fv, const BView& bw, Fn&& fn)
{
	const Nb8 nb = nb8(me, fv, bw);
#pragma clang loop unroll(full)
	for (const vec2 d : DIRS)
	{
		const vec2 n = me + d;
		std::uint16_t v;
		if (nb.ok)
		{
			const int o = nb.o + d.y * 8 + d.x;
			if ((nb.wall >> o) & 1u)
				continue;
			v = nb.fp[o];
		}
		else
		{
			if (!inb(n) || bw(n))
				continue;
			v = fv(n);
		}
		fn(n, d, v);
	}
}
// One step down field f through tiles walls leaves open, off the danger board when there is a choice.
bool descend(const distance_field& f, const bitboard& walls, const bitboard& danger, std::uint16_t cur)
{
	const vec2 me = W.me.pos;
	CandList cands;
#pragma clang loop unroll(full)
	for (const vec2 d : DIRS)
	{
		const vec2 n = me + d;
		if (!inb(n) || bbget(walls, n))
			continue;
		const std::uint16_t v = dfget(f, n);
		if (v == UNREACH || v >= cur)
			continue;
		cands.push_back({ n, static_cast<int>(v) * tune::STEP_TILE + (bbget(danger, n) ? 1 : 0) });
	}
	if (cands.empty())
		return false;
	return move_best(cands);
}
} // namespace

void travel_dash_need(int steps) { td_need = std::max(0, steps); }
} // namespace nova::mv
