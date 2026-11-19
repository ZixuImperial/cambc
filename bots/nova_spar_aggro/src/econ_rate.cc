// econ_rate.cc: Rate of a group, part 3: bag and foe limits and the final rate_for.
#include "econ_internal.h"
namespace nova::econ {
namespace {
static int belief_zone(int gi)
{
	if (blf_zc.size() != M.groups.size())
	{
		blf_zc.assign(M.groups.size(), 1);
		for (std::size_t i = 0; i < M.groups.size(); ++i)
		{
			const vec2 a = M.groups[i].anchor;
			const std::int64_t ux = a.x - M.home_anchor.x, uy = a.y - M.home_anchor.y, ex = a.x - M.enemy_anchor.x, ey = a.y - M.enemy_anchor.y;
			const std::int64_t du = ux * ux + uy * uy, dt = ex * ex + ey * ey; // squared: du < 0.8 dt <=> 25 du2 < 16 dt2
			blf_zc[i] = static_cast<std::int8_t>(25 * du < 16 * dt ? 0 : (25 * dt < 16 * du ? 2 : 1));
		}
	}
	return blf_zc[static_cast<std::size_t>(gi)];
}
// The same answer and the same families() re-reads as a call per body. A call on an entry not yet due changes nothing, so it is
// skipped: ex[i] = the round body i's entry falls due; any write that changes an entry's handle or bits clears them all, as does a
// new body.
static bool any_foe_capture_holder()
{
	static std::array<int, 16> ex{};
	static std::array<bool, 16> cap{};
	static int until = -1, nb = -1;
	static std::uint32_t chg = 0;
	static bool hold = false;
	const int t = W.round;
	const std::uint32_t c0 = rs::fam_chg;
	const int n0 = intel::team_body_changes();
	const bool same = c0 == chg && n0 == nb;
	if (same && t < until)
		return hold;
	const std::size_t n = intel::team_table().size();
	if (!same)
		ex.fill(-1);
	int u = 2147483647;
	bool h = false;
	for (std::size_t i = 0; i < n; ++i)
	{
		if (t >= ex[i])
		{
			if (const Body* b = intel::team_body(i))
			{
				cap[i] = rs::has(rs::families(b->h, t), rs::F_CAPTURE);
				ex[i] = std::max(t + 1, rs::fam_until(b->h));
			}
			else
			{
				cap[i] = false;
				ex[i] = 2147483647; // no body yet: team_body_changes moves when one comes
			}
		}
		h = h || cap[i];
		u = std::min(u, ex[i]);
	}
	until = u;
	chg = c0; // a write during this loop (an evicted entry) clears them next turn
	nb = n0;
	hold = h;
	return h;
}
// rounds from a read to the earliest pay of a foe's capture started then: a Capture emblem read on any foe shortens it (emblems as
// read in sight). Once a turn.
static int foe_capture_pay_rounds()
{
	static int au2_r = -1, au2_pay = 0;
	if (au2_r != now())
	{
		au2_r = now();
		bool holder = false;
		if (intel::team_table().size() <= 16)
			holder = any_foe_capture_holder();
		else
			for (std::size_t i = 0; i < intel::team_table().size(); ++i)
				if (const Body* b = intel::team_body(i); b && rs::has(rs::families(b->h, W.round), rs::F_CAPTURE))
					holder = true;
		au2_pay = rs::capture_pay(holder);
	}
	return au2_pay;
}
// someone of ours holds g's tiles (a mate's claim, an ally or me within 4 of the anchor): its CLEARED belief stays sure.
static bool our_body_holds_group_tiles(int gi)
{
	for (int s = 0; s < P.n && s < comms::CLAIM_SLOTS; ++s)
		if (s != P.my_slot && comms::cgroup(s) == gi)
			return true;
	const vec2 a = M.groups[static_cast<std::size_t>(gi)].anchor;
	if (cheb(W.me.pos, a) <= 4)
		return true;
	for (const auto& al : W.allies)
		if (cheb(al.pos, a) <= 4)
			return true;
	return false;
}
// the share of g's value still there (1 with the bits off, or a sure belief). Callers test (BLF_TAB[1] & 3) first.
static float belief_value_share(int gi, const GroupMem& m)
{
	if (m.status == GS_UNKNOWN && BLF_B(1))
	{
		const int z = belief_zone(gi);
		const int pm = m.seen <= -1000 ? BLF_PT_U[z][4] : BLF_PT_U[z][blf_bkt(now() - m.seen)];
		++blf_n[0];
		return 1.0f - static_cast<float>(pm) / 1000.0f;
	}
	if (m.status == GS_CLEARED && BLF_B(2))
	{
		const int age = now() - std::max(m.seen, m.state_checked); // the last round its state was read (own sight or news)
		RULE_AUDIT_FIX_CNT(5, !our_body_holds_group_tiles(gi) && (age < rs::capture_rounds(rs::rules().capture_time, false)) != (age < foe_capture_pay_rounds()));
		if (age < (foe_capture_pay_rounds()) || our_body_holds_group_tiles(gi))
			return 1.0f; // no capture by anyone else can have paid yet, or ours hold it
		++blf_n[1];
		return 1.0f - static_cast<float>(BLF_PT_C[belief_zone(gi)][blf_bkt(age)]) / 1000.0f;
	}
	return 1.0f;
}
static bool foe_hp_reads_full(int ti, const Body& b)
{
	const auto& tt = intel::team_table();
	if (ti < 0 || static_cast<std::size_t>(ti) >= tt.size())
		return false;
	if (tt[static_cast<std::size_t>(ti)].src == 4)
		return true;
	const int rd = intel::team_body_read_round(static_cast<std::size_t>(ti));
	const int age = now() - rd;
	if (rd <= -1000 || age <= 0)
		return false;
	const bool au2_home = rs::has(rs::families(b.h, W.round), rs::F_HOME);
	RULE_AUDIT_FIX_CNT(6, au2_home && age >= rs::recall_rounds(true, false) + 1 && age < rs::recall_rounds(false, false) + 1);
	if (age >= rs::recall_rounds(au2_home, false) + 1)
		return true;
	if (!blf_esp_ok)
	{
		blf_esp_ok = true;
		bbforeach(M.enemy_spawn, [&](vec2 p) { blf_esp.x0 = std::min(blf_esp.x0, p.x); blf_esp.y0 = std::min(blf_esp.y0, p.y); blf_esp.x1 = std::max(blf_esp.x1, p.x); blf_esp.y1 = std::max(blf_esp.y1, p.y); });
	}
	const int dx = std::max({ blf_esp.x0 - b.pos.x, 0, b.pos.x - blf_esp.x1 }), dy = std::max({ blf_esp.y0 - b.pos.y, 0, b.pos.y - blf_esp.y1 });
	return std::max(dx, dy) + 1 <= age;
}
void foe_arrival_refresh()
{
	if (gpv3_r == now())
		return;
	gpv3_r = now();
	gpv3_n = 0;
	gpv3_me = -1.0f; // read on first need
	gpv3_ss = -1.0f;
	gpv3_age = GPV_TAB[6];
	gpv3_st = static_cast<float>(GPV_TAB[8]) / 100.0f;
	gpv3_w = static_cast<float>(GPV_TAB[5]) / 100.0f;
	gpv3_e = std::clamp(static_cast<int>(GPV_TAB[9]), 1, 12);
	const auto& tt = intel::team_table();
	const int cell = intel::sight_cell_size();
	for (std::size_t i = 0; i < tt.size() && gpv3_n < 8; ++i)
	{
		const auto& e = tt[i];
		if (!e.alive)
			continue; // dead: back no earlier than its respawn (first version: not counted)
		GpvFoe f;
		f.spawn = e.src == 4 || e.round < 0;
		f.pos = e.pos;
		f.age = e.round < 0 ? 1000 : now() - e.round;
		f.slack = 3 + (e.src == 3 ? cell / 2 : 0);
		f.ti = static_cast<int>(i);
		gpv3_f[static_cast<std::size_t>(gpv3_n++)] = f;
	}
	std::stable_partition(gpv3_f.begin(), gpv3_f.begin() + gpv3_n, [](const GpvFoe& f) { return f.age <= gpv3_age; });
	gpv3_nf = 0;
	while (gpv3_nf < gpv3_n && gpv3_f[static_cast<std::size_t>(gpv3_nf)].age <= gpv3_age)
		++gpv3_nf;
}
float my_fight_strength()
{
	if (gpv3_me < 0.0f)
		gpv3_me = std::max(1.0f, combat::eff_hp(W.me) * combat::horizon_dps(W.me, true));
	return gpv3_me;
}
// A foe's strength, computed on first need this round (only foes that can arrive are read).
float foe_strength_lazy(GpvFoe& f)
{
	if (f.sok)
		return f.s;
	f.sok = true;
	const Body* b = intel::team_body(static_cast<std::size_t>(f.ti));
	const bool fgr = mu::bits != 0 && mu::on(mu::B_FGR); // The projection depends on now, so there is no round cache.
	GpvSc* sc = !fgr && f.ti >= 0 && f.ti < 8 ? &gpv3_sc[static_cast<std::size_t>(f.ti)] : nullptr;
	const int sr = now() - f.age;
	const bool healed = (b && b->kit && BLF_B(4)) ? foe_hp_reads_full(f.ti, *b) : f.age > 15;
	if (sc && b && b->kit && sc->round == sr && sc->healed == healed)
	{
		f.s = sc->s;
		return f.s;
	}
	if (b && b->kit)
	{
		Body c = *b;
		if (fgr)
			intel::team_body_pred(static_cast<std::size_t>(f.ti), now(), c);
		if (healed)
		{
			blf_n[3] += BLF_B(4) && c.hp < c.maxhp ? 1 : 0;
			c.hp = c.maxhp; // healed since
			c.shield = 0;
		}
		const combat::Foe fo = combat::foe_of(c, -1);
		f.s = std::max(1.0f, fo.ehp * fo.dps);
		if (sc)
		{
			sc->round = sr;
			sc->healed = healed;
			sc->s = f.s;
		}
	}
	else
		f.s = my_fight_strength(); // never read: as strong as I am
	return f.s;
}
// the rate factor for my trip to g finishing in tf rounds with a crew of `crew` (callers test the group-value flag, self, opened)
float foe_arrival_factor(const GroupI& g, float tf, int crew)
{
	(void)tf; // amendment: arrival by distance, not by our finish time
	foe_arrival_refresh();
	float F = 0.0f;
	for (int j = 0; j < gpv3_nf; ++j)
	{
		GpvFoe& f = gpv3_f[static_cast<std::size_t>(j)];
		float p = 0.0f;
		{
			// Arrival during a clear is distance-first: <= 6 tiles .71-.78, 7-12 .11-.19, 13-20 .02-.04. Distance = walk lower bound now
			// (sighting widened by half its age; spawn: d_enemy less its age).
			int a;
			if (f.spawn)
				a = g.d_enemy == UNREACH ? 1000 : static_cast<int>(g.d_enemy) - f.age;
			else
				a = cheb(f.pos, g.anchor) - f.age / 2 - (f.slack - 3);
			p = a <= 6 ? 0.75f : (a <= 12 ? 0.15f : (a <= 20 ? 0.03f : 0.0f));
		}
		if (p > 0.0f)
			F += p * foe_strength_lazy(f);
	}
	if (gpv3_nf < gpv3_n && g.contest > 0.30f)
	{
		if (gpv3_ss < 0.0f)
		{
			gpv3_ss = 0.0f;
			for (int j = gpv3_nf; j < gpv3_n; ++j)
				gpv3_ss += foe_strength_lazy(gpv3_f[static_cast<std::size_t>(j)]);
			gpv3_ss *= gpv3_st;
		}
		F += clampf((g.contest - 0.30f) / 0.40f, 0.0f, 1.0f) * gpv3_ss;
	}
	if (F <= 0.0f)
		return 1.0f;
	const float C = static_cast<float>(std::max(1, crew)) * my_fight_strength();
	// amendment: F/C > 2 is the deadly cell (crew deaths x7): risk = F^e / (F^e + C^e), e = [9] (0 reads as 2)
	const float fr = F / C;
	float fe = fr;
	for (int k = 1; k < gpv3_e; ++k)
		fe *= fr; // integer power, no std::pow
	const float risk = fe / (fe + 1.0f);
	return std::max(0.05f, 1.0f - gpv3_w * risk);
}
template <int DM>
float rate_for(int gi, int self, std::uint16_t trav, const Claims& cl, int max_extra, int* crew_out)
{
	const auto& g = M.groups[static_cast<std::size_t>(gi)];
	const auto& m = mem[static_cast<std::size_t>(gi)];
	RateJob j{ gi, self, trav, cl, max_extra, g, m, g.access != ACC_WALK };
	if (j.closed())
		return -1;
	if (j.respawn_too_late())
		return -1;
	if (j.claimed<DM>())
		return -1;
	j.size_crew();
	j.recruit();
	j.chip_trip();
	if (j.no_crew())
		return -1;
	if (j.crew_floor())
		return -1;
	j.crew_walk();
	j.time_and_value();
	j.penalties<DM>();
	j.crew_term<DM>();
	if (j.late_factors())
		return -1;
	// nova_spar_aggro hook (rows First contact, Enemy-half): see spag_factor in econ_internal.h.
	return j.publish(crew_out) * spag_factor(g);
}
// team_feasible's refresh of entry i
void team_feasible_refresh(std::size_t i)
{
	++tf_est_n;
	team_ok_round[i] = now();
	const auto& g = M.groups[i];
	if (g.n_att == 0)
		team_ok[i] = 1;
	else
	{
		// Hopeless only: camp damage above three times the whole team's HP budget (current HP varies; bodies heal before they engage, so
		// borderline groups stay candidates and rate_for judges them). The whole-team crew is built once per build of the team view.
		static Crew c;
		static int c_epoch = -1;
		if (c_epoch != crew_epoch)
		{
			c_epoch = crew_epoch;
			c = Crew{};
			for (int k = 0; k < TM.n; ++k)
				c.add(TM.m[static_cast<std::size_t>(TM.by_tank[static_cast<std::size_t>(k)])]);
			for (auto& b : c.budget)
				b *= 3.0f;
			for (auto& b : c.budget_he)
				b *= 3.0f;
		}
		team_ok[i] = estimate_cx(1, g, mem[i], c).feasible ? 1 : 0;
	}
}
bool team_feasible(int gi)
{
	if (team_ok.size() != static_cast<std::size_t>(M.ng))
	{
		team_ok.assign(static_cast<std::size_t>(M.ng), 1);
		team_ok_round.assign(static_cast<std::size_t>(M.ng), -1000);
	}
	const auto i = static_cast<std::size_t>(gi);
	if (TM.n <= 0)
		return true;
	// At most 4 fresh estimates per turn, with fuel to spare; a stale entry keeps its value (unknown counts as
	// feasible).
	if (tf_est_round != now())
	{
		tf_est_round = now();
		tf_est_n = 0;
	}
	if (now() - team_ok_round[i] >= 25 && tf_est_n < 4 && (fuel() > 60000))
		team_feasible_refresh(i);
	return team_ok[i] != 0;
}
// Hold a capture in our territory past capture()'s 16-round limit, up to TERR_HOLD more rounds, while I stand on its region above
// 40% health: a contested timer restarts, and stepping off hands the payout to them.
bool territory_hold(const GroupI& g, int gi)
{
	if (!opened || g.contest > TERR_OWN || now() - T.cap_start > 16 + TERR_HOLD || W.me.frac() < 0.4f)
		return false;
	for (int ci : g.members)
		if (M.camps[static_cast<std::size_t>(ci)].pos == W.me.pos)
		{
			(void)gi;
			return true;
		}
	return false;
}
} // namespace
} // namespace nova::econ
