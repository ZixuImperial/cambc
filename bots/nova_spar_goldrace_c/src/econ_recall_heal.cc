// econ_recall_heal.cc: Heal, shop and recall rules.
#include "econ_internal.h"
namespace nova::econ {
// the line for a body with upgrades or a dash. Called only below the fixed line, so the walk over the foes is rare.
// STRIPPED (FL5, Rule Checker 9 Nov): the HPL terms are gone, so this returns `line` for every HPL setting; arming HPL changes
// nothing. Restore first: deadstrip.py find HPL.
float upgraded_heal_line(float line, bool far)
{
	const float top = line;
	float v = top;
	return std::min(top, std::max(v, std::min(top, static_cast<float>(HPL_TAB[far ? 6 : 7]) / 100.0f)));
}
bool wants_heal()
{
	if (about_to_capture() || engaged_now())
		return false;
	if (GAME_END - now() <= EG_ROUNDS && W.me.gems >= 10 && bankable())
		return false; // the bag goes to the altar, not home
	if (finish_bank_bag())
		return false; // so does a finish bag
	float frac = W.me.frac();
	if (tsb_unhealed > 0.0f && tavi_layer::me() && W.me.maxhp - tsb_unhealed > 0.0f) // TSB 8: unhealed field Health is not missing HP
		frac = std::min(1.0f, W.me.hp / (W.me.maxhp - tsb_unhealed));
	if (M.ring && ring_gap && W.me.gems >= 10 && frac >= 0.25f && bank_dist_here() <= 8)
		return false; // the bag goes in through the gap before the heal recall
	// no heal recall at my target group while the camps hitting me deal at most EH_PCT % of my health a round and no enemy champion is
	// within EH_ENEMY_R.
	if (T.target >= 0 && T.target < M.ng && cheb(W.me.pos, M.groups[static_cast<std::size_t>(T.target)].anchor) <= EH_NEAR && (living_members_visible(T.target, nullptr) > 0)) // only while remains are in sight
	{
		bool enemy = false;
		for (const auto& e : W.enemies)
			if (cheb(e.pos, W.me.pos) <= EH_ENEMY_R)
			{
				enemy = true;
				break;
			}
		std::vector<mv::Threat> th_h;
		if (!enemy && incoming_at(W.me.pos, static_cast<std::vector<nova::mv::Threat> *>(nullptr)) * 100.0f <= static_cast<float>(EH_PCT) * W.me.hp) // FB1 bit 2 FL2: no list
			return false;
	}
	// A recall costs five turns wherever we are, so far from home it pays earlier.
	const int hd_h = home_dist();
	float thr = hd_h > 20 ? static_cast<float>(B438_HEALF_X100) / 100.0f : static_cast<float>(B438_HEALN_X100) / 100.0f;
	if (const int hpl_b = HPL_TAB[1]; hpl_b != 0) // above the highest possible line nothing changes
		if (frac < thr + ((hpl_b & HPL_BIT_REL) != 0 ? static_cast<float>(HPL_TAB[hd_h > 20 ? 13 : 14]) / 100.0f : 0.0f))
			thr = upgraded_heal_line(thr, hd_h > 20);
	return frac < thr;
}
bool finish_clear_ok()
{
	const Kit& k = *W.me.kit;
	if (!(heart_layer::kit(k) || varg_layer::kit(k) || ren_layer::kit(k)) || !engaged_now() || T.capturing || T.target < 0)
		return false;
	std::vector<mv::Threat> th;
	const float incoming = incoming_at(W.me.pos, &th);
	if (th.empty())
		return false;
	const Here here = crew_here(T.target);
	float hp_left = 0;
	const float dps = threat_kill_dps(here.crew, th, &hp_left);
	const float rounds = hp_left / dps;
	if (rounds > (4.0f)) // EB4 FNA limits
		return false;
	const float eff = W.me.hp + std::min(W.me.shield, incoming * static_cast<float>(std::max(1, W.me.shield_turns)));
	const float spent = incoming * (std::ceil(rounds) + 1.0f);
	bool ok = eff - spent >= std::max(PASSIVE_FINISH_KEEP * W.me.maxhp, 2.0f * incoming);
	// Small contested maps: an enemy known near (my sight, ward or a teammate's report in the last 8 rounds, about 12
	// tiles) arrives while I finish at low health. Leave as before.
	if (ok && intel::danger(W.me.pos, 12, 8) > 0.0f)
		ok = false;
	NLOG("r%d slot %d PASSIVE finish? hp %.0f left %.0f dps %.0f rounds %.1f incoming %.0f -> %d\n", now(), P.my_slot, W.me.hp,
		hp_left, dps, rounds, incoming, (int)ok);
	return ok;
}
// finish_clear_ok for every kit, tighter: the awake attackers in my reach (all of my target) die within 2 rounds with health to
// spare, and the rest of the target is in sight and harmless (0 Str), done within 3 rounds. The caller requires no enemy in sight
// within 8.
bool finish_low_camp_ok(float frac)
{
	if (T.target < 0 || T.target >= M.ng || T.capturing || frac < 0.08f)
		return false;
	if (intel::danger(W.me.pos, 12, 8) > 0.0f)
		return false;
	float fna_ra = 0.0f; // EB4 FNA: the attackers' rounds, for the arrival test at the end
	std::vector<mv::Threat> th;
	const float incoming = incoming_at(W.me.pos, &th);
	const Here here = crew_here(T.target);
	const float dps = std::max(30.0f, here.crew.dps(1));
	for (const auto& t : th)
	{
		const int ci = M.camp_index(t.pos);
		if (ci < 0 || M.camps[static_cast<std::size_t>(ci)].group != T.target)
			return false; // another group hits me: not this rule
	}
	if (!th.empty())
	{
		float hp_left = 0;
		const float kd = threat_kill_dps(here.crew, th, &hp_left);
		const float ra = hp_left / kd;
		if (ra > (2.0f))
			return false;
		fna_ra = ra;
		const float eff = W.me.hp + std::min(W.me.shield, incoming * static_cast<float>(std::max(1, W.me.shield_turns)));
		if (eff - incoming * (std::ceil(ra) + 1.0f) < std::max(0.05f * W.me.maxhp, incoming))
			return false;
	}
	float rest = 0;
	int alive = 0;
	bool near = false;
	for (int ci : M.groups[static_cast<std::size_t>(T.target)].members)
	{
		const auto& c = M.camps[static_cast<std::size_t>(ci)];
		if (!bbget(W.vis, c.pos))
			return false; // a member out of sight: its health is unknown
		if (!bbget(W.occ_camps, c.pos))
			continue;
		++alive;
		near |= cheb(c.pos, W.me.pos) <= 2;
		bool threat = false;
		for (const auto& t : th)
			threat |= t.pos == c.pos;
		if (threat)
			continue;
		if (c.str > 0.0f)
			return false; // a fighting camp still waits: more than a finish
		const VisCamp* vc = visible_camp(ci);
		rest += vc ? vc->hp : c.hp;
	}
	return alive > 0 && near && rest / dps <= 3.0f;
}
// finish my part-done target before a shop recall. Reached only when the shop would fire.
static bool finish_target_before_shop()
{
	if (T.target < 0 || T.capturing || gmem_size(mem) != static_cast<std::size_t>(M.ng) || fuel() < 15000)
		return false;
	const int gi = T.target;
	const auto& g = M.groups[static_cast<std::size_t>(gi)];
	const auto& m = mem[static_cast<std::size_t>(gi)];
	if (m.status != GS_ALIVE && m.status != GS_CLEARED)
		return false;
	const float left = m.status == GS_CLEARED ? 0.0f : m.hp_left;
	if (left < 0 || left >= g.hp || !living_attackers(gi, true).empty())
		return false;
	int dm = BIG;
	for (int ci : g.members)
		dm = std::min(dm, cheb(W.me.pos, M.camps[static_cast<std::size_t>(ci)].pos));
	if (dm > EH_NEAR)
		return false;
	std::vector<mv::Threat> th;
	if (incoming_at(W.me.pos, static_cast<std::vector<nova::mv::Threat> *>(nullptr)) * 100.0f > static_cast<float>(EH_PCT) * W.me.hp) // FB1 bit 2 FL2: no list
		return false;
	const Here here = crew_here(gi);
	const int need = static_cast<int>(std::ceil(left / std::max(30.0f, here.crew.dps(1)))) + 1 + (rs::capture_pay(mu::on(mu::B_GOLD) && prism::has_family(rs::F_CAPTURE))); // v699 R2B bit 8192 E6: my or an allied Capture holder on the region (GR:196) // my Capture (EB4 E6: the emblem alone sets the price, GameRules:196)
	if (need > (cbn_recall_t()) + home_dist())
		return false;
	for (const auto& e : W.enemies)
		if (cheb(e.pos, W.me.pos) <= need)
			return false;
	vec2 seen[16];
	const int ns = std::min(16, intel::recent_own(seen, 16, ESH_SEEN));
	for (int i = 0; i < ns; ++i)
		if (cheb(seen[i], W.me.pos) <= need + ESH_SEEN)
			return false;
	return true;
}
// finish mode, a gem target in reach, and the trip costs more than the gold buys before the game ends.
static bool finish_mode_hold()
{
	if (!finish_mode(0) || T.target < 0 || gmem_size(mem) != static_cast<std::size_t>(M.ng) || fuel() < 15000)
		return false;
	const int gi = T.target;
	const auto& g = M.groups[static_cast<std::size_t>(gi)];
	if (g.gems <= 0 || mem[static_cast<std::size_t>(gi)].status == GS_CLEARED)
		return false;
	const std::array<int, 3>* old = nullptr;
	for (const auto& h : eg_hist)
		if (now() - h[0] >= 200)
			old = &h;
	const float span = static_cast<float>(old ? now() - (*old)[0] : std::max(1, now()));
	const float ru = static_cast<float>(W.tributed_us - (old ? (*old)[1] : 0)) / span;
	const float rt = static_cast<float>(W.tributed_them - (old ? (*old)[2] : 0)) / span;
	float h = static_cast<float>(GAME_END - now());
	if (ru > 0)
		h = std::min(h, static_cast<float>(std::max(0, rs::WIN_TRIBUTE - static_cast<int>(W.tributed_us))) / ru);
	if (rt > 0)
		h = std::min(h, static_cast<float>(std::max(0, rs::WIN_TRIBUTE - static_cast<int>(W.tributed_them))) / rt);
	if (static_cast<float>(target_walk(W.me.pos, g.anchor)) > h)
		return false;
	const float trip = static_cast<float>((cbn_recall_t()) + home_dist());
	const float gain = (static_cast<float>(W.gold) / 30.0f) / static_cast<float>(own.shards + ESH_BASE);
	return gain * (h - trip) <= trip;
}
// FSR bit 1 (b1769): on a far map (max side >= FSR_SIDE) a healthy body (HP >= RD_HURT %) more than 12 from home has no shop reason to
// recall below the next item's cost + FSR_EXTRA gold. One test for want_shop, capture_recall's shop reason and the travel recall.
bool fsr_blocks_shop(int gold)
{
	if (std::max(G.w, G.h) < FSR_TAB[3] || W.me.frac() * 100.0f < static_cast<float>(RD_HURT) || home_dist() <= 12)
		return false;
	return gold < next_emblem_cost() + FSR_TAB[2];
}
// FB12 row 1: the caller passes its own next_emblem_cost() (one engine read per call, not two).
bool fsr_blocks_shop(int gold, int cost)
{
	if (std::max(G.w, G.h) < FSR_TAB[3] || W.me.frac() * 100.0f < static_cast<float>(RD_HURT) || home_dist() <= 12)
		return false;
	return gold < cost + FSR_TAB[2];
}
bool want_shop()
{
	if (GAME_END - now() <= EG_ROUNDS || (W.me.gems > 0 && finish_mode(0)))
		return false; // an item bought now buys nothing that still counts
	if (M.ring && ring_gap && W.me.gems >= 10 && bank_dist_here() <= 8)
		return false; // the bag goes in through the gap first
	// the two best camp tanks (they hold camps and front fights) shop at the item's cost, every 20 rounds, below 90% HP, with 60 gold
	// to spare or within 16 of home; everyone else keeps the base rule (eager shopping for all costs fights).
	const bool eager = P.my_slot >= 0 && P.tank_order[static_cast<std::size_t>(P.my_slot)] <= 1;
	if (W.on_spawn || tavi_layer::recall_skip_shop() || now() - S.recall_round < (eager ? 20 : 30))
		return false;
	if (about_to_capture() || engaged_now())
		return false;
	if (static_cast<int>(W.gold) < (eager ? 30 : std::max(30, B467_SHOPMIN)))
		return false; // no next item costs less than 30, so the answer below is false: skip the list build
	const int cost = next_emblem_cost();
	const int gold = static_cast<int>(W.gold);
	if (gold < (eager ? cost : std::max(cost, B467_SHOPMIN)))
		return false;
	const float frac = W.me.frac();
	if (frac * 100.0f >= static_cast<float>(RD_HURT))
	{
		// far from home a shop trip costs the walk back; buy more per trip
		const int hd = home_dist();
		if (hd > RD_D0 && gold < (eager ? cost : std::max(cost, B467_SHOPMIN)) + RDS_V * (hd - RD_D0))
			return false;
	}
	if (fsr_blocks_shop(gold, cost)) // FSR bit 1 (b1769): on far maps a healthy body shops with a bigger order
		return false;
	const bool ws = eager ? (frac < 0.9f || gold >= cost + 60 || home_dist() <= 16)
	                      : (frac < 0.8f || gold >= cost + (120) || home_dist() <= 12);
	return ws && !(finish_target_before_shop()) && !(finish_mode_hold());
}
bool recall_safe()
{
	if (W.on_spawn)
		return false;
	bool out = false; // low, far from home, contact broken
	if ((W.me.frac()) < 0.5f && home_dist() >= 11) // v699 R2B bit 4096 TFH2: unhealed field Health is not missing HP
	{
		int nd = BIG;
		for (const auto& e : W.enemies)
			nd = std::min(nd, cheb(e.pos, W.me.pos));
		out = nd >= RECALL_OUT;
		// contact is broken only when no visible foe can reach me during the channel (its turns, dash, reach)
		if (out && !W.enemies.empty())
		{
			const int n = foe_turns_during_recall();
			for (const auto& e : W.enemies)
			{
				if (cheb(e.pos, W.me.pos) <= foe_reach_in_turns(e, n))
				{
					out = false;
					break;
				}
			}
		}
	}
	if (now() - S.hurt <= (out ? 1 : 2))
		return false;
	bool low = false; // low and every seen foe clearly out of its reach
	if (!out && (W.me.frac()) < (static_cast<float>(B467_LOWREC_X100) / 100.0f)) // v699 R2B bit 4096 TFH2
	{
		low = true;
		for (const auto& e : W.enemies)
		{
			const int dash = (e.kit && e.kit->slot_dash >= 0) ? 2 : 0;
			const int spell = (e.kit && (e.kit->slot_dmg >= 0 || e.kit->slot_aoe >= 0 || e.kit->slot_cc >= 0)) ? 4 : 0;
			const int d = cheb(e.pos, W.me.pos);
			if (d < 4 || d <= std::max({ e.range, 1, spell }) + dash + 2)
			{
				low = false;
				break;
			}
		}
	}
	if ((out || low) && (W.me.frac()) < 0.35f && combat::recall_bush_threat()) // v699 R2B bit 4096 TFH2
	{
		out = false; // a foe that just stepped into a bush beside me has not broken contact
		low = false;
	}
	if (!out && !low && now() - S.enemy_close <= 4)
		return false;
	if (now() - S.recall_cancel < 3)
		return false;
	for (const auto& vc : W.camps)
	{
		const auto& c = M.camps[static_cast<std::size_t>(vc.ci)];
		if (vc.awake && c.attacks() && cheb(c.pos, W.me.pos) <= c.reach + 1)
			return false;
	}
	if (now() - S.hurt_unseen <= 8)
	{
		std::vector<mv::Threat> th;
		hidden_camp_threats(W.me.pos, th);
		if (!th.empty())
			return false;
	}
	return true;
}
static int rlg_skip_chain = -1000; // v707 RC5 RLG2: the chain that already pushed sc_skip_until
// -1: not such a start (no record); 0: refuse it; 1: allow it and record it.
static int recall_loop_guard()
{
	if (W.me.hp < 0.9f * W.me.maxhp)
		return -1;
	const vec2 me = W.me.pos;
	for (const auto& e : W.enemies)
		if (cheb(e.pos, me) <= 8)
			return -1;
	const int gems = static_cast<int>(W.me.gems);
	const bool chain = rcg_n > 0 && cheb(rcg_pos, me) <= RCG_R && now() - rcg_round <= RCG_ROUNDS && gems == rcg_gems &&
					   rcg_shop < rcg_last && (std::max(S.recall_cancel, S.orc_cancel)) < rcg_last;
	if (chain && rcg_n >= RCG_N)
	{
		if (stranded()) // v707 RC5 RLG1: no walk leads home, so a refusal strands the body
		{
			RLG1_CNT(true);
			if (rlg_cast_gi >= 0 && rlg_cast_gi < M.ng && rlg_cast_round >= rcg_round) // the loop is a crystal trip: break it at home
				mem[static_cast<std::size_t>(rlg_cast_gi)].fail_until = std::max(mem[static_cast<std::size_t>(rlg_cast_gi)].fail_until, now() + RCL_SC_SKIP);
			sc_skip_until = std::max(sc_skip_until, now() + RCL_SC_SKIP);
			return 1;
		}
		if (rlg_skip_chain != rcg_round)
		{
			sc_skip_until = std::max(sc_skip_until, now() + RCL_SC_SKIP);
			rlg_skip_chain = rcg_round;
		} // the callers walk, crystal trips too
		NLOG("r%d slot %d RC_GUARD refused recall %d at %d,%d gems %d\n", now(), P.my_slot, rcg_n + 1, me.x, me.y, gems);
		return 0;
	}
	return 1;
}
static void recall_loop_guard_record(int g)
{
	if (g <= 0)
		return;
	const vec2 me = W.me.pos;
	const int gems = static_cast<int>(W.me.gems);
	const bool chain = rcg_n > 0 && cheb(rcg_pos, me) <= RCG_R && now() - rcg_round <= RCG_ROUNDS && gems == rcg_gems &&
					   rcg_shop < rcg_last && (std::max(S.recall_cancel, S.orc_cancel)) < rcg_last;
	if (chain)
		++rcg_n;
	else
	{
		rcg_pos = me;
		rcg_round = now();
		rcg_gems = gems;
		rcg_n = 1;
	}
	rcg_last = now();
}
// recall_safe's tests other than the foes' reach (hurt, a recent cancel, awake camps, unseen hits).
static bool carry_recall_gate()
{
	if (W.on_spawn || now() - S.hurt <= 1 || now() - S.recall_cancel < 3 || now() - S.hurt_unseen <= 8 || home_dist() <= csx_recall_t())
		return false;
	for (const auto& vc : W.camps)
	{
		const auto& c = M.camps[static_cast<std::size_t>(vc.ci)];
		if (vc.awake && c.attacks() && cheb(c.pos, W.me.pos) <= c.reach + 1)
			return false;
	}
	return true;
}
bool go_home()
{
	AF_CHECK();
	if (W.on_spawn)
		return false;
	// a hurt body walking home (low health, heal or shop recall) never steps back into an awake camp's reach: its homeward scan pathed
	// through the reach it had just left (see mv::AvoidCampReach).
	bool b957_trap = false;
	if (W.me.frac() >= 0.5f && camp_escape_guard_on() && mv::spawn_in_camp_reach())
	{
		b957_trap = true;
		b957_gh_round = now(); // camp_out stands down next turn so this walk reaches the spawn
	}
	const mv::AvoidCampReach guard(W.me.frac() < 0.5f || (!b957_trap && camp_escape_guard_on()));
	const distance_field* hf = mv::home_field();
	PROF("gh_field");
	if (home_dist() <= 7 && hf && !(home_dist() > csx_recall_t() && recall_safe()) && mv::step_field(*hf)) // a safe recall that lands sooner than the walk goes first
		return true;
	if (recall_safe())
		return start_recall();
	if (carry_recall_gate() && nova::econ::carry_recall::ok(foe_turns_during_recall(sps_pending), sps_pending)) // the foes can't kill the bag before the recall lands (BB8_ON(1): per foe)
	{
		nova::econ::carry_recall::fired_rec();
		return start_recall();
	}
	PROF("gh_safe");
	// Not safe to channel: walk out of every reach, toward home when that is as good. Whole-board operations: a
	// per-tile scan of the 13x13 window against every threat cost 40-60k fuel.
	const auto th = recall_threats();
	PROF("gh_threats");
	if (!th.empty() && W.can_move() && fuel() < 35000)
		return mv::escape(th) || (hf && mv::step_field(*hf)); // review i2 (from planner c4): skip the scan late in a turn
	if (!th.empty() && W.can_move())
	{
		swd_block = static_cast<int>(W.round); // SWD: a walk clear of the threats keeps the dash
		const vec2 me = W.me.pos;
		const std::uint16_t hd = hf ? dfget(*hf, me) : UNREACH;
		bitboard danger;
		for (const auto& x : th)
			if (x.reach >= 0 && (cheb(x.pos, me) <= 6 + x.reach)) // a negative radius throws
				danger.draw_chebyshev(x.pos, static_cast<float>(x.reach));
		bitboard goals;
		goals.draw_chebyshev(me, 6.0f);
		goals &= ~danger;
		goals &= ~mv::blocked();
		bitboard homeward;
		bool any = false, any_home = false;
		if (hf && hd != UNREACH)
		{
			const FView fv = fview(*hf);
			bbforeach_near(goals, me, 6,
				[&](vec2 t)
				{
					any = true;
					if (fv(t) <= hd)
					{
						bbset(homeward, t);
						any_home = true;
					}
				});
		}
		else
			any = bbany(goals);
		PROF("gh_scan");
		if (any_home) // no tile nearer home in reach: walk clear of the foes that refuse the recall
		{
			bool lower = false;
			const FView fv = fview(*hf);
			bbforeach_near(homeward, me, 6, [&](vec2 t) { lower = lower || fv(t) < hd; });
			if (!lower)
			{
				bitboard clear_of = goals, refuse;
				for (const auto& x : th)
					if (x.reach >= 0 && cheb(x.pos, me) <= 6 + x.reach + 5)
						refuse.draw_chebyshev(x.pos, static_cast<float>(x.reach + 5));
				clear_of &= ~refuse;
				if (bbany(clear_of) && mv::step_to_set(clear_of, 14))
					return true;
			}
		}
		if (any_home && mv::step_to_set(homeward, 14))
			return true;
		if (any && mv::step_to_set(goals, 14))
			return true;
		if (mv::escape(th))
			return true;
	}
	// Nothing to escape (or no way out): walk home; the recall follows once it is safe.
	return hf && mv::step_field(*hf);
}
void on_recall()
{
	T.engaged = false;
	T.wait_since = -1;
	S.recalling = true;
	S.recall_round = now();
	hs3_commit_g = -1; // HSC bit 1: no shortcut commit survives a recall
}
void orc_own_cancel()
{
	S.recalling = false; // ORC bit 1: not a damage cancel
	S.orc_cancel = now();
}
// called on every dead turn. Keeps the target (refresh_target re-rates it on the first live turn).
void death_reset()
{
	rhl_rec = -1; // a death is not a hop loop
	T.engaged = false;
	T.capturing = false;
	T.wait_since = -1;
	T.bench_until = -1000;
	T.self_tank = false;
	T.eval_round = -1000;
	if (SC.on && !SC.used)
		sc_end(); // v676 DRS bit 2: a trip abandoned by death
	reg_gi = -1; // v676 DRS bit 4: the region clock restarts after a death
	hs3_commit_g = -1; // v676 DRS bit 16: no shortcut commit survives a death
	T.filler_until = -1000; // v678 FX7 bit 16: no filler or chip budget survives a death
	frl_chip_gi = -1;
	frl_chip_until = -1000;
}
} // namespace nova::econ

namespace nova::econ {
// the flag is read by the caller.
bool crystal_use_ready(float* camp_dmg)
{
	if (crystals_carried() <= 0)
		return false;
	*camp_dmg = incoming_at(W.me.pos, nullptr);
	return true;
}
bool use_crystal_consumable(vec2 t, bool* hidden)
{
	std::int32_t ok = 0;
	*hidden = false;
	try
	{
		cancel_spin_before_action();
		if (cambc::detail::sdk_use_consumable(RAW_CRYSTAL, t.x, t.y, &ok) == 0 && ok)
		{
			crystal_count = 0;
			crystal_checked = now();
			refresh_self(); // the channel: later steps of this turn see it
			return true;
		}
		*hidden = true;
	}
	catch (...)
	{
		FXR_PASS();
	}
	return false;
}
// On our spawn, with walled-off groups on the map and no crystal carried, buy one (10 gold).
void buy_crystal()
{
	if (!W.on_spawn || W.gold < 10 || W.round < 20 || !any_teleport_groups() || crystals_carried() > 0)
		return;
	cancel_spin_before_action();
	if (cambc::detail::sdk_buy_consumable(RAW_CRYSTAL) == 0)
	{
		W.gold -= 10;
		crystal_count = 1;
		crystal_checked = now();
	}
}
// On a map with a crystal route, a body on our spawn or dead holds one before it shops.
void spawn_crystal_prebuy()
{
	if (!sc_any_r || W.gold < 10 || (W.alive && !W.on_spawn) || crystals_carried() > 0)
		return;
	cancel_spin_before_action();
	if (cambc::detail::sdk_buy_consumable(RAW_CRYSTAL) == 0)
	{
		W.gold -= 10;
		crystal_count = 1;
		crystal_checked = now();
	}
}
// a route that saves RWK_BIG+ rounds (the altar or my target) gets its crystal before the shop spends the gold.
void recall_hop_prebuy()
{
	if (crystal_gems_scarce() && crystal_plan_trip_body(my_slot()) && W.gold >= 10 && (!W.alive || W.on_spawn) && crystals_carried() <= 0)
	{
		cancel_spin_before_action();
		if (cambc::detail::sdk_buy_consumable(RAW_CRYSTAL) == 0)
		{
			W.gold -= 10;
			crystal_count = 1;
			crystal_checked = now();
		}
		return;
	}
	if (!rh_any || !sc_any_r || W.gold < 10 || (W.alive && !W.on_spawn) || crystals_carried() > 0)
		return;
	const bool big = (sc_bank_f == &bank_field() && sc_bank_r.cost != UNREACH && sc_bank_r.save >= RWK_TAB[3]) ||
		(!(!W.alive) && T.target >= 0 && static_cast<std::size_t>(T.target) < sc_grp.size() && sc_grp[static_cast<std::size_t>(T.target)].cost != UNREACH && sc_grp[static_cast<std::size_t>(T.target)].save >= RWK_TAB[3]);
	if (big) // a bag's RWK_SAVE+ hop keeps its crystal from the shop
		spawn_crystal_prebuy();
}

// true on a map where some gem group or altar is walked RWK_BIG+ rounds more than a hop from the spawn could need (decided once).
__attribute__((always_inline)) bool recall_hop_early()
{
	static int v = -1;
	if (v < 0 && M.has_home && M.groups_ready())
	{
		int x0 = 1 << 20, x1 = -1, y0 = 1 << 20, y1 = -1;
		bbforeach(M.my_spawn, [&](vec2 p) { x0 = std::min(x0, p.x); x1 = std::max(x1, p.x); y0 = std::min(y0, p.y); y1 = std::max(y1, p.y); });
		const auto bound = [&](vec2 p, int dh)
		{
			const int ch = std::max(std::max({ x0 - p.x, 0, p.x - x1 }), std::max({ y0 - p.y, 0, p.y - y1 }));
			return dh - std::max(0, ch - 3) - 4;
		};
		int best = 0;
		for (const auto& g : M.groups)
			if (g.gems > 0 && g.d_home != UNREACH && g.access == ACC_WALK)
				best = std::max(best, bound(g.anchor, g.d_home));
		for (const auto& a : M.altars)
			if (a.d_home != UNREACH && a.access == ACC_WALK)
				best = std::max(best, bound(a.pos, a.d_home));
		v = best >= RWK_TAB[3] ? 1 : 0;
	}
	return v == 1;
}
// one crystal plan a turn out of what is really left, last in the turn. The caller reads the flag.
void crystal_plan_background_slow();
// inlined: the first early-out test runs at the call site, the rest out of line
__attribute__((always_inline)) void crystal_plan_background()
{
	if (!M.done())
		return;
	crystal_plan_background_slow();
}
__attribute__((noinline)) void crystal_plan_background_slow()
{
	if (!M.done())
		return;
	const bool sc = crystal_gems_scarce();
	if ((sc ? !crystal_plan_trip_body(my_slot()) : false) || fuel() < 30000) // non-scarce maps too
		return;
	// the last scan found no group; none can qualify before cpb_next while no plan changed (cp_gen)
	static int cpb_gen = -1, cpb_next = 0;
	static bool cpb_sc = false;
	if (cpb_gen == cp_gen && cpb_sc == sc && cplans.size() == static_cast<std::size_t>(M.ng) && now() < cpb_next)
		return;
	// the crystal-access groups, listed once (access is fixed once the map analysis is done): both scans below visit only them, in the
	// same ascending order.
	static std::vector<std::uint16_t> tpl;
	static std::size_t tpl_n = static_cast<std::size_t>(-1);
	if (tpl_n != static_cast<std::size_t>(M.ng))
	{
		tpl_n = static_cast<std::size_t>(M.ng);
		tpl.clear();
		for (std::size_t i = 0; i < static_cast<std::size_t>(M.ng); ++i)
			if (M.groups[i].access == ACC_TP)
				tpl.push_back(static_cast<std::uint16_t>(i));
	}
	const int cpr_gi = crystal_plan_partial_gi(); // v698 CPSCANR: a part-done scan's group goes first (same tests as the loop)
	for (int pass = cpr_gi >= 0 ? 0 : 1; pass < 2; ++pass)
		for (const std::uint16_t ti : tpl)
		{
			const std::size_t i = ti;
			if (pass == 0 && static_cast<int>(i) != cpr_gi)
				continue;
			const auto& g = M.groups[i];
			if (g.access != ACC_TP || g.gems + g.gold <= 0 || (i < cplans.size() && (cplans[i].done || now() < cplans[i].retry)))
				continue;
			if (!sc && static_cast<float>(g.gems) + 0.1f * static_cast<float>(g.gold) < CRYSTAL_MIN_V)
				continue; // crystal_ok's value bar off a scarce map
			cp_in_bg = true;
			crystal_plan(static_cast<int>(i));
			cp_in_bg = false;
			return;
		}
	if (cplans.size() == static_cast<std::size_t>(M.ng))
	{
		int nx = 1 << 30; // the earliest retry round of a group that only waits on its retry
		for (const std::uint16_t ti : tpl)
		{
			const std::size_t i = ti;
			const auto& g = M.groups[i];
			if (g.access != ACC_TP || g.gems + g.gold <= 0 || cplans[i].done)
				continue;
			if (!sc && static_cast<float>(g.gems) + 0.1f * static_cast<float>(g.gold) < CRYSTAL_MIN_V)
				continue;
			nx = std::min(nx, cplans[i].retry);
		}
		cpb_gen = cp_gen;
		cpb_sc = sc;
		cpb_next = nx;
	}
}
// the landing list, then the group and bank routes, in spare fuel.
void spawn_crystal_background_slow(long reserve);
// inlined: the first early-out test runs at the call site, the rest out of line
__attribute__((always_inline)) void spawn_crystal_background(long reserve)
{
	if (!M.done())
		return;
	spawn_crystal_background_slow(reserve);
}
__attribute__((noinline)) void spawn_crystal_background_slow(long reserve)
{
	if (!M.done())
		return;
	try
	{
		if (spawn_crystal_prep(reserve))
			spawn_crystal_routes(reserve);
	}
	catch (...)
	{
		FXR_PASS();
	}
}
} // namespace nova::econ

namespace nova::econ {
} // namespace nova::econ

namespace nova::econ {
} // namespace nova::econ

namespace nova::econ {
bool hoard_crew_decide();
int hc_mode_v = 0; // 0 = none (dom_loop = DOM), 3 = hoard mode, 4 = DOM + hoard
int hr_pend = 0; // 0 = decided, else the round from which a free slot with enough fuel may decide
bool hoard_region_late();
// dom_commit_decide plus the hoard decision, off dom_commit_free_slot's steady-state path.
__attribute__((noinline)) int dom_commit_decide_hoard()
{
	const int s = dom_commit_decide();
	if (s != 0 && hoard_crew_decide())
	{
		hc_mode_v = s == 2 ? 4 : 3;
		return 2;
	}
	return s;
}
// main's free slot (after the turn's last fuel read): decide the trigger once.
bool dom_commit_free_slot_slow();
// inlined: the first early-out test runs at the call site, the rest out of line
__attribute__((always_inline)) bool dom_commit_free_slot()
{
	if (hr_pend == 0 && dc_state != 0)
		return false;
	return dom_commit_free_slot_slow();
}
__attribute__((noinline)) bool dom_commit_free_slot_slow()
{
	if (hr_pend != 0 && dc_state == 1 && now() >= hr_pend && fuel() >= HR_FUEL)
		return hoard_region_late(); // the deferred decision
	if (!rsw(RSW_DOM_COMMIT) || dc_state != 0 || fuel() < DC_DECIDE_FUEL)
		return false;
	dc_state = dom_commit_decide_hoard(); // the one-time decision also decides the hoard mode (2 = enter dom_loop)
	return dc_state == 2;
}
int dc_mode() { return hc_mode_v; }
// Regions of attacker-free walkable gem groups (low contest) whose bounding boxes chain within a set Chebyshev gap; a region of 2 or
// more groups (up to a set maximum) with enough gems (or, with the second flag bit, enough groups with enough gems) at gem-weighted
// contest under a set cap is a hoard (table value = 2 + region id). A candidate group costs ~1.2k fuel in release, so the pass is
// resumable: it works in slices while enough fuel is left and later free slots (no DOM) continue it (hr_pend = the round from which
// to continue; 0 = decided). Never more than HR_MAXG candidates (a field of clusters).
namespace hrs
{
int stage = 0, gi = 0, k = 0, a = 0;
std::array<int, HR_MAXG> cand;
std::array<short, HR_MAXG> x0, y0, x1, y1;
std::array<signed char, HR_MAXG> par;
} // namespace hrs
__attribute__((noinline)) void hoard_region_decide()
{
	using namespace hrs;
	hr_pend = 0;
	auto is_cand = [](const auto& h) {
		return h.n_att == 0 && h.gems > 0 && h.access == ACC_WALK && h.d_home != UNREACH && !h.members.empty() &&
			h.contest * 100.0f <= static_cast<float>(HR_CMEM_X100);
	};
	auto later = []() {
		if (now() < HR_LATE_END)
			hr_pend = now() + 1; // continue in a later free slot
	};
	const int ng = M.ng;
	if (stage == 0)
	{
		stage = 1;
		gi = 0;
		k = 0;
	}
	const int nc = M.nc;
	for (; stage == 1 && gi < ng; ++gi)
	{
		if (fuel() < HR_SLICE)
			return later(); // every group: a slice never runs past the turn (an overrun suspends the next turn's start)
		const auto& h = M.groups[static_cast<std::size_t>(gi)];
		if (!is_cand(h))
			continue;
		if (k >= HR_MAXG)
		{
			stage = 3; // a field of clusters: decided, no region
			return;
		}
		short xa = 32000, ya = 32000, xb = -32000, yb = -32000;
		for (int m : h.members)
			if (m >= 0 && m < nc)
			{
				const vec2 p = M.camps[static_cast<std::size_t>(m)].pos;
				xa = std::min(xa, static_cast<short>(p.x));
				ya = std::min(ya, static_cast<short>(p.y));
				xb = std::max(xb, static_cast<short>(p.x));
				yb = std::max(yb, static_cast<short>(p.y));
			}
		if (xb < xa)
			continue;
		int q = k++; // insertion by left edge (the sweep needs x0 ascending)
		while (q > 0 && x0[static_cast<std::size_t>(q - 1)] > xa)
		{
			const auto u = static_cast<std::size_t>(q), v = static_cast<std::size_t>(q - 1);
			cand[u] = cand[v];
			x0[u] = x0[v];
			y0[u] = y0[v];
			x1[u] = x1[v];
			y1[u] = y1[v];
			--q;
		}
		const auto u = static_cast<std::size_t>(q);
		cand[u] = gi;
		x0[u] = xa;
		y0[u] = ya;
		x1[u] = xb;
		y1[u] = yb;
	}
	if (stage == 1)
	{
		if (k < 2)
		{
			stage = 3;
			return;
		}
		for (int j = 0; j < k; ++j)
			par[static_cast<std::size_t>(j)] = static_cast<signed char>(j);
		stage = 2;
		a = 0;
	}
	auto find = [](int x) {
		while (par[static_cast<std::size_t>(x)] != x)
		{
			par[static_cast<std::size_t>(x)] = par[static_cast<std::size_t>(par[static_cast<std::size_t>(x)])];
			x = par[static_cast<std::size_t>(x)];
		}
		return x;
	};
	for (; stage == 2 && a < k; ++a)
	{
		if (fuel() < HR_SLICE)
			return later();
		const auto ua = static_cast<std::size_t>(a);
		for (int b = a + 1; b < k; ++b)
		{
			const auto ub = static_cast<std::size_t>(b);
			if (x0[ub] - x1[ua] > HR_RAD)
				break; // later boxes start farther right
			if (y0[ub] - y1[ua] > HR_RAD || y0[ua] - y1[ub] > HR_RAD || x0[ua] - x1[ub] > HR_RAD)
				continue;
			const int ra = find(a), rb = find(b);
			if (ra != rb)
				par[static_cast<std::size_t>(ra)] = static_cast<signed char>(rb);
		}
	}
	if (stage != 2)
		return;
	if (fuel() < HR_SLICE + 2000L)
		return later();
	stage = 3;
	std::array<int, HR_MAXG> sum, cnt, id;
	std::array<float, HR_MAXG> wc;
	sum.fill(0);
	cnt.fill(0);
	wc.fill(0.0f);
	id.fill(-1);
	for (int j = 0; j < k; ++j)
	{
		const auto& h = M.groups[static_cast<std::size_t>(cand[static_cast<std::size_t>(j)])];
		const int r = find(j);
		par[static_cast<std::size_t>(j)] = static_cast<signed char>(r);
		const auto ur = static_cast<std::size_t>(r);
		sum[ur] += h.gems;
		cnt[ur] += 1;
		wc[ur] += static_cast<float>(h.gems) * h.contest;
	}
	for (int j = 0; j < k; ++j)
	{
		const auto r = static_cast<std::size_t>(j);
		if (par[r] != j || cnt[r] < 2 || cnt[r] > HR_MAXRG || hoard_region_sums().size() >= 250)
			continue;
		const bool big = sum[r] >= HC_GEMS;
		if (!big || wc[r] * 100.0f > static_cast<float>(HC_CMAX_X100) * static_cast<float>(sum[r]))
			continue;
		id[r] = static_cast<int>(hoard_region_sums().size());
		hoard_region_sums().push_back(sum[r]);
	}
	if (hoard_region_sums().empty())
		return;
	if (hoard_flags().empty())
		hoard_flags().assign(static_cast<std::size_t>(M.ng), 0);
	for (int q = 0; q < k; ++q)
	{
		const int r = id[static_cast<std::size_t>(par[static_cast<std::size_t>(q)])];
		if (r >= 0)
			hoard_flags()[static_cast<std::size_t>(cand[static_cast<std::size_t>(q)])] = static_cast<std::uint8_t>(2 + r);
	}
	hc_state = 2;
}
// The opening simulation ran (or started) in mode 0: every body re-runs it in the hoard mode (same inputs on every body).
void hoard_crew_reopen()
{
	if (now() < 30 && (OP.started || opened) && !T.engaged && !T.capturing)
	{
		OP.started = false;
		OP.sim = false;
		drop_target(0); // the mode-0 target goes too: refresh_target's post-opening switch test reads travel[T.target] (empty in the opening)
		opened = false;
		op_prestepped = true;
		T.eval_round = -1000;
	}
}
// a decision deferred for fuel (no DOM, no single hoard): the first free slot with HR_FUEL left decides it.
__attribute__((noinline)) bool hoard_region_late()
{
	hoard_region_decide();
	if (hc_state != 2)
		return false;
	hoard_crew_reopen();
	hc_mode_v = 3;
	dc_state = 2;
	return true;
}
// decided once with the dom-commit trigger (dom_commit_free_slot, after the turn's last fuel read).
bool hoard_crew_decide()
{
	if (hc_state != 0 || !M.ready() || M.groups.empty() || gmem_size(mem) != static_cast<std::size_t>(M.ng))
		return false;
	hc_state = 1;
	for (std::size_t i = 0; i < static_cast<std::size_t>(M.ng); ++i)
	{
		const auto& h = M.groups[i];
		if (h.n_att == 0 && h.gems >= HC_GEMS && h.access == ACC_WALK && h.contest * 100.0f <= static_cast<float>(HC_CMAX_X100))
		{
			if (hoard_flags().empty())
				hoard_flags().assign(static_cast<std::size_t>(M.ng), 0);
			hoard_flags()[i] = 1;
			hc_state = 2;
		}
	}
	if (hc_state != 2)
	{
		hoard_region_decide(); // no single hoard; a region of small attacker-free gem groups may be one (may defer)
	}
	if (hc_state != 2)
		return false;
	hoard_crew_reopen();
	return true;
}
void dom_commit_note(float ratio)
{
	dc_note_round = now();
	dc_ratio_v = ratio;
}
// the ring escape turned back a bank walk that can't pay: farm a while (want_bank's ring_off).
void abort_ring_bank_walk()
{
	if (M.ring && pf_bw_round >= now() - 1)
		ring_bank_off = now() + 40;
}
bool mul_mate_ls(int s, float& str, float& foc, float& maxhp, bool& died) { return mate_last_seen_stats(s, str, foc, maxhp, died); }
} // namespace nova::econ
// macros local to this module end here
#undef CSX_RCT
#undef CXL_NOTE
#undef EXPV
#undef FG_FORM_OK
#undef FXP_EXP_NOTE

// recall a carried bag out of a dead-end. Reached only with RCD_BITS set (the go_home hook reads the flag first).
namespace nova::econ::carry_recall
{
namespace
{
// The most damage foe e at Chebyshev d can deal me in its next n turns: basic hits from the turn it reaches (melee walks and hits,
// ranged walks or hits; + one hit with a reset ready by then), a dash ready by its last turn closes dash_range once (+ its landing
// damage), each damage spell once if ready by its last turn (cooldown c: ready on turn c + 1) and in range after its walks (a
// walk-excluding spell walks one turn less). A channelling foe is counted as acting at once (it may cancel and act).
float foe_dmg(const Body& e, int d, int n)
{
	const int R = std::max(e.range, 1);
	if (!e.kit || !e.kit->valid)
		return d - n - 2 <= R ? e.str * static_cast<float>(n) + 4.0f * e.foc : 0.0f; // unknown kit: hits every turn and a spell
	const Kit& k = *e.kit;
	auto by = [&](int s) { return s >= 0 && s <= 1 && foe_cd(e, s) <= n - 1; }; // ready by its n-th turn
	const int dash = by(k.slot_dash) ? static_cast<int>(k.dash_range) : 0;
	int hits = 0;
	for (int t = 1; t <= n; ++t)
		hits += d - ((k.ranged ? t - 1 : t) + dash) <= R ? 1 : 0;
	if (hits > 0 && by(k.slot_reset))
		++hits;
	float dmg = static_cast<float>(hits) * e.str;
	if (dash > 0 && k.dash_mod > 0 && d <= dash + static_cast<int>(k.dash_radius) + n)
		dmg += k.dash_mod * e.foc;
	auto spell = [&](int s, float mod, float range, float radius, bool excl)
	{
		if (mod <= 0 || !by(s))
			return;
		if (d - ((excl ? n - 1 : n) + dash) <= static_cast<int>(range + radius))
			dmg += mod * e.foc;
	};
	spell(k.slot_dmg, k.dmg_mod, k.dmg_range, 0.0f, k.dmg_excl);
	spell(k.slot_cc, k.cc_mod, k.cc_range, 0.0f, k.cc_excl);
	spell(k.slot_aoe, k.aoe_mod, k.aoe_range, k.aoe_radius, k.aoe_excl);
	return dmg;
}
} // namespace
bool ok(int n, bool prefired) // prefired: BB8_ON(1)
{
	if (static_cast<int>(W.me.gems) < RCD_TAB[3] || n <= 0)
		return false;
	float sum = 0;
	auto add = [&](const Body& e)
	{
		const int d = cheb(e.pos, W.me.pos);
		if (e.hp > 0 && d <= RCD_TAB[4])
		{
			sum += (mu::mult_foe_hit_to_real_hp(foe_dmg(e, d, n) * combat::kit_rules::passive_mult(e))); // RGS bit 16: same units as W.me.hp
		}
	};
	for (const auto& e : W.enemies)
		add(e);
	for (const auto& e : W.enemies_far)
		add(e);
	return sum < (W.me.hp + W.me.shield) * static_cast<float>(RCD_TAB[2]) / 100.0f;
}
void fired_rec()
{
	asm volatile("");
}
} // namespace nova::econ::carry_recall
