// brain_help_fight.cc: Help calls and the fight layer.
#include "brain_internal.h"
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
// A calm, healthy body with nothing pressing answers a fresh HELP call within the help radius: one step toward the caller.
__attribute__((noinline)) bool help_join(const combat::Assessment& a)
{
	const bool fhc_eng = econ::engaged_now(); // A camp engagement does not block joining; join_worth decides.
	if (!W.alive || a.stance != combat::CALM || W.me.frac() < 0.5f || econ::busy_capturing())
		return false;
	const comms::Event ev = comms::ev();
	if (ev.subject < 0 || ev.type != comms::EV_TYPE_HELP || ev.raw == help_my_raw)
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
	if (!mv::step_to(at, 2, 30))
		return false;
	tm2_coming = (d <= 2 ? 0 : d <= 5 ? 1 : 2) * 16 + oct * 2 + (W.me.frac() >= 0.6f ? 0 : 1);
	tm2_coming_r = W.round;
	return true;
}
} // namespace
} // namespace nova
