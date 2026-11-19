// econ_team_model.cc: Kit damage, member stats, the team table, claims, crew size for a group.
#include "econ_internal.h"
namespace nova::econ {
namespace {
std::array<int, 8> sen_claim{ -9, -9, -9, -9, -9, -9, -9, -9 }; // SEN: each mate's last read claim
std::array<int, 8> sen_since{}; // SEN: the round that claim was first read
#define FXP_EXP_NOTE(m) do { if (FXP_ON(FXP_BIT_EXP)) fxp_exp_lo = std::min(fxp_exp_lo, (m).respawn_at); } while (0)
// The walk to the altar for a value, with no known walk read as ALTAR_UNKNOWN.
constexpr float ALTAR_UNKNOWN = 30.0f;
// per slot, the last member_stat with its inputs. Member numbers then cost one copy while the stats hold.
struct MemberMemo
{
	const Kit* k = nullptr;
	float str = 0, foc = 0, dmg = 0;
	Member x{};
};
std::array<MemberMemo, 8> mm_memo{};
std::array<MemberMemo, 8> mm_memo_b{}; // Base-stat builds keep their own memo, so a base/live flip does not miss.
bool mm_base = false; // Set by build_team for this build: true for a base-stat build.
// UPG bit 2: each mate's last-seen numbers (my own sightings).
struct UpgLs
{
	int r = -1;
	float str = 0, foc = 0, maxhp = 0, gf = 1;
};
std::array<UpgLs, 8> upg_ls{};
// GRW bit 1: my last sighting of each mate, and whether I saw it dead since.
struct GrwLs
{
	int r = -1;
	float str = 0, foc = 0, maxhp = 0, hp = 0, gold = 0;
	bool died = false;
};
std::array<GrwLs, 8> grw_ls{};
// Per champion_type (sdk enum order): shards a round to Strength, Focus, Health (diag means; 5 Stellar and 11 Tavi: the mean), and the
// share of a shop's shards to Health, Strength, Focus (own bodies' end-of-game stat units).
constexpr float GRW_SR[13][3] = { { .0119f, .0022f, .0300f }, { .0729f, 0.0f, .0208f }, { .0303f, .0005f, .0105f }, { 0.0f, .0021f, .0008f },
	{ .0063f, 0.0f, .0008f }, { .0169f, .0187f, .0131f }, { .0005f, .1184f, .0270f }, { .0047f, .0439f, .0179f }, { 0.0f, .0090f, .0020f },
	{ .0310f, .0043f, .0143f }, { .0268f, .0017f, .0124f }, { .0169f, .0187f, .0131f }, { .0017f, .0234f, .0077f } };
constexpr float GRW_MIX[13][3] = { { .64f, .30f, .06f }, { .23f, .77f, 0.0f }, { .28f, .71f, .01f }, { .27f, .05f, .68f }, { .30f, .70f, 0.0f },
	{ .30f, .35f, .35f }, { .27f, .01f, .72f }, { .31f, .09f, .60f }, { .44f, .07f, .49f }, { .30f, .65f, .05f }, { .36f, .59f, .05f },
	{ .30f, .35f, .35f }, { .29f, .07f, .64f } };
// crew_for's numbers per member set, for this build of the team view
struct CrewMemo
{
	int epoch = 0;
	Crew c{};
};
std::array<CrewMemo, 256> crew_memo{};
} // namespace
// My region clock starts at my first turn on the cleared region (or the capture timer's cap_on), so when a mate started the team
// timer first it reads k 2-5 rounds high; the engine's ally_capturing countdown is exact. Lowers k to timer + 1 only (callers price
// k as raw-clock rounds, one above the timer); one engine read per round and group.
int bhf_k_r = -1, bhf_k_g = -1, bhf_k_t = 0;
namespace {
NOVA_INLINE std::size_t gmem_size(const std::vector<GroupMem>&) { return static_cast<std::size_t>(mem_n); }
// The one way a group becomes respawning: it pays at `at`. Keeps the expiry bound below every respawn_at.
__attribute__((always_inline)) inline void mark_respawn(GroupMem& m, int at)
{
	m.status = GS_RESPAWN;
	m.respawn_at = at;
	if (VBC_ON(2))
		m.ecp_d = 0; // VBC 2: only the ward-seen foe capture mark sets an offset
	FXP_EXP_NOTE(m);
}
__attribute__((always_inline)) inline float altar_walk(const GroupI& g)
{
	return g.d_altar != UNREACH ? static_cast<float>(g.d_altar) : ALTAR_UNKNOWN;
}
// The engine's own respawn timer of a group in sight.
inline void mark_respawn_timer(GroupMem& m, const GroupI& g)
{
	std::int32_t timer = 0;
	cambc::detail::sdk_camp_group_cooldown(g.handle, &timer);
	mark_respawn(m, now() + std::max(1, static_cast<int>(timer)));
}
// A crew mate captures it: it pays within capture_pay (a Capture holder there: 4), then respawns.
inline void mark_mate_capture(GroupMem& m, const GroupI& g)
{
	m.handoff = now();
	mark_respawn(m, now() + group_capture_pay_rounds(g, -1) + g.respawn);
}
// kit_dps(k, str, foc, 1) and kit_dps(k, str, foc, 3) with their shared parts computed once (the same float operations in the same
// order, so bit-identical to the two calls).
void kit_dps_pack1_and_3(const Kit& k, float str, float foc, float& d1, float& d3)
{
	const float basic = str * (static_cast<float>(rs::slot_cooldown()) + (k.slot_reset >= 0 ? 1.0f : 0.0f)) / static_cast<float>(rs::slot_cooldown());
	float basic3 = basic;
	if (k.splash)
	{
		basic3 *= (1.0f + varg_layer::camp_splash_extra(3.0f));
		VSP_CNT(1, true);
	}
	float spells = 0;
	if (k.slot_dmg >= 0)
		spells += k.dmg_mod * foc;
	if (k.slot_cc >= 0)
		spells += k.cc_mod * foc;
	float spells3 = spells;
	if (k.slot_aoe >= 0)
	{
		const float a = k.aoe_mod * foc;
		spells += a;
		spells3 += a * 3.0f;
	}
	if (k.slot_dash >= 0 && k.dash_mod > 0)
	{
		const float a = k.dash_mod * foc;
		spells += a;
		spells3 += a * 3.0f;
	}
	d1 = basic + spells / static_cast<float>(rs::slot_cooldown());
	d3 = basic3 + spells3 / static_cast<float>(rs::slot_cooldown());
	if (k.missing_hp_bonus)
	{
		d1 *= heart_layer::CLEAR_AVG_MULT;
		d3 *= heart_layer::CLEAR_AVG_MULT;
	}
}
// A member's numbers that depend on the kit and stats only (no health): kept per slot by build_team while the stats hold.
Member member_stat(const Kit& k, float str, float foc, float dmg_mult)
{
	Member x;
	kit_dps_pack1_and_3(k, str, foc, x.dps1, x.dps3);
	x.dps1 *= dmg_mult;
	x.dps3 *= dmg_mult;
	if (k.retaliation)
		x.ret = ren_layer::retaliation_damage(foc) * dmg_mult; // 0.2 x Focus on every camp that hits him (Monster applies)
	x.stuns = camp_stuns(k);
	stun_parts_of_member(x, k);
	x.heal = k.slot_heal >= 0 ? k.heal_mod * foc : 0.0f;
	x.shield = k.slot_shield >= 0 ? k.shield_mod * foc : 0.0f;
	x.melee = !k.ranged;
	if (vendetta_layer::vendash(k))
		x.chain = str * dmg_mult;
	return x;
}
// the health-dependent rest of a member.
inline void member_hp(Member& x, const Kit& k, float hp, float maxhp, float camp_mult)
{
	// Heart of Ruin: kit_dps counts the bonus as a flat x1.12 (a clear started at full health, ending near half). A clear started hurt
	// runs at the bonus of the current health and rises from there. Scope 1: every estimate (target choice too); scope 2
	// (threat_kill_dps): only the clear it is tanking.
	if (k.missing_hp_bonus && maxhp > 0)
	{
		const float m = heart_layer::clear_mult(hp, maxhp);
		x.dps1 *= m / heart_layer::CLEAR_AVG_MULT;
		x.dps3 *= m / heart_layer::CLEAR_AVG_MULT;
	}
	x.budget = std::max(0.0f, hp - static_cast<float>(CAL_TAB[10]) / 100.0f * maxhp) / std::max(0.3f, camp_mult);
	x.budget_he = x.budget; // build_team rescales it
}
Member member_of(const Kit& k, float str, float foc, float hp, float maxhp, float camp_mult, float dmg_mult)
{
	Member x = member_stat(k, str, foc, dmg_mult);
	member_hp(x, k, hp, maxhp, camp_mult);
	return x;
}
// Stat growth of an unseen ally from its items, by round (allies' items are not visible).
float growth_factor()
{
	return 1.0f + 0.6f * std::min(1.6f, static_cast<float>(now()) / 700.0f);
}
inline void member_put(std::size_t ss, const Kit& k, float str, float foc, float hp, float maxhp, float camp_mult, float dmg_mult)
{
	auto& c = mm_base ? mm_memo_b[ss] : mm_memo[ss]; // member_stat is pure, so either memo's hit is the same Member.
	if (c.k != &k || c.str != str || c.foc != foc || c.dmg != dmg_mult)
	{
		c.k = &k;
		c.str = str;
		c.foc = foc;
		c.dmg = dmg_mult;
		c.x = member_stat(k, str, foc, dmg_mult);
	}
	Member& x = TM.m[ss];
	x = c.x;
	member_hp(x, k, hp, maxhp, camp_mult);
}
// ECX bit 1 TML (RC X394): build_team keeps each member's inputs and member_put runs when a reader first takes TM.m[s] (tm_m); a
// member no reader takes this round costs nothing. member_stat and member_hp are pure in their inputs (the memo relies on it too), so
// the value read is the one the eager build wrote.
std::uint32_t tml_pend = 0; // slots whose TM.m[s] waits for its member_put
struct TmlArg
{
	const Kit* k;
	float str, foc, hp, maxhp, cm, dm;
};
std::array<TmlArg, 8> tml_arg{};
std::array<std::uint8_t, 8> tml_k2{}; // b1968 GBF bit 16 TML2: 1 = this slot's pending put is mate_last_seen_put's math (from grw_ls)
std::array<float, 8> tml_age{};       // TML2: the build round's age of that sighting (now() - l.r, >= 0)
static void gbf_mlsp_math(std::size_t ss, const Kit& k, const GrwLs& l, float age, float cm, float dm);
static __attribute__((noinline)) void tm_m_slow(std::size_t s)
{
	tml_pend &= ~(1u << s);
	const TmlArg& a = tml_arg[s];
	if (tml_k2[s]) // b1968 GBF bit 16 TML2: the deferred last-seen math, then its member_put
	{
		tml_k2[s] = 0;
		gbf_mlsp_math(s, *a.k, grw_ls[s], tml_age[s], a.cm, a.dm);
		return;
	}
	member_put(s, *a.k, a.str, a.foc, a.hp, a.maxhp, a.cm, a.dm);
}
__attribute__((always_inline)) inline const Member& tm_m(std::size_t s)
{
	if (__builtin_expect((tml_pend >> s) & 1u, 0))
		tm_m_slow(s);
	return TM.m[s];
}
__attribute__((always_inline)) inline void member_put_d(std::size_t ss, const Kit& k, float str, float foc, float hp, float maxhp, float camp_mult, float dmg_mult)
{
	tml_arg[ss] = TmlArg{ &k, str, foc, hp, maxhp, camp_mult, dmg_mult };
	tml_pend |= 1u << ss;
	tml_k2[ss] = 0; // TML2: a plain put
	return;
}
bool mate_last_seen_stats(int s, float& str, float& foc, float& maxhp, bool& died)
{
	if (s < 0 || s >= 8)
		return false;
	const GrwLs& g = grw_ls[static_cast<std::size_t>(s)];
	if (g.r >= 0)
	{
		str = g.str;
		foc = g.foc;
		maxhp = g.maxhp;
		died = g.died || !siege_ally_alive(s);
		return true;
	}
	const UpgLs& u = upg_ls[static_cast<std::size_t>(s)];
	if (u.r < 0)
		return false;
	str = u.str;
	foc = u.foc;
	maxhp = u.maxhp;
	died = !siege_ally_alive(s);
	return true;
}
static void mate_last_seen_put(std::size_t ss, int s, const Kit& k, GrwLs& l, float cm = 1.0f, float dm = 1.0f) // the mate's camp factors
{
	if (!siege_ally_alive(s))
		l.died = true;
	tml_arg[ss] = TmlArg{ &k, 0.0f, 0.0f, 0.0f, 0.0f, cm, dm };
	tml_age[ss] = static_cast<float>(std::max(0, now() - l.r));
	tml_k2[ss] = 1;
	tml_pend |= 1u << ss;
	return;
}
// b1968 GBF bit 16 TML2: mate_last_seen_put's math (same ops, same order) with the build's age, ending in member_put
static void gbf_mlsp_math(std::size_t ss, const Kit& k, const GrwLs& l, float age, float cm, float dm)
{
	const int t = std::clamp(static_cast<int>(P.type[ss]), 0, 12);
	if (l.died)
	{
		const float u = std::max(0.0f, 0.967f * l.gold / 30.0f + 0.0213f * age);
		const float mh = l.maxhp + u * GRW_MIX[t][0] * k.hp_g;
		member_put(ss, k, l.str + u * GRW_MIX[t][1] * k.str_g, l.foc + u * GRW_MIX[t][2] * k.foc_g, 0.9f * mh, mh, cm, dm);
		return;
	}
	const float a = 0.5f * std::min(age, static_cast<float>(GRW_TAB[2]));
	const float lf = l.hp / std::max(1.0f, l.maxhp);
	const float mh = l.maxhp + a * GRW_SR[t][2] * k.hp_g;
	member_put(ss, k, l.str + a * GRW_SR[t][0] * k.str_g, l.foc + a * GRW_SR[t][1] * k.foc_g, std::min(mh, l.maxhp * (1.0f - (1.0f - lf) * 30.0f / (30.0f + age))), mh, cm, dm);
}
__attribute__((always_inline)) void build_team(bool base)
{
	if (TM.round == now() && TM.base == base)
		return;
	TM.round = now();
	TM.base = base;
	TM.n = std::clamp(P.n, 0, 8);
	mm_base = base;
	refresh_owned();
	float gf_turn = -1.0f; // growth_factor() (>= 1) depends on the round only: read on first need, once.
	const int ng_turn = M.ng; // the group count, not reloaded (and divided by 120) per slot
	const bool mu_camp = mu::on(mu::B_CMATE) && !base; // MUL bit 1024 CMATE: the flag is read once; default off.
	for (int s = 0; s < TM.n; ++s)
	{
		const auto ss = static_cast<std::size_t>(s);
		const Kit& k = kit_of(P.type[ss]);
		float mu_cm = 1.0f, mu_dm = 1.0f; // a mate's own camp factors, last-seen families (1, 1 when off)
		if (mu_camp && s != my_slot())
		{
			const std::uint32_t mf = mu::slot_fam(s, now());
			mu_cm = mu::rule(mf, mu::CAMP, mu::IN);
			mu_dm = mu::rule(mf, mu::CAMP, mu::OUT);
		}
		if (base)
			member_put_d(ss, k, k.str, k.foc, k.hp, k.hp, 1.0f, 1.0f);
		else if (s == my_slot())
			member_put_d(ss, *W.me.kit, W.me.str, W.me.foc, W.me.hp, W.me.maxhp, (mu::on(mu::B_CAMP) ? mu::my_camp(mu::IN) : mu::rule(mu::own_fam(own.jungle, false, false), mu::CAMP, mu::IN)), (mu::on(mu::B_CAMP)) ? mu::my_camp(mu::OUT) : mu::rule(mu::own_fam(false, false, own.monster), mu::CAMP, mu::OUT));
		else if (const Body* b = W.ally_by_slot(s))
		{
			if (gf_turn < 0.0f)
				gf_turn = growth_factor();
			UpgLs& l = upg_ls[ss];
			l.r = now();
			l.str = b->str;
			l.foc = b->foc;
			l.maxhp = b->maxhp;
			l.gf = gf_turn;
			GrwLs& g = grw_ls[ss];
			std::uint32_t gold = 0;
			g.r = now();
			g.str = b->str;
			g.foc = b->foc;
			g.maxhp = b->maxhp;
			g.hp = b->hp;
			g.gold = cambc::detail::sdk_champion_gold(P.handle[ss], &gold) == 0 ? static_cast<float>(gold) : 0.0f;
			g.died = false;
			member_put_d(ss, k, b->str, b->foc, b->hp, b->maxhp, mu_cm, mu_dm);
		}
		else
		{
			if (gf_turn < 0.0f)
				gf_turn = growth_factor();
			const float f = gf_turn;
			const UpgLs& l = upg_ls[ss];
			if (grw_ls[ss].r >= 0)
				mate_last_seen_put(ss, s, k, grw_ls[ss], mu_cm, mu_dm);
			else if (l.r < 0)
				member_put_d(ss, k, k.str * f, k.foc * f, k.hp * (0.5f + 0.4f * f), k.hp * (0.5f + 0.5f * f), mu_cm, mu_dm);
			else
			{
				// Upgrade-model bit 2: its last-seen stats, grown by the growth model since; health at the model's share.
				const float ag = f / std::max(0.5f, l.gf);
				const float mh = l.maxhp * ag;
				member_put_d(ss, k, l.str * ag, l.foc * ag, mh * (0.5f + 0.4f * f) / (0.5f + 0.5f * f), mh, mu_cm, mu_dm);
			}
		}
		if (s == my_slot())
		{
			TM.claim[ss] = T.target;
			TM.busy[ss] = T.engaged;
		}
		else
		{
			const int g = comms::cgroup(s);
			TM.claim[ss] = g < ng_turn ? g : -1;
			TM.busy[ss] = comms::cengaged(s);
			if (!base && TM.claim[ss] >= 0 && !siege_ally_alive(s))
			{
				TM.claim[ss] = -1; // a dead mate claims nothing
				TM.busy[ss] = false;
			}
			if (ss < 8 && TM.claim[ss] != sen_claim[ss])
			{
				sen_claim[ss] = TM.claim[ss]; // SEN bit 1: when this claim began
				sen_since[ss] = now();
			}
		}
	}
	// tank_order is a permutation of the slots once the plan is made, so the sorted list is its inverse.
	static int xic_tbt_last = -1, xic_tbt_n = -1; // v723 XIC bit 64 TBT1: by_tank depends only on tank_order (plan_tank_order) and TM.n
	if (XIC_ON(64) && xic_tbt_last == xic_tbt_ver && xic_tbt_n == TM.n)
	{
	}
	else
	{
		if (XIC_ON(64))
		{
			xic_tbt_last = xic_tbt_ver;
			xic_tbt_n = TM.n;
		}
		int seen = 0;
		for (int s = 0; s < TM.n; ++s)
		{
			const int o = P.tank_order[static_cast<std::size_t>(s)];
			if (o < 0 || o >= TM.n)
				break;
			TM.by_tank[static_cast<std::size_t>(o)] = s;
			seen |= 1 << o;
		}
		if (seen != (1 << TM.n) - 1)
		{
			for (int s = 0; s < TM.n; ++s)
				TM.by_tank[static_cast<std::size_t>(s)] = s;
			std::sort(TM.by_tank.begin(), TM.by_tank.begin() + TM.n,
				[](int a, int b) { return P.tank_order[static_cast<std::size_t>(a)] < P.tank_order[static_cast<std::size_t>(b)]; });
		}
	}
	++crew_epoch;
}
inline Crew::Crew(const Crew& o) { vmove_n<sizeof(Crew)>(reinterpret_cast<unsigned char*>(this), reinterpret_cast<const unsigned char*>(&o)); }
// the claim as team memory holds it this turn (TM.claim may be from an earlier turn).
bool claim_is_fresh(int s, int gi)
{
	return gi >= 0 && s >= 0 && s < TM.n && s != my_slot() && s < comms::CLAIM_SLOTS && comms::claim_group(comms::claim(s)) == gi;
}
bool claims(int s, int gi)
{
	return s >= 0 && s < TM.n && s != my_slot() && TM.claim[static_cast<std::size_t>(s)] == gi;
}
// Bodies other than `self` claiming group gi.
int claimants(int gi, int self, const Claims& cl)
{
	// The same count from two i32x4 compares: bit s set for cl[s] == gi, kept for s < TM.n, s != self (a self outside 0..7 matches
	// no slot, as in the loop).
	const v128_t v = wasm_i32x4_splat(gi);
	std::uint32_t mk = wasm_i32x4_bitmask(wasm_i32x4_eq(wasm_v128_load(cl.data()), v)) |
		(wasm_i32x4_bitmask(wasm_i32x4_eq(wasm_v128_load(cl.data() + 4), v)) << 4);
	mk &= TM.n <= 0 ? 0u : (TM.n >= 8 ? 0xFFu : ((1u << TM.n) - 1u));
	if (static_cast<unsigned>(self) < 8u)
		mk &= ~(1u << self);
	return __builtin_popcount(mk);
}
int claimants(int gi) { return claimants(gi, my_slot(), TM.claim); }
// The slots free_near() counts (visible, within 8, not channelling unless a recall frees it); crew_for's pass 0 takes `extra` of
// these only, not the best tanks among every free body (otherwise some picks would be unseen mates).
std::uint32_t free_near_mask()
{
	std::uint32_t m = 0;
	for (const auto& a : W.allies)
		if (a.slot >= 0 && a.slot < TM.n && a.slot < 8 && (!a.channeling() || recall_frees_channel(a)) && cheb(a.pos, W.me.pos) <= 8)
			m |= 1u << a.slot;
	return m;
}
// The crew of member set `mask` (bit s = slot s), best camp tank first, from the memo.
inline const Crew& crew_of_mask(std::uint32_t mask)
{
	// a crew's numbers depend only on its member set and on the team view (build_team)
	auto& cm = crew_memo[static_cast<std::size_t>(mask)];
	if (cm.epoch != crew_epoch)
	{
		cm.epoch = crew_epoch;
		vzero_n<sizeof(Crew)>(reinterpret_cast<unsigned char*>(&cm.c)); // Crew{} is all zero bytes (every member is 0 / 0.0f)
		for (int i = 0; i < TM.n; ++i)
		{
			const int s = TM.by_tank[static_cast<std::size_t>(i)];
			if ((mask >> s) & 1u)
				cm.c.add(ECX_TM(static_cast<std::size_t>(s)));
		}
	}
	return cm.c;
}
const Crew& crew_for_ref(int gi, int self, int extra, const Claims& cl, Claims* extras = nullptr, int recruit = 0, bool rfree = false)
{
	// Members: self and gi's claimants, then up to `extra` free bodies (no claim), then up to `recruit` bodies that would leave their
	// own (not yet engaged) targets; best camp tanks first in each pass. The member set is a bit mask (bit s = in[s]). The initial set
	// comes from two i32x4 compares (cl[s] == gi), plus self, for s < TM.n.
	int ne = 0;
	const std::uint32_t nmask = TM.n <= 0 ? 0u : (TM.n >= 8 ? 0xFFu : ((1u << TM.n) - 1u));
	std::uint32_t mask;
	{
		const v128_t v = wasm_i32x4_splat(gi);
		mask = wasm_i32x4_bitmask(wasm_i32x4_eq(wasm_v128_load(cl.data()), v)) |
			(wasm_i32x4_bitmask(wasm_i32x4_eq(wasm_v128_load(cl.data() + 4), v)) << 4);
		if (static_cast<unsigned>(self) < 8u)
			mask |= 1u << self;
		mask &= nmask;
	}
	int rleft = 0; // recruits pass 1 left for free mates (pass 2, only with rfree)
	const std::uint32_t bhf_fm = (self == P.my_slot && !TM.base && !(extra <= 0)) ? free_near_mask() : 0xFFFFFFFFu;
	for (int pass = 0; pass < (rfree ? 3 : 2); ++pass)
	{
		int left = pass == 0 ? extra : pass == 1 ? recruit : rleft;
		for (int i = 0; i < TM.n && left > 0; ++i)
		{
			const int s = TM.by_tank[static_cast<std::size_t>(i)];
			const auto ss = static_cast<std::size_t>(s);
			if (((mask >> s) & 1u) || TM.busy[ss] ||
				((pass != 1) != (cl[ss] < 0) && !(pass == 0 && self == P.my_slot && !TM.base && nova::econ::crew_bypass::ok(s, gi, cl[ss])))) // A claimed mate passing near on its way to a far claim.
				continue;
			if (pass == 0 && !((bhf_fm >> s) & 1u))
				continue; // a free body free_near did not count
			if (!siege_ally_alive(s))
				continue; // a dead mate is not free crew
			mask |= 1u << s;
			--left;
			if (extras && ne < 8)
				(*extras)[static_cast<std::size_t>(ne++)] = s;
		}
		if (pass == 1)
			rleft = left;
	}
	if (extras)
		for (int i = ne; i < 8; ++i)
			(*extras)[static_cast<std::size_t>(i)] = -1;
	const Crew& c = crew_of_mask(mask); // The memo lookup lives in crew_of_mask.
	return c;
}
Crew crew_for(int gi, int self, int extra, const Claims& cl, Claims* extras = nullptr, int recruit = 0, bool rfree = false)
{
	return crew_for_ref(gi, self, extra, cl, extras, recruit, rfree);
}
// Crew of the bodies other than `self` that claim group gi (best camp tank first).
Crew crew_of_claimants(int gi, int self, const Claims& cl)
{
	Crew c;
	// The claimant set as a bit mask from two i32x4 compares (as claimants), then the same tank order.
	const v128_t v = wasm_i32x4_splat(gi);
	std::uint32_t mk = wasm_i32x4_bitmask(wasm_i32x4_eq(wasm_v128_load(cl.data()), v)) |
		(wasm_i32x4_bitmask(wasm_i32x4_eq(wasm_v128_load(cl.data() + 4), v)) << 4);
	if (static_cast<unsigned>(self) < 8u)
		mk &= ~(1u << self);
	if (mk != 0)
		for (int i = 0; i < TM.n; ++i)
		{
			const int s = TM.by_tank[static_cast<std::size_t>(i)];
			if ((mk >> s) & 1u)
				c.add(ECX_TM(static_cast<std::size_t>(s)));
		}
	return c;
}
// a heavy group (an elk, golem or monolith and >= 30 gems; static data)
bool he_group(const GroupI& g) { return g.gems >= 30 && g.n_elk + g.n_golem + g.n_mono > 0; }
// heavy-estimate bit 2: a group the team may clear over several trips: walkable, own side or middle, not next to our spawn, no enemy
// seen at it for HE_QUIET rounds.
// v8xx NSG (callers read NSG_ON first): the class, per group, static once M is done (-1 unknown, 0, 1).
__attribute__((noinline)) bool nsg_class(const GroupI& g)
{
	static std::vector<signed char> c;
	static int open_ok = -1;
	if (!M.done() || g.idx < 0 || g.idx >= M.ng)
		return false;
	if (open_ok < 0)
	{
		float all = 0, open = 0;
		for (const auto& q : M.groups)
		{
			all += static_cast<float>(q.gems);
			if (q.n_mono + q.n_golem == 0)
				open += static_cast<float>(q.gems);
		}
		open_ok = (all <= 0.0f || open / all >= 0.15f) ? 1 : 0; // not a siege map (static, from M)
		c.assign(static_cast<std::size_t>(M.ng), -1);
	}
	auto& v = c[static_cast<std::size_t>(g.idx)];
	if (v < 0)
		v = (open_ok && g.n_mono == 0 && he_group(g) && g.access == ACC_WALK && g.d_home != UNREACH && static_cast<int>(g.d_home) <= g.reach_max + 3 &&
				g.contest * 100.0f <= static_cast<float>(HE_CONT_X100)) ? 1 : 0;
	return v > 0;
}
bool heavy_multi_trip_ok(const GroupI& g, const GroupMem& m)
{
	return g.access == ACC_WALK && g.d_home != UNREACH && (static_cast<int>(g.d_home) > g.reach_max + 3 || nsg_class(g)) && g.contest * 100.0f <= static_cast<float>(HE_CONT_X100) && now() - m.enemy_seen >= HE_QUIET;
}
inline bool recall_frees_channel(const Body& a)
{
	return (a.state & ST_RECALL) != 0 && (a.state & (ST_TRIBUTE | ST_TELEPORT)) == 0 && a.slot < 8 && rcm_rcr[static_cast<std::size_t>(a.slot)] == now() && rcm_rc[static_cast<std::size_t>(a.slot)] >= RCM_TAB[2];
}
int free_near()
{
	int n = 0;
	for (const auto& a : W.allies)
		if (a.slot >= 0 && a.slot < TM.n && (!a.channeling() || recall_frees_channel(a)) && cheb(a.pos, W.me.pos) <= 8 &&
			TM.claim[static_cast<std::size_t>(a.slot)] < 0)
			++n;
	n += nova::econ::crew_bypass::count();
	return n;
}
// Claims as I count them for my own choice: a body that acts after me (lower priority) yields to my claims, so
// only claims of bodies before me (higher priority) count against a group I already hold.
Claims claims_for_me()
{
	Claims cl = TM.claim;
	cl[static_cast<std::size_t>(my_slot())] = -1;
	if (T.target >= 0 && !(T.crew >= 2)) // a crew choice keeps its crew mates' claims
		for (int s = 0; s < TM.n; ++s)
		{
			if (s != my_slot() && cl[static_cast<std::size_t>(s)] == T.target && !TM.busy[static_cast<std::size_t>(s)] && (P.prio[static_cast<std::size_t>(s)] < P.prio[static_cast<std::size_t>(my_slot())] || (s < 8 && sen_since[static_cast<std::size_t>(s)] > T.chosen)) && !T.engaged) // SEN bit 1: a newer claim yields
			{
				cl[static_cast<std::size_t>(s)] = -1;
			}
		}
	return cl;
}
} // namespace
bool cps_cps2_dead = false; // v7xx CPS2: the last engine read says paid (no capture available) or enemy capturing
int engine_capture_countdown(int gi, int k)
{
	if (bhf_k_r != now() || bhf_k_g != gi)
	{
		bhf_k_r = now();
		bhf_k_g = gi;
		bhf_k_t = 0;
		cambc::detail::camp_group_capture_state cs{};
		const int cps_rc = cambc::detail::sdk_camp_group_capture_state(M.groups[static_cast<std::size_t>(gi)].handle, &cs); // v7xx CPS2: the one read
		cps_cps2_dead = cps_rc == 0 && (static_cast<int>(cs.state) == 0 || static_cast<int>(cs.state) == 3);
		if (cps_rc == 0 && cs.state == 1 && cs.timer >= 1)
			bhf_k_t = static_cast<int>(cs.timer);
	}
	return (bhf_k_t >= 1 && bhf_k_t + 1 < k) ? bhf_k_t + 1 : k; // the raw clock's own +1 stays
}
} // namespace nova::econ

// ---------------------------------------------------------------- claimed mates near me that may join my crew (BYC): see econ.h.
// Reached only with BYC_BITS set.
namespace nova::econ::crew_bypass
{
namespace
{
namespace E = nova::econ;
// a mate near me that is walking (not engaged, not fighting, not channelling) toward a claim at least BYC_FAR away: the far claim's
// tile distance, else -1
int far_claim(const Body& a, int cg)
{
	const int s = a.slot;
	if (s < 0 || s >= E::TM.n || s >= 8 || s == E::my_slot() || cg < 0 || cg >= M.ng)
		return -1;
	if (E::TM.busy[static_cast<std::size_t>(s)] || a.channeling() || comms::ckind(s) == 4 || cheb(a.pos, W.me.pos) > BYC_TAB[3])
		return -1;
	const int d = cheb(a.pos, M.groups[static_cast<std::size_t>(cg)].anchor);
	return d >= BYC_TAB[2] ? d : -1;
}
} // namespace
int count()
{
	int n = 0;
	for (const auto& a : W.allies)
		if (a.slot >= 0 && a.slot < E::TM.n && a.slot < 8 && far_claim(a, E::TM.claim[static_cast<std::size_t>(a.slot)]) >= 0)
			++n;
	return n;
}
bool ok(int s, int gi, int cg)
{
	const Body* a = W.ally_by_slot(s);
	if (!a || gi < 0 || gi >= M.ng)
		return false;
	const int dc = far_claim(*a, cg);
	if (dc < 0 || dc <= cheb(a->pos, M.groups[static_cast<std::size_t>(gi)].anchor))
		return false;
	fired_add();
	return true;
}
void fired_add()
{
	asm volatile("");
}
} // namespace nova::econ::crew_bypass
