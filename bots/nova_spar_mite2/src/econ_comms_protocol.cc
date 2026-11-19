// econ_comms_protocol.cc: Shared-memory protocol: reads, writes, foe and map posts.
#include "econ_internal.h"
namespace nova::econ {
namespace {
void camp_news_init()
{
	CS.init = true;
	const int ng = M.ng;
	if (ng <= 0)
		return;
	const int avail = comms::spare_bits();
	{
		// empty + 8 ng + 16 ng + 4 cells (6x6 tile grid) + ng codes, parity on top. Too little room: K falls, then no channel.
		int total = comms::team_mem_code_count(ng) + (0);
		int w = 1;
		while ((1 << w) < total)
			++w;
		const int ew_old = w + 1;
		// lossless compact claim/call codes
		total -= ((G.w + 5) / 6) * ((G.h + 5) / 6);
		w = 1;
		while ((1 << w) < total)
			++w;
		const int ew = w + 1;
		const int sl_avail = std::max(0, avail - comms::slim_saved()); // the freed bits stay free (K as the old layout)
		const int avail = sl_avail; // the channel's room (shadows the outer avail in this block only)
		const int k = std::min(2, avail / ew_old); // as many as fit, up to 2, on any team size (K at the old width; freed bits stay free)
		CS.post_lo.assign(static_cast<std::size_t>(ng), -1000);
		CS.tb_kind.assign(static_cast<std::size_t>(ng), 0);
		CS.own_r.assign(static_cast<std::size_t>(ng), 0);
		CS.own_set.assign(static_cast<std::size_t>(ng), 0);
		CS.tb_asof.assign(static_cast<std::size_t>(ng), -1000);
		if (k >= 1 && k * ew <= 32)
		{
			CS.t2 = true;
			CS.ew = ew;
			CS.k = k;
			CS.t2_ng = ng;
			CS.t2_rc = 1 + 8 * ng;
			CS.t2_rr = 1 + 24 * ng;
			CS.t2_c6 = ((G.w + 5) / 6) * ((G.h + 5) / 6);
			CS.t2_fs = 3; // codes per FIGHT cell
			CS.t2_rcrew = CS.t2_rr + CS.t2_fs * CS.t2_c6; // t2_fs codes per FIGHT cell
			CS.t2_rnews = CS.t2_rcrew + ng;
			CS.f = comms::spare_alloc(k * ew);
		}
		if (!CS.f.ok())
		{
			CS.k = 0;
			CS.t2 = false;
		}
		if (!CS.t2)
			qk_rbase = 0;
		return;
	}
}
inline std::uint32_t cmp_ent(std::uint32_t all, int e) { return (all >> (e * CS.ew)) & ((1u << CS.ew) - 1u); }
inline int team_mem_round_bucket(int rem)
{
	int b = 15;
	while (b > 0 && T2_LO[b] > rem)
		--b;
	return b;
}
// One decoded message into the team belief, then into my own memory (own sight overrides; newest wins).
void team_mem_apply_message(int g, int kind, int r_lo, int r_hi, int p)
{
	const auto gu = static_cast<std::size_t>(g);
	if (p < CS.tb_asof[gu])
		return;
	CS.tb_kind[gu] = static_cast<std::int8_t>(kind);
	CS.tb_asof[gu] = p;
	CS.post_lo[gu] = kind == 3 ? r_lo : -1000;
	if (gmem_size(mem) != static_cast<std::size_t>(M.ng) || busy_with_group(g))
		return;
	auto& m = mem[gu];
	if (m.seen >= p - 1)
		return; // my own sight is as new (seen last round: I read it again in this turn's observe, so a mate's post can't overwrite it)
	const int t = now();
	if (kind == 3)
	{
		if (r_lo <= t || (m.status == GS_RESPAWN && m.respawn_at >= r_lo && m.respawn_at <= r_hi))
			return; // due already, or a timer I hold inside the message
		if (g == T.target && W.alive && r_hi - r_lo <= 1 && M.groups[gu].respawn > 0 && r_lo - M.groups[gu].respawn >= t &&
			cheb(M.groups[gu].anchor, W.me.pos) <= r_lo - M.groups[gu].respawn - t + 1)
			return; // a running capture I reach before it pays: my walk to it stands
		mark_respawn(m, r_lo);
	}
	else
	{
		if (kind == 2)
		{
			if (m.status == GS_CLEARED)
				return;
			CXL_NOTE(m);
			m.status = GS_CLEARED;
		}
		else
		{
			if (m.status != GS_RESPAWN && m.status != GS_CLEARED)
				return;
			m.status = GS_UNKNOWN; // assume alive, HP unknown
		}
	}
	m.state_checked = t;
	if (g == T.target && W.alive)
	{
		CS.due = true; // the news touches my target: decide again this turn
	}
}
void team_mem_read()
{
	const std::uint32_t all = comms::spare_get(CS.f);
	const int t = now();
	bool tmf_bump = false;
	if (tmf_lp.e >= 0 && t > tmf_lp.t)
	{
		if (tmf_lp.e < CS.k && cmp_ent(all, tmf_lp.e) != tmf_lp.v && t - tmf_lp.t <= 2)
		{
			tmf_bump = !tmf_lp.resent;
		}
		if (!tmf_bump)
			tmf_lp.e = -1;
	}
	for (int e = 0; e < CS.k; ++e)
	{
		const std::uint32_t v = cmp_ent(all, e);
		const auto eu = static_cast<std::size_t>(e);
		if (v == CS.last[eu])
			continue;
		CS.last[eu] = v;
		CS.first[eu] = t;
		const int code = static_cast<int>(v >> 1);
		if (code == 0)
			continue;
		const int p = t - ((t - static_cast<int>(v & 1u)) & 1); // parity: this round or the last
		if (qk_rbase > 0 && code >= qk_rbase && code < qk_rbase + 64) // The last-seen round code: the one R in [t - 127, t].
		{
			int r = 2 * (code - qk_rbase);
			r += 128 * ((t - r) / 128);
			if (r > t)
				r -= 128;
			qk_mate = std::max(qk_mate, r);
			qk_teamv = std::max(qk_teamv, r);
			continue;
		}
		int g = -1;
		if (code < CS.t2_rc)
		{
			const int x = code - 1, s = x & 7;
			g = x >> 3;
			if (g >= CS.t2_ng)
				continue;
			if (s <= 5)
			{
				const int r = p + s + M.groups[static_cast<std::size_t>(g)].respawn; // exact; an occupied spawn tile only delays it
				team_mem_apply_message(g, 3, r, r + 1, p);
			}
			else
				team_mem_apply_message(g, s == 6 ? 2 : 1, 0, 0, p);
		}
		else if (code < CS.t2_rr)
		{
			const int x = code - CS.t2_rc, b = x & 15;
			g = x >> 4;
			if (g >= CS.t2_ng)
				continue;
			team_mem_apply_message(g, 3, p + T2_LO[b], b == 15 ? 1 << 28 : p + T2_HI[b], p);
		}
		else
		{
			// the old event types keep their readers (no belief table)
			if (code < CS.t2_rcrew)
			{
				const int x = CS.t2_fs == 4 ? code - CS.t2_rr : ((code - CS.t2_rr) / 3) * 4 + (code - CS.t2_rr) % 3; // as the 4-code cell (stop reads as hold)
				comms::fl_call.cell = x >> 2;
				comms::fl_call.call = x & 3;
				comms::fl_call.r = p;
				comms::fl_call.mine = false;
				if ((x & 3) == 0)
				{
					const int cw6 = (G.w + 5) / 6, cell = x >> 2, c = comms::help_c(), cw = (G.w + c - 1) / c;
					const int tx = std::min<int>((cell % cw6) * 6 + 3, G.w - 1), ty = std::min<int>((cell / cw6) * 6 + 3, G.h - 1);
					comms::legacy_in((ty / c) * cw + (tx / c), comms::EV_TYPE_HELP, p); // FIGHT cell x rally = HELP
				}
			}
			else if (code < CS.t2_rnews)
				comms::legacy_in(code - CS.t2_rcrew, 5, p); // CREW g
			else
				comms::legacy_in((code - CS.t2_rnews) >> 2, (code - CS.t2_rnews) & 3, p);
			continue;
		}
	}
	if (tmf_bump) // re-send once; team_mem_pick_entry keeps the priority order
	{
		fxr_poll(); // FXR bit 1 (not shipped, FXR_BITS 2): a no-op
		tmf_lp.e = -1;
		tmf_resending = true;
		const int r0 = t2_lp_res;
		t2_lp_res = -1;
		team_mem_post_legacy_event(tmf_lp.sub, tmf_lp.type, tmf_lp.round);
		t2_lp_res = r0;
		tmf_resending = false;
	}
}
} // namespace
// Reader: decode the field once per turn (only when its bits moved) and merge new entries into my group memory.
__attribute__((always_inline)) void camp_news_read()
{
	if (!CS.init)
	{
		if (M.groups.empty())
			return;
		camp_news_init();
	}
	if (CS.k == 0)
		return;
	if (CS.t2)
	{
		team_mem_read();
		return;
	}
}
bool tm2_channel_on() { return CS.t2; }
bool camp_news_due_take()
{
	if (!CS.due)
		return false;
	CS.due = false;
	return true;
}
namespace {
// Writer (turn start, right after this turn's sight reached mem): one message per turn, the news the team lacks.
inline int team_mem_priority_of_entry(std::uint32_t v)
{
	const int code = static_cast<int>(v >> 1);
	if (code == 0)
		return -1;
	if (qk_rbase > 0 && code >= qk_rbase && code < qk_rbase + 64)
		return 15; // below camp news, above the old enemy news and crew calls
	int g = -1, base = 20;
	if (code < CS.t2_rc)
	{
		g = (code - 1) >> 3;
		if (((code - 1) & 7) == 7)
			base = 5; // 'alive, confirmed' is the lowest
	}
	else if (code < CS.t2_rr)
		g = (code - CS.t2_rc) >> 4;
	else if (code < CS.t2_rcrew)
		return 30; // FIGHT / rally
	else if (code < CS.t2_rnews)
		return 10; // Priority for crew claims.
	else
	{
		const int x = code - CS.t2_rnews;
		if ((x & 3) < 2)
			return 12; // the old enemy news
		g = x >> 2; // the old TAKEN / CLEARED: camp news (an altar subject matches no claim)
	}
	if (base == 20)
		for (int s = 0; g >= 0 && s < P.n && s < comms::CLAIM_SLOTS; ++s)
			if (s != P.my_slot && comms::cgroup(s) == g)
				return 40; // news on a mate-claimed camp
	return base;
}
// The entry a message of priority my_pri about group cg (-1: none) may take, or -1.
int team_mem_pick_entry(std::uint32_t all, int my_pri, int cg0, int t, int* out_sc)
{
	int e = -1, e_sc = -1;
	for (int i = 0; i < CS.k; ++i)
	{
		const auto iu = static_cast<std::size_t>(i);
		const std::uint32_t v = cmp_ent(all, i);
		const int code = static_cast<int>(v >> 1);
		int cg = -1;
		if (code > 0 && code < CS.t2_rc)
			cg = (code - 1) >> 3;
		else if (code >= CS.t2_rc && code < CS.t2_rr)
			cg = (code - CS.t2_rc) >> 4;
		const bool old = t - CS.first[iu] >= (1); // it stood through every mate's turn
		int sc = -1;
		if (cg0 >= 0 && cg == cg0)
			sc = 100; // the same group: newest wins
		else if (code == 0)
			sc = 90;
		else if (old)
			sc = 50 + std::min(t - CS.first[iu], 30);
		else if (team_mem_priority_of_entry(v) < my_pri)
			sc = 10; // higher overwrites lower at once; the bumped writer re-sends
		if (sc > e_sc)
		{
			e_sc = sc;
			e = i;
		}
	}
	if (out_sc)
		*out_sc = e_sc;
	return e;
}
static int bhc_tk = 0, bhc_asof = -1000, bhc_lo = -1000, bhc_post_r = -1000; // BHC bit 1: the team belief my pending post replaced
// A message of mine that another writer overwrote before any mate read it is sent again, unless the new message is about the same group.
static __attribute__((always_inline)) inline void team_mem_resend_if_bumped(std::uint32_t all, int t)
{
	if (CS.pend_e >= 0)
	{
		const std::uint32_t cur = cmp_ent(all, CS.pend_e);
		if (cur != CS.pend_v && CS.pend_g >= 0)
		{
			int cg = -1; // bumped before every mate read it: re-send, unless the new message is about the same group
			const int code = static_cast<int>(cur >> 1);
			if (code > 0 && code < CS.t2_rc)
				cg = (code - 1) >> 3;
			else if (code >= CS.t2_rc && code < CS.t2_rr)
				cg = (code - CS.t2_rc) >> 4;
			if (cg != CS.pend_g)
			{
				const auto pu = static_cast<std::size_t>(CS.pend_g);
				const bool bhc_mine = CS.tb_asof[pu] == bhc_post_r; // RC guard: no newer belief since my post
				CS.tb_kind[pu] = 0;
				if (bhc_mine) // BHC bit 1: the belief my post replaced, so an ALIVE correction is posted again
				{
					CS.tb_kind[pu] = static_cast<std::int8_t>(bhc_tk);
					CS.tb_asof[pu] = bhc_asof;
					CS.post_lo[pu] = bhc_lo;
				}
				if (CS.own_r[pu] > t + 1 && CS.own_set[pu] == 0)
				{
					CS.own_set[pu] = 1; // back on the list: bumped before delivery
					CS.own_list.push_back(CS.pend_g);
				}
			}
		}
		CS.pend_e = -1;
	}
}
// The best camp news found so far this turn.
struct TeamMemBest
{
	int best = -1, sc = -1000000, code = 0, kind = 0, r = 0;
};
// Scores group gi as a candidate for this turn's message and keeps it in B when it beats the best so far.
// Only the groups I see this turn and those I hold an engine timer for are scored (a loop over every group cost 2k fuel a turn).
static __attribute__((always_inline)) inline void team_mem_consider_group(int gi, int t, TeamMemBest& B)
{
	const auto gu = static_cast<std::size_t>(gi);
	const auto& m = mem[gu];
	const auto& g = M.groups[gu];
	const int tk = CS.tb_kind[gu], tr = CS.post_lo[gu];
	int code = 0, kind = 0, r = 0, base = 20;
	// Engine values only (capture countdown, cooldown): an estimate in mem is never posted.
	if (m.seen >= t)
	{
		if (m.status == GS_ALIVE)
		{
			CS.own_r[gu] = 0;
			if ((tk == 2 || (tk == 3 && tr > t + 1)))
			{
				code = 1 + gi * 8 + 7;
				kind = 1;
				base = 5;
			}
		}
		else
		{
			if ((m.status == GS_CLEARED || (m.status == GS_RESPAWN && CS.own_r[gu] <= t)))
			{
				cambc::detail::camp_group_capture_state cs{};
				if (cambc::detail::sdk_camp_group_capture_state(g.handle, &cs) == 0)
				{
					if (cs.state == 1 || cs.state == 3)
					{
						const int k = std::clamp(static_cast<int>(cs.timer), 0, 5);
						r = t + k + g.respawn;
						CS.own_r[gu] = r;
						if (!(tk == 3 && std::abs(tr - r) <= 1))
						{
							code = 1 + gi * 8 + k;
							kind = 3;
						}
					}
					else if (cs.state == 4)
					{
						CS.own_r[gu] = 0;
						if (tk != 2)
						{
							code = 1 + gi * 8 + 6;
							kind = 2;
						}
					}
				}
			}
			if (m.status == GS_RESPAWN && kind == 0 && CS.own_r[gu] <= t)
			{
				std::int32_t timer = 0;
				std::uint32_t st = 0;
				if (cambc::detail::sdk_camp_group_state(g.handle, &st) == 0 && st == 3 && cambc::detail::sdk_camp_group_cooldown(g.handle, &timer) == 0)
					CS.own_r[gu] = t + std::max(1, static_cast<int>(timer));
			}
		}
	}
	const int own = CS.own_r[gu];
	if (code == 0 && kind == 0 && own > t + 1)
	{
		const bool exact = tk == 3 && std::abs(tr - own) <= 1;
		if (!exact)
		{
			const int rem = own - t;
			// First news at once (low edge, 'no earlier than'). A refinement waits for the round when the wait equals a bucket's low edge,
			// so the post is EXACT (R_lo = R): at most one more write, and readers don't plan on a low edge up to 30% early.
			if (tk != 3 || (rem <= 112 && T2_EDGE[static_cast<std::size_t>(rem)]))
			{
				const int b = team_mem_round_bucket(rem);
				code = CS.t2_rc + gi * 16 + b;
				kind = 3;
				r = t + T2_LO[b];
			}
			if (CS.own_set[gu] == 0)
			{
				CS.own_set[gu] = 1; // on the list until the team's round is exact (a bump puts it back)
				CS.own_list.push_back(gi);
			}
		}
	}
	if (code == 0)
		return;
	if (base == 20)
		for (int s = 0; s < P.n && s < comms::CLAIM_SLOTS; ++s)
			if (s != P.my_slot && comms::cgroup(s) == gi)
			{
				base = 40;
				break;
			}
	const int sc = base * 1000 - (kind == 3 ? std::min(std::max(r - t, 0), 200) : 0);
	if (sc > B.sc)
	{
		B.sc = sc;
		B.best = gi;
		B.code = code;
		B.kind = kind;
		B.r = r;
	}
}
// Timer list first (a group I also see now is read after it), dropping the expired.
static __attribute__((always_inline)) inline void team_mem_scan_timer_list(int t, TeamMemBest& B)
{
	std::size_t w = 0;
	for (std::size_t i = 0; i < CS.own_list.size(); ++i)
	{
		const int gi = CS.own_list[i];
		const auto giu = static_cast<std::size_t>(gi);
		if (CS.own_r[giu] <= t + 1 || (CS.tb_kind[giu] == 3 && std::abs(CS.post_lo[giu] - CS.own_r[giu]) <= 1))
		{
			CS.own_set[giu] = 0;
			continue;
		}
		CS.own_list[w++] = gi;
		if (mem[giu].seen < t)
			team_mem_consider_group(gi, t, B);
	}
	CS.own_list.resize(w);
}
// Groups seen this turn that are candidates for news.
static __attribute__((always_inline)) inline void team_mem_scan_seen_groups(int t, TeamMemBest& B)
{
	const int* const sl = obf_seen.data();
	for (int i = 0; i < obf_sn; ++i)
	{
		const int gi = sl[i];
		const auto& pm = mem[static_cast<std::size_t>(gi)];
		if (pm.seen >= t) // the same body as below
		{
			const auto pg = static_cast<std::size_t>(gi);
			if (pm.status == GS_ALIVE && !((CS.tb_kind[pg] == 2 || (CS.tb_kind[pg] == 3 && CS.post_lo[pg] > t + 1))))
				CS.own_r[pg] = 0;
			else
				team_mem_consider_group(gi, t, B);
		}
	}
	return;
}
// Posts the quick-news value when no camp item outranks "alive"; true when this turn's message is written.
static __attribute__((always_inline)) inline bool team_mem_post_quick_news(std::uint32_t all, int t, int best_sc)
{
	if (qk_rbase > 0 && qk_own >= t - 1 && t - qk_teamv >= QKW_TAB[2] - QKW_TAB[8] && best_sc <= 10000) // no camp item above 'alive'
	{
		const int e = team_mem_pick_entry(all, 15, -1, t, nullptr);
		if (e >= 0)
		{
			const std::uint32_t v = static_cast<std::uint32_t>(t & 1) | (static_cast<std::uint32_t>(qk_rbase + ((qk_own / 2) & 63)) << 1);
			const int sh = e * CS.ew;
			const std::uint32_t mk = ((1u << CS.ew) - 1u) << sh;
			comms::spare_put(CS.f, (all & ~mk) | ((v << sh) & mk));
			CS.last[static_cast<std::size_t>(e)] = v;
			CS.first[static_cast<std::size_t>(e)] = t;
			qk_teamv = std::max(qk_teamv, qk_own);
			return true;
		}
	}
	return false;
}
// Writes the best camp news into a free entry and records it as pending.
static __attribute__((always_inline)) inline void team_mem_post_best(std::uint32_t all, int t, const TeamMemBest& B)
{
	if (B.best < 0)
		return;
	const int my_pri = B.sc > 30000 ? 40 : B.sc > 10000 ? 20 : 5;
	int e_sc = -1;
	const int e = team_mem_pick_entry(all, my_pri, B.best, t, &e_sc);
	if (e < 0)
		return;
	const std::uint32_t v = static_cast<std::uint32_t>(t & 1) | (static_cast<std::uint32_t>(B.code) << 1);
	const int sh = e * CS.ew;
	const std::uint32_t mk = ((1u << CS.ew) - 1u) << sh;
	comms::spare_put(CS.f, (all & ~mk) | ((v << sh) & mk));
	const auto eu = static_cast<std::size_t>(e);
	const auto gu = static_cast<std::size_t>(B.best);
	CS.last[eu] = v;
	CS.first[eu] = t;
	bhc_tk = CS.tb_kind[gu]; // BHC bit 1
	bhc_asof = CS.tb_asof[gu];
	bhc_lo = CS.post_lo[gu];
	bhc_post_r = t; // the round of my post (tb_asof below)
	CS.tb_kind[gu] = static_cast<std::int8_t>(B.kind);
	CS.tb_asof[gu] = t;
	CS.post_lo[gu] = B.kind == 3 ? B.r : -1000;
	CS.pend_e = e;
	CS.pend_g = B.best;
	CS.pend_v = v;
}
void team_mem_write()
{
	fxr_poll(); // FXR bit 1 (not shipped, FXR_BITS 2): a no-op
	const int t = now();
	const std::uint32_t all = comms::spare_get(CS.f);
	team_mem_resend_if_bumped(all, t);
	TeamMemBest B;
	team_mem_scan_timer_list(t, B);
	team_mem_scan_seen_groups(t, B);
	if (team_mem_post_quick_news(all, t, B.sc))
		return;
	team_mem_post_best(all, t, B);
}
} // namespace
void team_mem_post_legacy_event(int subject, int type, int round)
{
	bhf_lp = 0; // A plain store, read only with the flag on.
	if (!CS.t2)
		return;
	int code = -1, pri = 12;
	if (type < comms::EV_TYPE_HELP)
	{
		if (subject >= CS.t2_rcrew || subject < 0 || subject >= comms::news_subjects()) // LNB1: codes past the news range
			return;
		code = CS.t2_rnews + 4 * subject + type;
		pri = type < 2 ? 12 : 20;
	}
	else if (type == comms::EV_TYPE_HELP)
	{
		const int c = comms::help_c(), cw = (G.w + c - 1) / c;
		const int tx = std::min<int>((subject % cw) * c + c / 2, G.w - 1), ty = std::min<int>((subject / cw) * c + c / 2, G.h - 1);
		code = CS.t2_rr + CS.t2_fs * ((ty / 6) * ((G.w + 5) / 6) + tx / 6); // t2_fs codes a cell
		pri = 30;
	}
	else if (type == 5 && subject < CS.t2_ng)
	{
		code = CS.t2_rcrew + subject;
		pri = 10;
	}
	if (code < 0)
		return;
	const std::uint32_t all = comms::spare_get(CS.f);
	const int e = team_mem_pick_entry(all, pri, -1, now(), nullptr);
	if (e < 0)
	{
		bh64_lp_drop = true;
		return;
	}
	const std::uint32_t v = static_cast<std::uint32_t>((now()) & 1) | (static_cast<std::uint32_t>(code) << 1); // v683 NPB1: the readers' parity is the post round
	const int sh = e * CS.ew;
	const std::uint32_t mk = ((1u << CS.ew) - 1u) << sh;
	comms::spare_put(CS.f, (all & ~mk) | ((v << sh) & mk));
	CS.last[static_cast<std::size_t>(e)] = v;
	CS.first[static_cast<std::size_t>(e)] = now();
	bhf_lp = 1;
	t2_lp_res = 1;
	if (type < comms::EV_TYPE_HELP)
	{
		tmf_lp.e = e;
		tmf_lp.v = v;
		tmf_lp.t = now();
		tmf_lp.sub = subject;
		tmf_lp.type = type;
		tmf_lp.round = round;
		tmf_lp.resent = tmf_resending;
	}
}
// the 6x6 FIGHT cells of the team-memory channel.
vec2 fight_cell_tile(int cell)
{
	const int cw6 = (G.w + 5) / 6;
	return { std::min<int>((cell % cw6) * 6 + 3, G.w - 1), std::min<int>((cell / cw6) * 6 + 3, G.h - 1) };
}
int fl_cell_of(vec2 p) { return (p.y / 6) * ((G.w + 5) / 6) + p.x / 6; }
// post FIGHT cell(my tile) x call on the channel (priority 30, as HELP). False: no channel or no free entry.
bool fight_cell_post(int call)
{
	fxr_poll(); // FXR bit 1 (not shipped, FXR_BITS 2): a no-op
	if (!CS.t2 || call < 1 || call > 3) // rally goes through brain help_post (HELP)
		return false;
	const int cell = fl_cell_of(W.me.pos);
	const int code = CS.t2_rr + CS.t2_fs * cell + std::min(call, CS.t2_fs - 1); // hold and retreat share 'stop'
	if (code >= CS.t2_rcrew)
		return false;
	const int t = now();
	const std::uint32_t all = comms::spare_get(CS.f);
	const int e = team_mem_pick_entry(all, 30, -1, t, nullptr);
	if (e < 0)
		return false;
	const std::uint32_t v = static_cast<std::uint32_t>(t & 1) | (static_cast<std::uint32_t>(code) << 1);
	const int sh = e * CS.ew;
	const std::uint32_t mk = ((1u << CS.ew) - 1u) << sh;
	comms::spare_put(CS.f, (all & ~mk) | ((v << sh) & mk));
	CS.last[static_cast<std::size_t>(e)] = v;
	CS.first[static_cast<std::size_t>(e)] = t;
	comms::fl_call.cell = cell;
	comms::fl_call.call = call;
	comms::fl_call.r = t;
	comms::fl_call.mine = true;
	return true;
}
int team_mem_claim_state(int g, bool engaged)
{
	if (comms::slim_layout()) // BB8P: the slim field drops the bucket; nothing reads it
		return 0;
	if (g < 0 || g >= M.ng || gmem_size(mem) != static_cast<std::size_t>(M.ng))
		return 3;
	const auto& gg = M.groups[static_cast<std::size_t>(g)];
	const auto& m = mem[static_cast<std::size_t>(g)];
	if (engaged)
	{
		if (m.status == GS_CLEARED)
			return 0;
		int cnt = 1;
		for (int s = 0; s < P.n && s < comms::CLAIM_SLOTS; ++s)
			if (s != P.my_slot && comms::cgroup(s) == g && comms::cengaged(s))
				++cnt;
		const float hp = m.hp_left >= 0 ? m.hp_left : gg.hp;
		const int f = static_cast<int>(hp / (std::max(1.0f, W.me.str) * static_cast<float>(cnt)));
		return f <= 3 ? 0 : f <= 8 ? 1 : f <= 20 ? 2 : 3;
	}
	int w = mv::group_walk_at(g, W.me.pos);
	if (w < 0 || w >= mv::FP_NOWALK)
		w = cheb(gg.anchor, W.me.pos);
	return w == 0 ? 0 : w <= 5 ? 1 : w <= 15 ? 2 : 3;
}
namespace {
NOVA_INLINE bool ward_watch_inputs_unchanged(vec2 me, bool ow_on)
{
	const int xy = me.x * 4096 + me.y;
	const std::uint32_t ver = ward::watch_version();
	if (xy == obx_f2_xy && ver == obx_f2_ver && M.ng == obx_f2_ng)
		return true; // the last call took the cacheable path with these inputs
	obx_f2_xy = WARD_WATCH && ow_on && M.ready() && me.x >= 0 && me.y >= 0 && me.x < G.w && me.y < G.h ? xy : -2147483647 - 1;
	obx_f2_ver = ver;
	obx_f2_ng = M.ng;
	return false;
}
void camp_news_write()
{
	fxr_poll(); // FXR bit 1 (not shipped, FXR_BITS 2): a no-op
	if (!CS.init || CS.k == 0 || P.my_slot < 0 || gmem_size(mem) != static_cast<std::size_t>(M.ng))
		return;
	if (CS.t2)
	{
		team_mem_write();
		return;
	}
}
} // namespace
} // namespace nova::econ
