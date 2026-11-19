// move_thin_holes.cc: Thin-hole skips: walk then dash.
#include "move_internal.h"
namespace nova::mv {
namespace
{
constexpr vec2 CDW_OFF[16] = { { -2, -2 }, { -1, -2 }, { 0, -2 }, { 1, -2 }, { 2, -2 }, { -2, -1 }, { 2, -1 }, { -2, 0 },
	                           { 2, 0 },   { -2, 1 },  { 2, 1 },  { -2, 2 }, { -1, 2 }, { 0, 2 },  { 1, 2 },  { 2, 2 } };
constexpr int CDW_BUILD_RESERVE = 50000; // the static build runs one thin hole at a time while this much of the turn is left
constexpr int CDW_HOLD = 10;             // rounds at most on one launch tile waiting for the cooldown (the dash cooldown)
constexpr int CDW_FUEL = 50000; // A new plan (window scan + one host BFS) only with this much of the turn left.
constexpr int CDW_RMAX = 16;             // the widest window (spawn_crystal_start: the hop's launch distance + 3)
constexpr int CDW_R = 8;                 // launch tiles within this Chebyshev distance of me (farther ones: hs3's built routes)
constexpr int CDW_RETRY = 3;             // rounds before the same field is planned again after a plan found no legal skip
std::vector<std::uint16_t> cdw_ring; // Per tile: bit o when a dash by CDW_OFF[o] crosses a thin hole onto a standable tile.
std::vector<std::uint16_t> cdw_blk;      // per 8x8 block: launch tiles in it (the window scan skips empty blocks)
std::vector<std::uint8_t> cdw_done;      // per 8x8 block: its thin holes have been scanned (built on demand, where I walk)
constexpr int CDW_SLICE = 15000;         // block builds spend at most this much fuel a turn
// Direction pairs (around a hole m) whose tiles m + DIRS[i], m + DIRS[j] are 2 apart, with the dash offset index: built once.
struct CdwPair
{
	std::uint8_t i, j, o;
};
std::vector<CdwPair> cdw_pairs;
int cdw_state = 0;                       // 0 not started, 1 ready (blocks build on demand)
std::vector<std::pair<vec2, vec2>> cdw_cand;
distance_field cdw_d; // Host BFS from me inside the window (planning turns only).
// The plan: field, ignore group, the walk to the launch (path[0] = the first step, back() = the launch), the landing.
struct CdwPlan
{
	const distance_field* f = nullptr;
	int ig = -1, made = -1;
	bool sc = false; // Committed by spawn_crystal_start / mid_hop_try (runs without bit 2).
	std::vector<vec2> path;
	vec2 a{ -1, -1 }, t{ -1, -1 }, from{ -1, -1 };
};
CdwPlan cdw_p;
const distance_field* cdw_nf = nullptr; // the last field a plan found no legal skip for, and when
int cdw_nr = -1000;
int cdw_hold_n = 0, cdw_hold_r = -10;
vec2 cdw_hold_p{ -1, -1 };
NOVA_INLINE bool cdw_stand(vec2 p) { return inb(p) && !bbget(M.block_camps, p); }
// The static part, per body and per 8x8 block on demand: every (launch, offset) whose dash has a thin hole of the block as a middle
// (a hole middle is never a wall, camp, unit, crystal landing or spawn tile, so it is legal) and lands on a standable tile. Blocks
// are built for the tiles a plan's window reads, CDW_SLICE fuel a turn at most.
bool thin_hole_init()
{
	if (cdw_state == 1)
		return true;
	if (!M.done() || !M.has_thin || fuel() < CDW_BUILD_RESERVE)
		return false;
	const std::size_t nb = static_cast<std::size_t>(((G.w + 7) >> 3) * ((G.h + 7) >> 3));
	cdw_ring.assign(static_cast<std::size_t>(G.w * G.h), 0);
	cdw_blk.assign(nb, 0);
	cdw_done.assign(nb, 0);
	cdw_pairs.clear();
	for (int i = 0; i < 8; ++i)
		for (int j = 0; j < 8; ++j)
		{
			const vec2 da = DIRS[i], dt = DIRS[j];
			const int dx = dt.x - da.x, dy = dt.y - da.y;
			if (std::max(iabs(dx), iabs(dy)) != 2)
				continue;
			const int o = dy == -2 ? dx + 2 : dy == 2 ? dx + 13 : dx == -2 ? 5 + 2 * (dy + 1) : 6 + 2 * (dy + 1);
			cdw_pairs.push_back({ static_cast<std::uint8_t>(i), static_cast<std::uint8_t>(j), static_cast<std::uint8_t>(o) });
		}
	cdw_state = 1;
	return true;
}
// Build every block that touches the rectangle (launch tiles in it come from thin holes within 1, so the caller widens by 1).
bool thin_hole_build_rect(int x0, int y0, int x1, int y1)
{
	const long f0 = fuel();
	const int bw = (G.w + 7) >> 3;
	for (int by = std::max(0, y0) >> 3; by <= (std::min(G.h - 1, y1) >> 3); ++by)
		for (int bx = std::max(0, x0) >> 3; bx <= (std::min(G.w - 1, x1) >> 3); ++bx)
		{
			std::uint8_t& done = cdw_done[static_cast<std::size_t>(by * bw + bx)];
			if (done)
				continue;
			if (fuel() < CDW_BUILD_RESERVE || f0 - fuel() > CDW_SLICE)
				return false;
			for (int y = by * 8; y < std::min(G.h, by * 8 + 8); ++y)
				for (int x = bx * 8; x < std::min(G.w, bx * 8 + 8); ++x)
				{
					const vec2 m{ x, y };
					if (!bbget(M.thin_holes, m))
						continue;
					bool st[8];
					for (int d = 0; d < 8; ++d)
						st[d] = cdw_stand(m + DIRS[d]);
					for (const CdwPair& q : cdw_pairs)
						if (st[q.i] && st[q.j])
						{
							const vec2 a = m + DIRS[q.i];
							std::uint16_t& cell = cdw_ring[static_cast<std::size_t>(a.y * G.w + a.x)];
							if (cell == 0)
								++cdw_blk[static_cast<std::size_t>((a.y >> 3) * bw + (a.x >> 3))];
							cell |= static_cast<std::uint16_t>(1u << q.o);
						}
				}
			done = 1;
		}
	return true;
}
// The live dash test from a to t (middles as the engine sees them now, the landing's camps and foes).
bool thin_hole_dash_legal(vec2 a, vec2 t, int ignore_group)
{
	const Kit& k = *W.me.kit;
	if (!travel_dash_legal(a, t, 2) || !combat::dash_legal_between(a, t) || camp_threat(t, ignore_group) > 0)
		return false;
	if (k.dash_mod > 0 && landing_wakes_camp(t, std::max(1, static_cast<int>(k.dash_radius)), -1))
		return false;
	return a != W.me.pos || free_tile(t);
}
// The common gate: a dasher with a 2-tile dash, alive and free, no foe near (as travel_dash: the dash is kept for an escape).
bool thin_hole_dash_gate()
{
	if (!W.alive || !W.me.kit || W.me.channeling() || !M.has_thin)
		return false;
	const Kit& k = *W.me.kit;
	if (k.slot_dash < 0 || static_cast<int>(k.dash_range) != 2)
		return false;
	for (const auto& e : W.enemies)
		if (cheb(e.pos, W.me.pos) <= tune::TD_FOE_R)
			return false;
	return true;
}
// The host BFS from me with everything outside the window walled (its own function so the fuel profiler prices it apart).
__attribute__((noinline)) void thin_hole_window_bfs(vec2 me, int R)
{
	bitboard roots{}, vis{}, walls{};
	walls.draw_chebyshev(me, static_cast<float>(R));
	walls = ~walls;
	walls |= M.block_camps;
	bbset(roots, me);
	cdw_d.compute(walls, roots, vis);
}
NOVA_INLINE int cdw_cdr() { return std::max(0, static_cast<int>(W.cd[static_cast<std::size_t>(W.me.kit->slot_dash)])); }
} // namespace
void thin_hole_skip_crystal_set(const distance_field* f, vec2 a)
{
	if (cdw_p.f == f && cdw_p.a == a)
		cdw_p.sc = true;
}
// A new plan from me: launches within rad (window scan of the static pairs, Chebyshev bound first), the real walk to each by one
// host BFS inside the window, the live dash test on the best. Stored in cdw_p with its path.
int thin_hole_plan(const distance_field& f, int ignore_group, vec2& a_out, vec2& t_out, int rad)
{
	if (!thin_hole_dash_gate())
		return UNREACH;
	const vec2 me = W.me.pos;
	const FView fv = fview(f);
	const int walk = fv(me);
	if (walk == UNREACH || walk < HOLE_SHORT_MIN)
		return UNREACH;
	const int rnd = static_cast<int>(W.round);
	if (cdw_p.f == &f && cdw_p.made == rnd && cdw_p.from == me)
	{
		a_out = cdw_p.a; // asked again this round before a step (spawn_crystal_start, then step_field)
		t_out = cdw_p.t;
		return std::max(static_cast<int>(cdw_p.path.size()), cdw_cdr()) + fv(cdw_p.t);
	}
	if ((cdw_nf == &f && rnd - cdw_nr < CDW_RETRY) || fuel() < CDW_FUEL || !thin_hole_init())
		return UNREACH;
	const int R = rad > 0 ? std::min(rad, CDW_RMAX) : CDW_R;
	const int cdr = cdw_cdr();
	cdw_cand.clear();
	const int y0 = std::max(0, me.y - R), y1 = std::min(G.h - 1, me.y + R);
	const int x0 = std::max(0, me.x - R), x1 = std::min(G.w - 1, me.x + R);
	if (!thin_hole_build_rect(x0 - 1, y0 - 1, x1 + 1, y1 + 1))
		return UNREACH; // blocks still to scan: the next turns go on
	bool any = false; // the blocks the window touches: any launch tile?
	const int bw = (G.w + 7) >> 3;
	for (int by = y0 >> 3; by <= (y1 >> 3) && !any; ++by)
		for (int bx = x0 >> 3; bx <= (x1 >> 3) && !any; ++bx)
			any = cdw_blk[static_cast<std::size_t>(by * bw + bx)] != 0;
	if (!any)
		return UNREACH;
	for (int y = y0; y <= y1; ++y)
	{
		if (fuel() < CDW_FUEL / 2)
		{
			return UNREACH; // a wide window late in a turn: the next round scans again
		}
		const std::uint16_t* row = cdw_ring.data() + static_cast<std::size_t>(y * G.w);
		for (int x = x0; x <= x1; ++x)
		{
			unsigned r = row[x];
			if (r == 0)
				continue;
			const vec2 a{ x, y };
			const int ca = std::max(cheb(me, a), cdr);
			if (ca + HOLE_SHORT_GAIN >= walk)
				continue;
			for (; r != 0; r &= r - 1)
			{
				const vec2 t = a + CDW_OFF[__builtin_ctz(r)];
				const int ft = fv(t);
				if (ft != UNREACH && ca + ft + HOLE_SHORT_GAIN <= walk)
					cdw_cand.push_back({ a, t });
			}
		}
	}
	if (cdw_cand.empty())
	{
		cdw_nf = &f; // nothing near enough: skip one round, then scan again (a step moves the window by one a round)
		cdw_nr = rnd - (CDW_RETRY - 2);
		return UNREACH;
	}
	if (fuel() < 3L * G.w * G.h + CDW_FUEL)
	{
		return UNREACH; // The host BFS costs about 3 fuel a tile.
	}
	thin_hole_window_bfs(me, R);
	const FView dv = fview(cdw_d);
	int best = UNREACH;
	for (const auto& c : cdw_cand)
	{
		const int da = dv(c.first);
		if (da == UNREACH)
			continue;
		const int s = std::max(da, cdr) + fv(c.second);
		if (s + HOLE_SHORT_GAIN > walk || s >= best || !thin_hole_dash_legal(c.first, c.second, ignore_group))
			continue;
		best = s;
		a_out = c.first;
		t_out = c.second;
	}
	if (best == UNREACH)
	{
		cdw_nf = &f;
		cdw_nr = rnd;
		return UNREACH;
	}
	// The walk from me to the launch, read back down my BFS field from the launch.
	cdw_p.f = &f;
	cdw_p.ig = ignore_group;
	cdw_p.made = rnd;
	cdw_p.sc = false;
	cdw_p.a = a_out;
	cdw_p.t = t_out;
	cdw_p.from = me;
	cdw_p.path.clear();
	vec2 p = a_out;
	for (int dp = dv(p); dp > 0; --dp)
	{
		cdw_p.path.push_back(p);
		bool found = false;
		for (const vec2 d : DIRS)
		{
			const vec2 n = p + d;
			if (inb(n) && dv(n) == dp - 1)
			{
				p = n;
				found = true;
				break;
			}
		}
		if (!found)
		{
			cdw_p.f = nullptr;
			return UNREACH;
		}
	}
	std::reverse(cdw_p.path.begin(), cdw_p.path.end());
	return best;
}
// One move along the plan for field f: a step toward the launch, the dash (the walk on is step_field's), or a hold for the cooldown.
// The plan is followed without a new search while it still saves HOLE_SHORT_GAIN over the walk.
static bool thin_hole_turn(const distance_field& f, int ignore_group)
{
	const bool mine = cdw_p.f == &f && cdw_p.ig == ignore_group;
	const vec2 me = W.me.pos;
	const int rnd = static_cast<int>(W.round);
	bool ok = mine && thin_hole_dash_gate();
	if (ok)
	{
		// on the path (or on the launch): drop what is behind me; the plan holds while it still saves the gain
		auto it = std::find(cdw_p.path.begin(), cdw_p.path.end(), me);
		if (it != cdw_p.path.end())
			cdw_p.path.erase(cdw_p.path.begin(), it + 1);
		else if (!cdw_p.path.empty() && cheb(me, cdw_p.path.front()) > 1)
			ok = false; // pushed off the path
		const FView fv = fview(f);
		const int walk = fv(me), ft = fv(cdw_p.t);
		ok = ok && walk != UNREACH && ft != UNREACH &&
			 std::max(static_cast<int>(cdw_p.path.size()), cdw_cdr()) + ft + (cdw_p.sc ? 0 : HOLE_SHORT_GAIN) <= walk;
	}
	if (!ok)
	{
		const bool had = mine;
		cdw_p.f = nullptr;
		if (had && cdw_p.made == rnd)
			return false;
		vec2 a{ -1, -1 }, t{ -1, -1 };
		if (thin_hole_plan(f, ignore_group, a, t, 0) == UNREACH)
			return false;
	}
	const Kit& k = *W.me.kit;
	if (cdw_p.path.empty()) // on the launch tile
	{
		if (!thin_hole_dash_legal(me, cdw_p.t, ignore_group))
		{
			cdw_p.f = nullptr;
			cdw_nf = &f;
			cdw_nr = rnd;
			return false;
		}
		if (combat::ready(k.slot_dash))
		{
			const bool cast = combat::cast_at(k.slot_dash, cdw_p.t);
			CDW_CNT(1, cast);
			cdw_p.f = nullptr;
			if (cast)
			{
				++td_count;
				cdw_hold_n = 0;
			}
			return false; // the walk goes on from the landing (step_field)
		}
		cdw_hold_n = (cdw_hold_p == me && cdw_hold_r == rnd - 1) ? cdw_hold_n + 1 : 1;
		cdw_hold_p = me;
		cdw_hold_r = rnd;
		if (cdw_hold_n > CDW_HOLD || W.moved)
		{
			cdw_p.f = nullptr;
			return false;
		}
		CDW_CNT(2, true);
		return true; // hold on the launch tile for the cooldown
	}
	if (!try_move(cdw_p.path.front()))
		return false;
	cdw_p.path.erase(cdw_p.path.begin());
	CDW_CNT(3, true);
	return true;
}
void collect_dash(int mode) { cd_mode = mode; }
static bool vfd_dash_only = false; // CB3 bit 8192 VFD
void collect_dash_only(bool on) { vfd_dash_only = on; }
int fxr_vfd_stuck = 0; // FXR bit 2: turns that began with vfd_dash_only still set
// FXR bits 1 and 2, at play_turn_body's entry: hand-set toggles a call left set when an AfBail or RestartTurn unwound past their
// clear (static_audit.md pattern 1). Each is false between calls, so this changes nothing on a turn without an unwind.
void fxr_entry_resets()
{
	if (vfd_dash_only)
	{
		++fxr_vfd_stuck; // FXR-DG-VFD
	}
	vfd_dash_only = false;
	return;
}
bool step_field(const distance_field& f, int ignore_group)
{
	if (!W.can_move())
		return false;
	if (thin_hole_turn(f, ignore_group))
		return true;
	travel_dash(f, ignore_group);
	const vec2 me = W.me.pos;
	const FView fv = fview(f); // F4: one view of the field and of the blocked mask (nothing below changes them)
	const BView bw = bview(dynamic_walls());
	const std::uint16_t cur = fv(me);
	CandList cands;
	each_neighbour8(me, fv, bw,
		[&](vec2 n, vec2 d, std::uint16_t v) __attribute__((always_inline))
		{
			if (v == UNREACH)
				return;
			if (cur != UNREACH && v > cur)
				return;
			if (cur != UNREACH && v == cur && n == prev_pos)
				return;
			int score = static_cast<int>(v) * tune::STEP_TILE;
			if (cur != UNREACH && v == cur)
				score += tune::STEP_LEVEL;
			score += static_cast<int>(camp_threat(n, ignore_group));
			// Prefer straight progress (fewer zig-zags in corridors) slightly.
			if (d.x != 0 && d.y != 0)
				score += 1;
			cands.push_back({ n, score });
		});
	if (cands.empty())
		return false;
	return move_best(cands);
}
bool step_greedy(vec2 target, int ignore_group)
{
	if (!W.can_move() || !inb(target))
		return false;
	const vec2 me = W.me.pos;
	const int cur = cheb(me, target);
	CandList cands;
#pragma clang loop unroll(full) // The 8 directions unrolled (no loop counter, constant offsets).
	for (const vec2 d : DIRS)
	{
		const vec2 n = me + d;
		if (!free_tile(n))
			continue;
		const int v = cheb(n, target);
		if (v >= cur)
			continue;
		// Prefer the step that also closes the larger axis gap (straighter path), then lower camp danger.
		const int lin = iabs(n.x - target.x) + iabs(n.y - target.y);
		cands.push_back({ n, v * tune::GREEDY_TILE + lin * tune::GREEDY_AXIS + static_cast<int>(camp_threat(n, ignore_group)) });
	}
	if (cands.empty())
		return false;
	return move_best(cands);
}
bool step_greedy_set(const bitboard& goals, int ignore_group)
{
	// Nearest goal tile by Chebyshev distance, then a greedy step toward it.
	vec2 best{ -1, -1 };
	int bd = BIG;
	bbforeach(goals,
		[&](vec2 p)
		{
			const int d = cheb(p, W.me.pos);
			if (d < bd)
			{
				bd = d;
				best = p;
			}
		});
	return best.x >= 0 && step_greedy(best, ignore_group);
}
// Sum of x, sum of y and count of the set in-board tiles of b (NOVA_GDIRECT layout: 8x8 chunks, bit = y * 8 + x), by popcounts per
// chunk word: equal to bbforeach's per-tile sums (integers, any order).
static void popcount_centroid(const bitboard& b, long& sx, long& sy, long& cnt)
{
	constexpr std::uint64_t X1 = 0xAAAAAAAAAAAAAAAAull, X2 = 0xCCCCCCCCCCCCCCCCull, X4 = 0xF0F0F0F0F0F0F0F0ull;
	constexpr std::uint64_t Y1 = 0xFF00FF00FF00FF00ull, Y2 = 0xFFFF0000FFFF0000ull, Y4 = 0xFFFFFFFF00000000ull;
	const std::uint64_t* w = b.ptr();
	const int nw = G.ch * G.stride;
	auto word_at = [&](int k)
	{
		std::uint64_t word = w[k];
		const int cy = k / G.stride, cx = k - cy * G.stride;
		if (cx >= G.cw)
			return; // row padding: bbforeach never reads it
		const int nx = G.w - cx * 8, ny = G.h - cy * 8;
		if (nx < 8)
			word &= ((std::uint64_t(1) << nx) - 1) * 0x0101010101010101ull;
		if (ny < 8)
			word &= (std::uint64_t(1) << (ny * 8)) - 1;
		if (!word)
			return;
		const long pc = __builtin_popcountll(word);
		cnt += pc;
		sx += static_cast<long>(cx * 8) * pc + __builtin_popcountll(word & X1) + 2 * __builtin_popcountll(word & X2) + 4 * __builtin_popcountll(word & X4);
		sy += static_cast<long>(cy * 8) * pc + __builtin_popcountll(word & Y1) + 2 * __builtin_popcountll(word & Y2) + 4 * __builtin_popcountll(word & Y4);
	};
	int k = 0;
	for (; k + 4 <= nw; k += 4) // 4 empty words skipped per test (same words visited, same sums).
	{
		if (!wasm_v128_any_true(wasm_v128_or(wasm_v128_load(w + k), wasm_v128_load(w + k + 2))))
			continue;
		if (w[k])
			word_at(k);
		if (w[k + 1])
			word_at(k + 1);
		if (w[k + 2])
			word_at(k + 2);
		if (w[k + 3])
			word_at(k + 3);
	}
	for (; k + 2 <= nw; k += 2)
	{
		if (!wasm_v128_any_true(wasm_v128_load(w + k)))
			continue;
		if (w[k])
			word_at(k);
		if (w[k + 1])
			word_at(k + 1);
	}
	for (; k < nw; ++k)
		if (w[k])
			word_at(k);
}
// The search cost grows with its radius: keep it inside the fuel left this turn.
NOVA_INLINE int skip_search_radius_for_fuel(long left, int max_search)
{
	if (left < tune::STS_R10_FUEL)
		return std::min(max_search, tune::STS_R10);
	if (left < tune::STS_R20_FUEL)
		return std::min(max_search, tune::STS_R20);
	return max_search;
}
// A search that found no path from this tile, with the same walls, goals and radius, finds none again (the field is a pure function
// of them): answer from the record of failed searches (one body once repeated ~248 failed searches toward an enclosed goal).
struct StsFail
{
	bitboard w, r;
	vec2 me{ -1, -1 };
	int rad = -1;
};
struct StsFails
{
	std::array<StsFail, 2> list;
	int next = 0;
};
NOVA_INLINE StsFails& skip_search_failure_memo()
{
	static StsFails f;
	return f;
}
// Equal best scores: the candidate nearest the goals' centroid goes first.
NOVA_INLINE void skip_search_break_tie(CandList& cands, const bitboard& roots)
{
	int best = BIG, tied = 0;
	for (const auto& c : cands)
		best = std::min(best, c.score);
	for (const auto& c : cands)
		tied += c.score == best;
	if (tied < 2)
		return;
	long sx = 0, sy = 0, cnt = 0;
	if (NOVA_GDIRECT)
		popcount_centroid(roots, sx, sy, cnt); // The same sums by word popcounts.
	else
		bbforeach(roots,
			[&](vec2 p)
			{
				sx += p.x;
				sy += p.y;
				++cnt;
			});
	if (cnt <= 0)
		return;
	Cand* pick = nullptr;
	std::int64_t pd = 0;
	for (auto& c : cands)
		if (c.score == best)
		{
			const long dx = c.p.x * cnt - sx, dy = c.p.y * cnt - sy;
			const std::int64_t d = static_cast<std::int64_t>(dx * dx + dy * dy);
			if (!pick || d < pd)
			{
				pick = &c;
				pd = d;
			}
		}
	if (pick)
		pick->score = best - 1;
}

bool step_to_set(const bitboard& goals, int max_search, int ignore_group)
{
	AF_CHECK();
	const bool vfd = vfd_dash_only && !W.can_move(); // CB3 bit 8192 VFD: the dash alone, the walk is spent
	if (!W.can_move() && !vfd)
		return false;
	vec2 me = W.me.pos; // Moves with a collection dash.
	if (bbget(goals, me))
		return false;
	// Static boards and field, cleared here (nothing calls step_to_set from inside it).
	static bitboard pf_walls, pf_roots, pf_dest, pf_vis;
	static distance_field pf_f;
	bitboard& walls = pf_walls;
	{
		const bitboard& dw = dynamic_walls();
		bb3_or(dw, avoid_on ? avoid_bb : dw, walls); // One host call; a board copy costs ~10x. A guarded retreat paths around awake camps' reach.
	}
	bbset(walls, me, false);
	bitboard& roots = pf_roots; // goals & ~walls == goals ^ (goals & walls)
	bb3_and(goals, walls, pf_vis); // F4: 2 host calls for 6
	bb3_xor(goals, pf_vis, roots);
	std::int32_t px_z = 0; // The host's emptiness test here (roots is often empty: ~25 + 1 a chunk).
	if (cambc::detail::sdk_Bitboard_IsZero(roots.ptr(), &px_z) == 0 ? px_z != 0 : !bbany_simd_move(roots))
		return false;
	const long left = fuel();
	if (left < tune::STS_GREEDY_FUEL)
	{
		if (vfd) // CB3 bit 8192 VFD: no greedy walk, the walk is spent
			return false;
		return step_greedy_set(roots, ignore_group);
	}
	const int rad = std::max(2, skip_search_radius_for_fuel(left, max_search));
	StsFails& fails = skip_search_failure_memo();
	for (const auto& sf : fails.list)
		if (sf.me == me && sf.rad == rad && boards_equal(sf.r, roots) && boards_equal(sf.w, walls))
			return false;
	bitboard& dest = pf_dest;
	static vec2 pf_dest_p{ -1, -1 }; // F4: dest holds this one tile: unset it instead of a host clear
	if (pf_dest_p.x >= 0)
		bbset(dest, pf_dest_p, false);
	bbset(dest, me);
	pf_dest_p = me;
	bitboard& visited = pf_vis;
	visited.clear();
	distance_field& f = pf_f;
	PROF("sts_pre");
	f.compute_to(walls, roots, dest, visited, static_cast<std::uint16_t>(rad));
	PROF("sts_bfs");
	std::uint16_t cur = dfget(f, me);
	if (cur == UNREACH)
	{
		StsFail& sf = fails.list[static_cast<std::size_t>(fails.next)];
		fails.next ^= 1;
		sf.w = walls;
		sf.r = roots;
		sf.me = me;
		sf.rad = rad;
		return false;
	}
	// A collection walk dashes down the search field first (3+ tiles left), then steps from the landing.
	if (cd_mode > 0 && travel_dash(f, ignore_group))
	{
		me = W.me.pos;
		cur = dfget(f, me);
		if (bbget(goals, me) || cur == UNREACH || !W.can_move())
			return true;
	}
	if (vfd)
		return false; // CB3 bit 8192 VFD: no dash went, and no walk is left
	CandList cands;
	const FView fv = fview(f); // F4: one view each
	const BView bw = bview(walls);
	each_neighbour8(me, fv, bw,
		[&](vec2 n, vec2, std::uint16_t v) __attribute__((always_inline))
		{
			if (v == UNREACH || v >= cur)
				return;
			cands.push_back({ n, static_cast<int>(v) * tune::STEP_TILE + static_cast<int>(camp_threat(n, ignore_group)) });
		});
	if (cands.empty())
		return false;
	skip_search_break_tie(cands, roots);
	return move_best(cands);
}

bool step_to(vec2 target, int stop, int max_search, int ignore_group)
{
	if (!inb(target))
		return false;
	if (cheb(W.me.pos, target) <= stop)
		return false;
	bitboard goals;
	goals.draw_chebyshev(target, static_cast<float>(std::max(0, stop)));
	return step_to_set(goals, max_search, ignore_group);
}
} // namespace nova::mv
