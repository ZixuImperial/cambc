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
// v864 RXLS1: list the group for the expiry pass (deduped by one byte per group)
__attribute__((noinline)) void oxf_push(const GroupMem& m)
{
	const auto a = reinterpret_cast<std::uintptr_t>(&m), b0 = reinterpret_cast<std::uintptr_t>(mem.data());
	const std::size_t gi = a >= b0 ? (a - b0) / sizeof(GroupMem) : static_cast<std::size_t>(-1);
	if (oxf_rin.size() != gmem_size(mem))
		oxf_rin.assign(gmem_size(mem), 0);
	if (gi < oxf_rin.size() && gi < mem.size() && &mem[gi] == &m && !oxf_rin[gi])
	{
		oxf_rin[gi] = 1;
		oxf_rl.push_back(static_cast<int>(gi));
	}
}
// The one way a group becomes respawning: it pays at `at`. Keeps the expiry bound below every respawn_at.
__attribute__((always_inline)) inline void mark_respawn(GroupMem& m, int at)
{
	m.status = GS_RESPAWN;
	m.respawn_at = at;
	if (oxf_l2)
		oxf_push(m); // v864 RXLS1: the expiry pass walks only listed groups
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
// b2386 RPG bit 2 (callers read the flag): slot s posts a fight code (in a fight / retreat 4, coming 5): not free crew.
__attribute__((noinline)) bool rpg_fight_code(int s)
{
	const int k = comms::ckind(s);
	return k == 4 || k == 5;
}
// b2386 RPG bit 2: free_near_mask and free_near without the mates posting a fight code.
__attribute__((noinline)) std::uint32_t rpg_free_near_mask()
{
	std::uint32_t m = 0;
	for (const auto& a : W.allies)
		if (a.slot >= 0 && a.slot < TM.n && a.slot < 8 && (!a.channeling() || recall_frees_channel(a)) && cheb(a.pos, W.me.pos) <= 8 && !rpg_fight_code(a.slot))
			m |= 1u << a.slot;
	return m;
}
// The slots free_near() counts (visible, within 8, not channelling unless a recall frees it); crew_for's pass 0 takes `extra` of
// these only, not the best tanks among every free body (otherwise some picks would be unseen mates).
std::uint32_t free_near_mask()
{
	return rpg_free_near_mask();
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
			if (pass == 0 && rpg_fight_code(s))
				continue;
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
// v8xx SWG bit 1 (b2395, spec_swg_1113, owner replay 01a1d410): a big wolf pack is cleared from its rim. Monsters hit the nearest
// champion in their reach and do not chase (GR:192, :209), so only the attackers whose reach covers the crew's stand tile hit it.
inline bool swg_pack(const GroupI& g) { return g.n_wolf >= 12 && g.n_elk + g.n_golem + g.n_mono == 0; }
// SWG fuel trim (b2395, Aggression's adaptation after swg 15007's cut-offs 3.4x): one cached count grid per pack, 'living wolves whose
// reach covers this tile' over the group box + reach, rebuilt only when a member is seen to die or come back; the stand-off tile is
// cached and re-picked only after a rebuild, when it is taken, or when a seen foe's next-turn reach covers it.
struct SwgGrid
{
	int gi = -1, x0 = 0, y0 = 0, w = 0, h = 0;
	std::vector<std::uint8_t> cnt, dead; // dead: per member index, seen dead (unseen keep their last state)
	int sx = -1, sy = -1, sk = 0, pick_r = -1000; // the cached stand-off tile (-1 none) and its count
	int alive = 0; // attackers counted in cnt
	bool picked = false;
};
inline SwgGrid swg_gt[4]; // fuel trim: one grid per pack this body has targeted (slot gi & 3), so a switch back reuses it
inline const SwgGrid* swg_have(int gi)
{
	const SwgGrid& q = swg_gt[gi & 3];
	return q.gi == gi ? &q : nullptr;
}
inline int swg_cnt_at(const SwgGrid& s, vec2 t)
{
	const int x = t.x - s.x0, y = t.y - s.y0;
	return (x < 0 || y < 0 || x >= s.w || y >= s.h) ? 0 : s.cnt[static_cast<std::size_t>(y * s.w + x)];
}
// The grid for pack gi, updated this turn (callers read the flag and swg_pack first). s.gi != gi: box too large.
__attribute__((noinline)) SwgGrid& swg_grid(int gi)
{
	SwgGrid& s = swg_gt[gi & 3];
	const GroupI& g = M.groups[static_cast<std::size_t>(gi)];
	bool rebuild = false;
	if (s.gi != gi)
	{
		const int pad = std::max(1, g.reach_max), w = g.bx1 - g.bx0 + 1 + 2 * pad, h = g.by1 - g.by0 + 1 + 2 * pad;
		if (w <= 0 || h <= 0 || w * h > 1600)
		{
			s.gi = -1;
			return s;
		}
		s.gi = gi;
		s.x0 = g.bx0 - pad;
		s.y0 = g.by0 - pad;
		s.w = w;
		s.h = h;
		s.dead.assign(g.members.size(), 0);
		rebuild = true;
	}
	const int pad = std::max(1, g.reach_max);
	// one wolf's reach square, added (+1) or removed (-1)
	auto bump = [&](const CampI& c, int sgn) {
		s.alive += sgn;
		const int cx = c.pos.x - s.x0, cy = c.pos.y - s.y0;
		for (int dy = -pad; dy <= pad; ++dy)
		{
			std::uint8_t* row = &s.cnt[static_cast<std::size_t>((cy + dy) * s.w + cx - pad)];
			for (int k = 0; k <= 2 * pad; ++k)
				row[k] = static_cast<std::uint8_t>(row[k] + sgn); // counts stay in 0..(2 pad + 1)^2
		}
	};
	if (rebuild)
	{
		s.cnt.assign(static_cast<std::size_t>(s.w * s.h), 0);
		s.alive = 0;
		for (std::size_t j = 0; j < g.members.size(); ++j)
		{
			const auto& c = M.camps[static_cast<std::size_t>(g.members[j])];
			if (c.attacks() && !s.dead[j])
				bump(c, 1);
		}
		s.picked = false;
	}
	else
		for (std::size_t j = 0; j < g.members.size(); ++j)
		{
			const auto& c = M.camps[static_cast<std::size_t>(g.members[j])];
			if (!bbget(W.vis, c.pos))
				continue;
			const std::uint8_t d = bbget(W.occ_camps, c.pos) ? 0 : 1;
			if (d == s.dead[j])
				continue;
			s.dead[j] = d; // a seen death (or a respawn): only that wolf's square changes
			if (c.attacks())
				bump(c, d ? -1 : 1);
			s.picked = false;
		}
	return s;
}
inline bool swg_foe_covers(vec2 t)
{
	for (const auto& e : W.enemies)
		if (cheb(e.pos, t) <= combat::foe_next_turn_reach(e)) // RC C1249b
			return true;
	return false;
}
// The cached tile still holds: picked since the last rebuild, and (a tile) mine or free and out of a seen foe's reach; 'none' holds 2 rounds.
inline bool swg_stand_valid(const SwgGrid& s)
{
	if (!s.picked)
		return false;
	if (s.sx < 0)
		return now() - s.pick_r < 2;
	const vec2 t{ s.sx, s.sy };
	return (t == W.me.pos || mv::free_tile(t)) && !swg_foe_covers(t);
}
// Re-pick: the fewest wolves (1..SWG_K) first, the nearest tile within that count. One pass over the count array keeps the best 8
// (count, distance) cells; only those get the map, occupancy and foe tests (fuel trim).
__attribute__((noinline)) void swg_pick_stand(SwgGrid& s)
{
	s.picked = true;
	s.pick_r = now();
	s.sx = -1;
	const vec2 me = W.me.pos;
	const int kmax = SWG_TAB[2];
	int key[8], ix[8], n = 0;
	for (int y = 0; y < s.h; ++y)
	{
		const std::uint8_t* row = &s.cnt[static_cast<std::size_t>(y * s.w)];
		const int ty = s.y0 + y, dy = ty > me.y ? ty - me.y : me.y - ty;
		for (int x = 0; x < s.w; ++x)
		{
			const int c = row[x];
			if (c == 0 || c > kmax)
				continue;
			const int tx = s.x0 + x, dx = tx > me.x ? tx - me.x : me.x - tx;
			const int kk = c * 4096 + std::max(dx, dy);
			if (n == 8 && kk >= key[7])
				continue;
			int i = n < 8 ? n++ : 7;
			while (i > 0 && key[i - 1] > kk)
			{
				key[i] = key[i - 1];
				ix[i] = ix[i - 1];
				--i;
			}
			key[i] = kk;
			ix[i] = y * s.w + x;
		}
	}
	for (int i = 0; i < n; ++i)
	{
		const vec2 t{ s.x0 + ix[i] % s.w, s.y0 + ix[i] / s.w };
		if (!inb(t) || (!(t == me) && !mv::free_tile(t)) || swg_foe_covers(t))
			continue;
		s.sx = t.x;
		s.sy = t.y;
		s.sk = key[i] / 4096;
		return;
	}
}
// The fewest attackers in reach of a free tile (not blocked, not a camp tile) that has an attacker within the crew's attack range
// (3 ranged, 1 melee); static per group (wolf-only: every attacker at reach_max); 0 = unknown (map not done, low fuel, box too big).
__attribute__((noinline)) int swg_rim_k(const GroupI& g, bool ranged)
{
	// fuel trim (cutprof: this scan sat on 10 of 23 cut turns): the same count grid as the stand-off (row increments, no prefix sums),
	// then the cheapest walkable free tile by count passes 1..8 (array reads first, the map tests only on matching tiles); once per pack.
	static std::vector<std::uint8_t> kk; // per group: 0 unknown, 255 none within 8
	static std::vector<std::uint8_t> cnt;
	if (!ranged || !M.done() || g.idx < 0 || g.idx >= M.ng)
		return 0;
	if (kk.size() != static_cast<std::size_t>(M.ng))
		kk.assign(static_cast<std::size_t>(M.ng), 0);
	std::uint8_t& v = kk[static_cast<std::size_t>(g.idx)];
	if (v == 0)
	{
		const int pad = std::max(1, g.reach_max);
		const int x0 = g.bx0 - pad, y0 = g.by0 - pad, w = g.bx1 - g.bx0 + 1 + 2 * pad, h = g.by1 - g.by0 + 1 + 2 * pad;
		if (w <= 0 || h <= 0 || w * h > 1600)
		{
			v = 255;
			return 0;
		}
		if (fuel() < static_cast<long>(SWG_TAB[3]) + 6L * w * h + 200L * static_cast<long>(g.members.size()))
			return 0;
		cnt.assign(static_cast<std::size_t>(w * h), 0);
		for (int ci : g.members)
		{
			const auto& c = M.camps[static_cast<std::size_t>(ci)];
			if (!c.attacks())
				continue;
			const int cx = c.pos.x - x0, cy = c.pos.y - y0;
			for (int dy = -pad; dy <= pad; ++dy)
			{
				std::uint8_t* row = &cnt[static_cast<std::size_t>((cy + dy) * w + cx - pad)];
				for (int k = 0; k <= 2 * pad; ++k)
					++row[k]; // at most (2 pad + 1)^2 wolves reach one tile: no overflow
			}
		}
		int best = 9; // one pass: the map tests only on a cell that beats the best so far (none within 8: 255)
		for (int y = 0; y < h && best > 1; ++y)
		{
			const std::uint8_t* row = &cnt[static_cast<std::size_t>(y * w)];
			for (int x = 0; x < w; ++x)
			{
				const int c = row[x];
				if (c == 0 || c >= best)
					continue;
				const vec2 s{ x0 + x, y0 + y };
				if (inb(s) && !bbget(M.block, s) && !bbget(M.camp_tiles, s) && dfget(M.f_home, s) != UNREACH) // RC C1249: walkable stands only
					best = c;
			}
		}
		v = static_cast<std::uint8_t>(best <= 8 ? best : 255);
	}
	return v >= 255 ? 0 : v;
}
// SWG bit 1: a one-body crew's kit is ranged (RC C1249: the body's own kit, kit_of(P.type[slot]), not mine): the built team members
// with the crew's numbers (dps1, budget) are all ranged; none or a melee one = melee.
__attribute__((noinline)) bool swg_lone_ranged(const Crew& c)
{
	if (c.n != 1)
		return false;
	bool any = false;
	for (int s = 0; s < TM.n && s < 8; ++s)
	{
		if ((tml_pend >> s) & 1u)
			continue;
		const Member& x = TM.m[static_cast<std::size_t>(s)];
		if (x.dps1 != c.dps1 || x.budget != c.budget[0])
			continue;
		if (!kit_of(P.type[static_cast<std::size_t>(s)]).ranged)
			return false;
		any = true;
	}
	return any;
}
// SWG bit 1: the rim price of a pack's clear (callers read SWG_ON(1) first): k attackers hit for the whole clear time tc; -1 = not
// a pack or k unknown (live's price stands).
inline float swg_rim_dmg(const GroupI& g, const Crew& c, float tc)
{
	if (!swg_pack(g) || !swg_lone_ranged(c)) // Aggression 13 Nov: ranged kits only (melee rim k ~10: the pack stays at live's price)
		return -1.0f;
	const SwgGrid* sg = swg_have(g.idx);
	const int k = (sg && sg->picked && sg->sx >= 0) ? sg->sk : swg_rim_k(g, true); // the cached stand tile's k (trim)
	return k > 0 ? static_cast<float>(k) * g.str_max * tc : -1.0f;
}
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
// b2429 SHV (callers read SHV_ON first): per group, static once M is done (heavy groups only: monolith / golem). Bits 0-1: 1 a member
// within 3 (ranged reach, GR:254) of one of our spawn tiles, 2 within 1 (melee); bits 4-7: our spawn tiles within 3 of a member (cap 15);
// bits 8-11: those within 1 (cap 15).
__attribute__((noinline)) int shv_class(const GroupI& g)
{
	static std::vector<short> c;
	if (!M.done() || g.idx < 0 || g.idx >= M.ng)
		return 0;
	if (c.size() != static_cast<std::size_t>(M.ng))
		c.assign(static_cast<std::size_t>(M.ng), -1);
	auto& v = c[static_cast<std::size_t>(g.idx)];
	if (v < 0)
	{
		int b = 0, n3 = 0, n1 = 0;
		if (g.n_mono + g.n_golem > 0)
			for (int x = std::max(0, g.bx0 - 3); x <= g.bx1 + 3; ++x)
				for (int y = std::max(0, g.by0 - 3); y <= g.by1 + 3; ++y)
				{
					const vec2 t{ x, y };
					if (!inb(t) || !bbget(M.my_spawn, t))
						continue;
					int d = 99;
					for (int ci : g.members)
						d = std::min(d, cheb(t, M.camps[static_cast<std::size_t>(ci)].pos));
					if (d <= 3)
					{
						b |= 1;
						++n3;
					}
					if (d <= 1)
					{
						b |= 2;
						++n1;
					}
				}
		v = static_cast<short>(b | (std::min(n3, 15) << 4) | (std::min(n1, 15) << 8));
	}
	return v;
}
// SHV bit 1 (RC C1392): the crew's camp damage is 0 only if (i) every crew body has a spawn tile of ours in reach of a member to stand on
// (melee class: n tiles within 1; reach-3 class: n tiles within 3 and a ranged body to hit from there), and (ii) one round of every
// attacker's hits on the tank (str_sum, camp damage units) stays under the tank's budget (its health less the bail margin; tank_b).
inline bool shv_crew_reach(const GroupI& g, int n, int n_melee, float tank_b)
{
	if (g.contest > 0.45f || n <= 0 || g.str_sum >= tank_b)
		return false;
	const int k = shv_class(g);
	return ((k & 2) != 0 && ((k >> 8) & 15) >= n) || ((k & 1) != 0 && ((k >> 4) & 15) >= n && n > n_melee);
}
// SAX (econ_flags.h): a monolith group with 2+ attacker camps. sax_siege_ok (callers read SAX_ON(5) first) admits it to the siege
// recruit beside live's n_att == 1 groups: bit 1 any such group, bit 4 one in our half.
inline bool sax_mono2(const GroupI& g) { return g.n_mono > 0 && g.n_att >= 2; }
inline bool sax_siege_ok(const GroupI& g) { return static_cast<bool>(sax_mono2(g)); }
bool heavy_multi_trip_ok(const GroupI& g, const GroupMem& m)
{
	return g.access == ACC_WALK && g.d_home != UNREACH && (static_cast<int>(g.d_home) > g.reach_max + 3 || nsg_class(g) || (siege_map() && sax_mono2(g))) && g.contest * 100.0f <= static_cast<float>(HE_CONT_X100) && now() - m.enemy_seen >= HE_QUIET;
}
inline bool recall_frees_channel(const Body& a)
{
	return (a.state & ST_RECALL) != 0 && (a.state & (ST_TRIBUTE | ST_TELEPORT)) == 0 && a.slot < 8 && rcm_rcr[static_cast<std::size_t>(a.slot)] == now() && rcm_rc[static_cast<std::size_t>(a.slot)] >= RCM_TAB[2];
}
__attribute__((noinline)) int rpg_free_near()
{
	int n = 0;
	for (const auto& a : W.allies)
		if (a.slot >= 0 && a.slot < TM.n && (!a.channeling() || recall_frees_channel(a)) && cheb(a.pos, W.me.pos) <= 8 &&
			TM.claim[static_cast<std::size_t>(a.slot)] < 0 && !rpg_fight_code(a.slot))
			++n;
	n += nova::econ::crew_bypass::count();
	return n;
}
int free_near()
{
	return rpg_free_near();
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
