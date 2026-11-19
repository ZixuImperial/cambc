// econ_bank_race.cc: Race timing: bank-first and finish estimates.
#include "econ_internal.h"
namespace nova::econ {
// the first early-out test is inlined at the call site (this runs every turn); the rest is out of line
__attribute__((always_inline)) void bank_step_turn()
{
	if (bs_mark != now())
		return;
	bank_step_turn_slow();
}
__attribute__((noinline)) void bank_step_turn_slow()
{
	if (bs_mark != now() || fuel() < 8000 || !W.alive || !W.me.kit)
		return;
	const int gems = static_cast<int>(W.me.gems);
	const vec2 me = W.me.pos;
	if (gems < 1 || bag_too_late_to_bank(gems))
		return;
	const std::uint32_t h = static_cast<std::uint32_t>(cambc::detail::sdk_my_champion());
	cambc::detail::champion_info ci{};
	if (cambc::detail::sdk_champion(h, &ci) != 0 || (static_cast<std::uint32_t>(ci.state) & (ST_RECALL | ST_TRIBUTE | ST_TELEPORT)))
		return;
	for (int pass = 0; pass < 2; ++pass)
		for (const auto& a : M.altars)
		{
			if (cheb(a.pos, me) > cambc::constants::submit_gems_range)
				continue;
			if (END_HOLD_ON && end_hold_blocks_bank(gems))
				return;
			const bool pc = prism_layer::chan_guard();
			if (pc && !prism::channel_start_ok(gems))
				return;
			if (pc && gems >= PC_CHAN_BAG)
			{
				const int ticks = rs::tribute_turns(gems, prism::has_family(rs::F_TRIBUTE));
				const float inc = incoming_at(me, nullptr);
				if (inc > 0.0f && inc * static_cast<float>(ticks) >= 0.5f * W.me.hp)
					return;
			}
			if (pc && prism_channel_unsafe())
				return;
			if (!pc && !prism::tribute_start_allowed(gems))
				return;
			if (new_tribute_blocked())
				return;
			if (pass == 0)
			{
				bool shared = false;
				for (const auto& al : W.allies)
					shared |= (al.state & ST_TRIBUTE) && cheb(al.pos, a.pos) <= 1;
				if (shared)
					continue;
			}
			try
			{
				if (cambc::vision::has_altar_lock(a.pos))
				{
					cambc::detail::altar_lock_info lkb{};
					if (cambc::vision::altar_lock_at(a.pos).is_enemy() || enemy_altar_lock_direct(a.pos, lkb))
						continue; // both teams' locks read as ours; the enemy's is read directly
				}
				combat::protect_tribute(a.pos, gems);
				cancel_spin_before_action();
				cambc::self().submit_gems(a.pos);
				b781_trib_start = now();
				NLOG("r%d slot %d bank-step tribute %d gems\n", now(), P.my_slot, gems);
				return;
			}
			catch (const std::exception& e)
			{
				NLOG("r%d bank-step error %s\n", now(), e.what());
				return;
			}
		}
}
// My engaged target group pays soon: it is at <= 25% of its health or its awake attackers die to the crew here within 3 rounds (at
// most 4). Returns the rounds to finish it (-1: no) and its anchor; *camp_in receives the camps' damage per round on my tile. Not
// while capturing.
int finish_rounds(vec2* anchor, float* camp_in)
{
	if (T.capturing || T.target < 0 || !engaged_now() || gmem_size(mem) != static_cast<std::size_t>(M.ng))
		return -1;
	const auto& g = M.groups[static_cast<std::size_t>(T.target)];
	const auto& m = mem[static_cast<std::size_t>(T.target)];
	std::vector<mv::Threat> th;
	const float incoming = incoming_at(W.me.pos, &th);
	if (th.empty())
		return -1;
	const Here here = crew_here(T.target);
	float hp_left = 0;
	const float dps = threat_kill_dps(here.crew, th, &hp_left);
	const float rounds = hp_left / std::max(1.0f, dps);
	const float frac = m.hp_left >= 0 ? m.hp_left / std::max(1.0f, g.hp) : 1.0f;
	if (rounds > 4.0f || (frac > 0.25f && rounds > 3.0f))
		return -1;
	*anchor = g.anchor;
	*camp_in = incoming;
	return static_cast<int>(std::ceil(rounds));
}
bool target_pays_within(int max_rounds)
{
	if (T.capturing)
	{
		const int k = capture_pay_in();
		return k >= 0 && k <= max_rounds;
	}
	vec2 an{ -1, -1 };
	float ci = 0;
	const int fr = finish_rounds(&an, &ci);
	return fr >= 0 && fr <= max_rounds;
}
bool bank_first(const std::vector<vec2>& foe_pos, const std::vector<int>& foe_reach)
{
	const int gems = static_cast<int>(W.me.gems);
	if ((gems < 10) || !M.has_altar || !bankable() || prism_layer::bank_skip_bus()) // 1-9 gem bags
		return false;
	if (T.capturing || engaged_now() || about_to_capture())
		return false;
	const std::uint16_t d = bank_dist_here();
	if (d == UNREACH || d > 6)
		return false;
	const int walk = static_cast<int>(d);
	if (gems < 10 && walk > 1)
		return false; // a small bag only from the altar's edge (a 1-tick channel)
	const int chan = rs::tribute_rounds(gems, static_cast<bool>(prism::has_family(rs::F_TRIBUTE)));
	if (walk <= 1 && (finish_mode(0) || finish_bank(gems, walk + chan + 8)))
	{
		if (mv::camp_threat(W.me.pos) > 0 && walk == 0)
			return false;
		wbr_finf = true; // which caller channel_survives_known_foes serves
		const bool wbr_ok = channel_survives_known_foes(walk, chan);
		wbr_finf = false;
		if (!wbr_ok)
			return false;
		wb2_lc = true;
		const bool fok = bank();
		wb2_lc = false;
		return fok;
	}
	int worst = BIG;
	for (std::size_t i = 0; i < foe_pos.size(); ++i)
	{
		const int dist = std::max(0, cheb(foe_pos[i], W.me.pos) - walk);
		const int reach = foe_reach[i] >= 0 ? foe_reach[i] : 4; // an old sighting: assume a dash or a spell
		const int t_hit = 1 + std::max(0, dist - reach);
		worst = std::min(worst, t_hit);
		if (t_hit <= walk + chan)
			return false;
	}
	if (mv::camp_threat(W.me.pos) > 0 && walk == 0)
		return false; // an awake camp hits the tribute tile: the normal flow moves first
	const bool ok = bank();
	return ok;
}
} // namespace nova::econ
