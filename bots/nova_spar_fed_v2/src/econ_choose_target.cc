// econ_choose_target.cc: Bounds, best group, choose_target, join and filler targets.
#include "econ_internal.h"
namespace nova::econ {
namespace {
int gbs_key_gates = -1, gbs_key_ring = -1, gbs_key_sga = -1, gbs_key_dist = -1;
std::vector<std::pair<float, int>> opr_out;
bool gbr_want = false;  // best_group: this call is my own choice (set around its group_bounds call)
bool gbr_stop = false;  // the loop stopped; the list so far is kept in gbr_out
int gbr_gi = 0, gbr_round = -1000;
std::vector<std::pair<float, int>> gbr_out;
int gbr_trav = -1000; // travel_round when the loop stopped (a resumed stop keeps the first stop's)
// One pass of the group bounds: what is read once per pass, then the loop over the groups. Every step is inlined and the fields stay
// in registers; `live` and the sightings stay in the caller, because a member whose address leaves the struct would keep the whole
// struct in memory.
struct BoundsRun
{
	const int self;
	const std::uint16_t* trav_of;
	const bool use_home;
	std::pair<float, int>* out;
	const GBS* tab;
	const bool sga;
	GBS& live;
	vec2* const fc_pos;
	int nout = 0, ng = 0, nrow = 0, gi0 = 0; // resume where the last turn's loop stopped
	float dmax = 0, dclear = 0, chain_max = 0 /* VENDASH */, pk = 1.0f, ke0 = 0, cap0 = 0;
	bool crew_on = false, tf_fast = false, gt_fast = false, opr = false;
	float t = 0; // this group's trip time
	// group_value's per-pass parts, read on first need (as the per-group calls would)
	float ow = -1.0f, gneed = -1.0f /* GEMNEED (2) */, mu_g5 = 1.0f;
	int bk = -1;
	cambc::champion_type st{};
	float ma_gold_mult = 1.0f;
	bool ma_gems = false, ring_gw = false, gv_exact = false, gbp_fast = false, gbp_pros = false, prp_row = false, cpb_on = false;
	float gbp_goldf = 1.0f;
	// foe sightings for the free-camp test (own sight, at most FREE_AGE rounds old), read once on first need
	int fc_n = -1, fc_alive = 0;
	bool fc_all = false; // every sighting is on the map (then each lies within 1000 of every anchor)
	int fc_x0 = 0, fc_x1 = -1, fc_y0 = 0, fc_y1 = -1; // their box widened by FREE_R
	bool bf_live = false, gbb_e = false;
	float gbb_ew = -1.0f; // rate_for's endgame gold weight (gold_weight_in_gems()), on first need

	// A long pass keeps its place for the next turn.
	__attribute__((always_inline)) bool paused(int gi)
	{
		if (gbr_want && (gi & 7) == 0 && gi > gi0 && fuel() < TCF_TAB[2]) // keep the place for the next turn
		{
			gbr_out.assign(out, out + nout);
			gbr_gi = gi;
			gbr_round = now();
			gbr_trav = travel_round;
			gbr_pos = W.me.pos;
			gbr_stop = true;
			return true;
		}
		if (opr && (gi & 7) == 0 && gi > gi0 && fuel() < static_cast<long>(OPR_TAB[2]) + static_cast<long>(OPR_TAB[3]) * static_cast<long>(ng - gi)) // finishing could cut this turn
		{
			opening_bounds_save(out, nout, gi);
			return true;
		}
		return false;
	}
	// reachable_target(gi) = team_feasible(gi) && !behind_closed_gate(gi)
	__attribute__((always_inline)) bool blocked(int gi)
	{
		const auto i = static_cast<std::size_t>(gi);
		bool tfv;
		if (!tf_fast)
			tfv = team_feasible(gi);
		else
		{
			// team_feasible(gi)'s body
			if (tf_est_round != nrow)
			{
				tf_est_round = nrow;
				tf_est_n = 0;
			}
			if (nrow - team_ok_round[i] >= 25 && tf_est_n < 4 && (fuel() > 60000))
				team_feasible_refresh(i);
			tfv = team_ok[i] != 0;
		}
		if (!tfv)
			return true;
		// gates(gi)'s body
		const std::array<int, 3>* gs;
		if (!gt_fast)
			gs = &gates(gi);
		else if (gate_done[i] || !M.has_home || GT.round == nrow || (fuel() < 50000))
			gs = &gate_of[i];
		else
			gs = &gates_step(gi);
		if ((*gs)[0] >= 0) // a trace fills the entries in order: an empty first one means none
		{
			bool closed = false;
			for (const int og : *gs)
			{
				if (og < 0)
					continue;
				const auto& mo = mem[static_cast<std::size_t>(og)];
				if (mo.status == GS_CLEARED || mo.status == GS_RESPAWN)
					continue;
				if (!team_feasible(og))
				{
					closed = true;
					break;
				}
			}
			if (closed)
				return true;
		}
		return false;
	}
	__attribute__((always_inline)) bool trip_rejected(int gi, const GroupI& g, const GroupMem& m, const GBS& s, std::uint16_t tr)
	{
		t = static_cast<float>(tr) + cap0;
		if (m.status == GS_RESPAWN)
		{
			const float wait = static_cast<float>(std::max(0, m.respawn_at - nrow - static_cast<int>(tr)));
			if (wait > (MCK_ON(1) ? MCK_WAIT_CAP(g, crew_on ? crew_wait_limit(g) : 25.0f) : (crew_on ? crew_wait_limit(g) : 25.0f)) && !(crew_on && !use_home && respawn_wait_lifted(gi, self, wait))) // MCK bit 1
				return true; // rate_for rejects it
			t += wait;
		}
		if (m.status != GS_CLEARED)
		{
			const float scale = (m.status == GS_ALIVE && m.hp_left >= 0) ? clampf(m.hp_left / s.hp1, 0.02f, 1.0f) : 1.0f;
			float dc = dclear;
			if (chain_max > 0 && (s.fl & GB_CHAIN))
				dc = std::max(dc, 1.3f * (s.hp2m + 0.85f * dmax));
			t += s.hp * scale / dc + s.memb04;
		}
		if (s.fl & GB_GEMS)
			t += static_cast<float>(B438_ALTW_X100) / 100.0f * (altar_walk(g)); // read live: the analysis sets it after setup
		return false;
	}
	__attribute__((always_inline)) float crew_bound(const GBS& s)
	{
		// crew_bonus(g) with crew_keff() read once
		float cbb = 1.0f;
		if (crew_on)
		{
			const float ke = s.ck < 0 ? 0.0f : ke0 * s.ck;
			cbb = (ke > 0) ? 1.0f / (1.0f - CREW_PAIR * ke) : 1.0f;
		}
		if ((s.fl & (GB_GN | GB_WALK)) == (GB_GN | GB_WALK))
		{
			if (gneed < 0)
				gneed = gem_need();
			if (gneed >= GN_CREW_MIN)
				cbb = std::max(cbb, 1.0f + GN_PAIR * gneed);
		}
		if (!opened && (s.fl & GB_OE))
			cbb = std::max(cbb, OE_BONUS); // its crew bonus is in the bound
		return cbb;
	}
	__attribute__((always_inline)) float value_bound(const GroupI& g, int gi, const GBS& s)
	{
		// group_value(g, gi, self)
		if (ow < 0)
		{
			ow = gold_weight_in_gems();
			if (self == my_slot() && opened)
				ow = emblem_gold_weight(ow); // GPV bit 1 G1 (econ.h): the bound carries my weight
		}
		float gw = 1.0f;
		if (bk < 0)
			bk = bankable() ? 1 : 0;
		if (!(bk || (s.fl & GB_GATE) || ring_gw))
			gw = 0.03f;
		float gems_v = s.gems_f * gw, gold_v = s.gold_f * ow;
		if (cpb_on && g.access == ACC_TP)
			gems_v *= static_cast<float>(CP_TAB[2]) * 0.01f; // group_value's crystal-plan prize.
		if (mu_g5 != 1.0f)
			gold_v *= mu_g5;
		if (self == my_slot() && opened)
			gold_v += emblem_gold_bonus(s.gold_f * mu_g5, ow);
		if (ma_gems) // EB4 MTG: as group_value
			gems_v += 2.0f * s.gems_f * ma_gold_mult * ow;
		if (prp_row) // before the Prism factors, as group_value
		{
			gems_v += prospector_gems(g, gi) * gw;
			gold_v += prospector_gold(g, gi) * mu_g5 * ow;
		}
		if (gbp_fast) // group_value's Prism row
		{
			if (gbp_pros)
			{
				static std::vector<std::int16_t> gbp_clu; // gems from gem clusters per group: static map data
				if (gbp_clu.size() != static_cast<std::size_t>(ng))
				{
					gbp_clu.assign(static_cast<std::size_t>(ng), 0);
					for (int k = 0; k < ng; ++k)
						for (int ci : M.groups[static_cast<std::size_t>(k)].members)
							gbp_clu[static_cast<std::size_t>(k)] = static_cast<std::int16_t>(gbp_clu[static_cast<std::size_t>(k)] + (M.camps[static_cast<std::size_t>(ci)].type == cambc::camp_type::gem_cluster ? 7 : 0));
				}
				gems_v += (static_cast<float>(std::min<int>(gbp_clu[static_cast<std::size_t>(gi)], g.gems) / 4)) * gw;
				static std::vector<std::int16_t> cbn_gclu; // gold from gold clusters per group: static map data
				if (cbn_gclu.size() != static_cast<std::size_t>(ng))
				{
					cbn_gclu.assign(static_cast<std::size_t>(ng), 0);
					for (int k = 0; k < ng; ++k)
						for (int ci : M.groups[static_cast<std::size_t>(k)].members)
							cbn_gclu[static_cast<std::size_t>(k)] = static_cast<std::int16_t>(cbn_gclu[static_cast<std::size_t>(k)] + (M.camps[static_cast<std::size_t>(ci)].type == cambc::camp_type::gold_cluster ? 20 : 0));
				}
				gold_v += static_cast<float>(std::min<int>(cbn_gclu[static_cast<std::size_t>(gi)], static_cast<int>(g.gold)) / 4) * (1.0f + (prism::has_family(rs::F_TREASURE) ? static_cast<float>(rs::rules().treasure_pct) * 0.01f : 0.0f)) * ow;
			}
			gold_v *= gbp_goldf;
			if (g.n_att == 0)
				gems_v *= static_cast<float>(PZ_CLU_PCT) / 100.0f;
		}
		if (MCK_ON(2) && !gv_exact && MCK_LIGHT_MID(g))
			gems_v *= static_cast<float>(MCK_TAB[3]) / 100.0f; // MCK bit 2: the bound follows group_value
		const float gv = (gv_exact) ? group_value(g, gi, self) : gems_v + gold_v;
		return gv;
	}
	__attribute__((always_inline)) float endgame_bound(const GroupI& g, const GBS& s, float gv)
	{
		float gvb = gv;
		if (gbb_e && s.gold_f > 0.0f) // rate_for's endgame branch values gold at gold_weight_in_gems()
		{                             // 2000 - altar - 12 - channel (it needs its time t > tneed): gold x that weight over max(t, tneed)
			if (gbb_ew < 0.0f)
			{
				gbb_ew = gold_weight_in_gems();
				if (!(gbb_ew > ow || prism_layer::type(st)))
					gbb_e = false; // the bound's own gold term is already at least that (no G1 cut, no Prism gold rows)
			}
			if (gbb_e)
			{
				const float alt = altar_walk(g);
				float chan = static_cast<float>(rs::tribute_rounds(static_cast<int>(self == my_slot() ? W.me.gems : 0u) + g.gems, false));
				if (chan > 0.0f && slot_holds_tribute(self))
					chan = static_cast<float>(cbn_tt(static_cast<int>(self == my_slot() ? W.me.gems : 0u) + g.gems, true));
				const float tneed = GAME_END_F - static_cast<float>(nrow) - alt - 12.0f - chan;
				gvb = std::max(gv, s.gold_f * gbb_ew * t / std::max(t, tneed));
			}
		}
		return gvb;
	}
	// Free-camp part of opportunity_factor(g, m).
	__attribute__((always_inline)) bool free_camp_now(const GroupI& g, const GBS& s)
	{
		if (fc_n < 0)
		{
			fc_n = intel::recent_own(fc_pos, 16, FREE_AGE);
			fc_all = fc_n <= 16 && G.w <= 1001 && G.h <= 1001;
			for (int k = 0; k < fc_n && k < 16; ++k)
			{
				const vec2 q = fc_pos[k];
				if (!inb(q))
					fc_all = false;
				if (k == 0 || q.x - FREE_R < fc_x0)
					fc_x0 = q.x - FREE_R;
				if (k == 0 || q.x + FREE_R > fc_x1)
					fc_x1 = q.x + FREE_R;
				if (k == 0 || q.y - FREE_R < fc_y0)
					fc_y0 = q.y - FREE_R;
				if (k == 0 || q.y + FREE_R > fc_y1)
					fc_y1 = q.y + FREE_R;
			}
		}
		bool free_camp;
		if (fc_n > 16)
			free_camp = intel::count_near(g.anchor, FREE_R, FREE_AGE) == 0 && intel::count_near(g.anchor, 1000, FREE_AGE) >= fc_alive;
		else if (fc_all)
		{
			// every sighting counts within 1000; none within FREE_R when the anchor is outside their widened box
			free_camp = fc_n >= fc_alive;
			const vec2 a = s.anchor;
			if (free_camp && a.x >= fc_x0 && a.x <= fc_x1 && a.y >= fc_y0 && a.y <= fc_y1)
				for (int k = 0; k < fc_n; ++k)
					if (cheb(fc_pos[k], a) <= FREE_R)
					{
						free_camp = false;
						break;
					}
		}
		else
		{
			int nr = 0, nall = 0;
			for (int k = 0; k < fc_n; ++k)
			{
				const int d = cheb(fc_pos[k], g.anchor);
				nr += d <= FREE_R;
				nall += d <= 1000;
			}
			free_camp = nr == 0 && nall >= fc_alive;
		}
		return free_camp;
	}
	__attribute__((always_inline)) int run()
	{
		for (int gi = gi0; gi < ng; ++gi)
		{
			if (paused(gi))
				return nout;
			const auto& g = M.groups[static_cast<std::size_t>(gi)];
			const std::uint16_t tr = use_home ? g.d_home : trav_of[gi];
			if (tr == UNREACH)
				continue;
			if (!tab)
				group_static_fill(live, g, gi, sga);
			const GBS& s = tab ? tab[gi] : live;
			if (!(s.fl & GB_WALK) && !dash_group(gi, self))
				continue;
			if (blocked(gi))
				continue;
			const auto& m = mem[static_cast<std::size_t>(gi)];
			if (m.fail_until > nrow || (s.fl & GB_ZERO) || !zc::allow_fast(gi, self) || (s.fl & (GB_RGK | GB_SGB))) // as rate_for
				continue; // rate_for rejects these
			if (trip_rejected(gi, g, m, s, tr))
				continue;
			const float cbb = crew_bound(s);
			const float gv = value_bound(g, gi, s);
			const float gvb = endgame_bound(g, s, gv);
			float ub = pk * cbb * 1.02f * gvb / t;
			// free-camp part of opportunity_factor(g, m)
			if ((s.fl & GB_OPP) && opened && fc_alive > 0)
			{
				if (free_camp_now(g, s))
					ub *= FREE_BONUS;
			}
			if (bf_live)
			{
				const float bf = zc::respawn_return_factor(gi); // its factor is in the bound
				if (bf != 1.0f)
					ub *= bf;
			}
			// territory_factor(g, gi, self, TM.claim, m, true)
			if (opened && (s.fl & GB_TERR))
			{
				if ((s.fl & GB_TERRD) && m.status == GS_ALIVE && m.hp_left >= 0)
				{
					// chipped_share(g, m): the share of health gone, if >= 0.1
					const float done = 1.0f - clampf(m.hp_left / std::max(1.0f, s.hp), 0.0f, 1.0f); // BB8P: max(1, hp)
					if (done >= 0.1f)
						ub *= (1.0f + TERR_FIN * done);
				}
			}
			out[nout++] = { ub, gi };
		}
		return nout;
	}
	__attribute__((always_inline)) void resume()
	{
		if (gbr_want)
		{
			if (bounds_resume_ready() && gbr_gi <= ng && gbr_out.size() <= static_cast<std::size_t>(ng))
			{
				gi0 = gbr_gi;
				for (const auto& e : gbr_out)
					out[nout++] = e;
			}
			gbr_round = -1000;
		}
		opr = opr_on; // the opening's pass
		if (opr)
		{
			if (opr_round >= 0 && nrow > opr_round && nrow - opr_round <= 4 && opr_sslot == opr_slot && opr_gi <= ng && opr_out.size() <= static_cast<std::size_t>(ng))
			{
				gi0 = opr_gi;
				for (const auto& e : opr_out)
					out[nout++] = e;
			}
			opr_round = -1000;
			opr_gi0 = gi0;
		}
	}
	__attribute__((always_inline)) void read_team()
	{
		for (int s = 0; s < TM.n && s < 8; ++s)
			dmax = std::max({ dmax, TM.m[static_cast<std::size_t>(s)].dps1, TM.m[static_cast<std::size_t>(s)].dps3 });
		{
			float rmax = 0;
			for (int s = 0; s < TM.n && s < 8; ++s)
				rmax = std::max(rmax, TM.m[static_cast<std::size_t>(s)].ret);
			dmax += 2.5f * rmax / 0.85f;
		}
		dclear = std::max(10.0f, 1.3f * 0.85f * dmax); // 1.3: slack for live stats above the team view
		for (int s = 0; s < TM.n && s < 8; ++s)
			chain_max = std::max(chain_max, TM.m[static_cast<std::size_t>(s)].chain);
		pk = (((self == my_slot() && opened) || !opened) && combat::fight_map()) ? 1.5f : 1.0f; // group_pack_factor's bound
		ke0 = crew_keff();
		crew_on = ke0 > 0;
		nrow = now();
		ng = M.ng;
		// reachable_target's caches: their size tests hold for the whole call
		tf_fast = team_ok.size() == static_cast<std::size_t>(M.ng) && TM.n > 0;
		gt_fast = gate_of.size() == static_cast<std::size_t>(M.ng);
		st = P.type[static_cast<std::size_t>(self)];
		const int bonus_gold = vesper_layer::gold_pct(&kit_of(st));
		mu_g5 = mu::holder_gold_mult(self); // group_value's factor, taken from a single source (MUL bit 16, RI bit 8 TRG)
		ma_gems = marcella_layer::gem_gold(st);
		ma_gold_mult = mu_g5; // her tribute gold takes the holder's bonuses, as group_value
		ring_gw = M.ring; // gem_weight's last term
		// Below the bounds' minimum group count, a carrier Prism's row takes group_value's own number, since her Prospector and gem-focus
		// terms are in that bound.
		gv_exact = ng < BOUNDS_MIN_GROUPS && prism_layer::type_carrier(st);
		cap0 = cap_term(self); // per round per body, read once
		// group_value's Prism terms that don't depend on the group, read once
		gbp_fast = !gv_exact && prism_layer::type_carrier(st);
		prp_row = static_cast<bool>(mu::holds_prospector(self)); // the bound carries group_value's term for any holder
		if (gbp_fast)
		{
			gbp_pros = !prp_row && self == my_slot() && prism::has_family(9); // prp_row already holds her term
			const Body* pb = self == my_slot() ? &W.me : W.ally_by_slot(self);
			if (pb && pb->kit && pb->maxhp >= pb->kit->hp + static_cast<float>(PZ_HP_SHARDS) * pb->kit->hp_g)
				gbp_goldf = static_cast<float>(PZ_GOLDW_PCT) / 100.0f;
		}
		fc_alive = opened ? intel::enemies_alive() : 0;
		bf_live = self == my_slot() && zc::back_live();
		gbb_e = (M.any_altar || M.ring);
		cpb_on = crystal_gems_scarce() && crystal_plan_trip_body(self);
	}
};
// Order-preserving float key, its inverse, and the lazy heap best_group pops from.
std::vector<std::uint64_t> tcf_keys;
bool tcf_lazy_want = false; // best_group asks for a heap (set around its group_bounds call)
bool tcf_lazy = false;      // this call's list is a heap in tcf_keys; cand fills as it pops
long fg_pre_f0 = 0; // fuel and round at choose_target's start
int fg_pre_r0 = -1;
fg::Cost fg_bw; // the squad stick's best_within (rated near the leader's group)
long fg_bw_used = 0; // this choice's stick cost, left out of fg_pre
std::vector<std::pair<float, int>> st_cand;
int st_round = -1000;
bool reachable_target(int gi) { return team_feasible(gi) && !behind_closed_gate(gi); }
void group_static_fill(GBS& s, const GroupI& g, int gi, bool sga)
{
	s.hp = g.hp;
	s.hp1 = std::max(1.0f, g.hp);
	s.memb04 = 0.4f * static_cast<float>(static_cast<std::size_t>(g.nm));
	s.hp2m = g.members.empty() ? 0.0f : 2.0f * g.hp / static_cast<float>(static_cast<std::size_t>(g.nm));
	s.ck = (g.gems <= 0 || g.n_att <= 0 || g.access != ACC_WALK || g.n_mono + g.n_golem > 0) ? -1.0f : clampf((0.60f - g.contest) / 0.10f, 0.0f, 1.0f);
	s.gems_f = static_cast<float>(g.gems);
	s.gold_f = static_cast<float>(g.gold);
	s.contest = g.contest;
	s.anchor = g.anchor;
	std::uint16_t f = 0;
	if (g.access == ACC_WALK)
		f |= GB_WALK;
	if (g.gems == 0 && g.gold == 0)
		f |= GB_ZERO;
	if (ring_gate_keep(gi))
		f |= GB_RGK;
	if (sga && is_big_group_static(g))
		f |= GB_SGB;
	if (g.n_att == 0 && !g.members.empty())
		f |= GB_CHAIN;
	if (g.gems > 0)
		f |= GB_GEMS;
	if (is_gate(gi))
		f |= GB_GATE;
	if (gi < static_cast<int>(gn_band.size()) && gn_band[static_cast<std::size_t>(gi)])
		f |= GB_GN;
	if (opening_elk_group(gi))
		f |= GB_OE;
	if (siege_group(g))
		f |= GB_SIEGE;
	if (g.access == ACC_WALK && !siege_group(g))
		f |= GB_TERR; // territory_factor's own gate (with TERR and opened)
	if (g.contest <= TERR_OWN && g.hp > 0)
		f |= GB_TERRD; // chipped_share's static part (with GB_TERR)
	if (g.contest > 0.45f)
		f |= GB_OPP; // free-camp static part
	s.fl = f;
}
// The table, valid for this call: built once the map analysis is done, rebuilt when the gate list or the ring changes.
const GBS* group_static_table(bool sga)
{
	if (!(M.done() || M.distances_known()))
		return nullptr; // the group distances (d_home, access, contest) may still change
	const int kg = static_cast<int>(M.gate_groups.size()), kr = M.ring ? 1 : 0, ks = sga ? 1 : 0, kd = M.done() ? 2 : 1;
	if (gbs_tab.size() != static_cast<std::size_t>(M.ng) || kg != gbs_key_gates || kr != gbs_key_ring || ks != gbs_key_sga || kd != gbs_key_dist)
	{
		gbs_tab.assign(static_cast<std::size_t>(M.ng), GBS{});
		for (std::size_t i = 0; i < static_cast<std::size_t>(M.ng); ++i)
			group_static_fill(gbs_tab[i], M.groups[i], static_cast<int>(i), sga);
		gbs_key_gates = kg;
		gbs_key_ring = kr;
		gbs_key_sga = ks;
		gbs_key_dist = kd;
	}
	return gbs_tab.data();
}
void opening_bounds_save(const std::pair<float, int>* out, int nout, int gi)
{
	opr_out.assign(out, out + nout);
	opr_gi = gi;
	opr_round = now();
	opr_sslot = opr_slot;
	opr_stop = true;
}
bool bounds_resume_ready()
{
	if (!(gbr_round >= 0 && now() > gbr_round && now() - gbr_round <= 2 && gbr_pos == W.me.pos && travel_from == W.me.pos))
		return false;
	return travel_round == gbr_trav && now() - gbr_trav <= GBR_TAB[2];
}
// The group bounds list, with the group data read from the table (tab), or filled per group when the table is not valid yet (tab
// null: no draft memory and the analysis not done). Returns its length.
int group_bounds_loop(int self, const std::uint16_t* trav_of, bool use_home, std::pair<float, int>* out, const GBS* tab, bool sga)
{
	GBS live;
	alignas(vec2) unsigned char fc_raw[16 * sizeof(vec2)]; // No zeroing; only [0, min(fc_n, 16)) is written and read.
	BoundsRun b{ self, trav_of, use_home, out, tab, sga, live, reinterpret_cast<vec2*>(fc_raw) };
	b.read_team();
	b.resume();
	return b.run();
}
inline std::pair<float, int> bounds_heap_pair(std::uint64_t key)
{
	const std::uint32_t o = ~static_cast<std::uint32_t>(key >> 32);
	const std::uint32_t u = (o & 0x80000000u) ? (o & 0x7fffffffu) : ~o;
	return { __builtin_bit_cast(float, u), static_cast<int>(static_cast<std::uint32_t>(key)) };
}
// the next candidate into cand (false: none left)
inline bool bounds_heap_pop(std::vector<std::pair<float, int>>& cand)
{
	if (tcf_keys.empty())
		return false;
	std::pop_heap(tcf_keys.begin(), tcf_keys.end(), std::greater<std::uint64_t>());
	cand.push_back(bounds_heap_pair(tcf_keys.back()));
	tcf_keys.pop_back();
	return true;
}
inline void bounds_heap_drain(std::vector<std::pair<float, int>>& cand)
{
	while (bounds_heap_pop(cand))
	{
	}
	tcf_lazy = false;
}
// The list's tail: the squad-target factor, then std::sort on the list in group order.
void group_bounds_finish(int self, std::pair<float, int>* out, int nout, std::vector<std::pair<float, int>>& cand)
{
	PROF("bg_cand");
	(void)(self == my_slot() && opened && SQ_BONUS > 1.0f);
	if (self == my_slot())
		for (int k = 0; k < nout; ++k) // rate_for's x1.3 near a recent kill is in the bound.
			if (now() - mem[static_cast<std::size_t>(out[k].second)].kill_round < 20)
				out[k].first *= (static_cast<float>(B467_KILLW_X100) / 100.0f);
	if (self == my_slot())
		for (int k = 0; k < nout; ++k)
			out[k].first *= prism_mate_bound(M.groups[static_cast<std::size_t>(out[k].second)]);
	// The same libc++ introsort (its steps depend only on the comparison results) on a trivially copyable 8-byte twin of pair<float,
	// int>, sorted in the scratch list before the copy: one i64 move per element move instead of pair's member-wise assignment. Same
	// comparator, so the same permutation (ties included).
	struct __attribute__((may_alias)) GbKV
	{
		float f;
		int g;
	};
	static_assert(sizeof(GbKV) == sizeof(std::pair<float, int>), "GbKV layout");
	GbKV* const kv = reinterpret_cast<GbKV*>(out);
	std::sort(kv, kv + nout, [](const GbKV& a, const GbKV& b) { return a.f > b.f; });
	cand.resize(static_cast<std::size_t>(nout));
	if (nout > 0)
		std::memcpy(static_cast<void*>(cand.data()), out, static_cast<std::size_t>(nout) * sizeof(std::pair<float, int>));
}
std::pair<float, int>* group_bounds_buffer()
{
	static std::vector<std::pair<float, int>> buf; // the list is written here, then copied into cand once
	if (buf.size() < static_cast<std::size_t>(M.ng))
		buf.resize(static_cast<std::size_t>(M.ng));
	return buf.data();
}
// EB4 ECL: rate_for's ECL factor on the finished list (its walk can only grow, so the largest cell from this walk on).
__attribute__((noinline)) static void ecb_scale_bounds(std::pair<float, int>* out, int nout, const std::uint16_t* trav_of, bool use_home)
{
	for (int k = 0; k < nout; ++k)
	{
		const auto& g = M.groups[static_cast<std::size_t>(out[k].second)];
		const std::uint16_t tr = use_home ? g.d_home : trav_of[out[k].second];
		const int wb0 = tr <= 6 ? 0 : (tr <= 12 ? 1 : (tr <= 20 ? 2 : (tr <= 35 ? 3 : 4)));
		const float gv = static_cast<float>(g.gems) + 0.35f * static_cast<float>(g.gold);
		const int sb = gv < 15.0f ? 0 : (gv < 40.0f ? 1 : (gv < 100.0f ? 2 : 3));
		const int cb = g.contest <= 0.30f ? 0 : (g.contest <= 0.60f ? 1 : 2);
		int cell = 0;
		for (int wb = wb0; wb < 5; ++wb)
			cell = std::max<int>(cell, ECL_CELL[12 * wb + 3 * sb + cb]);
		out[k].first *= std::sqrt(static_cast<float>(cell) / 1000.0f);
	}
}
void group_bounds_bc(int self, const std::uint16_t* trav_of, bool use_home, std::vector<std::pair<float, int>>& cand)
{
	std::pair<float, int>* out = group_bounds_buffer();
	const bool sga = sg_any(); // static map data, computed once
	const int nout = group_bounds_loop(self, trav_of, use_home, out, group_static_table(sga), sga);
	if (gbr_want && !gbr_stop && fuel() < TCF_TAB[2]) // the order too waits for the next turn
	{
		gbr_out.assign(out, out + nout);
		gbr_gi = M.ng;
		gbr_round = now();
		gbr_trav = travel_round;
		gbr_pos = W.me.pos;
		gbr_stop = true;
	}
	if (gbr_stop)
		return;
	if (opr_on) // the sort waits for the next turn when this turn ran the loop and is low
	{
		const int ngb = static_cast<int>(M.groups.size());
		if (!opr_stop && opr_gi0 < ngb && fuel() < static_cast<long>(OPR_TAB[2]) + static_cast<long>(OPR_TAB[4]) * static_cast<long>(ngb))
			opening_bounds_save(out, nout, ngb);
		if (opr_stop)
			return;
	}
	if (eb4_ecb_far && opened && self == my_slot())
		ecb_scale_bounds(out, nout, trav_of, use_home);
	group_bounds_finish(self, out, nout, cand);
}
void group_bounds(int self, const std::uint16_t* trav_of, bool use_home, std::vector<std::pair<float, int>>& cand)
{
	group_bounds_bc(self, trav_of, use_home, cand); // on every map
}
bool stage_ready() { return !st_cand.empty() && now() > st_round && now() - st_round <= CHOICE_STAGE_KEEP && st_pos == W.me.pos; }
template <int DM>
int best_group(int self, const std::uint16_t* trav_of, bool use_home, const Claims& cl, int max_extra, float* out_rate, int* out_crew,
	long floor = PLAN_EVAL_FLOOR) // fuel for decisions
{
	// Candidates by an upper bound of their rate, best first: the exact (costly) rate is computed only while a
	// candidate can still beat the best so far, and never below a fuel floor.
	static std::vector<std::pair<float, int>> cand;
	const bool mine = self == my_slot() && !use_home && trav_of == travel.data();
	const bool staged = mine && stage_ready();
	if (staged) // FB2 bit 4 FU3: the same elements, copied as bytes
	{
		cand.resize(st_cand.size());
		if (!st_cand.empty())
			std::memcpy(static_cast<void*>(cand.data()), st_cand.data(), st_cand.size() * sizeof(std::pair<float, int>));
	}
	else if (staged)
		cand = st_cand;
	else
	{
		tcf_lazy = false;
		tcf_lazy_want = false; // A heap, popped below (hoard-crew mode 2 re-sorts the whole list).
		gbr_want = static_cast<bool>(mine);
		gbr_stop = false;
		group_bounds(self, trav_of, use_home, cand);
		tcf_lazy_want = false;
		gbr_want = false;
		if (gbr_stop) // no list this turn; the choice goes on next turn from the same tile
		{
			gbr_stop = false;
			gbr_defer = true;
			tcf_lazy = false;
			*out_rate = 0;
			*out_crew = 1;
			return -1;
		}
		if (DM & 2)
			hoard_crew_bounds(cand);
		if (mine && fg_pre_r0 >= 0 && fg::rnd() - fg_pre_r0 <= 1)
			fg::note(fg_pre, std::max(0L, fg::fuel_used_since(fg_pre_f0, fg_pre_r0) - fg_bw_used)); // the choice's cost before its rating loop (stick left out)
		fg_pre_r0 = -1;
	}
	int best = -1, best_crew = 1;
	float best_r = 0;
	// Evaluated candidates, re-ranked below by the value per round of the route each one starts.
	struct Ev
	{
		int gi, crew;
		float r, v, t, pen;
	};
	static std::vector<Ev> ev;
	ev.clear();
	int gsh_best = -1;
	float gsh_r = 0.0f;
	if (staged)
		floor += CHOICE_STAGE_SPARE; // leave the walk to the chosen group its fuel
	int clf_n = 0;
	const bool lnr = mine && opened;
	if (lnr)
		nova::econ::linear_score::begin();
	const bool lazy = tcf_lazy && !staged;
	for (std::size_t ci = 0;; ++ci)
	{
		if (ci >= cand.size() && !(lazy && bounds_heap_pop(cand)))
			break;
		const float ub = cand[ci].first;
		const int gi = cand[ci].second;
		if (ub <= best_r || ub <= 0.0f)
			break;
		if (fuel() < floor)
		{
			// Below the fuel floor: stop rating further candidates.
			break;
		}
		const auto& g = M.groups[static_cast<std::size_t>(gi)];
		const std::uint16_t tr = use_home ? g.d_home : trav_of[gi];
		int crew = 1;
		const float r = rate_for<DM>(gi, self, tr, cl, max_extra, &crew);
		if (r > 0)
			ev.push_back({ gi, crew, r, rf_value, rf_time, rf_pen });
		if (lnr && r > 0)
			nova::econ::linear_score::cand(gi, crew, r);
		if (r > best_r)
		{
			best_r = r;
			best = gi;
			best_crew = crew;
		}
	}
	if (lnr)
		nova::econ::linear_score::pick(1, &best, &best_crew, &best_r); // the linear per-body ranking; best_r stays a ratio
	if (mine)
	{
		if (!staged && ev.empty() && best < 0 && fuel() < floor && !cand.empty() && T.target < 0) // only a body with no target
		{
			if (lazy)
				bounds_heap_drain(cand); // the whole list
			st_cand = cand; // rate them on the next turn
			st_round = now();
			st_pos = W.me.pos;
		}
		else
			st_cand.clear();
	}
	*out_rate = best_r;
	*out_crew = best_crew;
	return best;
}
// My best group within r tiles (anchors) of c, rated exactly (rate_for) without the whole-map bounds: a squad's objective has few
// groups near it, so this costs a few ratings instead of a full choice.
template <int DM>
int best_within(vec2 c, int r, const Claims& cl, float* out_rate, int* out_crew)
{
	int best = -1, best_crew = 1;
	float best_r = 0;
	// Work cap (no fuel gate): the SQ_WITHIN_MAX groups nearest to c, each rated once.
	std::array<std::pair<int, int>, 64> near{};
	int nn = 0;
	for (int gi = 0; gi < M.ng && nn < 64; ++gi)
	{
		const int d = cheb(M.groups[static_cast<std::size_t>(gi)].anchor, c);
		if (d <= r)
			near[static_cast<std::size_t>(nn++)] = { d, gi };
	}
	std::sort(near.begin(), near.begin() + nn);
	const bool lnr = opened;
	if (lnr)
		nova::econ::linear_score::begin();
	for (int k = 0; k < nn && k < SQ_WITHIN_MAX; ++k)
	{
		const int gi = near[static_cast<std::size_t>(k)].second;
		if (travel[static_cast<std::size_t>(gi)] == UNREACH || !reachable_target(gi))
			continue;
		int cc = 1;
		const float rr = rate_for<0>(gi, my_slot(), travel[static_cast<std::size_t>(gi)], cl, free_near(), &cc); // BB8 bit 4: rated in my mode
		if (lnr && rr > 0)
			nova::econ::linear_score::cand(gi, cc, rr);
		if (rr > best_r)
		{
			best_r = rr;
			best = gi;
			best_crew = cc;
		}
	}
	if (lnr)
		nova::econ::linear_score::pick(4, &best, &best_crew, &best_r);
	*out_rate = best_r;
	*out_crew = best_crew;
	return best;
}
template <int DM>
int choose_target(float* out_rate, int* out_crew)
{
	fg_pre_f0 = fuel();
	fg_pre_r0 = fg::rnd();
	fg_bw_used = 0;
	build_team(false);
	if (!stage_ready() && !bounds_resume_ready()) // a staged list keeps the travel it was built with (same tile)
	if (travel_round != now() || travel_from != W.me.pos)
		compute_travel();
	const Claims cl = claims_for_me();
	int stick_g = -1, stick_c = 1;
	float stick_r = 0;
	// Squad stick: a squad that leaves together stays together. A visible ally next to me (within SQ_STICK_R) that just claimed a group
	// outside our own third (claim changed in the last SQ_STICK_AGE rounds): I take that group too, nearest ally first, when rate_for
	// allows it (joining a lone claimant outside our own third).
	{
		const Body* lead = nullptr;
		int lg = -1, ld = BIG;
		for (const auto& al : W.allies)
		{
			if (al.slot < 0 || al.slot >= static_cast<int>(comms::CLAIM_SLOTS) || al.slot == TM.sup || al.channeling() || al.frac() < 0.3f)
				continue;
			const int d = cheb(al.pos, W.me.pos);
			if (d > SQ_STICK_R || d >= ld || now() - squad::claim_changed(al.slot) > SQ_STICK_AGE)
				continue;
			const int g2 = comms::cgroup(al.slot);
			if (g2 < 0 || g2 >= M.ng || g2 == T.target || !squad::outside(g2) ||
				siege_group(M.groups[static_cast<std::size_t>(g2)]) || travel[static_cast<std::size_t>(g2)] == UNREACH || !squad::objective_ok(g2))
				continue;
			lead = &al;
			lg = g2;
			ld = d;
		}
		if (lead && T.target >= 0 && T.target != lg)
		{
			// I work in a crew (another body claims my target, not the leader): stay with that crew.
			for (int s2 = 0; s2 < TM.n && s2 < 8; ++s2)
				if (s2 != my_slot() && s2 != lead->slot && s2 != TM.sup && TM.claim[static_cast<std::size_t>(s2)] == T.target)
				{
					lead = nullptr;
					break;
				}
		}
		// no stick on a turn whose fuel cannot pay the stick, the bounds and the rating floor (the bounds after it would rate nothing and
		// the turn would be suspended).
		if (lead && fg_bw.hi > 0 && fuel() < fg_bw.hi + fg_pre.hi + FG_TAIL)
		{
			fg_bw.hi -= fg_bw.hi >> 5;
			lead = nullptr;
		}
		if (lead)
		{
			int cc = 1, pick = -1;
			float rr = 0;
			// leashed farming: my best group within SQ_STICK_LEASH of the leader's new group (its own group included)
			const long fbw = fuel();
			const int rbw = fg::rnd();
			pick = best_within<DM>(M.groups[static_cast<std::size_t>(lg)].anchor, SQ_STICK_LEASH, cl, &rr, &cc); // BB8_ON(4): rated in my mode
			fg_bw_used = fg::fuel_used_since(fbw, rbw);
			fg::note(fg_bw, fg_bw_used);
			if (pick >= 0 && rr > 0)
			{
				stick_g = pick; // compared with my own best below
				stick_r = rr;
				stick_c = cc;
			}
		}
	}
	int b = best_group<DM>(my_slot(), travel.data(), false, cl, free_near(), out_rate, out_crew);
	if (gbr_defer)
		return -1; // deferred
	const float sqk = (stick_g >= 0) ? nova::econ::linear_score::lsp_keep(stick_g) : SQ_KEEP; // v642 LSP: map-aware keep
	if (stick_g >= 0 && (b < 0 || (opened ? nova::econ::linear_score::keep_ok(4, 1, sqk) : stick_r >= sqk * *out_rate)))
	{
		// follow the squad mate when my share there is worth at least SQ_KEEP of my own best.
		*out_rate = stick_r;
		*out_crew = stick_c;
		++squad::diag().stuck;
		sq_stick_pick = true;
		return stick_g;
	}
	if (b < 0 && !support::me_active() && my_slot() != TM.sup && fuel() > 45000 &&
		W.me.frac() >= COVER_IDLE_HP)
	{
		// No feasible group of my own: join the own-side crew (claimants approaching or engaged) whose clear I speed up most once I get
		// there.
		float best_d = 0;
		int best_c = 1;
		for (int gi = 0; gi < M.ng; ++gi)
		{
			if (claimants(gi, my_slot(), cl) == 0)
				continue;
			const std::uint16_t tr = travel[static_cast<std::size_t>(gi)];
			if (tr == UNREACH || !reachable_target(gi))
				continue;
			int cc = 1;
			const float d = join_gain(gi, my_slot(), tr, cl, static_cast<int>(tr), &cc);
			if (d > best_d)
			{
				best_d = d;
				b = gi;
				best_c = cc;
			}
		}
		if (b >= 0)
		{
			*out_rate = best_d;
			*out_crew = best_c;
		}
	}
	PROF("choose");
	return b;
}
// Opening: what body b adds to the team rate (gem units per round) of the crew claiming group gi: the group's value over the crew's
// trip (walk `trav`, respawn wait, clear, capture overhead) with b, minus the same without b (all of it when the claimants cannot
// clear it alone). Own-side walkable groups only (contest <= 0.55, no siege). With `arrive` >= 0 (a crew already out there), b helps
// only after its own walk of `arrive` rounds. -1: not a candidate.
float join_gain(int gi, int b, std::uint16_t trav, const Claims& cl, int arrive, int* crew_out)
{
	const auto& g = M.groups[static_cast<std::size_t>(gi)];
	const auto& m = mem[static_cast<std::size_t>(gi)];
	if (trav == UNREACH || g.access != ACC_WALK || m.fail_until > now() || g.contest > 0.55f || siege_group(g) || sg_big(g) ||
		m.status == GS_CLEARED || (g.gems == 0 && g.gold == 0) || claimants(gi, b, cl) == 0)
		return -1; // a claimed group passed its claimant's reachability check
	float wait = 0;
	if (m.status == GS_RESPAWN)
	{
		wait = static_cast<float>(std::max(0, m.respawn_at - (0) - now() - static_cast<int>(trav))); // alive at my arrival
		if (wait > 25.0f)
			return -1;
	}
	const Crew c1 = crew_for(gi, b, 0, cl);
	const ClearEst e1 = estimate_cx(1, g, m, c1);
	if (!e1.feasible)
		return -1;
	const ClearEst e0 = estimate_cx(1, g, m, crew_of_claimants(gi, b, cl));
	const float v = group_value(g, gi, b);
	float t1 = e1.t;
	if (arrive >= 0 && e0.feasible)
	{
		// The crew clears without me until I arrive, then with me: the rest of the work goes at the faster rate.
		const float a = static_cast<float>(arrive);
		if (a >= e0.t)
			return -1;
		t1 = a + (e0.t - a) * e1.t / std::max(0.1f, e0.t);
	}
	else if (arrive >= 0)
		t1 = std::max(static_cast<float>(arrive), 0.0f) + e1.t;
	const float base = (arrive >= 0 ? 0.0f : static_cast<float>(trav) + wait) + cap_term(b);
	const float r1 = v / (base + t1);
	const float r0 = e0.feasible ? v / (base + e0.t) : 0.0f;
	if (crew_out)
		*crew_out = c1.n;
	return r1 - r0;
}
void set_target(int gi, float rate, int crew)
{
	if (gi != T.target) // a new target taken by an idle-recruit rating keeps that branch while held
		ir_tgt = ir_ok_round == now() && std::find(ir_ok.begin(), ir_ok.end(), gi) != ir_ok.end() ? gi : -1;
	if (gi != T.target)
	{
		NLOG("r%d slot %d target %d (was %d) rate %.3f crew %d pos %d,%d hp %.0f gems %u gold %u contest %d\n", W.round, P.my_slot, gi, T.target,
			rate, crew, W.me.pos.x, W.me.pos.y, W.me.hp, W.me.gems, W.gold, gi >= 0 ? static_cast<int>(100 * M.groups[static_cast<std::size_t>(gi)].contest) : -1);
		T.target = gi;
		T.chosen = now();
		planner::stat_set_target(gi);
		T.engaged = false;
		T.wait_since = -1;
		T.capturing = false;
		T.best_d = BIG;
		T.best_path = false;
		T.progress = now();
		T.focus = -1;
		T.bench_until = -1000;
		T.self_tank = false;
		T.filler_until = -1000;
	}
	T.rate = rate;
	T.crew = crew;
	T.eval_round = now();
}
// The zone crew's target while it walks to S and gathers (its claim tells the team where it goes).
void force_target_in(int gi)
{
	if (gi < 0 || gi == T.target || T.engaged || T.capturing)
		return;
	set_target(gi, 1.0f, 2);
	opened = true;
}
void drop_target(int fail_rounds)
{
	if (T.target >= 0)
		NLOG("r%d slot %d drop %d fail %d\n", W.round, P.my_slot, T.target, fail_rounds);
	if (T.target >= 0 && fail_rounds > 0)
		mem[static_cast<std::size_t>(T.target)].fail_until = std::max(mem[static_cast<std::size_t>(T.target)].fail_until, now() + fail_rounds);
	T.target = -1;
	T.engaged = false;
	T.capturing = false;
	T.wait_since = -1;
	T.focus = -1;
	T.bench_until = -1000;
	T.self_tank = false;
}
bool near_target(int gi)
{
	const auto& g = M.groups[static_cast<std::size_t>(gi)];
	const int ring = (g.reach_max > 0 ? g.reach_max : 1) + 2;
	return cheb(W.me.pos, g.anchor) <= ring + 2;
}
// A group I can finish alone (walk, clear, capture, walk back) before group `wait_gi` respawns in `left` rounds:
// the most valuable one that fits, or -1.
int filler_target(int wait_gi, int left, float* out_rate)
{
	build_team(false);
	if (travel_round != now() || travel_from != W.me.pos)
		compute_travel();
	const distance_field* back = mv::group_field(wait_gi);
	if (!back)
		return -1;
	const Claims cl = claims_for_me();
	int best = -1;
	float best_v = 0;
	for (int gi = 0; gi < M.ng; ++gi)
	{
		if (gi == wait_gi)
			continue;
		if (ring_gate_keep(gi))
			continue; // a one-camp ring gate is never captured (target_turn drops it), so it is no filler
		const auto& g = M.groups[static_cast<std::size_t>(gi)];
		const auto& m = mem[static_cast<std::size_t>(gi)];
		const std::uint16_t tr = travel[static_cast<std::size_t>(gi)];
		if (tr == UNREACH || static_cast<int>(tr) >= left || g.access != ACC_WALK || m.fail_until > now() || !reachable_target(gi) ||
			!zc::allow_fast(gi, my_slot()) || (sg_big(g) && !(big_group_nearly_dead(gi)))) // big groups are team operations (SG3), except where big_group_nearly_dead holds (OGS bit 8 REM)
			continue;
		if (m.status == GS_RESPAWN && m.respawn_at > now() + static_cast<int>(tr))
			continue;
		if (claimants(gi, my_slot(), cl) > 0)
			continue;
		const float v = group_value(g, gi, my_slot());
		if (v <= best_v)
			continue;
		const ClearEst e = estimate_cx(1, g, m, crew_for(gi, my_slot(), 0, cl));
		if (!e.feasible)
			continue;
		const std::uint16_t bd = dfget(*back, g.anchor);
		const std::uint16_t bdx = bd == UNREACH && FFX_ON ? mv::field_nb(*back, g.anchor) : bd; // the anchor is a camp tile
		if (bdx == UNREACH)
			continue;
		const float total = static_cast<float>(tr) + e.t + (static_cast<float>(rs::capture_pay(prism::has_family(rs::F_CAPTURE)))) + static_cast<float>(bdx); // the capture's own pay time (6, 4 with my Capture emblem)
		if (total > static_cast<float>(left) + (WAIT_FILL_SLACK)) // a late return is fine (the camp waits)
			continue;
		best_v = v;
		best = gi;
		*out_rate = v / std::max(1.0f, total);
	}
	return best;
}
} // namespace
int claim_target()
{
	if (ring_breaching)
		return ring_claim; // the breacher claims the ring group
	return T.target;
}
} // namespace nova::econ
