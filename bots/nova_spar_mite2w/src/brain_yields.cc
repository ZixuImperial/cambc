// brain_yields.cc: Giving up my tile for a stuck or hurt mate.
#include "brain_internal.h"
namespace nova {
namespace {
// v708 BF5 bit 1 YCH1: an ally that cannot move this turn (channelling, or stunned). One call per skip (firecount).
static __attribute__((noinline)) bool ych_busy(const Body& a) { return a.channeling() || a.stunned; }
// Allies' tiles at my previous turn (stuck = same tile one round later).
std::array<vec2, 8> my_apos{};
std::array<int, 8> my_around{ { -10, -10, -10, -10, -10, -10, -10, -10 } };
// The round of my last yield to each ally slot and the ally's tile then.
std::array<int, 8> spw_yr{ { -100, -100, -100, -100, -100, -100, -100, -100 } };
std::array<vec2, 8> spw_ypos{};
bool mate_yield(bool go)
{
	const vec2 me = W.me.pos;
	bool moved = false;
	bool calm = go && W.can_move();
	for (const auto& e : W.enemies)
		if (cheb(e.pos, me) <= 8)
			calm = false;
	if (calm)
	{
		const int mt = econ::claim_target();
		const distance_field* fm = mt >= 0 ? mv::group_field_ready(mt) : nullptr;
		for (const auto& a : W.allies)
		{
			if (a.slot < 0 || a.slot >= 8 || cheb(a.pos, me) != 1)
				continue;
			if (ych_busy(a))
				continue; // v708 BF5 bit 1 YCH1: a channelling or stunned ally cannot take my tile
			const auto sl = static_cast<std::size_t>(a.slot);
			if (my_around[sl] != W.round - 1 || my_apos[sl] != a.pos)
				continue; // it moved since my last turn (or I did not see it): not stuck
			if (spw_yr[sl] >= W.round - 40 && spw_ypos[sl] == a.pos)
				continue; // It did not take the tile I gave it: it waits, not stuck.
			const int gt = comms::cgroup(a.slot);
			if (gt < 0)
				continue;
			const distance_field* fa = mv::group_field_ready(gt);
			if (!fa)
				continue;
			const std::uint16_t va = dfget(*fa, a.pos), vm = dfget(*fa, me);
			if (va == UNREACH || vm == UNREACH || vm >= va || va <= 1)
				continue; // my tile is not on its way (or it is already at its group)
			if (fm && P.my_slot < a.slot)
			{
				const std::uint16_t ma = dfget(*fm, a.pos), mm = dfget(*fm, me);
				if (ma != UNREACH && mm != UNREACH && ma < mm)
					continue; // mutual block: the lower slot keeps the right of way
			}
			const float th0 = mv::camp_threat(me, mt);
			vec2 best{ -1, -1 };
			int bs = 1 << 30;
#pragma clang loop unroll(full)
			for (const vec2 d : DIRS)
			{
				const vec2 n = me + d;
				if (n == a.pos || !mv::free_tile(n) || mv::camp_threat(n, mt) > th0)
					continue;
				const std::uint16_t vn = dfget(*fa, n);
				int s = (vn != UNREACH && vn >= va) ? 0 : 1000; // off its path first, else further along it
				if (fm)
				{
					const std::uint16_t f = dfget(*fm, n);
					s += f == UNREACH ? 500 : static_cast<int>(f);
				}
				if (s < bs)
				{
					bs = s;
					best = n;
				}
			}
			if (best.x >= 0 && mv::try_move(best))
			{
				moved = true;
				spw_yr[sl] = W.round;
				spw_ypos[sl] = a.pos;
			}
			break;
		}
	}
	for (const auto& a : W.allies)
		if (a.slot >= 0 && a.slot < 8)
		{
			my_apos[static_cast<std::size_t>(a.slot)] = a.pos;
			my_around[static_cast<std::size_t>(a.slot)] = W.round;
		}
	return moved;
}
// deadend_yield's early tests plus its loop's first ally tests, inline at the call site; false means deadend_yield would return false with
// no move (it skips every ally failing these tests).
inline bool deadend_yield_pre()
{
	if (!W.alive || W.moved || !W.can_move() || W.me.channeling() || !M.has_home)
		return false;
	const float mf = W.me.frac();
	for (const auto& a : W.allies)
		if (a.hp > 0 && cheb(a.pos, W.me.pos) == 1 && a.frac() < 0.75f && a.frac() < mf)
			return true;
	return false;
}
// A hurt adjacent ally whose only free way home runs through my tile gets it.
__attribute__((noinline)) bool deadend_yield()
{
	if (!W.alive || W.moved || !W.can_move() || W.me.channeling() || !M.has_home || fuel() <= MY_FUEL || econ::busy_capturing())
		return false;
	const vec2 me = W.me.pos;
	const std::uint16_t hm = dfget(M.f_home, me);
	if (hm == UNREACH)
		return false;
	const float myf = W.me.frac();
	std::vector<mv::Threat> th;
	bool th_ok = false;
	for (const auto& a : W.allies)
	{
		if (a.hp <= 0 || cheb(a.pos, me) != 1)
			continue;
		if (ych_busy(a))
			continue; // v708 BF5 bit 1 YCH1
		const float fa = a.frac();
		if (fa >= 0.75f || fa >= myf)
			continue;
		const std::uint16_t ha = dfget(M.f_home, a.pos);
		if (ha == UNREACH || hm >= ha)
			continue; // my tile is not on its way home
		bool other = false; // another free neighbour of its tile nearer home: not blocked by me
		for (const vec2 d : DIRS)
		{
			const vec2 n = a.pos + d;
			if (n == me || !mv::free_tile(n))
				continue;
			const std::uint16_t hn = dfget(M.f_home, n);
			if (hn != UNREACH && hn < ha)
			{
				other = true;
				break;
			}
		}
		if (other)
			continue;
		if (fa >= 0.5f)
		{
			if (!th_ok)
			{
				th = mv::camp_threats_near(9);
				th_ok = true;
			}
			if (!mv::in_threat(th, a.pos))
				continue; // 50-75% HP and out of every awake camp's reach: not leaving fire
		}
		const float t0 = mv::camp_threat(me);
		vec2 best{ -1, -1 };
		int bs = 1 << 30;
		for (const vec2 d : DIRS)
		{
			const vec2 n = me + d;
			if (n == a.pos || !mv::free_tile(n))
				continue;
			const std::uint16_t hn = dfget(M.f_home, n);
			if (hn == UNREACH || mv::camp_threat(n) > t0)
				continue;
			const int s = (hn >= hm ? 0 : 1000) + static_cast<int>(hn); // off its way home first, else further along it
			if (s < bs)
			{
				bs = s;
				best = n;
			}
		}
		if (best.x >= 0 && mv::try_move(best))
			return true;
		return false;
	}
	return false;
}
} // namespace

namespace {

bool planned = false;
// My last own turn: its round, HP at its start, whether it attacked or cast.
int re_round = -1000;
float re_hp = 0;
bool re_acted = true;
} // namespace
} // namespace nova
