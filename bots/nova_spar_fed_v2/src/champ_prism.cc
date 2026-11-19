#include "champ_prism.h"
#include "champions.h" // Prism layer
#include "rules.h"
// The Prism map plan (draft side), its decoding (play side) and the carrier's shared helpers. The banking, capture and shopping
// hooks live in the econ files, the channel cancel in the brain files, the spell exemption in the combat files.
#include <algorithm>
#include <array>
#include "combat.h"
#include "mapinfo.h"
#include "plan.h"
#include "world.h"
#include "comms.h"
#include "intel.h"
#include "race_estimate.h"
#include "champ_willow.h"
#include "econ.h"
#include "move.h"
#include "multipliers.h"

namespace nova::prism {

Plan PL;

namespace {

// Enemy tributed history for the race deadline: one sample every 10 rounds, the last 32.
std::array<int, 32> hist_t{};
std::array<int, 32> hist_r{};
int hist_n = 0;
int hist_last = -100;
std::array<int, 32> hist_u{}; // our tributed total at the same samples
int race_lost = -100; // the last round a race-deadline bank was refused

int fam_round = -100;
std::uint32_t fam_bits = 0;

distance_field* alt_field = nullptr;
bool alt_tried = false;
int alt_for = -1;
} // namespace
// Fuel use: recursive (no static bound). Measured max 18,322, mean 8,714 per call, 4.3 calls per game, 37,904 per game including
// callees.
void write_plan(std::vector<std::uint8_t>& mem)
{
	if (!M.done())
		return;
	// the group/altar distances (encode_draft_memory in the plan code) run to 16 + 3(ng + na) uncapped: never overwrite them
	if (16 + 3 * (static_cast<std::size_t>(M.ng) + static_cast<std::size_t>(M.na)) > PLAN_AT)
		return;
	if (mem.size() < PLAN_END)
		mem.resize(PLAN_END, 0);
	std::array<std::uint8_t, N> b{};
	b[0] = MAGIC;
	b[1] = VERSION;
	std::uint8_t flags = 1;
	int clu = 0, gold = 0;
	struct Cand
	{
		int gi, gems;
		float contest;
	};
	std::vector<Cand> cand;
	for (std::size_t i = 0; i < static_cast<std::size_t>(M.ng) && i < 255; ++i)
	{
		const auto& g = M.groups[i];
		if (g.access != ACC_WALK || g.d_home == UNREACH || g.contest > 0.6f)
			continue;
		gold += g.gold;
		if (g.n_clu > 0)
			clu += g.gems;
		if (g.gems >= PC_ROUTE_GEMS)
			cand.push_back({ static_cast<int>(i), g.gems, g.contest });
	}
	if (clu >= 30)
		flags |= 2;
	if (gold >= PC_GOLD_TREASURE)
		flags |= 4;
	std::sort(cand.begin(), cand.end(), [](const Cand& x, const Cand& y) { return x.gems != y.gems ? x.gems > y.gems : x.contest < y.contest; });
	for (std::size_t k = 0; k < 4; ++k)
		b[8 + k] = k < cand.size() ? static_cast<std::uint8_t>(cand[k].gi) : 255;
	// The safest altars: walkable from our spawn, not gated; the enemy's walk longest, then ours shortest.
	int best[2] = { -1, -1 };
	float bs[2] = { -1e9f, -1e9f };
	for (std::size_t i = 0; i < static_cast<std::size_t>(M.na) && i < 255; ++i)
	{
		const auto& a = M.altars[i];
		if (a.d_home == UNREACH || a.gated || a.access != ACC_WALK)
			continue;
		const float de = a.d_enemy == UNREACH ? 400.0f : static_cast<float>(a.d_enemy);
		const float s = de - 0.5f * static_cast<float>(a.d_home);
		if (s > bs[0])
		{
			bs[1] = bs[0];
			best[1] = best[0];
			bs[0] = s;
			best[0] = static_cast<int>(i);
		}
		else if (s > bs[1])
		{
			bs[1] = s;
			best[1] = static_cast<int>(i);
		}
	}
	int cap = PC_CAP_DEFAULT;
	for (int k = 0; k < 2; ++k)
	{
		b[4 + k] = best[k] >= 0 ? static_cast<std::uint8_t>(best[k]) : 255;
		int t = 0;
		if (best[k] >= 0)
		{
			const auto& a = M.altars[static_cast<std::size_t>(best[k])];
			t = a.d_enemy == UNREACH ? 254 : std::clamp(static_cast<int>(a.d_enemy) - 4, 0, 254);
		}
		b[6 + k] = static_cast<std::uint8_t>(t);
	}
	if (best[0] >= 0)
	{
		flags |= 8;
		cap = 10 * std::clamp(static_cast<int>(b[6]), PC_CAP_TMIN, PC_CAP_TMAX);
	}
	b[2] = flags;
	b[3] = static_cast<std::uint8_t>(std::min(255, cap / 4));
	plan_bytes(plan_for_map(), &b[12]); // draft plan bytes 748-758, inside the checksum below
	int sum = 0;
	for (std::size_t i = 0; i + 1 < N; ++i)
		sum += b[i];
	b[N - 1] = static_cast<std::uint8_t>(sum & 255);
	for (std::size_t i = 0; i < N; ++i)
		mem[PLAN_AT + i] = b[i];
}
// Fuel use: formula over 4 loops. Measured max 985, mean 719 per call, 4.5 calls per game, 3,248 per game including callees.

int prism_slot()
{
	for (int i = 0; i < P.n; ++i)
		if (P.type[static_cast<std::size_t>(i)] == cambc::champion_type::prism)
			return i;
	return -1;
}

bool me_prism() { return W.me.kit && W.me.kit->gem_focus; }

bool carry_on() { return (PL.flags & 1) != 0 && prism_slot() >= 0; }
// Fuel use: formula over 2 loops. Measured max 84, mean 47 per call, 9.5 calls per game, 451 per game including callees.
bool prism_alive()
{
	const int ps = prism_slot();
	if (ps < 0)
		return false;
	if (ps == P.my_slot)
		return W.alive;
	return W.ally_by_slot(ps) != nullptr;
}
// Fuel use: formula over 2 loops. Measured max 42, mean 42 per call, 32.1 calls per game, 1,347 per game including callees.
vec2 pos_of_prism()
{
	const int ps = prism_slot();
	if (ps < 0)
		return { -1, -1 };
	if (ps == P.my_slot)
		return W.alive ? W.me.pos : vec2{ -1, -1 };
	const Body* b = W.ally_by_slot(ps);
	return b ? b->pos : vec2{ -1, -1 };
}
// Fuel use: formula over 1 loop. Measured max 51, mean 51 per call, 8.4 calls per game, 429 per game including callees.
int bag_of_prism()
{
	const int ps = prism_slot();
	if (ps < 0)
		return -1;
	if (ps == P.my_slot)
		return static_cast<int>(W.me.gems);
	std::uint32_t g = 0;
	if (cambc::detail::sdk_champion_gems(P.handle[static_cast<std::size_t>(ps)], &g) != 0)
		return -1;
	return static_cast<int>(g);
}

int pg_seen_r = -1000, pg_seen_bag = -1;
// Fuel use: formula over 5 loops. Measured max 618, mean 102 per call, 2,080.7 calls per game, 212,534 per game including callees.
vec2 guard_post_slow();
// inlined: the first early-out test is inline at the call site, the rest is out of line
__attribute__((always_inline)) vec2 guard_post()
{
	if (!W.alive)
		return { -1, -1 };
	return guard_post_slow();
}
__attribute__((noinline)) vec2 guard_post_slow()
{
	const int ps = prism_slot();
	if (ps < 0 || ps == P.my_slot || bag_of_prism() < PG_BAG)
		return { -1, -1 };
	const vec2 pz = pos_of_prism();
	if (pz.x < 0)
		return { -1, -1 };
	auto eligible = [](const Body& b) { return b.frac() >= 0.5f && !(willow_layer::prism_guard_skip(b)); };
	auto score = [&](const Body& b) { return 2 * cheb(b.pos, pz) - ((b.kit && !b.kit->ranged) ? 6 : 0); };
	if (!eligible(W.me))
		return { -1, -1 };
	const int mine = score(W.me);
	for (const auto& al : W.allies)
	{
		if (al.slot == ps || !eligible(al)) // W.allies holds the living allies
			continue;
		const int s = score(al);
		if (s < mine || (s == mine && al.slot < P.my_slot))
			return { -1, -1 };
	}
	return pz;
}
// Fuel use: formula over 1 loop. Measured max 924, mean 84 per call, 5,543.1 calls per game, 464,534 per game including callees.
bool has_family_slow(int fam);
// inlined: the range test and the cached bits are inline (about 6.5k calls a game); the 10-round refresh is out of line
__attribute__((always_inline)) bool has_family(int fam)
{
	if (fam < 0 || fam > 13)
		return false;
	if (W.round - fam_round < 10)
		return (fam_bits >> fam & 1u) != 0;
	return has_family_slow(fam);
}
__attribute__((noinline)) bool has_family_slow(int fam)
{
	if (W.round - fam_round >= 10)
	{
		fam_round = W.round;
		fam_bits = 0;
		try
		{
			const std::uint32_t* const counts = my_items_raw(); // no zero-filled copy
			if constexpr (ITEM_N >= 84)
			{
				// the same bits: family f is set when any of its 3 emblems (ids 6f+1, 6f+3, 6f+5) is held
#pragma clang loop unroll(full)
				for (int f = 0; f < 14; ++f)
					fam_bits |= static_cast<std::uint32_t>((counts[6 * f + 1] | counts[6 * f + 3] | counts[6 * f + 5]) != 0) << f;
			}
			else
			for (int f = 0; f < 14; ++f)
				for (int st = 0; st < 3; ++st)
				{
					const std::size_t id = static_cast<std::size_t>(6 * f + 2 * st + 1); // the emblem of family f, stat st
					if (id < ITEM_N && counts[id] > 0)
						fam_bits |= 1u << f;
				}
		}
		catch (...)
		{
			FXR_PASS();
		}
	}
	return (fam_bits >> fam & 1u) != 0;
}
// my emblem family bits (the same 10-round cache)
std::uint32_t my_families()
{
	(void)has_family(0);
	return fam_bits;
}

void fam_reset() { fam_round = -100; }

bool has_tribute() { return me_prism() && has_family(7); }
// Fuel use: formula over 1 loop. Not called in the measured games.
int channel_tick_count(int gems)
{
	// The engine's ceil(0.67 t) for a Tribute emblem holder, in integers ((2t+2)/3 is one turn short when 3 divides t). The emblem is
	// holder-only for any champion (prism::has_family(7)).
	const int n = rs::tribute_turns(gems, has_family(rs::F_TRIBUTE));
	RSD(const int t0 = std::max(1, (gems + 9) / 10); const int o = has_tribute() ? std::max(1, (2 * t0 + 2) / 3) : t0; if (has_family(rs::F_TRIBUTE)) ++rsd::c[0]; if (o != n) ++rsd::c[1];);
	return n;
}

// Her greed rule: the capture-routing cap c is lifted (1), or lifted while her bag is under a share of the team's gems (2).
static int prism_greed_capture_cap(int c)
{
	return 1 << 20;
}

int bag_cap()
{
	const int c = has_tribute() ? (3 * PL.cap) / 2 : PL.cap;
	return prism_greed_capture_cap(c * PC_CAP_MULT / 100); // her bag cap scaled by PC_CAP_MULT, with the greed rule applied
}
// Fuel use: formula over 2 loops. Measured max 26, mean 26 per call, 8.4 calls per game, 219 per game including callees. bag_cap()
// on a mate leaves out her Tribute (has_tribute() is the caller's own emblem test), so read her emblems.
int cap_of_prism()
{
	const int ps = prism_slot();
	if (ps < 0 || ps >= static_cast<int>(P.handle.size()) || ps == P.my_slot) // bounds: no UB on a bad slot
		return bag_cap();
	static int c_round = -1, c_val = 0;
	return 1 << 20; // greed rule: no cap
}

bool pf_group(int gi)
{
	if (gi < 0 || gi >= M.ng)
		return false;
	const auto& g = M.groups[static_cast<std::size_t>(gi)];
	return g.access == ACC_WALK && g.gems >= PF_GEMS && g.gold <= (PG_GOLD_PER_GEM) * g.gems; // greed rule: mixed groups too
}

bool pc_group(int gi) { return is_plan_group(gi) || pf_group(gi); }

bool is_plan_group(int gi)
{
	if (gi < 0)
		return false;
	for (int g : PL.groups)
		if (g == gi)
			return true;
	return false;
}

void track()
{
	if (W.round - hist_last < 10)
		return;
	hist_last = W.round;
	const std::size_t k = static_cast<std::size_t>(hist_n % 32);
	hist_t[k] = W.tributed_them;
	hist_u[k] = W.tributed_us;
	hist_r[k] = W.round;
	++hist_n;
}
// Fuel use: formula over 2 loops. Measured max 387, mean 375 per call, 0.7 calls per game, 255 per game including callees.
int foe_eta()
{
	const int them = W.tributed_them;
	if (them >= 1000)
		return 0;
	int best = BIG;
	for (const auto& e : W.enemies)
	{
		if (!(e.state & ST_TRIBUTE))
			continue;
		std::uint32_t eg = e.gems;
		if (them + static_cast<int>(eg) >= 1000)
		{
			std::int32_t left = -1;
			if (cambc::detail::sdk_champion_channel_time(e.h, &left) == 0 && left >= 0)
			{
				best = std::min(best, static_cast<int>(left) + (RGS_ON(8) && (e.state & FLEE_FIX_ST_ACTED) != 0 ? 1 : 0)); // RGS bit 8
			}
		}
	}
	if (hist_n < 2)
		return best;
	int r0 = -1, t0 = 0;
	for (int j = std::max(0, hist_n - 32); j < hist_n; ++j)
	{
		const std::size_t k = static_cast<std::size_t>(j % 32);
		if (W.round - hist_r[k] <= 200)
		{
			r0 = hist_r[k];
			t0 = hist_t[k];
			break;
		}
	}
	if (r0 < 0 || W.round - r0 < 50 || them <= t0)
		return best;
	const float rate = static_cast<float>(them - t0) / static_cast<float>(W.round - r0);
	return std::min(best, static_cast<int>(static_cast<float>(1000 - them) / rate));
}

// Rounds from now until the foe team's 1000th gem is credited: min(LINEAR, BAGS) (race_estimate.h). LINEAR: foe_finishes_before_bank's rate
// (the oldest sample of the last ~200 rounds, >= 50 rounds of history). BAGS: each living foe whose bag my sight or ward saw within
// RFE_AGE rounds (intel team table; a death voids it) banks p x bag at k x Chebyshev(that tile, nearest altar) +
// rs::tribute_rounds(bag) (the foe's Tribute emblem is not read: the no-emblem time), plus q x the same rate after RFE_L rounds. 1e9
// when neither predicts.
double foe_finish_eta()
{
	const int them = W.tributed_them;
	if (them >= 1000)
		return 0.0;
	double rate = 0.0;
	if (hist_n >= 2)
	{
		int r0 = -1, t0 = 0;
		for (int j = std::max(0, hist_n - 32); j < hist_n; ++j)
		{
			const std::size_t k = static_cast<std::size_t>(j % 32);
			if (W.round - hist_r[k] <= 200)
			{
				r0 = hist_r[k];
				t0 = hist_t[k];
				break;
			}
		}
		if (r0 >= 0 && W.round - r0 >= 50 && them > t0)
			rate = static_cast<double>(them - t0) / static_cast<double>(W.round - r0);
	}
	const double lin = rfe::linear_eta(them, rate);
	const int age = RACE_TAB[6];
	const double p = RACE_TAB[2] / 100.0, q = RACE_TAB[3] / 100.0, kw = RACE_TAB[5] / 10.0;
	double at[16], val[16];
	int n = 0;
	const auto& tt = intel::team_table();
	for (std::size_t i = 0; i < tt.size() && n < 16; ++i)
	{
		if (!tt[i].alive || W.round - intel::team_body_round(i) > age)
			continue;
		const Body* b = intel::team_body(i);
		if (!b || b->gems == 0)
			continue;
		int ad = 30; // no altar known
		if (!M.altars.empty())
		{
			ad = BIG;
			for (const auto& a : M.altars)
				ad = std::min(ad, cheb(a.pos, b->pos));
		}
		const int g = static_cast<int>(b->gems);
		RULE_AUDIT_FIX_CNT(7, rs::tribute_turns_of(g, b->h, W.round) != rs::tribute_rounds(g, false));
		at[n] = kw * ad + (rs::tribute_turns_of(g, b->h, W.round)); // uses the foe's Tribute emblem as read
		val[n] = p * g;
		++n;
	}
	if (n == 0 && rate <= 0.0)
		return lin;
	return std::min(lin, rfe::bags_time_to_need(1000.0 - them, at, val, n, q * rate, static_cast<double>(RACE_TAB[4]), 2000.0));
}

bool foe_finishes_before_bank(int t_bank)
{
	const int them = W.tributed_them;
	return foe_finish_eta() <= static_cast<double>(t_bank + PC_RACE_T);
	// their recent rate: the oldest sample of the last ~200 rounds
}
// Fuel use: formula over 5 loops. Measured max 862, mean 399 per call, 1.3 calls per game, 532 per game including callees.
bool prism_can_win_race(int gems, int t_bank)
{
	const int them = W.tributed_them;
	int r0 = -1, t0 = 0, u0 = 0;
	for (int j = std::max(0, hist_n - 32); j < hist_n; ++j)
	{
		const std::size_t k = static_cast<std::size_t>(j % 32);
		if (W.round - hist_r[k] <= 200)
		{
			r0 = hist_r[k];
			t0 = hist_t[k];
			u0 = hist_u[k];
			break;
		}
	}
	float span = 0.0f, left = 0.0f;
	const double eta = them >= 1000 ? 1e9 : foe_finish_eta();
	if (eta >= 1e8)
		return true; // no foe time (or they have won): no foe rate
	left = static_cast<float>(eta);
	span = r0 >= 0 && W.round - r0 >= 50 ? static_cast<float>(W.round - r0) : 0.0f; // our rate needs the same history
	const float win = left + static_cast<float>(RR_SLACK); // rounds we may take
	bool ok = static_cast<float>(t_bank) <= win;
	if (ok)
	{
		float sum = static_cast<float>(W.tributed_us + gems);
		for (const auto& al : W.allies)
		{
			int ag = static_cast<int>(al.gems);
			std::uint32_t pg = 0;
			if (cambc::detail::sdk_champion_gems(al.h, &pg) == 0)
				ag = static_cast<int>(pg);
			if (ag == 0)
				continue;
			int ad = BIG;
			for (const auto& a : M.altars)
				ad = std::min(ad, cheb(a.pos, al.pos));
			if (static_cast<float>(ad + rs::tribute_rounds(ag, static_cast<bool>(rs::has(rs::families(al.h, W.round), rs::F_TRIBUTE)))) <= win) // the ally's own emblem
				sum += static_cast<float>(ag);
		}
		if (W.tributed_us > u0 && span > 0.0f)
			sum += static_cast<float>(W.tributed_us - u0) / span * win;
		ok = sum >= 1000.0f;
	}
	if (!ok)
		race_lost = W.round;
	return ok;
}

bool race_deny() { return RACE_DENY && W.round - race_lost <= RD_AGE && static_cast<int>(W.me.gems) >= RD_BAG && W.me.kit && W.me.kit->gem_focus; }
// Fuel use: formula over 5 loops. Measured max 189, mean 189 per call, 0.0 calls per game, 4 per game including callees.
int nearest_known_enemy()
{
	int best = BIG;
	for (const auto& e : W.enemies)
		best = std::min(best, cheb(e.pos, W.me.pos));
	for (const auto& e : W.enemies_far)
		best = std::min(best, cheb(e.pos, W.me.pos));
	best = std::min(best, combat::nearest_foe_distance_seen(PC_KNOWN_AGE));
	return best;
}
// Fuel use: formula over 7 loops. Measured max 1,181, mean 32 per call, 28.4 calls per game, 919 per game including callees. Bit 1:
// true when foe_finishes_before_bank(t_bank) holds only through the flat 'them >= 1000 - race gems' clause: the tributed total plus
// the bags of foes seen in the last few rounds stays under 1000 and their recent rate (foe_finishes_before_bank's test, same
// samples) does not reach 1000 within t_bank + PC_RACE_T. Waiting can still win then.
static bool deadline_only_from_flat_clause(int t_bank)
{
	return false; // no flat clause: a deadline always came from the time test
}
bool winning_tribute_start_blocked(int gems)
{
	if (nearest_known_enemy() > WSG_TAB[2])
		return false;
	const int ticks = rs::tribute_turns(gems, has_family(rs::F_TRIBUTE));
	if (W.round + ticks >= 1990 || ((econ::bag_wins_with_mates(gems) || !(W.me.kit && !W.me.kit->gem_focus)) && foe_finishes_before_bank(ticks) && !(deadline_only_from_flat_clause(ticks))))
		return false; // the race: waiting cannot win it
	return !combat::channel_safe(0, ticks, 0.0f);
}
bool tribute_start_allowed(int gems)
{
	if (gems < TG_BAG)
		return true;
	if (econ::bag_wins_with_mates(gems)) // adds the mates' landings to the sum
		return !(winning_tribute_start_blocked(gems));
	if (nearest_known_enemy() > TG_R)
		return true;
	// A stun cannot cancel a stun-immune carrier's channel; only damage that kills her before it completes (known foes within TG_R + 2:
	// burst + dps over the channel's own turns) keeps the guard.
	if (marcella_layer::chan_stun_proof())
	{
		const int t0 = std::max(1, (gems + 9) / 10);
		const int ticks = WBK_TGT ? rs::tribute_turns(gems, has_family(rs::F_TRIBUTE)) : (has_tribute() ? std::max(1, (2 * t0 + 2) / 3) : t0);
		if (mu::mult_foe_hit_to_real_hp_alt(combat::channel_damage_threat(PC_KNOWN_AGE, TG_R + 2, ticks)) < W.me.hp + W.me.shield)
		{
			if (combat::rgf_foe_lock_in_time(ticks))
				return false; // a stun cannot cancel her channel, a foe lock can (GR:226; INT:114)
			return true;
		}
	}
	return false;
}
static int opb_wait0 = -1, opb_g0 = 0; // first round this winning bag waited, and its size then
// WKH bit 1: a winning channel that lands in `ticks` own turn starts should not be kept. (b) a foe seen within WKH_AGE rounds whose
// bag wins for them, banking at or before ours: its tribute's ticks left when visible and channelling, else the walk to a tile next
// to an altar (one step of it in the start turn) + our visible lock's hits there + its channel; its distance shrinks 1 a round of
// age.
static bool foe_banks_winning_bag_first(int ticks)
{
	const auto& tt = intel::team_table();
	for (std::size_t i = 0; i < tt.size(); ++i)
	{
		const int age = W.round - tt[i].round;
		if (!tt[i].alive || age < 0 || age > WKH_TAB[3])
			continue;
		const Body* b = intel::team_body(i);
		if (!b)
			continue;
		const int bag = static_cast<int>(b->gems);
		if (bag <= 0 || W.tributed_them + bag < 1000)
			continue;
		std::int32_t lf = -1;
		if (age == 0 && (b->state & ST_TRIBUTE) && cambc::detail::sdk_champion_channel_time(b->h, &lf) == 0 && lf >= 0)
		{
			if (lf + (RGS_ON(8) && (b->state & FLEE_FIX_ST_ACTED) != 0 ? 1 : 0) <= ticks) // RGS bit 8: already acted this round: it lands one round later
				return true;
			continue;
		}
		const int tc = rs::tribute_turns_of(bag, b->h, W.round); // the foe's emblem
		KIT_RULE_FIX_CNT(7, tc != rs::tribute_turns(bag, false));
		int best = BIG;
		for (const auto& a : M.altars)
		{
			const int walk = std::max(0, cheb(tt[i].pos, a.pos) - 1 - age);
			int hits = 0;
			try
			{
				if (bbget(W.vis, a.pos) && cambc::vision::has_altar_lock(a.pos))
				{
					const auto lock = cambc::vision::altar_lock_at(a.pos);
					if (!lock.is_enemy())
						hits = static_cast<int>(lock.hits_remaining());
				}
			}
			catch (...)
			{
				FXR_PASS();
			}
			best = std::min(best, std::max(0, walk - 1) + hits + tc);
		}
		if (best <= ticks)
			return true;
	}
	return false;
}
// WKH bit 1: (a) the known foes can kill her before it lands (foe_damage_over_ticks(ticks) = burst + dps x ticks: ticks + 1 foe turns, the extra
// one for the swapped first mover), or (bit 2) foe_banks_winning_bag_first.
static bool winning_channel_doomed(int ticks)
{
	const float eff = W.me.hp + std::max(0.0f, W.me.shield); // uses current HP plus shield
	if (combat::foe_damage_over_ticks(WKH_TAB[3], std::max(1, ticks)) * 100.0f >= static_cast<float>(WKH_TAB[4]) * eff)
		return true;
	return static_cast<bool>(foe_banks_winning_bag_first(ticks));
}
bool channel_start_ok(int gems)
{
	if (gems < PC_CHAN_BAG)
		return true;
	const int wck = nova::econ::win_channel::start_gate(gems);
	if (wck != 0)
		return wck > 0;
	// A winning bag opens with an enemy near while she is healthy, as channel_doomed keeps one (PC_WIN_KEEP_HP; below it, while no
	// known foe can kill her first)
	if (W.tributed_us + gems >= 1000 && (W.me.hp * 100.0f >= static_cast<float>(WKH_TAB[2]) * W.me.maxhp || (!winning_channel_doomed(channel_tick_count(gems)))))
		return !(winning_tribute_start_blocked(gems));
	return nearest_known_enemy() > PC_CHAN_R;
}

// The channel-doom keep arms, shared by channel_doomed and channel_not_doomed: a bag under PC_CHAN_BAG, or (winchan) a bag that wins
// the game while her HP >= PC_WIN_KEEP_HP percent (below it, while !winning_channel_doomed over `ticks`, the own turns until it
// lands)
static bool channel_doom_exempt(int gems, int ticks)
{
	if (gems < PC_CHAN_BAG)
		return true;
	if (W.tributed_us + gems < 1000)
		return false;
	if (!(W.me.hp * 100.0f < static_cast<float>(WKH_TAB[2]) * W.me.maxhp))
		return true;
	return !winning_channel_doomed(ticks);
}
// Fuel use: formula over 5 loops. Not called in the measured games. PRISM_CHAN_MARGIN: a channel of chan ticks opened walk rounds
// from now is tested by channel_doomed at its owner turns 1 .. chan - PC_DOOM_LEFT after the start (a tick ends every own turn, the
// start turn included), so a known foe now at distance D, walking straight in, is within PC_CHAN_R at a tested turn iff D <= walk +
// chan - PC_DOOM_LEFT + PC_CHAN_R.
bool channel_not_doomed(int gems, int walk, int chan)
{
	if (channel_doom_exempt(gems, std::max(0, walk) + chan))
		return true;
	int nke = nearest_known_enemy();
	return nke > std::max(0, walk) + std::max(0, chan - PC_DOOM_LEFT) + PC_CHAN_R;
}
// Fuel use: formula over 5 loops. Measured max 647, mean 167 per call, 17.9 calls per game, 2,995 per game including callees.
bool channel_doomed()
{
	if (!(W.me.state & ST_TRIBUTE) || static_cast<int>(W.me.gems) < PC_CHAN_BAG)
		return false;
	std::int32_t left = -1;
	if (cambc::detail::sdk_champion_channel_time(static_cast<std::uint32_t>(cambc::detail::sdk_my_champion()), &left) != 0)
		return false;
	if (left < PC_DOOM_LEFT)
		return false; // it completes at my next turn start: keep it
	if (nearest_known_enemy() > PC_CHAN_R)
		return false;
	// A channel whose bag wins the game is kept while she is healthy (winning banks would otherwise be cancelled and re-opened with
	// enemies at 8-11 tiles, at full HP)
	return !channel_doom_exempt(static_cast<int>(W.me.gems), static_cast<int>(left)) || (nova::econ::win_channel::keep_cancel(static_cast<int>(W.me.gems))); // 2-turn lethal test above the line
}

bool spell_free() { return nearest_known_enemy() > PC_SPELL_R; }
// Fuel use: formula over 28 loops. Measured max 46,569, mean 445 per call, 6.2 calls per game, 2,749 per game including callees.
const distance_field* safe_altar_field()
{
	const int ai = PL.altar[0];
	if (ai < 0 || ai >= M.na)
		return nullptr;
	if (alt_field && alt_for == ai)
		return alt_field;
	if (alt_tried || fuel() < 3L * M.w * M.h + 4000 + 45000) // a field costs about 3 w h + 4000 (MapInfo::field_cost)
		return nullptr;
	alt_tried = true;
	bitboard roots{};
	const vec2 ap = M.altars[static_cast<std::size_t>(ai)].pos;
	bool any = false;
	bbforeach(M.altar_adj,
		[&](vec2 p)
		{
			if (cheb(p, ap) <= 1)
			{
				bbset(roots, p);
				any = true;
			}
		});
	if (!any)
		return nullptr;
	static distance_field f;
	bitboard visited{};
	f.compute(M.block_camps, roots, visited);
	alt_field = &f;
	alt_for = ai;
	return alt_field;
}

} // namespace nova::prism

// Prism flags and bag bands live in PACK's spare bits.
namespace nova::prism {
namespace {
comms::Spare pg9_bagf, pg9_pzf, pg9_chf;
int pg9_bw = 0, pg9_n = 0, pg9_c = 0, pg9_cw = 0, pg9_wc = 0;
constexpr int PG9_T3[7] = { 0, 1, 30, 70, 140, 250, 450 }; // 3-bit bands 1-6 start here; band 7 = wins alone
constexpr int PG9_T2[3] = { 0, 1, 70 };                     // 2-bit bands 1-2; band 3 = wins alone
int pg9_need() { return std::max(1, 1000 - W.tributed_us); }
// the band's [lo, hi] at the current need
void bag_band_range(int b, int& lo, int& hi)
{
	const int need = pg9_need();
	const int top = pg9_bw == 3 ? 7 : 3;
	if (b <= 0)
	{
		lo = hi = 0;
		return;
	}
	if (b >= top)
	{
		lo = hi = need;
		return;
	}
	const int* t = pg9_bw == 3 ? PG9_T3 : PG9_T2;
	lo = t[b];
	hi = (b + 1 < top ? t[b + 1] : need) - 1;
	hi = std::min(hi, need - 1);
	lo = std::min(lo, hi);
}
// the Prism field, decoded
struct Pz
{
	int cell = -1, thr = 0, stamp = 0;
};
} // namespace



int bag_band_of_slot(int slot)
{
	if (!pg9_bagf.ok() || slot < 0 || slot >= pg9_n)
		return -1;
	return static_cast<int>((comms::spare_get(pg9_bagf) >> (slot * pg9_bw)) & ((1u << pg9_bw) - 1u));
}


int bag_band_lower_bound(int slot)
{
	if (slot == P.my_slot && slot >= 0)
		return W.alive ? static_cast<int>(W.me.gems) : 0;
	const int b = bag_band_of_slot(slot);
	if (b < 0)
		return -1;
	int lo, hi;
	bag_band_range(b, lo, hi);
	return lo;
}


bool bag_wins_alone(int slot)
{
	const int b = bag_band_of_slot(slot);
	return b >= 0 && b == (pg9_bw == 3 ? 7 : 3);
}





} // namespace nova::prism

// ==================================================================================== PRISM LAYER Her rules that the econ base asks
// for (champions.h; hooks in champ_prism.h). They run in econ's namespace (unity build: one translation unit, so econ's helpers and
// state are in scope). Order: TARGETS (funnel, relay, route, yield), SHOP (build), BANK (kept bag, threat bank, hold bank, channel
// safety).
namespace nova::econ {
namespace {
// ---- TARGETS: PC_FUNNEL quiet group Capture rank of a body for a group (lower captures). Gold buys items, and the first emblems of
// every body are worth the most, so the body with the fewest items captures; a stacking champion is preferred for the reward it
// multiplies (Marcella and Prism for gems, Vesper Vale for gold) unless it is already far richer. A badly hurt body leaves to heal.
// The plan's capture order breaks ties. PC_FUNNEL: no visible enemy within PF_FOE of the group (a contested group costs deaths, so
// no funnel there).
static bool prism_group_is_quiet(const GroupI& g)
{
	for (const auto& e : W.enemies)
		if (cheb(e.pos, g.anchor) <= PF_FOE)
			return false;
	return true;
}
// ---- TARGETS: CAP_RELAY, she is coming CAP_RELAY: Prism is coming for plan group gi (mate_waits_for_prism_capture's conditions without its wait
// window): I am not her, she claims it, lives, stands within PC_ROUTE_R of it, is under her bag cap, and no enemy is in sight. Her
// position is written to *pp.
static bool prism_coming_for_group(int gi, vec2* pp)
{
	if (!W.me.kit || prism_layer::me() || !prism::carry_on() || !prism::pc_group(gi) || !W.enemies.empty())
		return false;
	const int ps = prism::prism_slot();
	if (ps < 0 || ps >= comms::CLAIM_SLOTS || ps == P.my_slot || comms::cgroup(ps) != gi || !prism::prism_alive())
		return false;
	*pp = prism::pos_of_prism();
	return pp->x >= 0 && cheb(*pp, M.groups[static_cast<std::size_t>(gi)].anchor) <= PC_ROUTE_R &&
		prism::bag_of_prism() < (prism::cap_of_prism());
}
// ---- TARGETS: CAP_RELAY hand-off I stand on plan group gi's region while Prism comes: step off (and move on, as PC_YIELD_GO) only
// once she stands on a spawn tile of it. The team timer resets the moment the region is empty, even if she steps on later in the
// same round; it survives only with overlap, so she must be alone at the finish. Returns 0: she is not coming; 1: she is coming
// (hold the tile, no capture recall: a recall channel would keep me on the region at the finish); 2: handed off, the turn was used.
static int prism_relay_handoff(int gi, const GroupI& g)
{
	vec2 pp{ -1, -1 };
	if (!prism_coming_for_group(gi, &pp))
		return 0;
	const bool go = on_group_camp_tile(g, pp);
	if (!go)
		return 1;
	auto& m = mem[static_cast<std::size_t>(gi)];
	m.fail_until = std::max(m.fail_until, now() + 10);
	drop_target(0);
	capture_relay_avoid(gi);
	for (const vec2 dd : DIRS)
	{
		const vec2 q = W.me.pos + dd;
		if (inb(q) && mv::free_tile(q) && !on_group_camp_tile(g, q) && mv::try_move(q))
			break;
	}
	return 2;
}
// ---- TARGETS: PC_ROUTE, her plan groups PRISM_CARRY (PC_ROUTE): the plan's gem groups are the carrier's. A free carrier under her
// bag cap joins a plan group within PC_ROUTE_R that a mate claims: cap_rank ranks her first there, so its capture is hers alone
// (mates took 68% of the gems of 40+ gem captures otherwise).
template <int DM>
void prism_route_to_plan_groups()
{
	if (!prism_layer::carrier() || T.engaged || T.capturing || prism::pc_group(T.target))
		return;
	if (static_cast<int>(W.me.gems) >= prism::bag_cap())
		return;
	for (int gi : prism::PL.groups)
	{
		if (gi < 0 || gi >= M.ng || static_cast<std::size_t>(gi) >= gmem_size(mem))
			continue;
		const auto& g = M.groups[static_cast<std::size_t>(gi)];
		const auto& m = mem[static_cast<std::size_t>(gi)];
		if (cheb(g.anchor, W.me.pos) > PC_ROUTE_R || m.status == GS_RESPAWN || m.fail_until > now())
			continue;
		bool claimed = false;
		for (int s = 0; s < P.n && s < comms::CLAIM_SLOTS; ++s)
			claimed |= s != P.my_slot && comms::cgroup(s) == gi;
		if (!claimed)
			continue;
		force_target_in(gi);
		return;
	}
	if (W.enemies.empty())
		for (int s = 0; s < P.n && s < comms::CLAIM_SLOTS; ++s)
		{
			if (s == P.my_slot)
				continue;
			const int gi = comms::cgroup(s);
			if (!prism::pf_group(gi) || static_cast<std::size_t>(gi) >= gmem_size(mem))
				continue;
			const auto& g = M.groups[static_cast<std::size_t>(gi)];
			const auto& m = mem[static_cast<std::size_t>(gi)];
			if (cheb(g.anchor, W.me.pos) > PF_R || m.status == GS_RESPAWN || m.fail_until > now())
				continue;
			force_target_in(gi); // a mate clears a gem group within PF_R of me, so its capture is mine
			return;
		}
}
// ---- TARGETS: PC_ROUTE, a mate waits for her A mate at a cleared plan group leaves its capture to the coming carrier (rewards
// split among everyone on the region). While she claims the group, lives, is within PC_ROUTE_R and under her cap, and no enemy is in
// sight, the mate steps off the region and waits, at most PC_ROUTE_WAIT rounds. Returns true when the turn was used.
bool mate_waits_for_prism_capture(int gi)
{
	if (prism_layer::me() || !prism::carry_on() || !prism::pc_group(gi) || !W.enemies.empty())
		return false;
	const int ps = prism::prism_slot();
	if (ps < 0 || ps >= comms::CLAIM_SLOTS || comms::cgroup(ps) != gi || !prism::prism_alive())
		return false;
	const auto& g = M.groups[static_cast<std::size_t>(gi)];
	const vec2 pp = prism::pos_of_prism();
	if (pp.x < 0 || cheb(pp, g.anchor) > PC_ROUTE_R || prism::bag_of_prism() >= (prism::cap_of_prism()))
		return false;
	static int wait_gi = -1, wait_from = -1000, wait_last = -1000;
	if (wait_gi != gi || now() - wait_last > 3)
	{
		wait_gi = gi;
		wait_from = now();
	}
	wait_last = now();
	if (now() - wait_from > PC_ROUTE_WAIT)
		return false;
	auto on_region = [&](vec2 p)
	{
		for (int ci : g.members)
			if (M.camps[static_cast<std::size_t>(ci)].pos == p)
				return true;
		return false;
	};
	if (!on_region(pp))
	{
		// Capture relay: start the team capture for her when I stand on (or next to) a free spawn tile before she can, and she is close
		// enough to step on before it pays; capture() hands it to her once she stands on the region. Off the region, with a non-Prism mate
		// already on it (it relays): I yield. On it, I relay too (every relaying mate hands off).
		const bool me_on = on_region(W.me.pos);
		bool other = false;
		for (const auto& a : W.allies)
			other |= !me_on && a.slot != ps && on_region(a.pos);
		if (!other)
		{
			const vec2 none{ -1, -1 };
			const int dp = relay_free_spawn_dist(g, pp, none);
			const int dm = me_on ? 0 : relay_free_spawn_dist(g, W.me.pos, none);
			if (static_cast<std::size_t>(g.nm) >= 2 && dp >= 1 && dp <= CR_ETA && dm <= 1 && dm < dp) // one tile: she could never overlap me
				return capture(gi);
		}
	}
	if (on_region(W.me.pos) && !on_region(pp))
	{
		const int k = capture_pay_in();
		if (k >= 1 && relay_free_spawn_dist(g, pp, vec2{ -1, -1 }) > k)
			return false; // my capture is running and she can't reach a free tile before it pays: finish it (should_capture/capture)
	}
	mem[static_cast<std::size_t>(gi)].fail_until = std::max(mem[static_cast<std::size_t>(gi)].fail_until, now() + 10);
	drop_target(0); // no enemy in sight, so the carrier needs no guard: free this body now
	capture_relay_avoid(gi); // and keep off her region on the way out
	if (on_region(W.me.pos))
		for (const vec2 dd : DIRS)
		{
			const vec2 q = W.me.pos + dd;
			if (inb(q) && mv::free_tile(q) && !on_region(q) && mv::try_move(q))
				return true;
		}
	return true;
}
// ---- BANK: the switched-off bank paths keep her bag The carrier keeps her bag on a bank path whose switch is 0 (PC_WAIT_BANK,
// PC_RING_BANK, PC_DASH_BANK; prism_holds_bank gates PC_END_BANK and PC_CAP_BANK).
static bool pc_keeps_bag(int on) { return !on && prism_layer::carrier(); }
// ---- SHOP: PC_ITEMS, her Health build PRISM_CARRY (PC_ITEMS): her Focus comes from her bag (+1.5 a gem), so every emblem she buys
// is Health (+65 a shard on a 700 base). Families by the map plan: Prospector on cluster maps, Treasure where our side holds camp
// gold (else Hunter), Capture, Tribute (before the win-bank: a third shorter channel), Collectors, Durability, then Bruiser / Power
// Health.
void prism_carrier_shop_build()
{
	constexpr int HP = 2;
	auto emblem = [](int family) { return cambc::item_type(static_cast<std::uint32_t>(family * 6 + HP * 2)); };
	constexpr int POWER = 1, DURABILITY = 2, TREASURE = 3, BRUISER = 6, TRIBUTE = 7, CAPTURE = 8, PROSPECTOR = 9, HUNTER = 10,
		COLLECTORS = 13;
	constexpr int GREED = 12;
	if (prism::PL.flags & 2)
		build.push_back(emblem(PROSPECTOR));
	build.push_back(emblem((prism::PL.flags & 4) ? TREASURE : HUNTER));
	build.push_back(emblem(CAPTURE));
	build.push_back(emblem(TRIBUTE));
	build.push_back(emblem(COLLECTORS));
	build.push_back(emblem(DURABILITY));
	for (int i = 0; i < SHOP_TAIL; ++i)
		build.push_back(emblem(((i & 1) ? POWER : BRUISER)));
}
} // namespace
} // namespace nova::econ
namespace nova::econ {
// ---- BANK: PC_THREAT_BANK PC_THREAT_BANK: PTB_N+ enemy champions known within PTB_SEE of me (visible or far), and the nearest
// known one (combat memory too) farther than t + PTB_SLACK: a bank of t rounds completes first.
static bool prism_threat_bank_applies(int gems, int d, int chan)
{
	const int t = d + chan;
	int n = 0;
	for (const auto& e : W.enemies)
		n += cheb(e.pos, W.me.pos) <= PTB_SEE ? 1 : 0;
	for (const auto& e : W.enemies_far)
		n += cheb(e.pos, W.me.pos) <= PTB_SEE ? 1 : 0;
	if (n < PTB_N)
		return false;
	if (prism::nearest_known_enemy() <= t + PTB_SLACK)
		return false;
	return static_cast<bool>(prism::channel_not_doomed(gems, d, chan)); // PRISM_CHAN_MARGIN: the channel also outlasts channel_doomed's test
}
// PBK bit 2: the walk she really takes (the carrier field's altar, or the nearest one when it gives none), for the late bank's timing.
static int pbk_walk_she_takes(int d)
{
	const distance_field* f = bank_carrier_field(W.me.pos);
	const std::uint16_t ds = f ? dfget(*f, W.me.pos) : static_cast<std::uint16_t>(UNREACH);
	return ds != UNREACH ? static_cast<int>(ds) : d;
}
// ---- BANK: PC_HOLD, when she banks (PC_OWNER_BANK: she keeps her bag until the rule says bank)
bool prism_holds_bank(int gems, int d)
{
	if (pbl_bag > 0 && gems >= pbl_bag && now() - pbl_round <= PBL_AGE)
	{
		pc_hold_why = 2;
		return true; // the race-deadline bank holds until the bag goes in or is lost
	}
	pbl_bag = 0;
	const int chan = prism::channel_tick_count(gems);
	int why = 0;
	if (GAME_END - now() <= d + 25 + 2 * chan + PC_LATE && GAME_END - now() <= pbk_walk_she_takes(d) + 2 * chan + PC_LATE) // 25: bank_carrier_field's detour limit; the first test keeps her field unbuilt until it can matter
		why = 1;
	if (GAME_END - now() <= d + 2 * chan + PC_LATE)
		why = 1;
	else if (prism::foe_finishes_before_bank(d + chan) && prism::prism_can_win_race(gems, d + chan)) // bank while the race can still change, and only if a bank can win it
		why = 2;
	else if (gems >= PTB_BAG && prism_threat_bank_applies(gems, d, chan))
		why = 5; // the enemy team comes: the bag goes in while the channel can still finish
	else if (static_cast<long>(W.tributed_us) + gems + finish_mates_carried() >= 1000)
		why = 6; // her bag and my mates' bags win the game: the team's 'bank when we win'
	if (why == 2)
	{
		pbl_round = now();
		pbl_bag = gems;
	}
	pc_hold_why = why;
	return why != 0;
}
// ---- BANK: PC_CHAN_SAFE PC_CHAN_SAFE: a long channel needs a living mate within PCSF_MATE or no enemy champion known within PCSF_R
// for PCSF_AGE rounds
static bool prism_channel_unsafe()
{
	const int gems = static_cast<int>(W.me.gems);
	const int chan = prism::channel_tick_count(gems);
	if (chan <= PCSF_T || W.tributed_us + gems >= 1000 || GAME_END - now() <= bank_dist_here() + 2 * chan + PC_LATE)
		return false;
	for (const auto& al : W.allies)
		if (cheb(al.pos, W.me.pos) <= PCSF_MATE)
			return false;
	int nk = BIG;
	for (const auto& e : W.enemies)
		nk = std::min(nk, cheb(e.pos, W.me.pos));
	for (const auto& e : W.enemies_far)
		nk = std::min(nk, cheb(e.pos, W.me.pos));
	nk = std::min(nk, combat::nearest_foe_distance_seen(PCSF_AGE));
	if (nk > PCSF_R)
		return false;
	return static_cast<bool>(mu::mult_foe_hit_to_real_hp_alt(combat::foe_damage_over_ticks(PCSF_AGE, chan)) >= W.me.hp + W.me.shield);
}
} // namespace nova::econ
