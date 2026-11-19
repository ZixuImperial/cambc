// combat_foes.cc: The Foe record, its memo and unreachable foes.
#include "combat_internal.h"
namespace nova::combat {
namespace foe_model
{
namespace {
struct FocKey0
{
	const Kit* kit;
	std::uint32_t h, type, str, foc, hp, maxhp;
	int range, cd0, cd1;
	bool stunned;
	bool s2; // reach reads the turn count
	std::uint32_t mq; // the emblem factors foe_of reads (0 at flag 0)
	bool operator==(const FocKey0& o) const
	{
		return kit == o.kit && h == o.h && type == o.type && str == o.str && foc == o.foc && hp == o.hp && maxhp == o.maxhp && range == o.range
			&& cd0 == o.cd0 && cd1 == o.cd1 && stunned == o.stunned && s2 == o.s2 && mq == o.mq;
	}
};
struct FocKey : FocKey0
{
	int dn; // horizon_dps reads the distance to our nearest body and a second body near it (0 when off)
	bool two;
	int pass; // the PASS counts (DpsPass::pack; 0 when off)
	std::uint32_t inc; // Heart's incoming damage a turn (bit pattern; 0 when off)
	bool operator==(const FocKey& o) const
	{
		return FocKey0::operator==(o) && dn == o.dn && two == o.two && pass == o.pass && inc == o.inc;
	}
};
template <class Key>
struct FocEntT
{
	bool ok = false;
	Key k{};
	float dps = 0, dps_fc = 0, burst = 0, dps_dmg = 0;
	int reach = 2;
	bool melee = true;
};
using FocEnt = FocEntT<FocKey>;
using FocEnt0 = FocEntT<FocKey0>;
struct RecSeen
{
	std::uint32_t h;
	int first, last;
};
std::array<RecSeen, 16> rec_seen{};
int rec_n = 0;
struct StillSeen
{
	std::uint32_t h;
	vec2 pos;
	int since, last;
};
std::array<StillSeen, 16> still_seen{};
int still_n = 0;
// The key fields both memos read: everything foe_of_calc depends on at flag 0.
static __attribute__((always_inline)) inline void foe_memo_key_fill(FocKey0& k, const Body& e)
{
	const bool mh = e.kit->missing_hp_bonus;
	k.kit = e.kit;
	k.h = e.h;
	k.type = static_cast<std::uint32_t>(e.type);
	k.str = __builtin_bit_cast(std::uint32_t, e.str);
	k.foc = __builtin_bit_cast(std::uint32_t, e.foc);
	k.hp = mh ? __builtin_bit_cast(std::uint32_t, e.hp) : 0u;
	k.maxhp = mh ? __builtin_bit_cast(std::uint32_t, e.maxhp) : 0u;
	k.range = e.range;
	k.cd0 = foe_cd(e, 0);
	k.cd1 = foe_cd(e, 1);
	k.stunned = e.stunned;
	k.s2 = static_cast<bool>(burst::bh81_stun2(e)); // the lost-turn model's answer changes with the turn order, so the memo keys on it
	k.mq = mu::bits != 0 ? static_cast<std::uint32_t>(e.mc) << 8 | W.me.mc : 0u; // both emblem codes
}
// A memo hit: the stored values on e's current place. KEEP_DMG: only the DPS memo hands dps_dmg back.
template <bool KEEP_DMG, class Ent>
static __attribute__((always_inline)) inline Foe foe_from_memo(const Ent& c, const Body& e, int idx)
{
	Foe f;
	f.idx = idx;
	f.pos = e.pos;
	f.ehp = eff_hp(e);
	f.gems = static_cast<int>(e.gems);
	f.melee = c.melee;
	f.dps = c.dps;
	if constexpr (KEEP_DMG)
		f.dps_dmg = c.dps_dmg;
	f.dps_fc = c.dps_fc;
	f.burst = c.burst;
	f.reach = c.reach;
	return f;
}
template <class Ent, class Key>
static __attribute__((always_inline)) inline void foe_memo_store(Ent& c, const Key& k, const Foe& f)
{
	c.ok = true;
	c.k = k;
	c.dps = f.dps;
	c.dps_dmg = f.dps_dmg;
	c.dps_fc = f.dps_fc;
	c.burst = f.burst;
	c.reach = f.reach;
	c.melee = f.melee;
}
__attribute__((noinline)) Foe foe_of_memo(const Body& e, int idx)
{
	if (!e.kit || !e.kit->valid || (e.ally && e.h == W.me.h))
		return foe_of_calc(e, idx);
	static std::array<FocEnt0, 16> foc_tab{};
	FocKey0 k;
	foe_memo_key_fill(k, e);
	FocEnt0& c = foc_tab[static_cast<std::size_t>(e.h & 15u)];
	if (c.ok && c.k == k)
		return foe_from_memo<false>(c, e, idx);
	const Foe f = foe_of_calc(e, idx);
	foe_memo_store(c, k, f);
	return f;
}
Foe foe_of_calc(const Body& e, int idx) // the flag-0 foe_of
{
	Foe f;
	f.idx = idx;
	f.pos = e.pos;
	f.ehp = eff_hp(e);
	f.gems = static_cast<int>(e.gems);
	const Kit* kp = e.kit;
	if (!kp || !kp->valid)
	{
		f.dps = 50.0f;
		f.dps_dmg = 50.0f; // an unknown kit keeps its 50 in the damage sums
		f.dps_fc = 50.0f;
		f.burst = 60.0f;
		f.reach = std::max(2, e.range + 1);
		f.melee = e.range <= 1;
		return f;
	}
	const Kit& k = *kp;
	const float pm = kit_rules::passive_mult(e);
	f.melee = !k.ranged;
	f.dps = horizon_dps(e, false);
	f.dps_fc = f.dps; // enemy bodies with the live-duel refit of their kit
	{
		// The refit's damage factor per kit is a constant: computed once (fuel).
		static std::array<float, 13> mult{};
		static bool mult_ok = false;
		if (!mult_ok)
		{
			for (int t = 0; t < 13; ++t)
			{
				const auto ct = static_cast<cambc::champion_type>(t);
				mult[static_cast<std::size_t>(t)] = std::exp(0.25f * (kit_rules::kit_foe_value(ct) - kit_rules::kit_fight_value(ct)));
			}
			mult_ok = true;
		}
		const int t = static_cast<int>(e.type);
		f.dps_fc = f.dps * (t >= 0 && t < 13 ? mult[static_cast<std::size_t>(t)] : 1.0f);
	}
	// Next-turn reach and burst from the abilities that are ready.
	const bool reset = k.slot_reset >= 0 && kit_rules::slot_ready(e, k.slot_reset);
	const bool dash = k.slot_dash >= 0 && kit_rules::slot_ready(e, k.slot_dash);
	float burst = e.str * (reset ? 2.0f : 1.0f);
	// one successful cast per turn (GameRules): the basic hit plus the best ONE of the reset's second
	// hit, the dash landing and the ready spells.
	float cast1 = reset ? e.str : 0.0f;
	const bool ocb2 = OCB_ON(2);
	if (ocb2)
		burst = e.str;
	int reach = k.ranged ? e.range + (reset ? 1 : 0) : 2;
	if (dash)
	{
		reach = std::max(reach, (k.ranged ? e.range : 1) + 2 + (k.ranged ? 0 : 1));
		if (k.dash_mod > 0)
		{
			if (!(ocb2))
				burst += k.dash_mod * e.foc;
			cast1 = std::max(cast1, k.dash_mod * e.foc);
		}
	}
	auto spell = [&](int slot, float mod, float range, bool excl, float radius)
	{
		if (slot < 0 || !kit_rules::slot_ready(e, slot))
			return;
		if (!(ocb2))
			burst += mod * e.foc;
		cast1 = std::max(cast1, mod * e.foc);
		reach = std::max(reach, static_cast<int>(range + radius) + (excl ? 0 : 1));
	};
	spell(k.slot_dmg, k.dmg_mod, k.dmg_range, k.dmg_excl, 0.0f);
	spell(k.slot_cc, k.cc_mod, k.cc_range, k.cc_excl, 0.0f);
	spell(k.slot_aoe, k.aoe_mod, k.aoe_range, k.aoe_excl, k.aoe_radius);
	if (ocb2)
		burst += cast1;
	f.burst = burst * pm;
	if (mu::bits != 0 && mu::on(mu::B_FOEOF)) // the foe's emblem factor on its hits on me
	{
		const float q = mu::foe_in(e);
		f.dps *= q;
		f.dps_dmg *= q; // the damage call takes the same factor
		f.dps_fc *= q;
		f.burst *= q;
	}
	if (e.stunned && !e.ally)
	{
		f.reach = burst::stunned_foe_reach(e, reach);
		f.burst = burst::stunned_foe_burst(e, f.burst);
		return f;
	}
	f.reach = e.stunned ? (std::max(0, reach - 1)) : reach;
	return f;
}
} // namespace
// An enemy we cannot engage: on its own spawn (we cannot step there) and out of our reach. Foe e on its spawn, beyond my range and
// spells: a ready area spell reaches it, or a walk (melee only: ranged walk and attack share one allowance) and a ready dash bring
// me to a tile off its spawn that hits it.
static bool can_get_to_foe(const Body& e)
{
	if (!W.me.kit)
		return false;
	const Kit& k = *W.me.kit;
	const int d = cheb(e.pos, W.me.pos);
	if (k.slot_aoe >= 0 && k.aoe_mod > 0 && !W.cast && ready(k.slot_aoe) && d <= static_cast<int>(k.aoe_range + k.aoe_radius))
		return true;
	const int steps = (!k.ranged && W.can_move() ? 1 : 0) + (k.slot_dash >= 0 && !W.cast && ready(k.slot_dash) ? static_cast<int>(k.dash_range) : 0);
	if (steps == 0 || d > W.me.range + steps)
		return false;
	const int r = W.me.range;
	for (int dx = -r; dx <= r; ++dx)
		for (int dy = -r; dy <= r; ++dy)
		{
			const vec2 t{ e.pos.x + dx, e.pos.y + dy };
			if (inb(t) && cheb(t, W.me.pos) <= steps && !bbget(M.enemy_spawn, t) && mv::free_tile(t))
				return true;
		}
	return false;
}
bool unreachable(const Body& e)
{
	const int reach = std::max(W.me.range, W.me.kit ? static_cast<int>(std::max(W.me.kit->dmg_range, W.me.kit->cc_range)) : 0);
	return bbget(M.enemy_spawn, e.pos) && cheb(e.pos, W.me.pos) > reach && !(can_get_to_foe(e)/*BH80F:32*/);
}
namespace {
// Foe h's row of a small per-foe table: fresh = a new row (h set, the rest the caller's). A full table reuses its stalest row.
template <class Row, std::size_t N>
static Row& find_or_add_seen_row(std::array<Row, N>& tab, int& n, std::uint32_t h, bool& fresh)
{
	Row* r = nullptr;
	for (int i = 0; i < n; ++i)
		if (tab[static_cast<std::size_t>(i)].h == h)
			r = &tab[static_cast<std::size_t>(i)];
	fresh = r == nullptr;
	if (r)
		return *r;
	if (n < static_cast<int>(N))
		r = &tab[static_cast<std::size_t>(n++)];
	else
	{
		r = &tab[0];
		for (auto& x : tab)
			if (x.last < r->last)
				r = &x;
	}
	r->h = h;
	return *r;
}
} // namespace
bool fresh_recall(const Body& e)
{
	if (!(e.state & ST_RECALL) || (e.state & ST_TRIBUTE))
		return false;
	bool fresh = false;
	RecSeen& r = find_or_add_seen_row(rec_seen, rec_n, e.h, fresh);
	if (fresh || r.last < W.round - 1)
		r.first = W.round; // a new recall (not seen last round)
	r.last = W.round;
	return r.first == W.round;
}
int still_rounds(const Body& e)
{
	bool fresh = false;
	StillSeen& r = find_or_add_seen_row(still_seen, still_n, e.h, fresh);
	if (fresh || r.pos != e.pos || r.last < W.round - 1)
	{
		r.pos = e.pos;
		r.since = W.round;
	}
	r.last = W.round;
	return W.round - r.since;
}
namespace {
__attribute__((noinline)) float group_pack_factor_slow(int gi)
{
	const vec2 at = M.groups[static_cast<std::size_t>(gi)].anchor;
	int n = 0;
	for (int s = 0; s < std::min(P.n, static_cast<int>(comms::CLAIM_SLOTS)); ++s)
	{
		if (s == P.my_slot)
			continue;
		// Where that body is: its position when I see it, else the group it is heading to.
		vec2 p{ -1, -1 };
		for (const auto& al : W.allies)
			if (al.slot == s)
				p = al.pos;
		if (p.x < 0)
		{
			const int cg = comms::cgroup(s);
			if (cg >= 0 && cg < M.ng)
				p = M.groups[static_cast<std::size_t>(cg)].anchor;
		}
		if (p.x >= 0 && cheb(p, at) <= 8)
			++n;
	}
	return 1.0f + 0.25f * static_cast<float>(std::min(n, 2));
}
} // namespace
} // namespace foe_model
namespace {
__attribute__((always_inline)) inline Foe foe_of(const Body& e, int idx)
{
	return foe_model::foe_of_memo(e, idx);
}
// CB3 bits 32/64 (R1, R2): a stunned foe's record without the stun: a stun costs one turn (INT:35), so a remembered sighting, a
// several-turn channel and a chaser's reach read its full kit.
static __attribute__((noinline)) Foe foe_of_unstunned(const Body& e, int idx)
{
	Body u = e;
	u.stunned = false;
	return foe_model::foe_of_memo(u, idx);
}
} // namespace
// The first early-out test inline at the call site (a call and frame a turn saved), the rest out of line.
__attribute__((always_inline)) float group_pack_factor(int gi)
{
	if (gi < 0 || gi >= M.ng || !fight_map())
		return 1.0f;
	return foe_model::group_pack_factor_slow(gi);
}
} // namespace nova::combat
