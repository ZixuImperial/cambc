// combat_assess_contact.cc: Assess, part 1: first contact and hidden-damage tracking.
#include "combat_internal.h"
namespace nova::combat {
namespace stance
{
namespace tune
{
// The numbers of the HUNT leash (hunt_leash_assess).
inline constexpr float HD_LOW_HP = 0.25f;       // below this share of HP no race is run
inline constexpr float HD_WEAK_FOE_HP = 0.35f;  // a race on a foe below this share only needs HD_LOW_HP of me (else PSV_HDFR)
inline constexpr float HD_FLEE_RATIO = 0.6f;    // a FLEE below this balance is left alone (fh: only a finish)
inline constexpr float HD_FINISH_FOE_HP = 0.7f; // fh: a foe at or below this share can be a finish
inline constexpr int HD_RANGE = 8;              // foes further than this from me get no race
inline constexpr int HD_MATES_R = 6;            // the bodies with me: mates this close, and me
inline constexpr int HD_TARGET_FOES_R = 4;      // foes this close to the target count against the race
inline constexpr int HD_REACH_STEPS = 2;        // a foe within its reach + this of me hits me in the race
inline constexpr int HD_TEAM_STEPS = 2;         // a body within its reach + this of the target adds to the team's damage
inline constexpr float HD_WEAK_FOE_EXTRA = 0.3f; // a foe below this share may have one more body beside it than I have with me
inline constexpr float HD_MIN_TEAM_DPS = 10.0f; // the floor on the team's damage rate in the kill time
inline constexpr float HD_LOCK_MARGIN = 30.0f;  // the locked target's race margin bonus, on PSV_HDRACE
inline constexpr float HD_STEP_COST = 1.0f;     // target score, lowest first: per step beyond my range, on the kill time
inline constexpr float HD_FOE_COST = 2.0f;      // per other foe beside it
inline constexpr float HD_ALONE_BONUS = 3.0f;   // no other foe beside it
inline constexpr float HD_GEM_BONUS = 0.04f;    // per gem in its bag
inline constexpr int HD_GEM_CAP = 80;           // bag gems that count
inline constexpr float HD_LOCK_BONUS = 4.0f;    // it is the locked target
inline constexpr float HD_CHANNEL_BONUS = 4.0f; // it channels (not a fresh recall)
// The numbers of the stance decision (assess). Rule values that live in combat.h (POWER_ENGAGE, CT_R, PEEL_MIN, ...) stay there.
// who enters the assessment
inline constexpr int FOE_SIGHT_R = 9;         // a visible foe further than this is not assessed
inline constexpr int THREAT_R = 6;            // a foe this close goes on a.threats
inline constexpr int MEMORY_ROUNDS = 4; // a foe that left vision counts this many rounds, if last seen within MEMORY_R
inline constexpr int MEMORY_R = 8;            // last seen this close
inline constexpr int MEMORY_REACH_ROUNDS = 2; // only a sighting this recent can threaten me next turn
inline constexpr std::size_t FOE_RESERVE = 8; // one allocation (growing 1, 2, 4, 8 takes ~400 fuel a step)
// the fight balance
inline constexpr int FIGHT_R = 8;             // the foes in the fight: within this of me
inline constexpr int SYM_CONTACT_R = 3; // a foe with none of us this close gets the farming-ally discount
inline constexpr int SOON_REACH_MIN = 2;      // a foe joins soon within max(reach, this) ...
inline constexpr int SOON_REACH_STEPS = 2;    // ... + this of me
inline constexpr int PACK_R = 3;              // a foe's pack: foes this close to it (itself too)
inline constexpr int PACK_N = 3;              // a pack this big near me counts in full
inline constexpr int CAMP_BUSY_R = 1; // a foe this close to an awake camp is busy farming
inline constexpr float CAMP_BUSY_W = 0.6f;    // it brings this share
inline constexpr float CAMP_DRAIN = 4.0f;     // damage from awake camps, x this, comes off the health a body brings
inline constexpr int JOIN_R = 6;              // allies this close join my fight
inline constexpr int JOIN_R_TEAM = 7;         // with a support near (team_fight_mode)
inline constexpr int HEAL_HORIZON = 5;        // turns of heals in a side's power
// mates answering a HELP call, out of my sight
inline constexpr int HELP_AGE = 4;            // a call this old still draws them
inline constexpr int COMING_CLAIM = 5;        // the claim kind of a mate on its way
inline constexpr int COMING_NEAR = 2;         // its distance from the call at ETA <= 2 (the claim's first ETA step)
inline constexpr int COMING_FAR = 4;          // at ETA 3-5
inline constexpr float COMING_HP = 0.85f;     // its assumed share of HP
inline constexpr float GROW_RATE = 0.6f; // econ growth_factor (unseen ally items): 1 + this x min(GROW_CAP, round / GROW_ROUNDS)
inline constexpr float GROW_CAP = 1.6f;
inline constexpr float GROW_ROUNDS = 700.0f;
inline constexpr float GROW_HP_SHARE = 0.5f;  // items lift HP by this share of the growth
// engage and flee bars
inline constexpr float ENGAGE_OUTNUMBERED = 1.7f;
inline constexpr float ENGAGE_OUTNUMBERING = 1.15f;
inline constexpr int BAG_MIN = 20; // from this bag the bars rise, fully at BAG_FULL
inline constexpr float BAG_FULL = 80.0f;      // fully at this bag
inline constexpr float BAG_REACT = 0.2f;      // hit-back bar: + this + BAG_REACT_SLOPE x the bag's share of BAG_FULL
inline constexpr float BAG_REACT_SLOPE = 0.3f;
inline constexpr float LINKED_ENGAGE = 0.15f;
inline constexpr float LINKED_FLEE = 0.1f;
inline constexpr float TEAM_ENGAGE = 0.2f; // with our support in the fight: comes off the engage bar
inline constexpr float TEAM_FLEE = 0.1f; // comes off the flee bar
inline constexpr float TEAM_JOIN = 0.85f;     // and the join bar
inline constexpr float SUPPORT_FLEE_SCALE = 0.9f; // on the flee bar when her own engage scale is below 1
inline constexpr float LOW_HP = 0.3f;         // below this share of HP a body is low
inline constexpr float LOW_HP_LINKED = 0.4f;
// a carrier as focus: both sides priced in gems (see assess_carrier_cut)
inline constexpr float CUT_GEM_VALUE = 2.0f;  // a gem in a bag, either way
inline constexpr float CUT_FARMING = 12.0f;   // 60 rounds of farming lost with a death
inline constexpr float CUT_GOLD = 0.1f;       // a gold of bounty in gems
inline constexpr int CUT_MIN_BAG = 30;        // the focus's bag that starts it
inline constexpr float CUT_MAX = 0.35f; // the largest cut of the engage bar
inline constexpr float CUT_FULL_EDGE = 150.0f; // at this gain over loss
inline constexpr float CUT_FLOOR = 1.05f;     // the cut never takes the bar below this
inline constexpr int KILLER_R = 8;            // the bounty on me: the richest enemy this close
// the base stance
inline constexpr int RECENT_HIT_ROUNDS = 2;   // a hit this recent means the fight has begun
inline constexpr int ENGAGE_SIGHT_R = 6;      // a stronger side only engages what it sees this close
// RYTH_START_NEAR (champ_ryth.h): a Ryth body starts a fight only at this near balance
inline constexpr int CAUGHT_HOME_STEPS = 2;   // caught this close to home, a body runs for it
inline constexpr int FLEE_NEAR_R = 7;         // below the flee bar a foe this close starts the flee
inline constexpr int RETREAT_NEAR_R = 9; // a committed retreat holds with a foe this close
inline constexpr float RETREAT_MARGIN = 0.25f; // up to this over the flee bar
inline constexpr float EVEN_RATIO = 1.0f;     // an even balance
inline constexpr int OUTNUMBERED_NEAR_R = 8;  // outnumbered and not ahead: leave at this distance
// Hysteresis: a stance taken recently is not reversed lightly.
inline constexpr int HYST_ROUNDS = 2;         // a stance taken this recently is not reversed lightly
inline constexpr float HYST_TURN_BACK = 1.4f; // a retreat turns back only at engage x this
// channels and hit-back
inline constexpr float CHANNEL_MIN_RATIO = 0.6f;
inline constexpr int CHANNEL_BIG_BAG = 40;    // from this bag I hit a channel only at an even balance
inline constexpr float CHANNEL_PEEL_RATIO = 0.8f;      // an enemy on a channelling ally is peeled off at this balance
inline constexpr float CHANNEL_PEEL_RATIO_TEAM = 0.7f; // in team-fight mode
inline constexpr int CHANNEL_PEEL_R = 6;
inline constexpr float REACT_OUTNUMBERED = 1.1f; // outnumbered, only a winning trade
// the later rules
inline constexpr int MATE_DEAD_FOES = 2;      // with a mate dead, a fight against this many is left
// CI_MELEE_GAP (champ_ci.h): a linked ranged body keeps this far from melee while the stun is down
inline constexpr int LOCAL_POWER_R = 8;       // local power counts bodies this close
inline constexpr int LOCAL_POWER_STEPS = 2;   // a calm body leaves a foe within its reach + this
inline constexpr float CONVERGE_MY_HP = 0.35f;
inline constexpr float CONVERGE_ALLY_HP = 0.2f;
inline constexpr int CONVERGE_R = 8;          // the ally is this close, and bodies this close to it are counted
inline constexpr int CONVERGE_CONTACT_R = 2;  // a foe this close to the ally: it is in contact
inline constexpr int COMMIT_ROUNDS = 2;       // a mate hit and hitting back this recently is not left alone
inline constexpr float STILL_MY_HP = 0.5f;
inline constexpr int STILL_ALONE_R = 6;       // no other foe this close to it, and the sides are weighed this close to it
inline constexpr float PEEL_MY_HP = 0.3f;
inline constexpr int PEEL_R = 8;              // the ally under fire is this close, and bodies this close to it are counted
inline constexpr int PEEL_HIT_ROUNDS = 1;     // it was hit this recently
inline constexpr int PEEL_NEXT_TO_R = 3;      // foes further from it than this bring PEEL_FAR_W
inline constexpr float PEEL_FAR_W = 0.7f;
inline constexpr int PEEL_CHASER_STEPS = 2;   // a chaser beyond my range + this is out of reach in two turns
inline constexpr float CAMP_FIRST_MY_HP = 0.35f;
inline constexpr float FINISH_MY_HP = 0.35f;
inline constexpr int FINISH_MAX_BAG = 40;     // from this bag no finish rule
inline constexpr float FINISH_ANY_RATIO_HP = 0.5f; // from this HP the rule runs below an even balance too
inline constexpr int FINISH_R = 6;
inline constexpr int FINISH_NEXT_TO_R = 2;    // below even: at most FINISH_MAX_OTHERS other enemies this close to it
inline constexpr int FINISH_MAX_OTHERS = 1;
inline constexpr int LONE_NEAR5_MIN = 3;      // no lone fight against this many
}
namespace {
float ls_ratio_near = 99.0f; // this turn's assess() near balance
int fl_coming_added = 0; // firing count
int mu_coming_ls = 0; // coming mates priced at last-seen stats
static int ele_round = -1, ele_until = -1; // the round it last set FLEE; the last round its stickiness runs
struct HdtOrd
{
	int round = -1000;
	std::uint32_t me = 0;
	int ra = 0, ra2 = 0; // my rank this round / from next round
	int n = 0;
	std::array<std::uint32_t, 12> h{};
	std::array<int, 12> rb{}, rb2{};
};
HdtOrd hdt_o;
// One of my side in the race: team_dps_on's reach per body, once per call.
struct HdaTeamBody
{
	const Body* b;
	vec2 p;
	int r;
	std::size_t k; // its slot in the memo
	bool me;
};
// One call's state. nm < 0: no foe was in range yet, so nm, inc_me and the team below are not filled.
struct HdaCtx
{
	Assessment& a;
	const vec2 me;
	const float my_ehp;
	const bool fh;          // a healthy non-lethal FLEE takes the race on a finish
	const bool any_will_do; // the leash only needs one won race: the focus first
	const bool fs_our, fs_foe; // the DPS_TAB fight-share scaling of our side, of the foes' side
	int nm = -1;            // the bodies with me
	float inc_me = -1.0f;   // the damage rate of the foes that reach me
	std::array<HdaTeamBody, 9> team;
	int n_team = 0;
	HdaCtx(Assessment& as, vec2 at, float ehp, bool finish, bool any, int fs_bits) :
		a(as), me(at), my_ehp(ehp), fh(finish), any_will_do(any), fs_our((fs_bits & 16) != 0), fs_foe((fs_bits & 32) != 0)
	{
	}
};
struct PraMate
{
	vec2 pos{};
	bool assist = false;
	int nf = 0, hps = 0;
	float hp = 0; // its health + shield
};
std::array<PraMate, 8> pra_m{};
int pra_mn = 0, pra_mr = -1000;
// State shared by the pieces of one assess() call.
struct AssessCtx
{
	Assessment& a;
	const vec2 me;
	float e_sq = 0, e_near = 0, e_sq_fc = 0; // their strength: all, those that join soon, with the refit kits
	float e_h = 0;                           // CB3 bit 16 RAB: their health, weighted as their strength
	float f_sq = 0, f_h = 0, me_h = 1;       // our strength, our health, my health
	bool tfm = false;                        // team_fight_mode: our support is near
	int join_r = 0;
	bool ofs_any = false;                    // team_focus runs early for the fight shares
	int ofs_fc = -1;
	const Body* oe = nullptr;
	bool kill_now = false;
	int nc_cleared = -1;                     // the focus NOCHASE cleared this turn
	float engage = 0, flee_thr = 0, join = 1.0f, wsc = 1.0f; // bars; wsc: the support's own engage scale
	EfCounts efc{};
	bool linked = false;
	int bag = 0;
	bool low = false;
	bool ct_soft = false;                    // FLEE from the fight-balance or committed-retreat rule
};
// may this FLEE be priced by the race at all? Prism and linked C&I keep their rules, a lethal flee and a lone 1v3 stay.
static bool flee_race_allowed(const Assessment& a, float fr, int bag, float my_ehp)
{
	if (fr < 0.5f || bag >= 60 || a.incoming >= my_ehp || lethal_spot.round == W.round || (prism_layer::type(W.me.type)) || (linked_slot() >= 0 && !CI2_FIGHT()))
		return false;
	int near5 = 0, al4 = 0;
	for (const auto& f : a.foes)
		near5 += cheb(f.pos, W.me.pos) <= 5;
	if (near5 < 3)
		return true;
	for (const auto& al : W.allies)
		al4 += cheb(al.pos, W.me.pos) <= 4;
	return al4 > 0;
}
// The farthest this foe can be for my next hit: a step and a hit (melee), the shot, or a ready damage spell.
static int my_next_hit_reach()
{
	const Kit& k = *W.me.kit;
	int r = k.ranged ? W.me.range : W.me.range + 1;
	if (k.slot_dmg >= 0 && ready(k.slot_dmg))
		r = std::max(r, static_cast<int>(k.dmg_range));
	if (k.slot_dash >= 0 && ready(k.slot_dash) && !k.ranged)
		r = std::max(r, W.me.range + static_cast<int>(k.dash_range) + 1);
	return r;
}
// Our bodies within 3 of me, me included (visible allies; channelling ones count, they stand there).
static int mates_within_3_count()
{
	int n = 1;
	for (const auto& al : W.allies)
		n += cheb(al.pos, W.me.pos) <= 3 ? 1 : 0;
	return n;
}
// The pack near me: visible enemies within 8 plus foes in combat memory at most ELE_TAB[3] rounds old last seen within 8 of me (each body once).
static int pack_size_near_me()
{
	const vec2 me = W.me.pos;
	int n = 0;
	for (const auto& e : W.enemies)
		n += (cheb(e.pos, me) <= 8 && !foe_model::unreachable(e)) ? 1 : 0;
	for (const auto& sn : seen)
	{
		if (sn.round == W.round || W.round - sn.round > ELE_TAB[3] || cheb(sn.foe.pos, me) > 8)
			continue;
		bool vis = false;
		for (const auto& e : W.enemies)
			vis = vis || e.h == sn.h;
		n += vis ? 0 : 1;
	}
	return n;
}
// Called only with its flag bit on. The HP test runs first (it is the cheap one and most turns stop there).
static bool outnumbered_hurt_flee_wanted(const Assessment& a, bool kill_now)
{
	if (a.stance == FLEE || kill_now || !W.alive || W.me.channeling())
		return false;
	const bool held = W.round <= ele_until;
	if (!held && W.me.frac() * 100.0f >= static_cast<float>(ELE_TAB[5]))
		return false;
	const int pack = pack_size_near_me();
	if (held ? pack < 1 : pack <= mates_within_3_count() + 1)
		return false;
	return !econ::target_pays_within(ELE_TAB[4]);
}
void build_acting_order_table()
{
	if (hdt_o.round == W.round && hdt_o.me == W.me.h)
		return;
	hdt_o.round = W.round;
	hdt_o.me = W.me.h;
	const int pa = PRA_DEC(burst::ed_prio_hdt(W.me.h, false)), pa2 = PRA_DEC(burst::ed_prio_hdt(W.me.h, true)); // our values decode
	hdt_o.ra = hdt_o.ra2 = 0;
	for (const auto& al : W.allies)
	{
		const int p = PRA_DEC(burst::ed_prio_hdt(al.h, false)), p2 = PRA_DEC(burst::ed_prio_hdt(al.h, true));
		hdt_o.ra += (p > pa || (p == pa && al.h < W.me.h)) ? 1 : 0;
		hdt_o.ra2 += (p2 > pa2 || (p2 == pa2 && al.h < W.me.h)) ? 1 : 0;
	}
	const int m = std::min(static_cast<int>(W.enemies.size()), 12);
	std::array<int, 12> pb{}, pb2{};
	for (int x = 0; x < m; ++x)
	{
		const auto ux = static_cast<std::size_t>(x);
		hdt_o.h[ux] = W.enemies[ux].h;
		pb[ux] = burst::ed_prio_hdt(W.enemies[ux].h, false);
		pb2[ux] = burst::ed_prio_hdt(W.enemies[ux].h, true);
	}
	for (int x = 0; x < m; ++x)
	{
		const auto ux = static_cast<std::size_t>(x);
		int r = 0, r2 = 0;
		for (int y = 0; y < m; ++y)
		{
			const auto uy = static_cast<std::size_t>(y);
			r += (pb[uy] > pb[ux] || (pb[uy] == pb[ux] && hdt_o.h[uy] < hdt_o.h[ux])) ? 1 : 0;
			r2 += (pb2[uy] > pb2[ux] || (pb2[uy] == pb2[ux] && hdt_o.h[uy] < hdt_o.h[ux])) ? 1 : 0;
		}
		hdt_o.rb[ux] = r;
		hdt_o.rb2[ux] = r2;
	}
	hdt_o.n = m;
}
} // namespace
static int foe_turns_within_rounds(const Body& e, int k)
{
	if (k <= 1)
		return 0;
	build_acting_order_table();
	int x = 0;
	while (x < hdt_o.n && hdt_o.h[static_cast<std::size_t>(x)] != e.h)
		++x;
	if (x >= hdt_o.n)
		return k - 1; // not in sight: one turn a round
	const auto ux = static_cast<std::size_t>(x);
	auto foe_first = [&](int r, bool now) // e acts before me in round r
	{
		const bool en = enemy_starts(r);
		const int pm = 2 * (now ? hdt_o.ra : hdt_o.ra2) + (en ? 1 : 0);
		const int pf = 2 * (now ? hdt_o.rb[ux] : hdt_o.rb2[ux]) + (en ? 0 : 1);
		return pf < pm;
	};
	int f = foe_first(W.round, true) ? 0 : 1; // this round: e still to act after me
	f += k - 2;                                // every round between
	f += foe_first(W.round + k - 1, false) ? 1 : 0; // the round of my k-th turn: e before me
	return f;
}
namespace {
} // namespace
} // namespace stance
} // namespace nova::combat
