// move_turn_order.cc: Tie priorities and this round's and next round's turn order.
#include "move_internal.h"
namespace nova::mv {
// HP tier (edges .75/.50/.25) with FTR_TAB[2] points of hysteresis around the previous tier t0 (t0 < 0: none); q = tier + 1 while
// carrying gems, capped at 4.
int hp_order_tier(float frac, int t0)
{
	auto tier = [](float f) { return f >= 0.75f ? 0 : f >= 0.5f ? 1 : f >= 0.25f ? 2 : 3; };
	if (t0 < 0)
		return tier(frac);
	const float h = static_cast<float>(FTR_TAB[2]) * 0.01f;
	const int worse = tier(frac + h), better = tier(frac - h); // a tier changes only past its edge by h
	return t0 < worse ? worse : t0 > better ? better : t0;
}

// q = carrying + 2 k, k = 13 - distance to the nearest visible foe once one is within 12 (else 0): the body nearest the enemy acts
// LAST, carriers after non-carriers; overrides stay first.
int nearest_foe_acts_last_q(vec2 p, std::uint32_t gems)
{
	int dn = 99;
	for (const auto& e : W.enemies)
		dn = std::min(dn, cheb(e.pos, p));
	const int k = dn <= 12 ? 13 - dn : 0;
	return (gems > 0 ? 1 : 0) + 2 * k;
}

int turn_order_base()
{
	if (P.my_slot < 0)
		return 0;
	const int base = P.prio[static_cast<std::size_t>(P.my_slot)];
	// Once a round: my state is fixed during my turn; the tier carries over between rounds for the hysteresis.
	static int fq_round = -1000;
	static int ft = 0, fq = 0;
	if (fq_round != W.round)
	{
		fq_round = W.round;
		if (!W.alive)
			ft = fq = 0;
		else
		{
			ft = hp_order_tier(W.me.frac(), ft);
			fq = nearest_foe_acts_last_q(W.me.pos, W.me.gems);
		}
	}
	return base - 7 * fq;
}

// Within our team the higher priority acts first, then the lower slot.
NOVA_INLINE bool acts_before(int prio_a, int slot_a, int prio_b, int slot_b)
{
	return prio_a > prio_b || (prio_a == prio_b && slot_a < slot_b);
}

static int toh_on_round = -1000, toh_on_val = 0; // My next-round value once this turn has decided it.
int tie_prio(int s)
{
	if (s < 0 || s >= P.n || s >= 8)
		return 0;
	if (s == P.my_slot)
		return turn_order_base();
	static int tp_round = -1000;
	static std::array<int, 8> tp{};
	static std::array<bool, 8> tp_ok{};
	static int my_cur = 0;
	if (tp_round != W.round)
	{
		tp_round = W.round;
		tp_ok.fill(false);
		std::int32_t v = 0;
		my_cur = cambc::detail::sdk_bc_champion_priority(static_cast<std::uint32_t>(cambc::detail::cached_my_champion), 0, &v) == 0 ? v : 0;
		my_cur = PRA_DEC(my_cur); // Our values decode.
	}
	const auto si = static_cast<std::size_t>(s);
	if (!tp_ok[si])
	{
		tp_ok[si] = true;
		const int base = P.prio[si];
		tp[si] = base;
		if (const Body* b = W.ally_by_slot(s))
		{
			std::int32_t vn = 0, vc = 0;
			if (b->h != 0 && cambc::detail::sdk_bc_champion_priority(b->h, 1, &vn) == 0 &&
				cambc::detail::sdk_bc_champion_priority(b->h, 0, &vc) == 0)
			{
				vn = PRA_DEC(vn); // Our values decode.
				vc = PRA_DEC(vc);
				const bool acted = acts_before(vc, s, my_cur, P.my_slot); // ahead of me in this round's queue
				const int d = base - vn; // An FTR value is base - 7 q, q 0..4; anything else is an override.
				const bool band = d >= 0 && d % 7 == 0 && d / 7 <= (25);
				if (acted || !band || (RCB_ON(8) && b->channeling())) // v699 RCB bit 8 PK2: a channelling mate returns before setting its value
					tp[si] = vn; // its set value stands (or an override we cannot predict)
				else
				{
					// It sets its value at its own turn from its own HP and gems (on every body): recompute it.
					const int q0 = d / 7, t0 = (b->gems > 0 && q0 >= 1) ? q0 - 1 : std::min(3, q0);
					tp[si] = base - 7 * (nearest_foe_acts_last_q(b->pos, b->gems));
				}
			}
		}
	}
	return tp[si];
}

namespace {
// This round's and next round's order, once a round.
struct Toh
{
	int round = -1000;
	std::uint32_t me = 0; // Built for this body (each champion has its own bot instance, GameRules.md:409: the test only guards a stale build).
	bool en_now = false, en_next = false; // the enemy team starts this round / the next
	int ne = 0, ra = 0, ran = 0;          // roster size; my rank in our team now / next round
	std::array<std::uint32_t, 8> eh{};
	std::array<std::int8_t, 8> er{}, ern{}; // roster foe k's rank in its team now / next round
	unsigned done = 0; // The foes whose er, ern are filled since the last build (first query fills).
};
Toh toh;
std::array<std::int32_t, 8> toh_ec{}, toh_en{}; // each roster foe's last read priority (now / next round), kept while unseen
std::array<int, 8> toh_last{};                  // each of our slots' next-round value as last built
std::array<int, 8> toh_fb{};                    // this round's fallback current value per slot (last round's next-round value)
std::array<int, 8> toh_ucr{}, toh_ucv{}; // Our slots' this-round priority.
std::array<std::uint32_t, 8> toh_uch{};
// How many of v[0..n) rank ahead of v[i]: a higher value, or an equal one that `first` says goes first.
template <class V, class Tie> NOVA_INLINE int rank_of(const V& v, int n, std::size_t i, Tie first)
{
	int r = 0;
	for (int j = 0; j < n; ++j)
	{
		const auto uj = static_cast<std::size_t>(j);
		r += (v[uj] > v[i] || (v[uj] == v[i] && first(uj))) ? 1 : 0;
	}
	return r;
}
} // namespace


bool takes_tie(const Body& b)
{
	// Camp ties go to the body that acts first this round: within our team the higher priority, then the lower slot. Against enemies
	// the order alternates by round, so assume we are the one hit. An enemy that acts before me this round takes the tie (the camp hits
	// the tied body that acted first in the round before its turn).
	if (!b.ally || b.slot < 0 || P.my_slot < 0)
		return false;
	// The priorities in force at the next camp phase.
	if (b.slot >= 8)
		return acts_before(tie_prio(b.slot), b.slot, tie_prio(P.my_slot), P.my_slot);
	// tie_prio(s) is fixed for the round once first asked (tp_ok; mine is turn_order_base's per-round tier on the static P.prio), so the
	// answer per slot is too.
	static int tm_round = -1000;
	static std::array<std::int8_t, 8> tm{};
	if (tm_round != W.round)
	{
		tm_round = W.round;
		tm.fill(-1);
	}
	auto& v = tm[static_cast<std::size_t>(b.slot)];
	if (v < 0)
		v = acts_before(tie_prio(b.slot), b.slot, tie_prio(P.my_slot), P.my_slot) ? 1 : 0;
	return v != 0;
}
} // namespace nova::mv
