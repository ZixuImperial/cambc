// econ_siege_state.cc: State of the team siege (SG3); the turn logic is econ_team_ops.cc.
#include "econ_internal.h"
namespace nova::econ {
namespace {
// Big groups (sg_big) are team operations. A claim on a big group is a call: the claim bytes are the only shared state, and normal
// target choice never claims a big group, so every body reads the same calls. Claims go to -1 while a body banks, recalls, heals or
// is dead, so each body remembers the last big claim of every slot for SG_MEMO rounds.
int cw_sg_gi = -1, cw_sg_end = -1000, cw_sg_arrive = -1000; // my last ended big-group gather (group, end round, arrival round)
struct SgOp
{
	int gi = -1;          // the big group my target works for (-1: none)
	int since = -1000;    // round I called or joined
	int deadline = -1000; // no start by then: the crew did not form
	int arrive = -1000;   // first round I stood at the gather point
	int contested = -1000; // first round of the current contest while gathering (-1000: none)
	bool caller = false;
	int last_committed = -1; // V2m (review M2): the committed count of my last full check (-1: none yet)
	bool started_seen = false; // the operation was seen started at my last full check
};
SgOp SGO;
std::array<int, 8> sg_mgi{ -1, -1, -1, -1, -1, -1, -1, -1 };              // last big group each slot claimed
std::array<int, 8> sg_mround{ -1000, -1000, -1000, -1000, -1000, -1000, -1000, -1000 }; // ... seen at this round
// Last seen power (sqrt(maxHP x (str + focus))) of each enemy body and each ally slot. Unseen bodies grow like build_team's
// unseen allies (str/focus x f, HP x (0.5 + 0.5 f), f = 1 + 0.6 min(1.6, round / 700)), from their last sighting or base kit.
struct SgPw
{
	std::uint32_t h = 0;
	float pw = -1;
	int seen = -1000;
	int type = -1;
};
std::array<SgPw, 8> sg_foe{};
int sg_nfoe = -1;
std::array<int, 8> sg_alive_round{ -1, -1, -1, -1, -1, -1, -1, -1 };
std::array<int, 8> des_r{ -1000, -1000, -1000, -1000, -1000, -1000, -1000, -1000 };
static vec2 uw_tile{ -1, -1 }; // that member tile
static vec2 uw_from{ -1, -1 }; // the tile that walk stepped from (never stepped back onto)
vec2 rw_tile{ -1, -1 }; // that member's tile
// What a step of a turn routine leaves: go on to the next step, end the routine with true (turn used) or with false (choose again).
enum class TurnStep { Next, Done, Again };
} // namespace
// Per-camp health at this body's last sighting (0 = seen dead) and its round. A partly seen group's hidden members keep that health
// while the sighting is younger than the group's respawn + 4 rounds; hp is replaced only when some member is hidden. Fuel: one
// member loop for groups in sight, only while the bit is on.
static std::vector<float> b971_hp;
static std::vector<int> b971_at;
// The groups observe() reads this turn, as a bit set in ascending group order: anchor within 12 of me (lazy per-column and per-row
// masks: anchors are fixed once the map is ready; each column or row costs one pass over the groups, once) or watched by my ward.
std::vector<std::uint64_t> f2_cand, f2_xm, f2_ym;
namespace {
std::array<cambc::champion_type, 8> sh_ftype{}; // by rank, read once (fuel)
std::array<std::uint8_t, 8> sh_fok{};
std::array<int, 8> sh_fresh{};
int sh_nfresh = 0, sh_fresh_t = -1;
int sh_my_cell = -1, sh_my_hpb = -1, sh_my_bagb = -1;
int sh_pend_e = -1, sh_pend_kind = 0, sh_foe_last = -1000;
// TMS bits 8/16 (comms.h): T5+ channel write cap. At flag 0 no work and no state change.
int tcap_wr = -1000, tcap_i = 0, tcap_n_skip = 0;
int tcap_code[4] = { -1, -1, -1, -1 }, tcap_r[4] = { -1000, -1000, -1000, -1000 };
// Writer: one team-memory entry for my POS / STATE / a FOE report. kind 1 pos, 2 hp, 3 bag, 4 foe.
int sh9_n_post = 0, sh9_n_drop = 0;
} // namespace
// my own gold and gems gained so far (positive deltas between my turns; purchases reset the gold base).
int evm_gold = 0, evm_gems = 0, evm_pgold = -1, evm_pgems = -1;
// My own rates for the emblem ranking.
int emb_gold = 0, emb_pgold = -1, emb_turns = 0, emb_fturns = 0, emb_pr = -1000;
// Standing on a spawn tile of a captured group delays its respawn for as long as I stay: step off (toward the altar)
// unless I am capturing there.
static vec2 b957_lr_pos{ -1, -1 }; // the tile leave_respawn_tile last stepped me to
static int mfb_lr_gi = -1; // the group of that step
// Walk to a winning carrier's altar and stand guard. Last seen tile per slot (own sight).
static std::array<vec2, 8> wbe_pos{};
static std::array<int, 8> wbe_r{ -1000, -1000, -1000, -1000, -1000, -1000, -1000, -1000 };
int b957_gh_round = -100; // the round go_home last walked home with the home-edge guard off
} // namespace nova::econ
