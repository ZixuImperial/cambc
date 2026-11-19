// econ_tribute_gates.cc: What econ asks before starting a new channel: the foe that ended my last tribute, the restart hold and the
// block after a doomed cancel. The turn records of those events live here; brain writes them.
#include "econ_internal.h"
namespace nova {
int td_cancel_left = -1; // ticks left at the last doomed cancel
int b781_ec_round = -1000; // First own turn after the enemy ended my tribute channel.
vec2 b781_ec_pos{ -1, -1 }; // Where I stood then.
std::uint32_t wsi_ec_h[4] = { 0, 0, 0, 0 }; // enemy champions near me when the enemy ended my channel (WSI, champ_prism.h)
int wsi_ec_n = 0;
void note_channel_ender_foes()
{
	wsi_ec_n = 0;
	auto add = [](std::uint32_t h) {
		for (int i = 0; i < wsi_ec_n; ++i)
			if (wsi_ec_h[i] == h)
				return;
		if (wsi_ec_n < 4)
			wsi_ec_h[wsi_ec_n++] = h;
	};
	for (const auto& e : W.enemies)
		if (cheb(e.pos, W.me.pos) <= prism::WSI_TAB[2])
			add(e.h);
	for (const auto& e : W.enemies_far)
		if (cheb(e.pos, W.me.pos) <= prism::WSI_TAB[2])
			add(e.h);
	for (const auto& t : intel::team_table())
		if (t.alive && t.pos.x >= 0 && W.round - t.round <= prism::WSI_TAB[3] && cheb(t.pos, W.me.pos) <= prism::WSI_TAB[2])
			add(t.h);
}
// True: a note was taken and none of its foes is (alive and) visible within WSG_R or last seen within WSG_R; the window lifts.
bool channel_ender_window_lifts()
{
	if (wsi_ec_n <= 0)
		return false;
	const int r = prism::WSG_TAB[2];
	for (int i = 0; i < wsi_ec_n; ++i)
	{
		const std::uint32_t h = wsi_ec_h[i];
		for (const auto& e : W.enemies)
			if (e.h == h && cheb(e.pos, W.me.pos) <= r)
				return false;
		for (const auto& e : W.enemies_far)
			if (e.h == h && cheb(e.pos, W.me.pos) <= r)
				return false;
		for (const auto& t : intel::team_table())
			if (t.h == h && t.alive && t.pos.x >= 0 && cheb(t.pos, W.me.pos) <= r)
				return false;
	}
	return true;
}
int td_cancel_round = -1000;
int td_lost_round = -1000;
int b781_trib_start = -1000;
// Within TD_BLOCK_R rounds of a doomed-tribute cancel, a body hit within the last 2 rounds opens no new tribute. Bit 2 of the doom
// fix: also while a known enemy champion is within TD_WIN_R, unless the new channel is no longer than the cancelled one's rest.
// Enemy-ended hold: within BUSH_HIDDEN_HIT_EC_R rounds of an enemy-ended tribute, at that spot (within 2), while I am hit (not by
// camps) or a known enemy is within 4: ward the nearest unlit bush first (no ward once channelling).
bool tribute_restart_hold()
{
	if (W.round - b781_ec_round >= BUSH_HIDDEN_HIT_TAB[3] || b781_ec_pos.x < 0 || cheb(W.me.pos, b781_ec_pos) > 2)
		return false;
	const bool hit = combat::took_damage(2) && mv::camp_threat(W.me.pos) <= 0;
	if (!hit && prism::nearest_known_enemy() > 4)
		return false;
	ward::react(false);
	if (W.round + prism::channel_tick_count(static_cast<int>(W.me.gems)) <= b781_ec_round + BUSH_HIDDEN_HIT_TAB[4])
		return false;
	if (hit && W.can_move())
	{
		std::vector<mv::Threat> th;
		for (int dy = -2; dy <= 2; ++dy)
			for (int dx = -2; dx <= 2; ++dx)
			{
				const vec2 p{ W.me.pos.x + dx, W.me.pos.y + dy };
				if (inb(p) && bbget(M.bushes, p) && !bbget(W.vis, p))
					th.push_back({ p, 1 });
			}
		if (!th.empty())
			mv::escape(th);
	}
	return true;
}
bool new_tribute_blocked()
{
	if (W.round - b781_ec_round < prism::WSG_TAB[3] && W.me.kit && (prism::WSG_TAB[1] & ((prism_layer::chan_wsg_carrier()) ? 8 : 2)) && W.me.gems >= TG_BAG && !(channel_ender_window_lifts()) && prism::winning_tribute_start_blocked(static_cast<int>(W.me.gems)))
		return true; // The foe that ended my last channel can end this one too.
	if (tribute_restart_hold())
		return true; // The enemy ended my last channel here.
	if (!(W.round - td_cancel_round < TD_BLOCK_R))
		return false;
	if (combat::took_damage(2))
		return true;
	return prism::nearest_known_enemy() <= TD_WIN_R && prism::channel_tick_count(static_cast<int>(W.me.gems)) > td_cancel_left;
}

} // namespace nova
