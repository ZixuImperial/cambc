// econ_bank_decide.cc: Whether to bank now (want_bank) and the distance helpers it uses.
#include "econ_internal.h"
namespace nova::econ {
namespace {
// The winning bag's field over known-dead camp tiles; set only around bank_winning_bag's bank() call.
distance_field wb2_f;
bool wb2_go = false;
static bool wbr_finf = false; // set around bank_first's call of channel_survives_known_foes
bool wb2_lc = false; // this bank() call is the last call (the tribute guard and new_tribute_blocked are skipped)
int pf_bw_round = -1000; // my last bank walk step
} // namespace
// The carrier keeps her bag. Winning now and the r2000 walk deadline return in want_bank before this. She also banks near r2000 with
// room for a cancelled channel and a retry (1), at the race deadline (2), in a low-score endgame (3), and at the plan's bag cap when
// a channel can start safely (4). Nothing else. With the end-bank and cap-bank switches at 0, reasons 3 and 4 are closed for her; 1
// and 2 stay.
int pc_hold_why = 0; // the reason of the last call (0: keep)
int pbl_round = -1000, pbl_bag = 0; // the round and bag of the latched race-deadline bank
// own farm rate in V (gems + .35 gold gained) per game round, tracked on want_bank calls.
static float dbk_gain = 0.0f;
static int dbk_lost = 0;          // FF3b: my bags of 10+ lost this game
static bool dbk_e1 = false, dbk_e2 = false; // FF3b: a foe seen in our half / an unseen hit on me, this game
int pcf_calm = -1, pcf_ref = -1;
int cc_round = -1000; // first round of the current out-of-reach wait
static int eh_last = -1000; // last round the hold fired (latch: the foe radius grows by 2 for 5 rounds)
namespace {
// The refusal episode of a winning non-Prism bag. wbf_r = the last refused or guarded round, wbf_n = refusals in it.
static int wbf_r = -1000, wbf_n = 0;
int bs_mark = -1; // the round bank() last changed my tile
} // namespace
// My bag wins the game (tributed + bag >= 1000) and a tribute tile is within EB_WIN_D walk tiles: bank now. brain::turn calls this
// before hold_capture, the flee and fight branches, the retreats and the low-HP, heal and flee recalls, so a winning carrier is
// never turned away from the altar. Damage does not interrupt a tribute; bank() places our lock first and hits an enemy lock. True
// if the turn was used. Uses the field to every tribute tile over the camp tiles known dead (in sight and free; out of sight: a gap
// seen free on the ring, or the group cleared / respawning). Once a round; false when the fuel is short.
static bool mfb_walt_x = false; // this field leaves out altar tiles within 4 of a seen foe
// mates' landings, read once a turn (one SDK channel read per channelling mate), summed by completion time.
static int ebk_r = -1;
static std::uint32_t ebk_h = 0;
static int ebk_n = 0;
static int ebk_t[8], ebk_g[8]; // a mate's rounds to its landing, its bag
// wbf_g = the last guarded round; wbf_far = rounds running with the nearest known foe >= WSG_R + 2.
static int wbf_g = -1000, wbf_far = 0, wbf_far_r = -1000;
namespace {
constexpr int ALH_MAXA = 3;
constexpr int ALH_MAXF = 8;
int alh_round[ALH_MAXF];
int alh_tt[ALH_MAXF];
bool alh_init = false;
distance_field alh_f[ALH_MAXA];
int alh_fa[ALH_MAXA] = { -1, -1, -1 }; // altar index of each built field
int alh_last_a = -1, alh_last_r = -1000;
} // namespace
int alp_probe = 0, alp_slack = 0, alp_eta = 0, alp_ai = -1; // probe mode of altar_hold_turn_slow and what it found
// a target-level no-progress watchdog on calm farm turns (support_turn's loop guard for every branch).
int sd_gi = -1, sd_n = 0, sd_last = -100, sd_prog = -1000;
float sd_hp = 0;
namespace {
const distance_field& bank_field()
{
	if (wb2_go)
		return wb2_f;
	if (!M.any_altar && has_ring_field)
		return f_ring;
	if (nwc_map())
		return M.f_altar; // the open-altar field is never built without a gate
	return M.any_altar ? M.f_altar : M.f_altar_open;
}
// Bank-field distance from my tile; a camp spawn tile (blocked in the field) reads its best neighbour + 1.
std::uint16_t bank_dist_here()
{
	if (!M.any_altar && !M.has_altar_open && !wb2_go)
		return UNREACH; // no walking field to an altar was built
	const distance_field& f = bank_field();
	std::uint16_t d = dfget_me(f);
	if (d != UNREACH)
		return d;
	for (const vec2 dd : DIRS)
	{
		const vec2 n = W.me.pos + dd;
		if (!inb(n))
			continue;
		const std::uint16_t v = dfget(f, n);
		if (v != UNREACH && static_cast<std::uint16_t>(v + 1) < d)
			d = static_cast<std::uint16_t>(v + 1);
	}
	return d;
}
} // namespace
int home_dist()
{
	if (M.has_home)
	{
		const std::uint16_t v = dfget_me(M.f_home);
		if (v != UNREACH)
			return v;
	}
	return cheb(W.me.pos, M.home_anchor);
}
// the first early-out test is inlined at the call site (this runs every turn); the rest is out of line
__attribute__((always_inline)) bool leave_respawn_tile()
{
	if (T.capturing || !W.can_move() || W.moved || !bbget(M.camp_tiles, W.me.pos))
		return false;
	return leave_respawn_tile_slow();
}
__attribute__((noinline)) bool leave_respawn_tile_slow()
{
	if (T.capturing || !W.can_move() || W.moved || !bbget(M.camp_tiles, W.me.pos))
		return false;
	const int ci = M.camp_index(W.me.pos);
	if (ci < 0)
		return false;
	const int gi = M.camps[static_cast<std::size_t>(ci)].group;
	if (gi < 0 || gi >= static_cast<int>(gmem_size(mem)) || mem[static_cast<std::size_t>(gi)].status != GS_RESPAWN)
		return false;
	vec2 best{ -1, -1 };
	std::uint16_t bv = UNREACH;
	bool have = false;
#pragma clang loop unroll(full)
	for (const vec2 d : DIRS)
	{
		const vec2 n = W.me.pos + d;
		if (!inb(n) || !mv::free_tile(n) || bbget(M.camp_tiles, n) || mv::camp_threat(n) > 0)
			continue;
		const std::uint16_t v = M.has_altar ? dfget(bank_field(), n) : static_cast<std::uint16_t>(0);
		if (!have || v < bv)
		{
			have = true;
			bv = v;
			best = n;
		}
	}
	// Every neighbour is a camp tile or a hole (a cluster field cut off by holes; a Heart of Ruin captured from the field's far tile
	// can be stood on for 1,500 rounds, holding the field's respawn): first step onto a dead tile of the same group that has a way off.
	for (int pass = 0; !have && pass < 8; ++pass)
	{
		const vec2 n = W.me.pos + DIRS[static_cast<std::size_t>(pass)];
		if (!inb(n) || !mv::free_tile(n) || !bbget(M.camp_tiles, n) || mv::camp_threat(n) > 0)
			continue;
		const int cn = M.camp_index(n);
		if (cn < 0 || M.camps[static_cast<std::size_t>(cn)].group != gi)
			continue;
		for (const vec2 d2 : DIRS)
		{
			const vec2 q = n + d2;
			if (inb(q) && mv::free_tile(q) && !bbget(M.camp_tiles, q))
			{
				have = true;
				best = n;
				break;
			}
		}
	}
	if (!have)
		return false;
	NLOG("r%d slot %d leave respawn tile of %d\n", now(), P.my_slot, gi);
	const bool ok = mv::try_move(best);
	if (ok)
	{
		b957_lr_pos = best;
		mfb_lr_gi = gi;
	}
	return ok;
}
static bool prism_threat_bank_applies(int gems, int d, int chan);
bool prism_holds_bank(int gems, int d); // when she banks (hold rule)
// the first early-out test is inlined at the call site (this runs every turn); the rest is out of line
static __attribute__((always_inline)) bool bag_too_late_to_bank(int gems)
{
	if (gems <= 0 || GAME_END - now() > rs::tribute_rounds(gems, false) + 200) // no emblem: the cheap bound
		return false;
	return bag_too_late_to_bank_slow(gems);
}
static __attribute__((noinline)) bool bag_too_late_to_bank_slow(int gems)
{
	if (gems <= 0 || GAME_END - now() > rs::tribute_rounds(gems, false) + 200) // no emblem: the cheap bound
		return false; // cheap bound: the channel without an emblem plus a 200-tile walk fits (no work for most of a game)
	int d = 0;
	const std::uint16_t bd = bank_dist_here();
	if (bd != UNREACH)
		d = static_cast<int>(spawn_crystal_bank_dist(bd));
	const int ha = home_altar_dist();
	const int rct = rs::recall_rounds(prism::has_family(rs::F_HOME), false); // recall takes 5 turn ends, 3 with Home (GameRules:275)
	if (ha != UNREACH && !W.on_spawn)
		d = std::min(d, ha + rct); // a recall (3 turns with Home) to a home altar
	else if (ha != UNREACH)
		d = std::min(d, ha);
	if (d >= 1 && !(ha == 0 && !W.on_spawn && d == rct))
		--d; // the bank step starts on the arrival turn (a recall onto a tribute tile walks nothing: it starts a standing channel)
	return now() + d + rs::tribute_turns(gems, prism::has_family(rs::F_TRIBUTE)) > GAME_END;
}
// half the altar detour on the way to my target, never above d.
static int half_altar_detour(int d)
{
	if (T.target < 0 || T.target >= M.ng)
		return d;
	const int gd = M.groups[static_cast<std::size_t>(T.target)].d_altar;
	if (gd == UNREACH)
		return d;
	return std::max(0, std::min(d, (d + gd - path_dist(T.target)) / 2));
}
static void dynamic_bank_track_rate()
{
	static int last_r = -1;
	static std::uint32_t lg = 0, lgold = 0;
	const int r = now();
	if (r == last_r)
		return;
	if (last_r >= 0)
	{
		if (W.me.gems > lg)
			dbk_gain += static_cast<float>(W.me.gems - lg);
		if (W.gold > lgold)
			dbk_gain += 0.35f * static_cast<float>(W.gold - lgold);
	}
	if (last_r >= 0 && lg >= 10 && W.me.gems == 0 && r - last_r >= 15)
		++dbk_lost;
	if (now() - S.hurt_unseen <= 1)
		dbk_e2 = true;
	if (!dbk_e1 && M.has_home && M.has_enemy)
		for (const auto& e : W.enemies)
		{
			const int dh = dfget(M.f_home, e.pos), de = dfget(M.f_enemy, e.pos);
			if (dh != UNREACH && de != UNREACH && dh < de)
			{
				dbk_e1 = true;
				break;
			}
		}
	lg = W.me.gems;
	lgold = W.gold;
	last_r = r;
}
// the non-Prism bag bar: trip x rate / (2 P(loss)).
static float dynamic_bank_bar(int d)
{
	const int q = std::min(static_cast<int>(DBK_TAB[9]), std::max(0, now() - intel::latest_sighting()));
	float dn = 0.5f;
	if (M.has_enemy)
	{
		const int ds = dfget(M.f_enemy, M.home_anchor), dm = dfget_me(M.f_enemy);
		if (ds != UNREACH && dm != UNREACH && ds > 0)
			dn = std::min(1.5f, static_cast<float>(dm) / static_cast<float>(ds));
	}
	const float z = (static_cast<float>(DBK_TAB[2]) + static_cast<float>(DBK_TAB[3]) * std::log1p(static_cast<float>(q)) +
	                 static_cast<float>(DBK_TAB[4]) * dn + static_cast<float>(DBK_TAB[5]) * W.me.frac() +
	                 (static_cast<float>(DBK_TAB[10] + (dbk_e1 ? DBK_TAB[11] : 0) + (dbk_e2 ? DBK_TAB[12] : 0) +
	                                                              DBK_TAB[13] * std::min(2, dbk_lost)))) / 1000.0f;
	const float p = 1.0f / (1.0f + std::exp(-z));
	const float rate = std::max(static_cast<float>(DBK_TAB[6]) / 100.0f, dbk_gain / static_cast<float>(std::max(30, now())));
	const float trip = 2.0f * static_cast<float>(half_altar_detour(d)) + 1.0f;
	return clampf(trip * rate / (2.0f * std::max(0.001f, p)), static_cast<float>(DBK_TAB[7]), static_cast<float>(DBK_TAB[8]));
}
// The bank distance when the hole-shortcut altar route beats the walk (hole_shortcut_turn's own test); asks for the field when missing.
static std::uint16_t bank_dist_via_hole_dash(std::uint16_t d)
{
	if (!M.any_altar || !M.has_thin || !W.me.kit || prism_layer::bank_skip_dash() || !dn::dasher() || !(rsw(RSW_HS_BANK) & 1))
		return d;
	const vec2 me = W.me.pos;
	const int wd = dfget(M.f_altar, me);
	if (wd == UNREACH || wd < HOLE_SHORT_MIN)
		return d;
	int v = 0;
	const distance_field* H = hole_shortcut_field(hsb_alt(), &v);
	if (!H)
	{
		vec2 na{ -1, -1 };
		for (const auto& a : M.altars)
			if (na.x < 0 || cheb(a.pos, me) < cheb(na, me))
				na = a.pos;
		if (na.x >= 0 && bank_shortcut_trigger(wd, na))
			hsb_req_r = now(); // as bank() does: hole_shortcut_background builds the altar slot in background fuel
		return d;
	}
	const int hd = dfget(*H, me);
	if (hd == UNREACH)
		return d;
	for (const auto& e : W.enemies)
		if (cheb(e.pos, me) <= 10)
			return d; // hole_shortcut_turn keeps the dash for an escape: bank() walks
	const int sd = W.me.kit->slot_dash;
	const int cdr = sd >= 0 ? W.cd[static_cast<std::size_t>(sd)] : BIG;
	if (cdr >= BIG)
		return d;
	const int route = hd + std::max(0, cdr - hd) + v;
	return (route + HOLE_SHORT_GAIN <= wd && route < static_cast<int>(d)) ? static_cast<std::uint16_t>(route) : d;
}
bool want_bank()
{
	const int gems = static_cast<int>(W.me.gems);
	dynamic_bank_track_rate();
	if (gems <= 0)
		pbl_bag = 0; // tributed or lost
	if (gems <= 0 || !M.has_altar || !bankable())
		return false;
	if (bag_too_late_to_bank(gems))
		return false;
	if (crystal_gems_scarce())
		return true;
	// the farm-a-while rule yields to the win and deadline rules below
	const bool ring_off = M.ring && now() < ring_bank_off && dfget_me(M.f_altar) == UNREACH;
	const bool ring_dash = M.ring && !has_ring_field; // no gap known: the open-altar field walks into the ring; dash
	std::uint16_t d = bank_dist_here();
	if ((d == UNREACH || ring_dash) && dash_bankable())
	{
		d = static_cast<std::uint16_t>(std::min(5000, dn::route_len(dn::GOAL_ALTAR, W.me.pos)));
		// Only dashers bank here: an idle one carries what it has (one tributed gem breaks a 0-0 tie).
		if (T.target < 0 && !T.capturing && !ring_off && !pc_keeps_bag(PC_DASH_BANK))
			return true;
	}
	if (d != UNREACH)
		d = bank_dist_via_hole_dash(d);
	d = spawn_crystal_bank_dist(d); // on the spawn, the altar by a crystal hop
	if (rh_any && sc_bank_f == &bank_field())
	{
		const int rc = recall_hop_cost(sc_bank_r, 2);
		if (rc < static_cast<int>(d))
			d = static_cast<std::uint16_t>(rc);
	}
	if (d == UNREACH)
		return false;
	if (bag_wins_with_mates(gems)) // the plain sum
		return true;
	const int need = static_cast<int>(d) + rs::tribute_rounds(gems, static_cast<bool>(prism::has_family(rs::F_TRIBUTE))) + 8;
	if (GAME_END - now() <= need + 12)
		return true;
	if (ring_off)
		return false; // the ring was kept awake for 30 rounds: farm a while
	if (M.ring && ring_gap && gems >= 10 && d <= 8 && !pc_keeps_bag(PC_RING_BANK))
		return true; // at the gap with a bag: bank before any capture or shop recall
	if (prism_layer::bank_own_rule())
		return !(T.capturing || engaged_now() || about_to_capture()) && prism_holds_bank(gems, static_cast<int>(d));
	if (T.capturing || engaged_now() || about_to_capture())
		return false;
	if (T.bank_until > now())
		return true; // the target respawns later: the altar trip fits in the wait
	if (finish_bank(gems, need))
		return true; // team-level finish (after a capture or clear in progress, as the rules above)
	if (gems >= 10 && d <= 8 && low_score_game())
		return true; // in a game heading to r2000 only banked gems count; any bag of 10+ on an altar pass
	float thr = clampf(static_cast<float>(B467_BANKB) + (static_cast<float>(B467_BANKS_X100) / 100.0f) * static_cast<float>(d), static_cast<float>(B467_BANKB), 70.0f);
	if (LTB_LIGHT(1))
	{
		const int dd = (LTB_TAB[1] & 16) && gems >= LTB_TAB[2] ? half_altar_detour(static_cast<int>(d)) : static_cast<int>(d);
		const float lt = clampf(static_cast<float>(LTB_TAB[2]) + (static_cast<float>(LTB_TAB[3]) / 100.0f) * static_cast<float>(dd), static_cast<float>(LTB_TAB[2]), static_cast<float>(LTB_TAB[4]));
		thr = std::min(thr, lt); // only ever lowers the bar
	}
	// Prism fights with the Focus its bag gives: it carries more while no enemy is around.
	if (prism_layer::bank_quiet_bar() && now() - S.enemy_close > 40 && now() < 1700)
		thr = std::max(thr, 70.0f); // passive Prism: bag bar of at least 70
	if (team_quiet())
		thr *= static_cast<float>(QKW_TAB[4]) / 100.0f;
	if (W.me.kit && !prism_layer::bank_skip_dyn()) // Prism untouched; after the quick-walk adjustment so the raise does not compound
	{
		const float td = dynamic_bank_bar(static_cast<int>(d));
		const float thr0 = thr;
		thr = std::max(thr, td);
	}
	// Bank sooner with enemies about: near me (own vision, ward, teammates' reports) or near my target. Base rule: an enemy in sight,
	// or any enemy sighting reported in the last 20 rounds (team intel, wards included); enemies known near my target add to it. The
	// bar falls only when the bag is really at risk: a foe within 6, or more visible foes than our bodies within 8.
	{
		int foes = 0, near = 0, ours = 1;
		for (const auto& e : W.enemies)
		{
			const int d = cheb(e.pos, W.me.pos);
			foes += d <= 8 ? 1 : 0;
			near += d <= 6 ? 1 : 0;
		}
		for (const auto& al : W.allies)
			ours += cheb(al.pos, W.me.pos) <= 8 ? 1 : 0;
		if (near > 0 || foes > ours)
			thr *= (static_cast<float>(B467_BANKTH_X100) / 100.0f);
	}
	// Cassi & Issac: either death drops both bags, so the pair's bag is what is at risk: the body carrying at least half of it banks
	// for both.
	if (combat::linked_slot() >= 0)
	{
		const int pair = combat::linked_bag();
		if (2 * gems >= pair)
			return static_cast<float>(pair) >= thr;
	}
	static int bl_r = -100, bl_g = -1;
	static float bl_thr = 0.0f;
	const float use = (bl_r >= now() - 1 && bl_g == gems) ? std::min(thr, bl_thr) : thr;
	if (static_cast<float>(gems) < use)
		return false;
	bl_r = now();
	bl_g = gems;
	bl_thr = use;
	return true;
}
static bool prism_channel_unsafe();
bool pcf_hold() { return pcf_ref == W.round && incoming_at(W.me.pos, nullptr) <= 0.0f; }
} // namespace nova::econ
