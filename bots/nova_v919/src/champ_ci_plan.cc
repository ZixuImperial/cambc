// champ_ci_plan.cc: CI2, the from-scratch Cassi & Issac path (champ_ci_plan.h has the flag and the decision list; policy:
// condor-work/reports/ci_policy_v1_1108.md). Unity build: combat, econ, move and champ_ci come first, so their helpers are in scope.
#include "combat.h"
#include "champions.h"
#include "move.h"
namespace nova::ci2
{
namespace
{
constexpr int TAB_MATE = 2, TAB_BANK = 3, TAB_CHP = 4, TAB_STAND = 5, TAB_L = 6, TAB_LB = 7, TAB_Y = 8, TAB_KITE = 9, TAB_ER = 10, TAB_ED = 11;
constexpr int STUN_HOLD_R = 6;    // decision 5: a visible foe this close keeps the stun for escape
constexpr int STAND_FOE_R = 8;    // decision 4: with a visible foe this close Cassi stands at 4
constexpr int ALTAR_NEAR_R = 8;   // decision 7: both bodies this close to an altar bank their own bags in parallel

static int tab(int i) { return CI2_TAB[i]; }
// CDP bit 1: team size (draft picks, the linked pair counted once) is at most 4; static for the game.
static __attribute__((noinline)) bool cdp_small_team()
{
	static int c = -1;
	if (c < 0)
	{
		int picks = P.n, pair = 0;
		for (int s = 0; s < P.n && s < 8; ++s)
			pair += (P.type[static_cast<std::size_t>(s)] == cambc::champion_type::cassi) ? 1 : 0;
		picks -= pair > 0 ? 1 : 0;
		c = picks <= 4 ? 1 : 0;
	}
	return c == 1;
}
static bool foe_within(int r)
{
	for (const auto& e : W.enemies)
		if (cheb(e.pos, W.me.pos) <= r)
			return true;
	return false;
}
static bool altar_within(vec2 p, int r)
{
	for (const auto& al : M.altars)
		if (cheb(al.pos, p) <= r)
			return true;
	return false;
}
// The partner body when I can see it (nullptr otherwise, also when the partner died).
static const Body* partner_body()
{
	const int ls = combat::cassi_issac_partner_slot();
	return ls >= 0 ? W.ally_by_slot(ls) : nullptr;
}
} // namespace
// ---- Decision 4: Cassi's stand on camps
int stand_r()
{
	if (foe_within(STAND_FOE_R))
		return 4;
	return std::clamp(tab(TAB_STAND), 2, 4);
}
bool stand_exact() { return foe_within(STAND_FOE_R); }
void stand_goals(bitboard& goals, vec2 fp)
{
	if (!stand_exact())
	{
		goals.draw_chebyshev(fp, static_cast<float>(stand_r()));
		return;
	}
	for (int dx = -4; dx <= 4; ++dx)
		for (int dy = -4; dy <= 4; ++dy)
		{
			const vec2 t{ fp.x + dx, fp.y + dy };
			if (inb(t) && cheb(t, fp) == 4)
				bbset(goals, t);
		}
}
// ---- Decision 5: spells on camps. Damage spell on cooldown while standing; the stun only on an awake camp that is hitting, never
// on a sleeping group, and not with a visible foe within 6 (it is her only escape tool). One cast a turn.
// CIB bits 1/2: a foe the team saw within STUN_HOLD_R of me in the last 2 rounds (alive).
static __attribute__((noinline)) bool cib_foe_seen6()
{
	const auto& tt = intel::team_table();
	for (std::size_t i = 0; i < tt.size(); ++i)
	{
		const int r = intel::team_body_round(i);
		if (!tt[i].alive || r <= -1000 || W.round - r > 2)
			continue;
		const Body* b = intel::team_body(i);
		if (b && cheb(b->pos, W.me.pos) <= STUN_HOLD_R)
			return true;
	}
	return false;
}
// CIB bit 1: Cassi keeps the camp nuke while a foe is near (seen now or within 2 rounds), unless it finishes the focus camp.
static __attribute__((noinline)) bool cib_nuke_hold(const Kit& k, int focus_ci)
{
	if (!foe_within(STUN_HOLD_R) && !cib_foe_seen6())
		return false;
	for (const auto& vc : W.camps)
		if (vc.ci == focus_ci && vc.hp <= k.dmg_mod * W.me.foc * (mu::my_camp(mu::OUT))) // X65 bit 4 CNH1: my camp multiplier
			return false;
	return true;
}
void camp_spells(const Kit& k, int focus_ci)
{
	if (W.cast)
		return;
	if (focus_ci >= 0 && k.dmg_on_camps && combat::slot_up(k.slot_dmg) && !W.moved && !(cib_nuke_hold(k, focus_ci))) // CIB bit 1
		combat::camps::camp_abilities_nuke(k, focus_ci);
	if (W.cast || !k.cc_on_camps || !combat::slot_up(k.slot_cc) || foe_within(STUN_HOLD_R) || cib_foe_seen6()) // CIB bit 2
		return;
	int best = -1;
	float bs = 0;
	for (const auto& vc : W.camps)
	{
		const auto& c = M.camps[static_cast<std::size_t>(vc.ci)];
		if (vc.awake && c.attacks() && cheb(c.pos, W.me.pos) <= static_cast<int>(k.cc_range) && c.str > bs && !(!combat::camps::cst_hits_us(vc.ci))) // BB14 CST
		{
			bs = c.str;
			best = vc.ci;
		}
	}
	if (best >= 0)
		combat::cast_on_camp(k.slot_cc, best);
}
// ---- Decision 6: a linked body counts the lower of its own and its visible partner's effective health
float link_friend_h(const Body& b, float h, const combat::Assessment& a)
{
	const int ls = combat::cassi_issac_partner_slot();
	if (ls < 0)
		return h;
	if (b.h != W.me.h)
		return b.slot == ls ? std::min(h, combat::eff_hp(W.me)) : h;
	if (const Body* pb = W.ally_by_slot(ls))
		return std::min(h, combat::eff_hp(*pb));
	return h;
}
const Body* merged_partner(float join_r)
{
	const int ls = combat::cassi_issac_partner_slot();
	const Body* pb = ls >= 0 ? W.ally_by_slot(ls) : nullptr;
	return (pb && !pb->channeling() && static_cast<float>(cheb(pb->pos, W.me.pos)) <= join_r) ? pb : nullptr;
}
static int pb_bag = 0, pb_bag_round = -100000;
static bool pb_trib = false; // CIB bit 4: the partner was last seen tributing within 1 of an altar
static __attribute__((noinline)) bool cib_partner_tributing(int ls)
{
	const Body* pb = W.ally_by_slot(ls);
	if (!pb || !(pb->state & ST_TRIBUTE))
		return false;
	for (const auto& al : M.altars)
		if (cheb(al.pos, pb->pos) <= 1)
			return true;
	return false;
}
constexpr int PB_BAG_AGE = 30; // rounds a last-seen partner bag is trusted
// CIA bit 2: the partner's tribute could have landed (the bag stays carried until then).
static __attribute__((noinline)) bool cia_trib_landed()
{
	const int ls = combat::cassi_issac_partner_slot();
	const int n = ls >= 0 ? rs::tribute_turns_of(pb_bag, P.handle[static_cast<std::size_t>(ls)], W.round) : 1;
	return W.round - pb_bag_round > std::max(1, n) + 1;
}
// CIA bit 1: CIB bit 1's nuke hold from a recent team sighting (assist_cast_slow already skips a foe in sight within 6).
bool cia_nuke_held()
{
	return CI2_FARM() && cib_foe_seen6();
}
int pair_bag()
{
	const int ls = combat::cassi_issac_partner_slot();
	int g = static_cast<int>(W.me.gems);
	if (ls < 0)
		return g;
	std::uint32_t pg = 0;
	if (cambc::detail::sdk_champion_gems(P.handle[static_cast<std::size_t>(ls)], &pg) == 0)
	{
		pb_bag = static_cast<int>(pg);
		pb_bag_round = W.round;
		pb_trib = cib_partner_tributing(ls);
		return g + pb_bag;
	}
	return g + (W.round - pb_bag_round <= PB_BAG_AGE && !(pb_trib && cia_trib_landed()) ? pb_bag : 0); // CIB bit 4, CIA bit 2
}
// Price of death: at least ratio 1 + L to enter a fight when the pair's bag is at least B.
void death_price_bar(float& engage, int bag)
{
	if (bag >= tab(TAB_LB))
	{
		engage = std::max(engage, 1.0f + static_cast<float>((cdp_small_team()) ? CDP_TAB[2] : tab(TAB_L)) / 100.0f); // CDP bit 1: small teams
	}
}
// ---- Fight entry and Cassi's fight actions
int kite_reach() { return std::clamp(tab(TAB_KITE), 1, 4); } // CKF bit 2: kite_now's melee reach G
bool kite_now()
{
	if (!ci_layer::me_cassi() || !W.me.kit || W.me.kit->slot_cc < 0 || combat::ready(W.me.kit->slot_cc))
		return false;
	const int g = std::clamp(tab(TAB_KITE), 1, 4);
	for (const auto& e : W.enemies)
		if (e.kit && !e.kit->ranged && cheb(e.pos, W.me.pos) <= g)
			return true;
	return false;
}
// ---- Decision 3: one body stands on a capture
// CPW bit 1: a kit with no Focus-scaled damaging spell adds no Focus work.
static __attribute__((noinline)) bool cpw_no_foc(const Kit& k)
{
	return k.dmg_mod + k.cc_mod + k.aoe_mod + k.dash_mod <= 0.0f;
}
// The pair's share of the claimants' damage at group gi: claims() leaves out the asking body, so my own claim is read separately.
static float pair_work_share(int gi, float* all_out = nullptr)
{
	const auto& g = M.groups[static_cast<std::size_t>(gi)];
	const auto power = [](const Body& b) { return b.kit ? b.str + (ci_layer::issac(b.type) || (cpw_no_foc(*b.kit)) ? 0.0f : 0.25f * b.foc) : 40.0f; }; // CPW bit 1
	float pair = 0, all = 0;
	const auto add = [&](const Body& b, bool claiming)
	{
		if (!claiming || cheb(b.pos, g.anchor) > 6)
			return;
		const float d = power(b);
		all += d;
		if (ci_layer::type(b.type))
			pair += d;
	};
	add(W.me, econ::claim_target() == gi);
	for (const auto& a : W.allies)
		add(a, econ::claims(a.slot, gi));
	const int ls = combat::cassi_issac_partner_slot();
	if (ls >= 0 && ls < static_cast<int>(comms::CLAIM_SLOTS) && !W.ally_by_slot(ls))
	{
		const std::uint8_t cl = comms::claim(ls);
		if (comms::claim_group(cl) == gi && comms::claim_engaged(cl)) // unseen partner working gi: its posted claim, power from its kit
		{
			const Kit& pk = kit_of(P.type[static_cast<std::size_t>(ls)]);
			const float d = pk.str + (ci_layer::issac(P.type[static_cast<std::size_t>(ls)]) ? 0.0f : 0.25f * pk.foc); // CPW bit 1 (the partner is Issac, or Cassi with Focus damage)
			all += d;
			pair += d;
		}
	}
	if (all_out)
		*all_out = all;
	return all > 0.0f ? pair / all : 0.0f;
}
// b2345 PPY1: on a cluster group, when exactly one of the pair holds Prospector, that body stands; else keep dflt.
static __attribute__((noinline)) bool ppy_yield(const GroupI& g, const Body& pb, bool dflt)
{
	bool clu = false;
	for (int ci : g.members)
	{
		const auto ty = M.camps[static_cast<std::size_t>(ci)].type;
		if (ty == cambc::camp_type::gem_cluster || ty == cambc::camp_type::gold_cluster)
		{
			clu = true;
			break;
		}
	}
	if (!clu)
		return dflt;
	const bool mine = mu::holds_prospector(P.my_slot), theirs = mu::holds_prospector(pb.slot);
	return mine == theirs ? dflt : theirs;
}
bool yield_capture(int gi)
{
	const auto& g = M.groups[static_cast<std::size_t>(gi)];
	if (pair_work_share(gi) < 0.5f)
	{
		for (const auto& a : W.allies)
		{
			if (!ci_layer::type(a.type) && !a.channeling() && econ::on_group_spawn_tile(g, a.pos) && ((a.slot >= 0 && a.slot < 8 && econ::claims(a.slot, gi)))) // CIS bit 4
				return true; // bit 4: a mate stands on it and the pair did under half: the capture is theirs
		}
	}
	const Body* pb = partner_body();
	if (!pb || pb->channeling())
		return false;
	if (!econ::on_group_spawn_tile(g, pb->pos))
		return false;
	if (!(pb->slot >= 0 && pb->slot < 8 && econ::claims(pb->slot, gi))) // b2345 PYC1: a partner passing through does not hold it
		return false;
	if (!econ::on_group_spawn_tile(g, W.me.pos))
		return static_cast<bool>(ppy_yield(g, *pb, true)); // the partner already holds it: I do not step on (b2345 PPY1: unless only I hold Prospector)
	const int mine = econ::cap_rank(P.my_slot, g, W.me.frac(), econ::shards_of(W.me));
	const int theirs = econ::cap_rank(pb->slot, g, pb->frac(), econ::shards_of(*pb));
	return ppy_yield(g, *pb, theirs < mine || (theirs == mine && pb->slot < P.my_slot));
}
// Whoever did the work takes it (bit 4: and whoever did not, does not).
int work_rank(int slot, int gi)
{
	if (slot < 0 || slot >= P.n || gi < 0 || gi >= M.ng)
		return 0;
	float all = 0;
	const float sh = pair_work_share(gi, &all);
	if (all <= 0.0f)
		return 0;
	if (sh >= 0.5f)
		return -200;
	return 200;
}
// ---- Decision 7: bank when the pair's total reaches B; both near an altar bank their own bags in parallel
bool bank_pair(int gems)
{
	const int pair = pair_bag();
	if (gems <= 0 || pair < tab(TAB_BANK))
		return false;
	if (2 * gems >= pair)
		return true;
	const Body* pb = partner_body();
	return pb && altar_within(W.me.pos, ALTAR_NEAR_R) && altar_within(pb->pos, ALTAR_NEAR_R);
}
// ---- Decision 9: on a camp tie Issac acts one step above Cassi, and never above the team's tank (the other bodies' base order)
int issac_order(int want)
{
	const int ls = combat::cassi_issac_partner_slot();
	const Body* pb = ls >= 0 ? W.ally_by_slot(ls) : nullptr;
	if (!pb || cheb(pb->pos, W.me.pos) > 4 || W.me.frac() < 0.3f || (mv::camp_threat(W.me.pos) <= 0 && mv::camp_threat(pb->pos) <= 0 && !(mv::camp_tie_with(pb->pos)))) // CIB bit 8: a camp tie with the partner counts too
		return want;
	int tank = -1000000; // the highest base order among the other bodies (the camp-tank order: higher acts first)
	for (int s = 0; s < P.n; ++s)
	{
		if (s != ls && s != P.my_slot && !ci_layer::type(P.type[static_cast<std::size_t>(s)]))
		{
			tank = std::max(tank, mv::tie_prio(s)); // CIB bit 32: the order in force
		}
	}
	int w = mv::tie_prio(ls) + 1;
	if (tank > -1000000 && w >= tank)
		w = tank - 1;
	return std::max(want, w);
}
// ---- Decision 8: gold. Loose shards keep their entries; Issac all Health with Prospector first; Cassi Power-Focus, then Durability
// Health and Bruiser Health (optionally N Health shards first), with the shared list as the tail.
void build_pass()
{
	namespace E = nova::econ;
	auto& b = E::build;
	constexpr int ST_FO = 1, ST_HP = 2;
	std::vector<cambc::item_type> part;
	{
		FxmItems counts;
		my_item_counts(counts);
		for (std::size_t i = 0; i < b.size();)
		{
			const std::uint32_t id = static_cast<std::uint32_t>(b[i]);
			const std::uint32_t n = id < counts.v.size() ? counts.v[id] : 0u;
			if (n > 0u && n < 5u && std::find(part.begin(), part.end(), b[i]) == part.end())
			{
				part.push_back(b[i]);
				b.erase(b.begin() + static_cast<std::ptrdiff_t>(i));
			}
			else
				++i;
		}
	}
	const auto drop_one = [&b](cambc::item_type t)
	{
		const auto it = std::find(b.begin(), b.end(), t);
		if (it != b.end())
			b.erase(it);
	};
	std::vector<cambc::item_type> front;
	if (ci_layer::me_issac())
	{
		for (auto& t : b)
			t = E::itm_shard(E::itm_family(t), ST_HP);
		front = { E::itm_shard(E::I_PROSPECTOR, ST_HP), E::itm_shard(E::I_DURABILITY, ST_HP) };
	}
	else if (ci_layer::me_cassi())
	{
		const auto hp_first = E::itm_shard(E::I_DURABILITY, ST_HP);
		front = { E::itm_shard(E::I_POWER, ST_FO), hp_first, E::itm_shard(E::I_BRUISER, ST_HP) };
		if (tab(TAB_CHP) > 0)
			front = { hp_first, E::itm_shard(E::I_POWER, ST_FO), E::itm_shard(E::I_BRUISER, ST_HP) };
	}
	else
		return;
	for (const auto& t : front)
		drop_one(t);
	b.insert(b.begin(), front.begin(), front.end());
	b.insert(b.begin(), part.begin(), part.end());
	nova::econ::kbd_pin = static_cast<int>(front.size() + part.size());
}
// True while Cassi has her N Health shards (CI2_CASSI_HP, 1-4) and her Power-Focus emblem is not yet bought.
bool shop_hold(std::size_t item_id, int have)
{
	namespace E = nova::econ;
	const int n = tab(TAB_CHP);
	if (n <= 0 || n >= 5 || !ci_layer::me_cassi() || have < n)
		return false;
	if (item_id != static_cast<std::size_t>(static_cast<std::uint32_t>(E::itm_shard(E::I_DURABILITY, 2))))
		return false;
	FxmItems counts;
	my_item_counts(counts);
	const auto em = static_cast<std::uint32_t>(E::itm_shard(E::I_POWER, 1)) + 1u;
	return em < counts.v.size() && counts.v[em] == 0u;
}
} // namespace nova::ci2
