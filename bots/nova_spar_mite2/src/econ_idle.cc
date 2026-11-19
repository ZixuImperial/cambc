// econ_idle.cc: Idle moves, side scouts, camp-out and capture pay-in.
#include "econ_internal.h"
namespace nova::econ {
int idle_group = -1;
int idle_since = -1000;
// Cached per group (terrain and camp tiles are static), filled in spare fuel after the turn (dead_end_cache_fill); unknown
// counts as open.
std::vector<signed char> dead_end_of;
// Leave an awake camp's reach before anything else. After a bail or a drop, without this the next turn would walk to the new target,
// recall or dither inside the reach it had just left. Threats: awake attacking camps (in sight, or remembered awake) of groups other
// than my target whose reach covers my tile, unless a mate claiming that group stands nearer to the camp (it holds it). Not
// mv::camp_threat's "I am the nearest" test: the camp's target changes as bodies move, and a body would stop escaping when another
// stood nearer for a round, farm a cluster in its reach and die. A body engaged on a group with attackers is left to the tank's and
// holders' bail tests; one on a cluster group escapes too. A capture that pays before the hits kill me holds. True if I moved. Spawn
// siege (chip, SS_TAB): groups whose strongest attacker reaches SS_MINSTR and that lie within 3 of a spawn tile (static, once).
static std::vector<int> ss_gs;
static bool mf2_ssg = false; // the spawn monolith group is the map's economy
static std::vector<int> ss_no_rally; // per ss_gs entry, no rally before this round (latch)
static std::vector<int> ss_gd; // v698 SSF2: per ss_gs entry, the nearest spawn tile's distance to a member (static, found once)
bool ss_pending = true, ss_live = false;
static float ss_kf = 6400.0f; // the rate bar in force
// The rate bar from the map score; map features only. Spawn rectangles from the bitboards once (the engine's spawn is one rectangle;
// <= 16 tiles): Chebyshev distance to a rectangle is O(1).
struct SskRect { int x0 = 1 << 20, y0 = 1 << 20, x1 = -(1 << 20), y1 = -(1 << 20), n = 0; };
// What a body earns elsewhere per round, in group_value's units (map supply, not my stale target rate): every other reachable group's reward over its respawn time, our half and the middle,
// shared by the team. Gold's weight falls late, so the siege's turn comes as my hits grow and gold stops mattering.
static float ss_sup_v = 0;
static int ss_sup_r = -1000;
static int rcg_cls = -1; // SPAWNECON map class, static, once
static SskRect rcg_ra;   // our spawn rectangle, once
// The cleared group whose region I stand on (any group, not only my target: a dash or area hit can clear a group in passing), and
// the round I stepped on it. The engine pays at the 6th round start after the step-on.
static int reg_gi = -1, reg_since = -1;
namespace {
template <int DM>
bool farm_turn()
{
	AF_CHECK();
	last_act = ACT_NONE;
	(void)0;
	if (M.groups.empty())
		return false;
	drop_stalled_target();
	const int rvc_t0 = T.target; // v699 R2V bit 1 RVC1C
	(void)rvc_t0;
	if (target_turn<DM>())
		return true;
	// The old target just ended (captured, handed over, dropped, or swapped for a filler): act on the next one now. Not after a costly
	// choice (the opening simulation can leave little fuel; a suspended turn is fatal).
	if (!W.moved && W.can_move() && fuel() > 30000) // v699 R2V bit 1 RVC1C: retry only when the target really ended
	{
		return target_turn<DM>();
	}
	return false;
}
} // namespace
bool farm() { return farm_turn<0>(); }
bool farm_dom() { return farm_turn<1>(); }
bool farm_hc2() { return farm_turn<2>(); }
bool farm_hc3() { return farm_turn<3>(); }
// Nothing to farm (every group is claimed, respawning or out of reach): an altar trip costs no farming time now, so tribute even a
// small bag, and commit to the trip so a respawn does not turn us back halfway.
bool idle_bank()
{
	const int gems = static_cast<int>(W.me.gems);
	return false;
}
// Standable tiles next to a group's members (capped at 3): 1-2 means a dead end in a 1-wide corridor.
int open_side_count(const GroupI& g)
{
	if (static_cast<std::size_t>(g.nm) > 4)
		return 3; // a big group is never a corridor dead end
	std::array<vec2, 3> seen{};
	int n = 0;
	const BView vb = bview(M.block_camps);
	for (const int ci : g.members)
#pragma clang loop unroll(full)
		for (const vec2 d : DIRS)
		{
			const vec2 q = M.camps[static_cast<std::size_t>(ci)].pos + d;
			if (!inb(q) || vb(q))
				continue;
			bool dup = false;
			for (int k = 0; k < n; ++k)
				dup |= seen[static_cast<std::size_t>(k)] == q;
			if (dup)
				continue;
			seen[static_cast<std::size_t>(n)] = q;
			if (++n >= 3)
				return n;
		}
	return n;
}
bool group_is_dead_end(int gi)
{
	return static_cast<std::size_t>(gi) < dead_end_of.size() && dead_end_of[static_cast<std::size_t>(gi)] == 1;
}
void build_bg()
{
	if (!build_ready && W.round > FARM_RICH_ROUNDS && fuel() > MB_FUEL)
		make_build();
}
// the first early-out test is inlined at the call site (this runs every turn); the rest is out of line
__attribute__((always_inline)) void dead_end_cache_fill(long reserve)
{
	if (M.any_altar || !M.gate_groups.empty() || !M.ready())
		return;
	dead_end_cache_fill_slow(reserve);
}
__attribute__((noinline)) void dead_end_cache_fill_slow(long reserve)
{
	// Only maps without a walkable altar (dashers bank, walkers stay out of the corridors) use these flags.
	if (M.any_altar || !M.gate_groups.empty() || !M.ready())
		return;
	if (dead_end_of.size() != static_cast<std::size_t>(M.ng))
		dead_end_of.assign(static_cast<std::size_t>(M.ng), -1);
	for (std::size_t gi = 0; gi < dead_end_of.size(); ++gi)
	{
		if (dead_end_of[gi] >= 0)
			continue;
		if (fuel() < reserve)
			return;
		dead_end_of[gi] = open_side_count(M.groups[gi]) <= 2 ? 1 : 0;
	}
}
// v70x PTH: the walk from me to group gi for an idle-walk choice: its cached group field (no build), never below the straight line;
// UNREACH when the fields say no walk exists; cheb when no field is built (live behaviour). Reusable for any cheb-for-walk test.
int pth_walk(int gi)
{
	const int ch = cheb(W.me.pos, M.groups[static_cast<std::size_t>(gi)].anchor);
	const int w = mv::group_walk_at(gi, W.me.pos);
	if (w == mv::FP_NOWALK)
		return UNREACH;
	return std::max(ch, w);
}
// PTH bit 4 (PTH's one adaptation, spec_pth_1110): group gi is far by walk: no walk, or the walk exceeds the straight line by more than 8.
void pth4_drop()
{
}
bool pth_far(int gi, int ch)
{
	const int w = pth_walk(gi);
	if (w != UNREACH && w <= ch + 8)
		return false;
	pth4_drop();
	return true;
}
void pth4_changed()
{
}
bool idle_move()
{
	if (T.target < 0)
	{
		if (ir_last < now() - 1)
			ir_start = now();
		ir_last = now();
	}
	if (walled_in() && !W.on_spawn && !T.capturing && (dpx_leave(nullptr) || (recall_safe() && start_recall()))) // v7xx DPX bit 1: the pocket exit
		return true; // nothing left to do inside the walled area: home
	if (WIC_ON(1) && wic_shut_in() && !W.on_spawn && !T.capturing && !W.me.channeling() && recall_safe() && start_recall())
		return true; // v711 WIC bit 1: shut in by a door no crew can clear: home
	// While the opening simulation runs it leaves ~30k: a path search on top would push the turn over ~85k, and the
	// body has no target to walk to yet.
	if (fuel() < (opened ? 16000 : 40000))
		return false;
	// no idle walk while the opening simulation is pending: the prestep walks (an idle approach would build a group field after the
	// prestep and suspend the turn, and it would leave the spawn, dropping the simulation).
	if (!opened && OP.started && (now() < 30)) // b1939 RSF bit 8
		return false;
	last_act = ACT_IDLE;
	if (fuel() < 30000)
		return false; // fuel guard (see farm)
	// Nothing left to farm on this island: recall home (no walk leads there), and bank from there. Not on a camp tile:
	// leave_respawn_tile steps off a captured group's tile first (no moves once recalling).
	if (stranded() && !T.capturing && !W.me.channeling() && !bbget(M.camp_tiles, W.me.pos) && (dpx_leave(nullptr) || (recall_safe() &&
		start_recall()))) // v7xx DPX bit 1
		return true;
	// Nothing to farm, and most such turns are "no feasible crew": no group fits this health. Heal at home now instead of standing in
	// the field, so the next choice finds groups again. Cheap paths only (a safe recall, or a step down the home field): go_home's
	// escape scan exhausted fuel here.
	if (T.target < 0 && !T.capturing && !W.on_spawn && W.me.frac() < COVER_IDLE_HP &&
		fuel() > 42000)
	{
		bool foe = false;
		for (const auto& e : W.enemies)
			foe |= cheb(e.pos, W.me.pos) <= 7;
		if (!foe)
		{
			if (home_dist() > 7 && recall_safe() && start_recall())
			{
				NLOG("r%d slot %d cover-heal recall hp %.0f\n", now(), P.my_slot, W.me.hp);
				return true;
			}
			const distance_field* hf = mv::home_field_cb();
			if (!hf && M.has_home)
				hf = &M.f_home;
			else if (hf && M.has_home && dfget_me(*hf) == UNREACH)
				hf = &M.f_home; // on a camp tile the camps-blocked field reads UNREACH (as home_field() does)
			if (hf && dfget_me(*hf) != UNREACH && dfget_me(*hf) > 0 && mv::step_field(*hf))
				return true;
		}
	}
	// Wait near the group that respawns soonest on our side (kept for a while), otherwise stay put.
	if (idle_group < 0 || now() - idle_since > (15)) // re-pick the idle group after 15 rounds
	{
		bool soi_skip_awake = false;
	soi_repick:
		int best = -1;
		int best_t = BIG;
		int pth_lb = -1, pth_lbt = BIG; // PTH bit 4: live's pick (the firing count)
		const bool idl_t1 = fuel() < 50000; // X2I bit 1 IDL1: below 50k reachable_target has no side effects (refreshes need 50-60k)
		for (std::size_t gi = 0; gi < static_cast<std::size_t>(M.ng); ++gi)
		{
			const auto& g = M.groups[gi];
			const auto& m = mem[gi];
			if (idl_t1) // X2I bit 1 IDL1: the walk time first; a group no nearer than the best cannot change the pick
			{
				int t1 = std::max(m.status == GS_RESPAWN ? m.respawn_at - now() : 0, cheb(W.me.pos, g.anchor));
				if (chipped_share(g, m) > 0)
					t1 -= TERR_IDLE;
				if (t1 >= best_t)
					continue;
			}
			if (g.access != ACC_WALK || g.contest > 0.6f || g.gems + g.gold == 0 || m.fail_until > now() ||
				!reachable_target(static_cast<int>(gi)))
				continue;
			// A walker that cannot bank gems keeps out of the dashers' way (1-wide corridors jam).
			if (!M.any_altar && g.gold == 0 && dash_only_bank() && !slot_dasher(P.my_slot) && team_dasher())
				continue;
			// A dead-end group (at most two open sides) that an ally handles: waiting there blocks it.
			if (group_is_dead_end(static_cast<int>(gi)) && claimants(static_cast<int>(gi)) > 0)
				continue;
			if (soi_skip_awake && group_awake(static_cast<int>(gi)))
				continue; // SOI bit 1 (row 852)
			const int cg = cheb(W.me.pos, g.anchor); // v70x PTH bit 1: by walk
			int t = std::max(m.status == GS_RESPAWN ? m.respawn_at - now() : 0, cg);
			if (chipped_share(g, m) > 0)
				t -= TERR_IDLE; // wait by a chipped group in our territory first
			if (t < pth_lbt)
			{
				pth_lbt = t;
				pth_lb = static_cast<int>(gi);
			}
			if (t < best_t && pth_far(static_cast<int>(gi), cg))
				continue; // PTH bit 4: far behind a wall by walk, or no walk at all
			if (t < best_t)
			{
				best_t = t;
				best = static_cast<int>(gi);
			}
		}
		if (pth_lb != best)
			pth4_changed();
		if (!soi_skip_awake && best >= 0 && group_awake(best))
		{
			soi_skip_awake = true; // SOI bit 1: the pick was awake
			goto soi_repick;
		}
		idle_group = best;
		idle_since = now();
	}
	// a group whose respawn we know: wait next to it (respawn clock).
	if (idle_group >= 0 && (cheb(W.me.pos, M.groups[static_cast<std::size_t>(idle_group)].anchor)) > 6) // v70x PTH bit 2: by walk
	{
		if (W.me.pos == b957_lr_pos && cheb(W.me.pos, M.groups[static_cast<std::size_t>(idle_group)].anchor) <= 7 && ((mfb_lr_gi == idle_group && mem[static_cast<std::size_t>(idle_group)].status == GS_RESPAWN && mem[static_cast<std::size_t>(idle_group)].respawn_at > now())))
			return false; // the step in would land back on the respawning tile just left
		return approach_group(idle_group);
	}
	// a healthy body with no target does not wait at the spawn: it waits at its idle group, just outside the camps' reach.
	return false;
}
bool busy_capturing() { return T.capturing; }
bool engaged_now() { return T.engaged && T.target >= 0 && group_awake(T.target); }
static SskRect spawn_bounding_rect(const bitboard& sp)
{
	SskRect r;
	bbforeach(sp, [&](vec2 p) { r.x0 = std::min(r.x0, p.x); r.y0 = std::min(r.y0, p.y); r.x1 = std::max(r.x1, p.x); r.y1 = std::max(r.y1, p.y); ++r.n; });
	return r;
}
static int spawn_rect_distance(vec2 p, const SskRect& r)
{
	return std::max(std::max(0, std::max(r.x0 - p.x, p.x - r.x1)), std::max(0, std::max(r.y0 - p.y, p.y - r.y1)));
}
void spawn_siege_find_groups()
{
	ss_pending = false;
	for (int gi = 0; gi < M.ng; ++gi)
	{
		const auto& g = M.groups[static_cast<std::size_t>(gi)];
		if (g.n_att == 0 || g.gems + g.gold == 0 || g.str_max < static_cast<float>(SS_TAB[4]))
			continue;
		bool near = false;
		for (int ci : g.members)
		{
			const vec2 p = M.camps[static_cast<std::size_t>(ci)].pos;
			for (int dx = -3; dx <= 3 && !near; ++dx)
				for (int dy = -3; dy <= 3 && !near; ++dy)
				{
					const vec2 q{ p.x + dx, p.y + dy };
					near = inb(q) && bbget(M.my_spawn, q);
				}
		}
		if (near)
		{
			ss_gs.push_back(gi);
			int gd = 99;
			for (int ci : g.members)
			{
				const vec2 p = M.camps[static_cast<std::size_t>(ci)].pos;
				for (int dx = -3; dx <= 3; ++dx)
					for (int dy = -3; dy <= 3; ++dy)
					{
						const vec2 q{ p.x + dx, p.y + dy };
						if (inb(q) && bbget(M.my_spawn, q))
							gd = std::min(gd, cheb(p, q));
					}
			}
			ss_gd.push_back(gd);
		}
	}
	ss_no_rally.assign(ss_gs.size(), 0);
	ss_live = !ss_gs.empty();
	ss_kf = static_cast<float>(SPM_TAB[2]);
	int mono = 0, other = 0, mg = -1;
	for (int gi : ss_gs)
		if (M.groups[static_cast<std::size_t>(gi)].n_mono > 0 && M.groups[static_cast<std::size_t>(gi)].gems > mono)
		{
			mono = M.groups[static_cast<std::size_t>(gi)].gems;
			mg = gi;
		}
	for (int gi = 0; gi < M.ng; ++gi)
		if (gi != mg)
		{
			const auto& g = M.groups[static_cast<std::size_t>(gi)];
			if (g.d_enemy < g.d_home)
			{
				other += g.gems; // SSGR bit 1 (revert SSG): the foe's half counts again
				continue;
			}
			other += g.gems;
		}
	mf2_ssg = mg >= 0 && 4 * other < mono;
}
// What I add to a clear per round: basic hits with the reset, spells on their cooldown.
static float spawn_siege_my_dps()
{
	const Kit& k = *W.me.kit;
	float d = W.me.str * (k.slot_reset >= 0 ? 1.125f : 1.0f);
	if (k.slot_dmg >= 0 && k.dmg_on_camps)
		d += k.dmg_mod * W.me.foc / static_cast<float>(rs::slot_cooldown());
	if (k.slot_aoe >= 0)
		d += k.aoe_mod * W.me.foc / static_cast<float>(rs::slot_cooldown());
	if (k.slot_cc >= 0 && k.cc_on_camps)
	{
		d += k.cc_mod * W.me.foc / static_cast<float>(rs::slot_cooldown()); // X65 bit 16 KH3: the stun's damage on camps
	}
	if (k.slot_dash >= 0 && k.dash_mod > 0)
	{
		d += k.dash_mod * W.me.foc / static_cast<float>(rs::slot_cooldown()); // X65 bit 16 KH3: the dash's damage
	}
	d *= mu::my_camp(mu::OUT);
	return std::max(1.0f, d);
}
static float spawn_siege_alternative_supply(int skip)
{
	if (now() - ss_sup_r < 25)
		return ss_sup_v;
	ss_sup_r = now();
	float sum = 0;
	for (int gi = 0; gi < M.ng; ++gi)
	{
		const auto& g = M.groups[static_cast<std::size_t>(gi)];
		if (gi == skip || g.access != ACC_WALK || g.d_home == UNREACH || g.contest > 0.6f || siege_group(g))
			continue;
		sum += group_value(g, gi, my_slot()) / std::max(20.0f, static_cast<float>(g.respawn));
	}
	ss_sup_v = sum / static_cast<float>(std::max(1, TM.n));
	return ss_sup_v;
}
// true = commit to the spawn-siege group gi (pass the rate test), from current state only. Callers read RCG_TAB[1] first.
static float spawn_siege_kill_dps(const Kit* k, float str, float foc, const GroupI& g)
{
	if (k == nullptr)
		return 0;
	float d = str * (k->slot_reset >= 0 ? 1.125f : 1.0f);
	if (k->slot_dmg >= 0 && k->dmg_on_camps)
		d += k->dmg_mod * foc / static_cast<float>(rs::slot_cooldown());
	if (k->slot_aoe >= 0)
		d += k->aoe_mod * foc / static_cast<float>(rs::slot_cooldown());
	if (k->slot_cc >= 0 && k->cc_on_camps)
	{
		d += k->cc_mod * foc / static_cast<float>(rs::slot_cooldown()); // X65 bit 1 SSK1: the stun's damage on camps
	}
	if (k->slot_dash >= 0 && k->dash_mod > 0)
	{
		d += k->dash_mod * foc / static_cast<float>(rs::slot_cooldown()); // X65 bit 2 SSK1: the dash's damage
	}
	if (k->splash) // Varg: Str on the target's radius-1 neighbours
	{
		d += str * nova::econ::splash_geometry::adjacent_camp_mean(g);
		VSP_CNT(3, g.pack >= 2);
	}
	return std::max(1.0f, d);
}
// X65 bit 32 SSQ1: the clear rate from my spawn: mine plus the allies on our spawn with a camp of the group in reach (the commit sum).
static float x65_spawn_reach_dps(const GroupI& g)
{
	float R = spawn_siege_my_dps();
	for (const auto& al : W.allies)
	{
		if (!bbget(M.my_spawn, al.pos) || al.kit == nullptr)
			continue;
		bool reach = false;
		for (int ci : g.members)
			reach = reach || cheb(M.camps[static_cast<std::size_t>(ci)].pos, al.pos) <= al.range;
		if (reach)
			R += spawn_siege_kill_dps(al.kit, al.str, al.foc, g) * (mu::rule(mu::slot_fam(al.slot, now()), mu::CAMP, mu::OUT));
	}
	return std::max(1.0f, R);
}
static bool spawn_siege_commit_ok(int gi, const GroupI& g, float left)
{
	if (rcg_cls < 0)
	{
		rcg_cls = (map_class() & MCL_BIT_SPAWNECON) != 0 ? 1 : 0;
		rcg_ra = spawn_bounding_rect(M.my_spawn);
	}
	if (rcg_cls == 0)
		return false;
	const float hf = static_cast<float>(RCG_TAB[4]) / 100.0f;
	const bool heal_me = W.on_spawn && W.me.frac() < hf;
	if (heal_me)
		return true; // on spawn healing anyway
	float R = spawn_siege_kill_dps(W.me.kit, W.me.str, W.me.foc, g) * (mu::my_camp(mu::OUT));
	int paid = 1; // me (heal_me returned above)
	for (const auto& al : W.allies)
	{
		if (!bbget(M.my_spawn, al.pos) || al.kit == nullptr)
			continue;
		bool reach = false;
		for (int ci : g.members)
			reach = reach || cheb(M.camps[static_cast<std::size_t>(ci)].pos, al.pos) <= al.range;
		if (!reach)
			continue;
		R += spawn_siege_kill_dps(al.kit, al.str, al.foc, g) * (mu::rule(mu::slot_fam(al.slot, now()), mu::CAMP, mu::OUT));
		paid += al.frac() >= hf ? 1 : 0;
	}
	if (R < static_cast<float>(RCG_TAB[2]))
		return false;
	const float T = std::max(1.0f, left) / R;
	if (T > static_cast<float>(RCG_TAB[3]))
		return false;
	if (group_value(g, gi, my_slot()) <= static_cast<float>(paid) * spawn_siege_alternative_supply(gi) * T)
		return false;
	const SskRect& ra = rcg_ra;
	bool touch = false;
	for (int ci : g.members)
		touch = touch || spawn_rect_distance(M.camps[static_cast<std::size_t>(ci)].pos, ra) <= 1;
	if (!touch)
	{
		float arr = 1e9f;
		const int age_max = RCG_TAB[5];
		for (const auto& e : intel::team_table())
		{
			if (!e.alive || e.pos.x < 0 || now() - e.round > age_max)
			{
				if (g.d_enemy != UNREACH) // v701 RGF1: a dead or stale foe can be back from its spawn (respawn after 60, GR:375)
					arr = std::min(arr, static_cast<float>(std::max(0, (e.alive ? 0 : std::max(0, intel::foe_died_round(e.h) + 60 - now())) + static_cast<int>(g.d_enemy) - 5)));
				continue;
			}
			int d = 99999;
			for (int ci : g.members)
				d = std::min(d, cheb(M.camps[static_cast<std::size_t>(ci)].pos, e.pos));
			arr = std::min(arr, static_cast<float>(std::max(0, d - 5 - (now() - e.round))));
		}
		if (T + static_cast<float>(RCG_TAB[6]) >= arr)
			return false;
	}
	return true;
}
bool spawn_siege_turn(bool flee)
{
	if (ss_gs.empty() || !opened || !W.me.kit || W.me.channeling() || gmem_size(mem) != static_cast<std::size_t>(M.ng) || capture_pay_in() >= 0)
		return false;
	for (std::size_t ssk = 0; ssk < ss_gs.size(); ++ssk)
	{
		const int gi = ss_gs[ssk];
		const auto& g = M.groups[static_cast<std::size_t>(gi)];
		const auto& m = mem[static_cast<std::size_t>(gi)];
		if (m.status != GS_ALIVE)
			ss_no_rally[ssk] = 0;
		if (m.status == GS_CLEARED)
		{
			// #104: a fleeing body, or one with a foe near, keeps to its own branch
			bool fn = flee;
			for (const auto& e : W.enemies)
				fn = fn || cheb(e.pos, W.me.pos) <= 9;
			if (fn)
				continue;
			// The reward: every body within 3 steps on (split bags channel shorter; the region must not stand empty, GameRules:194).
			int bd = 4;
			vec2 bt{ -1, -1 };
			for (int ci : g.members)
			{
				const vec2 p = M.camps[static_cast<std::size_t>(ci)].pos;
				const int d = cheb(p, W.me.pos);
				if (d < bd && mv::free_tile(p))
				{
					bd = d;
					bt = p;
				}
			}
			if (bt.x < 0 || !W.can_move() || !mv::step_to(bt, 0))
				continue;
			return true;
		}
		if (m.status != GS_ALIVE)
			continue;
		if (!W.on_spawn) // only from a spawn tile: off it there is no full heal (stepping off, hits add up, walking out under fire and back)
		{
			// Rally (bit 4; a 400-round siege with a body or two at home costs more than a short one with all): when my chip pays, go home
			// with no bag, calm, not mid-clear.
			if ((now() < ss_no_rally[ssk]) || T.engaged || T.capturing || (static_cast<int>(W.me.gems) >= SS_TAB[5] && !prism_layer::ss_bag_skip()) || !W.enemies.empty())
				continue;
			if (ss_gd[ssk] > W.me.range) // v698 SSF2: found once (spawn_siege_find_groups)
				continue; // no spawn tile of mine reaches it
			const float left = m.hp_left >= 0 ? m.hp_left : g.hp;
			if (!mf2_ssg && !(spawn_siege_commit_ok(gi, g, left)) && group_value(g, gi, my_slot()) * spawn_siege_my_dps() / std::max(1.0f, left) * 100.0f < spawn_siege_alternative_supply(gi) * ss_kf)
				continue;
			if ((bankable()) && static_cast<float>(now()) + left / x65_spawn_reach_dps(g) + 10.0f + (altar_walk(g)) > GAME_END_F)
				continue; // v701 SSR1: CHIP's game-end test
			if (recall_safe() && start_recall())
				return true;
			continue;
		}
		// Living camps seen, the strongest reach on me, and what they would do if I walked out.
		float hp_left = 0, wdmg = 0;
		int need = 0, near_d = 99, tgt = -1;
		float tgt_hp = 1e9f;
		bool awake = false;
		for (const auto& vc : W.camps)
		{
			const auto& c = M.camps[static_cast<std::size_t>(vc.ci)];
			if (c.group != gi)
				continue;
			hp_left += vc.hp;
			const int d = cheb(c.pos, W.me.pos);
			near_d = std::min(near_d, d);
			if (d <= W.me.range && vc.hp < tgt_hp)
			{
				tgt_hp = vc.hp;
				tgt = vc.ci;
			}
			if (vc.awake && c.attacks() && d <= c.reach)
			{
				awake = true;
				wdmg += c.str;
				need = std::max(need, c.reach + 1 - d);
			}
		}
		if (hp_left <= 0)
		{
			ss_no_rally[ssk] = now() + SS_TAB[6];
			continue;
		}
		// Pinned: walking out through the awake group kills me and no mate on the tiles holds it.
		bool pin = awake && static_cast<float>(need) * (wdmg * mu::my_camp(mu::IN)) >= W.me.hp;
		if (pin)
			for (const auto& al : W.allies)
				if (bbget(M.my_spawn, al.pos))
					for (int ci : g.members)
						if (cheb(M.camps[static_cast<std::size_t>(ci)].pos, al.pos) <= near_d)
							pin = false;
		if (!pin)
		{
			if (static_cast<int>(W.me.gems) >= SS_TAB[5] && !prism_layer::ss_bag_skip())
				continue;
			const float rate = group_value(g, gi, my_slot()) * spawn_siege_my_dps() / std::max(1.0f, hp_left);
			if (!mf2_ssg && !(spawn_siege_commit_ok(gi, g, hp_left)) && rate * 100.0f < spawn_siege_alternative_supply(gi) * ss_kf)
				continue;
			const float tot = x65_spawn_reach_dps(g); // X65 bit 32 SSQ1
			if ((bankable()) && static_cast<float>(now()) + hp_left / tot + 10.0f + (altar_walk(g)) > GAME_END_F)
				continue;
		}
		if (!combat::spawn_siege_is_safe(W.me.pos, gi))
		{
			ss_no_rally[ssk] = now() + SS_TAB[6];
			continue;
		}
		if (tgt < 0)
		{
			// No camp in my basic reach from here: an adjacent spawn tile that has one (a body with no such tile does not chip).
			if (!W.can_move())
				continue;
			int bs = 1 << 20;
			vec2 best{ -1, -1 };
			for (const vec2 dd : DIRS)
			{
				const vec2 n = W.me.pos + dd;
				if (!inb(n) || !bbget(M.my_spawn, n) || !mv::free_tile(n))
					continue;
				int dn = 99;
				for (const auto& vc : W.camps)
					if (M.camps[static_cast<std::size_t>(vc.ci)].group == gi)
						dn = std::min(dn, cheb(M.camps[static_cast<std::size_t>(vc.ci)].pos, n));
				if (dn > W.me.range)
					continue;
				if (dn < bs)
				{
					bs = dn;
					best = n;
				}
			}
			if (best.x < 0 || !combat::spawn_siege_is_safe(best, gi) || !mv::try_move(best))
			{
				ss_no_rally[ssk] = now() + SS_TAB[6];
				continue;
			}
			for (const auto& vc : W.camps)
				if (M.camps[static_cast<std::size_t>(vc.ci)].group == gi && cheb(M.camps[static_cast<std::size_t>(vc.ci)].pos, W.me.pos) <= W.me.range && vc.hp < tgt_hp)
				{
					tgt_hp = vc.hp;
					tgt = vc.ci;
				}
				if (tgt >= 0)
				combat::hit_camp(tgt);
			return true;
		}
		combat::hd_hold(true); // no landing dash off the tile
		combat::camp_abilities(tgt, false);
		combat::hit_camp(tgt);
		return true;
	}
	return false;
}
// camp_out's flee test at tile p (threats: mv::camp_threats_near(7) around me, memoised): an awake attacker reaches p, it is not my
// target's (nor the ring breach's), and no claimant mate (not channeling) stands nearer to it than p. Off while camp_out stands down
// (engaged on a group with attackers).
bool camp_reach_flee_tile(vec2 p)
{
	if (gmem_size(mem) != static_cast<std::size_t>(M.ng) || (T.engaged && T.target >= 0 && M.groups[static_cast<std::size_t>(T.target)].n_att > 0))
		return false;
	const auto z = mv::camp_threats_near(7);
	for (const auto& t : z)
	{
		const int d = cheb(t.pos, p);
		if (t.reach < 0 || d > t.reach)
			continue;
		const int ci = M.camp_index(t.pos);
		const int cg = ci >= 0 ? M.camps[static_cast<std::size_t>(ci)].group : -1;
		if (cg >= 0 && cg == T.target)
			continue;
		if (cg >= 0 && cg == ring_claim && ring_last >= now() - 1 && !ring_resting)
			continue;
		const bool held = camp_held(t, cg, d);
		if (!held && (ci >= 0 ? M.camps[static_cast<std::size_t>(ci)].str : 60.0f) > 0.0f)
			return true;
	}
	return false;
}
bool camp_out()
{
	AF_CHECK();
	if (!W.alive || !W.can_move() || W.me.channeling() || gmem_size(mem) != static_cast<std::size_t>(M.ng))
		return false;
	if (b957_gh_round >= now() - 1 && W.me.frac() >= 0.5f && mv::spawn_in_camp_reach())
		return false; // last turn's walk home into a spawn under awake reach goes on (the heal covers it)
	if (T.engaged && T.target >= 0 && M.groups[static_cast<std::size_t>(T.target)].n_att > 0)
		return false;
	const auto z = mv::camp_threats_near(7);
	if (z.empty())
		return false;
	float ct = 0;
	for (const auto& t : z)
	{
		const int d = cheb(t.pos, W.me.pos);
		if (t.reach < 0 || d > t.reach)
			continue;
		const int ci = M.camp_index(t.pos);
		const int cg = ci >= 0 ? M.camps[static_cast<std::size_t>(ci)].group : -1;
		if (cg >= 0 && cg == T.target)
			continue; // my target's own camps: target_turn's business (stage_near, the crew start, the bails)
		if (cg >= 0 && cg == ring_claim && ring_last >= now() - 1 && !ring_resting)
			continue; // the ring breach camps: ring_breach's business (it leaves on its own damage test)
		const bool held = camp_held(t, cg, d);
		if (!held)
			ct += ci >= 0 ? M.camps[static_cast<std::size_t>(ci)].str : 60.0f;
	}
	if (ct <= 0.0f)
		return false;
	const int pay = capture_pay_in();
	if (pay >= 0 && (ct * mu::my_camp(mu::IN)) * static_cast<float>(camp_hits_before_capture_pay(pay)) < W.me.hp - 0.15f * W.me.maxhp)
		return false; // the capture pays first
	if (!mv::escape(z))
		return false;
	TT_EV("cfesc", T.target, static_cast<int>(ct), static_cast<int>(W.me.frac() * 100.0f));
	cf_esc_round = now();
	if (T.engaged)
		drop_target(15); // a cluster group inside an awake reach: leave it for now
	last_act = ACT_WALK;
	(void)0;
	return true;
}
// the guard is on for EO_ROUNDS rounds after camp_out's escape, while my own target is not awake.
bool camp_escape_guard_on()
{
	if (now() - cf_esc_round > EO_ROUNDS || fuel() < EO_FUEL_MIN)
		return false; // like the neighbours' fuel gates, no avoid-set build (or detour search) on a short turn
	return !(T.target >= 0 && group_awake(T.target));
}
// the other camp escapes stamp the escape round as camp_out does.
void note_camp_escape() { cf_esc_round = now(); }
// Called by try_move only with the flag on. True = refuse the step onto dest: for EOX_ROUNDS rounds after a camp escape, dest is hit
// by an awake camp (nearest-champion test) and my tile is not, no visible foe within EOX_FOE, and the camp is not my own engaged
// awake target's (the tank's business).
bool keep_out_of_escaped_reach(vec2 dest)
{
	if (now() - cf_esc_round > EOX_ROUNDS)
		return false;
	for (const auto& e : W.enemies)
		if (cheb(e.pos, W.me.pos) <= EOX_FOE)
			return false;
	const int ig = (T.target >= 0 && T.engaged && group_awake(T.target)) ? T.target : -1;
	return mv::camp_threat(dest, ig) > 0.0f && mv::camp_threat(W.me.pos, ig) <= 0.0f;
}
__attribute__((always_inline)) int capture_pay_in()
{
	if (gmem_size(mem) != static_cast<std::size_t>(M.ng))
		return -1;
	// The tile -> camp index gives the region's group in O(1); a scan over every camp of every group on every turn cost enough fuel to
	// push bodies under the target-choice fuel floor on a camp-heavy map.
	int here = -1;
	if (!M.camp_at.empty())
	{
		const int ci = M.camp_index(W.me.pos);
		if (ci >= 0 && static_cast<std::size_t>(ci) < static_cast<std::size_t>(M.nc))
			here = M.camps[static_cast<std::size_t>(ci)].group;
	}
	if (here < 0 || mem[static_cast<std::size_t>(here)].status != GS_CLEARED || ring_gate_keep(here)) // no hold on the gap
	{
		reg_gi = -1;
		return -1;
	}
	if (here != reg_gi)
	{
		reg_gi = here;
		reg_since = now();
	}
	for (const auto& e : W.enemies)
		for (int ci : M.groups[static_cast<std::size_t>(here)].members)
			if (M.camps[static_cast<std::size_t>(ci)].pos == e.pos)
			{
				reg_since = now(); // contested: the timer restarts once they are gone
				return -1;
			}
	if (capture_contested_by_engine(here))
	{
		reg_since = now(); // an enemy out of my sight holds the region
		return -1;
	}
	int since = reg_since;
	if (T.capturing && T.target == here && T.cap_on >= 0)
		since = T.cap_on; // the engine-derived start; reg_since is the arrival
	const int k = since + (group_capture_pay_rounds(M.groups[static_cast<std::size_t>(here)], since)) - now(); // 2 rounds sooner for a Capture holder
	RSD(if (prism::has_family(rs::F_CAPTURE)) ++rsd::c[6];);
	if (k >= 1)
	{
		const int cps_k = engine_capture_countdown(here, std::max(1, k));
		if (cps_cps2_dead)
			return -1; // v7xx CPS2 (VBB bit 8, b1836/b1851): the engine reads the region paid or held by the enemy
		return cps_k;
	}
	return k < 0 ? -1 : std::max(1, k); // past due and unpaid: someone else holds it or it already paid; stop holding
}
bool home_round_trip_too_costly() // the trip home and back to my target costs more than 15 rounds over going on
{
	if (W.me.frac() < 0.8f || W.me.gems >= 10u || T.target < 0 || static_cast<std::size_t>(T.target) >= static_cast<std::size_t>(M.ng))
		return false;
	const distance_field* f = mv::group_field_ready(T.target);
	const int dh = static_cast<int>(M.groups[static_cast<std::size_t>(T.target)].d_home);
	const int dn = f ? static_cast<int>(dfget_me(*f)) : UNREACH;
	return f && dn != UNREACH && M.groups[static_cast<std::size_t>(T.target)].d_home != UNREACH && (csx_recall_t()) + dh - dn > 15; // v699 TBF bit 16 HRM1
}
// The camp rounds an escape weighs against a capture that pays in `pay` rounds (capture_pay_in). k is the engine's ally_capturing
// countdown when lower (paid at the start of round now + k); camps hit at each round start, so k hits come before my next turn after
// the payout (k - 1 before the payout itself with bit 8). Call only with bit 1 or 2 set and pay >= 0.
int camp_hits_before_capture_pay(int pay)
{
	int k = pay;
	const int ci = M.camp_at.empty() ? -1 : M.camp_index(W.me.pos);
	if (ci >= 0 && ci < M.nc)
	{
		const int gi = M.camps[static_cast<std::size_t>(ci)].group;
		cambc::detail::camp_group_capture_state cs{};
		if (gi >= 0 && gi < M.ng &&
			cambc::detail::sdk_camp_group_capture_state(M.groups[static_cast<std::size_t>(gi)].handle, &cs) == 0 && cs.state == 1 &&
			cs.timer >= 1 && static_cast<int>(cs.timer) < k)
			k = static_cast<int>(cs.timer); // camp_group_capture_type::ally_capturing
	}
	return k;
}
// The turn-end idle escape ("never end a turn idle where an awake camp will hit me") holds a capture under me that pays before the
// camp hits leave less than 15% of my health, at any health and whether or not it is my target. Otherwise a body would step off a
// group a round before it paid, one 80-HP camp hit to take.
bool idle_escape_holds_capture()
{
	const int pay = capture_pay_in();
	return pay >= 0 && mv::camp_threat(W.me.pos) * static_cast<float>(camp_hits_before_capture_pay(pay)) < W.me.hp - 0.15f * W.me.maxhp;
}
// ch unless the walk from p to group gi's camps is at least ch + FP_DETOUR (or none exists).
int field_point_dist(int gi, vec2 p, int ch)
{
	const int w = mv::group_walk_at(gi, p);
	if (w < 0 || w < ch + FP_DETOUR)
		return ch;
	return w;
}
int target_walk(vec2 p, vec2 at)
{
	const int d = cheb(p, at);
	return T.target >= 0 ? field_point_dist(T.target, p, d) : d;
}
int capture_region_dist(vec2 p)
{
	if (reg_gi < 0)
		return BIG;
	int best = BIG;
	for (int ci : M.groups[static_cast<std::size_t>(reg_gi)].members)
		best = std::min(best, cheb(M.camps[static_cast<std::size_t>(ci)].pos, p));
	return best;
}
bool hold_region()
{
	last_act = ACT_CAPTURE;
	(void)0;
	for (const auto& e : W.enemies)
		if (cheb(e.pos, W.me.pos) <= W.me.range && combat::attack_champion(e))
			break;
	return true;
}
// HVB bit 8 HV5: a member of group gi within r of me (the capture tiles are the members', not the anchor).
static bool hvb_near_member(int gi, int r)
{
	for (int ci : M.groups[static_cast<std::size_t>(gi)].members)
		if (cheb(W.me.pos, M.camps[static_cast<std::size_t>(ci)].pos) <= r)
			return true;
	return false;
}
bool about_to_capture()
{
	if (T.capturing)
		return true;
	if (T.target < 0)
		return false;
	const auto& m = mem[static_cast<std::size_t>(T.target)];
	if (m.status != GS_CLEARED)
		return false;
	return hvb_near_member(T.target, 4); // HVB HV5
}
} // namespace nova::econ
