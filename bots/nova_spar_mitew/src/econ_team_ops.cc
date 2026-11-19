// econ_team_ops.cc: Team siege operations (SG3).
#include "econ_internal.h"
namespace nova::econ {
namespace {
extern std::array<int, 8> des_r;
// my last SG3 bail (group, round, HP frac).
int sgr_gi = -1;
int sgr_round = -1000;
float sgr_frac = 0;
// my SG cooldown per group (failed or aborted operations), apart from the normal targets' fail_until: a failed crew call does not
// drop a 30+ gem farming group from my normal choice.
std::vector<int> sg_cool;
std::vector<int> sg_crew_seen; // per group, the round I last saw a crew call for it (event slot) or made one
std::vector<signed char> sg_crew_v; // per group, -1 not checked, 0 no, 1 a crew group (no body clears it alone at base stats)
int sg_next_eval = -1000; // next round this body may call
std::array<SgPw, 8> sg_ally{};
std::array<bool, 8> sg_alive_v{};
// Team stat ratio: mean power of our living bodies over theirs (cambc-4f's siegeread measure). 3 when none of theirs lives.
int sg_ratio_round = -1;
float sg_ratio_v = 1.0f;
// A slot's walk to group gi: from where I see it, else from the group it claims, else from our spawn (+30 when unseen and unclaimed:
// maybe dead); read from gi's walk field when built. des_pos: where and when I last saw each mate (econ::observe).
std::array<vec2, 8> des_pos{};
// The rally tile of big group gi: from its anchor, follow our spawn's walk field (f_home) downhill to the first tile that is not a
// camp tile, lies outside every attacker's reach but within 2 of the nearest one, and walks to the group (its field). Every body
// follows the same static fields to the same tile, so the crew gathers in one spot and sees itself (bodies staged around a walled
// monolith do not see each other and never count 3). A walk of at most ~16 steps: a whole-area scan cost 68k fuel (it suspended the
// turn).
std::vector<vec2> sg_rally_tiles;
// Not engaged near my operation's group: walk to its rally tile (far away the normal approach leads, recalls included).
// True if this turn's action is taken.
// The walk field to a big group's rally tile (camps blocked), built once per group in a turn that can afford it.
std::vector<std::unique_ptr<distance_field>> sg_rally_fields;
// inlined: the static answer is read 26k times a game; the first call computes it
NOVA_INLINE bool sg_any() { return sg_any_v >= 0 ? sg_any_v > 0 : any_big_group_slow(); }
__attribute__((always_inline)) bool sg_big(const GroupI& g) { return sg_any() && is_big_group_static(g); } // inlined: 15k calls a team-game
int sg_op_group() { return SGO.gi; }
void siege_note_bail(int gi)
{
	sgr_gi = gi;
	sgr_round = now();
	sgr_frac = W.me.frac();
}
// True while group gi is refused: bailed from it within SGR_ROUNDS and not healed a set margin above the bail HP.
bool siege_group_refused(int gi)
{
	return gi >= 0 && gi == sgr_gi && now() - sgr_round <= SGR_ROUNDS && W.me.frac() < sgr_frac + SGR_MARGIN_X100 * 0.01f;
}
int sg_cool_until(int gi) { return gi >= 0 && gi < static_cast<int>(sg_cool.size()) ? sg_cool[static_cast<std::size_t>(gi)] : -1000; }
bool siege_crew_call_seen(int gi)
{
	return false && gi >= 0 && gi < static_cast<int>(sg_crew_seen.size()) && sg_crew_seen[static_cast<std::size_t>(gi)] >= now() - SG_MEMO;
}
float siege_strength_growth(int r)
{
	const float f = 1.0f + 0.6f * std::min(1.6f, static_cast<float>(std::max(0, r)) / 700.0f);
	return std::sqrt((0.5f + 0.5f * f) * f);
}
float sg_pw(float maxhp, float str, float foc) { return std::sqrt(std::max(1.0f, maxhp) * std::max(1.0f, str + foc)); }
float siege_kit_power(int type)
{
	if (type < 0)
		return 300.0f;
	const Kit& k = kit_of(static_cast<cambc::champion_type>(type));
	return sg_pw(k.hp, k.str, k.foc);
}
float siege_power_now(const SgPw& x, int type)
{
	const int t = now();
	return x.seen > -1000 && x.pw > 0 ? x.pw * siege_strength_growth(t) / siege_strength_growth(x.seen) : siege_kit_power(type) * siege_strength_growth(t);
}
void siege_observe_foes()
{
	if (sg_nfoe < 0)
	{
		sg_nfoe = 0;
		for (const auto& r : roster(team::enemy))
			if (sg_nfoe < 8)
			{
				sg_foe[static_cast<std::size_t>(sg_nfoe)].h = r.h;
				sg_foe[static_cast<std::size_t>(sg_nfoe)].type = static_cast<int>(r.type);
				++sg_nfoe;
			}
	}
	for (const auto* lst : { &W.enemies, &W.enemies_far })
		for (const auto& e : *lst)
			for (int i = 0; i < sg_nfoe; ++i)
			{
				auto& f = sg_foe[static_cast<std::size_t>(i)];
				if (f.h == e.h && e.maxhp > 1.0f)
				{
					// e.foc keeps a Prism's gem Focus (SJB bit 8 not shipped)
					f.pw = sg_pw(e.maxhp, e.str, e.foc);
					f.seen = now();
					break; // roster handles are distinct, no later entry matches
				}
			}
	for (const auto& a : W.allies)
		if (a.slot >= 0 && a.slot < 8 && a.maxhp > 1.0f)
		{
			sg_ally[static_cast<std::size_t>(a.slot)].pw = sg_pw(a.maxhp, a.str, a.foc);
			sg_ally[static_cast<std::size_t>(a.slot)].seen = now();
		}
}
bool siege_ally_alive(int s)
{
	if (s == my_slot())
		return W.alive;
	if (s < 0 || s >= 8)
		return false;
	const auto ss = static_cast<std::size_t>(s);
	if (sg_alive_round[ss] != now()) // one host call per slot and round
	{
		std::int32_t al = 1;
		sg_alive_v[ss] = !(cambc::detail::sdk_champion_is_alive(P.handle[ss], &al) == 0 && al == 0);
		sg_alive_round[ss] = now();
	}
	return sg_alive_v[ss];
}
template <int DM>
float siege_power_ratio()
{
	if (sg_ratio_round == now())
		return sg_ratio_v;
	sg_ratio_round = now();
	float ours = 0, no = 0, theirs = 0, nt = 0;
	for (int s = 0; s < TM.n && s < 8; ++s)
	{
		if (!siege_ally_alive(s))
			continue;
		ours += s == my_slot() ? (sg_pw(W.me.maxhp, W.me.str, W.me.foc)) : siege_power_now(sg_ally[static_cast<std::size_t>(s)], static_cast<int>(P.type[static_cast<std::size_t>(s)]));
		no += 1.0f;
	}
	const int t = now();
	for (int i = 0; i < sg_nfoe; ++i)
	{
		const auto& f = sg_foe[static_cast<std::size_t>(i)];
		const int died = intel::foe_died_round(f.h);
		bool vb3_dead = died > -1000 && t - died < rs::champ_respawn_rounds();
		const bool vb3_old = vb3_dead;
		for (const auto& e : intel::team_table())
			if (e.h == f.h)
			{
				vb3_dead = !e.alive;
				break;
			}
		VB3_CNT(1, vb3_dead != vb3_old);
		if (vb3_dead)
			continue; // dead: back 60 rounds after its death
		theirs += siege_power_now(f, f.type);
		nt += 1.0f;
	}
	sg_ratio_v = no <= 0 ? 0.0f : (nt <= 0 ? 3.0f : (ours / no) / (theirs / nt));
	return sg_ratio_v;
}
// Enemies near a big group: distinct living enemies I (or my ward) saw within 8 of its anchor in the last `age` rounds, or
// the team's reports there, whichever is more.
int siege_enemies_near_group(int gi, int age)
{
	const vec2 an = M.groups[static_cast<std::size_t>(gi)].anchor;
	const int own = intel::count_near(an, 8, age);
	const float dz = intel::danger(an, 6, age);
	return std::max(own, static_cast<int>(dz + 0.5f));
}
void observe_unseen_mates()
{
	for (const auto& a : W.allies)
		if (a.slot >= 0 && a.slot < 8)
		{
			des_pos[static_cast<std::size_t>(a.slot)] = a.pos;
			des_r[static_cast<std::size_t>(a.slot)] = now();
			const auto ss = static_cast<std::size_t>(a.slot);
			if ((a.state & ST_RECALL) != 0)
			{
				rcm_rc[ss] = rcm_rcr[ss] == now() - 1 ? rcm_rc[ss] + 1 : (rcm_rcr[ss] == now() ? rcm_rc[ss] : 1);
				rcm_rcr[ss] = now();
			}
		}
}
// An unseen mate whose claim is gi itself: its walk from where I last saw it, less the rounds since (at least 1).
int unseen_mate_eta(int s, int gi, const GroupI& g)
{
	if (s < 0 || s >= 8 || now() - des_r[static_cast<std::size_t>(s)] > DES_STALE)
		return (g.d_home != UNREACH ? static_cast<int>(g.d_home) : 60) + 30;
	const vec2 p = des_pos[static_cast<std::size_t>(s)];
	int d = cheb(p, g.anchor) * 5 / 4 + 2;
	if (const distance_field* f = mv::group_field_ready(gi))
	{
		const std::uint16_t fd = dfget(*f, p);
		if (fd != UNREACH)
			d = static_cast<int>(fd);
	}
	return std::max(1, d - (now() - des_r[static_cast<std::size_t>(s)]));
}
int siege_slot_arrival_eta(int s, int gi)
{
	const auto& g = M.groups[static_cast<std::size_t>(gi)];
	vec2 p{ -1, -1 };
	if (s == my_slot())
		p = W.me.pos;
	int via_home = -1;
	const Body* b = p.x >= 0 ? nullptr : W.ally_by_slot(s);
	if (b)
		p = b->pos;
	else { if (p.x < 0 && s >= 0 && s < comms::CLAIM_SLOTS)
	{
		const int cg = comms::cgroup(s);
		if (cg == gi)
			return unseen_mate_eta(s, gi, g); // its own claim's anchor is gi: the field there reads 0
		if (cg >= 0 && cg < M.ng)
		{
			const auto& og = M.groups[static_cast<std::size_t>(cg)];
			p = og.anchor;
			if (og.d_home != UNREACH && g.d_home != UNREACH)
				via_home = static_cast<int>(og.d_home) + static_cast<int>(g.d_home);
		}
	} }
	if (p.x < 0)
		return (g.d_home != UNREACH ? static_cast<int>(g.d_home) : 60) + 30;
	if (const distance_field* f = mv::group_field_ready(gi))
	{
		const std::uint16_t d = dfget(*f, p);
		if (d != UNREACH)
			return static_cast<int>(d);
	}
	return via_home >= 0 ? via_home : cheb(p, g.anchor) * 5 / 4 + 2;
}
// Claim memory, every turn: a slot claiming a big group is in that operation; a slot claiming another group has left; a released
// claim (-1: banking, a recall, dead) keeps the last one for SG_MEMO rounds.
template <int DM>
void siege_track_claims()
{
	// the group count and my slot read once (nothing in the loop resizes them); the operation-target range test is the one above it, so
	// its body is spelled out: sg_big(g) || siege_crew_call_seen, same order (sg_any still first read there).
	const int ng = M.ng;
	const int me = my_slot();
	const int n = std::min(TM.n, 8);
	for (int s = 0; s < n; ++s)
	{
		const auto ss = static_cast<std::size_t>(s);
		const int c = s == me ? SGO.gi : TM.claim[ss];
		if (c >= 0 && c < ng && (sg_big(M.groups[static_cast<std::size_t>(c)]) || siege_crew_call_seen(c)))
		{
			sg_mgi[ss] = c;
			sg_mround[ss] = now();
		}
		else if (c >= 0 || s == me)
			sg_mgi[ss] = -1;
	}
}
bool siege_slot_in_operation(int s, int gi)
{
	return sg_mgi[static_cast<std::size_t>(s)] == gi && now() - sg_mround[static_cast<std::size_t>(s)] <= SG_MEMO && siege_ally_alive(s);
}
// Is a non-healer slot free for an operation on gi: alive, not engaged on another group (clearing or capturing), and not
// seen hurt (it heals first).
// HVB bit 32 HV4: each slot's last seen health and recall state (refreshed once a round from the mates in sight).
static std::array<std::uint8_t, 8> hvb_seen_ok{};
static bool hvb_slot_ok(int s)
{
	static int refreshed = -1;
	if (refreshed != now())
	{
		refreshed = now();
		for (const auto& al : W.allies)
			if (al.slot >= 0 && al.slot < 8)
				hvb_seen_ok[static_cast<std::size_t>(al.slot)] = (al.frac() >= SG_HP && (al.state & ST_RECALL) == 0) ? 1 : 0;
	}
	return s >= 0 && s < 8 && hvb_seen_ok[static_cast<std::size_t>(s)] != 0;
}
bool siege_slot_is_free(int s, int gi)
{
	if (!siege_ally_alive(s))
		return false;
	if (s == my_slot())
		return true;
	if (const Body* b = W.ally_by_slot(s))
	{
		if (s < 8)
			hvb_seen_ok[static_cast<std::size_t>(s)] = (b->frac() >= SG_HP && (b->state & ST_RECALL) == 0) ? 1 : 0; // HVB HV4
		if (b->frac() < SG_HP) // X65 bit 64 SRM1: a seen mate on a recall is not free
		{
			return false;
		}
	}
	else if (!hvb_slot_ok(s))
		return false; // HVB HV4: unseen, last seen hurt or recalling (or never seen healthy)
	return !(TM.busy[static_cast<std::size_t>(s)] && TM.claim[static_cast<std::size_t>(s)] != gi);
}
// The bodies free for a call on gi that can walk there within SG_ETA_MAX, their crew
// (best camp tank first) and the slowest walk.
int siege_free_crew(int gi, Crew& c, int& eta)
{
	int n = 0;
	eta = 0;
	for (int i = 0; i < TM.n; ++i)
	{
		const int s = TM.by_tank[static_cast<std::size_t>(i)];
		if (!siege_slot_is_free(s, gi))
			continue;
		const int e = siege_slot_arrival_eta(s, gi);
		if (e > SG_ETA_MAX)
			continue; // too far to arrive with the crew
		c.add(ECX_TM(static_cast<std::size_t>(s)));
		++n;
		eta = std::max(eta, e);
	}
	return n;
}
// Bodies committed to the operation on gi (claim memory): me and the allies in it.
int siege_committed_count(int gi)
{
	int n = SGO.gi == gi ? 1 : 0;
	for (int s = 0; s < TM.n && s < 8; ++s)
		if (s != my_slot() && siege_slot_in_operation(s, gi))
			++n;
	return n;
}
// The operation running now: the big group of the lowest slot in one (mine counts as my operation's group), or -1. The
// lowest slot wins, so two calls made in the same round resolve the same way on every body.
int siege_running_group()
{
	for (int s = 0; s < TM.n && s < 8; ++s)
	{
		const int c = s == my_slot() ? SGO.gi : ((now() - sg_mround[static_cast<std::size_t>(s)] <= SG_MEMO && siege_ally_alive(s)) ? sg_mgi[static_cast<std::size_t>(s)] : -1);
		if (c >= 0)
			return c;
	}
	return -1;
}
// The group is there to take: alive (or back before I can walk there) and not cleared by someone else.
bool siege_group_available(int gi, int walk)
{
	const auto& m = mem[static_cast<std::size_t>(gi)];
	if (m.status == GS_CLEARED)
		return false;
	return m.status != GS_RESPAWN || m.respawn_at <= now() + walk;
}
void siege_end(int cool, const char* why)
{
	const int gi = SGO.gi;
	if (gi < 0)
		return;
	(void)why;
	if (cool > 0)
	{
		if (sg_cool.size() != static_cast<std::size_t>(M.ng))
			sg_cool.assign(static_cast<std::size_t>(M.ng), -1000);
		sg_cool[static_cast<std::size_t>(gi)] = std::max(sg_cool[static_cast<std::size_t>(gi)], now() + cool); // V2m (review M3)
		sg_next_eval = std::max(sg_next_eval, now() + SG_RECALL_GAP); // no new call of my own right after a failed operation
	}
	if (SGO.arrive >= 0)
	{
		cw_sg_gi = gi; // the gather I waited through at gi
		cw_sg_end = now();
		cw_sg_arrive = SGO.arrive;
	}
	if (T.target == gi && !T.capturing)
		drop_target(0);
	SGO = SgOp{};
	sg_mgi[static_cast<std::size_t>(my_slot())] = -1;
}
void siege_take_group(int gi, bool caller, int walk, int crew_eta)
{
	set_target(gi, 1.0f, SG_K);
	SGO = SgOp{};
	SGO.gi = gi;
	SGO.since = now();
	SGO.caller = caller;
	SGO.deadline = now() + std::min(SG_GMAX, std::max(walk, crew_eta) + SG_SLACK);
	opened = true;
	sg_mgi[static_cast<std::size_t>(my_slot())] = gi;
	sg_mround[static_cast<std::size_t>(my_slot())] = now();
}
// a crew group: a static candidate that the team's best camp tank cannot clear alone at base stats (cached).
template <int DM>
bool siege_is_crew_group(int gi)
{
	if (sg_crew_v.size() != static_cast<std::size_t>(M.ng))
		sg_crew_v.assign(static_cast<std::size_t>(M.ng), -1);
	auto& v = sg_crew_v[static_cast<std::size_t>(gi)];
	if (v < 0)
	{
		const auto& g = M.groups[static_cast<std::size_t>(gi)];
		v = 0;
		if (big_group_crew_candidate(g))
		{
			int best = -1;
			for (int s = 0; s < P.n && s < 8; ++s)
				if ((best < 0 || P.tank_order[static_cast<std::size_t>(s)] < P.tank_order[static_cast<std::size_t>(best)]))
					best = s;
			if (best >= 0)
			{
				const Kit& k = kit_of(P.type[static_cast<std::size_t>(best)]);
				Crew c1;
				c1.add(member_of(k, k.str, k.foc, k.hp, k.hp, 1.0f, 1.0f));
				v = estimate_cx(2, g, GroupMem{}, c1).feasible ? 0 : 1;
			}
		}
	}
	return v > 0;
}
// The call gate for gi. *score: the operation's value per round.
template <int DM>
bool siege_start_gate(int gi, float* score)
{
	const auto& g = M.groups[static_cast<std::size_t>(gi)];
	const auto& m = mem[static_cast<std::size_t>(gi)];
	const bool crew_op = !sg_big(g); // a crew group (the caller checked siege_is_crew_group)
	if (m.fail_until > now() || sg_cool_until(gi) > now()) // V2m (review M3)
		return false;
	if (sg_ratio_round == now() && !(sg_ratio_v >= ((crew_op ? SG_CREW_SR : SG_SR))))
		return false; // v698 FSR: this round's ratio already fails the test below; skip the crew and clear estimates
	const int walk = siege_slot_arrival_eta(my_slot(), gi); // a built field or Chebyshev: no field is built for a gate check
	if (walk > SG_ETA_MAX || !siege_group_available(gi, walk))
		return false;
	const int near = siege_enemies_near_group(gi, 15);
	Crew c;
	int eta = 0;
	const int n = siege_free_crew(gi, c, eta);
	if (near > SG_NEAR_MAX || n < SG_K)
		return false;
	const ClearEst e = estimate_cx(2, g, m, c);
	const float sr = siege_power_ratio<DM>();
	const bool late = (bankable()) && now() + std::max(walk, eta) + static_cast<int>(e.t) + (g.d_altar != UNREACH ? static_cast<int>(g.d_altar) : 30) + 30 > GAME_END;
	const bool feas = g.n_att == 0 || (e.feasible && e.dmg <= SG_MARGIN_CALL * e.budget); // the crew arrives hurt, tanks bail early
	bool ok = near <= SG_NEAR_MAX && n >= SG_K && feas && e.t <= static_cast<float>(SG_TMAX) && !late && (sr >= ((crew_op ? SG_CREW_SR : SG_SR)));
	if (ok && crew_op && T.target >= 0 && T.rate > 0 && !(T.rate == 1.0f)) // v701 TMO SRP: not against set_target's 1.0 placeholder
	{
		// a crew group pays less than a boss: the crew's rate per body must stand up to what I am doing now.
		const float per_body = group_value(g, gi, my_slot()) / (static_cast<float>(std::max(1, n)) * std::max(1.0f, static_cast<float>(std::max(walk, eta)) + e.t + 10.0f));
		ok = per_body >= SG_CREW_RATE * T.rate;
	}
	if (!ok)
		return false;
	*score = group_value(g, gi, my_slot()) / std::max(1.0f, static_cast<float>(std::max(walk, eta)) + e.t + 10.0f);
	return true;
}
vec2 siege_rally_tile(int gi)
{
	if (sg_rally_tiles.size() != static_cast<std::size_t>(M.ng))
		sg_rally_tiles.assign(static_cast<std::size_t>(M.ng), vec2{ -2, -2 });
	auto& rt = sg_rally_tiles[static_cast<std::size_t>(gi)];
	if (rt.x != -2)
		return rt;
	const distance_field* gf = mv::group_field_raw(gi); // the group's walk field (other camps blocked): same on every body
	if (!gf || !M.has_home)
		return vec2{ -1, -1 }; // not built yet: stage_near this turn, the rally once the field exists
	const auto& g = M.groups[static_cast<std::size_t>(gi)];
	std::array<vec2, 16> ap{};
	std::array<int, 16> ar{};
	int na = 0;
	for (int ci : g.members)
	{
		const auto& c = M.camps[static_cast<std::size_t>(ci)];
		if (c.attacks() && na < 16)
		{
			ap[static_cast<std::size_t>(na)] = c.pos;
			ar[static_cast<std::size_t>(na)] = c.reach;
			++na;
		}
	}
	const FView fh = fview(M.f_home);
	vec2 p = g.anchor, best{ -1, -1 };
	for (int step = 0; step < 16; ++step)
	{
		vec2 nx = p;
		std::uint16_t nv = fh(p);
#pragma clang loop unroll(full) // unroll fully
		for (const vec2 d : DIRS)
		{
			const vec2 q = p + d;
			if (!M.passable(q))
				continue;
			const std::uint16_t v = fh(q);
			if (v < nv)
			{
				nv = v;
				nx = q;
			}
		}
		if (nx == p)
			break; // our spawn, or no way down
		p = nx;
		bool in_reach = false;
		int dmin = BIG;
		for (int i = 0; i < na; ++i)
		{
			const int dd = cheb(p, ap[static_cast<std::size_t>(i)]);
			in_reach |= dd <= ar[static_cast<std::size_t>(i)];
			dmin = std::min(dmin, dd - ar[static_cast<std::size_t>(i)]);
		}
		if (in_reach || bbget(M.camp_tiles, p))
			continue;
		if (dmin > 3)
			break; // walked past the band
		const std::uint16_t walk = dfget(*gf, p);
		if (dmin <= 2 && walk != UNREACH && static_cast<int>(walk) <= g.reach_max + 4)
		{
			best = p;
			break;
		}
	}
	rt = best;
	return rt;
}
// Present at the gather point of gi: me and the allies claiming gi within the group's reach + 4 of its anchor or 3 of its rally tile
// (healer counted only for the number). *c: their crew, best camp tank first. A slot out of my sight now counts if I saw it within
// UNSEEN_CLAIMANT_AGE rounds within rad of the anchor or 3 of the rally tile, and the engine says it is alive (a mate in a bush I'm not in).
static bool mate_recently_near_rally(int s, vec2 an, int rad, vec2 rp)
{
	if (s < 0 || s >= 8 || s == my_slot() || W.ally_by_slot(s))
		return false;
	const auto ss = static_cast<std::size_t>(s);
	if (now() - des_r[ss] > UNSEEN_CLAIMANT_TAB[2])
		return false;
	const vec2 p = des_pos[ss];
	if (cheb(p, an) > rad && (rp.x < 0 || cheb(p, rp) > 3))
		return false;
	return siege_ally_alive(s);
}
int siege_present_count(int gi, Crew& c)
{
	const auto& g = M.groups[static_cast<std::size_t>(gi)];
	const int rad = (g.reach_max > 0 ? g.reach_max : 1) + 4;
	const vec2 rp = siege_rally_tile(gi);
	std::array<bool, 8> in{};
	in[static_cast<std::size_t>(my_slot())] = true;
	int n = 1;
	for (const auto& a : W.allies)
	{
		if (a.slot < 0 || a.slot >= 8 || a.channeling() || (cheb(a.pos, g.anchor) > rad && (rp.x < 0 || cheb(a.pos, rp) > 3)))
			continue;
		if (!claims(a.slot, gi))
			continue;
		++n;
		in[static_cast<std::size_t>(a.slot)] = true;
	}
	for (int s = 0; s < TM.n && s < 8; ++s)
	{
		if (s == my_slot() || in[static_cast<std::size_t>(s)])
			continue;
		if (!claims(s, gi) || !mate_recently_near_rally(s, g.anchor, rad, rp))
			continue;
		++n;
		in[static_cast<std::size_t>(s)] = true;
	}
	for (int i = 0; i < TM.n; ++i)
	{
		const int s = TM.by_tank[static_cast<std::size_t>(i)];
		if (in[static_cast<std::size_t>(s)])
			c.add(ECX_TM(static_cast<std::size_t>(s)));
	}
	return n;
}
bool siege_crew_ready(int gi)
{
	const auto& g = M.groups[static_cast<std::size_t>(gi)];
	if (SGO.arrive < 0)
		SGO.arrive = now();
	if (siege_clear_started(gi))
		return true; // the crew is at it: join the clear
	Crew c;
	const int present = siege_present_count(gi, c);
	const int committed = siege_committed_count(gi);
	int sgs_eta = 0;
	if (present < committed)
	{
		// Committed mates still on their way (a join after a bank trip or a capture): wait for the slowest one that can make it, never
		// past SG_GMAX rounds from my own call or join.
		int eta = 0;
		for (int s = 0; s < TM.n; ++s)
			if (s != my_slot() && siege_slot_in_operation(s, gi))
			{
				const Body* b = W.ally_by_slot(s);
				if (!b || cheb(b->pos, g.anchor) > (g.reach_max > 0 ? g.reach_max : 1) + 4)
					eta = std::max(eta, siege_slot_arrival_eta(s, gi));
			}
		SGO.deadline = std::max(SGO.deadline, std::min(SGO.since + SG_GMAX, now() + eta + 5));
		sgs_eta = eta;
	}
	if (present < SG_K)
		return false;
	const ClearEst e = estimate_cx(2, g, mem[static_cast<std::size_t>(gi)], c);
	const bool feas = g.n_att == 0 || (e.feasible && e.dmg <= SG_MARGIN * e.budget);
	const bool ok = present >= SG_K && feas && (present >= committed - 1 || now() - SGO.arrive >= SG_LATE) && siege_enemies_near_group(gi, 4) < SG_ABORT_N;
	if (!feas && present >= SG_K && (present >= committed ? now() - SGO.arrive >= 3 : (present >= committed - 1 && now() - SGO.arrive >= 10 && !(sgs_eta > 0))))
		SGO.deadline = std::min(SGO.deadline, now()); // (nearly) the whole crew is here and cannot clear it: release everyone now (siege_turn)
	return ok;
}
// The operation has started: a committed mate is engaged on the group (its claim's engaged bit). Late members join the
// clear; nobody waits or leaves by the gather rules any more.
bool siege_clear_started(int gi)
{
	for (int s = 0; s < TM.n && s < 8; ++s)
		if (s != my_slot() && TM.claim[static_cast<std::size_t>(s)] == gi && TM.busy[static_cast<std::size_t>(s)])
			return true;
	return false;
}
const distance_field* siege_rally_walk_field(int gi, vec2 rp)
{
	if (sg_rally_fields.size() != static_cast<std::size_t>(M.ng))
		sg_rally_fields.resize(static_cast<std::size_t>(M.ng));
	auto& slot = sg_rally_fields[static_cast<std::size_t>(gi)];
	if (!slot)
	{
		if (fuel() < 3L * G.w * G.h + 3000 + 50000)
			return nullptr;
		bitboard goal;
		bbset(goal, rp);
		auto f = std::make_unique<distance_field>();
		bitboard visited;
		f->compute(M.block_camps & ~goal, goal, visited);
		slot = std::move(f);
	}
	return slot.get();
}
// at the arrival gate, a shortcut-short path_dist with a walk still past the bar and nothing to hit from here.
bool dasher_walk_past_bar(int gi, int bar)
{
	if (!dn::dasher() || !M.has_thin || !W.me.kit)
		return false;
	const distance_field* af = mv::group_field_ready(gi);
	if (!af)
		return false;
	const int wd = dfget_me(*af);
	if (wd == UNREACH || wd <= bar)
		return false;
	const int range = W.me.kit->ranged ? 3 : 1;
	for (int ci : M.groups[static_cast<std::size_t>(gi)].members)
	{
		const vec2 p = M.camps[static_cast<std::size_t>(ci)].pos;
		if (inb(p) && cheb(p, W.me.pos) <= range && bbget(W.vis, p) && bbget(W.occ_camps, p))
			return false;
	}
	return true;
}
static int ocr_rl_gi = -1, ocr_rl_r = -1000, ocr_rl_d = 0; // OCR bit 1: my last rally step (group, round, rally-field distance before it)
static bool ocr_rally_closer(int gi, vec2 rp)
{
	const distance_field* rf = siege_rally_walk_field(gi, rp);
	if (!rf)
		return false;
	const int d = dfget_me(*rf);
	return d != UNREACH && d < ocr_rl_d;
}
bool siege_walk_to_rally(int gi)
{
	const vec2 rp = siege_rally_tile(gi);
	if (rp.x < 0 || cheb(W.me.pos, rp) <= 1 || siege_clear_started(gi))
		return false; // no rally tile (yet), there already, or the clear is on: straight to the group
	const auto& g = M.groups[static_cast<std::size_t>(gi)];
	// v7xx OCR bit 1: last turn's rally step brought my rally-field distance down: keep walking (the group path bar flips 13/14 here)
	const bool ocr_latch = ocr_rl_gi == gi && ocr_rl_r == now() - 1 && ocr_rally_closer(gi, rp);
	if (!(ocr_latch) && path_dist(gi) > (g.reach_max > 0 ? g.reach_max : 1) + 8)
		return false;
	if (!(ocr_latch) && dasher_walk_past_bar(gi, (g.reach_max > 0 ? g.reach_max : 1) + 8))
		return false; // the walk is still long: stay on the approach, which holds the dash
	const distance_field* rf = siege_rally_walk_field(gi, rp);
	if (!rf || dfget_me(*rf) == UNREACH)
		return false; // no field this turn: the normal approach
	last_act = ACT_WALK;
	(void)0;
	const int ocr_d0 = dfget_me(*rf);
	if (!mv::step_field(*rf, gi))
		return false;
	ocr_rl_gi = gi;
	ocr_rl_r = now();
	ocr_rl_d = ocr_d0;
	return true;
}
bool siege_at_rally(int gi)
{
	const vec2 rp = siege_rally_tile(gi);
	return rp.x >= 0 && cheb(W.me.pos, rp) <= 1;
}
// no claimant or squad mate rally_present_count counts as away can reach this group within budget rounds.
bool no_mate_arrives_in_time(int gi, int budget)
{
	const auto& g = M.groups[static_cast<std::size_t>(gi)];
	const int rad = (g.reach_max > 0 ? g.reach_max : 1) + 4;
	const vec2 rp = siege_rally_tile(gi);
	const int mine = siege_slot_arrival_eta(my_slot(), gi);
	const unsigned sm = squad::outside(gi) ? squad::mates(my_slot()) : 0u;
	for (int s = 0; s < TM.n && s < 8; ++s)
	{
		if (s == my_slot())
			continue;
		const bool cl = claims(s, gi);
		const bool mate = !cl && (sm & (1u << s)) && squad::alive(s);
		if (!cl && !mate)
			continue;
		const Body* b = W.ally_by_slot(s);
		if (b && b->channeling())
		{
			continue; // a channeling body does not walk here (same rule as the none-in-time check)
		}
		if (b && (cheb(b->pos, g.anchor) <= rad + (mate ? SQ_LEASH : 0) || (rp.x >= 0 && cheb(b->pos, rp) <= 3)))
			continue; // here already
		if (cl && !b && mate_recently_near_rally(s, g.anchor, rad, rp))
			continue; // rally_present_count counts it here
		int eta = siege_slot_arrival_eta(s, gi);
		if (eta - mine <= budget)
			return false;
	}
	return true;
}
// end the rally gather now. Bit 2: the crew here can clear it (estimate feasible). Bit 4: the nearest away claimant is >= 2 rounds
// out and the attackers' hits until it arrives cost no more than a set percent of the crew-here budget.
bool end_rally_gather_now(int gi, const GroupI& g, const GroupMem& m, const Crew& rc)
{
	if (rc.n < 1)
		return false;
	const ClearEst e = estimate_cx(4, g, m, rc);
	if (e.feasible)
		return true;
	return false;
}
void rally_present_count(int gi, Crew& c, int* away)
{
	const auto& g = M.groups[static_cast<std::size_t>(gi)];
	const int rad = (g.reach_max > 0 ? g.reach_max : 1) + 4;
	const vec2 rp = siege_rally_tile(gi);
	std::array<bool, 8> in{};
	in[static_cast<std::size_t>(my_slot())] = true;
	*away = 0;
	for (int s = 0; s < TM.n && s < 8; ++s)
	{
		if (!claims(s, gi))
			continue; // me, other groups
		const Body* b = W.ally_by_slot(s);
		if (b && !b->channeling() && (cheb(b->pos, g.anchor) <= rad || (rp.x >= 0 && cheb(b->pos, rp) <= 3)))
			in[static_cast<std::size_t>(s)] = true;
		else if (!b && mate_recently_near_rally(s, g.anchor, rad, rp))
			in[static_cast<std::size_t>(s)] = true; // a claimant I just saw here and can't see now (bush) is here
		else
			++*away;
	}
	// Outside our own third, the squad mates bound for a group near mine (objective within SQ_LEASH: squad::mates, claims only, the
	// same on every body) gather on this rally tile too, so the squad enters together and no second wait runs. They are not crew of
	// this group (their own group is near): not in *c.
	if (squad::outside(gi))
	{
		const unsigned sm = squad::mates(my_slot());
		for (int s = 0; s < TM.n && s < 8; ++s)
		{
			if (!(sm & (1u << s)) || s == my_slot() || claims(s, gi) || !squad::alive(s))
				continue;
			// arrived in the area: within the group's reach + 4 + SQ_LEASH of my anchor (a mate gathering for its own pack nearby counts me
			// the same way, so two packs of one squad never wait on each other), or near my rally tile
			const Body* b = W.ally_by_slot(s);
			if (!b && mate_recently_near_rally(s, g.anchor, rad + SQ_LEASH, rp))
				continue; // RCFX SQR1: a squad mate I just saw in the area and can't see now (bush, wall) has arrived
			if (!(b && !b->channeling() && (cheb(b->pos, g.anchor) <= rad + SQ_LEASH || (rp.x >= 0 && cheb(b->pos, rp) <= 3))))
				++*away;
		}
	}
	for (int i = 0; i < TM.n; ++i)
	{
		const int s = TM.by_tank[static_cast<std::size_t>(i)];
		if (in[static_cast<std::size_t>(s)])
			c.add(ECX_TM(static_cast<std::size_t>(s)));
	}
}
// This body's operation step, at the start of the target turn. True: SG holds my target this turn (no re-evaluation).
template <int DM>
bool siege_turn()
{
	if (!sg_any() || !opened || !W.alive)
		return false;
	build_team(false);
	siege_track_claims<DM>();
	// My operation.
	if (SGO.gi >= 0)
	{
		const int gi = SGO.gi;
		if (T.target != gi)
		{
			SGO = SgOp{}; // dropped (a bail, a flee blacklist, no progress, the capture went to a mate): a fresh join decides
		}
		else if (T.capturing)
			return true;
		else
		{
			const int ne = siege_enemies_near_group(gi, 3);
			if (ne >= SG_ABORT_N)
			{
				if (T.engaged)
				{
					// Mid-clear: leave unless the crew here outnumbers them by two (abort mode 1); mode 0 always leaves.
					Crew c;
					if ((siege_present_count(gi, c) < ne + 2))
					{
						siege_end(SG_ABORT_COOL, "contested");
						return false;
					}
				}
				else
				{
					if (SGO.contested < 0)
						SGO.contested = now();
					if (now() - SGO.contested >= SG_CONTEST_WAIT)
					{
						siege_end(SG_ABORT_COOL, "contested");
						return false;
					}
				}
			}
			else
				SGO.contested = -1000;
			if (!T.engaged && finish_progress_mode() && !siege_clear_started(gi))
			{
				siege_end(SG_COOL, "fin9"); // a few gems from the win, an operation not started yet is dropped
				return false;
			}
			const int lead = siege_running_group();
			const bool started = T.engaged || siege_clear_started(gi);
			SGO.started_seen = started; // V2m (review M2): for the short-turn checks
			SGO.last_committed = siege_committed_count(gi);
			if (!started && lead >= 0 && lead != gi)
			{
				SGO = SgOp{}; // a lower slot called another big group: follow it (below)
			}
			else if (started)
				return true; // commit until the clear is done
			else if (now() > SGO.deadline)
			{
				siege_end(SG_COOL, "deadline");
				return false;
			}
			else { if (now() - SGO.since >= SG_COLLAPSE && SGO.last_committed < SG_K)
			{
				siege_end(SG_COOL, "collapse");
				return false;
			}
			else
				return true; }
		}
	}
	if (T.engaged || T.capturing)
		return false;
	if (W.me.frac() < SG_HP)
		return false;
	// Join a running operation.
	const int c = siege_running_group();
	if ((DM & 1) && c >= 0 && dc_is(T.target) && c != T.target)
		return false; // committed to D
	if (c >= 0 && siege_group_refused(c))
		return false; // bailed from this operation and not healed yet
	if (c >= 0 && T.target >= 0 && T.target != c && finish_progress_mode())
		return false; // a few gems from the win, I keep my own target
	if (c >= 0)
	{
		const auto& m = mem[static_cast<std::size_t>(c)];
		const int walk = siege_slot_arrival_eta(my_slot(), c); // a built field or Chebyshev: no field is built on the join turn
		if (m.fail_until <= now() && sg_cool_until(c) <= now() && siege_group_available(c, walk) && siege_enemies_near_group(c, 6) < SG_ABORT_N) // V2m (M3)
		{
			if (W.me.gems >= 40 && bankable())
			{
				const std::uint16_t sjb_bd = bank_dist_here(); // v67x SJB bit 1: the bank trip must fit the gather deadline
				const int sjb_x = sjb_bd != UNREACH ? 2 * static_cast<int>(sjb_bd) + 6 : 30;
				if (walk + sjb_x + SG_SLACK > SG_GMAX)
					return false;
			}
			int extra = 0;
			if (W.me.gems >= 40 && bankable())
			{
				// Bank the bag first (want_bank runs before the farm step), already committed: the claim memory keeps me in the
				// crew while the claim byte is released, and the deadline covers the trip.
				T.bank_until = std::max(T.bank_until, now() + 40);
				const std::uint16_t bd = bank_dist_here();
				extra = bd != UNREACH ? 2 * static_cast<int>(bd) + 6 : 30;
			}
			siege_take_group(c, false, walk + extra, 0);
			return true;
		}
		return false;
	}
	return false;
}
// A short turn (50k fuel or less) still runs the O(1) parts of the checks: the deadline, the collapse from the committed count of my
// last full check, a contest that has lasted SG_CONTEST_WAIT. True: SG holds my target this turn.
bool siege_cheap_hold()
{
	if (SGO.gi < 0 || T.target != SGO.gi)
		return false;
	if (T.capturing || T.engaged || SGO.started_seen)
		return true;
	if (now() > SGO.deadline)
	{
		siege_end(SG_COOL, "deadline");
		return false;
	}
	if (now() - SGO.since >= SG_COLLAPSE && SGO.last_committed >= 0 && SGO.last_committed < SG_K)
	{
		siege_end(SG_COOL, "collapse");
		return false;
	}
	if (SGO.contested >= 0 && now() - SGO.contested >= SG_CONTEST_WAIT)
	{
		siege_end(SG_ABORT_COOL, "contested");
		return false;
	}
	return true;
}
// v7xx MBB7 bit 4 CI2X2 (RC X483, callers read the flag): the bag a death risks; a C&I body's partner dies with it (GR:381), so the pair's.
static __attribute__((noinline)) int ci2x2_risk_bag()
{
	return CI2_FARM() ? nova::ci2::pair_bag() : static_cast<int>(W.me.gems);
}
// Call one (after refresh_target, on a turn with fuel to spare: the gate's estimates never squeeze the target choice). True
// if I called (my target is the big group now).
template <int DM>
bool siege_try_call()
{
	if (!sg_any() || !opened || !W.alive || SGO.gi >= 0 || T.engaged || T.capturing || W.me.frac() < SG_HP)
		return false;
	if ((DM & 1) && dc_is(T.target))
		return false; // committed to D
	if (now() < sg_next_eval || fuel() < 72000 || (ci2x2_risk_bag() >= 40) || siege_running_group() >= 0) // v7xx MBB7 CI2X2
		return false;
	if (T.target >= 0 && finish_progress_mode())
		return false; // a few gems from the win, no new operation while I have a target
	sg_next_eval = now() + SG_EVERY;
	// a fresh HELP call (type 4, 4 rounds) or a fresh post of types 6-7 (6 rounds) stands: no crew call this turn (crew calls go in the
	// same slot; boss calls are claims and go on).
	int best = -1;
	float best_s = 0;
	for (int gi = 0; gi < M.ng && fuel() > 60000; ++gi)
	{
		if (!sg_big(M.groups[static_cast<std::size_t>(gi)]) && (!siege_is_crew_group<DM>(gi)))
			continue;
		if (siege_group_refused(gi))
			continue; // no new call on the group I just bailed from
		float s = 0;
		if (siege_start_gate<DM>(gi, &s) && s > best_s)
		{
			best_s = s;
			best = gi;
		}
	}
	if (best < 0)
		return false;
	Crew cc;
	int eta = 0;
	siege_free_crew(best, cc, eta);
	if (!sg_big(M.groups[static_cast<std::size_t>(best)]))
	{
		// the call goes out in the event slot (a claim on a crew group may be a body's own choice); types 5-6 have no other writer and
		// intel, the HELP posts and the contest plan leave a fresh type 4-6 event standing for 4-6 rounds.
		if (best < 255)
			comms::write_event(best, SG_CALL_EV, now());
	}
	siege_take_group(best, true, siege_slot_arrival_eta(my_slot(), best), eta);
	return true;
}
} // namespace
} // namespace nova::econ

// calling, joining and peeling for first fights. Unity build: after the econ .cc files, whose file-local state (M, T) is in scope.
// Only reached when the first-fight bits are set at the hook.
#include "engage.h"
namespace nova::econ::fight_help
{
namespace
{
float last_vf = 0, last_vs = 0; // the two values of the last decision (diag copies read them)
}
// firing counters, firecount's DG at each function entry: a decision changed
void trip_call()
{
}
void trip_join()
{
}
void trip_decline()
{
}
void trip_peel()
{
}
bool fight_call(const combat::Assessment& a)
{
	if (!W.alive || a.stance != combat::FIGHT || a.ratio_near * 100.0f >= static_cast<float>(FHC_CALL_X100) || W.me.channeling())
		return false;
	if (!(a.in_reach || combat::took_damage(1)))
		return false;
	for (const auto& al : W.allies)
	{
		const int d = cheb(al.pos, W.me.pos);
		if (d <= 2 || d > EN_HELP_R || al.channeling() || al.frac() < 0.5f)
			continue;
		bool busy = false;
		for (const auto& f : a.foes)
			busy |= cheb(f.pos, al.pos) <= 4;
		if (!busy)
			return true;
	}
	return false;
}
bool join_worth(vec2 at)
{
	const int d = cheb(at, W.me.pos);
	if (d > FHC_JOIN_R || T.target < 0)
		return false;
	int n = 0, nf = 0;
	float hp = 0, g = 0;
	for (const auto& al : W.allies)
		if (cheb(al.pos, at) <= 5)
		{
			++n;
			hp += al.hp;
			g += static_cast<float>(al.gems);
		}
	if (n == 0) // the caller is out of my sight: one body of unknown health
	{
		n = 1;
		hp = 500.0f;
	}
	for (const auto& e : W.enemies)
		if (cheb(e.pos, at) <= 6)
		{
			++nf;
			g += static_cast<float>(e.gems);
		}
	nf = std::max(nf, n); // a HELP call means the caller is not winning
	const float lift = n + 1 > nf ? 1.0f : n + 1 == nf ? 0.6f : 0.3f;
	const float remain = hp / (150.0f * static_cast<float>(nf)); // turns the callers last
	const float vf = (static_cast<float>(n * FHC_BODY_G) + g) * lift * (static_cast<float>(std::max(0, d - 2)) <= remain ? 1.0f : 0.5f);
	const float vs = static_cast<float>(M.groups[static_cast<std::size_t>(T.target)].gems) * (about_to_capture() ? 1.0f : 0.5f) +
		mv::camp_threat(W.me.pos) * 0.2f; // two turns of camp hits at 10 HP a gem
	(void)0;
	(void)0;
	if (vf > vs)
	{
		trip_join();
		return true;
	}
	trip_decline();
	return false;
}
bool peel_vetoes_target(float worst)
{
	if (worst * 100.0f >= static_cast<float>(FHC_PEEL_X100) || !combat::took_damage(2))
		return false;
	trip_peel();
	return true;
}
} // namespace nova::econ::fight_help
