// econ_threat_sense.cc: What this body felt: threats and blacklists.
#include "econ_internal.h"
namespace nova::econ {
namespace {
// unseen attackers that hit me next round, added to th. Returns their damage; 0 with the condition unmet (no list built).
float cbl_pred = 0.0f;
// ---------------------------------------------------------------- what this body felt

float my_shield()
{
	std::array<cambc::detail::buff_data, 3> raw{};
	std::uint32_t count = 0;
	if (cambc::detail::sdk_champion_buff_data(W.me.h, raw.data(), static_cast<std::uint32_t>(raw.size()), &count) != 0)
		return 0;
	float s = 0;
	for (std::uint32_t i = 0; i < count && i < raw.size(); ++i)
		if (raw[i].type == 0)
			s += raw[i].data.shield.value;
	return s;
}
// A recall started this turn completes at my turn start ch rounds later (ch = 3 with Home, GameRules :383); a foe gets N = ch - 1
// turns in between, +1 when it acts after me now, +1 when it starts round R + ch (:122-127): 6 or 4 for ch = 5. prefired: my kept
// spin has one tick done (ch 4, Home 2): 4 (Home 2) on both parities.
static int foe_turns_during_recall(bool prefired = false)
{
	const int ch = rs::recall_rounds(prism::has_family(rs::F_HOME), prefired);
	const int R = now();
	return std::max(1, ch - 1 + (enemy_starts(R) ? 0 : 1) + (enemy_starts(R + ch) ? 1 : 0));
}
// each foe's tile at the last two rounds I saw it (by handle), noted once a turn in the self refresh.
namespace
{
struct LrnSeen
{
	std::uint32_t h = 0;
	vec2 p_cur{}, p_prev{};
	int r_cur = -9, r_prev = -9;
};
LrnSeen lrn_s[12];
} // namespace
// The Chebyshev distance within which foe e can damage me in its n turns. Per option: melee moves and hits (1 + n),
// ranged moves or hits (range + n - 1; + 1 with an attack reset), spells range + area radius + n (- 1 when
// walk-excluding); + 2 once for a dash kit. Chebyshev <= walk distance, so cheb(e, me) <= this is conservative.
static int foe_reach_in_turns(const Body& e, int n)
{
	const Kit* k = e.kit;
	int r = std::max(e.range, 1) + n + 2; // unknown kit: move and hit, with a dash
	if (k && k->valid)
	{
		r = k->ranged ? std::max(e.range, 1) + n - (k->slot_reset >= 0 ? 0 : 1) : std::max(e.range, 1) + n;
		auto sp = [&](int slot, float range, float radius, bool excl)
		{
			if (slot >= 0)
				r = std::max(r, static_cast<int>(range + radius) + n - (excl ? 1 : 0));
		};
		sp(k->slot_dmg, k->dmg_range, 0.0f, k->dmg_excl);
		sp(k->slot_cc, k->cc_range, 0.0f, k->cc_excl);
		sp(k->slot_aoe, k->aoe_range, k->aoe_radius, k->aoe_excl);
		if (k->slot_dash >= 0)
			r += 2;
	}
	return r;
}
// last round's loss beat what the camps I can see explain, with no foe near and a hidden attacker in reach. My tile hasn't changed
// since the camps hit.
static bool unseen_camp_hit_check(float loss)
{
	if (S.hp_round != now() - 1)
		return false;
	if ((!T.engaged || W.me.frac() >= 0.8f))
		return false; // only a body on a camp fight, already hurt
	for (const auto& e : W.enemies)
		if (cheb(e.pos, W.me.pos) <= 8)
			return false;
	bool hid = false;
	static std::vector<int> att;
	static vec2 att_p{ -1, -1 };
	static std::size_t att_n = 0;
	if (att_n != static_cast<std::size_t>(M.nc) || !(att_p == W.me.pos))
	{
		att.clear();
		for (std::size_t ci = 0; ci < static_cast<std::size_t>(M.nc); ++ci)
		{
			const auto& c = M.camps[ci];
			if (c.attacks() && cheb(c.pos, W.me.pos) <= c.reach)
				att.push_back(static_cast<int>(ci));
		}
		att_n = static_cast<std::size_t>(M.nc);
		att_p = W.me.pos;
	}
	for (const int ci : att)
		if (!bbget(W.vis, M.camps[static_cast<std::size_t>(ci)].pos) && !(camp_known_dead(ci)))
		{
			hid = true;
			break;
		}
	if (!hid)
		return false;
	refresh_owned();
	cbl_pred = mv::camp_threat(W.me.pos) * (mu::on(mu::B_CTH) ? 1.0f : mu::on(mu::B_CAMP) ? mu::my_camp(mu::IN) : mu::rule(mu::own_fam(own.jungle, false, false), mu::CAMP, mu::IN));
	return loss > cbl_pred + 0.5f;
}
void sense()
{
	const float hp = W.me.hp;
	const float sh = W.me.kit->slot_shield >= 0 ? my_shield() : 0.0f;
	if (S.hp_round >= now() - 2 && !W.on_spawn)
	{
		const bool lost_hp = hp < S.hp - 0.5f;
		if (lost_hp && (unseen_camp_hit_check(S.hp - hp)))
		{
			bool foe = false;
			for (const auto& e : W.enemies)
				foe = foe || cheb(e.pos, W.me.pos) <= 8;
			if (!foe)
			{
				cbl_seen_until = now() + CBL_TAB[2];
				cbl_excess = S.hp - hp - cbl_pred;
			}
		}
		const bool lost_shield = S.shield > 0.5f && sh > 0.5f && sh < S.shield - 0.5f;
		if (lost_hp || lost_shield)
		{
			S.hurt = now();
			bool explained = false;
			for (const auto& e : W.enemies)
				explained |= cheb(e.pos, W.me.pos) <= std::max(e.range, 4) + 1;
			for (const auto& vc : W.camps)
			{
				const auto& c = M.camps[static_cast<std::size_t>(vc.ci)];
				explained |= vc.awake && c.attacks() && cheb(c.pos, W.me.pos) <= c.reach;
			}
			if (!explained)
				S.hurt_unseen = now();
			else if (lost_hp && nova::econ::threat_checks::unexplained_hp_loss(S.hp - hp, now() - S.hp_round)) // more than the camps deal
			{
				S.hurt_unseen = now();
				nova::econ::threat_checks::cex_round = now();
			}
		}
	}
	S.hp = hp;
	S.shield = sh;
	S.hp_round = now();
	for (const auto& e : W.enemies)
	{
		const int dash = (e.kit && e.kit->slot_dash >= 0) ? 2 : 0;
		const int spell = (e.kit && (e.kit->slot_dmg >= 0 || e.kit->slot_aoe >= 0 || e.kit->slot_cc >= 0)) ? 4 : 0;
		if (cheb(e.pos, W.me.pos) <= std::max({ e.range, 1, spell }) + dash + 5)
			S.enemy_close = now();
	}
	if (S.recalling && !(W.me.state & ST_RECALL))
	{
		S.recalling = false;
		if (!W.on_spawn)
		{
			S.recall_cancel = now();
			S.cancel_pos = W.me.pos;
			NLOG("r%d slot %d recall cancelled hp %.0f\n", now(), P.my_slot, W.me.hp);
		}
	}
}
// Camp tiles near p that we cannot see (bushes, walls): unseen camps hit through both.
void hidden_camp_threats(vec2 p, std::vector<mv::Threat>& th)
{
	for (const auto& c : M.camps)
	{
		if (!c.attacks() || cheb(c.pos, p) > c.reach + 1 || bbget(W.vis, c.pos))
			continue;
		const auto& m = mem[static_cast<std::size_t>(c.group)];
		if ((m.status == GS_RESPAWN || m.status == GS_CLEARED))
			continue;
		th.push_back({ c.pos, c.reach });
	}
}
// Everything that could damage us during a recall channel: awake camps in reach (+1), enemies that could walk
// or dash into reach, and unseen camps when something unseen hit us lately.
std::vector<mv::Threat> recall_threats()
{
	std::vector<mv::Threat> th;
	for (const auto& vc : W.camps)
	{
		const auto& c = M.camps[static_cast<std::size_t>(vc.ci)];
		if (vc.awake && c.attacks() && cheb(c.pos, W.me.pos) <= c.reach + 2)
			th.push_back({ c.pos, c.reach + 1 });
	}
	for (const auto& e : W.enemies)
	{
		const int dash = (e.kit && e.kit->slot_dash >= 0) ? 2 : 0;
		const int spell = (e.kit && (e.kit->slot_dmg >= 0 || e.kit->slot_aoe >= 0 || e.kit->slot_cc >= 0)) ? 4 : 0;
		if (cheb(e.pos, W.me.pos) <= 12)
			th.push_back({ e.pos, std::max({ e.range, 1, spell }) + dash + 1 });
	}
	if (now() - S.hurt_unseen <= 8)
		hidden_camp_threats(W.me.pos, th);
	return th;
}
// one leg of a route for me: the group's value (contest-discounted) and my solo clear time, with the altar detour of its gems. False
// when I cannot take it alone (or it is unreachable, worthless or failing).
bool route_leg_eval(int gi, float* value, float* clear_t)
{
	if (gi < 0 || gi >= M.ng || my_slot() < 0)
		return false;
	const auto& g = M.groups[static_cast<std::size_t>(gi)];
	const auto& m = mem[static_cast<std::size_t>(gi)];
	if (g.access != ACC_WALK || (g.gems == 0 && g.gold == 0) || m.fail_until > now())
		return false;
	build_team(false);
	Claims none;
	none.fill(-1);
	const ClearEst e = estimate_cx(8, g, m, crew_for(gi, my_slot(), 0, none));
	if (!e.feasible)
		return false;
	float v = group_value(g, gi, my_slot());
	if (g.contest > 0.55f)
		v *= 1.0f - 0.35f * (g.contest - 0.55f) / 0.45f;
	if (now() - m.enemy_seen < 25)
		v *= 0.6f;
	const float altar_d = altar_walk(g);
	*value = v;
	*clear_t = e.t + (g.gems > 0 ? 0.25f * altar_d : 0.0f);
	return true;
}
} // namespace
// my near-cleared big target survives a flee's blacklist for NCK_ROUNDS rounds from the first such flee.
static bool keep_near_cleared_target(int gi)
{
	if (gi != T.target || gi < 0 || gi >= static_cast<int>(gmem_size(mem)) || gi >= M.ng)
		return false;
	const auto& g = M.groups[static_cast<std::size_t>(gi)];
	if (g.gems < NCK_GEMS)
		return false;
	const auto& m = mem[static_cast<std::size_t>(gi)];
	const bool near_clear = m.status == GS_CLEARED ||
		(m.status == GS_ALIVE && m.hp_left >= 0.0f && m.hp_left * 100.0f <= static_cast<float>(NCK_LEFT_PCT) * g.hp);
	if (!near_clear)
		return false;
	static int nck_gi = -1, nck_from = -1000, nck_last = -1000;
	if (nck_gi != gi || now() - nck_last > 10)
	{
		nck_gi = gi;
		nck_from = now();
	}
	nck_last = now();
	return now() - nck_from <= NCK_ROUNDS;
}
// threat_seen in DOM mode.
template <bool DOM>
void threat_seen_t(const std::vector<vec2>& foes)
{
	if (foes.empty() || gmem_size(mem) != static_cast<std::size_t>(M.ng))
		return;
	for (std::size_t gi = 0; gi < static_cast<std::size_t>(M.ng); ++gi)
	{
		const vec2 an = M.groups[gi].anchor;
		bool near = false;
		for (const vec2 f : foes)
		{
			const int c = cheb(f, an);
			if (c <= 5) // not across a wall
				near = true;
		}
		if (!near || zc::keep_group(static_cast<int>(gi))) // the crew keeps its zone (the team yields together)
			continue;
		if (keep_near_cleared_target(static_cast<int>(gi)))
			continue;
		// We just retreated from enemies here: farm elsewhere for a while instead of walking back into them. Remember what this blacklist
		// replaced (the first of a run of flee turns), so a kill can undo it.
		if ((DOM ? mem[gi].thr_round < now() - 15 : mem[gi].thr_until < now()) || mem[gi].fail_until > mem[gi].thr_until)
		{
			mem[gi].thr_prev_fail = mem[gi].fail_until;
			mem[gi].thr_prev_seen = mem[gi].enemy_seen;
		}
		mem[gi].enemy_seen = now();
		// chased here again after an earlier, separate flee episode: stay away longer
		const bool dch = DOM && dc_is(static_cast<int>(gi)) && !dom_commit_contested(static_cast<int>(gi)); // hold D
		mem[gi].fail_until = std::max(mem[gi].fail_until, now() + (DOM ? (dch ? DC_HOLD : 15) : TS_BL));
		if (static_cast<int>(gi) == T.target && !T.capturing && !dch)
			drop_target(20);
		mem[gi].thr_round = now();
		mem[gi].thr_until = mem[gi].fail_until;
	}
}
// An enemy body died at `at` and no other living enemy is known within 8. A body within 10 that is free (not capturing, not tanking,
// not carrying 30+) re-chooses its target now, with the groups within 5 of the kill freed of their enemy marks and worth x1.3 for 20
// rounds (rate_for). Returns the number of groups marked.
int mark_groups_near_kill(vec2 at)
{
	if (gmem_size(mem) != static_cast<std::size_t>(M.ng) || T.capturing || engaged_now() || W.me.gems >= 30 || cheb(W.me.pos, at) > 10)
		return 0;
	int n = 0;
	for (std::size_t gi = 0; gi < static_cast<std::size_t>(M.ng); ++gi)
	{
		const auto& g = M.groups[gi];
		if (cheb(g.anchor, at) > 5 || g.access != ACC_WALK || (g.gems == 0 && g.gold == 0))
			continue;
		auto& m = mem[gi];
		if (now() - m.enemy_seen < (static_cast<int>(ES_TAB[4])))
			m.enemy_seen = -1000;
		m.kill_round = now();
		++n;
	}
	if (n > 0)
		T.eval_round = -1000;
	return n;
}
void threat_seen(const std::vector<vec2>& foes)
{
	threat_seen_t<false>(foes);
}
void threat_seen_dom(const std::vector<vec2>& foes)
{
	threat_seen_t<true>(foes);
}
// The foe that caused a flee here died and no other living enemy is known near: the groups within 5 of where it died get back the
// fail_until / enemy_seen they had before threat_seen (unless something else set them since). Returns the number of groups lifted.
int lift_flee_blacklist(vec2 at)
{
	if (gmem_size(mem) != static_cast<std::size_t>(M.ng))
		return 0;
	int n = 0;
	for (std::size_t gi = 0; gi < static_cast<std::size_t>(M.ng); ++gi)
	{
		auto& m = mem[gi];
		if (m.thr_round < now() - 25 || cheb(M.groups[gi].anchor, at) > 5)
			continue;
		bool any = false;
		if (m.fail_until > now() && m.fail_until <= m.thr_until)
		{
			m.fail_until = std::min(m.fail_until, m.thr_prev_fail);
			any = true;
		}
		if (m.enemy_seen == m.thr_round)
		{
			m.enemy_seen = m.thr_prev_seen;
			any = true;
		}
		m.thr_round = -1000;
		n += any ? 1 : 0;
	}
	return n;
}
} // namespace nova::econ

// camp-excess damage and low-HP flee zones. Reached only when the BUGD bits are set at the hook.
namespace nova::econ::threat_checks
{
bool unexplained_hp_loss(float loss, int rounds)
{
	for (const auto& e : W.enemies)
		if (cheb(e.pos, W.me.pos) <= std::max(e.range, 4) + 1)
			return false; // a visible foe explains it (sense's own test)
	float cap = 0.0f;
	for (const auto& vc : W.camps)
	{
		const auto& c = M.camps[static_cast<std::size_t>(vc.ci)];
		if (vc.awake && c.attacks() && cheb(c.pos, W.me.pos) <= c.reach)
			cap += c.str; // a camp hits once a round, at most its strength (Jungle / Durability only lower it)
	}
	return cap > 0.0f && loss > 1.05f * cap * static_cast<float>(std::max(1, rounds)) + 1.0f;
}
// add the foe reaches with the flee zones' widening bits (bit 4: a mate-reported foe's veto reach; bit 1: two foe turns before my
// next widen the zone by its walk, foe_two_turn_reach).
void low_hp_flee_zones(const ::nova::combat::Assessment& a, std::vector<::nova::mv::Threat>& z)
{
	for (const auto& f : a.foes)
	{
		int r = f.reach;
		if (r < 0 && f.veto_reach >= 0)
			r = f.veto_reach;
		if (r >= 0)
			r = std::max(r, ::nova::combat::geom::foe_two_turn_reach(f, nullptr));
		if (r >= 0)
			z.push_back({ f.pos, r });
	}
}
} // namespace nova::econ::threat_checks
