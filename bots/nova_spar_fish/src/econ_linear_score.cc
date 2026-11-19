// econ_linear_score.cc: the linear target score.
#include "econ_internal.h"
#include "econ_linear_score.h"
// econ_linear_score.cc: see econ_linear_score.h. Reached only with LNR_BITS set.
namespace nova::econ::linear_score
{
namespace
{
namespace E = nova::econ;
struct Parts
{
	int gi = -1;
	float alt = 0, clear = 0, dmg = 0, wait = 0, m3 = 1.0f;
	int trav = 0, crew = 1, others = 0, recruits = 0;
};
Parts cur;
float m3_pend = 1.0f;
int m3_gi = -1;
// m: the opportunity cost per body-round
float m_prior = -1.0f;
int smp_r[12] = {}, smp_t[12] = {};
int smp_n = 0, smp_last = -1000;
// state of the target-ranking loop: candidate count and the best pick so far
int nx = 0, pk_gi = -1, pk_crew = 1;
float pk_s = 0, pk_r = 0, pk_b = 1, m_used = 0.6f;
bool pk_any = false;
struct Cand
{
	int gi, crew;
	float r, a0, b;
	float ta[5], tb[5]; // per-term parts (PAVAIL, RISK, PCAP, DENY, CHAIN): S without term k = (a0 - ta[k]) - m (b - tb[k])
};
Cand cands[32];
int nc = 0;
// Opportunity cost per time unit m. A fixed m above rate_for's best ratio makes S rank by the shortest trip, so m is a percentage of
// this choice's best ratio (rate_for's own scale: pen's hand factors cancel). m = LNR_LAMBDA % x r*, r* = my best ratio in the first
// full loop after my target changed, held for the walk; every target comparison uses S with that m.
float hold_m = 0;
int hold_tg = -2;
float lam() { return static_cast<float>(LNR_TAB[11]) / 100.0f; }
float m_of(float best_r) { return lam() * best_r; } // re-taken every loop
float ca[8] = {}, cb[8] = {}; // per caller: A0 and B of its last pick (or rated current target); S = A0 - m B at compare time
// the state at the last choice
struct EvSt
{
	int r = -1000, tg = -1, st = -1, resp = 0, hpb = -1, nfoe = 0, nn = 0, k = 0;
	std::uint32_t gems = 0, gold = 0;
	int near[8] = {};
};
EvSt evs;
int event_foes_near(vec2 a)
{
	int n = 0;
	for (const auto& e : W.enemies)
		if (cheb(e.pos, W.me.pos) <= 8 || cheb(e.pos, a) <= 8)
			++n;
	return n;
}
// mates on my target that are not backing out (a posted retreat counts out)
int event_crew_count(int tg)
{
	int k = 0;
	for (int s2 = 0; s2 < static_cast<int>(comms::CLAIM_SLOTS); ++s2)
		if (s2 != E::my_slot() && comms::cgroup(s2) == tg && comms::ckind(s2) != 1)
			++k; // a dead mate
	for (const auto& al : W.allies)
		if (al.slot >= 0 && al.slot < static_cast<int>(comms::CLAIM_SLOTS) && comms::cgroup(al.slot) == tg && nova::combat::retreating_mates::retreating(al))
			--k;
	return k;
}
bool event_group_known(int gi)
{
	for (int k = 0; k < evs.nn; ++k)
		if (evs.near[k] == gi)
			return true;
	return false;
}
// 0: none; else the reason (diag)
int event_reason()
{
	const int tg = E::T.target;
	const auto& g = M.groups[static_cast<std::size_t>(tg)];
	const auto& mm = E::mem[static_cast<std::size_t>(tg)];
	const int hpb = static_cast<int>(4.0f * W.me.hp / std::max(1.0f, W.me.maxhp));
	if (evs.r != E::T.eval_round || evs.tg != tg)
	{
		evs.r = E::T.eval_round;
		evs.tg = tg;
		evs.st = mm.status;
		evs.resp = mm.respawn_at;
		evs.hpb = hpb;
		evs.nfoe = event_foes_near(g.anchor);
		evs.gems = W.me.gems;
		evs.gold = W.gold;
		evs.k = event_crew_count(tg);
		evs.nn = 0;
		for (int gi = 0; gi < M.ng && evs.nn < 8; ++gi)
			if (gi != tg && cheb(M.groups[static_cast<std::size_t>(gi)].anchor, W.me.pos) <= 4)
				evs.near[evs.nn++] = gi;
		return 0;
	}
	if (mm.status != evs.st || mm.respawn_at != evs.resp)
		return 1;
	if (W.me.gems > evs.gems || W.gold > evs.gold)
		return 2;
	if (hpb != evs.hpb)
		return 3;
	const int nf = event_foes_near(g.anchor);
	if (nf != evs.nfoe)
		return nf > evs.nfoe ? 4 : 5;
	const int kc = event_crew_count(tg);
	if (kc > evs.k)
		evs.k = kc;
	if (kc < evs.k)
		return 8; // a crew mate backs out: re-rank with the smaller crew
	const int bar = LNR_TAB[8];
	if ((static_cast<int>(W.me.gems) >= bar) != (static_cast<int>(evs.gems) >= bar))
		return 6;
	for (int gi = 0; gi < M.ng; ++gi)
		if (gi != tg && cheb(M.groups[static_cast<std::size_t>(gi)].anchor, W.me.pos) <= 4 && E::mem[static_cast<std::size_t>(gi)].status != E::GS_RESPAWN && !event_group_known(gi))
			return 7;
	return 0;
}

float prior()
{
	if (m_prior < 0.0f)
	{
		// the map's group gems per body, quartile cuts 48 / 73 / 137 -> m of .50 / .64 / .65 / .90
		long gems = 0;
		for (const auto& g : M.groups)
			gems += g.gems;
		const float pb = static_cast<float>(gems) / static_cast<float>(std::max(1, E::TM.n));
		m_prior = pb < 48.0f ? 0.50f : (pb < 73.0f ? 0.64f : (pb < 137.0f ? 0.65f : 0.90f));
	}
	return m_prior;
}
// S for the candidate whose parts rate_for just published: S(m) = A0 - m x B. Stage B: every term on top of rf_pen x rf_value.
float sB = 0;
float tA[5] = {}, tB[5] = {}; // this score's per-term parts (PAVAIL, RISK, PCAP, DENY, CHAIN)
float score(int gi)
{
	const auto& g = M.groups[static_cast<std::size_t>(gi)];
	const float v = linear_group_value(gi, E::my_slot());
	float pen = E::rf_pen;
	const auto& mm = E::mem[static_cast<std::size_t>(gi)];
	float t = E::rf_time - (cur.alt); // No altar term in the time (LNR_NOALT).
	t = std::max(1.0f, t);
	for (int k = 0; k < 5; ++k)
	{
		tA[k] = 0.0f;
		tB[k] = 0.0f;
	}
	const float a0 = pen * v;
	float fpav = 1.0f, fpc = 1.0f, pc = -1.0f;
	int fs = -1;
	const float a1 = a0 * fpav * fpc;
	tA[0] = a1 - a0 * fpc;
	tA[2] = a1 - a0 * fpav;
	sB = t + tB[1] + tB[4];
	return a1 + tA[1] + tA[3];
}
// opening_pick's per-body candidates; the hold
Cand sd_c[32];
int sd_n = 0;
int sd_st = 0, sd_tg = -1, sd_k = 0;
int cl_tg = -2, cl_k = 0;
} // namespace

bool due(int eval_round)
{
	if (E::now() - eval_round >= LNR_TAB[10])
		return true;
	const int why = event_reason();
	return why != 0;
}
float linear_group_value(int gi, int self)
{
	(void)gi;
	(void)self;
	return E::rf_value; // the value terms (group_value / crew, gold_weight_in_gems included)
}
void note(int gi, float alt_t, float clear_t, float dmg, float wait, int trav, int crew, int others, int recruits)
{
	cur.gi = gi;
	cur.alt = alt_t;
	cur.clear = clear_t;
	cur.dmg = dmg;
	cur.wait = wait;
	cur.trav = trav;
	cur.crew = std::max(1, crew);
	cur.others = others;
	cur.recruits = recruits;
	cur.m3 = m3_gi == gi ? m3_pend : 1.0f;
	m3_gi = -1;
}
void begin()
{
	nx = 0;
	nc = 0;
	pk_gi = -1;
	pk_any = false;
	pk_s = 0;
}
void cand(int gi, int crew, float r)
{
	if (cur.gi != gi)
		return; // parts not from this rating
	const float a0 = score(gi);
	if (nc < 32)
	{
		cands[nc] = { gi, crew, r, a0, sB, {}, {} };
		for (int k = 0; k < 5; ++k)
		{
			cands[nc].ta[k] = tA[k];
			cands[nc].tb[k] = tB[k];
		}
		++nc;
	}
}
int pick(int caller, int* gi, int* crew, float* r)
{
	if (caller == 1 && (hold_tg != E::T.target || hold_m <= 0.0f))
	{
		hold_m = lam() * *r; // A2: re-taken in the first full loop after a target change, then held for the walk
		hold_tg = E::T.target;
	}
	m_used = m_of(*r);
	pk_any = false;
	for (int k = 0; k < nc; ++k)
	{
		const float sk = cands[k].a0 - m_used * cands[k].b;
		if (!pk_any || sk > pk_s)
		{
			pk_any = true;
			pk_s = sk;
			pk_b = cands[k].b;
			pk_gi = cands[k].gi;
			pk_crew = cands[k].crew;
			pk_r = cands[k].r;
		}
	}
	if (caller >= 0 && caller < 8)
	{
		ca[caller] = pk_any ? pk_s + m_used * pk_b : 0.0f;
		cb[caller] = pk_any ? pk_b : 0.0f;
	}
	if (!pk_any || pk_gi == *gi)
		return 0;
	*gi = pk_gi;
	*crew = pk_crew;
	*r = pk_r; // T.rate keeps the ratio scale
	return 1;
}
void rate_cur(int caller)
{
	if (caller < 0 || caller >= 8 || cur.gi != E::T.target)
		return;
	ca[caller] = score(E::T.target);
	cb[caller] = sB;
}
bool keep_ok(int c1, int cbb, float k)
{
	// r_a >= k x r_b in S terms: S_a >= S_b - (1 - k) x m x B_a (the same at m = r_b)
	const float m = m_used; // the latest pick's m for both sides
	return ca[c1] - m * cb[c1] >= ca[cbb] - m * cb[cbb] - (1.0f - k) * m * cb[c1];
}
int switch_test(int best, float sw)
{
	if (!pk_any || pk_gi != best || cur.gi != E::T.target)
		return -1; // not this loop's pick: the ratio rule
	const float sc = score(E::T.target) - m_used * sB; // the same m and the same time basis (remaining, from my tile)
	float mg;
	mg = sw > 1.0f ? (1.0f - 1.0f / sw) * m_used * std::max(1.0f, sB) : 0.0f; // matches the live sw x ratio rule
	return pk_s > sc + mg ? 1 : 0;
}
bool crew_left()
{
	const int tg = E::T.target;
	if (tg < 0)
	{
		cl_tg = -2;
		return false;
	}
	const int k = event_crew_count(tg);
	const bool left = tg == cl_tg && k < cl_k;
	cl_tg = tg;
	cl_k = k;
	return left;
}
} // namespace nova::econ::linear_score
