// econ_opening_walk.cc: The opening: prestep and start walks.
#include "econ_internal.h"
namespace nova::econ {
namespace {
// ally slot s acts before me within our team (higher base priority first, then draft order).
static bool ally_acts_before_me(int s)
{
	const int me = my_slot();
	if (s < 0 || s >= P.n || me < 0 || me >= P.n || s >= 8 || me >= 8)
		return false;
	{
		const int ps = mv::tie_prio(s), pm = mv::tie_prio(me);
		return ps > pm || (ps == pm && s < me);
	}
	const int ps = P.prio[static_cast<std::size_t>(s)], pm = P.prio[static_cast<std::size_t>(me)];
	return ps > pm || (ps == pm && s < me);
}
// camp_out's reach test at tile p: an awake attacker (z, near me) reaches p, is not my target's, and no claimant mate (not
// channeling) stands nearer to it than p. A mate that claims this camp's group stands nearer than `d`, or ties and goes first: the
// camp is its to take.
__attribute__((always_inline)) inline bool camp_held(const mv::Threat& t, int cg, int d)
{
	bool held = false;
	for (const auto& al : W.allies)
		if (cg >= 0 && (claims(al.slot, cg) || claim_is_fresh(al.slot, cg)) && !al.channeling() && (cheb(al.pos, t.pos) < d || (cheb(al.pos, t.pos) == d && ally_acts_before_me(al.slot))))
			held = true;
	return held;
}
static bool pos_in_camp_reach(const std::vector<mv::Threat>& z, vec2 p)
{
	for (const auto& t : z)
	{
		const int d = cheb(t.pos, p);
		if (t.reach < 0 || d > t.reach)
			continue;
		const int ci = M.camp_index(t.pos);
		const int cg = ci >= 0 ? M.camps[static_cast<std::size_t>(ci)].group : -1;
		if (cg >= 0 && cg == T.target)
			continue;
		const bool held = camp_held(t, cg, d);
		if (!held && (ci >= 0 ? M.camps[static_cast<std::size_t>(ci)].str : 60.0f) > 0.0f)
			return true;
	}
	return false;
}
// the straight line from a to b crosses a wall or hole within PW_LEN tiles (Bresenham, 8-connected).
static bool line_crosses_wall_or_hole(vec2 a, vec2 b)
{
	int x = a.x, y = a.y;
	const int dx = iabs(b.x - a.x), dy = iabs(b.y - a.y), sx = a.x < b.x ? 1 : -1, sy = a.y < b.y ? 1 : -1;
	int err = dx - dy;
	for (int k = 0; k < PW_LEN && !(x == b.x && y == b.y); ++k)
	{
		const int e2 = 2 * err;
		if (e2 > -dy)
		{
			err -= dy;
			x += sx;
		}
		if (e2 < dx)
		{
			err += dx;
			y += sy;
		}
		const vec2 t{ x, y };
		if (!inb(t))
			return true;
		if (bbget(M.walls, t) || bbget(M.holes, t))
			return true;
	}
	return false;
}
static void opening_goal_list_add(std::array<int, 4>& L, std::array<float, 4>& V, int& n, int gi, float v)
{
	const int K = std::min(static_cast<int>(OFMASK_FAST_TAB[2]), 4);
	int at = n;
	while (at > 0 && V[static_cast<std::size_t>(at - 1)] < v)
		--at;
	if (at >= K)
		return;
	for (int k = std::min(n, K - 1); k > at; --k)
	{
		L[static_cast<std::size_t>(k)] = L[static_cast<std::size_t>(k - 1)];
		V[static_cast<std::size_t>(k)] = V[static_cast<std::size_t>(k - 1)];
	}
	L[static_cast<std::size_t>(at)] = gi;
	V[static_cast<std::size_t>(at)] = v;
	n = std::min(n + 1, K);
}
static void opening_goal_list_cut(const std::array<float, 4>& V, int& n)
{
	const float f = static_cast<float>(OFMASK_FAST_TAB[3]) / 100.0f;
	for (int k = 1; k < n; ++k)
		if (V[static_cast<std::size_t>(k)] < f * V[0])
		{
			n = k;
			return;
		}
}
static inline void opening_step_note(const vec2 from, const int r)
{
	opb_prev = from;
	opb_prev_r = r;
}
// EB4 PSG (bit 4): the top unheld groups kept when op_pre_g is chosen; a step may not raise the walk to any of them whose field is ready.
static std::array<int, 3> psg_top{ -1, -1, -1 };
static bool psg_step_refused(const vec2 me, const vec2 n)
{
	for (const int g : psg_top)
	{
		const distance_field* const f = g >= 0 ? mv::group_field_ready(g) : nullptr;
		if (f && dfget(*f, me) != UNREACH && dfget(*f, n) > dfget(*f, me))
			return true;
	}
	return false;
}
void opening_prestep()
{
	if (!W.alive || !W.can_move() || W.moved || W.me.channeling() || T.target >= 0 || fuel() < 30000 || M.groups.empty())
		return;
	bool psg_a = false; // EB4 PSG bit 4 applies to this step (never to my own running pass)
	int gi = -1;
	if (OP.sim && OP.i < TM.n && opening_sim_body_at(OP.i) == my_slot() && OP.best >= 0)
		gi = OP.best;
	else
	{
		psg_a = false;
		auto held = [](int g)
		{
			for (int s = 0; s < TM.n && s < 8; ++s)
				if (OP.done[static_cast<std::size_t>(s)] && OP.cl[static_cast<std::size_t>(s)] == g)
					return true;
			return false;
		};
		if (op_pre_g < 0 || held(op_pre_g))
		{
			std::vector<std::pair<float, int>> cand;
			group_bounds(my_slot(), nullptr, true, cand);
			op_pre_g = -1;
			for (const auto& c : cand)
				if (!held(c.second))
				{
					op_pre_g = c.second;
					break;
				}
			if (psg_a)
			{
				std::size_t psg_n = 0;
				psg_top.fill(-1);
				for (const auto& c : cand)
					if (psg_n < psg_top.size() && !held(c.second))
						psg_top[psg_n++] = c.second;
			}
		}
		gi = op_pre_g;
	}
	if (gi < 0 || gi >= M.ng)
		return;
	const auto& g = M.groups[static_cast<std::size_t>(gi)];
	if (g.access != ACC_WALK)
		return;
	const distance_field* f = mv::group_field_ready(gi);
	const vec2 me = W.me.pos;
	const int cur = f ? static_cast<int>(dfget(*f, me)) : (cheb(me, g.anchor));
	if (cur == UNREACH || (cur <= 1))
		return;
	const bool osc_blind = !f && M.has_home && dfget(M.f_home, me) != UNREACH;
	const std::uint16_t osc_h = osc_blind ? dfget(M.f_home, me) : 0;
	vec2 best{ -1, -1 };
	int bv = cur, bl = BIG;
	const bool opb2 = opb_prev_r == now() - 1, opb4 = false;
	const auto po_z = mv::camp_threats_near(7);
	for (const vec2 d : DIRS)
	{
		const vec2 n = me + d;
		if (!mv::free_tile(n) || mv::camp_threat(n) > 0)
			continue;
		if (osc_blind && dfget(M.f_home, n) < osc_h)
			continue; // a wall-blind step never walks back toward home
		if (!po_z.empty() && pos_in_camp_reach(po_z, n))
			continue; // camp_out would walk me back out next turn
		if (psg_a && psg_step_refused(me, n))
			continue; // EB4 PSG bit 4: never away from a group my simulation may pick
		const int v = f ? static_cast<int>(dfget(*f, n)) : (cheb(n, g.anchor));
		if (v == UNREACH || v < 0)
			continue;
		const int lin = iabs(n.x - g.anchor.x) + iabs(n.y - g.anchor.y);
		const bool ou = opb2 && n == opb_prev;
		if (ou && opb4)
			continue;
		if (ou ? v < bv : (v < bv || (v == bv && best.x >= 0 && (lin < bl || (opb2 && best == opb_prev)))))
		{
			bv = v;
			bl = lin;
			best = n;
		}
	}
	if (best.x >= 0 && bv < cur && mv::try_move(best))
	{
		opening_step_note(me, now());
		op_prestepped = true;
		(void)0;
		last_act = ACT_WALK;
	}
}
int sgm_ng = -1, sgm_best = -1; // X2I bit 64 SGM1: the no-distance answer (static inputs after the group build) and its group count
vec2 sgm_ha{ -1, -1 }, sgm_ea{ -1, -1 }; // X2I bit 64: the anchors it was computed from
int start_goal_i()
{
	if (start_g_fixed || M.groups.empty() || !M.groups_ready())
		return start_g;
	bool dist = false;
	for (const auto& g : M.groups)
		if (g.d_home != UNREACH)
		{
			dist = true;
			break;
		}
	if (!dist && sgm_ng == M.ng && sgm_ha == M.home_anchor && sgm_ea == M.enemy_anchor) // X2I bit 64 SGM1: the same answer as the last no-distance call
	{
		start_g = sgm_best;
		return sgm_best;
	}
	int best = -1;
	float bv = -1.0f;
	for (int pass = 0; pass < 2 && best < 0; ++pass)
		for (std::size_t gi = 0; gi < static_cast<std::size_t>(M.ng); ++gi)
		{
			const auto& g = M.groups[gi];
			if (g.gems + g.gold <= 0)
				continue;
			if (pass == 0 && g.n_mono > 0)
				continue; // the first target is found in 0.6% of bodies
			int d = 0;
			bool ours = false;
			if (dist)
			{
				if (g.access != ACC_WALK || g.d_home == UNREACH)
					continue;
				d = static_cast<int>(g.d_home);
				ours = g.contest <= 0.5f;
			}
			else
			{
				d = cheb(g.anchor, M.home_anchor);
				ours = d <= cheb(g.anchor, M.enemy_anchor);
			}
			if (!ours)
				continue;
			const float v = (static_cast<float>(g.gems) + 0.5f * static_cast<float>(g.gold)) / static_cast<float>(d + 10);
			if (v > bv)
			{
				bv = v;
				best = static_cast<int>(gi);
			}
		}
	if (!dist) // X2I bit 64 SGM1
	{
		sgm_ng = M.ng;
		sgm_best = best;
		sgm_ha = M.home_anchor;
		sgm_ea = M.enemy_anchor;
	}
	start_g = best;
	start_g_fixed = dist;
	return best;
}
// Draft: the same static value as start_goal_i over the groups on my side; groups with a monolith are skipped.
void write_draft_opening_values(std::vector<std::uint8_t>& mem)
{
	std::array<int, 4> L{ { -1, -1, -1, -1 } };
	std::array<float, 4> V{};
	int n = 0;
	for (std::size_t gi = 0; gi < static_cast<std::size_t>(M.ng); ++gi)
	{
		const auto& g = M.groups[gi];
		if (g.gems + g.gold <= 0 || g.access != ACC_WALK || g.d_home == UNREACH || g.d_home > g.d_enemy || g.n_mono > 0)
			continue;
		opening_goal_list_add(L, V, n, static_cast<int>(gi), (static_cast<float>(g.gems) + 0.5f * static_cast<float>(g.gold)) / (static_cast<float>(g.d_home) + 10.0f));
	}
	opening_goal_list_cut(V, n);
	if (n <= 0)
		return;
	if (mem.size() < 768)
		mem.resize(768, 0);
	mem[760] = 0xB7;
	for (int k = 0; k < 3; ++k)
	{
		const vec2 a = k < n ? M.groups[static_cast<std::size_t>(L[static_cast<std::size_t>(k)])].anchor : vec2{ 255, 255 };
		mem[static_cast<std::size_t>(761 + 2 * k)] = static_cast<std::uint8_t>(a.x);
		mem[static_cast<std::size_t>(762 + 2 * k)] = static_cast<std::uint8_t>(a.y);
	}
}
template <class Val, class Ok, class Held>
static vec2 sidestep_tile(const vec2 me, const int cur, const Val& val, const Ok& ok, const Held& held)
{
	const int r = static_cast<int>(round_number_nc());
	bool any = false;
#pragma clang loop unroll(full) // unroll fully
	for (const vec2 d : DIRS)
	{
		const vec2 n = me + d;
		if (!inb(n) || !held(n))
			continue;
		const int v = val(n);
		if (v >= 0 && v < cur)
		{
			any = true;
			break;
		}
	}
	if (!any)
		return vec2{ -1, -1 };
	vec2 best{ -1, -1 };
	int bk = 0;
#pragma clang loop unroll(full) // unroll fully
	for (const vec2 d : DIRS)
	{
		const vec2 n = me + d;
		if (!inb(n) || (n == spw_prev && spw_prev_r >= r - 2) || !ok(n) || val(n) != cur)
			continue;
		int k = 0;
		for (const vec2 e : DIRS)
		{
			const vec2 q = n + e;
			if (q == me || !inb(q) || !ok(q))
				continue;
			const int vq = val(q);
			if (vq >= 0 && vq < cur)
				++k;
		}
		if (k > bk)
		{
			bk = k;
			best = n;
		}
	}
	return best;
}
static bool blind_field_step(const vec2 me, const std::array<vec2, 3>& A, const int na)
{
	static std::array<std::unique_ptr<distance_field>, 3> F;
	static std::array<vec2, 3> FA{ { vec2{ -1, -1 }, vec2{ -1, -1 }, vec2{ -1, -1 } } };
	// Measured on a 50x40 map in a release build: about 5k a field with its allocation and fill, 1-2k for the step after; 2 a tile cut
	// turns on 91x91 and 98x98 boards, so 4 a tile. Never cut the turn (a cut turn resumes next round): each field needs its cost + 5k
	// left. The lead goal's field is required; another goal's field is built if it fits, else that goal keeps the Chebyshev veto of the
	// base step.
	const long fcost = 4L * M.w * M.h + 3000L;
	std::array<bool, 3> have{ { false, false, false } };
	for (int k = 0; k < na; ++k)
	{
		const std::size_t s = static_cast<std::size_t>(k);
		if (F[s] && FA[s] == A[s])
		{
			have[s] = true;
			continue;
		}
		if (fuel() < (fcost + static_cast<long>(distance_field::raw_buffer_size()) + 2L * static_cast<long>(bitboard::raw_buffer_size()) + 2000L) + 5000L || !inb(A[s])) // priced like the path-field cost
		{
			if (k == 0)
				return false;
			continue;
		}
		bitboard t;
		bbset(t, A[s]);
		auto f = std::make_unique<distance_field>();
		bitboard visited;
		f->compute(M.block, t, visited); // static walls only: a goal anchor sits among its own camps (the step itself skips camp tiles)
		F[s] = std::move(f);
		FA[s] = A[s];
		have[s] = true;
	}
	const auto& self = cambc::self();
	const int d0 = static_cast<int>(dfget(*F[0], me));
	if (d0 == UNREACH || d0 <= 1)
		return false;
	bitboard units = cambc::vision::champion_tiles();
	for (int rfm = 0;; ++rfm) // one more pass after a refused step
	{
		vec2 best{ -1, -1 };
		int bv = d0, bs = BIG;
#pragma clang loop unroll(full) // unroll fully
		for (const vec2 d : DIRS)
		{
			const vec2 n = me + d;
			if (!inb(n) || bbget(M.block, n) || bbget(M.camp_tiles, n) || bbget(units, n))
				continue;
			const int v = static_cast<int>(dfget(*F[0], n));
			if (v == UNREACH || v >= d0)
				continue;
			bool veto = false;
			int sum = 0;
			for (int k = 1; k < na && !veto; ++k)
			{
				const std::size_t s = static_cast<std::size_t>(k);
				const int a = have[s] ? static_cast<int>(dfget(*F[s], me)) : cheb(me, A[s]), b = have[s] ? static_cast<int>(dfget(*F[s], n)) : cheb(n, A[s]);
				if (a == UNREACH)
					continue;
				veto = b == UNREACH || b > a;
				sum += b;
			}
			if (veto)
				continue;
			if (v < bv || (v == bv && sum < bs))
			{
				bv = v;
				bs = sum;
				best = n;
			}
		}
		if (best.x < 0)
			return false;
		cancel_spin_before_action();
		if (self.move_absolute(best))
			break;
		if (rfm > 0)
			return false;
		bbset(units, best); // refused (unseen unit); the move is kept
	}
	op_prestepped = true;
	(void)0;
	return true;
}
// Raw SDK only, W not perceived. Walks to Chebyshev 1 of the lead goal; camps known so far block.
bool opening_blind_step_i()
{
	if (static_cast<int>(round_number_nc()) > 6 || fuel() < 8000)
		return false;
	try
	{
		const auto mem = dmem::view();
		if (mem.size() < 768 || std::to_integer<std::uint8_t>(mem[760]) != 0xB7)
			return false;
		const auto& self = cambc::self();
		const auto st = self.state();
		if (!st.contains(cambc::champion_state::alive) || !st.contains(cambc::champion_state::can_move))
			return false;
		const vec2 me = self.position();
		std::array<vec2, 3> A{};
		int na = 0;
		for (int k = 0; k < 3; ++k)
		{
			const int x = std::to_integer<std::uint8_t>(mem[static_cast<std::size_t>(761 + 2 * k)]), y = std::to_integer<std::uint8_t>(mem[static_cast<std::size_t>(762 + 2 * k)]);
			if (x < 255)
				A[static_cast<std::size_t>(na++)] = vec2{ x, y };
		}
		if (na <= 0 || cheb(me, A[0]) <= (1))
			return false;
		if (line_crosses_wall_or_hole(me, A[0]))
			return static_cast<bool>(blind_field_step(me, A, na)); // only where the Chebyshev step refuses
		bitboard units = cambc::vision::champion_tiles();
		bool spw_s = false;
		for (int rfm = 0;; ++rfm) // one more pass after a refused step
		{
		vec2 best{ -1, -1 };
		int bv = cheb(me, A[0]), bl = BIG;
#pragma clang loop unroll(full) // unroll fully
		for (const vec2 d : DIRS)
		{
			const vec2 n = me + d;
			if (!inb(n) || bbget(M.block, n) || bbget(M.camp_tiles, n) || bbget(units, n))
				continue;
			bool veto = false;
			for (int k = 1; k < na && !veto; ++k)
				veto = cheb(n, A[static_cast<std::size_t>(k)]) > cheb(me, A[static_cast<std::size_t>(k)]);
			if (veto)
				continue;
			const int v = cheb(n, A[0]);
			const int lin = iabs(n.x - A[0].x) + iabs(n.y - A[0].y);
			if (v < bv || (v == bv && best.x >= 0 && lin < bl))
			{
				bv = v;
				bl = lin;
				best = n;
			}
		}
		if (best.x < 0 || bv >= cheb(me, A[0]))
		{
			if (rfm == 0 && blind_field_step(me, A, na)) // no Chebyshev step
				return true;
			if (!(rfm == 0))
				return false;
			const vec2 a0 = A[0];
			best = sidestep_tile(
				me, cheb(me, a0), [&](const vec2 n) { return cheb(n, a0); },
				[&](const vec2 n) {
					if (!inb(n) || bbget(M.block, n) || bbget(M.camp_tiles, n) || bbget(units, n))
						return false;
					for (int k = 1; k < na; ++k)
						if (cheb(n, A[static_cast<std::size_t>(k)]) > cheb(me, A[static_cast<std::size_t>(k)]))
							return false;
					return true;
				},
				[&](const vec2 n) { return bbget(units, n) && !bbget(M.block, n); });
			if (best.x < 0)
				return false;
			spw_s = true;
		}
		cancel_spin_before_action();
		if (self.move_absolute(best))
			break;
		if (rfm > 0)
			return false;
		bbset(units, best); // refused (unseen unit); the move is kept
		}
		if (spw_s)
		{
			spw_prev = me;
			spw_prev_r = static_cast<int>(round_number_nc());
		}
		op_prestepped = true;
		(void)0;
		return true;
	}
	catch (...)
	{
		FXR_PASS();
	}
	return false;
}
// A turn that ends before the turn logic (the map analysis spreads over the first turns; setup waits for fuel) takes one greedy step
// toward the start goal instead of standing on the spawn. W is not perceived in such a turn: raw SDK calls only (my position and
// state, the visible champions' tiles), the static block mask with every camp tile, and the camps' reach (never within reach + 1 of
// an attacking camp). Stops at distance 1 of the goal's anchor. A body off the spawn keeps the opening simulation (op_prestepped):
// the simulation uses spawn distances only.
// v724 DFG bit 2: in a pre-turn step with a draft record, hit a camp of my record's group in reach, else travel-dash toward it (raw SDK,
// as the step). Combat's guard: never C&I or Prism (their dash is their escape); the landing is no nearer the foe spawn than my spawn
// tile and lies in our half or by the goal group, never in reach + 1 of another group's attacking camp; the opening's 40k reserve.
bool dfg_early_act(int gi, vec2 me, const cambc::champion_state& st)
{
	static vec2 dfg_sp{ -1, -1 }; // my spawn tile (first seen on a spawn tile), else the spawn anchor
	if (dfg_sp.x < 0)
		dfg_sp = bbget(M.my_spawn, me) ? me : M.home_anchor;
	if (fuel() < OPENING_RESERVE + 20000)
		return false;
	int n = 0;
	if (dfg::my_slot_raw(n) < 0)
		return false;
	const Kit& kit = kit_of(dfg::my_t);
	const auto& g = M.groups[static_cast<std::size_t>(gi)];
	if (st.contains(cambc::champion_state::can_attack))
		for (int ci : g.members)
		{
			const auto& c = M.camps[static_cast<std::size_t>(ci)];
			if (cheb(c.pos, me) > std::max(1, kit.range))
				continue;
			cancel_spin_before_action();
			if (cambc::detail::sdk_attack(2u, c.handle) == 0) // 2 = KIND_CAMP
				return true;
		}
	using CT = cambc::champion_type;
	if (kit.slot_dash < 0 || dfg::my_t == CT::cassi || dfg::my_t == CT::issac || dfg::my_t == CT::prism || !st.contains(cambc::champion_state::can_cast))
		return false;
	std::int32_t cd = 1;
	if (cambc::detail::sdk_champion_cooldown(static_cast<std::uint32_t>(cambc::detail::sdk_my_champion()), static_cast<std::uint32_t>(kit.slot_dash), &cd) != 0 || cd > 0)
		return false;
	const distance_field* pf = mv::group_field_ready(gi); // RC C96 DFD1: the goal's walk field once built (as the step), else Chebyshev
	if (pf && dfget(*pf, me) == UNREACH)
		pf = nullptr;
	const auto dist = [&](const vec2 p) { return pf ? static_cast<int>(dfget(*pf, p)) : cheb(p, g.anchor); };
	const int cur = dist(me);
	const int sp_e = cheb(dfg_sp, M.enemy_anchor);
	const bitboard units = cambc::vision::champion_tiles();
	vec2 best{ -1, -1 };
	int bv = BIG, bl = BIG;
	for (const vec2 d : DIRS)
	{
		const vec2 mid = me + d, u = mid + d;
		if (!inb(u) || !inb(mid) || bbget(M.block_camps, mid) || bbget(M.block_camps, u) || bbget(units, u) || bbget(units, mid))
			continue;
		const int v = dist(u);
		if (v == static_cast<int>(UNREACH) || v < 1 || v > cur - 2)
			continue; // a dash gains two steps on the goal
		if (cheb(u, M.enemy_anchor) < sp_e)
			continue; // no nearer the foe spawn than my spawn tile
		if (cheb(u, M.home_anchor) > cheb(u, M.enemy_anchor) && cheb(u, g.anchor) > g.reach_max + 2)
			continue; // our half, or by the goal group
		bool bad = false;
		for (std::size_t ci = 0; ci < static_cast<std::size_t>(M.nc) && !bad; ++ci)
		{
			const auto& c = M.camps[ci];
			bad = c.group != gi && c.attacks() && cheb(c.pos, u) <= c.reach + 1;
		}
		if (bad)
			continue;
		const int lin = iabs(u.x - g.anchor.x) + iabs(u.y - g.anchor.y);
		if (v < bv || (v == bv && lin < bl))
		{
			bv = v;
			bl = lin;
			best = u;
		}
	}
	if (best.x < 0)
		return false;
	std::int32_t ok = 0;
	cancel_spin_before_action();
	return cambc::detail::sdk_cast(static_cast<std::uint32_t>(kit.slot_dash), 0u, 0u, best.x, best.y, &ok) == 0 && ok != 0;
}
bool start_prestep_i()
{
	if (!M.groups_ready())
		return opening_blind_step_i();
	if (!M.groups_ready() || M.groups.empty() || fuel() < 12000)
		return false;
	if (static_cast<int>(round_number_nc()) > START_ROUNDS)
		return false;
	int dfg_g = -1;
	const int gi = ((dfg_g = dfg_goal()) >= 0) ? dfg_g : start_goal_i(); // v724 DFG bit 1: the draft record's group
	if (gi < 0 || gi >= M.ng)
		return false;
	const auto& g = M.groups[static_cast<std::size_t>(gi)];
	try
	{
		const auto& self = cambc::self();
		const auto st = self.state();
		if (dfg_g >= 0 && st.contains(cambc::champion_state::alive) && dfg_early_act(gi, self.position(), st)) // v724 DFG bit 2
			return true;
		if (!st.contains(cambc::champion_state::alive) || !st.contains(cambc::champion_state::can_move))
			return false;
		const vec2 me = self.position();
		const distance_field* pf = nullptr; // the goal's walk field once it is built and reaches me, else Chebyshev
		pf = mv::group_field_ready(gi);
		if (pf && dfget(*pf, me) == UNREACH)
			pf = nullptr;
		if (!pf)
		{
			pf = mv::group_field_build(gi, PF_RESERVE); // leftover fuel of this turn (never banked)
			if (pf && dfget(*pf, me) == UNREACH)
				pf = nullptr;
		}
		if ((pf ? static_cast<int>(dfget(*pf, me)) <= 1 : cheb(me, g.anchor) <= 1))
			return false;
		const int cur = pf ? static_cast<int>(dfget(*pf, me)) : (cheb(me, g.anchor));
		bitboard units = cambc::vision::champion_tiles();
		// Attacking camps whose reach + 1 could cover a neighbour of mine (one pass over the camps).
		int near_n = 0;
		std::array<int, 16> near_c{};
		for (std::size_t ci = 0; ci < static_cast<std::size_t>(M.nc) && near_n < 16; ++ci)
		{
			const auto& c = M.camps[ci];
			if (c.attacks() && cheb(c.pos, me) <= c.reach + 2)
				near_c[static_cast<std::size_t>(near_n++)] = static_cast<int>(ci);
		}
		bool spw_s = false;
		for (int rfm = 0;; ++rfm) // one more pass after a refused step
		{
		vec2 best{ -1, -1 };
		int bv = cur, bl = BIG;
#pragma clang loop unroll(full) // unroll fully
		for (const vec2 d : DIRS)
		{
			const vec2 n = me + d;
			if (!inb(n) || bbget(M.block_camps, n) || bbget(units, n))
				continue;
			bool hit = false;
			for (int k = 0; k < near_n && !hit; ++k)
			{
				const auto& c = M.camps[static_cast<std::size_t>(near_c[static_cast<std::size_t>(k)])];
				hit = cheb(c.pos, n) <= c.reach + 1;
			}
			const int v = pf ? static_cast<int>(dfget(*pf, n)) : (cheb(n, g.anchor));
			if (v == UNREACH || v < 0)
				continue;
			const int lin = iabs(n.x - g.anchor.x) + iabs(n.y - g.anchor.y);
			if (v < bv || (v == bv && best.x >= 0 && lin < bl))
			{
				bv = v;
				bl = lin;
				best = n;
			}
		}
		if (best.x < 0 || bv >= cur)
		{
			if (!(rfm == 0))
				return false;
			const auto vf = [&](const vec2 n) {
				const int v = pf ? static_cast<int>(dfget(*pf, n)) : (cheb(n, g.anchor));
				return v == UNREACH ? -1 : v;
			};
			best = sidestep_tile(
				me, cur, vf,
				[&](const vec2 n) {
					if (!inb(n) || bbget(M.block_camps, n) || bbget(units, n))
						return false;
					return true;
				},
				[&](const vec2 n) { return bbget(units, n) && !bbget(M.block_camps, n); });
			if (best.x < 0)
				return false;
			spw_s = true;
		}
		cancel_spin_before_action();
		if (self.move_absolute(best))
			break;
		if (rfm > 0)
			return false;
		bbset(units, best); // refused (unseen unit); the move is kept
		}
		if (spw_s)
		{
			spw_prev = me;
			spw_prev_r = static_cast<int>(round_number_nc());
		}
		opening_step_note(me, static_cast<int>(round_number_nc()));
		op_prestepped = true; // the opening simulation still runs for me off the spawn
		(void)0;
		return true;
	}
	catch (...)
	{
		FXR_PASS();
	}
	return false;
}
// In rounds 1..START_ROUNDS, a turn that reached the farm step and did nothing near our spawn (the opening simulation pending, a
// fuel skip, a target chosen this turn whose field is not built yet, no target) ends with one cheap step: toward my target, else the
// group the opening simulation gives me so far, else the start goal. Downhill on the group's field when it is built, else Chebyshev;
// never onto an awake camp's reach; stops at distance 1 with no target, else outside the target group's reach + 2. A crew wait
// (ACT_WAIT), camp work and captures are kept (crews still leave and arrive together).
bool start_step_i()
{
	if (now() > START_ROUNDS || !W.alive || !W.can_move() || W.moved || W.attacked || W.cast || W.me.channeling() || T.capturing || T.engaged || M.groups.empty() || fuel() < 15000)
		return false;
	if (last_act == ACT_WAIT || last_act == ACT_CAMP || last_act == ACT_CAPTURE || last_act == ACT_FOLLOW)
		return false;
	if (W.me.frac() < 0.9f)
		return false;
	for (const auto& e : W.enemies)
		if (cheb(e.pos, W.me.pos) <= 8)
			return false;
	const bool fuel_skip = T.target >= 0 && last_act == ACT_NONE;
	if (!fuel_skip && home_dist() > START_NEAR)
		return false;
	int gi = T.target;
	if (gi < 0 && !opened) // v724 DFG bit 1: the draft record's group before the simulation's
		gi = dfg_goal();
	if (gi < 0 && !opened && OP.sim && OP.i < TM.n && opening_sim_body_at(OP.i) == my_slot() && OP.best >= 0)
		gi = OP.best;
	if (gi < 0 && !opened && op_pre_g >= 0)
		gi = op_pre_g;
	if (gi < 0)
		gi = start_goal_i();
	if (gi < 0 || gi >= M.ng)
		return false;
	const auto& g = M.groups[static_cast<std::size_t>(gi)];
	if (g.access != ACC_WALK)
		return false;
	const distance_field* f = mv::group_field_ready(gi);
	const vec2 me = W.me.pos;
	if (!f)
	{
		f = mv::group_field_build(gi, PF_RESERVE); // the walk field now, not a wall-blind Chebyshev step
		if (f && dfget(*f, me) == UNREACH)
			f = nullptr;
	}
	const int cur = f ? static_cast<int>(dfget(*f, me)) : (cheb(me, g.anchor));
	if (cur == UNREACH || ((T.target < 0) ? cur <= 1 : cur <= (g.reach_max > 0 ? g.reach_max : 1) + 2))
		return false;
	if (f && hole_shortcut_turn(gi, *f)) // the hole shortcut on opening steps too
	{
		if (!opened)
			op_prestepped = true;
		(void)0;
		return true;
	}
	const bool osc_blind = !f && M.has_home && dfget(M.f_home, me) != UNREACH;
	const std::uint16_t osc_h = osc_blind ? dfget(M.f_home, me) : 0;
	vec2 best{ -1, -1 };
	int bv = cur, bl = BIG;
	const bool opb2 = T.target < 0 && opb_prev_r == now() - 1, opb4 = false;
	const auto po_z = mv::camp_threats_near(7);
	for (const vec2 d : DIRS)
	{
		const vec2 n = me + d;
		if (!mv::free_tile(n) || mv::camp_threat(n) > 0)
			continue;
		if (osc_blind && dfget(M.f_home, n) < osc_h)
			continue; // a wall-blind step never walks back toward home
		if (!po_z.empty() && pos_in_camp_reach(po_z, n))
			continue; // camp_out would walk me back out next turn
		const int v = f ? static_cast<int>(dfget(*f, n)) : (cheb(n, g.anchor));
		if (v == UNREACH || v < 0)
			continue;
		const int lin = iabs(n.x - g.anchor.x) + iabs(n.y - g.anchor.y);
		const bool ou = opb2 && n == opb_prev;
		if (ou && opb4)
			continue;
		if (ou ? v < bv : (v < bv || (v == bv && best.x >= 0 && (lin < bl || (opb2 && best == opb_prev)))))
		{
			bv = v;
			bl = lin;
			best = n;
		}
	}
	bool spw_s = false;
	if ((best.x < 0 || bv >= cur))
	{
		const auto vf = [&](const vec2 n) {
			const int v = f ? static_cast<int>(dfget(*f, n)) : (cheb(n, g.anchor));
			return v == UNREACH ? -1 : v;
		};
		best = sidestep_tile(
			me, cur, vf,
			[&](const vec2 n) {
				if (!mv::free_tile(n) || mv::camp_threat(n) > 0)
					return false;
				if (osc_blind && dfget(M.f_home, n) < osc_h)
					return false;
				if (!po_z.empty() && pos_in_camp_reach(po_z, n))
					return false;
				return true;
			},
			[&](const vec2 n) {
				for (const auto& a : W.allies)
					if (a.pos == n)
						return true;
				return false;
			});
		spw_s = best.x >= 0;
	}
	if (best.x < 0 || (bv >= cur && !spw_s) || !mv::try_move(best))
		return false;
	if (spw_s)
	{
		spw_prev = me;
		spw_prev_r = now();
	}
	opening_step_note(me, now());
	if (!opened)
		op_prestepped = true; // the opening simulation still runs for me off the spawn
	last_act = ACT_WALK;
	(void)0;
	return true;
}
} // namespace
} // namespace nova::econ
