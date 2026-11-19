// brain_tribute_doom.cc: Whether a tribute channel dies before it completes.
#include "brain_internal.h"
namespace nova {
namespace {
// HP + shield at my last own turns inside a tribute channel (oldest first; td_n samples, consecutive rounds).
int td_round[4] = { -1000, -1000, -1000, -1000 };
float td_hp[4] = { 0, 0, 0, 0 }; // HP and shield apart.
float td_sh[4] = { 0, 0, 0, 0 };
int td_n = 0;
int td_left = -1; // Ticks left at my last tribute_doomed sample.
int b781_own_cancel = -1000; // Round of my last cancel of a doomed tribute channel.
// Records this turn's sample and decides whether the tribute channel dies before it completes.
bool tribute_doomed()
{
	if (!(W.me.state & ST_TRIBUTE))
	{
		td_n = 0;
		return false;
	}
	if (td_n > 0 && td_round[td_n - 1] != W.round - 1)
		td_n = 0; // a gap (death, another channel): restart the history
	if (td_n >= 4)
	{
		for (int i = 0; i < 3; ++i)
		{
			td_round[i] = td_round[i + 1];
			td_hp[i] = td_hp[i + 1];
			td_sh[i] = td_sh[i + 1];
		}
		td_n = 3;
	}
	const float eff = W.me.hp + std::max(0.0f, W.me.shield);
	td_round[td_n] = W.round;
	const float sh_now = std::max(0.0f, W.me.shield);
	td_hp[td_n] = W.me.hp;
	td_sh[td_n] = sh_now;
	++td_n;
	if (td_n < 2)
		return false;
	std::int32_t left = -1;
	if (cambc::detail::sdk_champion_channel_time(static_cast<std::uint32_t>(cambc::detail::sdk_my_champion()), &left) != 0)
		return false;
	if (left <= 1)
		return false; // it completes at my next turn start: keep it
	if (W.round + static_cast<int>(left) <= TDE_END && W.round + 1 + rs::tribute_turns(static_cast<int>(W.me.gems), prism::has_family(rs::F_TRIBUTE)) > TDE_END)
		return false; // v799 TDE1 (X555, INT:120): it lands by r2000 and no restart can
	td_left = left;
	// Over td_n - 1 own turns (at most 3); a shield that expired is not damage (HP drop + shield drop while it is up).
	const float dmg = (td_hp[0] - W.me.hp) + (sh_now > 0.5f ? td_sh[0] - sh_now : 0.0f);
	if (!(dmg > 0))
		return false;
	// The winning channel keeps on under camp damage (bit 2: no known enemy champion within TD_WIN_R).
	const bool td_win = (W.tributed_us + static_cast<int>(W.me.gems) >= rs::WIN_TRIBUTE) && (prism::nearest_known_enemy() > TD_WIN_R); // v7xx PFB bit 2
	const bool tdc = W.me.type != cambc::champion_type::prism; // TDC: non-Prism carriers
	if (tdc && !combat::took_damage(2))
		return false; // TDC bit 2: no recent hit, so no cancel (the same turn's bank would restart from full ticks)
	if (tdc && td_win)
		return false; // TDC bit 1: the winning channel keeps on (the low-HP branch too)
	if (!td_win && td_n >= 4 && static_cast<float>(left) * dmg / 3.0f >= static_cast<float>(TD_RATE_PCT) * 0.01f * eff)
		return true;
	return eff * 100.0f < static_cast<float>(TD_LOW_PCT) * W.me.maxhp && left > 2;
}
} // namespace
} // namespace nova
