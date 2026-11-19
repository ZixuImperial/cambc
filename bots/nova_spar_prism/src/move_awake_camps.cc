// move_awake_camps.cc: Camps that may still hit me out of sight.
#include "move_internal.h"
namespace nova::mv {
namespace {
// v7xx MBB5 bit 1 AWM1, caller read the flag: an entry out of sight whose reach covers me and not known dead is renewed (round - 1, as
// note_awake: readers that skip this round's sightings still count it). It expires AWAKE_MEM_ROUNDS after I leave the reach.
__attribute__((noinline)) void awm1_refresh_in_reach(int now)
{
	for (auto& m : awake_mem)
	{
		const auto& c = M.camps[static_cast<std::size_t>(m.ci)];
		if (m.round < now - 1 && cheb(c.pos, W.me.pos) <= c.reach && !bbget(W.vis, c.pos) && !econ::camp_known_dead(m.ci))
			m.round = now - 1;
	}
}
void update_awake_mem()
{
	const int now = W.round;
	// FW: one pass with a per-camp index into awake_mem instead of a scan of awake_mem for every awake camp (quadratic
	// with dozens of awake wolves in sight: 13-21k on 02the-pack). Same entries in the same order: a camp never has two
	// entries (this loop and note_awake add one only when none exists).
	static std::vector<std::int32_t> am_at;
	if (am_at.size() != static_cast<std::size_t>(M.nc))
		am_at.assign(static_cast<std::size_t>(M.nc), -1);
	for (std::size_t i = 0; i < awake_mem.size(); ++i)
		am_at[static_cast<std::size_t>(awake_mem[i].ci)] = static_cast<std::int32_t>(i);
	for (const auto& vc : W.camps)
	{
		if (!vc.awake || !M.camps[static_cast<std::size_t>(vc.ci)].attacks())
			continue;
		auto& at = am_at[static_cast<std::size_t>(vc.ci)];
		if (at >= 0)
			awake_mem[static_cast<std::size_t>(at)].round = now;
		else
		{
			at = static_cast<std::int32_t>(awake_mem.size());
			awake_mem.push_back({ vc.ci, now });
		}
	}
	for (const auto& m : awake_mem)
		am_at[static_cast<std::size_t>(m.ci)] = -1;
	awm1_refresh_in_reach(now);
	awake_mem.erase(std::remove_if(awake_mem.begin(), awake_mem.end(),
						[&](const AwakeMem& m)
						{
							if (now - m.round > tune::AWAKE_MEM_ROUNDS)
								return true;
							return m.round != now && bbget(W.vis, M.camps[static_cast<std::size_t>(m.ci)].pos);
						}),
		awake_mem.end());
	++ct_ver;
}

} // namespace

bool awake_known(int ci)
{
	for (const auto& m : awake_mem)
		if (m.ci == ci)
			return true;
	return false;
}

// Remembered-awake attackers out of sight now (camp_threat counts them, the bail's threat list did not) whose reach covers p.
void awake_mem_threats(vec2 p, std::vector<Threat>& th)
{
	for (const auto& m : awake_mem)
	{
		if (m.round == W.round) // v699 RCB bit 16 AWM1: skip only camps in sight now
			continue;
		const auto& c = M.camps[static_cast<std::size_t>(m.ci)];
		if (!c.attacks() || cheb(c.pos, p) > c.reach)
			continue;
		bool dup = false;
		for (const auto& t : th)
			dup = dup || t.pos == c.pos;
		if (!dup)
			th.push_back({ c.pos, c.reach });
	}
}

void note_awake(int ci)
{
	if (ci < 0 || ci >= M.nc)
		return;
	++ct_ver; // FW: camp_threat's list follows awake_mem
	for (auto& m : awake_mem)
		if (m.ci == ci)
		{
			m.round = W.round - 1;
			return;
		}
	awake_mem.push_back({ ci, W.round - 1 });
}
} // namespace nova::mv
