// econ_shortcuts.cc: Dash shortcut fields across holes.
#include "econ_internal.h"
namespace nova::econ {
namespace {
// Per top group, a field to the launch tiles of the straight dashes over one thin hole that save HS3_SAVE+ steps (the band of the
// lowest landing walk), and the walk left after the dash (the band's worst landing + the dash turn). Terrain, holes and camp tiles
// are static: built once, in background fuel only (hole_shortcut_background), never inside the turn.
struct Hs3
{
	signed char st = 0; // 0 not built, 1 no shortcut, 2 ready, 3 given up
	int v = 0;
	std::unique_ptr<distance_field> f;
	int v2 = 0; // the field to the launches best from my spawn, and its walk after the dash
	std::unique_ptr<distance_field> f2;
};
std::vector<Hs3> hs3;
std::array<int, HS3_TOP> hs3_top{};
int hs3_ntop = -1; // -1: the ranking is not made yet
long hs3_worst = 0; // the costliest field build measured (fuel)
int hs3_sc_g = -1, hs3_sc_pos = 0; // the chunked launch-tile scan in progress: the hole-board word, its unread bits
std::uint64_t hs3_sc_bits = 0;
bool hs3_sc_started = false, hs3_sc_done = false;
std::vector<Hs3Cand> hs3_cs;
int hs3_wait_g = -1, hs3_wait_n = 0, hs3_wait_r = -10;
constexpr int HSB_MAX = 6;
constexpr int HSB_GRP_MIN = 20; // a group outside the top 3 gets a field only when its walk is at least this long
int hsb_alt() { return M.ng; }
bool ht_choice() { return false; } // path_dist counts every built shortcut
// decide the trigger (true once decided): a dash a -> b over a thin hole whose two ends differ by more than a set gain on the walk
// field from my spawn. Background fuel only; the fuel is read before every hole.
bool hole_travel_decide(long reserve)
{
	if (ht_state != -1)
		return true;
	ht_state = -2; // flag 0 (read once): never on, nothing else runs
	return true;
}
// a hole on the straight line from p to q (the cheap test that a shortcut may exist).
bool hole_on_line(vec2 p, vec2 q)
{
	const int n = cheb(p, q);
	for (int i = 1; i < n; ++i)
	{
		const vec2 t{ p.x + ((q.x - p.x) * i * 2 + (q.x >= p.x ? n : -n)) / (2 * n), p.y + ((q.y - p.y) * i * 2 + (q.y >= p.y ? n : -n)) / (2 * n) };
		if (inb(t) && bbget(M.holes, t))
			return true;
	}
	return false;
}
// the walk wd from me to goal is long and detours (>= HS3_SAVE - HS3_DETOUR over the straight line) round a hole on it.
bool bank_shortcut_trigger(int wd, vec2 goal)
{
	if (!dn::dasher() || !M.has_thin || wd == UNREACH || wd < HOLE_SHORT_MIN)
		return false;
	const vec2 me = W.me.pos;
	return wd + HS3_DETOUR >= cheb(me, goal) + HS3_SAVE && hole_on_line(me, goal); // and a hole on the straight line
}
// The HS3_TOP walkable groups with the most gems (static map data, once).
bool hole_shortcut_top_ready()
{
	if (hs3_ntop >= 0)
		return hs3_ntop > 0;
	if (!M.ready() || M.groups.empty())
		return false;
	hs3_ntop = 0;
	hs3.clear();
	hs3.resize(static_cast<std::size_t>(M.ng) + 1); // plus the altar slot (hsb_alt)
	for (int k = 0; k < HS3_TOP; ++k)
	{
		int best = -1, bg = 0;
		for (int gi = 0; gi < M.ng; ++gi)
		{
			const auto& g = M.groups[static_cast<std::size_t>(gi)];
			bool used = false;
			for (int j = 0; j < hs3_ntop; ++j)
				used |= hs3_top[static_cast<std::size_t>(j)] == gi;
			if (!used && g.access == ACC_WALK && g.gems > bg)
			{
				bg = g.gems;
				best = gi;
			}
		}
		if (best < 0)
			break;
		hs3_top[static_cast<std::size_t>(hs3_ntop++)] = best;
	}
	return hs3_ntop > 0;
}
// The shortcut field of group gi when it is built (nullptr otherwise); *v_out = the walk left after the dash.
const distance_field* hole_shortcut_field(int gi, int* v_out)
{
	if (hs3_ntop <= 0 || gi < 0 || gi >= static_cast<int>(hs3.size()))
		return nullptr;
	const Hs3& h = hs3[static_cast<std::size_t>(gi)];
	if (h.st != 2 || !h.f)
		return nullptr;
	*v_out = h.v;
	return h.f.get();
}
// gi is one of the HS3_TOP groups.
bool hole_shortcut_is_top(int gi)
{
	for (int t = 0; t < hs3_ntop; ++t)
		if (hs3_top[static_cast<std::size_t>(t)] == gi)
			return true;
	return false;
}
// the hs3 shortcut decision for group gi (gi < 0: any top group) is still pending on a thin-hole map.
bool hole_shortcut_pending(int gi)
{
	if (!dn::dasher())
		return false;
	if (!M.done())
		return true;
	if (!M.has_thin)
		return false;
	if (hs3_ntop < 0)
		return true;
	if (hs3_ntop == 0 || hs3.size() != static_cast<std::size_t>(M.ng) + 1)
		return false;
	if (gi >= 0)
		return gi < M.ng && hole_shortcut_is_top(gi) && hs3[static_cast<std::size_t>(gi)].st == 0;
	for (int t = 0; t < hs3_ntop; ++t)
		if (hs3[static_cast<std::size_t>(hs3_top[static_cast<std::size_t>(t)])].st == 0)
			return true;
	return false;
}
// The shortcut route length from p to group gi (walk to the launch + the walk left after the dash), UNREACH if none.
int hole_shortcut_len(int gi, vec2 p)
{
	int v = 0;
	const distance_field* H = hole_shortcut_field(gi, &v);
	if (!H || !inb(p))
		return UNREACH;
	const int hd = dfget(*H, p);
	int r = hd == UNREACH ? UNREACH : hd + v;
	return r;
}
// Background step: the next top group's scan and field, within this turn's spare fuel (calibrated bar).
void hole_shortcut_background(long reserve)
{
	if (!dn::dasher() || !M.has_thin || !M.done() || !hole_shortcut_top_ready() || hs3.size() != static_cast<std::size_t>(M.ng) + 1)
		return;
	const int alt = hsb_alt();
	if (ht_state == -1 && !hole_travel_decide(reserve))
		return; // the trigger scan ran out of this turn's spare fuel (or the home field is not built yet)
	int gi = hs3_sc_g;
	if (gi < 0)
	{
		// a bank walk that asked for the altar's shortcut this round or the last one (only set with the slot on)
		if (now() - hsb_req_r <= 1 && M.any_altar && hs3[static_cast<std::size_t>(alt)].st == 0 && (rsw(RSW_HS_BANK) & 1))
			gi = alt;
		// my target first when it is a top group, then the ranking; a group's walk field must be built
		for (int j = -1; j < hs3_ntop && gi < 0; ++j)
		{
			const int c = j < 0 ? T.target : hs3_top[static_cast<std::size_t>(j)];
			bool top = j >= 0; // hs3_top[j] is in the list (the scan below found it there); only my target is searched
			if (!top)
				for (int t = 0; t < hs3_ntop; ++t)
					top |= hs3_top[static_cast<std::size_t>(t)] == c;
			if (top && c >= 0 && c < alt && hs3[static_cast<std::size_t>(c)].st == 0 &&
				mv::group_field_raw(c) != nullptr)
				gi = c;
			else if (j < 0 && !top && c >= 0 && c < alt && hs3[static_cast<std::size_t>(c)].st == 0 && hsb_n < (HSB_MAX) &&
				M.groups[static_cast<std::size_t>(c)].access == ACC_WALK)
			{
				// my target outside the top groups, when a hole lies between me and it and the walk detours
				const distance_field* tf = mv::group_field_raw(c);
				const int twd = tf ? static_cast<int>(dfget_me(*tf)) : UNREACH;
				if (tf && twd != UNREACH && twd >= HSB_GRP_MIN && bank_shortcut_trigger(twd, M.groups[static_cast<std::size_t>(c)].anchor) && (rsw(RSW_HS_BANK) & 2))
					gi = c;
			}
		}
		if (gi < 0)
			return;
		hs3_sc_g = gi;
		hs3_sc_pos = 0;
		hs3_sc_bits = 0;
		hs3_sc_started = false;
		hs3_sc_done = false;
		hs3_cs.clear();
		int vm = 0, nr = 0;
		const std::uint16_t* rt = nullptr;
		if (dmem::launch_record(gi, vm, rt, nr)) // the draft's scan of this slot: its roots and best landing walk, no scan here
		{
			if (nr == 0)
			{
				hs3[static_cast<std::size_t>(gi)].st = 1;
				hs3_sc_g = -1;
				return;
			}
			for (int k = 0; k < nr; ++k)
				hs3_cs.push_back({ vec2{ rt[k] % G.w, rt[k] / G.w }, vm });
			hs3_sc_done = true;
		}
	}
	const distance_field* F = gi == alt ? &M.f_altar : mv::group_field_raw(gi); // the altar slot walks M.f_altar
	if (!F)
		return;
	Hs3& h = hs3[static_cast<std::size_t>(gi)];
	if (!hs3_sc_done)
	{
		// The scan: dashes a -> b with the thin hole hl as the middle (both orientations), resumed across turns.
		const FView fv = fview(*F);
		// the move pairs (u, w) of a dash a = hl - u -> b = hl + w: the 4 straight lines, then the 8 knight bends (orthogonal then
		// diagonal; the reverse orientation covers diagonal then orthogonal)
		static const vec2 PU[12] = { { 1, 0 }, { 0, 1 }, { 1, 1 }, { 1, -1 }, { 1, 0 }, { 1, 0 }, { -1, 0 }, { -1, 0 }, { 0, 1 }, { 0, 1 },
			{ 0, -1 }, { 0, -1 } };
		static const vec2 PW[12] = { { 1, 0 }, { 0, 1 }, { 1, 1 }, { 1, -1 }, { 1, 1 }, { 1, -1 }, { -1, 1 }, { -1, -1 }, { 1, 1 }, { -1, 1 },
			{ 1, -1 }, { -1, -1 } };
		// Resumed at (word, remaining bits) of the hole board: no re-walk of the holes already read. Fuel is read before every hole
		// (a hole costs well under the 3000 margin), so the step ends at or above the reserve.
		if (!NOVA_GDIRECT)
		{
			h.st = 1; // the raw board is not readable: no shortcut
			hs3_sc_g = -1;
			return;
		}
		const long bar = reserve + 3000;
		const std::uint64_t* hw = M.thin_holes.ptr();
		const int nw = G.ch * G.cw;
		while (hs3_sc_pos < nw)
		{
			const int cy = hs3_sc_pos / G.cw, cx = hs3_sc_pos % G.cw;
			if (!hs3_sc_started)
			{
				hs3_sc_bits = hw[cy * G.stride + cx];
				hs3_sc_started = true;
			}
			while (hs3_sc_bits)
			{
				if (fuel() < bar)
					return;
				const int bit = __builtin_ctzll(hs3_sc_bits);
				hs3_sc_bits &= hs3_sc_bits - 1;
				const vec2 hl{ cx * 8 + (bit & 7), cy * 8 + (bit >> 3) };
				if (hl.x >= G.w || hl.y >= G.h)
					continue;
				for (int q = 0; q < 12; ++q)
				{
					const vec2 a{ hl.x - PU[q].x, hl.y - PU[q].y }, b{ hl.x + PW[q].x, hl.y + PW[q].y };
					if (!inb(a) || !inb(b))
						continue;
					const int fa = fv(a), fb = fv(b);
					if (fa == UNREACH || fb == UNREACH)
						continue;
					if (fb + 1 + HS3_SAVE <= fa && !bbget(M.block_camps, a) && !bbget(M.block_camps, b) && hs3_cs.size() < 512)
						hs3_cs.push_back({ a, fb + 1 });
					else if (fa + 1 + HS3_SAVE <= fb && !bbget(M.block_camps, a) && !bbget(M.block_camps, b) && hs3_cs.size() < 512)
						hs3_cs.push_back({ b, fa + 1 });
				}
			}
			++hs3_sc_pos;
			hs3_sc_started = false;
		}
		hs3_sc_done = true;
		if (hs3_cs.empty())
		{
			h.st = 1;
			hs3_sc_g = -1;
			return;
		}
	}
	// The field: one host distance field at the field_cost bar (3 per tile + 3000, the bar build_fields uses) plus the new field's zero
	// fill and two boards, or 1.25 x the costliest measured build.
	const long prior = 3L * M.w * M.h + 3000 + static_cast<long>(distance_field::raw_buffer_size()) +
		2L * static_cast<long>(bitboard::raw_buffer_size()) + 2000L;
	if (fuel() < reserve + std::max(prior, hs3_worst + hs3_worst / 4))
		return;
	const long f0 = fuel();
	const int r0 = static_cast<int>(round_number_nc());
	int vmin = UNREACH;
	for (const auto& c : hs3_cs)
		vmin = std::min(vmin, c.v);
	bitboard roots{};
	for (const auto& c : hs3_cs)
		if (c.v <= vmin + HS3_BAND)
			bbset(roots, c.a);
	auto f = std::make_unique<distance_field>();
	bitboard visited;
	f->compute(M.block_camps, roots, visited);
	h.f = std::move(f);
	h.v = vmin + HS3_BAND;
	h.st = 2;
	bool top_g = gi == alt;
	for (int t = 0; t < hs3_ntop; ++t)
		top_g |= hs3_top[static_cast<std::size_t>(t)] == gi;
	if (!top_g)
		++hsb_n; // a field outside the top groups
	hs3_sc_g = -1;
	hs3_cs.clear();
	const long used = static_cast<int>(round_number_nc()) != r0 ? f0 + (100000 - FXR_FUEL()) : f0 - FXR_FUEL();
	hs3_worst = std::max(hs3_worst, used);
}
// A dash from my tile over a thin hole to a landing that saves the gain on F (walk wd from here); true if cast.
bool hole_shortcut_dash(int gi, const distance_field& F, int wd)
{
	const Kit& k = *W.me.kit;
	if (k.slot_dash < 0 || !combat::ready(k.slot_dash))
		return false;
	const vec2 me = W.me.pos;
	vec2 best{ -1, -1 };
	int bv = wd - HOLE_SHORT_GAIN;
	for (int dx = -2; dx <= 2; ++dx)
		for (int dy = -2; dy <= 2; ++dy)
		{
			const vec2 u{ me.x + dx, me.y + dy };
			if (std::max(iabs(dx), iabs(dy)) != 2 || !inb(u) || bbget(M.block_camps, u))
				continue;
			const int fu = dfget(F, u);
			if (fu == UNREACH || fu >= bv)
				continue;
			bool hole = false;
#pragma clang loop unroll(full) // unroll fully
			for (const vec2 d : DIRS)
			{
				const vec2 m = me + d;
				hole |= inb(m) && cheb(m, u) == 1 && bbget(M.thin_holes, m);
			}
			if (!hole || !mv::free_tile(u) || mv::camp_threat(u, gi < hsb_alt() ? gi : -1) > 0)
				continue;
			if (k.dash_mod > 0 && combat::lw_bad(u, std::max(1, static_cast<int>(k.dash_radius)), gi < hsb_alt() ? gi : -1))
				continue;
			bool unsafe = false;
			for (const auto& e : W.enemies)
				unsafe |= cheb(e.pos, u) <= (std::max(e.range + 2, combat::foe_next_turn_reach(e) + 1));
			if (unsafe)
				continue;
			bv = fu;
			best = u;
		}
	return best.x >= 0 && combat::cast_at(k.slot_dash, best);
}
// One shortcut turn toward group gi (walk field F): the dash across from a launch tile, else a step toward the launch tiles while
// that route (walk to the launch + the cooldown wait + the walk after the dash) beats the walk by HOLE_SHORT_GAIN.
bool hole_shortcut_turn(int gi, const distance_field& F)
{
	if (!dn::dasher() || !W.me.kit || !W.alive || W.me.channeling())
		return false;
	int v = 0;
	const distance_field* H = hole_shortcut_field(gi, &v);
	if (!H)
		return false;
	const vec2 me = W.me.pos;
	const int wd = dfget(F, me);
	int hd = dfget(*H, me);
	if (wd == UNREACH || hd == UNREACH || (wd < HOLE_SHORT_MIN && !(hsc_held(gi))))
		return false;
	if (gi < static_cast<int>(gmem_size(mem)) && now() - mem[static_cast<std::size_t>(gi)].enemy_seen < HS3_SAFE)
	{
		hs3_commit_g = -1; // an enemy seen at the group lately: walk in with the crew instead
		return false;
	}
	for (const auto& e : W.enemies)
		if (cheb(e.pos, me) <= 10)
		{
			hs3_commit_g = -1; // a visible foe near me keeps the dash for an escape
			return false;
		}
	const Kit& k = *W.me.kit;
	const int cdr = k.slot_dash >= 0 ? W.cd[static_cast<std::size_t>(k.slot_dash)] : BIG;
	const int route = hd + std::max(0, cdr - hd) + v;
	if (route + ((hsc_held(gi)) ? 1 : HOLE_SHORT_GAIN) > wd)
	{
		if (hs3_commit_g == gi)
			hs3_commit_g = -1;
		return false;
	}
	if (hd == 0)
	{
		if (hole_shortcut_dash(gi, F, wd))
		{
			hs3_commit_g = -1;
			hs3_wait_n = 0;
			if (W.can_move() && !W.moved)
				mv::step_field(F, gi < hsb_alt() ? gi : -1); // the altar slot ignores no group
			last_act = ACT_WALK;
			return true;
		}
		// on a launch tile, the dash not ready or every landing taken: hold, a few rounds at most
		hs3_wait_n = (hs3_wait_g == gi && hs3_wait_r >= now() - 1) ? hs3_wait_n + 1 : 1;
		hs3_wait_g = gi;
		hs3_wait_r = now();
		if (hs3_wait_n > HS3_WAIT)
		{
			hs3[static_cast<std::size_t>(gi)].st = 3; // given up for this group
			hs3[static_cast<std::size_t>(gi)].f.reset();
			hs3[static_cast<std::size_t>(gi)].f2.reset();
			hs3_commit_g = -1;
			return false;
		}
		hs3_commit_g = gi;
		hsc_commit_r = now();
		last_act = ACT_WALK;
		return true;
	}
	if (!W.can_move() || W.moved)
		return false;
	mv::travel_dash_need(hd + 1); // keep the dash for the launch tile
	const bool walked = mv::step_field(*H, gi < hsb_alt() ? gi : -1);
	mv::travel_dash_need(0);
	if (!walked)
		return false;
	hs3_commit_g = gi;
	hsc_commit_r = now();
	last_act = ACT_WALK;
	if (dfget_me(*H) == 0)
	{
		const int wd2 = dfget_me(F);
		if (wd2 != UNREACH && hole_shortcut_dash(gi, F, wd2))
			hs3_commit_g = -1;
	}
	return true;
}
} // namespace
void hs3_bg(long reserve) { hole_shortcut_background(reserve); }
bool hs3_pending_x(int gi) { return hole_shortcut_pending(gi); }
} // namespace nova::econ
