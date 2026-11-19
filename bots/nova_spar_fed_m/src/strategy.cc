// strategy.cc: works out the active strategy each turn and carries the plan through draft memory.
#include "strategy.h"

#include <algorithm>

#include "common.h"
#include "world.h"

namespace nova::strat {

namespace {
constexpr std::uint8_t MAGIC = 0x53, VERSION = 2;
constexpr std::size_t NB = BLOCK_END - BLOCK_AT; // block size in bytes
Mode play_mode = BASE;
Plan play_plan;
bool play_plan_ok = false;
Mode chosen = BASE;
Plan draft_plan;
int eval_round = -1;
Mode eval_mode = BASE;
int eval_phase = -1, eval_rule = -1;
bool forced() { return STRAT_FORCE >= 0 && STRAT_FORCE < NMODES; }

void evaluate()
{
	if (eval_round == W.round)
		return;
	eval_round = W.round;
	eval_phase = -1;
	eval_rule = -1;
	if (!play_plan_ok)
	{
		eval_mode = play_mode;
		return;
	}
	if (play_plan.nr > 0)
	{
		long lead = 0;
		try
		{
			lead = static_cast<long>(cambc::global_submitted_gems(team::ally)) -
				   static_cast<long>(cambc::global_submitted_gems(team::enemy));
		}
		catch (...)
		{
			FXR_PASS();
		}
		for (int i = 0; i < play_plan.nr; ++i)
		{
			const Rule& r = play_plan.rule[i];
			if (W.round < static_cast<int>(r.min_round))
				continue;
			if ((r.kind == R_LEAD && lead >= static_cast<long>(r.thr)) || (r.kind == R_DEFICIT && -lead >= static_cast<long>(r.thr)))
			{
				eval_rule = i;
				break;
			}
		}
	}
	eval_phase = play_plan.n - 1;
	for (int i = 0; i < play_plan.n; ++i)
		if (W.round <= static_cast<int>(play_plan.ph[i].until))
		{
			eval_phase = i;
			break;
		}
	eval_mode = eval_rule >= 0 ? play_plan.rule[eval_rule].mode : play_plan.ph[eval_phase].mode;
}
} // namespace
Mode mode()
{
	if (forced())
		return static_cast<Mode>(STRAT_FORCE);
	evaluate();
	return eval_mode;
}


void set_mode(std::uint8_t m)
{
	play_mode = m < NMODES ? static_cast<Mode>(m) : BASE;
	eval_round = -1;
}
// Block layout (64 bytes): [0] magic, [1] version, [2] phases n, [3] rules nr, [4..15] 4 phases x (mode, until hi, until lo),
// [16..31] parameters, [32..39] 2 rules x (mode, kind, thr / 4, min_round / 8), [40..62] reserved, [63] checksum of [0..62].
void set_block(const std::uint8_t* b, std::size_t n)
{
	play_plan_ok = false;
	eval_round = -1;
	if (n < NB || b[0] != MAGIC || b[1] != VERSION)
		return;
	unsigned sum = 0;
	for (std::size_t i = 0; i + 1 < NB; ++i)
		sum += b[i];
	if ((sum & 255) != b[NB - 1])
		return;
	const int np = b[2], nr = b[3];
	if (np < 1 || np > MAX_PHASES || nr < 0 || nr > MAX_RULES)
		return;
	Plan p;
	p.n = np;
	for (int i = 0; i < np; ++i)
	{
		const std::uint8_t m = b[4 + 3 * i];
		if (m >= NMODES)
			return;
		p.ph[i].mode = static_cast<Mode>(m);
		p.ph[i].until = static_cast<std::uint16_t>(b[5 + 3 * i] << 8 | b[6 + 3 * i]);
	}
	for (int i = 0; i < NPARAM; ++i)
		p.param[i] = b[16 + i];
	p.nr = nr;
	for (int i = 0; i < nr; ++i)
	{
		const std::uint8_t* q = b + 32 + 4 * i;
		if (q[0] >= NMODES || q[1] > R_DEFICIT)
			return;
		p.rule[i].mode = static_cast<Mode>(q[0]);
		p.rule[i].kind = static_cast<RuleKind>(q[1]);
		p.rule[i].thr = static_cast<std::uint16_t>(q[2] * 4);
		p.rule[i].min_round = static_cast<std::uint16_t>(q[3] * 8);
	}
	play_plan = p;
	play_plan_ok = true;
}

std::uint8_t draft_choice()
{
	if (forced())
		return static_cast<std::uint8_t>(STRAT_FORCE);
	if (draft_plan.n > 0)
		return static_cast<std::uint8_t>(draft_plan.ph[0].mode);
	return static_cast<std::uint8_t>(chosen);
}


void write_block(std::vector<std::uint8_t>& mem)
{
	if (draft_plan.n <= 0)
		return;
	if (mem.size() < BLOCK_END)
		mem.resize(BLOCK_END, 0);
	std::uint8_t* b = mem.data() + BLOCK_AT;
	for (std::size_t i = 0; i < NB; ++i)
		b[i] = 0;
	b[0] = MAGIC;
	b[1] = VERSION;
	b[2] = static_cast<std::uint8_t>(draft_plan.n);
	b[3] = static_cast<std::uint8_t>(draft_plan.nr);
	for (int i = 0; i < draft_plan.n; ++i)
	{
		b[4 + 3 * i] = static_cast<std::uint8_t>(draft_plan.ph[i].mode);
		b[5 + 3 * i] = static_cast<std::uint8_t>(draft_plan.ph[i].until >> 8);
		b[6 + 3 * i] = static_cast<std::uint8_t>(draft_plan.ph[i].until & 255);
	}
	for (int i = 0; i < NPARAM; ++i)
		b[16 + i] = draft_plan.param[i];
	for (int i = 0; i < draft_plan.nr; ++i)
	{
		std::uint8_t* q = b + 32 + 4 * i;
		q[0] = static_cast<std::uint8_t>(draft_plan.rule[i].mode);
		q[1] = static_cast<std::uint8_t>(draft_plan.rule[i].kind);
		q[2] = static_cast<std::uint8_t>(std::min(255, draft_plan.rule[i].thr / 4));
		q[3] = static_cast<std::uint8_t>(std::min(255, draft_plan.rule[i].min_round / 8));
	}
	unsigned sum = 0;
	for (std::size_t i = 0; i + 1 < NB; ++i)
		sum += b[i];
	b[NB - 1] = static_cast<std::uint8_t>(sum & 255);
}

float pick_bias(Mode m, int champion)
{
	const auto f = POLICIES[m]->pick_bias;
	return f ? f(champion) : 0.0f;
}

void choose(const mapfeat::Feats& f)
{
	float best = 0.0f;
	Mode pick = BASE;
	for (int m = 0; m < NMODES; ++m)
		if (const auto score = POLICIES[m]->select_score)
		{
			const float v = score(f);
			if (v > best)
			{
				best = v;
				pick = static_cast<Mode>(m);
			}
		}
	chosen = pick;
}

const Policy* active_policy = &POLICY_BASE;
void begin_turn() { active_policy = POLICIES[mode()]; }

} // namespace nova::strat
