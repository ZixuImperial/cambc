// econ_observe.cc: Per-turn memory update and intel.
#include "econ_internal.h"
namespace nova::econ {
namespace {
int them_last = 0;       // enemy tributed gems at the previous turn
int us_last = 0;         // our tributed gems at the previous turn
// v7xx OBF 1 OBX1: each group's member tiles as bitboard words (camp_bits' k/m), at most 2 words (k1 = k0, m1 = 0 for one); k0 = -1: no pretest.
struct ObfGroupBits
{
	int k0 = -1, k1 = -1;
	std::uint64_t m0 = 0, m1 = 0;
};
std::vector<ObfGroupBits> obf_gb;
int obf_gb_nc = -1;
const ObfGroupBits* obf_group_bits(const std::vector<CampBit>& cb)
{
	if (obf_gb.size() != static_cast<std::size_t>(M.ng) || obf_gb_nc != M.nc)
	{
		obf_gb.assign(static_cast<std::size_t>(M.ng), ObfGroupBits{});
		obf_gb_nc = M.nc;
		for (std::size_t gi = 0; gi < static_cast<std::size_t>(M.ng); ++gi)
		{
			int k0 = -1, k1 = -1;
			std::uint64_t m0 = 0, m1 = 0;
			bool fit = true;
			for (int ci : M.groups[gi].members)
			{
				const CampBit& b = cb[static_cast<std::size_t>(ci)];
				if (k0 < 0 || b.k == k0)
					k0 = b.k, m0 |= b.m;
				else if (k1 < 0 || b.k == k1)
					k1 = b.k, m1 |= b.m;
				else
				{
					fit = false;
					break;
				}
			}
			if (fit && k0 >= 0)
				obf_gb[gi] = ObfGroupBits{ k0, k1 < 0 ? k0 : k1, m0, m1 };
		}
	}
	return obf_gb.data();
}
} // namespace
// Read-only views and per-call caches shared by the group scan of observe().
struct ObserveScan
{
	const std::vector<CampBit>& cbit;
	const std::uint64_t* vis_w;
	const std::uint64_t* occ_w;
	const std::int16_t* px_slot; // W's camp slot table, read once
	const std::size_t px_nslot;
	const VisCamp* px_camps;
	const int px_stamp;
	const vec2 me;
	int* px_hst = nullptr; // the hoard-fuel note's three vectors, sized on the first group
	int* px_hal = nullptr;
	int* px_hin = nullptr;
	bool px_box = false; // the foes' box, computed on the first group that sees a camp
	const ObfGroupBits* obf_b = nullptr; // v7xx OBF 1 OBX1: the groups' tile words (set while the bit is on)
	int* obf_s = nullptr; // v7xx OBF 2 OBX2: the seen list (set while the bit is on)
	int px_x0 = 0, px_x1 = -1, px_y0 = 0, px_y1 = -1;
};
static __attribute__((always_inline)) inline void observe_resize_memory()
{
if (gmem_size(mem) != static_cast<std::size_t>(M.ng))
{
	mem.assign(static_cast<std::size_t>(M.ng), GroupMem{});
	fxp_exp_lo = -2147483647 - 1; // full pass next
}
}
static __attribute__((always_inline)) inline void observe_avoid_handoff_region()
{
	if (cr_av_gi >= 0)
	{
		// off Prism's region after a hand-off, until it pays (respawn seen) or the window ends.
		if (cr_av_gi >= M.ng || now() > cr_av_until || mem[static_cast<std::size_t>(cr_av_gi)].status == GS_RESPAWN || !W.alive)
			cr_av_gi = -1;
		else
			for (int ci : M.groups[static_cast<std::size_t>(cr_av_gi)].members)
				if (ci >= 0 && ci < M.nc && M.camps[static_cast<std::size_t>(ci)].pos != W.me.pos)
					mv::avoid_tile(M.camps[static_cast<std::size_t>(ci)].pos);
	}
}
// Any tribute (ours or theirs) on a map whose altars are gated means a gate is open.
static __attribute__((always_inline)) inline void observe_tribute_signals()
{
if (W.tributed_them > them_last || W.tributed_us > us_last)
{
	if (W.tributed_us > us_last)
		ring_signal = now();
	gate_signal = now();
	them_last = W.tributed_them;
	us_last = W.tributed_us;
}
}
// Expiry pass: a respawn that has run out is unknown again (nothing after it reads another group's memory).
static __attribute__((always_inline)) inline void observe_expire_respawns()
{
	{
		const int t_now = now();
		GroupMem* mp = mem.data();
		GroupMem* const mp_end = mp + gmem_size(mem);
		// v864 RXLS1 (RC X770): on maps with OXF_NG+ groups the pass walks only the groups mark_respawn listed (per-group updates are
		// order-free, lo is the same min); a mem reset (fxp_exp_lo = INT_MIN) walks every group once and rebuilds the list.
		const bool oxf2 = M.ng >= OXF_NG;
		oxf_l2 = oxf2;
		if (oxf2 && t_now >= fxp_exp_lo && fxp_exp_lo != -2147483647 - 1 && oxf_rin.size() == gmem_size(mem))
		{
			int lo = 2147483647;
			std::size_t k = 0;
			for (std::size_t i = 0; i < oxf_rl.size(); ++i)
			{
				const int gi = oxf_rl[i];
				GroupMem& gm = mp[gi];
				if (gm.status == GS_RESPAWN && t_now < gm.respawn_at)
				{
					lo = std::min(lo, gm.respawn_at);
					oxf_rl[k++] = gi;
					continue;
				}
				if (gm.status == GS_RESPAWN)
					gm.status = GS_UNKNOWN;
				oxf_rin[static_cast<std::size_t>(gi)] = 0;
			}
			oxf_rl.resize(k);
			fxp_exp_lo = lo;
		}
		else if (t_now >= fxp_exp_lo) // below the bound no GS_RESPAWN group is due (the pass would change nothing)
		{
			if (oxf2)
			{
				oxf_rin.assign(gmem_size(mem), 0);
				oxf_rl.clear();
				for (std::size_t i = 0; i < gmem_size(mem); ++i)
					if (mp[i].status == GS_RESPAWN && t_now < mp[i].respawn_at)
					{
						oxf_rin[i] = 1;
						oxf_rl.push_back(static_cast<int>(i));
					}
			}
			int lo = 2147483647;
#pragma clang loop unroll_count(8)
			for (; mp != mp_end; ++mp)
				if (mp->status == GS_RESPAWN)
				{
					if (t_now >= mp->respawn_at)
						mp->status = GS_UNKNOWN;
					else
						lo = std::min(lo, mp->respawn_at);
				}
			fxp_exp_lo = lo;
		}
	}
}
static __attribute__((always_inline)) inline void observe_reopen_cleared_groups()
{
}
// Counts the group's visible and alive camps and their health and wakefulness.
static __attribute__((always_inline)) inline void observe_count_group(const ObserveScan& sc, const GroupI& g, std::size_t gi, int& vis_n, int& alive_n, float& hp)
{
	if (!(static_cast<std::size_t>(g.nm) >= 6 && of_scan(gi, vis_n, alive_n, hp))) // of_scan answers false below 6 members
	for (int ci : g.members)
	{
		const CampBit& cb = sc.cbit[static_cast<std::size_t>(ci)]; // the same two bit reads as bbget, with word, bit and hp precomputed
		if (!(sc.vis_w[cb.k] & cb.m))
		{
			hp += cb.hp;
			continue;
		}
		++vis_n;
		if (sc.occ_w[cb.k] & cb.m)
		{
			++alive_n;
			const int px_k = static_cast<std::size_t>(ci) < sc.px_nslot ? sc.px_slot[static_cast<std::size_t>(ci)] : -1; // same as visible_camp(ci)
			const VisCamp* vc = px_k >= 0 ? sc.px_camps + px_k : nullptr;
			hp += vc ? vc->hp : cb.hp;
		}
	}
}
// v864 HNV1: the hoard-fuel note (hf_st / hf_alive / hf_inv) is no longer written; living_members_visible recomputes it.
// True when a foe is within 5 of the group's anchor (my ward's sightings too); a foe in my own sight is stamped on the group.
static __attribute__((always_inline)) inline bool observe_foe_near_group(ObserveScan& sc, GroupMem& m, const GroupI& g)
{
	bool enemy_near = false;
	if (!sc.px_box) // the foes' box, once per call (the lists don't change in this loop)
	{
		sc.px_box = true;
		bool any = false;
		for (const auto* lst : { &W.enemies, &W.enemies_far })
			for (const auto& e : *lst)
			{
				if (!any || e.pos.x < sc.px_x0)
					sc.px_x0 = e.pos.x;
				if (!any || e.pos.x > sc.px_x1)
					sc.px_x1 = e.pos.x;
				if (!any || e.pos.y < sc.px_y0)
					sc.px_y0 = e.pos.y;
				if (!any || e.pos.y > sc.px_y1)
					sc.px_y1 = e.pos.y;
				any = true;
			}
	}
	if (g.anchor.x >= sc.px_x0 - 5 && g.anchor.x <= sc.px_x1 + 5 && g.anchor.y >= sc.px_y0 - 5 && g.anchor.y <= sc.px_y1 + 5)
	for (const auto* lst : { &W.enemies, &W.enemies_far }) // my ward's sightings too
		for (const auto& e : *lst)
			if (cheb(e.pos, g.anchor) <= 5)
			{
				m.enemy_seen = now(); // v698 WES: a ward sighting stamps too
				enemy_near = true; // intel::end_turn posts the sighting to the team
				return true; // FB6 RO8: the first hit decides
			}
	return enemy_near;
}
// The reason for the penalty is gone and my sight proves it: lift the threat mark and the foe sighting.
static __attribute__((always_inline)) inline void observe_lift_stale_threat(GroupMem& m, const GroupI& g, bool enemy_near)
{
	if (!enemy_near && (m.thr_round >= now() - 25 || now() - m.enemy_seen < static_cast<int>(ES_TAB[4])) && bbget(W.vis, g.anchor)) // the reason for the penalty is gone and my sight proves it
	{
		bool slv_fn = false;
		for (const auto& e : W.enemies)
			if (cheb(e.pos, g.anchor) <= 8)
			{
				slv_fn = true;
				break;
			}
		if (!slv_fn)
			for (const auto& e : W.enemies_far) // v698 WLF: my ward's sightings keep the mark too
				if (cheb(e.pos, g.anchor) <= 8)
				{
					slv_fn = true;
					break;
				}
		if (!slv_fn)
		{
			if (m.thr_round >= now() - 25) // as lift_flee_blacklist does: the threat mark is lifted on sight instead of on a kill
			{
				if (m.fail_until > now() && m.fail_until <= m.thr_until)
					m.fail_until = std::min(m.fail_until, m.thr_prev_fail);
				if (m.enemy_seen == m.thr_round)
					m.enemy_seen = m.thr_prev_seen;
				m.thr_round = -1000;
			}
			if (m.enemy_seen != m.thr_round && m.enemy_seen < now() && now() - m.enemy_seen < static_cast<int>(ES_TAB[4]))
				m.enemy_seen = -1000;
		}
	}
}
// v790 GHL (RC X419 GHP1): hidden members read at full spawn HP (dead ones too), so a partial sighting could raise the one
// remembered HP. Both values are upper bounds while the group stayed alive since the last write: a die-capture-respawn cycle
// needs >= 3 capture rounds (emblem cap, GR:196) plus the group's cooldown, and a seen respawn passes through a non-ALIVE status.
static __attribute__((always_inline)) inline float ghl_bound(GroupMem& m, const GroupI& g, int vis_n, float hp, std::uint8_t prev)
{
	const int t = now();
	if (prev == GS_ALIVE && vis_n < g.nm && m.hp_left >= 0 && t - static_cast<int>(m.ghl_wr) < g.respawn + 2)
		hp = std::min(hp, m.hp_left);
	m.ghl_wr = static_cast<std::uint16_t>(t);
	return hp;
}
// Reads the group's state: alive, cleared or waiting to respawn.
static __attribute__((always_inline)) inline void observe_read_group_state(const vec2 me, GroupMem& m, const GroupI& g, std::size_t gi, int vis_n, int alive_n, float hp, bool enemy_near)
{
	// a group seen only through my ward (beyond my own sight) has unread camps counted at full health: keep the health we know (camps
	// never regenerate) and only learn that it is alive.
	const auto far = [&] { return cheb(g.anchor, me) > 12; }; // read only where used
	if (alive_n > 0)
	{
		if (!(far() && m.status == GS_ALIVE))
		{
			hp = ghl_bound(m, g, vis_n, hp, m.status); // v790 GHL: a partial read never raises a living group's HP
			if ((m.hp_left != hp || gi >= bgx_gn.size() || bgx_gn[gi] < 0))
				note_attackers_clear_sums(g, gi); // only when the group's HP changed
			m.hp_left = hp;
		}
		m.status = GS_ALIVE;
		return;
	}
	// no visible member alive. One visible spawn tile is enough to read the group's state.
	const bool all_visible = vis_n == g.nm;
	const bool recheck = m.status == GS_UNKNOWN || m.status == GS_ALIVE || now() - m.state_checked >= 6 ||
		static_cast<int>(gi) == T.target;
	if (!recheck)
		return;
	m.state_checked = now();
	std::uint32_t st = 0;
	if (cambc::detail::sdk_camp_group_state(g.handle, &st) != 0)
		return;
	constexpr int handoff_abandon_rounds = 8; // a capture handed off this long ago with no mate near it was abandoned
	if (st == 2 && m.status == GS_RESPAWN && now() - m.handoff < 20 &&
		!(now() - m.handoff >= handoff_abandon_rounds && !capture_or_clear_is_ours(static_cast<int>(gi)))) // past the 7-round pay guess with no mate claiming or near it, the handoff was abandoned
		return; // a crew mate is capturing it
	const std::uint8_t prev = m.status;
	const int prev_at = m.respawn_at;
	const int prev_d = VBC_ON(2) ? m.ecp_d : 0; // VBC 2 ECP1k
	if (st == 2)
	{
		CXL_NOTE(m);
		m.status = GS_CLEARED;
		if (prev != GS_CLEARED && enemy_near && !capture_or_clear_is_ours(static_cast<int>(gi)))
		{
			intel::record_group_cleared(static_cast<int>(gi));
			// far away (my ward sees it), enemies will capture it before we get there: expect a respawn.
			if (far())
			{
				const int vbc = vbc_bits; // VBC_ON(2|4)
				int vbc_t = -1;
				if (vbc & 6) // VBC 2/4 ECP1: the foe's running countdown
				{
					cambc::detail::camp_group_capture_state vcs{};
					if (cambc::detail::sdk_camp_group_capture_state(g.handle, &vcs) == 0 && static_cast<int>(vcs.state) == 3 && vcs.timer >= 0)
						vbc_t = static_cast<int>(vcs.timer);
				}
				if (vbc_t < 0)
					mark_respawn(m, now() + enemy_cap_pay(g) + g.respawn);
				else
				{
					mark_respawn(m, now() + vbc_t + g.respawn);
					if (vbc & 2)
						m.ecp_d = static_cast<std::uint8_t>(std::clamp(enemy_cap_pay(g) - vbc_t, 0, 255)); // VBC 2: the dedup sees the old value
					if (vbc & 4)
						intel::record_group_taken(static_cast<int>(gi), now() + vbc_t); // VBC 4: mates get the exact timer now
				}
			}
		}
		else if (prev != GS_CLEARED && prev != GS_RESPAWN && !enemy_near && !far() && static_cast<int>(gi) == T.target) // the channel's free/CAPTURE posts say it
			intel::record_group_cleared(static_cast<int>(gi)); // our own clear
	}
	else if (st == 3)
	{
		mark_respawn_timer(m, g);
		const bool known = prev == GS_RESPAWN && std::abs(prev_at + prev_d - m.respawn_at) <= 3; // VBC 2: prev_d is 0 unless ECP1k marked it VBC_ON(2) via prev_d
		if (!known && !capture_or_clear_is_ours(static_cast<int>(gi)))
			intel::record_group_taken(static_cast<int>(gi), m.respawn_at - g.respawn);
	}
	else if (st == 1)
	{
		m.status = GS_ALIVE;
		if (!all_visible)
		{
			hp = ghl_bound(m, g, vis_n, hp, prev); // v790 GHL: as above
			if ((m.hp_left != hp || gi >= bgx_gn.size() || bgx_gn[gi] < 0))
				note_attackers_clear_sums(g, gi); // only when the group's HP changed
			m.hp_left = hp; // hidden members counted at full health
		}
	}
}
static __attribute__((always_inline)) inline void observe_group(ObserveScan& sc, std::size_t gi)
{
	const auto& g = M.groups[gi];
	if (sc.obf_b) // v7xx OBF 1 OBX1: no member tile in sight -> vis_n = alive_n = 0 on both count paths (hp is not read then)
	{
		const ObfGroupBits& o = sc.obf_b[gi];
		if (o.k0 >= 0 && !((sc.vis_w[o.k0] & o.m0) | (sc.vis_w[o.k1] & o.m1)))
			return; // v864 OVSC1 (RC X770): no hoard note (see below)
	}
	auto& m = mem[gi];
	int vis_n = 0, alive_n = 0;
	float hp = 0;
	observe_count_group(sc, g, gi, vis_n, alive_n, hp);
	if (vis_n == 0)
		return; // v864 OVSC1 + HNV1 (RC X770 / X839): no hoard note at all; living_members_visible recomputes the same from W.vis / W.occ_camps
	m.seen = now();
	if (sc.obf_s) // v7xx OBF 2 OBX2: the groups seen this turn, ascending (team_mem_scan_seen_groups walks them)
		sc.obf_s[obf_sn++] = static_cast<int>(gi);
	const bool enemy_near = observe_foe_near_group(sc, m, g);
	observe_lift_stale_threat(m, g, enemy_near);
	observe_read_group_state(sc.me, m, g, gi, vis_n, alive_n, hp, enemy_near);
}
void observe()
{
	observe_resize_memory();
	mem_n = M.ng;
	emblem_observe();
	observe_avoid_handoff_region();
	if (wm_cap < 0 && now() > 30 && M.ready() && fuel() > 85000)
		wait_cap_compute(); // after the opening, a few groups per turn that starts with fuel to spare
	sense();
	observe_unseen_mates(); // where I last saw each mate
	if (sg_any())
		siege_observe_foes(); // last seen stats of every body (the team stat ratio)
	update_dash_bank();
	const vec2 me = W.me.pos;
	// Any tribute (ours or theirs) on a map whose altars are gated means a gate is open.
	observe_tribute_signals();
	ring_observe();
	endgame_sample_tributes();
	const bool ow_on = true;
	const std::vector<std::uint8_t>& ow_f = ward::watch_flags();
	// Expiry pass first (nothing below reads another group's memory), then
	// only the groups near me and those my ward watches from afar, in the same ascending order.
	observe_expire_respawns();
	observe_reopen_cleared_groups();
	const std::size_t f2_words = (static_cast<std::size_t>(M.ng) + 63) >> 6;
	if (!(ward_watch_inputs_unchanged(me, ow_on)))
		camps_near_me_mask(me, ow_f, f2_words, ow_on);
	ObserveScan sc{ camp_bits(), W.vis.ptr(), W.occ_camps.ptr(), W.camp_slot.data(), W.camp_slot.size(), W.camps.data(), static_cast<int>(fg::pstamp), me };
	sc.obf_b = obf_group_bits(sc.cbit);
	obf_sn = 0;
	if (obf_seen.size() != static_cast<std::size_t>(M.ng))
		obf_seen.resize(static_cast<std::size_t>(M.ng));
	sc.obf_s = obf_seen.data();
	for (std::size_t f2_w_i = 0; f2_w_i < f2_words; ++f2_w_i)
	for (std::uint64_t f2_b = f2_cand[f2_w_i]; f2_b != 0;)
	{
		const std::size_t gi = (f2_w_i << 6) + static_cast<std::size_t>(__builtin_ctzll(f2_b));
		f2_b &= f2_b - 1;
		observe_group(sc, gi);
	}
	camp_news_write(); // one CAMP entry from my own sight
	// camp-state model (vision, allies' claims, news); take over the captures it inferred out of sight.
}
// team intelligence (intel.cc) about groups: an enemy seen near one, a capture we did not make, an enemy clear.
void ks_turn() { step_onto_capture_region(); }
bool vcd_clear_dash() { return vcd_clear_dash_impl(); } // VCD bit 2
void intel_taken(int gi, int capture_round)
{
	if (gi < 0 || gi >= static_cast<int>(gmem_size(mem)))
		return;
	auto& m = mem[static_cast<std::size_t>(gi)];
	const int at = capture_round + M.groups[static_cast<std::size_t>(gi)].respawn;
	if (at <= now() || busy_with_group(gi))
		return;
	if (m.status == GS_RESPAWN && std::abs(m.respawn_at - at) <= 3)
		return;
	if (m.status == GS_RESPAWN && m.respawn_at > now() && m.respawn_at >= at - INTEL_NEWS_TTL - 1 && m.respawn_at < at && tm2_channel_on())
		return; // XCB bit 4 CMS1: the channel dates TAKEN at the post round, a latest bound; the held timer is inside it
	if (m.status == GS_ALIVE && m.seen > capture_round)
		return;
	mark_respawn(m, at);
	m.state_checked = now();
}
void intel_cleared(int gi, int round)
{
	if (gi < 0 || gi >= static_cast<int>(gmem_size(mem)))
		return;
	auto& m = mem[static_cast<std::size_t>(gi)];
	const bool cnw_own = mate_claims_group_recently(gi, round);
	const bool cs9 = !cnw_own;
	if (busy_with_group(gi) || m.seen > round)
		return;
	if (cs9 && m.status == GS_RESPAWN && m.respawn_at > now())
		return; // a timer I already hold (own sight or TAKEN news) is exact
	if (cnw_own && gi == T.target && W.me.kit && prism_layer::cnw_own() && cheb(W.me.pos, M.groups[static_cast<std::size_t>(gi)].anchor) <= PC_ROUTE_R)
		return; // the carrier a mate may be holding this capture for (mate_waits_for_prism_capture)
	// The enemy is about to capture it: expect a respawn one full timer after the capture.
	mark_respawn(m, round + (enemy_cap_pay(M.groups[static_cast<std::size_t>(gi)])) + M.groups[static_cast<std::size_t>(gi)].respawn);
	m.state_checked = now();
}
} // namespace nova::econ
