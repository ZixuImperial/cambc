// econ_camp_focus.cc: Which camp of a group to hit.
#include "econ_internal.h"
namespace nova::econ {
namespace {
// Camp focus score for a splash kit from a per-camp table of its camp neighbours (static: built once per camp), with the same terms
// in the same DIRS order: a living visible same-group neighbour -1000, a sleeping visible other-group one +50000.
struct CfNb
{
	std::array<int, 8> c{};
	std::int8_t n = -1, same = 0;
};
inline std::vector<CfNb> cf_nb;
inline std::vector<std::vector<PfM>> pf_tab;
inline std::vector<int> pf_at; // camp -> its index in its group's table (-1: none yet)
// Once per (group, near, perceive) (cached): it reads W's camps (perceive), static camp data and my kit.
int pick_focus(int gi, vec2 near)
{
	struct Memo
	{
		int gi;
		vec2 near;
		int best;
	};
	static std::array<Memo, 8> memo{};
	static int nm = 0, st_cur = -1;
	if (st_cur != fg::pstamp)
	{
		st_cur = fg::pstamp;
		nm = 0;
	}
	for (int k = 0; k < nm; ++k)
	{
		const Memo& m = memo[static_cast<std::size_t>(k)];
		if (m.gi == gi && m.near == near)
			return m.best;
	}
	const int best = pick_focus_raw(gi, near);
	if (nm < 8)
		memo[static_cast<std::size_t>(nm++)] = { gi, near, best };
	return best;
}
inline const CfNb& camp_neighbours(int ci)
{
	if (cf_nb.size() != static_cast<std::size_t>(M.nc))
		cf_nb.assign(static_cast<std::size_t>(M.nc), CfNb{});
	CfNb& e = cf_nb[static_cast<std::size_t>(ci)];
	if (e.n < 0)
	{
		const auto& c = M.camps[static_cast<std::size_t>(ci)];
		e.n = 0;
#pragma clang loop unroll(full)
		for (const vec2 d : DIRS)
		{
			const int c2 = M.camp_index(c.pos + d);
			if (c2 < 0 || c2 == ci)
				continue;
			const bool same = M.camps[static_cast<std::size_t>(c2)].group == c.group;
			e.c[static_cast<std::size_t>(e.n++)] = same ? c2 : -2 - c2;
			e.same = static_cast<std::int8_t>(e.same + (same ? 1 : 0));
		}
	}
	return e;
}
float camp_focus_score(int ci, const VisCamp& vc, vec2 near)
{
	const auto& c = M.camps[static_cast<std::size_t>(ci)];
	float s = vc.hp + static_cast<float>(cheb(c.pos, near)) * 40.0f;
	if (!c.attacks())
		s += 100000.0f;
	const CfNb& e = camp_neighbours(ci);
	const auto& slot = W.camp_slot;
	for (int k = 0; k < e.n; ++k)
	{
		const int v = e.c[static_cast<std::size_t>(k)];
		const int c2 = v >= 0 ? v : -2 - v;
		if (static_cast<std::size_t>(c2) >= slot.size())
			continue;
		const int sl = slot[static_cast<std::size_t>(c2)];
		if (sl < 0)
			continue;
		if (v >= 0)
			s -= PASSIVE_VARG_NBR;
		else if (!W.camps[static_cast<std::size_t>(sl)].awake)
			s += 50000.0f;
	}
	return s;
}
std::vector<PfM>& pf_group(int gi)
{
	if (pf_tab.size() != static_cast<std::size_t>(M.ng))
		pf_tab.assign(static_cast<std::size_t>(M.ng), {});
	if (pf_at.size() != static_cast<std::size_t>(M.nc))
		pf_at.assign(static_cast<std::size_t>(M.nc), -1);
	auto& t = pf_tab[static_cast<std::size_t>(gi)];
	const auto& mem = M.groups[static_cast<std::size_t>(gi)].members;
	if (t.size() != mem.size())
	{
		t.clear();
		t.reserve(mem.size());
		for (int ci : mem)
		{
			if (ci >= 0 && ci < M.nc)
			{
				const auto& c = M.camps[static_cast<std::size_t>(ci)];
				pf_at[static_cast<std::size_t>(ci)] = static_cast<int>(t.size());
				t.push_back({ ci, c.pos, !c.attacks(), false, 0.0f });
			}
			else
				t.push_back({ ci, vec2{ 0, 0 }, false, false, 0.0f });
		}
	}
	return t;
}
inline float camp_focus_splash_neighbour_bonus(PfM& m)
{
	if (!m.ns_ok)
	{
		m.nsk = PASSIVE_VARG_NBR * static_cast<float>(camp_neighbours(m.ci).same);
		m.ns_ok = true;
	}
	return m.nsk;
}
// The table entry of a visible camp of group gi (W.camps branch), or nullptr when the table does not list it there.
inline PfM* camp_focus_entry(std::vector<PfM>& t, int ci)
{
	const int k = pf_at[static_cast<std::size_t>(ci)];
	if (k < 0 || k >= static_cast<int>(t.size()) || t[static_cast<std::size_t>(k)].ci != ci)
		return nullptr;
	return &t[static_cast<std::size_t>(k)];
}
int pick_focus_fast(int gi, vec2 near)
{
	int best = -1;
	float best_s = 1e9f;
	auto& t = pf_group(gi);
	const auto& slot = W.camp_slot;
	const std::size_t nslot = slot.size();
	const std::size_t ncamps = static_cast<std::size_t>(M.nc);
	const bool member_loop = !(W.camps.size() < M.groups[static_cast<std::size_t>(gi)].members.size());
	if (varg_layer::focus_splash())
	{
		struct Cand
		{
			int ci;
			const VisCamp* vc;
			float lb;
		};
		static std::vector<Cand> cand;
		if (cand.size() < t.size() || cand.size() < W.camps.size())
			cand.resize(std::max(t.size(), W.camps.size()));
		std::size_t nc = 0;
		if (!member_loop)
		{
			for (const auto& vc : W.camps)
			{
				if (vc.ci < 0 || vc.ci >= static_cast<int>(ncamps) || M.camps[static_cast<std::size_t>(vc.ci)].group != gi)
					continue;
				float b, nsk;
				if (PfM* m = camp_focus_entry(t, vc.ci))
				{
					b = vc.hp + static_cast<float>(cheb(m->pos, near)) * 40.0f;
					if (m->natt)
						b += 100000.0f;
					nsk = camp_focus_splash_neighbour_bonus(*m);
				}
				else
				{
					const auto& c = M.camps[static_cast<std::size_t>(vc.ci)];
					b = vc.hp + static_cast<float>(cheb(c.pos, near)) * 40.0f;
					if (!c.attacks())
						b += 100000.0f;
					nsk = PASSIVE_VARG_NBR * static_cast<float>(camp_neighbours(vc.ci).same);
				}
				cand[nc++] = { vc.ci, &vc, b - nsk };
			}
		}
		else
			for (auto& m : t)
			{
				if (static_cast<std::size_t>(m.ci) >= nslot)
					continue;
				const int sl = slot[static_cast<std::size_t>(m.ci)];
				if (sl < 0)
					continue;
				const VisCamp& vc = W.camps[static_cast<std::size_t>(sl)];
				float b = vc.hp + static_cast<float>(cheb(m.pos, near)) * 40.0f;
				if (m.natt)
					b += 100000.0f;
				cand[nc++] = { m.ci, &vc, b - camp_focus_splash_neighbour_bonus(m) };
			}
		if (nc == 0)
			return -1;
		std::size_t seed = 0;
		for (std::size_t k = 1; k < nc; ++k)
			if (cand[k].lb < cand[seed].lb)
				seed = k;
		best = cand[seed].ci;
		best_s = camp_focus_score(best, *cand[seed].vc, near);
		for (std::size_t k = 0; k < nc; ++k)
		{
			if (k == seed || cand[k].lb > best_s + 1.0f)
				continue;
			const float s = camp_focus_score(cand[k].ci, *cand[k].vc, near);
			if (s < best_s || (s == best_s && cand[k].ci < best))
			{
				best_s = s;
				best = cand[k].ci;
			}
		}
		return best;
	}
	if (!member_loop)
	{
		for (const auto& vc : W.camps)
		{
			if (vc.ci < 0 || vc.ci >= static_cast<int>(ncamps) || M.camps[static_cast<std::size_t>(vc.ci)].group != gi)
				continue;
			float s;
			if (const PfM* m = camp_focus_entry(t, vc.ci))
			{
				s = vc.hp + static_cast<float>(cheb(m->pos, near)) * 40.0f;
				if (m->natt)
					s += 100000.0f;
			}
			else
			{
				const auto& c = M.camps[static_cast<std::size_t>(vc.ci)];
				s = vc.hp + static_cast<float>(cheb(c.pos, near)) * 40.0f;
				if (!c.attacks())
					s += 100000.0f;
			}
			if (s < best_s || (s == best_s && best >= 0 && vc.ci < best))
			{
				best_s = s;
				best = vc.ci;
			}
		}
		return best;
	}
	for (const auto& m : t)
	{
		if (static_cast<std::size_t>(m.ci) >= nslot)
			continue;
		const int sl = slot[static_cast<std::size_t>(m.ci)];
		if (sl < 0)
			continue;
		float s = W.camps[static_cast<std::size_t>(sl)].hp + static_cast<float>(cheb(m.pos, near)) * 40.0f;
		if (m.natt)
			s += 100000.0f;
		if (s < best_s)
		{
			best_s = s;
			best = m.ci;
		}
	}
	return best;
}
int pick_focus_raw(int gi, vec2 near)
{
	return pick_focus_fast(gi, near);
}
// Tiles from which I can hit `focus` without being any awake attacker's target (another body is nearer, or as
// near and first in turn order). Whole-board operations: each attacker marks the square where I would be its target.
bitboard safe_attack_tiles(int gi, int focus, int range, bool must_be_safe, bool* any)
{
	*any = false;
	const vec2 fp = M.camps[static_cast<std::size_t>(focus)].pos;
	bitboard goals;
	goals.draw_chebyshev(fp, static_cast<float>(range));
	bitboard blocked = mv::blocked();
	bbset(blocked, W.me.pos, false);
	goals &= ~blocked;
	if (must_be_safe)
	{
		std::vector<Attacker> la_tmp;
		const auto& att = living_attackers_cached(gi, true, la_tmp);
		bitboard unsafe;
		bool any_unsafe = false;
		for (const auto& a : att)
		{
			int d = BIG;
			bool tie_ok = false;
			auto consider = [&](const Body& b)
			{
				const int db = cheb(b.pos, a.pos);
				if (db < d)
				{
					d = db;
					tie_ok = mv::takes_tie(b);
				}
				else if (db == d && mv::takes_tie(b))
					tie_ok = true;
			};
			for (const auto& al : W.allies)
				if (!al.channeling() || (al.state & ST_TRIBUTE))
					consider(al);
			for (const auto& e : W.enemies)
				consider(e);
			// I am its target within min(reach, d - 1), or d when the other body loses the tie.
			const int r = std::min(a.reach, d == BIG ? a.reach : (tie_ok ? d - 1 : d));
			if (r < 0)
				continue;
			unsafe.draw_chebyshev(a.pos, static_cast<float>(r));
			any_unsafe = true;
		}
		if (any_unsafe)
			goals &= ~unsafe;
	}
	*any = bbany(goals);
	return goals;
}
bool in_reach_of(const std::vector<Attacker>& att, vec2 p, int margin)
{
	for (const auto& a : att)
		if (cheb(p, a.pos) <= a.reach + margin)
			return true;
	return false;
}
static bool prism_group_is_quiet(const GroupI& g);
} // namespace
} // namespace nova::econ
