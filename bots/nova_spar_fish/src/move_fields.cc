// move_fields.cc: Walk fields per group and home.
#include "move_internal.h"
namespace nova::mv {
// M.block_camps & ~tiles into a kept board with two host ops (no NOT and AND temporaries, each a board allocation): the same walls
// for the group field.
NOVA_INLINE const bitboard& camp_walls_but_tiles(const bitboard& tiles)
{
	static bitboard r;
	bb3_and(M.block_camps, tiles, r);
	bb3_xor(M.block_camps, r, r);
	return r;
}
// One slot per group in both field lists.
NOVA_INLINE void size_group_field_lists()
{
	if (static_cast<std::size_t>(gf_n) == static_cast<std::size_t>(M.ng))
		return;
	gfields.clear();
	gfields.resize(static_cast<std::size_t>(M.ng));
	gf_n = M.ng;
	gfields_open.clear();
	gfields_open.resize(static_cast<std::size_t>(M.ng));
}
// Group gi's walk field from its camp tiles: camps block except its own; camps_open: every camp passable (gated groups).
static std::unique_ptr<distance_field> make_group_field(int gi, bool camps_open)
{
	bitboard tiles;
	for (int ci : M.groups[static_cast<std::size_t>(gi)].members)
		bbset(tiles, M.camps[static_cast<std::size_t>(ci)].pos);
	auto f = std::make_unique<distance_field>();
	bitboard visited;
	f->compute(camps_open ? M.block : camp_walls_but_tiles(tiles), tiles, visited);
	return f;
}
// The field home from my spawn, camps blocking.
static std::unique_ptr<distance_field> make_home_field()
{
	auto f = std::make_unique<distance_field>();
	bitboard visited;
	f->compute(M.block_camps, M.my_spawn, visited);
	return f;
}
// The field's value at q, FView's index written inline.
NOVA_INLINE std::uint16_t distance_field_value_at(const distance_field& f, vec2 q)
{
	const std::uint16_t* const d = f.ptr();
	return d ? d[((q.y >> 3) * G.cw + (q.x >> 3)) * 64 + ((q.y & 7) << 3) + (q.x & 7)] : f.get(q);
}

const distance_field* group_field(int gi)
{
	if (gi < 0 || gi >= M.ng)
		return nullptr;
	size_group_field_lists();
	auto& slot = gfields[static_cast<std::size_t>(gi)];
	if (!slot)
	{
		// Built in spare fuel at turn ends (build_fields); on demand only when the turn can afford it.
		if (fuel() < field_cost() + tune::FIELD_SLACK)
			return nullptr;
		slot = make_group_field(gi, false);
	}
	if (W.alive && distance_field_value_at(*slot, W.me.pos) == UNREACH)
	{
		auto& open = gfields_open[static_cast<std::size_t>(gi)];
		if (!open)
		{
			if (fuel() < field_cost() + tune::FIELD_SLACK)
				return slot.get();
			open = make_group_field(gi, true);
		}
		return open.get();
	}
	return slot.get();
}
// The walk from p to group gi's camps read from its built field (no work): -1 when unknown (no field, p off the map or on a tile we
// cannot stand on, or no walk while a dash may cross thin holes or the camps-passable field is not built), FP_NOWALK when no walk
// exists.
int group_walk_at(int gi, vec2 p)
{
	if (gi < 0 || gi >= gf_n || !inb(p) || bbget(M.block, p))
		return -1;
	const auto& slot = gfields[static_cast<std::size_t>(gi)];
	if (!slot)
		return -1;
	const std::uint16_t d = dfget(*slot, p);
	if (d != UNREACH)
		return static_cast<int>(d);
	if (gi >= static_cast<int>(gfields_open.size()))
		return -1;
	const auto& open = gfields_open[static_cast<std::size_t>(gi)];
	if (!open)
		return -1;
	const std::uint16_t d2 = dfget(*open, p);
	if (d2 != UNREACH)
		return static_cast<int>(d2);
	return M.has_thin ? -1 : FP_NOWALK;
}
__attribute__((always_inline)) const distance_field* group_field_ready(int gi)
{
	// The same tests with one unsigned bound check and the field read inline (FView's index).
	if (static_cast<std::size_t>(static_cast<unsigned>(gi)) >= static_cast<std::size_t>(gf_n) || gi < 0)
		return nullptr;
	const distance_field* const f = gfields[static_cast<std::size_t>(gi)].get();
	if (!f)
		return nullptr;
	if (W.alive && distance_field_value_at(*f, W.me.pos) == UNREACH)
		return gfields_open[static_cast<std::size_t>(gi)].get();
	return f;
}
// Group gi's walk field (camps block, its own camp tiles open), built now when the turn still has field_cost() + reserve; the same
// field build_fields makes later (so nothing is built twice). nullptr when unaffordable.
const distance_field* group_field_build(int gi, long reserve)
{
	if (gi < 0 || gi >= M.ng)
		return nullptr;
	size_group_field_lists();
	auto& slot = gfields[static_cast<std::size_t>(gi)];
	if (!slot)
	{
		// The build's real cost includes the new field's zero fill and two boards (~1 fuel a byte).
		const long cost = field_cost() + static_cast<long>(distance_field::raw_buffer_size()) +
				2L * static_cast<long>(bitboard::raw_buffer_size()) + 2000L;
		if (fuel() < cost + reserve)
			return nullptr;
		slot = make_group_field(gi, false);
	}
	return slot.get();
}
std::uint16_t group_dist_here(int gi)
{
	if (gi < 0 || gi >= gf_n)
		return UNREACH;
	const auto& slot = gfields[static_cast<std::size_t>(gi)];
	if (!slot)
		return UNREACH;
	const std::uint16_t d = dfget_me(*slot);
	if (W.alive && d == UNREACH)
	{
		const auto& open = gfields_open[static_cast<std::size_t>(gi)];
		return open ? dfget_me(*open) : UNREACH;
	}
	return d;
}

std::uint16_t field_nb(const distance_field& f, vec2 p)
{
	std::uint16_t d = inb(p) ? dfget(f, p) : UNREACH;
	if (d != UNREACH)
		return d;
	for (const vec2 dd : DIRS)
	{
		const vec2 n = p + dd;
		if (!inb(n))
			continue;
		const std::uint16_t v = dfget(f, n);
		if (v != UNREACH && static_cast<std::uint16_t>(v + 1) < d)
			d = static_cast<std::uint16_t>(v + 1);
	}
	return d;
}

const distance_field* group_field_raw(int gi)
{
	if (gi < 0 || gi >= gf_n)
		return nullptr;
	return gfields[static_cast<std::size_t>(gi)].get();
}

// build_fields' scan found nothing left to build (home field and every walkable group's field exist; fields are never dropped and
// group access is fixed after setup); keyed on the group count.
std::size_t bf_done_n = static_cast<std::size_t>(-1);
// The nearest walkable group without a field (its distances matter soonest), or -1.
static int nearest_unbuilt_group()
{
	int best = -1, bd = BIG;
	for (std::size_t gi = 0; gi < static_cast<std::size_t>(M.ng); ++gi)
	{
		const auto& g = M.groups[gi];
		if (gfields[gi] || g.access != ACC_WALK)
			continue;
		const int d = cheb(g.anchor, W.me.pos);
		if (d < bd)
		{
			bd = d;
			best = static_cast<int>(gi);
		}
	}
	return best;
}
int build_fields(long reserve)
{
	if (bf_done_n == static_cast<std::size_t>(M.ng) && static_cast<std::size_t>(gf_n) == bf_done_n && hfield)
		return 0; // The same result as the scan below, without it.
	size_group_field_lists();
	int built = 0;
	if (!hfield && fuel() > reserve + field_cost())
	{
		hfield = make_home_field();
		++built;
	}
	while (fuel() > reserve + field_cost())
	{
		const int best = nearest_unbuilt_group();
		if (best < 0)
		{
			if (hfield)
				bf_done_n = static_cast<std::size_t>(M.ng);
			break;
		}
		gfields[static_cast<std::size_t>(best)] = make_group_field(best, false);
		++built;
	}
	return built;
}

// The home field with camps blocking (nullptr until it is built).
const distance_field* home_field_cb() { return hfield.get(); } // built in spare fuel (build_fields)
const distance_field* home_field()
{
	if (!hfield)
	{
		if (fuel() < field_cost() + tune::HOME_FIELD_SLACK)
			return M.has_home ? &M.f_home : nullptr;
		hfield = make_home_field();
	}
	if (W.alive && dfget_me(*hfield) == UNREACH && M.has_home)
		return &M.f_home;
	return hfield.get();
}
} // namespace nova::mv
