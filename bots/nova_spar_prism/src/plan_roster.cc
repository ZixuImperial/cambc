// plan_roster.cc: The plan: roster, tank order, carriers and capture order.
#include "plan_internal.h"
namespace nova {
NOVA_INLINE void plan_tank_order()
{
	// The healer is never a camp tank and acts last on camp ties (it stands behind its partner). With the Ryth-first setting 2, Ryth is
	// the team's first camp tank.
	auto rank_of = [](cambc::champion_type t)
	{ return willow_layer::plan_no_tank(kit_of(t)) ? 99 : (camp_tank_rank(t)); };
	for (int i = 0; i < P.n; ++i)
	{
		int better = 0;
		const int ri = rank_of(P.type[static_cast<std::size_t>(i)]);
		for (int j = 0; j < P.n; ++j)
		{
			const int rj = rank_of(P.type[static_cast<std::size_t>(j)]);
			if (rj < ri || (rj == ri && j < i))
				++better;
		}
		P.tank_order[static_cast<std::size_t>(i)] = better;
		P.prio[static_cast<std::size_t>(i)] = 20 - better;
	}
	++xic_tbt_ver; // v723 XIC bit 64 TBT1: build_team's by_tank key (rare: once per plan)
}
NOVA_INLINE void plan_carriers()
{
	// Stacking champions collect: Prism gains Focus from carried gems, Marcella earns gold on gems she tributes,
	// Vesper Vale earns +33% on her own gold share.
	P.carrier_gems = P.carrier_gold = -1;
	for (int i = 0; i < P.n; ++i)
	{
		const Kit& k = kit_of(P.type[static_cast<std::size_t>(i)]);
		if (k.gem_focus)
			P.carrier_gems = i;
		else if (vesper_layer::gold_carrier(k))
			P.carrier_gold = i;
	}
	if (P.carrier_gems < 0)
		for (int i = 0; i < P.n; ++i)
			if (marcella_layer::plan_gem_carrier(P.type[static_cast<std::size_t>(i)]))
				P.carrier_gems = i;
}
NOVA_INLINE void plan_capture_order()
{
	// Capture order when several bodies stand on a cleared group: carriers first, the best tank last.
	for (int i = 0; i < P.n; ++i)
	{
		int r = 10 + (P.n - P.tank_order[static_cast<std::size_t>(i)]);
		if (i == P.carrier_gems)
			r = 0;
		else if (i == P.carrier_gold)
			r = 5;
		P.capture_rank[static_cast<std::size_t>(i)] = r * 8 + i;
	}
}
void build_plan()
{
	const auto allies = roster(team::ally);
	P.n = static_cast<int>(std::min<std::size_t>(allies.size(), P.handle.size()));
	const auto me = static_cast<std::uint32_t>(cambc::detail::sdk_my_champion());
	for (int i = 0; i < P.n; ++i)
	{
		const auto& c = allies[static_cast<std::size_t>(i)];
		P.handle[static_cast<std::size_t>(i)] = c.h;
		P.type[static_cast<std::size_t>(i)] = c.type;
		P.party[static_cast<std::size_t>(i)] = -1;
		if (P.handle[static_cast<std::size_t>(i)] == me)
			P.my_slot = i;
	}
	if (XCF_ON(4)) // v775 XCF bit 4 PSL1
		P.prism_at = plan_prism_scan();
	try
	{
		decode_memory();
	}
	catch (...)
	{
		FXR_PASS();
	}
	try
	{
		prism::read_plan(); // The draft's Prism map plan, or the map-only defaults.
	}
	catch (...)
	{
		FXR_PASS();
	}
	// Every body farms on its own targets; crews form per target through the shared-memory claims (econ), so no body waits on a fixed
	// partner. Camp ties go to the higher priority, so the best camp tank gets the highest.
	for (int i = 0; i < P.n; ++i)
	{
		const auto si = static_cast<std::size_t>(i);
		P.party[si] = -1;
		P.role[si] = ROLE_SOLO;
	}
	P.lead = { -1, -1 };
	plan_tank_order();
	plan_carriers();
	plan_capture_order();
}

int camp_tank_rank(cambc::champion_type t)
{
	using C = cambc::champion_type;
	switch (t)
	{
	case C::heart_of_ruin: return 0;
	case C::varg: return 1;
	case C::ryth: return 2;
	case C::marcella: return 3;
	case C::ren: return 4;
	case C::issac: return 5;
	case C::vendetta: return 6;
	case C::vesper_vale: return 7;
	case C::tavi: return 8;
	case C::stellar: return 9;
	case C::willow: return 10;
	case C::prism: return 11;
	case C::cassi: return 12;
	default: return 13;
	}
}

} // namespace nova

// Map class bits from the group distances. Draft: exact walks from the draft's own analysis; champions only on the fallback path (no
// stored field), from the decoded distances.
