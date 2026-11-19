// econ_value.cc: Reward of a group in gems: weights, game phase, need.
#include "econ_internal.h"
namespace nova::econ {
namespace {
// The team sieges one lone monolith or golem at a time: the one a body already claims, else the one nearest our
// spawn (every body picks the same, without talking).
int designated_siege = -2;
// The static part of the team's gem need (map features from draft memory, computed once in init, the same on every body) and the
// contested gem groups that crews go for.
float gn_static = 0;
// The gem need now, in [0, 1]: static x race. Race mode 1 (default): race = max(their lead / lead cap, the gems we are short of pace
// per round / lag), so a game we lead or keep pace in is unaffected; race mode 0: 1 while level or behind, 0 at a lead of lead cap.
// My bag counts as ours. Cached per round. In the opening (round < 30) every body sees 0-0 and an empty bag, so the value is the
// same on every body.
int gn_round = -1000;
float gn_val = 0;
// The team recruits for one contested gem camp with attackers at a time: the one another body already claims, else the richest
// (ties: nearest our spawn). Every body picks the same without talking.
int gn_designated = -2;
int gpv1_r = -1, gpv1_d = 0;
float gpv1_q = 1.0f;
bool gpv1_ok = false, gpv1_done = false;
bool gpv_susp = false; // the shadow rating's flag-0 value
int gpv_hfh = -1; // 1 = a hole field with heavy-guarded gems, once a game
int fin9_r = -1, fin9_v = 0;
// a holder's Prospector bonus on one group, solo share, from static map data filled once.
static std::vector<std::int16_t> prp_gem, prp_gold;
void endgame_sample_tributes()
{
	if (eg_hist.empty() || now() - eg_hist.back()[0] >= 50)
		eg_hist.push_back({ now(), W.tributed_us, W.tributed_them });
}
bool low_score_game()
{
	if (now() < 1000 || eg_hist.empty())
		return false;
	const std::array<int, 3>* old = nullptr;
	for (const auto& h : eg_hist)
		if (now() - h[0] >= 200)
			old = &h;
	if (!old)
		return false;
	const float span = static_cast<float>(now() - (*old)[0]), left = static_cast<float>(GAME_END - now());
	const float us = static_cast<float>(W.tributed_us) + static_cast<float>(W.tributed_us - (*old)[1]) / span * left;
	const float them = static_cast<float>(W.tributed_them) + static_cast<float>(W.tributed_them - (*old)[2]) / span * left;
	return us < static_cast<float>(rs::WIN_TRIBUTE) && them < static_cast<float>(rs::WIN_TRIBUTE);
}
bool bankable() { return M.any_altar || dash_bank_flag || nwc_bank_flag || (M.ring && ring_gap) || (M.has_altar_open && gate_open()); }
// No altar is walkable from our spawn: only dashers can bank gems (dash routes).
inline bool dash_only_bank() { return !M.any_altar && M.gate_groups.empty(); }
bool slot_dasher(int s) { return s >= 0 && s < P.n && kit_of(P.type[static_cast<std::size_t>(s)]).slot_dash >= 0; }
bool team_dasher()
{
	for (int s = 0; s < P.n; ++s)
		if (slot_dasher(s))
			return true;
	return false;
}
// Groups that holes cut off on foot, for my own choice when I can dash (dashnav routes, built in spare fuel). One dasher per group,
// solo; the trip ends with a recall when no walk leads home (bank from there).
bool dash_group(int gi, int self)
{
	if (self == my_slot() && M.groups[static_cast<std::size_t>(gi)].access == ACC_TP && crystal_ok(gi))
		return true; // crystal: one body, no crew
	return self == my_slot() && dn::dasher() && M.groups[static_cast<std::size_t>(gi)].access != ACC_WALK;
}
// I stand where no walk leads home (an island I dashed to).
bool stranded() { return W.alive && M.has_home && dfget_me(M.f_home) == UNREACH; }
// Walking distance from our spawn to the nearest open altar (from draft memory), or UNREACH.
int home_altar_dist()
{
	if (!M.any_altar)
		return UNREACH;
	int best = UNREACH;
	for (const auto& a : M.altars)
		if (a.d_home != UNREACH && !a.gated && a.access == ACC_WALK) // v695 AHX bit 2
			best = std::min<int>(best, a.d_home);
	return best;
}
float gem_weight(int gi = -1)
{
	if (bankable() || (gi >= 0 && is_gate(gi)) || M.ring) // a breach costs one camp
		return 1.0f;
	return 0.03f;
}
bool siege_group(const GroupI& g) { return g.n_mono + g.n_golem > 0; }
bool is_big_group_static(const GroupI& g)
{
	return g.gems >= SG_GEMS && g.hp >= SG_HPMIN && g.access == ACC_WALK && g.d_home != UNREACH && g.contest <= SG_CMAX && ((g.n_mono + g.n_golem > 0)) && !g.members.empty() && !is_gate(g.idx) && !siege_map();
}
// Heavy camp groups that no body can clear alone are siege operations too, by the same gate (otherwise no crew of free bodies forms
// and estimate() rejects them solo). They stay normal targets as well (a claim on one is not a call: the call goes out in the event
// slot, type SG_CALL_EV). The static superset:
bool big_group_crew_candidate(const GroupI& g)
{
	return false;
}
bool any_big_group_slow()
{
	if (sg_any_v < 0 && !M.groups.empty())
	{
		sg_any_v = 0;
		for (const auto& g : M.groups)
			if (is_big_group_static(g) || big_group_crew_candidate(g))
				sg_any_v = 1;
	}
	return sg_any_v > 0;
}
// OGS bit 8 REM (common.h; all maps): a big group I saw alive with less than SG_HPMIN health left (camps never regenerate) is a
// normal target again in rate_for and the filler (is_big_group_static stays static: an operation in progress keeps its group).
inline bool big_group_nearly_dead(int gi)
{
	const auto& m = mem[static_cast<std::size_t>(gi)];
	if (m.status == GS_CLEARED)
		return true; // SGB bit 1
	return m.status == GS_ALIVE && m.hp_left >= 0 && m.hp_left < SG_HPMIN;
}
// Monoliths and golems hold nearly every gem: the team must siege them (elsewhere farming the rest pays better).
bool siege_map() { return open_gem_share < 0.15f; }
bool siege_allowed(int gi, int self, const std::array<int, 8>& cl)
{
	for (int s = 0; s < static_cast<int>(cl.size()) && s < P.n; ++s)
	{
		if (s == self)
			continue;
		const int c = cl[static_cast<std::size_t>(s)];
		if (c >= 0 && c < M.ng && siege_group(M.groups[static_cast<std::size_t>(c)]) && (M.groups[static_cast<std::size_t>(c)].n_att == 1 || (sax_siege_ok(M.groups[static_cast<std::size_t>(c)]))))
			return c == gi;
	}
	if (designated_siege == -2)
	{
		designated_siege = -1;
		int best = UNREACH + 1;
		for (const auto& g : M.groups)
			if (siege_group(g) && (g.n_att == 1 || sax_siege_ok(g)) && g.access == ACC_WALK && g.d_home < best)
			{
				best = g.d_home;
				designated_siege = g.idx;
			}
	}
	return gi == designated_siege;
}
float gem_need()
{
	if (gn_static <= 0)
		return 0;
	if (gn_round != now())
	{
		const float ours = static_cast<float>(W.tributed_us) + static_cast<float>(W.me.gems);
		const float them = static_cast<float>(W.tributed_them);
		// Only once the race says so: they lead (full at GN_LEAD gems), or we hold fewer gems than GN_PACE per round (full GN_LAG gems
		// short). A game we lead or keep pace in is unaffected.
		const float behind = clampf((them - ours) / GN_LEAD, 0.0f, 1.0f);
		const float lag = clampf((GN_PACE * static_cast<float>(now()) - ours) / GN_LAG, 0.0f, 1.0f);
		gn_val = gn_static * std::max(behind, lag);
		gn_round = now();
	}
	return gn_val;
}
// GEMNEED (2): group gi is a crew target now (a contested gem group while the need is high). EJC (common.h): called only with
// EJC_TAB[1] != 0. Bit 1: elk groups up to contest EJC_CAP/100; bit 2: contested non-elk gem groups between EJC_MLO/100 and
// EJC_CAP/100.
static bool gem_need_join_group(const GroupI &g)
{
	const float cap = static_cast<float>(EJC_TAB[2]) * 0.01f;
	if (g.contest > cap)
		return false;
	if (g.n_elk > 0)
		return false;
	return g.gems > 0 && g.contest >= static_cast<float>(EJC_TAB[3]) * 0.01f;
}
bool gem_need_crew_group(int gi)
{
	return gi >= 0 && static_cast<std::size_t>(gi) < gn_band.size() && gn_band[static_cast<std::size_t>(gi)] && gem_need() >= GN_CREW_MIN;
}
float gn_bonus() { return 1.0f + GN_PAIR * gem_need(); }
// an elk group on our side (walkable, no monolith or golem, with gems).
bool opening_elk_group(int gi)
{
	if (gi < 0 || gi >= M.ng)
		return false;
	const auto& g = M.groups[static_cast<std::size_t>(gi)];
	return g.access == ACC_WALK && !siege_group(g) && g.n_elk > 0 && g.gems > 0 && g.d_home != UNREACH && g.contest < OE_CMAX;
}
// the crew floor.
int opening_elk_crew_floor()
{
	const int fighters = TM.n;
	return std::max(2, fighters <= 3 ? fighters - 1 : std::min(OE_K, fighters));
}
// The opening crew works one own-side elk group at a time: the one another body claims; with no such claim any.
// Claims only: identical in the opening simulation.
bool opening_elk_target(int gi, int self, const Claims& cl)
{
	if (opened || !opening_elk_group(gi))
		return false;
	for (int s = 0; s < TM.n && s < 8; ++s)
	{
		const int c = cl[static_cast<std::size_t>(s)];
		if (s != self && c >= 0 && c != gi && opening_elk_group(c))
			return false;
	}
	return true;
}
bool gem_need_allowed(int gi, int self, const std::array<int, 8>& cl)
{
	for (int s = 0; s < static_cast<int>(cl.size()) && s < P.n; ++s)
	{
		if (s == self)
			continue;
		const int c = cl[static_cast<std::size_t>(s)];
		if (c >= 0 && static_cast<std::size_t>(c) < gn_band.size() && gn_band[static_cast<std::size_t>(c)] &&
			M.groups[static_cast<std::size_t>(c)].n_att > 0)
			return c == gi;
	}
	if (gn_designated == -2)
	{
		gn_designated = -1;
		int best_g = 0, best_d = UNREACH + 1;
		for (const auto& g : M.groups)
			if (static_cast<std::size_t>(g.idx) < gn_band.size() && gn_band[static_cast<std::size_t>(g.idx)] && g.n_att > 0 &&
				(g.gems > best_g || (g.gems == best_g && g.d_home < best_d)))
			{
				best_g = g.gems;
				best_d = g.d_home;
				gn_designated = g.idx;
			}
	}
	return gi == gn_designated;
}
// Gold in gem units. Early gold buys items that speed up every later clear (and wins fights), so it is worth
// half a gem (B467_GOLDW_X100) until round 400; late in the game it only breaks ties. Where monoliths hold most of the gems,
// gems are scarce and gold counts for less.
float gold_weight_in_gems()
{
	if (!bankable()) // a ring map banks gems; BEF bit 32 (row 824): gate, dash and nwc banks too
		return 1.0f;
	const float left = static_cast<float>(GAME_END - now());
	// Gold buys items and Treasure lifts every later gain (local A/B: 0.5 instead of 0.35 won 48-36, +10% gold).
	float w = clampf((static_cast<float>(B467_GOLDW_X100) / 100.0f) * (left - 400.0f) / 1200.0f, 0.06f, (static_cast<float>(B467_GOLDW_X100) / 100.0f));
	// Late in the game more gems are needed to fulfil the win condition, especially if the enemy team is ahead. From LATE_GEMS_R gold's
	// weight falls to a third over 300 rounds, and with the enemy ahead in tributed gems by up to 80% more (full at LATE_GEMS_LEAD gems
	// behind).
	if (now() >= LATE_GEMS_R)
	{
		w *= 1.0f - 0.67f * clampf(static_cast<float>(now() - LATE_GEMS_R) / 300.0f, 0.0f, 1.0f);
		w *= 1.0f - 0.8f * clampf(static_cast<float>(W.tributed_them - W.tributed_us) / LATE_GEMS_LEAD, 0.0f, 1.0f);
		w = std::max(0.02f, w);
	}
	return siege_map() ? w * (0.3f + 0.7f * open_gem_share) : w;
}
bool hole_heavy_gems_map()
{
	if (gpv_hfh < 0 && !M.groups.empty())
	{
		const int tiles = std::max(1, G.w * G.h);
		const int hole_pct = static_cast<int>(100LL * static_cast<long long>(M.holes.count()) / tiles);
		int gems = 0, heavy = 0;
		for (const auto& g : M.groups)
		{
			gems += g.gems;
			if (g.n_elk + g.n_golem + g.n_mono > 0)
				heavy += g.gems;
		}
		gpv_hfh = (hole_pct >= GPV_TAB[10] && gems > 0 && 100 * heavy >= GPV_TAB[11] * gems) ? 1 : 0;
	}
	return gpv_hfh == 1;
}
void emblem_gold_refresh()
{
	if (gpv1_r == now())
		return;
	gpv1_r = now();
	gpv1_ok = false;
	if (hole_heavy_gems_map())
		return;
	if (!build_ready || !W.me.kit || (prism_layer::shop_own_gold_rows()))
		return; // a carrier Prism keeps her own gold rows
	const int r = std::max(1, now());
	auto left = [&](int trib) { return trib <= 0 ? GAME_END_F : static_cast<float>(rs::WIN_TRIBUTE - trib) * static_cast<float>(r) / static_cast<float>(trib); };
	const float tl = static_cast<float>(std::max(1, GAME_END - r));
	gpv1_q = clampf(std::min({ tl, left(W.tributed_us), left(W.tributed_them) }) / tl, 0.0f, 1.0f);
	int cost = 1 << 24;
	try
	{
		FxmItems counts; // Counts my items as cambc::self().item_count() does, without its 336-byte zero fill.
		my_item_counts(counts);
		std::array<int, 96> need;
		// The count table is zeroed lazily per entry (stamp) instead of all 96 ints.
		static std::array<int, 96> gpz_st{};
		static int gpz_gen = 0;
		++gpz_gen;
		for (const auto& sh : build)
		{
			const auto si = static_cast<std::size_t>(static_cast<std::uint32_t>(sh));
			if (si + 1 >= need.size())
				continue;
			if (gpz_st[si] != gpz_gen)
			{
				gpz_st[si] = gpz_gen;
				need[si] = 0;
			}
			++need[si];
			if (static_cast<int>(counts[cambc::item_type(static_cast<std::uint32_t>(si + 1))]) >= need[si])
				continue;
			cost = 30 * std::max(1, (static_cast<int>(si) / 6 == 12 ? 25 : 5) - static_cast<int>(counts[sh]));
			break;
		}
	}
	catch (...)
	{
		FXR_PASS();
		return;
	}
	gpv1_done = cost >= (1 << 24);
	gpv1_d = gpv1_done ? 0 : std::max(0, cost - static_cast<int>(W.gold));
	gpv1_ok = true;
}
// my gold weight from the time line w (callers test the gold-value flag, self == my_slot() and opened first)
float emblem_gold_weight(float w)
{
	emblem_gold_refresh();
	if (!gpv1_ok || gpv_susp)
		return w;
	w *= 1.0f - static_cast<float>(GPV_TAB[2]) / 100.0f * (1.0f - gpv1_q);
	if (gpv1_done)
		w *= static_cast<float>(GPV_TAB[3]) / 100.0f;
	return w;
}
// G1: a group whose gold (raw, kit bonus included) completes my next emblem: [4]/100 x 30 gold at my weight ow
float emblem_gold_bonus(float gold_raw, float ow)
{
	if (!gpv1_ok || gpv_susp || gpv1_done || gpv1_d <= 0 || gold_raw < static_cast<float>(gpv1_d))
		return 0.0f;
	return static_cast<float>(GPV_TAB[4]) / 100.0f * 30.0f * ow;
}
float gold_weight_in_gems_for_slot(int self)
{
	float w = gold_weight_in_gems();
	if (self == my_slot() && opened)
		w = emblem_gold_weight(w);
	if (self >= 0 && self < P.n && ci_layer::type(P.type[static_cast<std::size_t>(self)])) // CGM bit 2: C&I bodies value gold less
		w *= static_cast<float>(CGM_TAB[2]) / 100.0f;
	return w;
}
// The one reader of my mates' carried gems; knowing the team's gems makes the final tribute safer. A mate in sight: the engine's
// exact bag; out of sight: unknown (0). Not counted: a Prism carrier's bag (she keeps it, owner rule), a bag that wins
// alone (it banks and the game ends, or bit 2 holds it, and either way a short finish of mine helps), a bag that cannot finish by
// r2000.
// v691 QBR bit 2: each mate's last bag read in sight (round, tributed_us then).
static int qbr_bag[8], qbr_r[8] = { -1000, -1000, -1000, -1000, -1000, -1000, -1000, -1000 }, qbr_us[8];
// v693 QMS bit 1: the stored bags of every mate unseen this round that still count (the team-wide rise must cover them all).
static int qms_unseen_sum()
{
	int t = 0;
	for (int j = 0; j < P.n && j < 8; ++j)
	{
		const std::size_t q = static_cast<std::size_t>(j);
		if (j != P.my_slot && qbr_bag[q] > 0 && qbr_r[q] < now() && now() - qbr_r[q] <= QBR_TAB[2])
			t += qbr_bag[q];
	}
	return t;
}
// v699 R2B bit 2 QMS1: banks seen landing (mine, or an in-sight mate's bag dropping between reads <= 2 rounds apart; gems leave a
// living bag only by a tribute, GR:226) since each mate's read, so the rise that erases unseen bags excludes them.
static long qms_seen_bank = 0, qbr_sb[8];
static int qms_me_bag = 0, qms_me_r = -1000;
static long qbr_unseen_bag(int s)
{
	const std::size_t k = static_cast<std::size_t>(s);
	if (qbr_bag[k] <= 0 || (now() - qbr_r[k] >= QBR_TAB[2]) || /* b2056 DTR bit 8 QBR1 */ (static_cast<long>(W.tributed_us - qbr_us[k])) >= (qms_unseen_sum())) // v699 R2B bit 2 QMS1
		return -1;
	std::int32_t al = 0;
	if (cambc::detail::sdk_champion_is_alive(P.handle[k], &al) != 0 || !al)
	{
		if (cambc::detail::sdk_champion_is_alive(P.handle[k], &al) == 0)
			qbr_bag[k] = 0; // v695 QMD bit 1: read dead: the bag is gone
		return -1;
	}
	return qbr_bag[k];
}
long finish_mates_carried()
{
	long sum = 0;
	int qmo_read[8] = { 0, 0, 0, 0, 0, 0, 0, 0 }; // v699 R2B bit 2 QMSO1: 1 in sight (qmo_eg), 2 not
	std::uint32_t qmo_eg[8] = { 0, 0, 0, 0, 0, 0, 0, 0 };
	for (int s = 0; s < P.n && s < 8; ++s)
	{
		if (s == P.my_slot)
			continue;
		if (prism_layer::type_carrier(P.type[static_cast<std::size_t>(s)]))
			continue;
		long g = -1;
		std::uint32_t eg = 0;
		if (cambc::detail::sdk_champion_gems(P.handle[static_cast<std::size_t>(s)], &eg) == 0) // v699 R2B bit 2 QMSO1
		{
			g = static_cast<long>(eg); // in sight: exact; out of sight unknown (v675: the never-allocated bag-band read removed)
			const std::size_t k = static_cast<std::size_t>(s);
			qbr_bag[k] = static_cast<int>(eg);
			qbr_r[k] = now();
			qbr_us[k] = W.tributed_us;
		}
		else g = qbr_unseen_bag(s); // v691 QBR bit 2: the last read bag, while it can still be carried
		if (g <= 0)
			continue;
		if (static_cast<long>(W.tributed_us) + g >= rs::WIN_TRIBUTE)
			continue; // wins alone
		if (now() + rs::tribute_turns(static_cast<int>(g), static_cast<bool>(body_family_or_default(P.handle[static_cast<std::size_t>(s)], rs::F_TRIBUTE, true))) <= GAME_END)
			sum += g;
	}
	return sum;
}
// b1932 EAP: APPROACH (champ_prism.h), once a round; callers read EAP_ON first.
static bool eap_approach()
{
	const int gems = static_cast<int>(W.me.gems);
	if (!W.me.kit || gems < EAP_TAB[3] || !prism_layer::carrier())
		return false; // the cheap tests first: other bodies pay nothing more
	static int r = -1;
	static bool v = false;
	if (r == now())
		return v;
	r = now();
	v = false;
	for (const auto& al : W.allies)
		if (static_cast<int>(al.gems) > gems)
			return false; // not the largest carrier
	const long t = static_cast<long>(W.tributed_us) + gems + finish_mates_carried();
	v = t >= rs::WIN_TRIBUTE - EAP_TAB[2] && t < rs::WIN_TRIBUTE;
	return v;
}
// b1932 EAP bit 2: no foe known within 8 (in sight or ward-seen).
static bool eap_no_foe8()
{
	for (const auto& e : W.enemies)
		if (cheb(e.pos, W.me.pos) <= 8)
			return false;
	for (const auto& e : W.enemies_far)
		if (cheb(e.pos, W.me.pos) <= 8)
			return false;
	return true;
}
// team: also count my mates' bags (bit 8 for the need of bit 1; always for bit 4). Without it, 1000 - tributed - my bag.
int finish_need(bool team)
{
	const long own = static_cast<long>(rs::WIN_TRIBUTE) - static_cast<long>(W.tributed_us) - static_cast<long>(W.me.gems);
	if (!team)
		return static_cast<int>(std::max(-100000L, std::min(100000L, own)));
	if (fin9_r == now())
		return fin9_v;
	const long n = own - finish_mates_carried();
	fin9_r = now();
	fin9_v = static_cast<int>(std::max(-100000L, std::min(100000L, n)));
	return fin9_v;
}
int finish_need() { return finish_need(false); }
bool finish_progress_mode()
{
	const int n = finish_need();
	return n > 0 && n <= WIN_FINISH_TAB[2] && M.has_altar;
}
// A gem group's value as progress toward the win (gem units): my share of its gems capped at the need; gold only counts a tenth on a
// group with no gems (gold ends no game).
static inline float prospector_gems(const GroupI& g, int gi); // b2384 EFB bit 4 FGV1
float finish_group_value(const GroupI& g, int gi, int self, float share)
{
	if (g.gems == 0)
		return 0.1f * share * group_value(g, gi, self);
	if (mu::holds_prospector(self)) // b2384 EFB bit 4 FGV1: the holder's Prospector cluster gems, as group_value
		return gem_weight(gi) * std::min(share * static_cast<float>(g.gems) + (share) * prospector_gems(g, gi), static_cast<float>(finish_need())); // b2387 FGSF bit 1: x share
	return gem_weight(gi) * std::min(share * static_cast<float>(g.gems), static_cast<float>(finish_need()));
}
static void prospector_fill()
{
	const std::size_t ng = static_cast<std::size_t>(M.ng);
	prp_gem.assign(ng, 0);
	prp_gold.assign(ng, 0);
	for (std::size_t k = 0; k < ng; ++k)
		for (int ci : M.groups[k].members)
		{
			const auto ty = M.camps[static_cast<std::size_t>(ci)].type;
			if (ty == cambc::camp_type::gem_cluster)
				prp_gem[k] = static_cast<std::int16_t>(prp_gem[k] + rs::gem_cluster_gems());
			else if (ty == cambc::camp_type::gold_cluster)
				prp_gold[k] = static_cast<std::int16_t>(prp_gold[k] + rs::gold_cluster_gold());
		}
}
static inline float prospector_gems(const GroupI& g, int gi)
{
	if (prp_gem.size() != static_cast<std::size_t>(M.ng))
		prospector_fill();
	return static_cast<float>(rs::prospector_bonus(std::min<int>(prp_gem[static_cast<std::size_t>(gi)], g.gems)));
}
static inline float prospector_gold(const GroupI& g, int gi)
{
	if (prp_gold.size() != static_cast<std::size_t>(M.ng))
		prospector_fill();
	return static_cast<float>(rs::prospector_bonus(std::min<int>(prp_gold[static_cast<std::size_t>(gi)], static_cast<int>(g.gold))));
}
// b1802 XGV bit 1: the gold part of group_value alone (the end-game value when the gems cannot bank by the end).
float xgv_gold_value(const GroupI& g, int gi, int self)
{
	const float ow = gold_weight_in_gems_for_slot(self);
	const float mu_g = mu::holder_gold_mult(self);
	float v = static_cast<float>(g.gold) * ow * mu_g;
	if (mu::holds_prospector(self))
		v += prospector_gold(g, gi) * mu_g * ow;
	return v;
}
// Reward of a group in gem units for body `self` (stacking champions earn more from their own captures).
float group_value(const GroupI& g, int gi, int self)
{
	const float ow = gold_weight_in_gems_for_slot(self);
	float gems_v = static_cast<float>(g.gems) * gem_weight(gi), gold_v = static_cast<float>(g.gold) * ow;
	if (crystal_gems_scarce() && g.access == ACC_TP && crystal_plan_trip_body(self)) // Crystal plan: on maps where the only gems there are decide the game.
		gems_v *= static_cast<float>(CP_TAB[2]) * 0.01f;
	const auto t = P.type[static_cast<std::size_t>(self)];
	const float mu_g = mu::holder_gold_mult(self);
	if (mu_g != 1.0f)
	{
		gold_v *= mu_g;
	}
	if (self == my_slot() && opened)
		gold_v += emblem_gold_bonus(static_cast<float>(g.gold) * mu_g, ow);
	// Passive Marcella: she earns 2 gold per gem she tributes, and the gems she captures are hers to tribute, also when a Prism is the
	// team's gem carrier (not only for the carrier).
	if (marcella_layer::gem_gold(t)) // EB4 MTG: no tribute gold where her gems cannot bank (b2295 MTG bit 1)
		gems_v += marcella_layer::tribute_gold(static_cast<float>(g.gems)) * (mu_g) * ow;
	// Prospector adds 25% of a holder's share of the cluster part (7 gems a gem cluster); the carrier buys it first on cluster maps.
	// Only my own items are known (as in the item valuation): her own valuation only.
	if (mu::holds_prospector(self)) // any holder, a mate from its last-seen emblems
	{
		gems_v += prospector_gems(g, gi) * gem_weight(gi);
		gold_v += prospector_gold(g, gi) * mu_g * ow;
		if (marcella_layer::gem_gold(t)) // b2295 MTP1: her Prospector gems are tributed too
			gems_v += marcella_layer::tribute_gold(prospector_gems(g, gi)) * mu_g * ow;
	}
	// her row, the same on every body.
	if (prism_layer::type_carrier(t))
	{
		const Body* pb = self == my_slot() ? &W.me : W.ally_by_slot(self);
		if (pb && pb->kit && pb->maxhp >= pb->kit->hp + static_cast<float>(PZ_HP_SHARDS) * pb->kit->hp_g)
			gold_v *= static_cast<float>(PZ_GOLDW_PCT) / 100.0f;
		if (g.n_att == 0)
			gems_v *= static_cast<float>(PZ_CLU_PCT) / 100.0f;
	}
	if (MCK_LIGHT_MID(g))
		gems_v *= static_cast<float>(MCK_TAB[3]) / 100.0f; // MCK bit 2: light / cluster mid gem groups
	return gems_v * strat::policy().gem_value + gold_v * strat::policy().gold_value;
}
} // namespace
} // namespace nova::econ
