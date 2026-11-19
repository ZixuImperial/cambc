// brain_help_fight.cc: Help calls and the fight layer.
#include "brain_internal.h"
// b2315 HP2S bit 4 DMC1b: the engine says this mate slot is dead now (one host call; called only with the flag on).
static inline bool hp2s_dead_hf(int s)
{
	std::int32_t al = 1;
	return cambc::detail::sdk_champion_is_alive(nova::P.handle[static_cast<std::size_t>(s)], &al) == 0 && al == 0;
}
namespace nova {
namespace {
// the team HELP call (event type 4, subject = my cell; cells sized so the map fits in 254 of them).
int help_grid_cell_size()
{
	int c = 1;
	while (((G.w + c - 1) / c) * ((G.h + c - 1) / c) > 254)
		++c;
	return c;
}
int help_last_post = -100;
std::uint16_t help_my_raw = 0;
void help_post()
{
	if (W.round - help_last_post < 3)
		return;
	const comms::Event cur = comms::ev();
	const int age = comms::event_age_rounds(cur, W.round);
	if (cur.subject >= 0 && cur.type >= comms::EV_TYPE_HELP && age < 4)
		return; // a fresh call (mine or a mate's) stands
	const int c = help_grid_cell_size(), cw = (G.w + c - 1) / c;
	const int cell = (W.me.pos.y / c) * cw + (W.me.pos.x / c);
	{
		comms::bh64_help_dropped = false;
		comms::write_event(cell, comms::EV_TYPE_HELP, W.round);
		if (comms::bh64_help_dropped)
			return;
	}
	help_my_raw = comms::ev().raw;
	help_last_post = W.round;
}
// Fight layer writers (bits 1, 2) and the follow rule (bit 8).
int fl_last_call = -1, fl_last_cell = -1, fl_last_r = -100;
void fight_layer_turn(const combat::Assessment& a)
{
	if (!W.alive || a.stance == combat::CALM || a.nearest > 6 || W.me.channeling())
		return;
	// commit = FIGHT with the focus in my reach + 1; hold = another FIGHT turn (kiting, holding); retreat = FLEE.
	int st = 0;
	if (a.stance == combat::FLEE)
		st = 2;
	else if (!(a.focus >= 0 && cheb(W.enemies[static_cast<std::size_t>(a.focus)].pos, W.me.pos) <= W.me.range + 1))
		st = 1;
	if (!econ::engaged_now())
	{
		const float f = W.me.frac();
		tm2_flv = st * 4 + hp_band(f);
		tm2_fl_r = W.round;
	}
	// the lead posts; a visible lower slot mate near me or a mate's fresh call of this fight leads instead
	for (const auto& al : W.allies)
		if (al.slot >= 0 && al.slot < P.my_slot && cheb(al.pos, W.me.pos) <= 6)
		{
			return;
		}
	auto& fc = comms::fl_call;
	if (!fc.mine && W.round - fc.r <= 2 && fc.cell >= 0 && cheb(econ::fight_cell_tile(fc.cell), W.me.pos) <= 6)
		return;
	// Support curve: visible mates near (assess's n_friends) + mates coming to the call near me (kind 5: ETA <= 2 now, <= 5 soon).
	int c0 = 0, c1 = 0;
	if (fc.cell >= 0 && W.round - fc.r <= comms::FL_TAB[2] && cheb(econ::fight_cell_tile(fc.cell), W.me.pos) <= 8)
		for (int s = 0; s < P.n && s < comms::CLAIM_SLOTS; ++s)
			if (s != P.my_slot && comms::ckind(s) == 5 && !W.ally_by_slot(s))
			{
				if (hp2s_dead_hf(s))
					continue; // b2315 HP2S bit 4 DMC1b: a dead mate is not on the way
				const int eta = comms::cval(s) >> 4;
				c1 += eta == 1 ? 1 : 0;
			}
	int foes = 0;
	for (const auto& f : a.foes)
		foes += cheb(f.pos, W.me.pos) <= 8 ? 1 : 0;
	const int ours1 = a.n_friends + c0, ours3 = ours1 + c1;
	int call = 0;
	if (a.stance == combat::FIGHT)
		call = (a.ratio >= 1.0f || ours1 > foes) ? 1 : 0; // winning: commit; help 2 rounds out: hold; else rally
	else
		call = ours3 > foes ? 0 : 3; // help on the way: rally (keep coming); none: retreat
	const int cell = econ::fl_cell_of(W.me.pos);
	const bool same = call == fl_last_call && cell == fl_last_cell;
	if (W.round - fl_last_r < (same ? 3 : 2)) // firing (f15, 40 maps): ~170 calls/g flip-flopped; a change waits 2 rounds, a refresh 3
		return;
	bool ok = false;
	if (call == 0)
	{
		help_post();
		ok = help_last_post == W.round;
		if (ok)
		{
			fc.cell = cell;
			fc.call = 0;
			fc.r = W.round;
			fc.mine = true;
		}
	}
	else
		ok = econ::fight_cell_post(call);
	if (ok)
	{
		fl_last_call = call;
		fl_last_cell = cell;
		fl_last_r = W.round;
	}
}
// b2386 PFJ (callers read the flag): the nearest tile at Chebyshev 4 from the foe, no nearer than 4 to any seen foe, not within 2 of the
// call cell ct (when cell), inb and standable; among equal walks one outside every seen foe's next-turn reach (RC C1275 (1)). {-1,-1} none.
__attribute__((noinline)) vec2 pfj_ring_tile(vec2 foe, bool cell, vec2 ct)
{
	vec2 best{ -1, -1 };
	int bd = BIG;
	for (int dx = -4; dx <= 4; ++dx)
		for (int dy = -4; dy <= 4; ++dy)
		{
			if (std::max(std::abs(dx), std::abs(dy)) != 4)
				continue;
			const vec2 t{ foe.x + dx, foe.y + dy };
			if (!inb(t) || bbget(M.block_camps, t) || (cell && cheb(t, ct) <= 2))
				continue;
			bool ok = true, reach = false;
			for (const auto& e : W.enemies)
			{
				ok = ok && cheb(e.pos, t) >= 4;
				reach = reach || cheb(e.pos, t) <= combat::foe_next_turn_reach(e);
			}
			if (!ok)
				continue;
			const int dd = cheb(t, W.me.pos) * 2 + (reach ? 1 : 0);
			if (dd < bd)
			{
				bd = dd;
				best = t;
			}
		}
	return best;
}
__attribute__((noinline)) void pfj_fc_event()
{
	__asm__ volatile("");
}
// b2386 PFJ bit 1/2 (Prism Planner add (2); caller read the flag): a Prism answering a HELP call walks to the PFJ tile (Chebyshev 4 from
// the nearest seen foe within 6 of the call tile) instead of the cell centre; no seen foe there: false (the live walk to the cell).
__attribute__((noinline)) bool pfj_event_step(vec2 at)
{
	int fd = BIG;
	vec2 foe{ -1, -1 };
	for (const auto& e : W.enemies)
		if (cheb(e.pos, at) <= 6 && cheb(e.pos, W.me.pos) < fd)
		{
			fd = cheb(e.pos, W.me.pos);
			foe = e.pos;
		}
	if (foe.x < 0)
		return false;
	if (fd <= 4)
		return true; // already in her range: hold here (the fight logic casts when the stance flips)
	const vec2 t = pfj_ring_tile(foe, false, at);
	if (t.x < 0 || !mv::step_to(t, 0, 30))
		return false;
	pfj_fc_event();
	return true;
}
// A calm, healthy body with nothing pressing answers a fresh HELP call within the help radius: one step toward the caller.
__attribute__((noinline)) bool help_join(const combat::Assessment& a)
{
	const bool fhc_eng = econ::engaged_now(); // A camp engagement does not block joining; join_worth decides.
	if (!W.alive || a.stance != combat::CALM || W.me.frac() < 0.5f || econ::busy_capturing())
		return false;
	const comms::Event ev = comms::ev();
	if (ev.subject < 0 || ev.type != comms::EV_TYPE_HELP || (ev.raw == help_my_raw && (W.round - help_last_post <= 4))) // b2157 TMR HMR1
		return false;
	const int age = comms::event_age_rounds(ev, W.round);
	if (age > 4)
		return false;
	const int c = help_grid_cell_size(), cw = (G.w + c - 1) / c;
	vec2 at{ (ev.subject % cw) * c + c / 2, (ev.subject / cw) * c + c / 2 };
	at = { std::min<int>(at.x, G.w - 1), std::min<int>(at.y, G.h - 1) };
	if (cheb(at, W.me.pos) > EN_HELP_R || cheb(at, W.me.pos) <= 2) // The caller counted mates this close as help.
		return false;
	const auto& fc = comms::fl_call;
	if ((fc.cell >= 0 && W.round - fc.r <= comms::FL_TAB[2] && fc.call >= 2 && cheb(econ::fight_cell_tile(fc.cell), at) <= 6) || cheb(at, W.me.pos) > comms::FL_TAB[3])
		return false;
	if (fhc_eng && !econ::fight_help::join_worth(at))
		return false;
	// coming to the call: ETA x octant from the cell x HP (kept only while I hold no claim)
	const int d = cheb(at, W.me.pos), dx = W.me.pos.x - at.x, dy = W.me.pos.y - at.y;
	const int oct = dx > 0 ? (dy > 0 ? 1 : dy < 0 ? 7 : 0) : dx < 0 ? (dy > 0 ? 3 : dy < 0 ? 5 : 4) : (dy > 0 ? 2 : 6);
	const bool pfj_ev = W.me.kit && prism_layer::me() && pfj_event_step(at); // b2386 PFJ: a Prism's destination is her cast-range tile
	if (!pfj_ev)
	if (!mv::step_to(at, 2, 30))
		return false;
	tm2_coming = (d <= 2 ? 0 : d <= 5 ? 1 : 2) * 16 + oct * 2 + (W.me.frac() >= 0.6f ? 0 : 1);
	tm2_coming_r = W.round;
	return true;
}
} // namespace
} // namespace nova
