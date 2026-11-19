// econ_tank_support.cc: Tank and support play at the group.
#include "econ_internal.h"
namespace nova::econ {
namespace {
// A heavy-pack bail hands the camps to a healthy engaged mate instead of abandoning the group (the bail line fires at ~94% HP under
// 3 elks, and each bail drops the target for 25 rounds so the crew cascades). Awake camps hit the NEAREST champion in reach (tie:
// the one that acted first), which camp_threat models from the bodies' positions: step to (or stay on) a tile where the bail test
// passes there, ideally one I can hit from. hold: rotated last round, re-tested.
int tr_gi = -1, tr_last = -100;
// Crew mate: add damage without becoming a camp's target. True if acted. lf_*: consecutive support turns at one group that ended
// without a hit.
int lf_gi = -1, lf_n = 0, lf_last = -100;
// I am the tank: engage and hit the focus. True if acted. tank_attack_focus: no focus in my camp list (camps within 9 of me): walk to the
// nearest living member in sight (a ward sees it).
static bool tank_attack_focus(int gi)
{
	if (!W.can_move() || W.moved)
		return false;
	vec2 best{ -1, -1 };
	int bd = BIG;
	for (int ci : M.groups[static_cast<std::size_t>(gi)].members)
	{
		const vec2 p = M.camps[static_cast<std::size_t>(ci)].pos;
		if (!bbget(W.vis, p) || !bbget(W.occ_camps, p))
			continue;
		const int d = cheb(p, W.me.pos);
		if (d < bd)
		{
			bd = d;
			best = p;
		}
	}
	if (best.x < 0 || bd <= 1)
		return false;
	if (mv::step_to(best, 1, 40, gi))
		return true;
	// step_to's search reaches at most 40 tiles (10-20 on a short turn), so a living member seen by my ward farther away than that is
	// UNREACH and the turn would end empty every round. Step greedily toward it instead.
	return mv::step_greedy(best, gi);
}
bool rotate_camps_to_mate(int gi, float eff, bool hold)
{
	if (gi < 0 || gi >= M.ng || W.me.maxhp <= 0)
		return false;
	const vec2 me = W.me.pos;
	if (W.me.hp * 100.0f < static_cast<float>(TR_FLOOR_PCT) * W.me.maxhp)
		return false;
	for (const auto& e : W.enemies)
		if (cheb(e.pos, me) <= TR_ENEMY_R)
			return false;
	refresh_owned();
	const float jf = (mu::on(mu::B_CAMP) ? mu::my_camp(mu::IN) : mu::rule(mu::own_fam(own.jungle, false, false), mu::CAMP, mu::IN));
	// the awake attackers in sight, listed once (W.camps order) for the 10 tile scans and the mate test below; the same entries in the
	// same order, so the same threats and sums. Off: every scan walks W.camps.
	static const std::vector<FbAw> aw_none;
	const std::vector<FbAw>& aw = awake_attacking_camps();
	// The tile scan below only asks me and my 8 neighbours, so an attacker farther than reach + 1 from me reaches none of them: the
	// near list keeps the others in aw's order (same threats, same sums).
	static std::vector<FbAw> aw_near; // filled once the mate test passes
	const std::vector<FbAw>* awp = &aw;
	// Raw load of a tile: every awake attacker in reach of it, as if nobody else stood near (the walk-out if the mate leaves).
	auto raw_at = [&](vec2 t, std::vector<mv::Threat>& th)
	{
		float raw = 0;
		for (const auto& c : *awp)
			if (cheb(t, c.pos) <= c.reach)
			{
				th.push_back({ c.pos, c.reach });
				raw += c.str;
			}
		return raw * jf;
	};
	std::vector<mv::Threat> th0;
	const float raw0 = raw_at(me, th0);
	if (raw0 <= 0.0f)
		return false;
	bool mate = false;
	for (const auto& a : W.allies)
	{
		if (mate || !claims(a.slot, gi) || a.channeling() || cheb(a.pos, me) > TR_MATE_D)
			continue;
		if (a.frac() * 100.0f < static_cast<float>(TR_MATE_PCT) || a.hp < 3.0f * raw0 || !TM.busy[static_cast<std::size_t>(a.slot)])
			continue;
		for (const auto& c : aw)
			if (c.group == gi && cheb(a.pos, c.pos) <= c.reach)
			{
				mate = true;
				break;
			}
		continue;
	}
	if (!mate)
		return false;
	aw_near.clear();
	for (const auto& c : aw)
		if (cheb(me, c.pos) <= c.reach + 1)
			aw_near.push_back(c);
	awp = &aw_near;
	const auto& g = M.groups[static_cast<std::size_t>(gi)];
	const bool ranged = W.me.kit->ranged;
	const int focus = pick_focus(gi, me);
	// the members within range + 1 of me, in member order (hit_from asks only tiles within 1 of me, also after the move); the range
	// test runs before the camp-state call (both pure reads).
	static std::vector<int> mem_near;
	mem_near.clear();
	for (int ci : g.members)
		if (ci >= 0 && ci < M.nc && cheb(me, M.camps[static_cast<std::size_t>(ci)].pos) <= W.me.range + 1)
			mem_near.push_back(ci);
	auto hit_from = [&](vec2 t)
	{
		int best = -1;
		float bh = 1e30f;
		for (int ci : mem_near)
		{
			const VisCamp* vc = visible_camp(ci);
			if (!vc || cheb(t, M.camps[static_cast<std::size_t>(ci)].pos) > W.me.range || !camp_alive_now(ci))
				continue;
			const float h = (ci == focus ? -1e9f : 0.0f) + (M.camps[static_cast<std::size_t>(ci)].attacks() ? 0.0f : 1e6f) + vc->hp;
			if (h < bh)
			{
				bh = h;
				best = ci;
			}
		}
		return best;
	};
	vec2 bt = me;
	int bscore = -1, bci = -1;
	float binc = 1e30f;
	for (int dx = -1; dx <= 1; ++dx)
		for (int dy = -1; dy <= 1; ++dy)
		{
			const vec2 t{ me.x + dx, me.y + dy };
			const bool stay = dx == 0 && dy == 0;
			if (!stay && (!W.can_move() || !mv::free_tile(t)))
				continue;
			const float inc = mv::camp_threat(t) * jf;
			static std::vector<mv::Threat> th_keep; // one vector, cleared per tile
			std::vector<mv::Threat> th_own;
			std::vector<mv::Threat>& th = th_keep;
			th.clear();
			const float raw = raw_at(t, th);
			const int steps = mv::escape_steps(th, t);
			if (inc > 0.0f && eff < inc * (static_cast<float>(steps) + 1.5f) + 0.08f * W.me.maxhp)
				continue; // the bail test fails there too
			if (W.me.hp * 100.0f < static_cast<float>(TR_WALK_X100) * raw * static_cast<float>(steps))
				continue; // the walk-out if the mate leaves (it walks out too: part of the hits go to it)
			const int ci = (ranged && !stay) ? -1 : hit_from(t);
			if (hold && ci < 0)
				continue;
			const int score = (ci >= 0 ? 4 : 0) + (stay ? 2 : 0) + (inc <= 0.0f ? 1 : 0);
			if (score > bscore || (score == bscore && inc < binc))
			{
				bscore = score;
				binc = inc;
				bt = t;
				bci = ci;
			}
		}
	if (bscore < 0)
		return false;
	if (bt != me && !mv::try_move(bt))
		return false;
	NLOG("r%d slot %d TANK_ROTATE group %d hp %.0f hold %d to (%d,%d) inc %.0f hit %d\n", now(), P.my_slot, gi, W.me.hp, (int)hold, bt.x, bt.y, binc, bci);
	TT_EV("trot", gi, hold ? 1 : 0, static_cast<int>(W.me.frac() * 100.0f));
	tr_gi = gi;
	tr_last = now();
	last_act = ACT_CAMP;
	if (bci < 0 && !ranged)
		bci = hit_from(W.me.pos);
	if (bci >= 0)
	{
		combat::hit_camp(bci);
		combat::camp_abilities(bci, true);
	}
	return true;
}
float unseen_camp_threats(vec2 p, std::vector<mv::Threat>& out)
{
	const bool seen = now() <= cbl_seen_until;
	if (!seen)
		return 0.0f;
	std::vector<mv::Threat> hid;
	hidden_camp_threats(p, hid);
	refresh_owned();
	const float jf = (mu::on(mu::B_CAMP) ? mu::my_camp(mu::IN) : mu::rule(mu::own_fam(own.jungle, false, false), mu::CAMP, mu::IN));
	float add = 0.0f;
	for (const auto& t : hid)
	{
		const int d = cheb(t.pos, p);
		const int ci = M.camp_index(t.pos);
		if (d > t.reach || ci < 0 || mv::awake_known(ci))
			continue; // camp_threat already counts a remembered awake camp
		const auto& c = M.camps[static_cast<std::size_t>(ci)];
		if (!group_awake(c.group) || (0.85f * c.str * jf > cbl_excess + 1.0f))
			continue;
		int dmin = BIG, dtie = BIG; // the same nearest-body rule as camp_threat
		for (const auto* lst : { &W.allies, &W.enemies })
			for (const auto& b : *lst)
			{
				const int db = cheb(b.pos, c.pos);
				dmin = std::min(dmin, db);
				if (mv::takes_tie(b))
					dtie = std::min(dtie, db);
			}
		if (d > dmin || d == dtie)
			continue;
		out.push_back(t);
		add += c.str * jf;
	}
	if (add > 0.0f)
		cbl_priced_round = now();
	return add;
}
// A bail with unseen attackers priced: remember them as awake, so the next turns' camp_threat (camp_out, the walk) counts them too, as hidden_fire does.
void remember_unseen_attackers(const std::vector<mv::Threat>& th)
{
	if (cbl_priced_round != now())
		return;
	for (const auto& t : th)
		if (!bbget(W.vis, t.pos))
			mv::note_awake(M.camp_index(t.pos));
}
// The crew mates on group gi in reach of my attackers (th), each against its own bail bar (exit steps + 1.5 rounds of hits, + 8%,
// not winning alone). Bit 1 of the result: one fails it with every th attacker in its reach, i.e. once I am gone, so my walk-out
// takes th's whole strength. Bit 2: one can't hold its current share (attackers no farther from it than from me) until the crew
// kills th, so it leaves before the kill: its damage is gone and staying takes the whole strength too. *full gets th's strength
// (jungle counted); on bit 2, *dps drops those mates' damage.
static int crew_mates_in_reach(int gi, const std::vector<mv::Threat>& th, float hp_left, const Crew& crew, float* full, float* dps)
{
	int res = 0;
	float drop = 0;
	const vec2 me = W.me.pos;
	const float rtk = hp_left / std::max(30.0f, *dps); // the crew's kill time (my winning test's)
	for (const auto& a : W.allies)
	{
		if (!claims(a.slot, gi) || a.hp <= 0)
			continue;
		float inc = 0, inc_now = 0;
		int steps = 0;
		for (const auto& t : th)
		{
			const int d = cheb(a.pos, t.pos);
			if (d > t.reach)
				continue;
			const int ci = M.camp_index(t.pos);
			const float str = ci >= 0 ? M.camps[static_cast<std::size_t>(ci)].str : 0.0f;
			inc += str;
			if (d <= cheb(me, t.pos))
				inc_now += str;
			steps = std::max(steps, t.reach - d + 1);
		}
		if (inc <= 0)
			continue;
		const float mdps = std::max(30.0f, TM.m[static_cast<std::size_t>(a.slot)].dps1);
		const float keep = 0.08f * a.maxhp;
		auto fails = [&](float in)
		{
			const float eff = a.hp + std::min(a.shield, in * static_cast<float>(std::max(1, a.shield_turns)));
			return in > 0 && !(eff > in * (hp_left / mdps + 1.0f)) && eff < in * (static_cast<float>(steps) + 1.5f) + keep;
		};
		if (fails(inc))
			res |= 1;
		const float eff_now = a.hp + std::min(a.shield, inc_now * static_cast<float>(std::max(1, a.shield_turns)));
		if (inc_now > 0 && (eff_now < inc_now * (static_cast<float>(steps) + 1.5f) + keep)) // its own bail line; it can't hold its share until the crew kills th: it leaves before
		{
			res |= 2;
			drop += TM.m[static_cast<std::size_t>(a.slot)].dps1;
		}
	}
	if (res == 0)
		return 0;
	float f = 0;
	for (const auto& t : th)
	{
		const int ci = M.camp_index(t.pos);
		f += ci >= 0 ? M.camps[static_cast<std::size_t>(ci)].str : 0.0f;
	}
	refresh_owned();
	if (mu::on(mu::B_CAMP)) // Durability x Jungle
		f *= mu::my_camp(mu::IN);
	else if (own.jungle)
		f *= mu::rule(mu::own_fam(true, false, false), mu::CAMP, mu::IN);
	*full = f;
	if ((res & 2) && crew.dps1 > 0)
		*dps = std::max(30.0f, *dps * std::max(0.0f, 1.0f - drop / crew.dps1));
	return res;
}
// She holds more than this group would pay, and the Chebyshev read still lets her stand: price the true walk. The walk runs only
// once a turn while that walk could change the answer. True: steps was raised and the bail will fire on it.
static bool prism_exit_walk_longer(int gi, float eff, float incoming, const std::vector<mv::Threat>& th, int& steps)
{
	if (!prism_layer::px_longer_rule())
		return false;
	const GroupI& g = M.groups[static_cast<std::size_t>(gi)];
	if (static_cast<int>(W.me.gems) <= g.gems + g.gold / 10)
		return false;
	const float keep = 0.08f * W.me.maxhp;
	if (eff >= incoming * (static_cast<float>(PX_LIMIT) + 1.5f) + keep || eff < incoming * (static_cast<float>(steps) + 1.5f) + keep)
		return false;
	const int w = mv::safe_tile_walk_steps(th);
	if (w == 99 || w <= steps)
		return false;
	steps = w;
	return eff < incoming * (static_cast<float>(w) + 1.5f) + keep;
}
// VDH (common.h): a ranged dash kit (Vesper) farming with the dash ready, nothing done yet this turn, healthy and no foe threat
// dashes onto the best tile of `goals` within the dash (a cast, so the ranged attack allowance stays) and, with `hit`, hits `focus`
// the same turn.
static bool vesper_dash_approach(const bitboard& goals, int focus, int gi, bool hit)
{
	if (!W.me.kit || fuel() < 15000)
		return false;
	const Kit& k = *W.me.kit;
	if (!k.ranged || k.slot_dash < 0 || W.moved || W.attacked || W.cast || !W.can_attack() || !combat::ready(k.slot_dash))
		return false;
	if (W.me.frac() * 100.0f < static_cast<float>(VDH_TAB[2]))
		return false;
	const vec2 me = W.me.pos;
	for (const auto& e : W.enemies)
		if (cheb(e.pos, me) <= VDH_TAB[3])
			return false;
	if (combat::nearest_foe_distance_seen(8) <= VDH_TAB[4])
		return false;
	const int r = std::max(1, static_cast<int>(k.dash_range));
	const auto& mem = M.groups[static_cast<std::size_t>(gi)].members;
	vec2 best{ -1, -1 };
	int bs = -1;
	for (int dx = -r; dx <= r; ++dx)
		for (int dy = -r; dy <= r; ++dy)
		{
			const vec2 t{ me.x + dx, me.y + dy };
			if ((dx == 0 && dy == 0) || !inb(t) || !bbget(goals, t) || !mv::free_tile(t) || !combat::dash_legal_between(me, t))
				continue;
			int s = 0;
			for (int ci : mem)
				if (visible_camp(ci) && camp_alive_now(ci) && cheb(t, M.camps[static_cast<std::size_t>(ci)].pos) <= W.me.range)
					++s;
			s = s * 4 + (2 - std::min(2, cheb(t, me))); // more living members in range, then the shorter dash
			if (s > bs)
			{
				bs = s;
				best = t;
			}
		}
	if (best.x < 0 || !combat::cast_at(k.slot_dash, best))
		return false;
	if (hit)
		combat::hit_camp(focus);
	return true;
}
// the focus the tank should keep this turn, given the one picked from the camps in sight.
int fkh_ci = -1, fkh_gi = -1, fkh_r = -1000, fkh_seen = -1000;
static __attribute__((noinline)) int focus_hold(int gi, int focus, vec2 me)
{
	if (fkh_gi != gi || fkh_ci == focus || fkh_ci < 0 || fkh_r < now() - 1 || now() - fkh_seen > FKH_TAB[2])
		return focus;
	const auto& held = M.camps[static_cast<std::size_t>(fkh_ci)];
	const auto& pick = M.camps[static_cast<std::size_t>(focus)];
	if (visible_camp(fkh_ci) || !camp_alive_now(fkh_ci) || (pick.attacks() && !held.attacks()))
		return focus;
	const int reach = (held.attacks() && !W.me.kit->ranged) ? 1 : W.me.range;
	if (cheb(me, held.pos) <= reach || cheb(me, pick.pos) <= W.me.range)
		return focus;
	return fkh_ci;
}
static __attribute__((always_inline)) inline bool tank_bail_out(int gi, const Here& here, const vec2 me)
{
	std::vector<mv::Threat> th;
	float incoming = incoming_at(me, &th);
	incoming += unseen_camp_threats(me, th);
	if (T.engaged && incoming > 0)
	{
		mv::awake_mem_threats(me, th);
		float hp_left = 0;
		int steps = mv::escape_steps(th, me);
		float dps = threat_kill_dps(here.crew, th, &hp_left, true); // splash and retaliation count
		float walk_inc = incoming; // the walk-out's price
		float full = incoming;
		const int cm = crew_mates_in_reach(gi, th, hp_left, here.crew, &full, &dps);
		full = std::max(full, incoming);
		if (cm & 2)
			incoming = full;
		if (cm != 0)
		{
			NLOG("r%d slot %d cbx group %d cm %d inc %.0f full %.0f\n", now(), P.my_slot, gi, cm, walk_inc, full);
			walk_inc = full;
		}
		const float rounds_to_kill = hp_left / dps;
		// A shield runs out: it only absorbs the hits of the turns it has left.
		float eff = W.me.hp + std::min(W.me.shield, incoming * static_cast<float>(std::max(1, W.me.shield_turns)));
 // the healer behind me tops me up
		const bool winning = eff > incoming * (rounds_to_kill + 1.0f);
		bool harmless = false; // remains that deal <= EH_PCT % of my health a round, no enemy near: no bail
		if (incoming * 100.0f <= static_cast<float>(EH_PCT) * W.me.hp)
		{
			harmless = true;
			for (const auto& e : W.enemies)
				harmless = harmless && cheb(e.pos, me) > EH_ENEMY_R;
		}
		const bool px_far = !winning && !harmless && prism_exit_walk_longer(gi, eff, walk_inc, th, steps);
		if (!winning && !harmless && eff < walk_inc * (static_cast<float>(steps) + 1.5f) + 0.08f * W.me.maxhp && !(crew_bail::skip(gi, th, hp_left, dps, eff, steps)))
		{
			if (!(cbl_priced_round == now()) && rotate_camps_to_mate(gi, eff, false)) // rotate_camps_to_mate cannot see unseen attackers
				return true;
			remember_unseen_attackers(th);
			bool relief = false;
			for (const auto& a : W.allies)
				if (claims(a.slot, gi) && !a.kit->ranged && a.frac() > 0.5f && !a.channeling())
					for (const auto& t : th)
						relief |= cheb(a.pos, t.pos) <= 1;
			NLOG("r%d slot %d bail out of group %d hp %.0f steps %d relief %d\n", now(), P.my_slot, gi, W.me.hp, steps, (int)relief);
			if (relief)
				T.bench_until = now() + 12;
			else if (sg_op_group() == gi)
			{
				siege_note_bail(gi);
				drop_target(0); // no blacklist: healed, the tank rejoins the operation (siege_turn)
			}
			else
			{
				drop_target(25);
				bail_ban_remember(gi);
			}
			if (!(px_far && mv::escape_to_safe_tile(th)))
				mv::escape(th);
			return true;
		}
	}
	return false;
}
// Watches whether the walk to the focus makes progress; a focus the body cannot get closer to is blocked for a while and the
// nearest other visible member of the group takes its place.
static __attribute__((always_inline)) inline void tank_track_focus_progress(int gi, const vec2 me, int& focus)
{
	static int fr_focus = -1, fr_best = BIG, fr_n = 0, fr_block = -1, fr_until = -1;
	static int fr_last = -1000; // the last round this code ran
	static int fr_prev = -1, fr_flips = 0, fr_flip_r = -1000, fr_lock = -1, fr_lock_until = -1;
	if (focus == fr_block && now() < fr_until)
	{
		int alt = -1, ad = BIG;
		for (int ci : M.groups[static_cast<std::size_t>(gi)].members)
		{
			const int dc = cheb(me, M.camps[static_cast<std::size_t>(ci)].pos);
			if (ci != fr_block && visible_camp(ci) && dc < ad)
			{
				ad = dc;
				alt = ci;
			}
		}
		if (alt >= 0)
		{
			focus = alt;
			dbg_path = 13;
		}
	}
	const auto& fc = M.camps[static_cast<std::size_t>(focus)];
	const int d = cheb(me, fc.pos);
	const int in_r = (fc.attacks() && !W.me.kit->ranged) ? 1 : W.me.range;
	const bool fr_gap = now() - fr_last > 1;
	fr_last = now();
	if (focus != fr_focus || fr_gap) // back after an absence: progress counts from here
	{
		fr_prev = fr_focus;
		fr_focus = focus;
		fr_best = d;
		fr_n = 0;
	}
	else if (d < fr_best)
	{
		fr_best = d;
		fr_n = 0;
	}
	else if (d > in_r && d <= FR_NEAR && W.can_move() && ++fr_n >= FR_TURNS)
	{
		NLOG("r%d slot %d FOCUS_REACH block camp %d of group %d at %d\n", now(), P.my_slot, focus, gi, d);
		fr_block = focus;
		fr_until = now() + FR_BLOCK;
		fr_n = 0;
		fr_focus = -1;
	}
}
// Melee stands next to the focus; a ranged tank stops in basic range (walking would spend its attack).
static __attribute__((always_inline)) inline int tank_want_range(int ci)
{
	if (ci_layer::me_cassi())
		return nova::ci2::stand_r(); // CI2 decision 4
	return (M.camps[static_cast<std::size_t>(ci)].attacks() && !W.me.kit->ranged) ? 1 : W.me.range;
}
// A tile in range of the camp that is free now (a dead camp tile included) or open terrain (maybe occupied now).
static __attribute__((always_inline)) inline bool tank_can_stand_near(int ci, const vec2 me)
{
	const vec2 c = M.camps[static_cast<std::size_t>(ci)].pos;
	const int r = tank_want_range(ci);
	if (cheb(me, c) <= r)
		return true;
	for (int dx = -r; dx <= r; ++dx)
		for (int dy = -r; dy <= r; ++dy)
		{
			const vec2 t{ c.x + dx, c.y + dy };
			if (inb(t) && (!bbget(M.block_camps, t) || mv::free_tile(t)))
				return true;
		}
	return false;
}
// A focus with no tile to stand on in my range (only holes and the group's living camps around it) would park the body beside it
// for the rest of the game, in the 1-wide pocket that is the field's only access. Take the nearest living member I can stand in
// range of; the rest open up as their neighbours die. Checked only where the walk toward an unreachable focus stops (within want +
// 1 of it): no cost on the way there.
static __attribute__((always_inline)) inline void tank_pick_standable_focus(int gi, const vec2 me, int& focus)
{
	if (cheb(me, M.camps[static_cast<std::size_t>(focus)].pos) <= tank_want_range(focus) + 1 && !tank_can_stand_near(focus, me))
	{
		int best = -1, bd = BIG;
		for (int ci : M.groups[static_cast<std::size_t>(gi)].members)
		{
			if (ci == focus || !visible_camp(ci))
				continue;
			const int d = cheb(me, M.camps[static_cast<std::size_t>(ci)].pos);
			if (d < bd && tank_can_stand_near(ci, me))
			{
				bd = d;
				best = ci;
			}
		}
		if (best >= 0)
			focus = best;
	}
}
// Records the chosen focus for the next turn's focus hold.
static __attribute__((always_inline)) inline void tank_remember_focus(int gi, int focus)
{
	T.focus = focus;
	if (fkh_ci != focus || fkh_gi != gi || visible_camp(focus))
		fkh_seen = now();
	fkh_ci = focus;
	fkh_gi = gi;
	fkh_r = now();
}
// A ready walk-excluding damage spell (Stellar, Cassi) that reaches the group from here goes first; the walk into basic range would
// forfeit it. True if it was cast.
static __attribute__((always_inline)) inline bool tank_cast_before_walk(int focus, const vec2 fp, int want, const vec2 me)
{
	if (cheb(me, fp) > want && combat::caster_spell_reaches(focus))
	{
		combat::camp_abilities(focus, true);
		if (W.cast)
		{
			T.engaged = true;
			return true;
		}
	}
	return false;
}
static __attribute__((always_inline)) inline void tank_walk_to_focus(int gi, const vec2 me, const vec2 fp, int want)
{
	if (cheb(me, fp) > want && W.can_move())
	{
		// a kept board zeroed in place instead of a new board per walk
		static bitboard tkb_goals{ cambc::uninitialized };
		std::optional<bitboard> tkb_loc;
		nchk(cambc::detail::sdk_Bitboard_Zero(tkb_goals.ptr()));
		bitboard& goals = tkb_loc ? *tkb_loc : tkb_goals;
		bool any = false;
		for (int dx = -want; dx <= want; ++dx)
			for (int dy = -want; dy <= want; ++dy)
			{
				const vec2 t{ fp.x + dx, fp.y + dy };
				if (!mv::free_tile(t))
					continue;
				bbset(goals, t);
				any = true;
			}
		mv::collect_dash(1); // the tank's last leg to its focus dashes from 3 tiles out (not landing kits)
		if (any)
			mv::step_to_set(goals, 30, gi);
		else
			mv::step_to(fp, want + 1, 30, gi);
		mv::collect_dash(0);
	}
}
// Hits the focus from where the body stands, or uses a ranged ability when the walk was unused.
static __attribute__((always_inline)) inline void tank_hit_focus(int focus, const vec2 fp, bool& acted)
{
	if (cheb(W.me.pos, fp) <= W.me.range)
	{
		if (combat::hit_camp(focus))
		{
			acted = true;
			T.engaged = true;
		}
	}
	else if (!W.moved && W.me.kit->ranged && cheb(W.me.pos, fp) <= 4)
	{
		combat::camp_abilities(focus, true);
		acted |= W.cast;
	}
}
	// Vendetta's kill refunds her reset and dash: with the walk unused, step (or dash, if no reset went out) toward the next living
	// member out of reach, so the next turn opens with attack + reset again.
static __attribute__((always_inline)) inline void tank_follow_kill_to_next_member(int gi, int focus, bool& acted)
{
	if (vendetta_layer::vendash(*W.me.kit) && W.attacked && (W.can_move() || (!W.cast && W.me.kit->slot_dash >= 0 && combat::ready(W.me.kit->slot_dash))) && !camp_alive_now(focus) && fuel() > 30000) // CB3 bit 8192 VFD: after a walk, the dash (GameRules.md:262, :430)
	{
		// The goal loop calls camp_threat 8 times a member (up to 53k with 9 members and 14-28 camps in sight): a member already in reach
		// skips it, and the fuel is checked a member at a time.
		bool in_reach = false;
		for (int ci : M.groups[static_cast<std::size_t>(gi)].members)
			if (visible_camp(ci) && camp_alive_now(ci) && cheb(W.me.pos, M.camps[static_cast<std::size_t>(ci)].pos) <= 1)
				in_reach = true;
		static bitboard tkb_goals2{ cambc::uninitialized }; // a kept board, as above
		std::optional<bitboard> tkb_loc2;
		nchk(cambc::detail::sdk_Bitboard_Zero(tkb_goals2.ptr()));
		bitboard& goals = tkb_loc2 ? *tkb_loc2 : tkb_goals2;
		bool any = false;
		for (int ci : M.groups[static_cast<std::size_t>(gi)].members)
		{
			if (in_reach || fuel() < 30000)
				break;
			if (!visible_camp(ci) || !camp_alive_now(ci))
				continue;
			const vec2 cp = M.camps[static_cast<std::size_t>(ci)].pos;
			for (int dx = -1; dx <= 1; ++dx)
				for (int dy = -1; dy <= 1; ++dy)
				{
					const vec2 t{ cp.x + dx, cp.y + dy };
					if ((dx || dy) && inb(t) && mv::free_tile(t) && mv::camp_threat(t, gi) <= 0.0f)
					{
						bbset(goals, t);
						any = true;
					}
				}
		}
		if (!in_reach && any)
		{
			mv::collect_dash(1);
			const bool vfd = !W.can_move(); // CB3 bit 8192 VFD
			if (vfd)
				mv::collect_dash_only(true);
			if (mv::step_to_set(goals, 12, gi))
				acted = true;
			if (vfd)
				mv::collect_dash_only(false);
			mv::collect_dash(0);
		}
	}
}
bool tank_turn(int gi, const Here& here)
{
	last_act = ACT_CAMP;
	dbg_path = 10;
	const vec2 me = W.me.pos;
	if (tank_bail_out(gi, here, me))
		return true;
	if (T.engaged && tr_gi == gi && now() - tr_last <= 1 && rotate_camps_to_mate(gi, W.me.hp, true))
		return true;
	PROF("t_bail");
	int focus = pick_focus(gi, me);
	if (focus >= 0)
		focus = focus_hold(gi, focus, me);
	dbg_path = 11;
	if (focus < 0)
	{
		if (tank_attack_focus(gi))
			return true;
		return false;
	}
	dbg_path = 12;
	tank_track_focus_progress(gi, me, focus);
	PROF("t_focus");
	tank_pick_standable_focus(gi, me, focus);
	tank_remember_focus(gi, focus);
	const vec2 fp = M.camps[static_cast<std::size_t>(focus)].pos;
	const int want = tank_want_range(focus);
	if (tank_cast_before_walk(focus, fp, want, me))
		return true;
	tank_walk_to_focus(gi, me, fp, want);
	PROF("t_move");
	bool acted = W.moved;
	tank_hit_focus(focus, fp, acted);
	PROF("t_hit");
	tank_follow_kill_to_next_member(gi, focus, acted);
	if (T.engaged || cheb(W.me.pos, fp) <= 1)
		combat::camp_abilities(focus, true);
	PROF("t_abil");
	return acted || W.cast;
}
// Melee crew mate with health: hold an attacker nobody holds yet (each camp hits its nearest champion), so the
// group's damage spreads over several bodies. True if acted.
bool hold_attacker(int gi, int focus)
{
	std::vector<Attacker> la_tmp;
	const auto& att = living_attackers_cached(gi, false, la_tmp);
	if (att.empty())
		return false;
	int best = -1;
	float best_s = 1e9f;
	for (const auto& a : att)
	{
		bool held = false;
		for (const auto& al : W.allies)
			if (!al.channeling() && cheb(al.pos, a.pos) <= 1)
				held = true;
		if (cheb(W.me.pos, a.pos) <= 1)
			held = false; // keep holding the one we are next to
		if (held)
			continue;
		const VisCamp* vc = visible_camp(a.ci);
		const float s = (vc ? vc->hp : 1000.0f) + static_cast<float>(cheb(W.me.pos, a.pos)) * 40.0f;
		if (s < best_s)
		{
			if (cheb(W.me.pos, a.pos) > 1)
			{
				bool ow_free = false;
				for (const vec2 d : DIRS)
					ow_free = ow_free || mv::free_tile(a.pos + d);
				if (!ow_free)
					continue;
			}
			best_s = s;
			best = a.ci;
		}
	}
	if (best < 0)
	{
		if (W.me.frac() < 0.6f || focus < 0 || !M.camps[static_cast<std::size_t>(focus)].attacks())
			return false;
		best = focus; // everything is held: add damage on the focus from melee range
	}
	if (cheb(W.me.pos, M.camps[static_cast<std::size_t>(best)].pos) > 1)
	{
		bool hoa_free = false;
		for (const vec2 d : DIRS)
			hoa_free = hoa_free || mv::free_tile(M.camps[static_cast<std::size_t>(best)].pos + d);
		if (!hoa_free)
		{
			int hoa_alt = -1, hoa_d = BIG;
			for (int ci : M.groups[static_cast<std::size_t>(gi)].members)
			{
				const VisCamp* vc = ci == best ? nullptr : visible_camp(ci);
				if (!vc || vc->hp <= 0.0f)
					continue;
				const vec2 p = M.camps[static_cast<std::size_t>(ci)].pos;
				const int d = cheb(W.me.pos, p);
				bool ok = d <= 1;
				for (const vec2 dd : DIRS)
					ok = ok || mv::free_tile(p + dd);
				if (ok && d < hoa_d)
				{
					hoa_d = d;
					hoa_alt = ci;
				}
			}
			if (hoa_alt < 0)
				return false;
			best = hoa_alt;
		}
	}
	T.focus = best;
	const vec2 ap = M.camps[static_cast<std::size_t>(best)].pos;
	if (cheb(W.me.pos, ap) > 1 && W.can_move())
	{
		bitboard goals;
		bool any = false;
		for (const vec2 d : DIRS)
		{
			const vec2 t = ap + d;
			if (mv::free_tile(t))
			{
				bbset(goals, t);
				any = true;
			}
		}
		if (any)
			mv::step_to_set(goals, 20, gi);
	}
	if (cheb(W.me.pos, ap) <= 1)
	{
		combat::hit_camp(best);
		combat::camp_abilities(best, true);
	}
	return true;
}
void support_idle_reset()
{
	lf_n = 0;
}
bool support_idle_turn(int gi)
{
	if (lf_gi == gi && now() - lf_last <= 3)
		++lf_n;
	else
	{
		lf_gi = gi;
		lf_n = 1;
	}
	lf_last = now();
	if (lf_n < LOOP_FIX)
		return false;
	NLOG("r%d slot %d LOOP_FIX drop %d after %d idle support turns\n", now(), P.my_slot, gi, lf_n);
	lf_n = 0;
	drop_target(20);
	return true;
}
// The tank's bail (tank_turn) for a crew mate: losing to the attackers that hit me (they do not die to the crew here before I
// would), with too little health left to walk out of their reach -> bench while a healthy melee claimant holds them, else drop the
// group, and escape. True if this turn was used.
bool camp_holder_bail(int gi, const Here& here)
{
	std::vector<mv::Threat> th;
	float incoming = incoming_at(W.me.pos, &th);
	incoming += unseen_camp_threats(W.me.pos, th);
	if (incoming <= 0.0f || th.empty())
		return false;
	mv::awake_mem_threats(W.me.pos, th);
	float hp_left = 0;
	int steps = mv::escape_steps(th, W.me.pos);
	float dps = threat_kill_dps(here.crew, th, &hp_left, true);
	float walk_inc = incoming; // the walk-out's price
	float full = incoming;
	const int cm = crew_mates_in_reach(gi, th, hp_left, here.crew, &full, &dps);
	full = std::max(full, incoming);
	if (cm & 2)
		incoming = full;
	if (cm != 0)
		walk_inc = full;
	float eff = W.me.hp + std::min(W.me.shield, incoming * static_cast<float>(std::max(1, W.me.shield_turns)));
	const bool px_far = !(eff > incoming * (hp_left / dps + 1.0f)) && prism_exit_walk_longer(gi, eff, walk_inc, th, steps);
	if (eff > incoming * (hp_left / dps + 1.0f) || eff >= walk_inc * (static_cast<float>(steps) + 1.5f) + 0.08f * W.me.maxhp || crew_bail::skip(gi, th, hp_left, dps, eff, steps))
		return false; // winning, or health to stay; or the crew holds
	if (!(cbl_priced_round == now()) && rotate_camps_to_mate(gi, eff, false))
	{
		dbg_path = 62;
		return true;
	}
	remember_unseen_attackers(th);
	bool relief = false;
	for (const auto& a : W.allies)
		if (claims(a.slot, gi) && !a.kit->ranged && a.frac() > 0.5f && !a.channeling())
			for (const auto& t : th)
				relief |= cheb(a.pos, t.pos) <= 1;
	TT_EV("cfhb", gi, relief ? 1 : 0, static_cast<int>(W.me.frac() * 100.0f));
	if (relief)
		T.bench_until = now() + 12;
	else if (sg_op_group() == gi)
	{
		siege_note_bail(gi);
		drop_target(0); // no blacklist (the operation's own rules)
	}
	else
	{
		drop_target(25);
		bail_ban_remember(gi);
	}
	if (!(px_far && mv::escape_to_safe_tile(th)))
		mv::escape(th);
	last_act = ACT_CAMP;
	dbg_path = 61;
	return true;
}
int camp_engaged_check(int gi, const Here& here) // 0: go on; 1: this turn was used; 2: the target was dropped (choose again)
{
	const auto& g = M.groups[static_cast<std::size_t>(gi)];
	if (g.n_att == 0 || !group_awake(gi))
		return 0;
	if (sg_op_group() == gi)
		return 0; // operations keep their own aborts (siege_turn)
	std::vector<Attacker> la_tmp;
	const auto& att = living_attackers_cached(gi, false, la_tmp);
	if (att.empty())
		return 0;
	std::vector<mv::Threat> th;
	const bool fb1_gate = att.size() >= 2 && W.me.frac() * 100.0f < static_cast<float>(CF_REENTRY_HP);
	const float incoming = FB1_ON(1) ? (fb1_gate ? incoming_at(W.me.pos, nullptr) : (refresh_owned(), 0.0f)) : incoming_at(W.me.pos, &th); // FB1 bit 1 FL1: gate first; refresh_owned keeps its timing
	// No solo re-entry into an awake pack while hurt: a body that re-enters alone at 35-59% after a bench dies. In contact (next to an
	// attacker, or hit) the bail tests decide.
	if (att.size() >= 2 && W.me.frac() * 100.0f < static_cast<float>(CF_REENTRY_HP) && incoming <= 0.0f)
	{
		bool contact = false, held = false;
		const int my_r = std::max(1, W.me.range); // review (cambc-a9): a ranged mate shooting from its range is in contact, not re-entering
		for (const auto& a : att)
		{
			contact |= cheb(a.pos, W.me.pos) <= my_r;
			for (const auto& al : W.allies)
				if (claims(al.slot, gi) && !al.kit->ranged && al.frac() > 0.5f && !al.channeling() && cheb(al.pos, a.pos) <= 1)
					held = true;
		}
		if (!contact && !held)
		{
			TT_EV("cfre", gi, static_cast<int>(W.me.frac() * 100.0f));
			drop_target(25);
			bail_ban_remember(gi);
			return 2;
		}
	}
	return 0;
}
// CTG bit 1: support_turn's measured camp-work cost per camp in sight (x100, decayed maximum per body).
static long ctg_rate_hi = 0;
struct CtgMeter
{
	long f0;
	int r0;
	long nc;
	~CtgMeter()
	{
		if (f0 >= 0)
			ctg_rate_hi = std::max(fg::fuel_used_since(f0, r0) * 100 / nc, ctg_rate_hi - (ctg_rate_hi >> 5));
	}
};
bool support_turn(int gi, const Here& here)
{
	last_act = ACT_CAMP;
	dbg_path = 20;
	const vec2 near = here.tank ? here.tank->pos : M.groups[static_cast<std::size_t>(gi)].anchor;
	int focus = pick_focus(gi, near);
	if (focus < 0)
	{
		if (tank_attack_focus(gi))
			return true;
		return false;
	}
	T.focus = focus;
	const Kit& k = *W.me.kit;
	PROF("s_pre");
	const long ctg_nc = std::max(1L, static_cast<long>(W.camps.size()));
	if (fuel() < ctg_rate_hi * ctg_nc / 100 + static_cast<long>(CTG_TAB[2])) // CTG bit 1: the camp work would not fit
	{
		cheap_camp_hit(gi);
		return true;
	}
	const CtgMeter ctg_m{ (fuel()), fg::rnd(), ctg_nc };
	if (T.engaged && camp_holder_bail(gi, here))
		return true;
	if (T.engaged && tr_gi == gi && now() - tr_last <= 1 && rotate_camps_to_mate(gi, W.me.hp, true))
		return true;
	if (!k.ranged && W.me.frac() > 0.5f && now() >= T.bench_until && hold_attacker(gi, focus))
	{
		PROF("s_held");
		return true;
	}
	dbg_path = 21;
	PROF("s_hold");
	// Safe tiles (no awake attacker would pick me) within basic and spell range of the focus, computed once.
	const int spell_r = std::max({ static_cast<int>(k.dmg_range), static_cast<int>(k.cc_range), static_cast<int>(k.aoe_range) });
	const int reach = std::max(W.me.range, spell_r);
	bool any_all = false;
	const bitboard safe = safe_attack_tiles(gi, focus, reach, true, &any_all);
	PROF("s_safe");
	if ((SBL_TAB[1] & (k.ranged ? 2 : 1)) != 0 && !any_all && W.can_move() && !W.moved && W.me.frac() > 0.5f && now() >= T.bench_until && [&]
		{
			std::vector<Attacker> sbl_tmp;
			return living_attackers_cached(gi, false, sbl_tmp).empty();
		}() && incoming_at(W.me.pos, nullptr) <= 0 && approach_group(gi))
		return true; // engaged, no attacker in sight, no safe tile: walk in until one is seen, don't stand
	const vec2 fp = M.camps[static_cast<std::size_t>(focus)].pos;
	bitboard goals;
	bool any = false;
	if (any_all)
	{
		if (ci_layer::me_cassi())
			nova::ci2::stand_goals(goals, fp); // CI2 decision 4
		else
			goals.draw_chebyshev(fp, static_cast<float>(W.me.range));
		goals &= safe;
		any = bbany(goals);
		(void)(any && willow_layer::me() && WL2_ON(2));
		(void)(any && willow_layer::me() && WL2_ON(1024));
		if (any && willow_layer::me() && here.tank && M.groups[static_cast<std::size_t>(gi)].n_golem + M.groups[static_cast<std::size_t>(gi)].n_mono > 0)
		{ // WGL bit 2 (b1769): on a golem/monolith crew, a safe attack tile in heal reach of the tank and farther from the focus than the tank
			bitboard hr;
			hr.draw_chebyshev(here.tank->pos, k.heal_range);
			hr &= goals;
			const int dt = cheb(here.tank->pos, fp);
			bitboard far_t;
			bbforeach(hr, [&](vec2 p) {
				if (cheb(p, fp) > dt)
					bbset(far_t, p);
			});
			if (bbany(far_t))
				goals = far_t;
		}
	}
	if (any && bbget(goals, W.me.pos))
	{
		dbg_path = 22;
		// In place: spells first (no walk this turn), then basic attacks.
		combat::camp_abilities(focus, false);
		combat::hit_camp(focus);
		support_idle_reset();
		return true;
	}
	// A walk-excluding damage spell is ready and reaches from my safe tile: cast it here, since walking into basic range would forfeit
	// it (the walk waits a turn).
	if (any_all && bbget(safe, W.me.pos) && combat::caster_spell_reaches(focus))
	{
		combat::camp_abilities(focus, false);
		if (W.cast)
		{
			combat::hit_camp(focus);
			return true;
		}
	}
	if (any && vesper_dash_approach(goals, focus, gi, true))
	{
		support_idle_reset();
		return true;
	}
	if (any && W.can_move())
	{
		vec2 bt{ -1, -1 };
		if ((bt.x >= 0 && mv::try_move(bt)) || mv::step_to_set(goals, 20, gi))
		{
			combat::hit_camp(focus);
			combat::try_heal();
			support_idle_reset();
			return true;
		}
	}
	// No safe spot in basic range: cast from spell range if that is safe, else wait outside reach.
	if (spell_r > W.me.range && any_all)
	{
		if (bbget(safe, W.me.pos) && cheb(W.me.pos, fp) <= spell_r)
		{
			combat::camp_abilities(focus, false);
			support_idle_reset();
			return true;
		}
		if (W.can_move() && mv::step_to_set(safe, 20, gi))
			return true;
	}
	combat::try_heal();
	dbg_path = any ? 24 : 23;
	if (!W.attacked && !W.cast && support_idle_turn(gi))
		return false; // this group has no place for me
	std::vector<mv::Threat> th;
	if (incoming_at(W.me.pos, &th) > 0)
		mv::escape(th);
	return true;
}
} // namespace
} // namespace nova::econ

// crew-pooled bail from a camp. A camp hits only its nearest champion, so the crew holds an attacker in turns: each hitter down to
// its own bail line (exit steps + 1.5 rounds of hits + 8%). Unity build: the econ .cc files come first, so their helpers are in
// scope.
namespace nova::econ::crew_bail
{
namespace
{
// The holding rounds body (pos, hp, shield) gives before its own bail line against the attackers of th in its reach.
float rounds(vec2 p, float hp, float shield, int sh_turns, float maxhp, const std::vector<mv::Threat>& th)
{
	float inc = 0;
	int st = 0;
	for (const auto& t : th)
	{
		const int d = cheb(p, t.pos);
		if (d > t.reach)
			continue;
		const int ci = M.camp_index(t.pos);
		inc += ci >= 0 ? M.camps[static_cast<std::size_t>(ci)].str : 0.0f;
		st = std::max(st, t.reach - d + 1);
	}
	if (inc <= 0)
		return 0;
	const float eff = hp + std::min(shield, inc * static_cast<float>(std::max(1, sh_turns)));
	return std::max(0.0f, eff - (inc * (static_cast<float>(st) + 1.5f) + 0.08f * maxhp)) / inc;
}
// HV2 bit 1: my own holding rounds with my camp-hit factor (mu::ct_k) on the attackers' strength, as incoming_at prices it.
float hv2_rounds_me(const std::vector<mv::Threat>& th)
{
	float inc = 0;
	int st = 0;
	for (const auto& t : th)
	{
		const int d = cheb(W.me.pos, t.pos);
		if (d > t.reach)
			continue;
		const int ci = M.camp_index(t.pos);
		inc += ci >= 0 ? M.camps[static_cast<std::size_t>(ci)].str : 0.0f;
		st = std::max(st, t.reach - d + 1);
	}
	inc *= mu::ct_k;
	if (inc <= 0)
		return 0;
	const float eff = W.me.hp + std::min(W.me.shield, inc * static_cast<float>(std::max(1, W.me.shield_turns)));
	return std::max(0.0f, eff - (inc * (static_cast<float>(st) + 1.5f) + 0.08f * W.me.maxhp)) / inc;
}
} // namespace
bool skip(int gi, const std::vector<mv::Threat>& th, float hp_left, float dps, float eff, int steps)
{
	if (th.empty())
		return false;
	float pool = hv2_rounds_me(th); // HV2: my camp-hit factor
	for (const auto& a : W.allies)
		if (claims(a.slot, gi) && a.hp > 0 && !a.channeling())
			pool += rounds(a.pos, a.hp, a.shield, a.shield_turns, a.maxhp, th);
	if (pool < hp_left / std::max(30.0f, dps))
		return false; // the crew can't hold until the kill
	float my_inc = 0;
	bool shielded = true; // a claimant mate is nearer than me to every attacker in my reach: none hits me now
	for (const auto& t : th)
	{
		const int d = cheb(W.me.pos, t.pos);
		if (d > t.reach)
			continue;
		const int ci = M.camp_index(t.pos);
		my_inc += ci >= 0 ? M.camps[static_cast<std::size_t>(ci)].str : 0.0f;
		bool nearer = false;
		for (const auto& a : W.allies)
			nearer |= claims(a.slot, gi) && a.hp > 0 && !a.channeling() && cheb(a.pos, t.pos) < d;
		shielded = shielded && nearer;
	}
	my_inc *= mu::ct_k; // HV2: my camp-hit factor (Durability, Jungle), as incoming_at
	if (my_inc <= 0 || shielded)
		return true;
	return steps <= 1 && eff >= my_inc * 2.5f + 0.08f * W.me.maxhp; // I step out next turn on my own line
}
} // namespace nova::econ::crew_bail
