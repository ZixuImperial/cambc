// squad.cc: Squads per objective: which bodies work together, chosen each turn from their objectives (see squad.h).
#include "squad.h"

#include <algorithm>
#include <cstdio>

#include "comms.h"
#include "econ.h"
#include "intel.h"
#include "mapinfo.h"
#include "plan.h"
#include "champ_willow.h"

namespace nova::squad {

namespace {
// Objective of each slot this turn (claims; mine is econ's target), and the group count it was read against.
std::array<int, 8> obj{ -1, -1, -1, -1, -1, -1, -1, -1 };
int obj_round = -1;

int n_slots() { return std::clamp(P.n, 0, static_cast<int>(comms::CLAIM_SLOTS)); }

void read_objectives()
{
	if (obj_round == W.round)
		return;
	obj_round = W.round;
	const int ng = M.ng;
	for (int s = 0; s < 8; ++s)
	{
		int g = -1;
		if (s < n_slots())
			g = s == P.my_slot ? econ::claim_target() : comms::cgroup(s);
		obj[static_cast<std::size_t>(s)] = (g >= 0 && g < ng) ? g : -1;
	}
}

bool near_objectives(int ga, int gb)
{
	if (ga < 0 || gb < 0)
		return false;
	return ga == gb || cheb(M.groups[static_cast<std::size_t>(ga)].anchor, M.groups[static_cast<std::size_t>(gb)].anchor) <= SQ_LEASH;
}
} // namespace

namespace {
std::array<int, 8> cl_last{ -2, -2, -2, -2, -2, -2, -2, -2 }, cl_round{ -1000, -1000, -1000, -1000, -1000, -1000, -1000, -1000 };
}

void begin_turn()
{
	obj_round = -1; // claims were re-read: refresh on first use
	// when each slot's claimed group last changed (as seen at my turn starts), so a squad that leaves together stays together.
	for (int s = 0; s < n_slots(); ++s)
	{
		const int g = comms::cgroup(s);
		if (cl_last[static_cast<std::size_t>(s)] != -2 && g != cl_last[static_cast<std::size_t>(s)])
			cl_round[static_cast<std::size_t>(s)] = W.round;
		cl_last[static_cast<std::size_t>(s)] = g;
	}
}

int claim_changed(int s)
{
	if (s < 0 || s >= 8)
		return -1000;
	return cl_round[static_cast<std::size_t>(s)];
}


__attribute__((always_inline)) int objective(int s)
{
	if (s < 0 || s >= 8)
		return -1;
	if (s == P.my_slot)
		return econ::claim_target(); // my target may change within the turn
	read_objectives();
	return obj[static_cast<std::size_t>(s)];
}

bool outside(int gi)
{
	return gi >= 0 && gi < M.ng && M.groups[static_cast<std::size_t>(gi)].contest > SQ_OUT;
}

unsigned mates(int s)
{
	const int go = objective(s);
	if (go < 0)
		return 0;
	unsigned m = 0;
	for (int t = 0; t < n_slots(); ++t)
		if (t != s && near_objectives(go, objective(t)))
			m |= 1u << t;
	return m;
}

namespace {
std::array<int, 8> f_seed{ -1, -1, -1, -1, -1, -1, -1, -1 };
std::array<int, 8> live{};
int form_round = -1, live_round = -1;

void read_live()
{
	if (live_round == W.round)
		return;
	live_round = W.round;
	// n_slots() is read once and the allies' slots are kept as one mask (ally_by_slot(s) != nullptr <=> bit s).
	const int n = n_slots();
	unsigned am = 0;
	for (const auto& a : W.allies)
		if (a.slot >= 0 && a.slot < 8)
			am |= 1u << a.slot;
	for (int s = 0; s < 8; ++s)
	{
		int v = 0;
		if (s < n)
		{
			if (s == P.my_slot)
				v = W.alive ? 1 : 0;
			else if (am & (1u << s))
				v = 1;
			else
			{
				std::int32_t a = 1;
				if (cambc::detail::sdk_champion_is_alive(P.handle[static_cast<std::size_t>(s)], &a) != 0)
					a = 1;
				v = a != 0 ? 1 : 0;
			}
		}
		live[static_cast<std::size_t>(s)] = v;
	}
}

// The formation reads the claim bytes of every slot, mine included (what every other body reads too).
void form()
{
	if (form_round == W.round)
		return;
	form_round = W.round;
	f_seed.fill(-1);
	read_live();
	const int n = n_slots(), ng = M.ng;
	std::array<int, 8> o{ -1, -1, -1, -1, -1, -1, -1, -1 };
	std::array<bool, 8> eng{};
	std::array<vec2, 8> oa; // Each objective's anchor is read once (valid where o >= 0).
	const GroupI* const gp = M.groups.data();
	for (int s = 0; s < n; ++s)
	{
		const int g = comms::cgroup(s);
		o[static_cast<std::size_t>(s)] = (live[static_cast<std::size_t>(s)] && g >= 0 && g < ng) ? g : -1;
		if (o[static_cast<std::size_t>(s)] >= 0)
			oa[static_cast<std::size_t>(s)] = gp[g].anchor;
		eng[static_cast<std::size_t>(s)] = comms::cengaged(s);
	}
	std::array<bool, 8> seed{}, pool{};
	for (int s = 0; s < n; ++s)
	{
		const int g = o[static_cast<std::size_t>(s)];
		if (g < 0 || gp[g].access != ACC_WALK)
			continue;
		if (gp[g].contest > SQ_OUT) // outside(g) (g is in range)
		{
			// near_objectives(g, o[t]) on the cached anchors, stopping at the first mate (pure tests).
			bool mate = false;
			const vec2 ga = oa[static_cast<std::size_t>(s)];
			for (int t = 0; t < n && !mate; ++t)
			{
				const int ot = o[static_cast<std::size_t>(t)];
				mate = t != s && ot >= 0 && (ot == g || cheb(oa[static_cast<std::size_t>(t)], ga) <= SQ_LEASH);
			}
			// the hot test from shared reports only, so every pool body forms the same pairs: with SQ_HOT 1 the test is 'any kept report
			// near', answered at the first match
			seed[static_cast<std::size_t>(s)] = !mate && ((intel::danger_shared_any(ga, SQ_HOT_R, SQ_HOT_AGE)));
		}
		else
		{
			// A pool body works alone (no other claimant of its group): pulling a crew member would break its crew (the opening's drafted
			// crews, elk crews). SQ_FORM_FROM: never in the opening.
			bool crew = false;
			for (int t = 0; t < n; ++t)
				crew |= t != s && o[static_cast<std::size_t>(t)] == g;
			pool[static_cast<std::size_t>(s)] = !eng[static_cast<std::size_t>(s)] && !crew && W.round >= SQ_FORM_FROM;
		}
	}
	for (int s = 0; s < n; ++s)
	{
		if (!seed[static_cast<std::size_t>(s)])
			continue;
		const vec2 at = oa[static_cast<std::size_t>(s)];
		int best = -1, bd = SQ_FORM_R + 1;
		for (int t = 0; t < n; ++t)
		{
			if (!pool[static_cast<std::size_t>(t)])
				continue;
			const int d = cheb(oa[static_cast<std::size_t>(t)], at); // pool[t] implies o[t] >= 0
			if (d < bd)
			{
				bd = d;
				best = t;
			}
		}
		if (best >= 0)
		{
			pool[static_cast<std::size_t>(best)] = false;
			f_seed[static_cast<std::size_t>(best)] = s;
		}
	}
}
} // namespace
int squad_seed_of_slot(int s)
{
	if (s < 0 || s >= 8)
		return -1;
	if (form_round != W.round)
	{
		// f_seed[s] >= 0 needs pool[s] (form's own test, same calls in the same order up to it: read_live, memoised per round). Without it the answer is -1 and the full formation is left for a call that needs it (f_seed is read nowhere else).
		read_live();
		const int n = n_slots(), ng = M.ng;
		bool may = s < n && live[static_cast<std::size_t>(s)] && W.round >= SQ_FORM_FROM;
		int g = -1;
		if (may)
		{
			g = comms::cgroup(s);
			may = g >= 0 && g < ng && M.groups[static_cast<std::size_t>(g)].access == ACC_WALK && !outside(g) && !comms::cengaged(s);
		}
		for (int t = 0; t < n && may; ++t)
			if (t != s && live[static_cast<std::size_t>(t)] && comms::cgroup(t) == g)
				may = false; // a crew mate on my group
		if (!may)
			return -1;
	}
	form();
	return f_seed[static_cast<std::size_t>(s)];
}

bool alive(int s)
{
	if (s < 0 || s >= 8)
		return false;
	read_live();
	return live[static_cast<std::size_t>(s)] != 0;
}

bool objective_ok(int gi)
{
	if (!outside(gi))
		return false;
	return hot(gi);
}

bool hot(int gi)
{
	if (gi < 0 || gi >= M.ng)
		return false;
	return intel::danger(M.groups[static_cast<std::size_t>(gi)].anchor, SQ_HOT_R, SQ_HOT_AGE) >= static_cast<float>(SQ_HOT);
}

} // namespace nova::squad
