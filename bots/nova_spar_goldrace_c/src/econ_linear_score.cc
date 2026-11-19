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
	float alt = 0;
};
Parts cur;
// state of the target-ranking loop: candidate count and the best pick so far
int nx = 0, pk_gi = -1, pk_crew = 1;
float pk_s = 0, pk_r = 0, pk_b = 1, m_used = 0.6f;
bool pk_any = false;
struct Cand
{
	int gi, crew;
	float r, a0, b;
	float lm; // LSP: this candidate's lambda (0 when LSP is off)
};
Cand cands[128]; // v682 LSC: M.ng <= 126 groups
int nc = 0;
// Opportunity cost per time unit m. A fixed m above rate_for's best ratio makes S rank by the shortest trip, so m is a percentage of
// this choice's best ratio (rate_for's own scale: pen's hand factors cancel). m = LNR_LAMBDA % x r*, r* = my best ratio in the first
// full loop after my target changed, held for the walk; every target comparison uses S with that m.
float lam() { return static_cast<float>(LNR_TAB[11]) / 100.0f; }
float m_of(float best_r) { return lam() * best_r; } // re-taken every loop
float ca[8] = {}, cb[8] = {}; // per caller: A0 and B of its last pick (or rated current target); S = A0 - m B at compare time
// LSP (bit 1): lambda, the switch factor and SQ_KEEP from the draft's map features plus the candidate's band and foe terms.
int lsp_g[8] = { -1, -1, -1, -1, -1, -1, -1, -1 }; // per caller: the group of ca/cb
float lsp_r = 0.0f;                                   // the latest pick's r*
bool lsp_ok = false;
float lsp_b[3] = {}, lsp_y1[3] = {}, lsp_y2[3] = {};
constexpr float LSP_S[3] = { 50.0f / 3.4641016f, 0.4f / 3.4641016f, 0.5f / 3.4641016f }; // range / sqrt(12): lambda %, switch, keep
constexpr float LSP_LO[3] = { 100.0f, 1.0f, 0.5f }, LSP_HI[3] = { 150.0f, 1.4f, 1.0f };
void lsp_init()
{
	lsp_ok = true;
	float z[8] = {};
	const std::uint32_t v = nova::dmem::extra(LSP_XID, 0xFFFFFFFFu);
	if (v != 0xFFFFFFFFu)
		for (int i = 0; i < 8; ++i)
			z[i] = (static_cast<float>((v >> (4 * i)) & 15u) - 7.5f) / 3.75f;
	for (int k = 0; k < 3; ++k)
	{
		float a = static_cast<float>(LSP_TAB[2 + 11 * k]);
		for (int i = 0; i < 8; ++i)
			a += static_cast<float>(LSP_TAB[3 + 11 * k + i]) * z[i];
		lsp_b[k] = a;
		lsp_y1[k] = static_cast<float>(LSP_TAB[11 + 11 * k]);
		lsp_y2[k] = static_cast<float>(LSP_TAB[12 + 11 * k]);
	}
}
// constant k (0 lambda as a fraction, 1 switch, 2 keep) for candidate group gi (-1: the map terms only)
float lsp_val(int k, int gi)
{
	if (!lsp_ok)
		lsp_init();
	float a = lsp_b[k];
	if (gi >= 0 && gi < M.ng && (lsp_y1[k] != 0.0f || lsp_y2[k] != 0.0f))
	{
		const auto& g = M.groups[static_cast<std::size_t>(gi)];
		a += lsp_y1[k] * (g.contest < 0.4f ? -1.0f : (g.contest > 0.6f ? 1.0f : 0.0f));
		if (lsp_y2[k] != 0.0f) // only the y2 term reads the foe scan (fuel)
		{
			bool foe = false;
			for (const auto& e : W.enemies)
				foe = foe || cheb(e.pos, g.anchor) <= 8;
			for (const auto& e : W.enemies_far)
				foe = foe || cheb(e.pos, g.anchor) <= 8;
			a += foe ? lsp_y2[k] : 0.0f;
		}
	}
	const float c0 = k == 0 ? static_cast<float>(LNR_TAB[11]) : (k == 1 ? static_cast<float>(B467_SWITCH_X100) / 100.0f : SQ_KEEP);
	if (a == 0.0f)
		return k == 0 ? c0 / 100.0f : c0; // all terms 0: the live constant, bit for bit
	const float c = std::min(LSP_HI[k], std::max(LSP_LO[k], c0 + LSP_S[k] * a / 1000.0f));
	return k == 0 ? c / 100.0f : c;
}
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
		if (s2 != E::my_slot() && comms::cgroup(s2) == tg) // BB8P: ckind 1 never arrives
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

// S for the candidate whose parts rate_for just published: S(m) = A0 - m x B. Stage B: every term on top of rf_pen x rf_value.
float sB = 0;
float score(int gi)
{
	const float v = linear_group_value(gi, E::my_slot());
	const float pen = E::rf_pen;
	float t = E::rf_time - (cur.alt); // No altar term in the time (LNR_NOALT).
	t = std::max(1.0f, t);
	sB = t;
	return pen * v;
}
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
	(void)clear_t;
	(void)dmg;
	(void)wait;
	(void)trav;
	(void)crew;
	(void)others;
	(void)recruits;
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
	if (nc < 128)
	{
		cands[nc] = { gi, crew, r, a0, sB, (lsp_val(0, gi)) };
		++nc;
	}
}
int pick(int caller, int* gi, int* crew, float* r)
{
	m_used = m_of(*r);
	lsp_r = *r;
	pk_any = false;
	float pk_m = m_used;
	for (int k = 0; k < nc; ++k)
	{
		const float mk = cands[k].lm * lsp_r; // LSP: each candidate's own lambda
		const float sk = cands[k].a0 - mk * cands[k].b; // LSP: each candidate's own lambda
		if (!pk_any || sk > pk_s)
		{
			pk_m = mk;
			pk_any = true;
			pk_s = sk;
			pk_b = cands[k].b;
			pk_gi = cands[k].gi;
			pk_crew = cands[k].crew;
			pk_r = cands[k].r;
		}
	}
	m_used = pk_m; // the picked candidate's m (keep and switch margins)
	if (caller >= 0 && caller < 8)
	{
		ca[caller] = pk_any ? pk_s + m_used * pk_b : 0.0f;
		cb[caller] = pk_any ? pk_b : 0.0f;
		lsp_g[caller] = pk_any ? pk_gi : -1;
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
	lsp_g[caller] = E::T.target;
}
bool keep_ok(int c1, int cbb, float k)
{
	// r_a >= k x r_b in S terms: S_a >= S_b - (1 - k) x m x B_a (the same at m = r_b)
	// LSP: each side's S at its own lambda (the latest pick's r*)
	const float ma = lsp_val(0, lsp_g[c1]) * lsp_r, mb = lsp_val(0, lsp_g[cbb]) * lsp_r;
	return ca[c1] - ma * cb[c1] >= ca[cbb] - mb * cb[cbb] - (1.0f - k) * ma * cb[c1];
}
int switch_test(int best, float sw)
{
	if (!pk_any || pk_gi != best || cur.gi != E::T.target)
		return -1; // not this loop's pick: the ratio rule
	const float s0 = score(E::T.target); // score() writes sB: call it first, then read sB
	const float sc = s0 - (lsp_val(0, E::T.target) * lsp_r) * sB; // the same m and the same time basis (remaining, from my tile)
	float mg;
	mg = sw > 1.0f ? (1.0f - 1.0f / sw) * m_used * std::max(1.0f, sB) : 0.0f; // matches the live sw x ratio rule
	return pk_s > sc + mg ? 1 : 0;
}
float lsp_switch(int gi) { return lsp_val(1, gi); }
float lsp_keep(int gi) { return lsp_val(2, gi); }
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
