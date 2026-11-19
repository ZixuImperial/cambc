// planner.cc: Planner: capture routing to the stacking champions (stack_rank_bonus) and turn measurement (stat_*).
#include "planner.h"

#include "comms.h"
#include "mapinfo.h"
#include "move.h"
#include "plan.h"
#include "champions.h" // Kit layers.
#include "world.h"

namespace nova::planner {

namespace {

int now() { return W.round; }

// ---------------------------------------------------------------- stats
struct Stats
{
	long t_start = 0;
	int r_start = -1;
	int turns = 0, susp = 0, over85 = 0;
	long long sum = 0;
	long mx = 0;
	std::array<int, 260> hist{};
	int trips = 0, wasted = 0, wasted_rounds = 0, wait_resp = 0, wait_crew = 0, idle = 0;
	int caps = 0, shared = 0, first = -1, capgems = 0, capgold = 0;
	int first_act = -1;
	std::array<int, 8> idle_act{};
};
Stats ST;

} // namespace

// ---------------------------------------------------------------- stacking

// Damage per 100 base capture gold by kit x10, in champion_type order (ranks computed from the rules; Vesper's +33% gold is in her
// number). Ryth, Vesper, Vendetta, Cassi, Issac, Stellar, Prism, Marcella, Willow, Ren, Varg, Tavi, HoR.
static const int rcy_d100[13] = { 233, 344, 311, 149, 155, 166, 115, 181, 155, 230, 259, 259, 138 };
// Rank points this capture is worth to kit t now: damage its gold buys x RCY_K, x the share of the game left to use it (1 to r150,
// .65 at r300, .2 at r600, 0 from r875: the fall of gems per damage).
static int capture_rank_fit(cambc::champion_type t, int slot, int gold, int gems)
{
	const int ti = static_cast<int>(t);
	if (ti < 0 || ti >= 13)
		return 0;
	const int geq = static_cast<int>(mu::holder_gold_mult(slot) * (static_cast<float>(gold) + (marcella_layer::gem_gold(t) ? marcella_layer::tribute_gold(static_cast<float>(gems)) : 0.0f)));
	if (geq <= 0)
		return 0;
	const int r = now();
	const int fade = r <= 150 ? 100 : r <= 300 ? 100 - 35 * (r - 150) / 150 : r <= 600 ? 65 - 45 * (r - 300) / 300 : r < 875 ? 20 - 20 * (r - 600) / 275 : 0;
	const int w = R3L_ON(1) && ti == 1 ? 259 : (willow_layer::type(t)) ? rcy_d100[ti] * WL2_TAB[5] / 100 : rcy_d100[ti]; // v703 R3L bit 1 L68: Vesper's 344 holds her +33%, holder_gold_mult adds it again (GR:532): 344/1.33 = 259 // WL2 bit 32768: rewards route to her mates
	return static_cast<int>(static_cast<std::int64_t>(geq) * w * RCY_TAB[2] * fade / 100000);
}
int stack_rank_bonus(int slot, int gi)
{
	if (gi < 0 || gi >= M.ng || slot < 0)
		return 0;
	const auto& g = M.groups[static_cast<std::size_t>(gi)];
	const auto t = P.type[static_cast<std::size_t>(slot)];
	const Kit& k = kit_of(t);
	int b = 0;
	const bool rcy = true;
	// Marcella earns 2 gold per gem she tributes and Prism gains Focus per carried gem: gem captures go to them.
	if (g.gems > 0 && ((marcella_layer::gem_gold(t) && !rcy) || k.gem_focus))
		b -= 200 + 4 * g.gems;
	// Gold captures pass Cassi & Issac by when a mate stands there to take them (CI_CAP_PEN).
	if (g.gold > 0 && (ci_layer::type(t)) && !CRE_ON(1) && !CI2_FARM()) // CRE1: a C&I slot ranks by work_rank on every body
		b += CI_CAP_PEN + g.gold / 2;
	// Vesper Vale earns a third more gold from her own captures.
	(void)(g.gold > 0 && vesper_layer::targets_own_gold(k) && !rcy);
	b -= capture_rank_fit(t, slot, g.gold, g.gems);
	return b;
}

// ---------------------------------------------------------------- measurement

void stat_set_target(int) { ++ST.trips; }
void stat_wasted_trip(int, int walked)
{
	++ST.wasted;
	ST.wasted_rounds += walked;
}
void stat_wait(int kind)
{
	if (kind == 0)
		++ST.wait_resp;
	else
		++ST.wait_crew;
}
void stat_idle(int act)
{
	++ST.idle;
	++ST.idle_act[static_cast<std::size_t>(std::clamp(act, 0, 7))];
}
void stat_capture(int, int sharing, int gems, int gold)
{
	++ST.caps;
	if (sharing > 1)
		++ST.shared;
	if (ST.first < 0)
		ST.first = W.round;
	ST.capgems += gems;
	ST.capgold += gold;
}

} // namespace nova::planner
