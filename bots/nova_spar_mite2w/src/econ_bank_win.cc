// econ_bank_win.cc: The game-winning bank and its escorts.
#include "econ_internal.h"
namespace nova::econ {
static bool altar_walk_field_camps_blocked()
{
	static int wb2_round = -1000;
	static bool wb2_ok = false;
	static bool wb2_x = false;
	if (wb2_round == now() && wb2_x == mfb_walt_x)
		return wb2_ok;
	wb2_round = now();
	wb2_x = mfb_walt_x;
	wb2_ok = false;
	if (fuel() < 3L * G.w * G.h + 30000)
		return false;
	bitboard blocked = M.block_camps, tgt = M.altar_adj_all;
	for (const auto& c : M.camps)
	{
		const vec2 p = c.pos;
		if (!inb(p))
			continue;
		bool dead;
		if (bbget(W.vis, p))
			dead = !bbget(W.occ_camps, p);
		else
		{
			const int g = c.group;
			dead = bbget(ring_open_bb, p) ||
				   (g >= 0 && g < static_cast<int>(gmem_size(mem)) &&
					(mem[static_cast<std::size_t>(g)].status == GS_CLEARED ||
					 (mem[static_cast<std::size_t>(g)].status == GS_RESPAWN && mem[static_cast<std::size_t>(g)].respawn_at > now())));
		}
		if (dead)
			bbset(blocked, p, false);
		else
			bbset(tgt, p, false);
	}
	if (mfb_walt_x)
		for (const auto& e : W.enemies)
			for (int dy = -4; dy <= 4; ++dy)
				for (int dx = -4; dx <= 4; ++dx)
				{
					const vec2 t{ e.pos.x + dx, e.pos.y + dy };
					if (inb(t))
						bbset(tgt, t, false);
				}
	if (!bbany(tgt))
		return false;
	bitboard visited;
	wb2_f.compute(blocked, tgt, visited);
	wb2_ok = true;
	return true;
}
// No known foe (nor the awake camps where I stand) deals my HP + shield x WB2_SAFE_PCT% before a channel that starts after `walk`
// steps and lasts `chan` turns ends. Foes as in bank_first: the tribute tile up to `walk` tiles nearer to them, reach at least 4 (a
// spell); a channelling foe starts 2 rounds later.
static bool channel_survives_known_foes(int walk, int chan)
{
	const int span = walk + chan + 1;
	const bool wbr = (wbr_finf ? WBR_ON(combat::WBR_BIT_FINF) : WBR_ON(combat::WBR_BIT_ALL));
	float dmg = incoming_at(W.me.pos, nullptr) * static_cast<float>(span);
	for (const auto& e : W.enemies)
	{
		const int dist = std::max(0, cheb(e.pos, W.me.pos) - walk);
		const int t_hit = (wbr ? combat::foe_first_hit_turn(e, dist) : 1 + std::max(0, dist - (std::max({ 4, e.range, combat::foe_next_turn_reach(e) })))) + (combat::foe_channel_act_delay(e));
		const int expo = span - t_hit + 1;
		if (expo > 0)
			dmg += mu::mult_foe_hit_to_real_hp_alt(combat::body_dps(e) * static_cast<float>(expo) + 2.0f * e.str);
	}
	return dmg * 100.0f < static_cast<float>(WB2_SAFE_PCT) * (W.me.hp + W.me.shield);
}
// The winning bag's walk and channel when the end-bank test did not bank it. True if the turn was used. No enemy body can reach me
// (within WBK_REACH) before my walk to the altar, its walk there and the channel end.
static bool winning_bag_walk_safe(int walk, int chan)
{
	const int r = intel::reach_rounds(W.me.pos, WBK_REACH, M.enemy_anchor, WBK_SPD_X100);
	return r > 2 * walk + chan + WBK_MARGIN;
}
static bool winning_bag_altar_walk_turn(int gems)
{
	const bool big = gems > WB2_BAG;
	if (big && !(W.tributed_us + gems >= rs::WIN_TRIBUTE))
		return false;
	if (big && !(W.alive && winning_bag_walk_safe(0, rs::tribute_turns(gems, prism::has_family(rs::F_TRIBUTE)))))
		return false; // the walk-free bound first, so altar_walk_field_camps_blocked's map-wide field runs only when it can pass
	if (!W.alive || W.me.channeling() || !altar_walk_field_camps_blocked())
		return false;
	std::uint16_t d = dfget_me(wb2_f);
	if (d == UNREACH)
		for (const vec2 dd : DIRS)
		{
			const vec2 n = W.me.pos + dd;
			if (!inb(n))
				continue;
			const std::uint16_t v = dfget(wb2_f, n);
			if (v != UNREACH && static_cast<std::uint16_t>(v + 1) < d)
				d = static_cast<std::uint16_t>(v + 1);
		}
	if (d == UNREACH)
		return false;
	const int chan = rs::tribute_turns(gems, prism::has_family(rs::F_TRIBUTE));
	// no later start finishes by round 2000 (start after the walk, completion at the turn start chan rounds later,
	// GameRules.md:226-230): the guard protects nothing, so the channel starts now.
	if (big)
	{
		if (!winning_bag_walk_safe(static_cast<int>(d), chan))
			return false;
	}
	else if (!channel_survives_known_foes(static_cast<int>(d), chan))
		return false;
	wb2_go = true;
	wb2_lc = false;
	const bool ok = bank();
	wb2_go = false;
	wb2_lc = false;
	NLOG("r%d slot %d win-bank2 gems %d tributed %d walk %d ok %d\n", now(), P.my_slot, gems, W.tributed_us, (int)d, (int)ok);
	return ok;
}
// a mate's bag, read only for a mate these sums can count; a failed read keeps al.gems.
static int mate_bag_read(const Body& al)
{
	if (!(al.state & ST_TRIBUTE))
		return static_cast<int>(al.gems);
	std::uint32_t g = 0;
	return cambc::detail::sdk_champion_gems(al.h, &g) == 0 ? static_cast<int>(g) : static_cast<int>(al.gems);
}
int mates_landing_by(int t_done)
{
	if (ebk_r != now() || ebk_h != W.me.h)
	{
		ebk_r = now();
		ebk_h = W.me.h;
		ebk_n = 0;
		for (const auto& al : W.allies)
		{
			if (ebk_n >= 8 || al.h == W.me.h)
				continue;
			const int ag = mate_bag_read(al);
			if (ag == 0)
				continue;
			if (al.state & ST_TRIBUTE)
			{
				std::int32_t left = -1;
				if (cambc::detail::sdk_champion_channel_time(al.h, &left) != 0 || left < 0)
					continue;
				ebk_t[ebk_n] = static_cast<int>(left) + (RGS_ON(8) && (al.state & FLEE_FIX_ST_ACTED) != 0 ? 1 : 0); // completes at its turn start once the timer is 0 (GameRules.md:232); RGS bit 8
			}
			else continue;
			ebk_g[ebk_n] = ag;
			RULE_AUDIT_FIX_CNT(2, al.gems == 0u);
			++ebk_n;
		}
	}
	int sum = 0;
	for (int k = 0; k < ebk_n; ++k)
		if (ebk_t[k] <= t_done)
			sum += ebk_g[k];
	return sum;
}
bool bag_wins_with_mates(int gems)
{
	if (W.tributed_us + gems >= rs::WIN_TRIBUTE)
		return true;
	if (gems <= 0)
		return false;
	int all = 0; // every mate's bag: the cheap bound before any SDK read
	for (const auto& al : W.allies)
		all += (mate_bag_read(al));
	if (W.tributed_us + gems + all < rs::WIN_TRIBUTE || (prism_layer::bank_skip_ebk()))
		return false;
	const std::uint16_t d = bank_dist_here();
	const int t = (d == UNREACH ? 0 : static_cast<int>(d)) + rs::tribute_turns(gems, prism::has_family(rs::F_TRIBUTE));
	const bool w = W.tributed_us + gems + mates_landing_by(t) >= rs::WIN_TRIBUTE;
	RULE_AUDIT_FIX_CNT(3, static_cast<bool>(w));
	if (w)
		EBK_FIRE(1);
	return w;
}
// v663 BB29 (b1776): firing markers (the diag copy counts their entries; empty in release) and the non-Prism test.
void bb29_fc_eg1()
{
}
void bb29_fc_eg2()
{
}
void bb29_fc_eg3()
{
}
void bb29_fc_eg4()
{
}
// EG1 (called with the bit on): their tributed total rose by less than this bag since the read: a smaller tribute, not this bag.
bool bb29_rise_short(int tt_then, int g)
{
	if (W.tributed_them - tt_then >= g)
		return false;
	bb29_fc_eg1();
	return true;
}
// EG4 (called with the bit on, non-Prism): the cut is GAME_END (no later start can land); marks a turn the old 1990 cut differs.
int bb29_eg4_cut(int fin)
{
	if ((fin >= 1990) != (fin >= GAME_END))
		bb29_fc_eg4();
	return GAME_END;
}
void bb29_fc_dk1()
{
}
// DK1 (called with the bit on): the win-progress need is the gems still missing.
int bb29_dk1_need()
{
	bb29_fc_dk1();
	return std::max(1, rs::WIN_TRIBUTE - W.tributed_us);
}
bool bb29_not_prism()
{
	return P.my_slot >= 0 && P.type[static_cast<std::size_t>(P.my_slot)] != cambc::champion_type::prism;
}
static bool winning_bag_flipflop_clear(int gems)
{
	const std::uint16_t d = bank_dist_here();
	const int walk = d == UNREACH ? 0 : static_cast<int>(d);
	const int ticks = rs::tribute_turns(gems, prism::has_family(rs::F_TRIBUTE));
	const int land = W.round + walk + ticks - (0); // v683 HLD bit 8 (EG4c): the walk's last step and the first tick share a round
	if (land >= (BB29_ON(8) && bb29_not_prism() ? bb29_eg4_cut(land) : 1990) || (!(W.me.kit && !prism_layer::bank_skip_ffw()) && prism::foe_finishes_before_bank(walk + ticks))) // v663 BB29 EG4
		return true; // the race: waiting cannot win it; not for a non-Prism bag
	const int ne = prism::nearest_known_enemy();
	if (ne < prism::WSG_TAB[2] + 2)
		wbf_far = 0;
	else if (wbf_far_r != now())
		wbf_far = wbf_far_r == now() - 1 ? wbf_far + 1 : 1;
	wbf_far_r = now();
	if (wbf_far >= 2)
		return true; // the foes stayed away
	if (d == UNREACH)
		return false;
	return ne > prism::WSG_TAB[2] + walk || combat::channel_safe(walk, ticks, 0.0f); // the start test from the altar tile, foes walk tiles nearer
}
static bool winning_bag_flipflop_blocks(int gems)
{
	if (prism_layer::bank_skip_wbf())
		return false; // Prism: channel_start_ok's guard below
	if (!bag_wins_with_mates(gems) || wbf_n < WBF_TAB[2] || now() - wbf_r > WBF_TAB[3])
		return false;
	if (now() - wbf_g <= WBF_TAB[3])
		return !winning_bag_flipflop_clear(gems); // the guard sent this bag off; it stays off until the reason is gone
	return !prism::tribute_start_allowed(gems);
}
// the first early-out test is inlined at the call site (this runs every turn); the rest is out of line
__attribute__((always_inline)) bool bank_winning_bag()
{
	if (static_cast<int>(W.me.gems) <= 0 || !M.has_altar)
		return false;
	return bank_winning_bag_slow();
}
__attribute__((noinline)) bool bank_winning_bag_slow()
{
	const int gems = static_cast<int>(W.me.gems);
	if (gems <= 0 || !M.has_altar)
		return false;
	if (bag_too_late_to_bank(gems))
		return false;
	const bool wins = bag_wins_with_mates(gems); // plus mates' landings by mine
	if (wins && nova::econ::win_bag_flee::live() && nova::econ::win_bag_flee::own(gems)) // the flee/return loop recalls home
		return nova::econ::win_bag_flee::act();
	if (!wins)
	{
		// in the last WB2_LATE rounds a bag that puts us ahead of their tributed + seen bags wins at round 2000
		if (GAME_END - now() > WB2_LATE)
			return false;
		long them = W.tributed_them;
		for (const auto& e : W.enemies)
			them += static_cast<long>(e.gems);
		for (const auto& e : W.enemies_far)
			them += static_cast<long>(e.gems);
		if (static_cast<long>(W.tributed_us) + gems + (0L) <= them)
			return false;
	}
	const bool bk = wins && bankable();
	// A Prism carrier whose channel the Prism rule refuses (a known enemy champion within PC_CHAN_R) is left to the Prism code: bank()
	// would walk her in, then refuse at the altar (a flee/bank flip-flop).
	if (prism_layer::chan_guard() && !prism::channel_start_ok(static_cast<int>(W.me.gems)))
		return false;
	// the same guard for every other kit, once the tribute guard has refused this winning bag at the altar WBF_N times
	if (winning_bag_flipflop_blocks(gems))
	{
		wbf_r = now(); // the episode lasts while the guard holds
		wbf_g = now();
		if (W.on_spawn)
			return true; // hold (GameRules.md:151)
		return go_home();
	}
	if (bk)
	{
		const std::uint16_t d = bank_dist_here();
		if (d != UNREACH && static_cast<int>(d) <= EB_WIN_D)
		{
			const bool ok = bank();
			NLOG("r%d slot %d win-bank gems %d tributed %d altar %d ok %d\n", now(), P.my_slot, gems, W.tributed_us, (int)d, (int)ok);
			if (ok)
				return ok;
		}
	}
	return winning_bag_altar_walk_turn(gems);
}
// WBH bit 1: the end hold would refuse the bank this cancel frees (not the Prism).
static bool wbh_end_hold_refuses(int gems)
{
	return !prism_layer::me() && END_HOLD_ON && end_hold_blocks_bank(gems);
}
// During a kept recall with left ticks to go, my bag now wins and the altar from here is sooner than the recall + the home-altar
// walk (the tribute is the same on both ways); bank_winning_bag's own refusals (cannot finish by r2000, the Prism channel guard, the
// winning-bag guard) keep the recall.
bool cancel_recall_for_winning_bag(int left)
{
	const int gems = static_cast<int>(W.me.gems);
	if (gems <= 0 || !M.has_altar || !bankable() || bag_too_late_to_bank(gems) || !bag_wins_with_mates(gems))
		return false;
	const std::uint16_t d = bank_dist_here();
	if (d == UNREACH || (!VB2_ON(4) && static_cast<int>(d) > EB_WIN_D))
		return false;
	if (VB2_ON(4)) // v7xx VB2 bit 4 EBW1: the walk path's own safety test, not the 10-tile cap
	{
		const int ebw_chan = rs::tribute_turns(gems, prism::has_family(rs::F_TRIBUTE));
		if (!(gems > WB2_BAG ? winning_bag_walk_safe(static_cast<int>(d), ebw_chan) : channel_survives_known_foes(static_cast<int>(d), ebw_chan)))
			return false;
		VB2_CNT(4, static_cast<int>(d) > EB_WIN_D);
	}
	if (prism_layer::chan_guard() && !prism::channel_start_ok(gems))
		return false;
	if (winning_bag_flipflop_blocks(gems))
		return false;
	if (!prism::tribute_start_allowed(gems) || (win_bag_flee::live() && win_bag_flee::own(gems)))
		return false; // WBQ bit 1 (RD1): bank_winning_bag would not take the turn the cancel frees
	if (wbh_end_hold_refuses(gems))
		return false; // WBH bit 1: the end hold refuses that bank
	const int ha = home_altar_dist();
	const int via_home = std::max(0, left) + (ha != UNREACH ? ha : static_cast<int>(d) + home_dist());
	return static_cast<int>(d) < via_home + ((ha == 0) ? 1 : 0); // v707 ECB bit 2 CRH1: a recall onto an altar-side spawn tributes on landing (no walk turn)
}
} // namespace nova::econ

// ---------------------------------------------------------------- keep or cancel a winning tribute channel. Only reached when the
// hook's switch is on.
namespace nova::econ::win_channel
{
namespace
{
// A winning bag at or above PC_WIN_KEEP_HP: channel_doom_exempt and the win start keep without any lethal test.
inline bool winning_bag_hp_ok(int gems)
{
	return W.tributed_us + gems >= rs::WIN_TRIBUTE && !(W.me.hp * 100.0f < static_cast<float>(WKH_TAB[2]) * W.me.maxhp);
}
// The known foes' burst + dps over the next WCK_TURNS foe turns reaches WKH_PCT % of her HP + shield: winning_channel_doomed's test, short
// horizon.
inline bool foe_burst_lethal_to_healer()
{
	const float eff = W.me.hp + std::max(0.0f, W.me.shield);
	return combat::foe_damage_over_ticks_deliver(WKH_TAB[3], WCK_TURNS) * 100.0f >= static_cast<float>(WKH_TAB[4]) * eff;
}
// firing counters, firecount's DG at each function entry: a decision changed
void trip_keep()
{
	cancel_round = W.round;
}
bool trip_start()
{
	return true;
}
void trip_flee(::nova::combat::Assessment& a)
{
	a.stance = ::nova::combat::FLEE;
}
} // namespace
bool keep_cancel(int gems)
{
	if (!winning_bag_hp_ok(gems) || !foe_burst_lethal_to_healer())
		return false;
	trip_keep();
	return true;
}
bool start_refuse(int gems)
{
	return winning_bag_hp_ok(gems) && foe_burst_lethal_to_healer() && trip_start();
}
int start_gate(int gems)
{
	if (start_refuse(gems))
		return -1;
	return 0;
}
void force_flee(::nova::combat::Assessment& a)
{
	if (cancel_round == W.round && !a.foes.empty() && a.stance != ::nova::combat::FLEE)
		trip_flee(a);
}
void widen(const ::nova::combat::Assessment& a, std::vector<::nova::mv::Threat>& z)
{
	if (cancel_round != W.round)
		return;
	for (std::size_t i = 0; i < z.size() && i < a.foes.size(); ++i)
	{
		const auto& f = a.foes[i];
		if (z[i].reach < 0 || f.reach < 0)
			continue;
		const bool vis = !f.remembered && f.idx >= 0 && f.idx < static_cast<int>(W.enemies.size());
		const Body* e = vis ? &W.enemies[static_cast<std::size_t>(f.idx)] : nullptr;
		const int r2 = ::nova::combat::geom::foe_two_turn_reach_after_turn_count(f, e, VBC_ON(16)); // VBC 16
		if (r2 > z[i].reach)
			z[i].reach = r2;
	}
}
} // namespace nova::econ::win_channel

// ---------------------------------------------------------------- a winning bag stuck fleeing recalls home. Reached only from
// econ::bank_winning_bag_slow when the switch is on, the bag wins and wff::live().
namespace nova::econ::win_bag_flee
{
// The guards before the episode takes bank_winning_bag's turn (a fall-through plays bank_winning_bag as usual): the game end (a recall, the walk
// back from home and the channel would not land before GAME_END); on a tribute tile, or a safe channel from the altar: the bank
// starts under bank_winning_bag's own guards (the loop is the unsafe walk back).
bool own(int gems)
{
	const int ha = econ::home_altar_dist();
	PFB_CNT(128, ha != static_cast<int>(UNREACH) && (econ::GAME_END - econ::now() <= econ::csx_recall_t() + ha + rs::tribute_rounds(gems, false)) != (econ::GAME_END - econ::now() <= econ::csx_recall_t() + ha + rs::tribute_rounds(gems, prism::has_family(rs::F_TRIBUTE))));
	if (ha == static_cast<int>(UNREACH) || econ::GAME_END - econ::now() <= econ::csx_recall_t() + ha + rs::tribute_rounds(gems, static_cast<bool>(prism::has_family(rs::F_TRIBUTE)))) // v7xx PFB bit 128 PF14: her emblem (GR:312)
		return false;
	// The bank goes ahead (bank_winning_bag as usual) on the tile (bit 2: when the tribute guard passes), or when the channel is safe from the
	// altar tile (winning_bag_flipflop_clear's stateless start test: the nearest known foe beyond WSG_R + the walk, or channel_safe).
	const std::uint16_t d = econ::bank_dist_here();
	if (d == 0)
		return false;
	if (d == UNREACH)
		return true;
	const int walk = static_cast<int>(d);
	const int ticks = rs::tribute_turns(gems, prism::has_family(rs::F_TRIBUTE));
	return !(prism::nearest_known_enemy() > prism::WSG_TAB[2] + walk || combat::channel_safe(walk, ticks, 0.0f));
}
float bsf_stake(int bag)
{
	const int need = ::nova::econ::bb29_dk1_need();
	return std::max(std::min(1.0f, static_cast<float>(bag) / static_cast<float>(std::max(1, static_cast<int>(WFF_STK_TAB[1])))), std::min(1.0f, static_cast<float>(bag) / static_cast<float>(std::max(1, need))));
}
void stake_bars(int bag, float& engage, float& flee)
{
	const int need = ::nova::econ::bb29_dk1_need(); // v663 BB29 DK1
	const float stake = std::max(std::min(1.0f, static_cast<float>(bag) / static_cast<float>(std::max(1, static_cast<int>(WFF_STK_TAB[1])))), std::min(1.0f, static_cast<float>(bag) / static_cast<float>(std::max(1, need)))); // grill: max(bag share, stake): caution only rises
	engage += (static_cast<float>(WFF_STK_TAB[2]) + static_cast<float>(WFF_STK_TAB[3]) * stake) / 100.0f;
	flee += (static_cast<float>(WFF_STK_TAB[4]) + static_cast<float>(WFF_STK_TAB[5]) * stake) / 100.0f;
}
// Bit 2: the foes' two-turn burst on me (foe_two_turn_damage for a foe in reach, a step and a hit for one a tile out) reaches my effective HP,
// so the new fight could lose the bag.
bool gate_burst()
{
	float s2 = 0.0f;
	for (const auto& e : ::nova::W.enemies)
	{
		const int d = cheb(e.pos, ::nova::W.me.pos);
		if (d > 9)
			continue;
		const float h = combat::burst::lethal_burst_hit(e, d, 0, nullptr);
		if (h > 0.0f)
			s2 += combat::burst::foe_two_turn_damage(e, d, h);
		else if (d > 1)
			s2 += std::max(0.0f, combat::burst::lethal_burst_hit(e, d - 1, 1, nullptr));
	}
	return s2 >= combat::eff_hp(::nova::W.me);
}
bool gate()
{
	if (!gate_burst())
		return false;
	wff_g2 = econ::now();
	return true;
}
bool act()
{
	if (econ::recall_safe() && econ::start_recall())
		return true; // the recall keeps the bag and lands at full health (flee_streak's recall test)
	if (wff_flee || wff_g2 == econ::now())
		return false; // unsafe: flee_stage keeps fleeing, no walk back to the altar
	return econ::go_home(); // off-FLEE turn: home, out of every reach, recalling when it turns safe
}
} // namespace nova::econ::win_bag_flee
