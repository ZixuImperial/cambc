// move_walls.cc: The turn's move mask and tiles that refused me.
#include "move_internal.h"
namespace nova::mv {
// The retreat tiles of fleeing mates this round, added to the move mask.
static std::array<vec2, 24> frb_tiles{};
static int frb_n = 0, frb_round = -1000;
namespace {
// Static walls plus visible units, visible living camps and unseen camp tiles.
__attribute__((noinline)) const bitboard& dynamic_walls_build()
{
	AF_CHECK();
	// The same mask with no temporary boards: x & ~v == x ^ (x & v); dyn &= ~s == dyn ^= (s & dyn).
	static bitboard pf_s;
	// Once the groups are built (M.block and M.camp_tiles never change after), with T = camp tiles off the static walls and S = M.block
	// | T (disjoint): S ^ (T & vis) = M.block | (camp tiles out of sight), so the same mask takes 4 host ops instead of 5. pf_s is
	// scratch (the ring part below overwrites it before reading it).
	static bitboard px_S, px_T;
	static bool px_st = false;
	if (M.groups_ready())
	{
		if (!px_st)
		{
			bb3_and(M.camp_tiles, M.block, px_T);
			bb3_xor(M.camp_tiles, px_T, px_T);
			bb3_or(M.block, px_T, px_S);
			px_st = true;
		}
		bb3_and(px_T, W.vis, pf_s);
		bb3_xor(px_S, pf_s, dyn_walls);
		bb3_or(dyn_walls, W.occ_units, dyn_walls);
		bb3_or(dyn_walls, W.occ_camps, dyn_walls);
	}
	else
	{
		bb3_or(M.block, W.occ_units, dyn_walls); // F4: three-address host ops, 5 calls for 9
		bb3_or(dyn_walls, W.occ_camps, dyn_walls); // The same ops, with inline checks.
		bb3_and(M.camp_tiles, W.vis, pf_s);
		bb3_xor(pf_s, M.camp_tiles, pf_s);
		bb3_or(dyn_walls, pf_s, dyn_walls);
	}
	if (M.ring)
	{
		bb3_and(known_open, W.vis, pf_s);
		pf_s ^= known_open;
		pf_s &= dyn_walls;
		dyn_walls ^= pf_s;
	}
	static bitboard bh81_tp{ cambc::uninitialized };
	if (cambc::detail::sdk_teleport_occupancy(bh81_tp.ptr()) == 0)
	{
		BH81_CNT(10, [&]() { for (const vec2 dd : DIRS) if (inb(W.me.pos + dd) && bbget(bh81_tp, W.me.pos + dd)) return true; return false; }());
		bb3_or(dyn_walls, bh81_tp, dyn_walls);
	}
	for (vec2 r : refused)
		if (inb(r))
			bbset(dyn_walls, r);
	if (frb_round == W.round) // Set only with the flee-retreat bit on.
		for (int k = 0; k < frb_n; ++k)
			bbset(dyn_walls, frb_tiles[static_cast<std::size_t>(k)]);
	dyn_round = W.round;
	dyn_valid = true;
	return dyn_walls;
}
// Inlined: the per-round memo test runs about 16k times a game; the build is out of line.
NOVA_INLINE const bitboard& dynamic_walls() { return (dyn_valid && dyn_round == W.round) ? dyn_walls : dynamic_walls_build(); }

// A field's compute alone: the buffer fill (distance_field::raw_buffer_size(), ~10k more on 64x64, ~25k real in all) is not in it.
// make_group_field adds it (move_fields.cc:122); the bars at move_fields.cc:59, :68, :197, :202 and :223 use this alone, so a field
// can start about 10k short there (comment only: the bars stay as they are, play-identical).
long field_cost() { return 3L * G.w * G.h + 3000; }
} // namespace
// A tile an unseen occupant refused stays blocked on my next turn too, while I still can't see it. The oldest of the 4 slots goes.
static void note_refused_tile(vec2 p)
{
	int k = 0;
	for (int i = 1; i < 4; ++i)
		if (rfk_until[i] < rfk_until[k])
			k = i;
	rfk_tile[k] = p;
	rfk_until[k] = W.round + 1;
}

// Remember a refused tile that holds a visible teleport reservation (caller read the flag).
void note_teleport_reservation(vec2 p)
{
	// a refusal on a tile I see with no unit, wall or camp on it: a teleport-crystal reservation (the only visible blocker the
	// occupancy boards leave out; no extra engine call)
	if (!inb(p) || !bbget(W.vis, p) || bbget(W.occ_units, p) || bbget(M.block, p) || bbget(W.occ_camps, p))
		return;
	const int k = trz_until[0] <= trz_until[1] ? 0 : 1;
	trz_tile[k] = p;
	trz_until[k] = W.round + TRZ_TAB[2];
}
// Treat tile p as blocked for the rest of this turn (like a refused move).
void avoid_tile(vec2 p)
{
	if (!inb(p))
		return;
	refused.push_back(p);
	dyn_valid = false;
}

// A cast landing an unseen occupant refused stays blocked this turn and my next one (while I still can't see it), as a refused step
// does (caller read the flag).
int refuse_n = 0;
int refused_landings() { return refuse_n; }
void refuse_landing(vec2 p)
{
	if (!inb(p))
		return;
	++refuse_n;
	avoid_tile(p);
	note_refused_tile(p);
}

void set_known_open(const bitboard& b)
{
	known_open = b;
	dyn_valid = false;
}

void begin_turn()
{
	refused.clear();
	for (int i = 0; i < 4; ++i)
		if (rfk_until[i] >= W.round && inb(rfk_tile[i]) && !bbget(W.vis, rfk_tile[i]))
			refused.push_back(rfk_tile[i]);
	for (int i = 0; i < 2; ++i)
		if (trz_until[i] >= W.round)
			refused.push_back(trz_tile[i]); // The reservation lasts the 3-turn channel: kept TRZ_AGE rounds at most.
	dyn_valid = false;
	td_need = 0;
	cd_mode = 0;
	if (W.alive && M.ready())
		update_awake_mem();
	else
	{
		awake_mem.clear();
		++ct_ver; // the awake-camp memory was cleared: bump the version
	}
	if (W.me.pos != last_pos)
	{
		prev_pos = last_pos;
		prev_round = W.round;
		last_pos = W.me.pos;
	}
	if (!W.alive)
		last_pos = vec2{ -1, -1 }; // b2056 DDT bit 2 DTM1: the respawn jump is no step-back
}

const bitboard& blocked() { return dynamic_walls(); }
bool free_tile(vec2 p)
{
	// One read of the per-turn blocked mask (static blocks, visible units and camps, unseen camp tiles, refusals).
	return inb(p) && !bbget(dynamic_walls(), p);
}
} // namespace nova::mv
