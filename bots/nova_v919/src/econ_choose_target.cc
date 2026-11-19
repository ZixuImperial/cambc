// econ_choose_target.cc: Bounds, best group, choose_target, join and filler targets.
#include "econ_internal.h"
#include "econ_lzi_sort.h"
namespace nova::econ {
namespace {
int cap_rank(int slot, const GroupI& g, float frac, float shards); // econ_capture.cc (VJN bit 1)
float shards_of(const Body& b); // econ_capture.cc (VJN bit 1)
int gbs_key_gates = -1, gbs_key_ring = -1, gbs_key_sga = -1, gbs_key_dist = -1;
std::vector<std::pair<float, int>> opr_out;
bool gbr_want = false;  // best_group: this call is my own choice (set around its group_bounds call)
bool gbr_stop = false;  // the loop stopped; the list so far is kept in gbr_out
int gbr_gi = 0, gbr_round = -1000;
std::vector<std::pair<float, int>> gbr_out;
bool gba_lazy = false; // X3I bit 1 GBA1: the paused list is still in the scratch buffer (not in gbr_out)
int gba_n = 0;         // X3I bit 1: its length
int gbr_trav = -1000; // travel_round when the loop stopped (a resumed stop keeps the first stop's)
// b2147 FSQ1 (caller read the flag): this choice's one skip: the turn it starts (now() holds through the engine's suspension, so the
// tail round runs on too); a later turn pauses as live
static inline bool fsq_skip()
{
	if (fsq_r < 0)
		fsq_r = now();
	return fsq_r == now();
}
int fgp_rej = -1000;  // b2194 FGP1: the round a targeted body's stored pass was rejected
// CGB bit 1: gate-group member tiles seen empty (dead), and the groups reachable from our spawn with only living camp tiles blocked.
int cgb_round = -1;
bool cgb_dirty = false, cgb_init = false;
static __attribute__((noinline)) bool cgb_open(int gi)
{
	static bitboard cgb_dead;
	static std::vector<std::uint8_t> cgb_ok; // per group: reachable through a seen breach
	if (!cgb_init)
	{
		cgb_init = true;
		cgb_dead.clear();
	}
	if (cgb_round != now())
	{
		cgb_round = now();
		std::vector<std::uint8_t> isgate(static_cast<std::size_t>(M.ng), 0);
		for (const auto& go : gate_of)
			for (const int og : go)
				if (og >= 0 && og < M.ng)
					isgate[static_cast<std::size_t>(og)] = 1;
		for (int og = 0; og < M.ng; ++og)
			if (isgate[static_cast<std::size_t>(og)])
				for (const int ci : M.groups[static_cast<std::size_t>(og)].members)
				{
					const vec2 p = M.camps[static_cast<std::size_t>(ci)].pos;
					if (!bbget(W.vis, p))
						continue;
					const bool dead = !bbget(W.occ_camps, p);
					if (dead != bbget(cgb_dead, p))
					{
						bbset(cgb_dead, p, dead);
						cgb_dirty = true;
					}
				}
	}
	if (cgb_dirty && fuel() > CGB_FLOOR + 3L * G.w * G.h)
	{
		cgb_dirty = false;
		cgb_ok.assign(static_cast<std::size_t>(M.ng), 0);
		if (!cgb_dead.is_empty())
		{
			distance_field f;
			bitboard visited;
			f.compute(M.block_camps & ~cgb_dead, M.my_spawn, visited);
			for (int k = 0; k < M.ng; ++k)
				cgb_ok[static_cast<std::size_t>(k)] = M.group_dist_blocked(f, M.groups[static_cast<std::size_t>(k)]) != UNREACH ? 1 : 0;
		}
	}
	return static_cast<std::size_t>(gi) < cgb_ok.size() && cgb_ok[static_cast<std::size_t>(gi)] != 0;
}
// CGB bit 2: gate group og is a ring gate with a one-camp breach that is not a monolith or golem (its cheapest camp by hp x str).
static __attribute__((noinline)) bool cgb_one_camp(int og)
{
	if (!M.ring)
		return false;
	int bc = -1;
	float bv = 0;
	for (const int ci : M.ring_camps)
	{
		const auto& c = M.camps[static_cast<std::size_t>(ci)];
		if (c.group != og)
			continue;
		const float v = c.hp * c.str;
		if (bc < 0 || v < bv)
		{
			bc = ci;
			bv = v;
		}
	}
	if (bc < 0)
		return false;
	const auto t = M.camps[static_cast<std::size_t>(bc)].type;
	return t != cambc::camp_type::monolith && t != cambc::camp_type::golem;
}
// One pass of the group bounds: what is read once per pass, then the loop over the groups. Every step is inlined and the fields stay
// in registers; `live` and the sightings stay in the caller, because a member whose address leaves the struct would keep the whole
// struct in memory.
// v7xx XFB GBC1: bit 64 read once a pass into a member (XFB_GBC)
#define XFB_GBC xfb_gbc
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
	bool gbb_e = false;
	float gbb_ew = -1.0f; // rate_for's endgame gold weight (gold_weight_in_gems()), on first need
	// v7xx XFB GBC1 (X355, play-identical): per-pass parts of emblem_gold_bonus, the Prospector rows and rate_for's tribute channel, read once
	bool eg_on = false;
	float eg_min = 0.0f, eg_add = 0.0f;
	const float* prp_v = nullptr; // [2*gi] prospector_gems, [2*gi+1] prospector_gold (static map data per group)
	int eg_mg = -1, eg_hold = -1, tr_min = 1, tr_base = 0, tr_per = 10;
	bool xfb_gbc = false; // XFB_ON(64), set once a pass
	bool gt_now = false; // b1990 GBH2: !M.has_home || GT.round == nrow, this pass
	// b1968 GBF (bits 1, 2): per-pass copies, set by gbf_setup only with the flag on, and the loop's template copy (gbf_run<F>)
	bool opn = false;                // GBF1: opened
	// b2131 GBZ: the word read once a pass (gz), GPM1 masks, GVT1 eg threshold (+INF when off), TFQ1 latch
	unsigned gz = 0;
	std::uint16_t m_oe = 0, m_free = 0, m_terr = 0;
	float eg_min_eff = __builtin_inff();
	bool tf_may = true;
	// F & 64: every GBZ loop bit on (constexpr); F & 128: the bits read from gz; else off
#define GBZ_ZB(b) (zb<F>(b)) // b2131 GBZ: bit b in a gbf_run<F> copy
#define GBZ_NOPL ((F & 32u) == 0) // b2131 GPT1: not the plain copy
#define GBZ_ALL_LOOP 79u // b2131 GBZ: the loop bits GPM1 GVT1 GZF1 GTN1 TFQ1
	template <unsigned F> __attribute__((always_inline)) bool zb(unsigned b) const
	{
		if constexpr ((F & 64u) != 0)
			return true;
		else if constexpr ((F & 128u) != 0)
			return (gz & b) != 0;
		else
			return false;
	}
	const GroupI* gbf_g = nullptr;   // GBF2: M.groups, mem, team_ok_round, team_ok, gate_done, gate_of bases
	const GroupMem* gbf_m = nullptr;
	const int* gbf_tor = nullptr;
	const signed char* gbf_tok = nullptr;
	const signed char* gbf_gdn = nullptr;
	const std::array<int, 3>* gbf_gof = nullptr;
	const unsigned char* gbf_tb = nullptr; // GBF2: travel row base and stride (d_home in M.groups, or trav_of)
	std::size_t gbf_ts = 0;
	const unsigned char* gbf_sb = nullptr; // GBF2: GBS row base and stride (tab, or live with stride 0)
	std::size_t gbf_ss = 0;
	template <unsigned F> __attribute__((always_inline)) const GroupI& grp(int gi) const
	{
		if constexpr ((F & 2u) != 0)
			return gbf_g[gi];
		else
			return M.groups[static_cast<std::size_t>(gi)];
	}
	template <unsigned F> __attribute__((always_inline)) const GroupMem& gmem(int gi) const
	{
		if constexpr ((F & 2u) != 0)
			return gbf_m[gi];
		else
			return mem[static_cast<std::size_t>(gi)];
	}
	template <unsigned F> __attribute__((always_inline)) bool opd() const
	{
		if constexpr ((F & 1u) != 0)
			return opn;
		else
			return opened;
	}

	// A long pass keeps its place for the next turn.
	__attribute__((always_inline)) bool paused(int gi)
	{
		if (gbr_want && (gi & 7) == 0 && gi > gi0 && fuel() < ((htk_low) ? static_cast<long>(HTK_TAB[3]) : static_cast<long>(TCF_TAB[2])) && !(fsq_pass && fsq_skip())) // keep the place for the next turn (b2147 HTK2: safe-turn slice; FSQ1: once per choice, run on)
		{
			gba_lazy = true;
			gba_n = nout;
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
				if (!team_feasible(og) && !(cgb_one_camp(og))) // CGB bit 2: one breach camp is enough
				{
					closed = true;
					break;
				}
			}
			if (closed && !(cgb_open(gi)) && !(cgb_fails >= CGB_N && cgb_caged())) // CGB bits 1, 4
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
			if (wait > ((crew_on ? crew_wait_limit(g) : 25.0f)) && !(crew_on && !use_home && respawn_wait_lifted(gi, self, wait))) // MCK bit 1
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
		if (s.fl & GB_ALTW)
			t += s.altw; // filled once the analysis is done
		else if (s.fl & GB_GEMS)
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
			{
				ow = emblem_gold_weight(ow); // GPV bit 1 G1 (econ.h): the bound carries my weight
				if (XFB_GBC) // v7xx XFB GBC1: emblem_gold_bonus(gold_raw, ow)'s state, read after the refresh above; nothing in the pass changes it
				{
					eg_on = !(!gpv1_ok || gpv_susp || gpv1_done || gpv1_d <= 0);
					eg_min = static_cast<float>(gpv1_d);
					eg_add = static_cast<float>(GPV_TAB[4]) / 100.0f * 30.0f * ow;
				}
			}
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
		if (XFB_GBC)
		{
			if (eg_on && !(s.gold_f * mu_g5 < eg_min)) // v7xx XFB GBC1: emblem_gold_bonus (mine and opened only)
				gold_v += eg_add;
		}
		else if (self == my_slot() && opened)
			gold_v += emblem_gold_bonus(s.gold_f * mu_g5, ow);
		if (ma_gems) // EB4 MTG: as group_value (b2295 MTG bit 1)
			gems_v += 2.0f * s.gems_f * ma_gold_mult * ow;
		if (prp_row) // before the Prism factors, as group_value
		{
			if (XFB_GBC) // v7xx XFB GBC1: the per-group Prospector values cached (static map data)
			{
				if (!prp_v)
				{
					static std::vector<float> gbc_prp;
					if (gbc_prp.size() != 2 * static_cast<std::size_t>(ng))
					{
						gbc_prp.resize(2 * static_cast<std::size_t>(ng));
						for (int k = 0; k < ng; ++k)
						{
							const auto& gk = M.groups[static_cast<std::size_t>(k)];
							gbc_prp[2 * static_cast<std::size_t>(k)] = prospector_gems(gk, k);
							gbc_prp[2 * static_cast<std::size_t>(k) + 1] = prospector_gold(gk, k);
						}
					}
					prp_v = gbc_prp.data();
				}
				gems_v += prp_v[2 * gi] * gw;
				if (ma_gems) // b2295 MTP1: as group_value
					gems_v += 2.0f * prp_v[2 * gi] * ma_gold_mult * ow;
				gold_v += prp_v[2 * gi + 1] * mu_g5 * ow;
			}
			else
			{
				gems_v += prospector_gems(g, gi) * gw;
				if (ma_gems) // b2295 MTP1: as group_value
					gems_v += 2.0f * prospector_gems(g, gi) * ma_gold_mult * ow;
				gold_v += prospector_gold(g, gi) * mu_g5 * ow;
			}
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
		if (!gv_exact && (s.fl & GB_MCKL))
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
				float chan = 0.0f;
				if (XFB_GBC) // v7xx XFB GBC1: rs::tribute_rounds(n, false) inlined (its integer formula), then cbn_tt(n, true) for a Tribute holder
				{
					if (eg_mg < 0)
					{
						eg_mg = static_cast<int>(self == my_slot() ? W.me.gems : 0u);
						const rs::Rules& r = rs::rules();
						tr_min = r.trib_min;
						tr_base = r.trib_base;
						tr_per = r.trib_per;
					}
					const int n = eg_mg + g.gems;
					if (n > 0)
					{
						chan = static_cast<float>(std::max(tr_min, tr_base + (n + tr_per - 1) / tr_per));
						if (chan > 0.0f && eg_hold < 0)
							eg_hold = slot_holds_tribute(self) ? 1 : 0;
						if (chan > 0.0f && eg_hold > 0)
							chan = static_cast<float>(cbn_tt(n, true));
					}
				}
				else
				{
					chan = static_cast<float>(rs::tribute_rounds(static_cast<int>(self == my_slot() ? W.me.gems : 0u) + g.gems, false));
					if (chan > 0.0f && slot_holds_tribute(self))
						chan = static_cast<float>(cbn_tt(static_cast<int>(self == my_slot() ? W.me.gems : 0u) + g.gems, true));
				}
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
			if ((!XFB_GBC || (gi & 7) == 0) && paused(gi)) // v7xx XFB GBC1: paused() acts only on (gi & 7) == 0
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
			if (m.fail_until > nrow || (s.fl & GB_ZERO) || (s.fl & GB_RGK) || ((s.fl & GB_SGB) && !(big_group_nearly_dead(gi)))) // as rate_for (SGB bit 2)
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
			if (gbr_round >= 0 && T.target >= 0 && !bounds_resume_ready()) // b2194 FGP1 (RC X635): a targeted body's stored pass is thrown away
				fgp_rej = now();
			if (gba_lazy) // X3I bit 1 GBA1: the list is already in place at out[0, gba_n)
			{
				gba_lazy = false;
				if (bounds_resume_ready() && gbr_gi <= ng && gba_n <= ng)
				{
					gi0 = gbr_gi;
					nout = gba_n;
				}
			}
			else if (bounds_resume_ready() && gbr_gi <= ng && gbr_out.size() <= static_cast<std::size_t>(ng))
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
			dmax = std::max({ dmax, ECX_TM(static_cast<std::size_t>(s)).dps1, ECX_TM(static_cast<std::size_t>(s)).dps3 });
		{
			float rmax = 0;
			for (int s = 0; s < TM.n && s < 8; ++s)
				rmax = std::max(rmax, ECX_TM(static_cast<std::size_t>(s)).ret);
			dmax += 2.5f * rmax / 0.85f;
		}
		dclear = std::max(10.0f, 1.3f * 0.85f * dmax); // 1.3: slack for live stats above the team view
		for (int s = 0; s < TM.n && s < 8; ++s)
			chain_max = std::max(chain_max, ECX_TM(static_cast<std::size_t>(s)).chain);
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
		gbb_e = (bankable() || M.ring); // v683 EGA: the bound follows rate_for's end test
		cpb_on = crystal_gems_scarce() && crystal_plan_trip_body(self);
		xfb_gbc = true; // v7xx XFB GBC1
	}
	template <unsigned F> __attribute__((always_inline)) bool gbf_blocked(int gi)
	{
		const auto i = static_cast<std::size_t>(gi);
		bool tfv;
		if (!((F & 2u) != 0 || tf_fast)) // GBF2 runs only with tf_fast
			tfv = team_feasible(gi);
		else
		{
			// team_feasible(gi)'s body
			if ((F & 8u) == 0 && tf_est_round != nrow) // b1990 GBH1 (GBH_ON(1)): F & 8 resets once before the loop
			{
				tf_est_round = nrow;
				tf_est_n = 0;
			}
			if (GBZ_ZB(64))
			{
				if (tf_may && nrow - ((F & 2u) != 0 ? gbf_tor[i] : team_ok_round[i]) >= 25 && tf_est_n < 4) // b2131 GBZ TFQ1: fuel only falls in a pass
				{
					if (fuel() > 60000)
						team_feasible_refresh(i);
					else
						tf_may = false;
				}
			}
			else
			if (nrow - ((F & 2u) != 0 ? gbf_tor[i] : team_ok_round[i]) >= 25 && tf_est_n < 4 && (fuel() > 60000)) // GBF2
				team_feasible_refresh(i);
			tfv = ((F & 2u) != 0 ? gbf_tok[i] : team_ok[i]) != 0;
		}
		if (!tfv)
			return true;
		// gates(gi)'s body
		const std::array<int, 3>* gs;
		if (!((F & 2u) != 0 || gt_fast)) // GBF2 runs only with gt_fast
			gs = &gates(gi);
		else if ((F & 16u) != 0 && GBZ_ZB(8) && gt_now) // b2131 GBZ GTN1: the latch first (both reads pure)
			gs = (F & 2u) != 0 ? &gbf_gof[i] : &gate_of[i];
		else if (((F & 2u) != 0 ? gbf_gdn[i] : gate_done[i]) || ((F & 16u) != 0 ? gt_now : (!M.has_home || GT.round == nrow)) || (fuel() < 50000)) // b1990 GBH2 (GBH_ON(2)): F & 16 reads the latch
			gs = (F & 2u) != 0 ? &gbf_gof[i] : &gate_of[i];
		else
		{
			gs = &gates_step(gi);
			if constexpr ((F & 16u) != 0) // b1990 GBH2: gates_step may set GT.round
				gt_now = !M.has_home || GT.round == nrow;
		}
		if ((*gs)[0] >= 0) // a trace fills the entries in order: an empty first one means none
		{
			bool closed = false;
			for (const int og : *gs)
			{
				if (og < 0)
					continue;
				const auto& mo = gmem<F>(og);
				if (mo.status == GS_CLEARED || mo.status == GS_RESPAWN)
					continue;
				if (!team_feasible(og) && !(cgb_one_camp(og))) // CGB bit 2: one breach camp is enough
				{
					closed = true;
					break;
				}
			}
			if (closed && !(cgb_open(gi)) && !(cgb_fails >= CGB_N && cgb_caged())) // CGB bits 1, 4
				return true;
		}
		return false;
	}
	template <unsigned F> __attribute__((always_inline)) float gbf_crew_bound(const GBS& s)
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
		if (GBZ_ZB(1) ? (s.fl & m_oe) != 0 : (!opd<F>() && (s.fl & GB_OE))) [[unlikely]] // GBF1: a branch, not a select (b2131 GPM1: mask)
			cbb = std::max(cbb, OE_BONUS); // its crew bonus is in the bound
		return cbb;
	}
	template <unsigned F> __attribute__((always_inline)) float gbf_value_bound(const GroupI& g, int gi, const GBS& s)
	{
		// group_value(g, gi, self)
		if (ow < 0)
		{
			ow = gold_weight_in_gems();
			if (self == my_slot() && opd<F>())
			{
				ow = emblem_gold_weight(ow); // GPV bit 1 G1 (econ.h): the bound carries my weight
				if (XFB_GBC) // v7xx XFB GBC1: emblem_gold_bonus(gold_raw, ow)'s state, read after the refresh above; nothing in the pass changes it
				{
					eg_on = !(!gpv1_ok || gpv_susp || gpv1_done || gpv1_d <= 0);
					eg_min = static_cast<float>(gpv1_d);
					eg_add = static_cast<float>(GPV_TAB[4]) / 100.0f * 30.0f * ow;
					if (GBZ_ZB(2) && eg_on) // b2131 GVT1: the test's threshold, +INF when off
						eg_min_eff = eg_min;
				}
			}
			if (GBZ_ZB(2)) // b2131 GVT1: bankable() once, with ow (it does not read the gpv1 state)
				bk = bankable() ? 1 : 0;
		}
		float gw = 1.0f;
		if (!GBZ_ZB(2) && bk < 0)
			bk = bankable() ? 1 : 0;
		if (!(bk || (s.fl & GB_GATE) || ring_gw))
			gw = 0.03f;
		float gems_v = s.gems_f * gw, gold_v = s.gold_f * ow;
		if (GBZ_NOPL && cpb_on && g.access == ACC_TP) [[unlikely]] // GBF1: the pass-invariant terms as cold branches (b2131 GPT1: F & 32 has none)
			gems_v *= static_cast<float>(CP_TAB[2]) * 0.01f; // group_value's crystal-plan prize.
		if (GBZ_ZB(2))
			gold_v *= mu_g5; // b2131 GVT1: x1.0f is exact
		else if (mu_g5 != 1.0f) [[unlikely]]
			gold_v *= mu_g5;
		if (XFB_GBC)
		{
			if (GBZ_ZB(2))
			{
				if (!(s.gold_f * mu_g5 < eg_min_eff)) [[unlikely]] // b2131 GVT1: finite gold, so false when eg is off
					gold_v += eg_add;
			}
			else if (eg_on && !(s.gold_f * mu_g5 < eg_min)) [[unlikely]] // v7xx XFB GBC1: emblem_gold_bonus (mine and opened only)
				gold_v += eg_add;
		}
		else if (self == my_slot() && opd<F>())
			gold_v += emblem_gold_bonus(s.gold_f * mu_g5, ow);
		if (GBZ_NOPL && ma_gems) [[unlikely]] // EB4 MTG: as group_value (b2295 MTG bit 1)
			gems_v += 2.0f * s.gems_f * ma_gold_mult * ow;
		if (prp_row) // before the Prism factors, as group_value
		{
			if (XFB_GBC) // v7xx XFB GBC1: the per-group Prospector values cached (static map data)
			{
				if (!prp_v)
				{
					static std::vector<float> gbc_prp;
					if (gbc_prp.size() != 2 * static_cast<std::size_t>(ng))
					{
						gbc_prp.resize(2 * static_cast<std::size_t>(ng));
						for (int k = 0; k < ng; ++k)
						{
							const auto& gk = M.groups[static_cast<std::size_t>(k)];
							gbc_prp[2 * static_cast<std::size_t>(k)] = prospector_gems(gk, k);
							gbc_prp[2 * static_cast<std::size_t>(k) + 1] = prospector_gold(gk, k);
						}
					}
					prp_v = gbc_prp.data();
				}
				gems_v += prp_v[2 * gi] * gw;
				if (ma_gems) // b2295 MTP1: as group_value
					gems_v += 2.0f * prp_v[2 * gi] * ma_gold_mult * ow;
				gold_v += prp_v[2 * gi + 1] * mu_g5 * ow;
			}
			else
			{
				gems_v += prospector_gems(g, gi) * gw;
				if (ma_gems) // b2295 MTP1: as group_value
					gems_v += 2.0f * prospector_gems(g, gi) * ma_gold_mult * ow;
				gold_v += prospector_gold(g, gi) * mu_g5 * ow;
			}
		}
		if (GBZ_NOPL && gbp_fast) // group_value's Prism row (b2131 GPT1: F & 32 has none)
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
		if constexpr ((F & 1u) != 0)
			gems_v *= s.mckm; // GBF1: MCK bit 2's factor (1 off the light-mid groups; with gv_exact gems_v is unused)
		else if (!gv_exact && (s.fl & GB_MCKL))
			gems_v *= static_cast<float>(MCK_TAB[3]) / 100.0f; // MCK bit 2: the bound follows group_value
		const float gv = (GBZ_NOPL && gv_exact) ? group_value(g, gi, self) : gems_v + gold_v;
		return gv;
	}
	template <unsigned F> __attribute__((always_inline)) int gbf_run()
	{
		for (int gi = gi0; gi < ng; ++gi)
		{
			if ((!XFB_GBC || (gi & 7) == 0) && paused(gi)) // v7xx XFB GBC1: paused() acts only on (gi & 7) == 0
				return nout;
			const auto& g = grp<F>(gi);
			std::uint16_t tr;
			if constexpr ((F & 2u) != 0) // GBF2: base + stride, no select
				tr = *reinterpret_cast<const std::uint16_t*>(gbf_tb + static_cast<std::size_t>(gi) * gbf_ts);
			else
				tr = use_home ? g.d_home : trav_of[gi];
			if (tr == UNREACH)
				continue;
			if (!tab)
				group_static_fill(live, g, gi, sga);
			const GBS& s = (F & 2u) != 0 ? *reinterpret_cast<const GBS*>(gbf_sb + static_cast<std::size_t>(gi) * gbf_ss) : (tab ? tab[gi] : live);
			if (!(s.fl & GB_WALK) && !dash_group(gi, self))
				continue;
			if (gbf_blocked<F>(gi))
				continue;
			const auto& m = gmem<F>(gi);
			if (GBZ_ZB(4) ? (m.fail_until > nrow || ((s.fl & (GB_ZERO | GB_RGK | GB_SGB)) && ((s.fl & (GB_ZERO | GB_RGK)) || !big_group_nearly_dead(gi)))) : (m.fail_until > nrow || (s.fl & GB_ZERO) || (s.fl & GB_RGK) || ((s.fl & GB_SGB) && !(big_group_nearly_dead(gi))))) // as rate_for (SGB bit 2; b2131 GZF1: one test)
				continue; // rate_for rejects these
			if (trip_rejected(gi, g, m, s, tr))
				continue;
			const float cbb = gbf_crew_bound<F>(s);
			const float gv = gbf_value_bound<F>(g, gi, s);
			const float gvb = endgame_bound(g, s, gv);
			float ub = pk * cbb * 1.02f * gvb / t;
			// free-camp part of opportunity_factor(g, m)
			if (GBZ_ZB(1) ? (s.fl & m_free) != 0 : ((s.fl & GB_OPP) && opd<F>() && fc_alive > 0)) // b2131 GPM1: per-pass mask
			{
				if (free_camp_now(g, s))
					ub *= FREE_BONUS;
			}
			// territory_factor(g, gi, self, TM.claim, m, true)
			if (GBZ_ZB(1) ? ((s.fl & m_terr) == (GB_TERR | GB_TERRD) && m.status == GS_ALIVE && m.hp_left >= 0) : (opd<F>() && (s.fl & GB_TERR)))
			{
				if (GBZ_ZB(1) || ((s.fl & GB_TERRD) && m.status == GS_ALIVE && m.hp_left >= 0))
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
	// b1968 GBF: the per-pass copies for the flag bits gf (1, 2); returns the bits that run (GBF2 only while no vector can resize)
	unsigned gbf_setup(unsigned gf)
	{
		opn = opened;
		if ((gz & 1u) != 0) // b2131 GBZ GPM1: opn and fc_alive are fixed for the pass
		{
			m_oe = opn ? 0 : GB_OE;
			m_free = (opn && fc_alive > 0) ? GB_OPP : 0;
			m_terr = opn ? static_cast<std::uint16_t>(GB_TERR | GB_TERRD) : 0;
		}
		if ((gf & 2u) != 0)
		{
			if (tf_fast && gt_fast && mem.size() >= static_cast<std::size_t>(ng) && M.groups.size() >= static_cast<std::size_t>(ng))
			{
				gbf_g = M.groups.data();
				gbf_m = mem.data();
				gbf_tor = team_ok_round.data();
				gbf_tok = team_ok.data();
				gbf_gdn = gate_done.data();
				gbf_gof = gate_of.data();
				if (use_home)
				{
					gbf_tb = reinterpret_cast<const unsigned char*>(&gbf_g->d_home);
					gbf_ts = sizeof(GroupI);
				}
				else
				{
					gbf_tb = reinterpret_cast<const unsigned char*>(trav_of);
					gbf_ts = sizeof(std::uint16_t);
				}
				if (tab)
				{
					gbf_sb = reinterpret_cast<const unsigned char*>(tab);
					gbf_ss = sizeof(GBS);
				}
				else
				{
					gbf_sb = reinterpret_cast<const unsigned char*>(&live);
					gbf_ss = 0;
				}
			}
			else
				gf &= ~2u;
		}
		return gf & 3u;
	}
};
// Order-preserving float key, its inverse, and the lazy heap best_group pops from.
std::vector<std::uint64_t> tcf_keys;
bool tcf_lazy = false;      // this call's list is a heap in tcf_keys; cand fills as it pops
long fg_pre_f0 = 0; // fuel and round at choose_target's start
int fg_pre_r0 = -1;
fg::Cost fg_bw; // the squad stick's best_within (rated near the leader's group)
long fg_bw_used = 0; // this choice's stick cost, left out of fg_pre
std::vector<std::pair<float, int>> st_cand;
LziS lzi_st;            // b2187 LZI1: st_cand's ranges still to sort
LziS* lzi_req = nullptr; // b2187 LZI1: best_group's list is sorted as read (its pending ranges)
int st_round = -1000;
bool pec_st = false;    // PEC bit 1: st_cand is a resumed list of a body with a target (valid on round st_round + 1 only)
int pec_res_r = -1000; // PEC bit 1: the round a resumed list was rated (apply_retarget_choice's margin)
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
	if (MCK_LIGHT_MID(g))
		f |= GB_MCKL;
	if (g.gems > 0 && M.done())
	{
		f |= GB_ALTW;
		s.altw = static_cast<float>(B438_ALTW_X100) / 100.0f * (altar_walk(g));
	}
	s.fl = f;
	s.mckm = (f & GB_MCKL) ? static_cast<float>(MCK_TAB[3]) / 100.0f : 1.0f;
}
// The table, valid for this call: built once the map analysis is done, rebuilt when the gate list or the ring changes.
const GBS* group_static_table(bool sga)
{
	if (!(M.done() || M.distances_known()))
		return nullptr; // the group distances (d_home, access, contest) may still change
	const int kg = static_cast<int>(M.gate_groups.size()), kr = M.ring ? 1 : 0, ks = sga ? 1 : 0, kd = M.done() ? 2 : 1;
	if (kd == 2 && gbs_key_dist == 1 && gbs_tab.size() == static_cast<std::size_t>(M.ng) && kg == gbs_key_gates && kr == gbs_key_ring && ks == gbs_key_sga)
	{
		// v7xx XFB GSI1 (X346): only the map analysis finished: add the altar-walk part in place (the full fill's own expression)
		for (std::size_t i = 0; i < static_cast<std::size_t>(M.ng); ++i)
		{
			const GroupI& g = M.groups[i];
			if (g.gems > 0)
			{
				gbs_tab[i].fl |= GB_ALTW;
				gbs_tab[i].altw = static_cast<float>(B438_ALTW_X100) / 100.0f * (altar_walk(g));
			}
		}
		gbs_key_dist = kd;
	}
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
// XEP STNP1 (caller read the flag): true when group_static_table(sga) would rebuild every row now (its key test; the GSI1 in-place
// altar-walk step and a current table are not rebuilds)
bool xep_rebuild_due(bool sga)
{
	if (!(M.done() || M.distances_known()))
		return false; // the table call returns null anyway
	const int kg = static_cast<int>(M.gate_groups.size()), kr = M.ring ? 1 : 0, ks = sga ? 1 : 0, kd = M.done() ? 2 : 1;
	const bool same = gbs_tab.size() == static_cast<std::size_t>(M.ng) && kg == gbs_key_gates && kr == gbs_key_ring && ks == gbs_key_sga;
	if (same && (kd == gbs_key_dist || (kd == 2 && gbs_key_dist == 1)))
		return false;
	return true;
}
} // namespace
// XEP QTB1 (caller read the flag): the staged table, its keys and its row cursor
std::vector<GBS> xep_stage;
int xep_si = 0, xep_skg = -1, xep_skr = -1, xep_sks = -1;
void xep_qtb_slice(long reserve, bool sga, int kg, int kr, int ks)
{
	if (xep_stage.size() != static_cast<std::size_t>(M.ng) || kg != xep_skg || kr != xep_skr || ks != xep_sks)
	{
		xep_stage.assign(static_cast<std::size_t>(M.ng), GBS{});
		xep_si = 0;
		xep_skg = kg;
		xep_skr = kr;
		xep_sks = ks;
	}
	while (xep_si < M.ng && fuel() > reserve + static_cast<long>(XEP_TAB[4]))
	{
		group_static_fill(xep_stage[static_cast<std::size_t>(xep_si)], M.groups[static_cast<std::size_t>(xep_si)], xep_si, sga);
		++xep_si;
	}
	if (xep_si < M.ng)
		return;
	gbs_tab.swap(xep_stage); // complete: the same rows a full rebuild fills (map done: kd 2)
	gbs_key_gates = kg;
	gbs_key_ring = kr;
	gbs_key_sga = ks;
	gbs_key_dist = 2;
	xep_stage.clear();
	xep_si = 0;
	xep_skg = -1;
}
void gtb_prebuild(long reserve)
{
	if (M.ng < BOUNDS_MIN_GROUPS || !M.done() || M.ring_todo || M.open_todo)
		return;
	const bool sga = sg_any();
	const int kg = static_cast<int>(M.gate_groups.size()), kr = M.ring ? 1 : 0, ks = sga ? 1 : 0;
	const bool same = gbs_tab.size() == static_cast<std::size_t>(M.ng) && ks == gbs_key_sga;
	if (same && kg == gbs_key_gates && kr == gbs_key_ring)
		return; // current, or only kd 1 -> 2 (GSI1 sets the altar walk in place on the next bounds call, a few k)
	xep_qtb_slice(reserve, sga, kg, kr, ks); // XEP QTB1: sliced, not all-or-nothing
	return;
}
namespace {
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
	if (!(gbr_round >= 0 && now() > gbr_round && now() - gbr_round <= 2 && cheb(gbr_pos, W.me.pos) <= 1 && travel_from == gbr_pos))
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
	const unsigned gbf = GBF_WORD() & 3u; // b1968 GBF bits 1, 2: read once a pass
	if (gbf == 0)
		return b.run();
	const unsigned gbh = (8u) | (16u);
	b.gz = (M.ng > GBZH_TAB[2]) ? static_cast<unsigned>(GBZH_TAB[1]) : 0u; // b2131 GBZ: read once a pass (b2147 GBZH: > GBZH_G groups only)
	const unsigned gf = b.gbf_setup(gbf);
	if ((gbh & 8u) != 0 && tf_est_round != b.nrow) // GBH1: gbf_blocked's reset, once (every tf_est_n reader resets first)
	{
		tf_est_round = b.nrow;
		tf_est_n = 0;
	}
	b.gt_now = !M.has_home || GT.round == b.nrow; // GBH2
	switch (gf | gbh)
	{
	case 1 | 8: return b.gbf_run<1 | 8>();
	case 2 | 8: return b.gbf_run<2 | 8>();
	case 3 | 8: return b.gbf_run<3 | 8>();
	case 1 | 16: return b.gbf_run<1 | 16>();
	case 2 | 16: return b.gbf_run<2 | 16>();
	case 3 | 16: return b.gbf_run<3 | 16>();
	case 1 | 24: return b.gbf_run<1 | 24>();
	case 2 | 24: return b.gbf_run<2 | 24>();
	case 3 | 24:
		if (b.gz != 0) // b2131 GBZ: 64 every loop bit on, 128 the bits read from gz; 32 GPT1's plain copy
		{
			const bool plain = (b.gz & 16u) != 0 && !b.ma_gems && !b.gbp_fast && !b.gv_exact && !b.cpb_on;
			if ((b.gz & GBZ_ALL_LOOP) == GBZ_ALL_LOOP)
				return plain ? b.gbf_run<3 | 24 | 64 | 32>() : b.gbf_run<3 | 24 | 64>();
			return plain ? b.gbf_run<3 | 24 | 128 | 32>() : b.gbf_run<3 | 24 | 128>();
		}
		return b.gbf_run<3 | 24>();
	default: return b.run();
	}
	switch (b.gbf_setup(gbf))
	{
	case 1: return b.gbf_run<1>();
	case 2: return b.gbf_run<2>();
	case 3: return b.gbf_run<3>();
	default: return b.run();
	}
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
	if (self == my_slot() && !(M.ng > GBZH_TAB[2] && now() - klx_last >= 20)) // b2131 GBZ KLX1: no kill_round is newer than klx_last
		for (int k = 0; k < nout; ++k) // rate_for's x1.3 near a recent kill is in the bound.
			if (now() - mem[static_cast<std::size_t>(out[k].second)].kill_round < 20)
				out[k].first *= (static_cast<float>(B467_KILLW_X100) / 100.0f);
	if (self == my_slot() && W.me.kit && prism_layer::phm() && opened && static_cast<int>(W.me.gems) < PHM_TAB[2])
		for (int k = 0; k < nout; ++k)
			out[k].first *= prism_mate_bound(M.groups[static_cast<std::size_t>(out[k].second)]);
	if (lzi_req != nullptr) // b2187 LZI1/LZI2: the caller's list, unsorted; its reader sorts each index it reaches
	{
		cand.assign(out, out + nout);
		lzi::start(*lzi_req, nout);
		return;
	}
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
	cand.assign(out, out + nout);
	return;
}
std::pair<float, int>* group_bounds_buffer()
{
	static std::vector<std::pair<float, int>> buf; // the list is written here, then copied into cand once
	if (buf.size() < static_cast<std::size_t>(M.ng))
		buf.resize(static_cast<std::size_t>(M.ng));
	return buf.data();
}
// b2368 BNX (RC X912): my own list's bounds raised to the rate terms the bound left out; each factor >= 1, so no candidate is removed.
static __attribute__((noinline)) void bnx_bounds(const std::uint16_t* trav_of, bool use_home, std::pair<float, int>* out, int nout)
{
	const bool wl = willow_layer::type(W.me.type); // rate_for's wl2_pull (econ_rate.cc:400)
	const bool ecl = opened && (map_class() & 1) != 0; // late_factors' ECL row
	if (!wl && !ecl)
		return;
	for (int k = 0; k < nout; ++k)
	{
		const int gi = out[k].second;
		const auto& g = M.groups[static_cast<std::size_t>(gi)];
		const std::uint16_t tr = use_home ? g.d_home : trav_of[gi];
		float ub = out[k].first;
		if (ecl) // BNX2: the largest cell over walk buckets >= wb(tr); sb and cbk as late_factors
		{
			const int wb = tr <= 6 ? 0 : (tr <= 12 ? 1 : (tr <= 20 ? 2 : (tr <= 35 ? 3 : 4)));
			const float gv = static_cast<float>(g.gems) + 0.35f * static_cast<float>(g.gold);
			const int sb = gv < 15.0f ? 0 : (gv < 40.0f ? 1 : (gv < 100.0f ? 2 : 3));
			const int cbk = g.contest <= 0.30f ? 0 : (g.contest <= 0.60f ? 1 : 2);
			int cmax = 1000;
			for (int b = wb; b <= 4; ++b)
				cmax = std::max(cmax, static_cast<int>(ECL_CELL[12 * b + 3 * sb + cbk]));
			ub *= std::sqrt(static_cast<float>(cmax) / 1000.0f);
		}
		if (wl) // BNX1: the same pull rate_for applies to her rate
			ub = support::wl2_pull(gi, ub);
		out[k].first = ub;
	}
}
void group_bounds_bc(int self, const std::uint16_t* trav_of, bool use_home, std::vector<std::pair<float, int>>& cand)
{
	std::pair<float, int>* out = group_bounds_buffer();
	if (gba_lazy && !gbr_want) // X3I bit 1 GBA1: another body's list will overwrite the buffer: keep the paused one first
	{
		gbr_out.assign(out, out + gba_n);
		gba_lazy = false;
	}
	if (gbr_want && !gbr_stop && !opr_on && fuel() < ((htk_low) ? static_cast<long>(HTK_TAB[3]) : static_cast<long>(TCF_TAB[2])) && !bounds_resume_ready() && !(fsq_pass && fsq_skip())) // XEP GBEP1: a fresh pass under the loop's pause floor waits whole (gbr_gi 0)
	{
		gba_lazy = true;
		gba_n = 0;
		gbr_gi = 0;
		gbr_round = now();
		gbr_trav = travel_round;
		gbr_pos = W.me.pos;
		gbr_stop = true;
		return;
	}
	const bool sga = sg_any(); // static map data, computed once
	const GBS* xep_tab = (gbr_want && xep_rebuild_due(sga) && fuel() < static_cast<long>(XEP_TAB[2]) + static_cast<long>(XEP_TAB[3]) * static_cast<long>(M.ng)) ? nullptr : group_static_table(sga); // XEP STNP1
	const int nout = group_bounds_loop(self, trav_of, use_home, out, xep_tab, sga);
	if (gbr_want && !gbr_stop && fuel() < TCF_TAB[2] && !(fsq_pass && fsq_skip())) // the order too waits for the next turn (b2147 FSQ1: once per choice, run on)
	{
		gba_lazy = true;
		gba_n = nout;
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
	if (self == my_slot()) // b2368 BNX (RC X912): the bound covers the rate's Willow pull / VTK / ECL terms
		bnx_bounds(trav_of, use_home, out, nout);
	group_bounds_finish(self, out, nout, cand);
}
void group_bounds(int self, const std::uint16_t* trav_of, bool use_home, std::vector<std::pair<float, int>>& cand)
{
	group_bounds_bc(self, trav_of, use_home, cand); // on every map
}
static __attribute__((noinline)) bool pec_stage_ready() { return !st_cand.empty() && now() == st_round + 1 && cheb(st_pos, W.me.pos) <= 1; } // PEC bit 1
bool stage_ready()
{
	if (pec_st)
		return pec_stage_ready(); // PEC bit 1: a resumed list only on the next round, same tile or one step
	return !st_cand.empty() && now() > st_round && now() - st_round <= CHOICE_STAGE_KEEP &&
		(cheb(st_pos, W.me.pos) <= 1); // b2366 ZCS bit 4 (RC X789 STGM1): one tile, as PEC's stage
}
// PEC bit 1: the floor cut this call's loop at cand[ci] with its bound above the best found, for a body with a target: keep the
// unrated rest (bit 2: its PEC_K best bounds) for the next round.
static __attribute__((noinline)) void pec_store(std::vector<std::pair<float, int>>& cand, std::size_t ci, bool lazy)
{
	if (lazy)
		bounds_heap_drain(cand); // the heap's rest, appended best first
	st_cand.assign(cand.begin() + static_cast<std::ptrdiff_t>(std::min(ci, cand.size())), cand.end());
	st_round = now();
	st_pos = W.me.pos;
	pec_st = !st_cand.empty();
	PEC_CNT(1, pec_st);
}
template <int DM>
int best_group(int self, const std::uint16_t* trav_of, bool use_home, const Claims& cl, int max_extra, float* out_rate, int* out_crew,
	long floor = PLAN_EVAL_FLOOR) // fuel for decisions
{
	// Candidates by an upper bound of their rate, best first: the exact (costly) rate is computed only while a
	// candidate can still beat the best so far, and never below a fuel floor.
	static std::vector<std::pair<float, int>> cand;
	static LziS lzc; // b2187 LZI1: cand's ranges still to sort
	const bool mine = self == my_slot() && !use_home && trav_of == travel.data();
	const bool staged = mine && stage_ready();
	if (staged) // FB2 bit 4 FU3: the same elements, copied as bytes
	{
		cand.assign(st_cand.begin(), st_cand.end());
		lzi::shift(lzc, lzi_st, 0); // b2187 LZI1: the stored list's ranges come with it
	}
	else
	{
		tcf_lazy = false;
		(void)0; // A heap, popped below (hoard-crew mode 2 re-sorts the whole list).
		if (mine && T.target < 0 && !(DM & 2) && M.ng > HTK_TAB[2]) // b2147 HTK2: my own target-less choice on a > HTK_G map, safe turn
			htk_low = opened && W.enemies.empty() && !combat::took_damage(2) && mv::camp_threat(W.me.pos) <= 0.0f && !bbget(M.camp_tiles, W.me.pos) &&
				!(W.me.kit && W.me.kit->dash_stun);
		if (mine && M.ng > FSQ_TAB[2]) // b2147 FSQ1: my own target-less choice on a > FSQ_G map, safe standing turn
		{
			if (T.target >= 0)
				fsq_r = -1;
			fsq_pass = T.target < 0 && fsq_r < 0 && opened && W.enemies.empty() && !combat::took_damage(2) && mv::camp_threat(W.me.pos) <= 0.0f &&
				!bbget(M.camp_tiles, W.me.pos) && !(W.me.kit && W.me.kit->dash_stun);
		}
		gbr_want = static_cast<bool>(mine);
		gbr_stop = false;
		lzi_req = &lzc;
		group_bounds(self, trav_of, use_home, cand);
		lzi_req = nullptr;
		(void)0;
		gbr_want = false;
		htk_low = false;
		fsq_pass = false;
		if (gbr_stop) // no list this turn; the choice goes on next turn from the same tile
		{
			if (mine && fgp_rej == now() && fg_pre_r0 >= 0) // b2194 FGP1 (RC X635): the abandoned pass needed at least this turn's slice
				fg::note(fg_pre, fg::fuel_used_since(fg_pre_f0, fg_pre_r0) + static_cast<long>(TCF_TAB[2]));
			gbr_stop = false;
			gbr_defer = true;
			tcf_lazy = false;
			*out_rate = 0;
			*out_crew = 1;
			return -1;
		}
		if (DM & 2)
		{
			lzi::drain(lzc, reinterpret_cast<LziKV*>(cand.data())); // b2187 LZI1: the whole list, as std::sort's
			hoard_crew_bounds(cand);
		}
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
	const bool xic_evw = XIC_ON(4096); // v723 XIC bit 4096 EVW1: ev is only tested for emptiness: a bool
	bool ev_any = false;
	if (!xic_evw)
		ev.clear();
	if (staged)
		floor += CHOICE_STAGE_SPARE; // leave the walk to the chosen group its fuel
	const bool lnr = mine && opened;
	if (lnr)
		nova::econ::linear_score::begin();
	const bool lazy = tcf_lazy && !staged;
	std::size_t pec_ci = 0; // PEC bit 1: where the floor cut the loop (0: no cut)
	if (staged && pec_st)
		pec_res_r = now(); // PEC bit 1: this call rates a resumed list
	const float rcb_pull = 1.0f; // v699 RCB bit 32 WHV1: her bound takes the Willow pull
	for (std::size_t ci = 0;; ++ci)
	{
		if (ci >= cand.size() && !(lazy && bounds_heap_pop(cand)))
			break;
		lzi::need(lzc, reinterpret_cast<LziKV*>(cand.data()), static_cast<int>(ci)); // b2187 LZI1: cand[ci] final
		const float ub = cand[ci].first;
		const int gi = cand[ci].second;
		if ((ub <= best_r) || ub <= 0.0f) // v699 RCB bit 32 WHV1
			break;
		if (fuel() < floor)
		{
			// Below the fuel floor: stop rating further candidates.
			pec_ci = ci + 1; // PEC bit 1: cand[ci] (bound above best_r) is unrated
			break;
		}
		const auto& g = M.groups[static_cast<std::size_t>(gi)];
		const std::uint16_t tr = use_home ? g.d_home : trav_of[gi];
		int crew = 1;
		const float r = rate_for<DM>(gi, self, tr, cl, max_extra, &crew);
		if (xic_evw && r > 0)
			ev_any = true; // v723 XIC bit 4096 EVW1
		if (!XIC_ON(4096) && r > 0)
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
		pec_st = false; // PEC bit 1: a resumed list is used once
	if (mine && !staged && pec_ci > 0 && T.target >= 0)
	{
		pec_store(cand, pec_ci - 1, lazy); // PEC bit 1: a body with a target resumes the cut list next round
		lzi::shift(lzi_st, lzc, static_cast<int>(pec_ci - 1)); // b2187 LZI1: the unsorted rest goes with it (every range starts after ci)
	}
	else if (mine)
	{
		if (!staged && (XIC_ON(4096) ? !ev_any : ev.empty()) && best < 0 && fuel() < floor && !cand.empty() && T.target < 0) // only a body with no target
		{
			if (lazy)
				bounds_heap_drain(cand); // the whole list
			if (pec_ci > 0)
			{
				// b2366 ZCS bit 1 (RC X786 ZCS1): only the unrated rest, from the cut (as pec_store); the rated head all rated <= 0
				st_cand.assign(cand.begin() + static_cast<std::ptrdiff_t>(std::min(pec_ci - 1, cand.size())), cand.end());
				lzi::shift(lzi_st, lzc, static_cast<int>(pec_ci - 1));
			}
			else
			{
				st_cand = cand; // rate them on the next turn
				lzi::shift(lzi_st, lzc, 0); // b2187 LZI1
			}
			st_round = now();
			st_pos = W.me.pos;
		}
		else if (staged && pec_ci > 0 && (XIC_ON(4096) ? !ev_any : ev.empty()) && best < 0 && T.target < 0)
		{
			// b2366 ZCS bit 2 (RC X786 ZCS1): a staged run cut again with no pick re-stages its own unrated rest, so turns walk down the list
			st_cand.assign(cand.begin() + static_cast<std::ptrdiff_t>(std::min(pec_ci - 1, cand.size())), cand.end());
			lzi::shift(lzi_st, lzc, static_cast<int>(pec_ci - 1));
			st_round = now();
			st_pos = W.me.pos;
		}
		else
			st_cand.clear();
	}
	if (mine && best >= 0)
		fsq_r = -1; // b2147 FSQ1: the choice ended with a pick
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
		if (d <= r) // b2355 SQWL bit 4
			near[static_cast<std::size_t>(nn++)] = { d, gi };
	}
	if (XIC_ON(131072) && nn > SQ_WITHIN_MAX) // v723 XIC bit 131072 SRT3: (d, gi) keys are distinct and only the first SQ_WITHIN_MAX are read
		std::partial_sort(near.begin(), near.begin() + SQ_WITHIN_MAX, near.begin() + nn);
	else
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
		const float rr = (DM != 0) ? rate_for<DM>(gi, my_slot(), travel[static_cast<std::size_t>(gi)], cl, free_near(), &cc) : rate_for<0>(gi, my_slot(), travel[static_cast<std::size_t>(gi)], cl, free_near(), &cc); // mode 0; b2193 BWDM row 462: rate in my mode
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
// v699 VJN bit 1 (a) (spec_vjn_1110 as corrected): the crew's own holder value of claimed group gi for Vesper (body b, value v_her):
// group_value of the claimant that would hold the capture by cap_rank (an unseen mate: full health, her shards); *her_first when she
// would rank first among the claimants (GR:532, 335; interactions.md:113: each holder's own bonus). Outside her window: v_her, first.
float vjn_crew_value(const GroupI& g, int gi, int b, const Claims& cl, float v_her, bool* her_first)
{
	*her_first = true;
	if (g.gold <= 0 || now() > VJN_TAB[2] || b < 0 || b >= P.n || b >= 8 || P.type[static_cast<std::size_t>(b)] != cambc::champion_type::vesper_vale)
		return v_her;
	const Body* bb = b == my_slot() ? &W.me : W.ally_by_slot(b);
	const float bs = bb ? shards_of(*bb) : 0.0f;
	const int mine = cap_rank(b, g, bb ? bb->frac() : 1.0f, bs);
	int h = -1, hr = 0;
	for (int s = 0; s < TM.n && s < 8; ++s)
	{
		if (s == b || cl[static_cast<std::size_t>(s)] != gi)
			continue;
		const Body* a = s == my_slot() ? &W.me : W.ally_by_slot(s);
		const int th = cap_rank(s, g, a ? a->frac() : 1.0f, a ? shards_of(*a) : bs);
		if (h < 0 || th < hr)
		{
			h = s;
			hr = th;
		}
	}
	if (h < 0)
		return v_her;
	*her_first = mine < hr || (mine == hr && b < h);
	return group_value(g, gi, h);
}
// v699 VJN bit 1 (b): Vesper with a best group of her own (rate own_r) in the window, healthy, uncommitted, over the fuel floor: the
// mates' claimed group whose join gain (holder term included) beats own_r most; -1 when none does.
int vjn_join(int own, float own_r, const Claims& cl, float* gain, int* crew)
{
	int best = -1;
	float bd = own_r;
	for (int gi = 0; gi < M.ng; ++gi)
	{
		if (gi == own || claimants(gi, my_slot(), cl) == 0)
			continue;
		const std::uint16_t tr = travel[static_cast<std::size_t>(gi)];
		if (tr == UNREACH || !reachable_target(gi))
			continue;
		int cc = 1;
		const float d = join_gain(gi, my_slot(), tr, cl, static_cast<int>(tr), &cc);
		if (d > bd)
		{
			bd = d;
			best = gi;
			*crew = cc;
		}
	}
	*gain = bd;
	return best;
}
// b2273 CLTF bits 2/4 (caller read the flag): the carry's own pick, scoped to choose_target (not rate_for / best_within: no deny-stand,
// squad-stick or formation leak). Bit 2: the nearest cleared group whose carry I am, with gold or gems, within CLTF_WAIT path tiles, no
// capture running there (or out of sight), no foe within 8. Bit 4: else, with my own target farther than CLTF_TRAIL, the group the nearest
// non-carry mate within 2 of its anchor is clearing, whose carry I am (one carry per crew: no other carry claims it), within CLTF_TRAIL.
static float cltf_rate = 0.0f;
static int cltf_pay() { return rs::has(rs::families(W.me.h, now()), rs::F_CAPTURE) ? 3 : 5; }
// b2405 CNF bit 1 (caller read the flag): safe by state at spawn exit: the visible (not recalling) foes' two-turn damage on me, spells
// included (combat::burst::foe_two_turn_damage, as combat_geometry's danger sum; RC C1339), under HP + shield.
static __attribute__((noinline)) bool cnf_safe()
{
	float dmg = 0.0f;
	for (const auto& e : W.enemies)
	{
		if ((e.state & ST_RECALL) != 0)
			continue;
		const int d = cheb(e.pos, W.me.pos);
		dmg += combat::burst::foe_two_turn_damage(e, d, combat::burst::lethal_burst_hit(e, d, 0, nullptr));
	}
	return dmg < W.me.hp + W.me.shield;
}
// b2405 CNF bit 1 (caller read the flag): a roster carry at spawn exit, free to walk and safe by state (the 50% gate's replacement).
static __attribute__((noinline)) bool cnf_exit()
{
	return cltf_kind(P.my_slot) != 0 && W.alive && !W.me.channeling() && !T.capturing && !engaged_now() && home_dist() <= CNF_TAB[2] && cnf_safe();
}
// b2405 CNF bit 1: mate-claimed group g at path d qualifies: live's test (mate within 2, my target not within CLTF_TRAIL: !near), or at spawn
// exit the mate within CNF_MATE of the anchor or nearer to it than I am, with my target absent or >= CNF_GAIN farther, gold or gems on it.
static bool cnf_mate_ok(const GroupI& g, vec2 mate, int d, bool near)
{
	const int md = cheb(mate, g.anchor);
	if (!near && md <= 2)
		return true;
	const int td = (T.target >= 0 && travel[static_cast<std::size_t>(T.target)] != UNREACH) ? static_cast<int>(travel[static_cast<std::size_t>(T.target)]) : BIG;
	return (T.target < 0 || td >= d + CNF_TAB[4]) && (g.gold > 0 || g.gems > 0) && (md <= CNF_TAB[3] || md < cheb(W.me.pos, g.anchor));
}
// b2409 CNF bit 2 (Deep spec_cnf_1113; caller read the flag): a roster carry, free and safe by state (cnf_safe), anywhere on the map.
static __attribute__((noinline)) bool cnf_any_ok()
{
	return cltf_kind(P.my_slot) != 0 && W.alive && !W.me.channeling() && !T.capturing && !engaged_now() && !(CNF_ON(8) && W.me.type != cambc::champion_type::vesper_vale) && cnf_safe(); // b2405 bit 8: Vesper only
}
// b2405 CNF bit 16 (caller read the flag): group gi is worth >= CNF_VAL_X100 % of my current target (no target: yes).
static bool cnf_val_ok(int gi)
{
	if (T.target < 0 || T.target >= M.ng)
		return true;
	const float vt = group_value(M.groups[static_cast<std::size_t>(T.target)], T.target, my_slot());
	return group_value(M.groups[static_cast<std::size_t>(gi)], gi, my_slot()) * 100.0f >= vt * static_cast<float>(CNF_TAB[6]);
}
// b2409 CNF bit 2: a live walk non-siege gold/gem group whose carry I am, claimed (shared claim channel, comms::cgroup) by a non-carry
// mate, within CNF_EXIT of me, with my own target (if any) >= CNF_GAIN farther by walk; the nearest such. -1: none.
static __attribute__((noinline)) int cnf_any_pick()
{
	const int td = (T.target >= 0 && travel[static_cast<std::size_t>(T.target)] != UNREACH) ? static_cast<int>(travel[static_cast<std::size_t>(T.target)]) : BIG;
	int best = -1, bd = BIG;
	for (int s = 0; s < P.n && s < static_cast<int>(comms::CLAIM_SLOTS); ++s)
	{
		if (s == P.my_slot)
			continue;
		const int gi = comms::cgroup(s);
		if (gi < 0 || gi >= M.ng)
			continue;
		const auto& g = M.groups[static_cast<std::size_t>(gi)];
		const auto& m = mem[static_cast<std::size_t>(gi)];
		const int d = travel[static_cast<std::size_t>(gi)];
		if (m.status != GS_ALIVE || d == UNREACH || d >= bd || cheb(W.me.pos, g.anchor) > CNF_TAB[2] || (T.target >= 0 && td < d + CNF_TAB[4]) || T.target == gi)
			continue;
		if ((g.gold <= 0 && g.gems <= 0) || g.access != ACC_WALK || siege_group(g))
			continue;
		if (cltf_level(s, g) != 0 || cltf_carry_for(g) != P.my_slot || !cltf_quiet(g.anchor))
			continue; // the claimer is no carry here; the group is mine
		if (CNF_ON(16) && !cnf_val_ok(gi))
			continue; // b2405 CNF bit 16: not worth enough against my target
		best = gi;
		bd = d;
	}
	if (CNF_ON(4)) // b2405 CNF bit 4 WIDE: a seen non-carry mate within CNF_WIDE of the group, claimed or not
		for (const auto& al : W.allies)
		{
			if (al.slot < 0 || al.slot >= P.n || al.channeling())
				continue;
			for (int gi = 0; gi < M.ng; ++gi)
			{
				const auto& g = M.groups[static_cast<std::size_t>(gi)];
				if (cheb(al.pos, g.anchor) > CNF_TAB[5] || cheb(W.me.pos, g.anchor) > CNF_TAB[2] || T.target == gi)
					continue;
				const auto& m = mem[static_cast<std::size_t>(gi)];
				const int d = travel[static_cast<std::size_t>(gi)];
				if (m.status != GS_ALIVE || d == UNREACH || d >= bd || (T.target >= 0 && td < d + CNF_TAB[4]))
					continue;
				if ((g.gold <= 0 && g.gems <= 0) || g.access != ACC_WALK || siege_group(g))
					continue;
				if (cltf_level(al.slot, g) != 0 || cltf_carry_for(g) != P.my_slot || !cltf_quiet(g.anchor))
					continue;
				if (CNF_ON(16) && !cnf_val_ok(gi))
					continue;
				best = gi;
				bd = d;
			}
		}
	return best;
}
static __attribute__((noinline)) int cltf_carry_pick()
{
	const bool cnf = CNF_ON(1) && cnf_exit(); // b2405 CNF bit 1
	const bool cnf_low = CNF_ON(1) && cnf && W.me.frac() < 0.5f; // CNF: below half HP only the spawn-exit take (state-safe)
	if (!(CNF_ON(1) && cnf) && (cltf_kind(P.my_slot) == 0 || !W.alive || W.me.channeling() || W.me.frac() < 0.5f || T.capturing || engaged_now()))
		return -1; // RC C883b 4: not while engaged
	int best = -1, bd = BIG;
	if (!(CNF_ON(1) && cnf_low)) // CNF: live's bit 2 runs only where live's guard passed
	for (int gi = 0; gi < M.ng; ++gi)
	{
		const auto& g = M.groups[static_cast<std::size_t>(gi)];
		const auto& m = mem[static_cast<std::size_t>(gi)];
		const int d = travel[static_cast<std::size_t>(gi)];
		if (m.status != GS_CLEARED || d == UNREACH || d > CLTF_TAB[2] || d >= bd || (g.gold <= 0 && g.gems <= 0) || m.fail_until > now())
			continue;
		if (cltf_carry_for(g) != P.my_slot || !cltf_quiet(g.anchor))
			continue;
		cambc::detail::camp_group_capture_state cs{};
		if (cambc::detail::sdk_camp_group_capture_state(g.handle, &cs) == 0 && cs.state == 1)
			continue; // a capture runs there: the hand-over / VTK paths own it
		best = gi;
		bd = d;
	}
	if (best >= 0)
	{
		const auto& g = M.groups[static_cast<std::size_t>(best)];
		cltf_rate = group_value(g, best, my_slot()) / static_cast<float>(bd + cltf_pay() + 1); // RC C883b 5
		return best;
	}
	if (CNF_ON(2) && cnf_any_ok()) // b2409 CNF bit 2: at any pick, a near mate-claimed live group
	{
		const int c2 = cnf_any_pick();
		if (c2 >= 0)
		{
			const auto& g = M.groups[static_cast<std::size_t>(c2)];
			cltf_rate = group_value(g, c2, my_slot()) / static_cast<float>(travel[static_cast<std::size_t>(c2)] + cltf_pay() + 1);
			return c2;
		}
	}
	const bool cnf_near = CNF_ON(1) && (cnf_low || (T.target >= 0 && travel[static_cast<std::size_t>(T.target)] != UNREACH && travel[static_cast<std::size_t>(T.target)] <= CLTF_TAB[4])); // CNF: live's early-out state
	if (!(CNF_ON(1) && cnf) && T.target >= 0 && travel[static_cast<std::size_t>(T.target)] != UNREACH && travel[static_cast<std::size_t>(T.target)] <= CLTF_TAB[4])
		return -1;
	for (const auto& al : W.allies)
	{
		if (al.slot < 0 || al.slot >= static_cast<int>(comms::CLAIM_SLOTS))
			continue;
		const int gi = comms::cgroup(al.slot);
		if (gi < 0 || gi >= M.ng)
			continue;
		const auto& g = M.groups[static_cast<std::size_t>(gi)];
		const auto& m = mem[static_cast<std::size_t>(gi)];
		const int d = travel[static_cast<std::size_t>(gi)];
		if (m.status != GS_ALIVE || d == UNREACH || d > CLTF_TAB[4] || d >= bd || ((CNF_ON(1) && cnf) ? !cnf_mate_ok(g, al.pos, d, cnf_near) : cheb(al.pos, g.anchor) > 2) || g.access != ACC_WALK || siege_group(g))
			continue;
		if (cltf_level(al.slot, g) != 0 || cltf_carry_for(g) != P.my_slot || !cltf_quiet(g.anchor))
			continue; // the clearer is no carry here; the group is mine
		bool other = false;
		for (int s = 0; s < P.n && s < 8 && !other; ++s)
			other = s != P.my_slot && cltf_level(s, g) != 0 && comms::cgroup(s) == gi;
		if (other)
			continue;
		best = gi;
		bd = d;
	}
	if (best >= 0)
	{
		const auto& g = M.groups[static_cast<std::size_t>(best)];
		cltf_rate = group_value(g, best, my_slot()) / static_cast<float>(bd + cltf_pay() + 1); // RC C883b 5 (her clear share comes on top)
	}
	return best;
}
// b2383 PTY bit 1 (callers read the flag; spec_pty_1113 S1, Shared Mem ESC ruling). The lead carry SAYS the party in the ESC field:
// 0 closed, 1 open (no escort), 2-5 one unit, 6-11 two units (pairs lexicographic), 12-15 closed. Units: bodies other than the lead,
// ascending slot, Cassi + Issac one unit, at most 4.
static comms::Spare pty_f;
static int pty_g = -1; // the escort pick's group (pty_escort_pick)
void pty_alloc_i() { pty_f = comms::spare_alloc(4); }
static int pty_lead_slot()
{
	static int pty_ls_n = -1, pty_ls_v = -1; // the roster is fixed once P.n is known: computed once (fuel cap)
	if (pty_ls_n == P.n)
		return pty_ls_v;
	int best = -1, bk = 99;
	for (int s = 0; s < P.n && s < 8; ++s)
	{
		const auto t = P.type[static_cast<std::size_t>(s)];
		const int k = t == cambc::champion_type::prism ? 1 : t == cambc::champion_type::vesper_vale ? 2 : t == cambc::champion_type::marcella ? 3 : 99;
		if (k < bk)
			bk = k, best = s;
	}
	pty_ls_n = P.n;
	pty_ls_v = best;
	return best;
}
static bool pty_ci(int s)
{
	const auto t = P.type[static_cast<std::size_t>(s)];
	return t == cambc::champion_type::cassi || t == cambc::champion_type::issac;
}
// unit u's slots (1 or 2); returns the count
static int pty_unit_slots(int lead, int u, int* out)
{
	int k = -1, ci_u = -1, n = 0;
	for (int s = 0; s < P.n && s < 8; ++s)
	{
		if (s == lead)
			continue;
		int us;
		if (pty_ci(s) && ci_u >= 0)
			us = ci_u;
		else
		{
			us = ++k;
			if (pty_ci(s))
				ci_u = us;
		}
		if (us == u && n < 2)
			out[n++] = s;
	}
	return n;
}
static int pty_code(int na, int a, int b)
{
	if (na == 1)
		return 2 + a;
	if (na == 2)
	{
		static const int pi[4][4] = { { -1, 6, 7, 8 }, { 6, -1, 9, 10 }, { 7, 9, -1, 11 }, { 8, 10, 11, -1 } };
		return pi[a & 3][b & 3];
	}
	return 0;
}
// the units a code names (-1 none)
static void pty_decode(int c, int* a, int* b)
{
	*a = -1;
	*b = -1;
	if (c >= 2 && c <= 5)
		*a = c - 2;
	else if (c >= 6 && c <= 11)
	{
		static const int pa[6][2] = { { 0, 1 }, { 0, 2 }, { 0, 3 }, { 1, 2 }, { 1, 3 }, { 2, 3 } };
		*a = pa[c - 6][0];
		*b = pa[c - 6][1];
	}
}
static float pty_walk_from(int s, vec2 p, int gi)
{
	const auto& g = M.groups[static_cast<std::size_t>(gi)];
	if (s == my_slot() && travel.size() == static_cast<std::size_t>(M.ng) && travel[static_cast<std::size_t>(gi)] != UNREACH)
		return static_cast<float>(travel[static_cast<std::size_t>(gi)]);
	return static_cast<float>(cheb(p, g.anchor) * 5 / 4 + 2);
}
// value share / (slowest walk + clear at this crew + 5), plus the members' camp-damage saving L(1) - L(n)/n (n > 1) as heal-trip rounds
static float pty_rate(int gi, const int* sl, const vec2* ps, int n, ClearEst* eo = nullptr) // eo: b2383 MGY5 fuel cut, the clear estimate for the HP check
{
	if (gi < 0 || gi >= M.ng || n <= 0)
		return -1.0f;
	const auto& g = M.groups[static_cast<std::size_t>(gi)];
	const auto& m = mem[static_cast<std::size_t>(gi)];
	if (m.status == GS_RESPAWN || g.access != ACC_WALK)
		return -1.0f;
	Crew c;
	for (int i = 0; i < TM.n; ++i)
	{
		const int s = TM.by_tank[static_cast<std::size_t>(i)];
		for (int j = 0; j < n; ++j)
			if (sl[j] == s)
				c.add(ECX_TM(static_cast<std::size_t>(s)));
	}
	if (c.n != n)
		return -1.0f;
	const ClearEst e = estimate_cx(1, g, m, c);
	if (eo)
		*eo = e;
	if (!e.feasible)
		return -1.0f;
	float walk = 0.0f, v = 0.0f;
	for (int j = 0; j < n; ++j)
	{
		walk = std::max(walk, pty_walk_from(sl[j], ps[j], gi));
		v += std::max(0.0f, group_value(g, gi, sl[j])) / static_cast<float>(n);
	}
	if (v <= 0.0f)
		return -1.0f;
	const float tt = std::max(1.0f, walk + e.t + 5.0f);
	float r = v / tt;
	if (n > 1)
	{
		static const int K[2][3] = { { 88, 78, 69 }, { 221, 193, 150 } };
		const int h = g.n_elk + g.n_golem + g.n_mono > 0 ? 1 : 0;
		const float ghp = (m.status == GS_ALIVE && m.hp_left >= 0) ? m.hp_left : g.hp;
		const float lk = ghp * static_cast<float>(PTY_TAB[6]) / 100000.0f;
		const float dhp = static_cast<float>(K[h][0]) * lk - static_cast<float>(K[h][std::min(n, 3) - 1]) * lk / static_cast<float>(n);
		const std::uint16_t dh = dfget(M.f_home, g.anchor);
		const float trip = (5.0f + (dh == UNREACH ? 30.0f : static_cast<float>(dh))) * static_cast<float>(PTY_TAB[7]) / 100.0f;
		float saved = 0.0f;
		for (int j = 0; j < n; ++j)
		{
			const Body* bd = sl[j] == my_slot() ? &W.me : W.ally_by_slot(sl[j]);
			const float mhp = bd ? bd->maxhp : kit_of(P.type[static_cast<std::size_t>(sl[j])]).hp;
			saved += std::max(0.0f, dhp) / std::max(1.0f, 0.7f * mhp) * trip;
		}
		r += saved * (r / static_cast<float>(n)) / tt;
	}
	return r;
}
// S1b: the crew of these slots alone clears gi in one trip (estimate)
static bool pty_solo_ok(int gi, const int* sl, int n)
{
	if (gi < 0 || gi >= M.ng)
		return false;
	Crew c;
	for (int i = 0; i < TM.n; ++i)
	{
		const int s = TM.by_tank[static_cast<std::size_t>(i)];
		for (int j = 0; j < n; ++j)
			if (sl[j] == s)
				c.add(ECX_TM(static_cast<std::size_t>(s)));
	}
	return c.n == n && estimate_cx(1, M.groups[static_cast<std::size_t>(gi)], mem[static_cast<std::size_t>(gi)], c).feasible;
}
static bool pty_foe_near_r(vec2 p, int r)
{
	for (const auto& e : W.enemies)
		if (cheb(e.pos, p) <= r)
			return true;
	return false;
}
static bool pty_foe_near(vec2 p)
{
	for (const auto& e : W.enemies)
		if (cheb(e.pos, p) <= 8)
			return true;
	return false;
}
// a unit's position for the walk (in sight: its tile; else the group its digit names), and availability. false = not available.
static bool pty_unit_pos(const int* us, int nu, vec2* p)
{
	bool have = false;
	for (int i = 0; i < nu; ++i)
	{
		const int s = us[i];
		if (!siege_ally_alive(s) || cltf_kind(s) != 0)
			return false;
		if (const Body* b = W.ally_by_slot(s))
		{
			if (b->frac() < 0.5f || b->channeling())
				return false;
			if (comms::cgroup(s) < 0 && pty_foe_near(b->pos))
				return false;
			if (!have)
				*p = b->pos, have = true;
			continue;
		}
		const int cg = comms::cgroup(s);
		if (cg < 0 || cg >= M.ng)
			return false;
		if (!have)
			*p = M.groups[static_cast<std::size_t>(cg)].anchor, have = true;
	}
	return have;
}
// the party (lead + named units) rate at gi v the solo sum (lead alone at gi, each unit at its own digit's group)
static void pty_eval(int lead, int gi, const int* units, int nun, float* pr, float* ss)
{
	int sl[5];
	vec2 ps[5];
	int n = 0;
	sl[n] = lead;
	ps[n++] = W.me.pos;
	*ss = std::max(0.0f, pty_rate(gi, sl, ps, 1));
	for (int i = 0; i < nun; ++i)
	{
		int us[2];
		const int nu = pty_unit_slots(lead, units[i], us);
		vec2 p{ -1, -1 };
		if (nu <= 0 || !pty_unit_pos(us, nu, &p))
		{
			*pr = -1.0f;
			return;
		}
		vec2 up[2] = { p, p };
		const int og = comms::cgroup(us[0]);
		*ss += std::max(0.0f, pty_rate(og, us, up, nu));
		for (int j = 0; j < nu && n < 5; ++j)
		{
			sl[n] = us[j];
			ps[n++] = p;
		}
	}
	*pr = pty_rate(gi, sl, ps, n);
}
void pty_fc_move()
{
}
static int pty_code_now = 0, pty_tgt = -1, pty_below = 0, pty_ban_g = -1, pty_ban_until = -1000, pty_turn_r = -1;
static int pty_units[2] = { -1, -1 }, pty_nun = 0;
static void pty_put(int c)
{
	if (c != pty_code_now)
		comms::spare_put(pty_f, static_cast<std::uint32_t>(c));
	pty_code_now = c;
	if (c <= 1)
		pty_nun = 0, pty_tgt = -1, pty_below = 0;
}
// b2383 MGY bit 4 SYNC ENGAGE (callers read the flag). The party's bodies (slots), the gather test, and the pre-form HP check.
static int mgy_slots(int lead, const int* units, int nun, int* sl)
{
	int n = 0;
	sl[n++] = lead;
	for (int i = 0; i < nun; ++i)
	{
		int us[2];
		const int nu = pty_unit_slots(lead, units[i], us);
		for (int j = 0; j < nu && n < 5; ++j)
			sl[n++] = us[j];
	}
	return n;
}
// every member's body seen within MGY_SR (3) of the lead (the lead's own view, or an escort's: the lead seen and each seen member near her)
static bool mgy_gathered(int lead, const int* units, int nun)
{
	int sl[5];
	const int n = mgy_slots(lead, units, nun, sl);
	const Body* lb = lead == my_slot() ? &W.me : W.ally_by_slot(lead);
	if (!lb)
		return false;
	for (int i = 1; i < n; ++i)
	{
		const Body* b = sl[i] == my_slot() ? &W.me : W.ally_by_slot(sl[i]);
		if (!b || cheb(b->pos, lb->pos) > MGY_TAB[7])
			return false;
	}
	return true;
}
// b2383 MGY5 fuel cut: mgy_hp_ok on the party rate's own estimate (the same crew: the lead + the units' slots, mgy_slots' order)
static bool mgy_hp_ok_e(const ClearEst& e, const int* sl, int n)
{
	if (!e.feasible)
		return false;
	const float share = e.dmg / static_cast<float>(n);
	for (int j = 0; j < n; ++j)
	{
		const Body* b = sl[j] == my_slot() ? &W.me : W.ally_by_slot(sl[j]);
		if (b && b->hp - share < 0.5f * b->maxhp)
			return false; // unseen members are taken at full HP
	}
	return true;
}
// MGY bit 8 NAMING (caller read the flag): every body of the unit is not busy (seen: not channelling; not engaged on its claim; not
// fighting its claimed group in the team view), placed by my sight or by its digit, and within MGY_NW (Chebyshev) of the group's anchor.
static bool mgy_name_ok(const int* us, int nu, vec2 an)
{
	for (int j = 0; j < nu; ++j)
	{
		const int s = us[j];
		if (s < 0 || s >= 8 || comms::cengaged(s) || TM.busy[static_cast<std::size_t>(s)])
			return false;
		vec2 p{ -1, -1 };
		if (const Body* b = W.ally_by_slot(s))
		{
			if (b->channeling())
				return false;
			p = b->pos;
		}
		else
		{
			const int cg = comms::cgroup(s);
			if (cg < 0 || cg >= M.ng)
				return false;
			p = M.groups[static_cast<std::size_t>(cg)].anchor;
		}
		if (cheb(p, an) > MGY_TAB[9])
			return false;
	}
	return true;
}
static int mgy_form_r = -1000;
void mgy_fc_sync()
{
}
// b2383 MGY (caller read MGY_ON(1)): the mid gem party. True = handled this turn (the S1 path does not run).
static bool mgp_on = false;
static long mgy_f0 = 0; // the form scan's starting fuel (diag reads it)
void mgp_fc_form()
{
}
static bool pty_mgp_turn(int lead)
{
	const bool recall = (W.me.state & (ST_RECALL | ST_TRIBUTE)) != 0;
	const bool bankw = pcf_calm >= now() - 1;
	if (mgp_on)
	{
		bool brk = recall || bankw || pty_foe_near(W.me.pos) || pty_tgt < 0 || pty_tgt >= M.ng || T.target != pty_tgt || mem[static_cast<std::size_t>(pty_tgt)].status == GS_RESPAWN;
		for (int i = 0; i < pty_nun && !brk; ++i)
		{
			int us[2];
			const int nu = pty_unit_slots(lead, pty_units[i], us);
			for (int j = 0; j < nu; ++j)
			{
				const Body* b = W.ally_by_slot(us[j]);
				brk = brk || !siege_ally_alive(us[j]) || (b && b->frac() < 0.5f);
			}
		}
		if (!brk && pty_tgt >= 0 && pty_tgt < M.ng && mem[static_cast<std::size_t>(pty_tgt)].status == GS_ALIVE && !mgy_gathered(lead, pty_units, pty_nun) && now() - mgy_form_r >= MGY_TAB[8])
		{
			mgy_fc_sync(); // bit 4: not gathered in time: dissolve, no solo start
			pty_ban_g = pty_tgt;
			pty_ban_until = now() + PTY_TAB[5];
			drop_target(0);
			brk = true;
		}
		if (!brk && now() % std::max(1, static_cast<int>(PTY_TAB[2])) == 0 && fuel() >= static_cast<long>(PTY_TAB[8]) && mem[static_cast<std::size_t>(pty_tgt)].status == GS_ALIVE)
		{
			build_team(false);
			float pr = -1.0f, ss = 0.0f;
			pty_eval(lead, pty_tgt, pty_units, pty_nun, &pr, &ss);
			if (pr < ss * (1.0f - static_cast<float>(PTY_TAB[4]) / 100.0f))
			{
				if (++pty_below >= 2)
				{
					pty_ban_g = pty_tgt;
					pty_ban_until = now() + PTY_TAB[5];
					brk = true;
				}
			}
			else
				pty_below = 0;
		}
		if (brk)
		{
			mgp_on = false;
			pty_put(0);
		}
		return true;
	}
	if (!opened || W.tributed_us >= FIN_US || W.tributed_them >= FIN_THEM || GAME_END - now() <= FIN_TIME) // RC C1145: state, not rounds: after the opening choice, before finish mode (finish_mode(0)'s test)
		return false;
	if (now() % std::max(1, static_cast<int>(PTY_TAB[2])) != 0 || recall || bankw || pty_foe_near(W.me.pos) || T.capturing || engaged_now() || W.me.frac() < 0.5f || fuel() < static_cast<long>(MGY_TAB[4]))
		return true;
	mgy_f0 = fuel();
	const bool tfresh = travel_round == now() && travel_from == W.me.pos && travel.size() == static_cast<std::size_t>(M.ng);
	auto my_walk = [&](int gi) -> int
	{
		return tfresh ? static_cast<int>(travel[static_cast<std::size_t>(gi)]) : cheb(W.me.pos, M.groups[static_cast<std::size_t>(gi)].anchor) * 5 / 4 + 2;
	};
	Claims cl{};
	bool cl_ok = false; // MGY5 fuel cut (RC X889): claims_for_me only after a group passes the cheap rejects
	int cg[6], cw[6], ncg = 0;
	for (int gi = 0; gi < M.ng; ++gi)
	{
		const auto& g = M.groups[static_cast<std::size_t>(gi)];
		const auto& m = mem[static_cast<std::size_t>(gi)];
		if (g.gems < MGY_TAB[2] || g.contest < 0.35f || g.contest > 0.65f || m.status != GS_ALIVE || g.access != ACC_WALK || (gi == pty_ban_g && now() < pty_ban_until))
			continue;
		const int w = my_walk(gi);
		if (w > MGY_TAB[3])
			continue;
		if (!cl_ok)
			cl = claims_for_me(), cl_ok = true;
		if (claimants(gi, my_slot(), cl) > 0) // RC X874: the cheap rejects first, claimants after the walk
			continue;
		if (intel::count_near(g.anchor, MGY_TAB[5], MGY_TAB[6]) > 0 || pty_foe_near_r(g.anchor, MGY_TAB[5])) // MGY2: no foe seen near it lately
			continue;
		int pos = 5;
		if (ncg < 6)
			pos = ncg++;
		else if (w >= cw[5])
			continue; // the 6 nearest kept (fuel cap)
		cg[pos] = gi;
		cw[pos] = w;
		for (int i = pos; i > 0 && cw[i] < cw[i - 1]; --i)
			std::swap(cw[i], cw[i - 1]), std::swap(cg[i], cg[i - 1]);
	}
	if (ncg == 0)
		return true;
	build_team(false);
	float my_now = 0.0f;
	bool my_now_ok = false; // MGY5: her current pick's solo rate, on the first party evaluation
	float ur[4] = { 0, 0, 0, 0 }; // MGY5: each unit's solo rate at its digit's group and its walk position, once per scan
	vec2 upo[4];
	bool ur_ok[4] = { false, false, false, false };
	int best = -1, bk = 0, bu[2] = { -1, -1 };
	float bm = 0.0f, bpr = 0.0f;
	for (int i = 0; i < ncg; ++i)
	{
		const int gi = cg[i];
		const int me1[1] = { lead };
		if (pty_solo_ok(gi, me1, 1))
			continue; // she clears it alone: not the no_crew case
		const vec2 an = M.groups[static_cast<std::size_t>(gi)].anchor;
		int cu[4], cd[4], nc = 0;
		for (int u = 0; u < 4; ++u)
		{
			int us[2];
			const int nu = pty_unit_slots(lead, u, us);
			vec2 p{ -1, -1 };
			if (nu <= 0 || !pty_unit_pos(us, nu, &p))
				continue;
			const int w = cheb(p, an) * 5 / 4 + 2;
			if (w > MGY_TAB[3])
				continue;
			if (!mgy_name_ok(us, nu, an)) // MGY4 NAMING: not busy, seen (or digit-placed and quiet), within MGY_NW of the group
				continue;
			upo[u] = p;
			cu[nc] = u;
			cd[nc] = w;
			++nc;
		}
		for (int a = 1; a < nc; ++a)
			for (int z = a; z > 0 && cd[z] < cd[z - 1]; --z)
				std::swap(cd[z], cd[z - 1]), std::swap(cu[z], cu[z - 1]);
		for (int k = 1; k <= std::min(2, nc); ++k)
		{
			// MGY5 fuel cut: pty_eval(lead, gi, cu, k) from the scan's caches (the lead's solo term is 0: pty_solo_ok was false on the same estimate)
			int sl[5];
			vec2 ps[5];
			int n = 0;
			sl[n] = lead;
			ps[n++] = W.me.pos;
			float ss = 0.0f;
			for (int i2 = 0; i2 < k; ++i2)
			{
				int us[2];
				const int nu = pty_unit_slots(lead, cu[i2], us);
				if (!ur_ok[cu[i2]])
				{
					const vec2 up[2] = { upo[cu[i2]], upo[cu[i2]] };
					ur[cu[i2]] = std::max(0.0f, pty_rate(comms::cgroup(us[0]), us, up, nu));
					ur_ok[cu[i2]] = true;
				}
				ss += ur[cu[i2]];
				for (int j = 0; j < nu && n < 5; ++j)
				{
					sl[n] = us[j];
					ps[n++] = upo[cu[i2]];
				}
			}
			ClearEst pe;
			const float pr = pty_rate(gi, sl, ps, n, &pe);
			if (pr <= 0.0f)
				continue;
			if (!my_now_ok)
			{
				my_now_ok = true;
				if (T.target >= 0 && T.target < M.ng)
				{
					const int me1[1] = { lead };
					const vec2 mp[1] = { W.me.pos };
					my_now = std::max(0.0f, pty_rate(T.target, me1, mp, 1));
				}
			}
			ss += my_now;
			if (pr >= ss * static_cast<float>(PTY_TAB[3]) / 100.0f && pr - ss > bm && !(!mgy_hp_ok_e(pe, sl, n))) // bit 4: no member predicted under 50% HP (only for a pair that would lead)
			{
				bm = pr - ss;
				best = gi;
				bk = k;
				bpr = pr;
				bu[0] = k > 1 ? std::min(cu[0], cu[1]) : cu[0];
				bu[1] = k > 1 ? std::max(cu[0], cu[1]) : -1;
			}
		}
	}
	if (best < 0)
		return true;
	mgp_fc_form();
	mgp_on = true;
	pty_units[0] = bu[0];
	pty_units[1] = bu[1];
	pty_put(pty_code(bk, bu[0], bu[1]));
	pty_nun = bk;
	pty_tgt = best;
	pty_below = 0;
	mgy_form_r = now();
	if (T.target != best)
		set_target(best, bpr / static_cast<float>(bk + 1), bk + 1);
	return true;
}
static void pty_lead_turn(int lead)
{
	if (!W.alive)
	{
		mgp_on = false;
		pty_put(0); // her first dead turn
		return;
	}
	if (pty_mgp_turn(lead)) // b2383 MGY: the mid gem party first
		return;
	pty_put(0);
	return;
}
// the escort side: the group the lead's party names me for (-1 none); the one accessor of the field
static int pty_named_target_c(int lead);
// fuel cap: one evaluation a round (the field, the lead's digit and my state are fixed within my turn)
static int pty_named_target(int lead)
{
	static int pty_nt_r = -1, pty_nt_lead = -2, pty_nt_v = -1;
	if (pty_nt_r == W.round && pty_nt_lead == lead)
		return pty_nt_v;
	pty_nt_r = W.round;
	pty_nt_lead = lead;
	pty_nt_v = pty_named_target_c(lead);
	return pty_nt_v;
}
static int pty_named_target_c(int lead)
{
	if (!pty_f.ok() || lead < 0 || lead == my_slot())
		return -1;
	const int c = static_cast<int>(comms::spare_get(pty_f)); // the code first: most turns name nobody
	int a = -1, b = -1;
	pty_decode(c, &a, &b);
	if (a < 0 || !siege_ally_alive(lead))
		return -1;
	bool me = false;
	for (int u : { a, b })
	{
		if (u < 0)
			continue;
		int us[2];
		const int nu = pty_unit_slots(lead, u, us);
		for (int j = 0; j < nu; ++j)
			me = me || us[j] == my_slot();
	}
	if (!me)
		return -1;
	const int gi = comms::cgroup(lead);
	if (gi < 0 || gi >= M.ng || mem[static_cast<std::size_t>(gi)].status == GS_RESPAWN || M.groups[static_cast<std::size_t>(gi)].access != ACC_WALK)
		return -1;
	if (!W.alive || W.me.frac() < 0.5f || W.me.channeling() || pty_foe_near(W.me.pos))
		return -1;
	return gi;
}
bool pty_escort_pick(float* out_rate, int* out_crew)
{
	if (mgp_on && pty_tgt >= 0 && pty_lead_slot() == my_slot()) // MGY: the lead keeps her party's group
	{
		pty_g = pty_tgt;
		*out_rate = std::max(T.rate, 0.0f);
		*out_crew = 1 + pty_nun;
		return true;
	}
	const int gi = pty_named_target(pty_lead_slot());
	if (gi < 0 || T.capturing || engaged_now())
		return false;
	pty_g = gi;
	*out_rate = std::max(T.rate, 0.0f);
	*out_crew = 1;
	return true;
}
// RC C1027 (a)+(b): every other body of the said party (the lead, every named unit's bodies) in sight within PTY_NEAR of me, and the
// crew of me + them clears gi by estimate_cx(4) (the live start test on the bodies actually present).
bool mgy_sync_hold_i(int gi)
{
	if (!pty_f.ok() || gi < 0 || gi >= M.ng || mem[static_cast<std::size_t>(gi)].status != GS_ALIVE)
		return false;
	const int lead = pty_lead_slot();
	if (lead == my_slot())
		return mgp_on && pty_tgt == gi && !mgy_gathered(lead, pty_units, pty_nun);
	if (pty_named_target(lead) != gi)
		return false;
	int ua = -1, ub = -1;
	pty_decode(static_cast<int>(comms::spare_get(pty_f)), &ua, &ub);
	if (comms::cengaged(lead) && comms::cgroup(lead) == gi) // RC C1145d: the lead started on gi (her shared claim's engaged bit): the escorts go too
		return false;
	return true; // RC C1145e: escorts hold until the lead's shared signal (the party's end or a target change releases them via the code)
}
void pty_turn_i()
{
	if (pty_turn_r == W.round || !pty_f.ok())
		return;
	pty_turn_r = W.round;
	const int lead = pty_lead_slot();
	if (lead < 0)
		return;
	if (lead == my_slot())
	{
		pty_lead_turn(lead);
		return;
	}
	const int gi = pty_named_target(lead);
	if (gi < 0 || gi == T.target || T.capturing || engaged_now())
		return;
	pty_fc_move();
	set_target(gi, std::max(T.rate, 0.0f), 1);
}
} // namespace (b2383 PTY: the two entry points econ.h names)
void pty_alloc() { pty_alloc_i(); }
void pty_turn() { pty_turn_i(); }
bool mgy_sync_hold(int gi) { return mgy_sync_hold_i(gi); }
// MGY bit 8 MEMBER KEEP (caller read the flag): named in the lead's party code for a living / cleared group that is my target: the retarget
// switch keeps it (exits: the party's breaks drop the naming; own HP < 50%, a foe within 8, channelling, the group respawning: pty_named_target).
bool mgy_member_keep()
{
	if (!pty_f.ok() || T.target < 0)
		return false;
	const int lead = pty_lead_slot();
	if (lead < 0 || lead == my_slot())
		return false;
	const int gi = pty_named_target(lead);
	return gi >= 0 && gi == T.target && mem[static_cast<std::size_t>(gi)].fail_until <= now() && reachable_target(gi); // RC C1145g: never keep what TCS would drop
}
namespace {
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
	if (pty_escort_pick(out_rate, out_crew)) // b2383 PTY: a named escort takes the lead's target
		return pty_g;
	if (const int cltf_g = cltf_carry_pick(); cltf_g >= 0) // b2273 CLTF bits 2/4: the carry takes a cleared group of hers / trails a clearing crew
	{
		*out_rate = cltf_rate;
		*out_crew = 1;
		return cltf_g;
	}
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
			if (al.slot < 0 || al.slot >= static_cast<int>(comms::CLAIM_SLOTS) || al.channeling() || al.frac() < 0.3f)
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
				if (s2 != my_slot() && s2 != lead->slot && TM.claim[static_cast<std::size_t>(s2)] == T.target)
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
		sq_stick_pick = true;
		return stick_g;
	}
	if (b >= 0 && now() <= VJN_TAB[2] && vesper_layer::me() && my_slot() >= 0 && fuel() > 45000 && W.me.frac() >= COVER_IDLE_HP && !T.engaged && !T.capturing)
	{
		// v699 VJN bit 1 (b): she joins a mates' fight when the gain beats her own rate (bit 2: her solo rate)
		float own_r = *out_rate;
		float jg = 0;
		int jc = 1;
		const int jgi = vjn_join(b, own_r, cl, &jg, &jc);
		if (jgi >= 0)
		{
			b = jgi;
			*out_rate = jg;
			*out_crew = jc;
		}
	}
	if (b < 0 && my_slot() >= 0 && fuel() > 45000 &&
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
	float jgw_wr = 0.0f; // v683 JGW1: the crew starts clearing at respawn_at
	if (arrive >= 0 && e0.feasible)
	{
		// The crew clears without me until I arrive, then with me: the rest of the work goes at the faster rate.
		const float a = static_cast<float>(arrive);
		if (m.status == GS_RESPAWN)
		{
			jgw_wr = static_cast<float>(std::max(0, m.respawn_at - now()));
			if (a >= jgw_wr + e0.t)
				return -1;
			t1 = a <= jgw_wr ? jgw_wr + e1.t : a + (jgw_wr + e0.t - a) * e1.t / std::max(0.1f, e0.t);
		}
		else
		{
			if (a >= e0.t)
				return -1;
			t1 = a + (e0.t - a) * e1.t / std::max(0.1f, e0.t);
		}
	}
	else if (arrive >= 0)
		t1 = std::max(static_cast<float>(arrive), 0.0f) + e1.t;
	const float base = (arrive >= 0 ? 0.0f : static_cast<float>(trav) + wait) + cap_term(b);
	const float r1 = v / (base + t1);
	// v699 VJN bit 1 (a): without her the crew's holder is paid; with her, her value when she would hold the capture
	bool vjn_first = true;
	const float vjn_c = vjn_crew_value(g, gi, b, cl, v, &vjn_first);
	if (crew_out)
		*crew_out = c1.n;
	return (vjn_first ? v : vjn_c) / (base + t1) - (e0.feasible ? vjn_c / (base + (jgw_wr) + e0.t) : 0.0f);
}
void set_target(int gi, float rate, int crew)
{
	if (gi != T.target) // a new target taken by an idle-recruit rating keeps that branch while held
		ir_tgt = ir_ok_round == now() && std::find(ir_ok.begin(), ir_ok.end(), gi) != ir_ok.end() ? gi : -1;
	if (gi != T.target)
	{
		if (hs3_commit_g != gi && !(hs3_commit_g == M.ng)) // v678 FX7 bit 4: the bank-shortcut commit (hsb_alt() == M.ng) stays
			hs3_commit_g = -1; // v676 DRS bit 16: a new target drops another group's shortcut commit
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
	if (T.target >= 0)
	{
		hrts_last = T.target; // b2387 HRTS bit 1: the reference for the home-trip veto
		hrts_last_r = now();
	}
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
			(sg_big(g) && !(big_group_nearly_dead(gi)))) // big groups are team operations (SG3), except where big_group_nearly_dead holds (OGS bit 8 REM)
			continue;
		if (m.status == GS_RESPAWN && m.respawn_at > now() + static_cast<int>(tr))
			continue;
		if (claimants(gi, my_slot(), cl) > 0)
			continue;
		const float v = group_value(g, gi, my_slot());
		if (v <= best_v)
			continue;
		const ClearEst e = estimate_cx(1, g, m, crew_for_ref(gi, my_slot(), 0, cl));
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
	if (dtr_rsp) // b2056 DTR bit 4 RS2R: no pre-death claim before the re-rate
	{
		if (T.eval_round == -1000)
			return -1;
		dtr_rsp = false;
	}
	if (ring_breaching)
		return ring_claim; // the breacher claims the ring group
	return T.target;
}
} // namespace nova::econ
