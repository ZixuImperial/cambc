// econ_capture.cc: Who captures, recall off a capture, leave or hold.
#include "econ_internal.h"
namespace nova::econ {
namespace {
// The next farm is CRD_M+ walk turns nearer from here than from the spawn: walk on, shop later.
static std::vector<int> crd_hs; // spawn -> group walk per group (-2 = not read yet)
static int crd_key = -1000; // one answer per capture (pay round); the body stands still until payout
static bool crd_res = false;
// The engine's capture state of group gi says 'contested' (an enemy on the region, seen or not; BotAPICpp.md:7928-7950). Callers ask
// only with the flag on and no visible enemy on the region.
static int cct_gi = -1, cct_last = -100, cct_n = 0;
static int cl_gi = -1, cl_start = -1, cl_last = -100;
static std::uint32_t cl_init = 0, cl_prev = 0;
// ---------------------------------------------------------------- capture

// Capture rank of a body for a group (lower captures): stacking champions take the rewards they multiply; a badly
// hurt body leaves to heal.
// Shards bought by a visible body, estimated from its stats against the kit's base stats and growths.
float shards_of(const Body& b)
{
	if (!b.kit || !b.kit->valid)
		return 0;
	const Kit& k = *b.kit;
	float n = 0;
	if (k.hp_g > 0)
		n += std::max(0.0f, b.maxhp - k.hp) / k.hp_g;
	if (k.str_g > 0 && !ryth_layer::str_from_health(k))
		n += std::max(0.0f, b.str - k.str) / k.str_g;
	if (k.foc_g > 0 && !prism_layer::focus_from_bag(k))
		n += std::max(0.0f, b.foc - k.foc) / k.foc_g;
	return n;
}
int cap_rank(int slot, const GroupI& g, float frac, float shards)
{
	int r = 1000 + static_cast<int>(10.0f * shards) + P.capture_rank[static_cast<std::size_t>(slot)] / 16;
	const bool carrier = (slot == P.carrier_gems && g.gems > 0) || (slot == P.carrier_gold && g.gold > 0);
	if (carrier)
		r -= 40;
	// A healer supports: its partner or the stacker captures (feedback 13), so it never takes a reward from them.
	if (willow_layer::rank_yield(kit_of(P.type[static_cast<std::size_t>(slot)])))
		r += 300;
	r += planner::stack_rank_bonus(slot, g.idx); // stacking champions capture what they multiply
	// past her bag cap the carrier leaves gem captures to her mates (a bigger bag only lengthens her channel).
	if (g.gems > 0 && prism_layer::carrier_slot(slot) && prism::bag_of_prism() >= (prism::cap_of_prism()))
		r += 4000 + 4 * g.gems;
	else if (g.gems > 0 && prism_layer::carrier_slot(slot) && prism::pf_group(g.idx) && prism_group_is_quiet(g))
		r -= PF_RANK; // under her cap she captures her gem groups ahead of every mate
	if (!M.any_altar && g.gems > 0 && dash_only_bank() && team_dasher())
		r += slot_dasher(slot) ? -200 : 3000;
	r += vesper_open::rank(g.idx, slot); // her first capture
	if (frac < 0.35f)
		r += 4000;
	r += support::cap_penalty(slot); // captures go to the partner or the stacker
	return r;
}
// p stands on a spawn tile of group g (its capture region).
static bool on_group_spawn_tile(const GroupI& g, vec2 p)
{
	for (int ci : g.members)
		if (M.camps[static_cast<std::size_t>(ci)].pos == p)
			return true;
	return false;
}
bool should_capture(int gi)
{
	const auto& g = M.groups[static_cast<std::size_t>(gi)];

	const int mine = cap_rank(P.my_slot, g, W.me.frac(), shards_of(W.me));
	// Prism under her cap at her plan group with no enemy in sight: the non-Prism mates on it hand her the capture.
	const bool pz_relay = W.me.kit && prism_layer::carrier() && prism::pc_group(gi) && W.enemies.empty() && static_cast<int>(W.me.gems) < (prism::cap_of_prism());
	for (const auto& a : W.allies)
	{
		if (a.slot < 0 || a.channeling() || cheb(a.pos, g.anchor) > 5 || !claims(a.slot, gi))
			continue;
		if (pz_relay && a.slot < P.n && !prism_layer::kit(kit_of(P.type[static_cast<std::size_t>(a.slot)])))
			continue;
		// Bodies in a cleared region handed the capture to a crew mate still walking in and left the same turn, so the region emptied and
		// our own capture reset with no enemy near. Only an ally on or next to one of the group's camp tiles may take the capture from me.
		{
			bool in_region = false;
			for (int ci : g.members)
				in_region |= cheb(M.camps[static_cast<std::size_t>(ci)].pos, a.pos) <= 1;
			if (!in_region)
				continue;
			if (!on_group_spawn_tile(g, a.pos) && on_group_spawn_tile(g, W.me.pos))
				continue;
		}
		const int theirs = cap_rank(a.slot, g, a.frac(), shards_of(a));
		if (theirs < mine || (theirs == mine && a.slot < P.my_slot))
			return false;
	}
	return true;
}
// Finish mode starts when our tributed gems reach FIN_US, theirs reach FIN_THEM, or the rounds left barely cover my walk and channel
// (`need`).
bool finish_mode(int need)
{
	return W.tributed_us >= FIN_US || W.tributed_them >= FIN_THEM || GAME_END - now() <= need + FIN_TIME;
}
// Bank this bag now. My share of the gems still missing is ceil((1000 - tributed) / team size): when every body carries its share
// the team has won, so carrying it I start no new farm trip; in finish mode any bag of FIN_BAG+ (or of my share, when that is
// smaller) goes to the altar.
bool finish_bank(int gems, int need)
{
	if (gems <= 0)
		return false;
	const int n = std::max(1, P.n);
	const int share = std::max(1, (1000 - W.tributed_us + n - 1) / n);
	if (gems >= share)
		return true;
	return finish_mode(need) && gems >= std::min(FIN_BAG, share);
}
// the first early-out test is inlined at the call site (this runs every turn); the rest is out of line
static __attribute__((always_inline)) bool finish_bank_bag()
{
	if (static_cast<int>(W.me.gems) <= 0 || !M.has_altar)
		return false;
	return finish_bank_bag_slow();
}
static __attribute__((noinline)) bool finish_bank_bag_slow()
{
	const int gems = static_cast<int>(W.me.gems);
	if (gems <= 0 || !M.has_altar || !bankable() || (prism_layer::bank_skip_fhb()))
		return false;
	const std::uint16_t d = spawn_crystal_bank_dist(bank_dist_here());
	if (d == UNREACH)
		return false;
	const int ha = home_altar_dist();
	if (ha != UNREACH && static_cast<int>(d) > ha + 5)
		return false;
	return finish_bank(gems, static_cast<int>(d) + rs::tribute_rounds(gems, static_cast<bool>(prism::has_family(rs::F_TRIBUTE))) + 8);
}
// The gold that pays for a capture-timed shop recall from group g. In the held middle: the next full emblem (at least 120) for
// groups past SHOPCR_BAND, with an enemy close to me in the last SHOPCR_SAFE rounds, or on a compact contact map (crew_k >=
// SHOPCR_K). Otherwise one shard per SHOPCR_TRIP tiles of walk home, at least SHOPCR_SHARDS, never more than that rule.
int shopcr_need(const GroupI& g)
{
	const int full = std::max(120, next_emblem_cost());
	if (g.contest > SHOPCR_BAND || (now() - S.enemy_close <= SHOPCR_SAFE) || crew_k >= SHOPCR_K)
		return full;
	int shards = std::max(1, SHOPCR_SHARDS);
	shards = std::max(shards, (home_dist() + SHOPCR_TRIP - 1) / SHOPCR_TRIP);
	return std::min(full, 30 * shards);
}
// Capture-recall: the reward comes 6 round starts after we hold the cleared region, and a recall started a turn later (three turns
// later with Home) completes right after that payout. Going home this way costs no time on the spot: we shop and heal, then walk out
// to the next target. True if the recall started. Bits 2 and 8 give reasons to skip a shop-only capture-timed recall.
bool capture_recall_costs_no_time(const GroupI& g, int sharing)
{
	for (std::size_t gi = 0; gi < static_cast<std::size_t>(M.ng); ++gi)
	{
		if (static_cast<int>(gi) == g.idx)
			continue;
		int alive = 0;
		bool harmless = true, near = false;
		for (int ci : M.groups[gi].members)
		{
			const auto& c = M.camps[static_cast<std::size_t>(ci)];
			if (!bbget(W.vis, c.pos) || !bbget(W.occ_camps, c.pos))
				continue;
			++alive;
			harmless &= c.str <= 0.0f;
			near |= cheb(c.pos, W.me.pos) <= 2;
		}
		if (alive > 0 && harmless && near)
			return true;
	}
	return false;
}
static bool next_farm_nearer_than_spawn(const GroupI& g, int pay_round)
{
	if (gmem_size(mem) != static_cast<std::size_t>(M.ng))
		return false;
	if (crd_key == pay_round)
		return crd_res;
	if (crd_hs.size() != static_cast<std::size_t>(M.ng))
		crd_hs.assign(static_cast<std::size_t>(M.ng), -2);
	int best_here = UNREACH, best_home = UNREACH;
	for (std::size_t gi = 0; gi < static_cast<std::size_t>(M.ng); ++gi)
	{
		const auto& o = M.groups[gi];
		if (static_cast<int>(gi) == g.idx || o.gems + o.gold <= 0)
			continue;
		const auto& m = mem[gi];
		if (m.fail_until > now() || m.status == GS_CLEARED || claimants(static_cast<int>(gi)) > 0)
			continue;
		int ready = 0;
		if (m.status == GS_RESPAWN)
		{
			ready = std::max(0, m.respawn_at - pay_round);
		}
		const distance_field* f = mv::group_field_ready(static_cast<int>(gi));
		if (!f)
			continue;
		const int dh = dfget_me(*f);
		int& hs = crd_hs[gi];
		if (hs == -2)
		{
			hs = UNREACH;
			if (M.ssu_x0 >= 0) // the same tiles
			{
				const FView vf = fview(*f);
				for (int y = M.ssu_y0; y <= M.ssu_y1; ++y)
					for (int x = M.ssu_x0; x <= M.ssu_x1; ++x)
						hs = std::min<int>(hs, vf(vec2{ x, y }));
			}
			else
				bbforeach(M.my_spawn, [&](vec2 p) { hs = std::min<int>(hs, dfget(*f, p)); });
		}
		if (dh != UNREACH)
			best_here = std::min(best_here, std::max(dh, ready));
		if (hs != UNREACH)
			best_home = std::min(best_home, std::max(hs, ready));
	}
	crd_key = pay_round;
	crd_res = best_here != UNREACH && best_home != UNREACH && best_here + CRD_TAB[2] <= best_home;
	return crd_res;
}
bool capture_recall(const GroupI& g)
{
	if (M.ring && ring_gap && W.me.gems >= 10 && bank_dist_here() <= 8)
		return false; // no shop or heal recall with a bag at the gap: the altar first
	refresh_owned();
	const int len = rs::recall_rounds(own.home, false);
	// enemies in my own sight range only (a far ward also lists the enemies it sees).
	bool foe_near = false;
	for (const auto& e : W.enemies)
		foe_near |= cheb(e.pos, W.me.pos) <= 10;
	const int pay_d = group_capture_pay_rounds(g, T.cap_on); // a Capture holder's reward lands 2 rounds sooner; an allied holder on the region counts too
	RSD(if (!foe_near && T.cap_on >= 0 && now() >= T.cap_on + pay_d - len && now() < T.cap_on + 6 - len) ++rsd::c[5];);
	RSD(if (!foe_near && rsd::stale_on >= 0 && rsd::stale_on != T.cap_on && now() >= rsd::stale_on + pay_d - len && (T.cap_on < 0 || now() < T.cap_on + pay_d - len)) ++rsd::c[12];);
	if ((T.cap_on < 0) || now() < T.cap_on + pay_d - len || home_dist() <= 6 || foe_near || !recall_safe()) // not while contested
		return false;
	int sharing = 1;
	bool bh66_low = true; // no receiver with a lower ID than mine
	for (const auto& a : W.allies)
		for (int ci : g.members)
			if (M.camps[static_cast<std::size_t>(ci)].pos == a.pos)
			{
				++sharing;
				bh66_low &= a.h > W.me.h;
			}
	int my_gems = g.gems / sharing;
	if (sharing > 1) // the lowest ID takes the remainder
	{
		const int sh = rs::split_share(g.gems, sharing, bh66_low);
		ALTAR_LOCK_SPLIT_CNT(1, sh != my_gems);
		my_gems = sh;
	}
	if (g.gems > 0 && prism::has_family(rs::F_PROSPECTOR)) // 25% of my share of the cluster gems
	{
		int clu = 0;
		for (int ci : g.members)
			clu += M.camps[static_cast<std::size_t>(ci)].type == cambc::camp_type::gem_cluster ? rs::gem_cluster_gems() : 0;
		const int bonus = rs::prospector_bonus(rs::split_share(std::min(clu, g.gems), sharing, bh66_low));
		RULE_AUDIT_FIX_CNT(4, bonus > 0);
		my_gems += bonus;
	}
	if (g.gems > 0 && bankable() && W.tributed_us + static_cast<int>(W.me.gems) + my_gems >= 1000)
	{
		// the winning bag skips the recall only while the foe races
		const int eta = prism::foe_eta();
		const std::uint16_t dh = bank_dist_here();
		if (eta < BIG && dh != UNREACH)
		{
			const int bag = static_cast<int>(W.me.gems) + my_gems;
			const int ticks = rs::tribute_turns(bag, prism::has_family(rs::F_TRIBUTE));
			const int pay = std::max(0, T.cap_on + pay_d - now());
			const int ha = home_altar_dist();
			const int t_without = now() + pay + static_cast<int>(dh) + ticks;
			const int t_with = now() + std::max(pay, len) + (ha != UNREACH ? ha : static_cast<int>(dh) + home_dist()) + ticks;
			const int t_foe = now() + eta;
			if (t_without < t_with && t_foe < t_with && t_foe + RR_SLACK >= t_without)
				return false; // the altar from here is sooner, and the recall loses a race the walk can still win
		}
	}
	const float bonus = mu::holder_gold_mult(my_slot());
	float gold_after = static_cast<float>(W.gold) + bonus * static_cast<float>(g.gold) / static_cast<float>(sharing);
	if (g.gold > 0 && prism::has_family(rs::F_PROSPECTOR)) // 25% of my share of the cluster gold, at my gold bonuses
	{
		int clu = 0;
		for (int ci : g.members)
			clu += M.camps[static_cast<std::size_t>(ci)].type == cambc::camp_type::gold_cluster ? rs::gold_cluster_gold() : 0;
		gold_after += bonus * static_cast<float>(rs::prospector_bonus(rs::split_share(std::min(clu, static_cast<int>(g.gold)), sharing, bh66_low)));
	}
	const int need = shopcr_need(g); // one or two shards' worth on our side, the full emblem in the middle
	bool shop = !tavi_layer::recall_skip_shop() && gold_after >= static_cast<float>(need);
	bool heal = W.me.frac() < 0.55f + (0.0f);
	if (shop && !heal && W.me.frac() * 100.0f >= static_cast<float>(RD_HURT))
	{
		// far from home the capture-timed shop trip costs the walk back; buy more per trip
		const int hd = home_dist();
		if (hd > RD_D0 && gold_after < static_cast<float>(need + RDS_V * (hd - RD_D0)))
			shop = false;
	}
	// late, a bankable reward is carried to the altar, not home.
	if ((GAME_END - now() <= EG_ROUNDS || finish_mode(0)) && bankable() && static_cast<int>(W.me.gems) + g.gems >= 10)
		shop = heal = false;
	// A full bag goes to the altar next: from the spawn when that altar is nearer to it than to us.
	bool bank = false;
	if (g.gems > 0 && bankable())
	{
		const std::uint16_t d = bank_dist_here();
		const int ha = home_altar_dist();
		const float bag = static_cast<float>(W.me.gems) + (static_cast<float>(my_gems));
		// a bag she would keep anyway (want_bank) is no reason for the far-bag recall.
		const float far_bag = std::max(12.0f + 0.6f * static_cast<float>(d), 0.0f);
		bank = d != UNREACH && ha != UNREACH && static_cast<int>(d) > ha + 8 &&
			(bag >= far_bag ||
				finish_bank(static_cast<int>(bag), static_cast<int>(d) + rs::tribute_rounds(static_cast<int>(bag), static_cast<bool>(prism::has_family(rs::F_TRIBUTE))) + 8));
		if (prism_layer::recall_keeps_bag())
			bank = false; // the carrier's bag is never a reason to recall
	}
	if (shop && !heal && !bank && capture_recall_costs_no_time(g, sharing))
		shop = false;
	if (shop && !heal && !bank && !prism_layer::recall_skip_bsr() && bankable() && static_cast<int>(W.me.gems) + my_gems >= 10)
	{
		const std::uint16_t d = bank_dist_here();
		const int ha = home_altar_dist();
		if (d != UNREACH && static_cast<int>(d) <= CTX_TAB[7] && (ha == UNREACH || static_cast<int>(d) < ha))
			shop = false; // the bag goes to the altar first; the shop trip comes later
	}
	if (shop && !heal && !bank && gold_after < static_cast<float>(CRD_TAB[3]) && next_farm_nearer_than_spawn(g, T.cap_on + pay_d))
		shop = false;
	if (!shop && !heal && !bank)
		return false;
	NLOG("r%d slot %d capture-recall gold %.0f hp %.0f\n", now(), P.my_slot, gold_after, W.me.hp);
	return start_recall();
}
static void capture_relay_avoid(int gi)
{
	cr_av_gi = gi;
	cr_av_until = now() + 6;
}
static bool prism_coming_for_group(int gi, vec2* pp); // she is coming
static bool on_group_camp_tile(const GroupI& g, vec2 p)
{
	for (int ci : g.members)
		if (M.camps[static_cast<std::size_t>(ci)].pos == p)
			return true;
	return false;
}
// Chebyshev distance from p to the nearest free spawn tile of g other than `skip` (BIG if none).
static int relay_free_spawn_dist(const GroupI& g, vec2 p, vec2 skip)
{
	int best = BIG;
	for (int ci : g.members)
	{
		const vec2 q = M.camps[static_cast<std::size_t>(ci)].pos;
		if (q == skip || !mv::free_tile(q))
			continue;
		best = std::min(best, cheb(p, q));
	}
	return best;
}
static int prism_relay_handoff(int gi, const GroupI& g); // hand-off
static bool capture_contested_by_engine(int gi)
{
	if (gi < 0 || gi >= M.ng)
		return false;
	cambc::detail::camp_group_capture_state cs{};
	if (cambc::detail::sdk_camp_group_capture_state(M.groups[static_cast<std::size_t>(gi)].handle, &cs) != 0)
		return false;
	return cs.state == 2; // camp_group_capture_type::contested
}
// The engine's capture timer for group gi has not started (capture_available: dead, no capture phase has seen us on it yet), so it
// starts at the next round's capture phase. Failed read: false (assume it started).
static bool capture_timer_not_started(int gi)
{
	if (gi < 0 || gi >= M.ng)
		return false;
	cambc::detail::camp_group_capture_state cs{};
	if (cambc::detail::sdk_camp_group_capture_state(M.groups[static_cast<std::size_t>(gi)].handle, &cs) != 0)
		return false;
	return cs.state == 4; // camp_group_capture_type::capture_available
}
// On the region of a running capture, a better-ranked ally that was not on the region when I started (and stood on it last turn too,
// so it is holding, not passing) takes the reward alone: I step off and move on. Also handles a capture region with no free member
// tile. 1 = dropped (caller returns false), 2 = walked on (caller returns true), 0 = wait as usual.
static int mate_holds_capture_region_turn(int gi, const GroupI& g, GroupMem& m)
{
	int na = 0, ne = 0, dm = BIG;
	for (int ci : g.members)
	{
		const vec2 p = M.camps[static_cast<std::size_t>(ci)].pos;
		dm = std::min(dm, cheb(p, W.me.pos));
		for (const auto& a : W.allies)
			na += a.pos == p ? 1 : 0;
		for (const auto& e : W.enemies)
			ne += e.pos == p ? 1 : 0;
	}
	if (na > 0 && ne == 0)
	{
		NLOG("r%d slot %d NFT mate holds %d\n", now(), P.my_slot, gi);
		mark_mate_capture(m, g);
		drop_target(0);
		return 1;
	}
	if (ne > 0)
	{
		NLOG("r%d slot %d NFT foe holds %d\n", now(), P.my_slot, gi);
		drop_target(10);
		return 1;
	}
	return 0;
}
static bool capture_region_handoff(int gi, const GroupI& g)
{
	std::uint32_t on = 0;
	for (const auto& a : W.allies)
	{
		if (a.slot < 0 || a.slot >= 32 || a.slot == P.my_slot || a.channeling())
			continue;
		for (int ci : g.members)
			if (M.camps[static_cast<std::size_t>(ci)].pos == a.pos)
			{
				on |= 1u << a.slot;
				break;
			}
	}
	const bool fresh = cl_gi != gi || cl_start != T.cap_start || now() - cl_last > 1;
	cl_last = now();
	if (fresh)
	{
		cl_gi = gi;
		cl_start = T.cap_start;
		cl_init = on;
		cl_prev = on;
	}
	const std::uint32_t held = (on) & (~0u); // mates on the region from the start too
	cl_prev = on;
	if (!held || T.cap_on < 0)
		return false;
	for (const auto& e : W.enemies)
		if (cheb(e.pos, W.me.pos) <= CL_FOE)
			return false;
	const int mine = cap_rank(P.my_slot, g, W.me.frac(), shards_of(W.me));
	for (const auto& a : W.allies)
	{
		if (a.slot < 0 || a.slot >= 32 || !(held & (1u << a.slot)))
			continue;
		const int theirs = cap_rank(a.slot, g, a.frac(), shards_of(a));
		if (theirs < mine || (theirs == mine && a.slot < P.my_slot))
			return true;
	}
	return false;
}
// Standing on tile p of dead group gi's region until the reward lands takes the awake camps' hits there (camp_threat: the
// nearest-champion test) each round start before it; true when my HP + shield do not cover them and a keep margin. started: the
// capture timer's start round (T.cap_on), or -1 for a step that starts it now.
bool capture_wait_lethal(vec2 p, int gi, int started)
{
	const float ct = mv::camp_threat(p, gi);
	if (ct <= 0.0f)
		return false;
	const int pay_d = (gi >= 0 && gi < M.ng) ? group_capture_pay_rounds(M.groups[static_cast<std::size_t>(gi)], started) : rs::capture_pay(prism::has_family(rs::F_CAPTURE));
	const int hits = started >= 0 ? std::max(0, started + pay_d - 1 - now()) : pay_d - 1;
	return hits > 0 && W.me.hp + std::max(0.0f, W.me.shield) <= ct * static_cast<float>(hits) + 0.1f * W.me.maxhp;
}
// Everything here runs only with the switch on, after an attack or cast with the move unused.
void step_onto_capture_region()
{
	const int gi = T.target;
	if (gi < 0 || gi >= M.ng || fuel() < 6000 || !W.me.kit || ring_gate_keep(gi))
		return;
	const auto& g = M.groups[static_cast<std::size_t>(gi)];
	bool adj = false;
	for (int ci : g.members)
	{
		const int d = cheb(W.me.pos, M.camps[static_cast<std::size_t>(ci)].pos);
		if (d == 0)
			return; // on the region already
		adj |= d == 1;
	}
	if (!adj)
		return;
	for (int ci : g.members)
		if (camp_alive_now(ci)) // out of sight reads alive: no step
			return;
	for (const auto& a : W.allies)
		for (int ci : g.members)
			if (a.pos == M.camps[static_cast<std::size_t>(ci)].pos)
				return; // a mate holds the region
	if (!should_capture(gi))
		return;
	vec2 pp{ -1, -1 };
	if (prism_coming_for_group(gi, &pp))
		return; // the region waits for Prism
	const float here = mv::camp_threat(W.me.pos, gi);
	vec2 best{ -1, -1 };
	float best_t = 1e9f;
	for (int ci : g.members)
	{
		const vec2 p = M.camps[static_cast<std::size_t>(ci)].pos;
		if (cheb(W.me.pos, p) != 1 || bbget(W.occ_units, p))
			continue;
		bool closer = false;
		for (const auto& e : W.enemies)
			closer |= cheb(e.pos, p) <= 4 && cheb(e.pos, p) < cheb(e.pos, W.me.pos);
		if (closer)
			continue;
		const float t = mv::camp_threat(p, gi);
		if (t <= here && t < best_t && !(capture_wait_lethal(p, gi, -1)))
		{
			best_t = t;
			best = p;
		}
	}
	if (best.x >= 0)
		mv::try_move(best);
}
// A better-ranked visible mate (not channeling) stands on group g's region and no foe is within CL_FOE of me.
static bool mate_holds_region(int gi, const GroupI& g)
{
	(void)gi;
	for (const auto& e : W.enemies)
		if (cheb(e.pos, W.me.pos) <= CL_FOE)
			return false;
	int mine = -1;
	for (const auto& a : W.allies)
	{
		if (a.slot < 0 || a.slot >= 32 || a.slot == P.my_slot || a.channeling())
			continue;
		bool on = false;
		for (int ci : g.members)
			on |= M.camps[static_cast<std::size_t>(ci)].pos == a.pos;
		if (!on)
			continue;
		if (mine < 0)
			mine = cap_rank(P.my_slot, g, W.me.frac(), shards_of(W.me));
		const int theirs = cap_rank(a.slot, g, a.frac(), shards_of(a));
		if (theirs < mine || (theirs == mine && a.slot < P.my_slot))
			return true;
	}
	return false;
}
bool capture(int gi)
{
	last_act = ACT_CAPTURE;
	const auto& g = M.groups[static_cast<std::size_t>(gi)];
	auto& m = mem[static_cast<std::size_t>(gi)];
	if (!T.capturing)
	{
		T.capturing = true;
		T.cap_start = now();
		T.cap_on = -1;
		T.cap_gems = W.me.gems;
		RSD(rsd::stale_on = -1;);
		T.cap_gold = W.gold;
	}
	if ((W.me.gems > T.cap_gems || W.gold > T.cap_gold) && m.status != GS_RESPAWN)
	{
		// a gain while the engine shows the group alive or unpaid (1/2) is not the capture (a kill's gold/bag)
		const int gs = group_state_now(gi);
		if (gs == 1 || gs == 2)
		{
			T.cap_gems = W.me.gems;
			T.cap_gold = W.gold;
		}
	}
	if (W.me.gems > T.cap_gems || W.gold > T.cap_gold || m.status == GS_RESPAWN)
	{
		if (W.me.gems > T.cap_gems || W.gold > T.cap_gold)
		{
			// camp model and measurement.
			int sharing = 1;
			for (const auto& a : W.allies)
				for (int ci : g.members)
					if (M.camps[static_cast<std::size_t>(ci)].pos == a.pos)
						++sharing;
			RSD(const bool hc = prism::has_family(rs::F_CAPTURE); ++rsd::c[hc ? 9 : 10]; rsd::head("RS3", now(), P.my_slot); rsd::s(" g"); rsd::i(gi); rsd::s(" h"); rsd::i(hc););
			RSD(rsd::s(" on"); rsd::i(T.cap_on); rsd::s(" st"); rsd::i(rsd::stale_on); rsd::s(" sh"); rsd::i(sharing););
			RSD(rsd::s(" gm"); rsd::i(static_cast<long>(W.me.gems) - static_cast<long>(T.cap_gems)); rsd::s(" gd"); rsd::i(static_cast<long>(W.gold) - static_cast<long>(T.cap_gold)); rsd::s("\n"););
			planner::on_captured_by_me(gi);
			intel::record_group_taken(gi, now()); // teammates learn the respawn of our capture
			planner::stat_capture(gi, sharing, static_cast<int>(W.me.gems - T.cap_gems), static_cast<int>(W.gold - T.cap_gold));
		}
		mark_respawn(m, now() + g.respawn);
		NLOG("r%d slot %d captured group %d gems %u gold %u\n", now(), P.my_slot, gi, W.me.gems, W.gold);
		drop_target(0);
		return false;
	}
	if (now() - T.cap_start > 16 && !territory_hold(g, gi) && // held in our territory
		!(T.cap_on >= 0 && now() - T.cap_on <= rs::capture_pay(prism::has_family(rs::F_CAPTURE)) && now() - T.cap_start <= 30)) // the timer started within capture_pay rounds: the reward is due
	{
		drop_target(15);
		return false;
	}
	bool on_region = false;
	for (int ci : g.members)
		if (M.camps[static_cast<std::size_t>(ci)].pos == W.me.pos)
			on_region = true;
	if (on_region && cheb(g.anchor, W.me.pos) > 12 && group_state_now(gi) == 3)
	{
		// captured out of sight; what observe() would have read within 12 of the anchor
		mark_respawn_timer(m, g);
		drop_target(0);
		return false;
	}
	if (on_region)
	{
		const int cr = prism_relay_handoff(gi, g);
		if (cr == 2)
			return true; // Prism takes over the running capture
		dbg_path = 50;
		RSD(if (rsd::stale_on < 0) rsd::stale_on = now(););
		// admitting an enemy resets the engine's capture timer (GameRules 194/206): while a visible foe stands on the region nothing
		// counts, and the timer restarts on the first uncontested round.
		bool cf_contest = false;
		for (const auto& e : W.enemies)
			for (int ci : g.members)
				cf_contest |= M.camps[static_cast<std::size_t>(ci)].pos == e.pos;
		bool cct = false;
		if (!cf_contest && capture_contested_by_engine(gi))
		{
			// blocked by an enemy out of my sight: the timer is not running.
			cct = true;
			if (cct_gi != gi || now() - cct_last > (HOLD_BUDGET_FIX_TAB[2])) // the budget runs per group, not per streak
				cct_n = 0;
			cct_gi = gi;
			cct_last = now();
			++cct_n;
		}
		else if (cf_contest)
		{
			// a visible foe on the region is a contested turn of the same hold budget.
			if (cct_gi != gi || now() - cct_last > HOLD_BUDGET_FIX_TAB[2])
				cct_n = 0;
			cct_gi = gi;
			cct_last = now();
			++cct_n;
		}
		if (cf_contest || cct)
			T.cap_on = -1;
		else if (T.cap_on < 0)
			T.cap_on = now() + ((capture_timer_not_started(gi)) ? 1 : 0);
		// A long group's far end: stay on the region while the pin is worth its value, with a fresh capture timer.
		const bool b805_hold = cct && W.me.frac() >= 0.4f && static_cast<float>(cct_n) <= group_value(g, gi, P.my_slot) * (static_cast<float>(MFB_TAB[5]) / 100.0f) && !(mate_pins_group(g)); // one body pins
		if (b805_hold)
			T.cap_start = now();
		if (!b805_hold && cct && cct_n >= CCT_GIVE)
		{
			// give up now rather than after the 16 (+12) round timer.
			NLOG("r%d slot %d CAP_CONTESTED give up %d after %d\n", now(), P.my_slot, gi, cct_n);
			drop_target(15);
			return false;
		}
		if (!cf_contest && !cct && cr == 0 && capture_region_handoff(gi, g))
		{
			// a better-ranked mate holds the region: hand it the whole reward and move on (as a non-capturer does).
			NLOG("r%d slot %d CAP_LEAVE %d\n", now(), P.my_slot, gi);
			mark_mate_capture(m, g);
			drop_target(0);
			return false;
		}
		if (cr == 0 && capture_recall(g)) // no recall channel while Prism comes (cr == 1)
		{
			RSD(rsd::head("RS3C", now(), P.my_slot); rsd::s(" g"); rsd::i(gi); rsd::s(" h"); rsd::i(prism::has_family(rs::F_CAPTURE)); rsd::s(" on"); rsd::i(T.cap_on); rsd::s(" st"); rsd::i(rsd::stale_on); rsd::s("\n"););
			return true;
		}
		if (T.cap_on >= 0 && capture_wait_lethal(W.me.pos, gi, T.cap_on))
		{
			// the awake camps here kill me before the reward lands: leave the capture (the farm turn steps off)
			NLOG("r%d slot %d CAW leave %d\n", now(), P.my_slot, gi);
			drop_target(10);
			return false;
		}
		// Hold the tile; hit an enemy in range if there is one.
		for (const auto& e : W.enemies)
			if (cheb(e.pos, W.me.pos) <= W.me.range && combat::attack_champion(e))
				break;
		return true;
	}
	RSD(rsd::stale_on = -1;);
	T.cap_on = -1; // Off the region, the engine's timer restarts when we step back on.
	if (mate_holds_region(gi, g))
	{
		mark_mate_capture(m, g);
		drop_target(0);
		return false;
	}
	vec2 pp{ -1, -1 };
	if (prism_coming_for_group(gi, &pp) && on_group_camp_tile(g, pp))
	{
		// Prism already stands on the region: do not step on (a share of her reward); move on.
		m.fail_until = std::max(m.fail_until, now() + 10);
		drop_target(0);
		capture_relay_avoid(gi);
		return false;
	}
	bitboard goals;
	bool any = false;
	for (int ci : g.members)
	{
		const vec2 p = M.camps[static_cast<std::size_t>(ci)].pos;
		if (mv::free_tile(p) && !(capture_wait_lethal(p, gi, -1)))
		{
			bbset(goals, p);
			any = true;
		}
	}
	if (!any)
	{
		dbg_path = 52;
		const int nf = mate_holds_capture_region_turn(gi, g, m);
		if (nf == 1)
			return false;
		if (nf == 2)
			return true;
		if (now() - T.cap_start > (group_capture_pay_rounds(g, -1))) // 4 with a Capture holder on the region
			drop_target(10);
		return true;
	}
	if ((starved_map_bits() & 8) != 0 && group_outside_walk(gi) && approach_group(gi))
		return true; // A dead dash-only group is captured from inside: walk to the launch and dash in.
	dbg_path = 51;
	mv::collect_dash(2); // dash onto the capture region (the five-round timer starts sooner)
	bool stepped;
	{
		const mv::AvoidCampReach eo_guard(camp_escape_guard_on()); // the capture walk keeps out of the reach camp_out just left
		stepped = mv::step_to_set(goals, 30, gi);
	}
	mv::collect_dash(0);
	if (!stepped)
	{
		if (now() - T.cap_start > 8)
			drop_target(10);
	}
	return true;
}
// The cheap action of a skipped tank/support turn: one basic hit (with reset) on the lowest-HP visible living camp of my target
// group in my range; no step, no searches.
__attribute__((noinline)) bool cheap_camp_hit(int gi)
{
	if (!W.alive || W.me.channeling() || !W.can_attack())
		return false;
	int best = -1;
	float bh = 1e30f;
	for (const auto& vc : W.camps)
	{
		if (vc.ci < 0 || static_cast<std::size_t>(vc.ci) >= static_cast<std::size_t>(M.nc))
			continue;
		const auto& c = M.camps[static_cast<std::size_t>(vc.ci)];
		if (c.group != gi || cheb(c.pos, W.me.pos) > W.me.range || vc.hp >= bh)
			continue;
		bh = vc.hp;
		best = vc.ci;
	}
	return best >= 0 && combat::hit_camp(best); // no hit: the camp turn runs after all
}
static int wait_chip_target(int wait_gi, int left, float* out_rate)
{
	if (W.me.frac() < 0.5f || ((prism_layer::cr_rich() || static_cast<int>(W.me.gems) >= CR_BAG)))
		return -1;
	build_team(false);
	if (travel_round != now() || travel_from != W.me.pos)
		compute_travel();
	const Claims cl = claims_for_me();
	int best = -1;
	float best_v = 0;
	for (int gi = 0; gi < static_cast<int>(M.groups.size()); ++gi)
	{
		if (gi == wait_gi)
			continue;
		const auto& g = M.groups[static_cast<std::size_t>(gi)];
		const auto& m = mem[static_cast<std::size_t>(gi)];
		const std::uint16_t tr = travel[static_cast<std::size_t>(gi)];
		if (tr == UNREACH || static_cast<int>(tr) > FRL_TAB[3] || g.access != ACC_WALK || g.n_att == 0 || g.n_mono > 0 ||
			m.status == GS_CLEARED || m.status == GS_RESPAWN || m.fail_until > now() ||
			g.contest * 100.0f > static_cast<float>(CR_CONTEST_X100) || is_gate(gi) || !reachable_target(gi) || !zc::allow_fast(gi, my_slot()) || sg_big(g))
			continue;
		const float budget = static_cast<float>(left + 15 - 2 * static_cast<int>(tr));
		if (budget < 3.0f || claimants(gi, my_slot(), cl) > 0 || !chip_group_is_quiet(gi))
			continue;
		const Crew c1 = crew_for(gi, my_slot(), 0, cl);
		const ClearEst e = estimate(g, m, c1);
		const float sh = std::min(e.feasible ? 1.0f : chip_clear_share(g, m, c1), budget / std::max(1.0f, e.t));
		if (sh * 100.0f < static_cast<float>(FRL_TAB[5]))
			continue;
		const float v = group_value(g, gi, my_slot()) * sh;
		if (v <= best_v)
			continue;
		best_v = v;
		best = gi;
		*out_rate = v / std::max(1.0f, static_cast<float>(tr) + e.t * sh);
	}
	return best;
}
} // namespace
} // namespace nova::econ

// ---------------------------------------------------------------- ending the game through a capture. Reached only when the
// end-capture switch is on at the hook (brain_*.cc contest_capture_turn).
#include "mapinfo.h"
#include "multipliers.h"
namespace nova::econ::capture_end
{
namespace bu = ::nova::combat::burst;
namespace
{
// Firing counters (firecount puts one at each function entry): a game-ending group was found; the turn was used; bit 2 passed an
// 80-99 group.
void end_seen()
{
}
void end_fire()
{
}
void low_fire()
{
}
// One round of the visible foes' ready hits on tile p (lethal_burst_hit, cooldowns read; a foe stunned through its next turn deals none).
float round_hits(vec2 p)
{
	float s = 0.0f;
	for (const auto& e : W.enemies)
	{
		const int d = cheb(e.pos, p);
		if (d > 9)
			continue;
		s += std::max(0.0f, bu::lethal_burst_hit(e, d, 0, nullptr));
	}
	return s;
}
} // namespace
bool end_turn(const ::nova::combat::Assessment& a, float keep)
{
	static int mx = -1; // the richest group (map values, read once): no game-ending group below 1000 - mx tributed
	if (mx < 0)
	{
		mx = 0;
		for (int i = 0; i < M.ng; ++i)
			mx = std::max(mx, M.groups[static_cast<std::size_t>(i)].gems);
	}
	const int need = 1000 - W.tributed_them;
	if (need <= 0 || need > mx)
		return false;
	const int dmax = CC_D + 3;
	int gi = -1;
	for (int i = 0; i < M.ng && gi < 0; ++i)
	{
		const auto& g = M.groups[static_cast<std::size_t>(i)];
		if (g.gems < need)
			continue;
		bool near = false, foe = false;
		for (int ci : g.members)
		{
			const vec2 p = M.camps[static_cast<std::size_t>(ci)].pos;
			if (cheb(p, W.me.pos) <= dmax)
				near = true;
			for (const auto& e : W.enemies)
				if (cheb(e.pos, p) <= CCE_FOE)
					foe = true;
		}
		if (!near || !foe)
			continue;
		std::uint32_t st = 0;
		if (cambc::detail::sdk_camp_group_state(g.handle, &st) != 0 || st != 2)
			continue;
		gi = i;
	}
	if (gi < 0)
		return false;
	end_seen();
	const auto& g = M.groups[static_cast<std::size_t>(gi)];
	const float ehp = W.me.hp + W.me.shield;
	bool on = false, any = false;
	bitboard goals;
	for (int ci : g.members)
	{
		const vec2 p = M.camps[static_cast<std::size_t>(ci)].pos;
		if (p == W.me.pos)
			on = true;
		else if (cheb(p, W.me.pos) <= dmax && mv::free_tile(p) && mv::camp_threat(p) <= 0.0f)
		{
			if (cheb(p, W.me.pos) <= 1 && mu::mult_foe_hit_to_real_hp(round_hits(p)) >= ehp)
				continue; // the last step: one round of seen ready hits there kills me before the capture phase
			bbset(goals, p);
			any = true;
		}
	}
	if (on)
	{
		if (mu::mult_foe_hit_to_real_hp(round_hits(W.me.pos)) >= ehp)
			return false; // dying here does not stop their capture
	}
	else
	{
		if (!any || !W.can_move())
			return false;
		bool adj = false;
		for (int ci : g.members)
			if (cheb(M.camps[static_cast<std::size_t>(ci)].pos, W.me.pos) <= 1 && bbget(goals, M.camps[static_cast<std::size_t>(ci)].pos))
				adj = true;
		if (!adj) // the walk in: contest_capture_turn's damage test
		{
			float dmg = 0;
			for (const auto& f : a.foes)
				if (f.reach >= 0 && cheb(f.pos, W.me.pos) <= f.reach + 2)
					dmg += (f.burst + (f.dps));
			if (mu::mult_foe_hit_to_real_hp(dmg) > ehp - keep)
				return false;
		}
		if (!mv::step_to_set(goals, 12, gi))
			return false;
	}
	end_fire();
	for (const auto& e : W.enemies)
		if (cheb(e.pos, W.me.pos) <= W.me.range && combat::attack_champion(e))
			break;
	return true;
}
bool low_ok(int gems)
{
	if (gems < CCE_GEMS)
		return false;
	low_fire();
	return true;
}
} // namespace nova::econ::capture_end
