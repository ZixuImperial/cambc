// econ_group_helpers.cc: Geometry, crew-on-the-spot and fighting-a-group helpers.
#include "econ_internal.h"
namespace nova::econ {
namespace {

struct Attacker
{
	vec2 pos;
	int reach;
	float str;
	int ci;
};
std::vector<Attacker> living_attackers(int gi, bool assume_all);
// econ::observe's member counts per group, keyed on the perceive stamp.
std::vector<int> hf_st, hf_alive, hf_inv;
// pick_focus_raw from a per-group static member table. Every branch keeps pick_focus_raw's iteration order, float expressions, seed
// choice, pruning test and tie rules.
struct PfM
{
	int ci;
	vec2 pos;
	bool natt; // !attacks(): +100000
	bool ns_ok; // nsk filled (splash kits only: camp_neighbours)
	float nsk; // PASSIVE_VARG_NBR * static same-group neighbours (camp_neighbours(ci).same)
};
struct Hs3Cand
{
	vec2 a;
	int v;
};
int hs3_commit_g = -1;
// Slot hs3[groups.size()] is the altar's shortcut (field M.f_altar); hsb_req_r = the last round a bank walk asked for it; hsb_n =
// the shortcut fields built for groups outside the top HS3_TOP (capped at HSB_MAX).
int hsb_req_r = -10, hsb_n = 0;
// ht_state: -1 undecided, -2 off (read once), 0 off, 1 on; the map trigger's scan over the thin holes is resumed at (word, unread
// bits) like hs3's.
int ht_state = -1, ht_pos = 0;
bool ht_started = false, ht_hit = false;
std::vector<int> ht_sxg; // their savings (scan order, before the cut)
int rgg_f_gi = -1;
int rgg_go = -1; // the target gate_on_way last called a false gate on: only that walk takes the live route
// Walk toward a group using its cached field (fallback: short dynamic search).
int cf_esc_round = -100; // the last round camp_out walked me out of a reach
// Track approach progress (path distance when the group's field exists); drop targets we cannot reach.
vec2 tpr_pos{ -100, -100 }; // my tile at the last tracked turn
// ---------------------------------------------------------------- crew on the spot

struct Here
{
	int n = 0;                   // crew bodies here (me included)
	bool tank_is_me = true;      // I am the best camp tank among them
	const Body* tank = nullptr;  // the tank when it is not me
	int claim_away = 0;          // claimants not seen here yet
	Crew crew;                   // stats of the bodies here
};
// Stand on the group's region until the reward arrives. True while capturing. After handing a plan group's capture to Prism, keep
// off its spawn tiles (a walk through them takes a share of her reward) until it pays or for a set number of rounds.
static int cr_av_gi = -1, cr_av_until = -1;
// ---------------------------------------------------------------- fighting a group

// The awake attacking camps in sight, in W.camps order, once per perceive (W.camps and its awake flags are set in perceive only).
// Scans that keep exactly these entries read the short list instead of every camp in sight.
struct FbAw
{
	vec2 pos;
	int reach;
	float str;
	int group;
};
float cbl_excess = 0.0f;
int cbl_pred_round = -1000, cbl_seen_until = -1000, cbl_priced_round = -1000;
// Checks of an engaged body on an awake group, before its tank or crew-mate turn. True if this turn was used (the body walked out of
// the reach); false with the target dropped lets farm() choose again this turn.
int cf_bad_gi = -1, cf_bad_n = 0, cf_bad_round = -10;
} // namespace
} // namespace nova::econ
