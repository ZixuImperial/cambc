#pragma once
// rules.h: Game rule values, read from the engine where possible; gold, capture, tribute and recall formulas. The bot models four
// engine 2.0.0 rules as the engine plays them and reads the rule numbers from the SDK. Master switch RULES_SYNC, one integer
// sub-switch per fix (each .cpp that uses a switch includes this header; never #if on a float define): RS_C1 Tribute emblem channel:
// ceil(0.67 t), t = max(1, ceil(G/10)), for the holder (not (2t+2)/3, which is 1 short when 3 | t). RS_C2 Monster emblem: +15%
// damage to camps (not +10%). RS_C3 Capture emblem: the holder's capture pays at r+4, not r+6 (timer capped at 3); recall, hold,
// rates, enemy respawns. RS_C3R an enemy on the region resets the capture timer (GameRules 194/206). Default 0: it never fired in
// the measured games. RS_C4 a death is priced by the killer's kit and items (kill gold 100, Hunter +50, Treasure +10%, VV +33%; a
// linked Cassi & Issac death pays one reward), not a flat 22. RS_K rule numbers from the SDK (cambc::constants, item passive
// magnitudes), range-checked; the literals otherwise. RS_DIAG (diag copies only, default 0): cheap integer records inside small
// debug_blocks, drained at turn end.
#include <algorithm>
#include <cmath>
#include <cstdint>
#include <cambc.h>


namespace rs
{
// item families (item id = 6 x family + 2 x stat + 1 for an emblem)
constexpr int F_MONSTER = 0, F_TREASURE = 3, F_HOME = 5, F_TRIBUTE = 7, F_CAPTURE = 8, F_PROSPECTOR = 9, F_HUNTER = 10;
constexpr int F_COLLECTORS = 13; // GameRules.md:318 (mu::F_COLLECTORS is this one)

struct Rules
{
	int capture_time = 5, capture_cap = 3, respawn = 60, recall = 5, kill_gold = 100, hunter_gold = 50, treasure_pct = 10,
	    vv_pct = 33, monster_pct = 15, dur_pct = 10 /* GameRules.md:307 Durability: 10% less incoming damage */, trib_per = 10, trib_base = 0, trib_min = 1, trib_keep = 67;
	int read = 0, bad = 0, diff = 0; // probe of values read from the engine: read, rejected (out of range: the literal stays), read != literal
	long raw[5] = { -1, -1, -1, -1, -1 }; // passive magnitudes x 1000: Monster, Treasure, Tribute, Capture, Hunter
};

inline int take(int lit, long v, long lo, long hi, Rules& r)
{
	++r.read;
	if (v < lo || v > hi)
	{
		++r.bad;
		return lit;
	}
	if (v != lit)
		++r.diff;
	return static_cast<int>(v);
}

inline double magnitude(int fam)
{
	return static_cast<double>(cambc::item_type(static_cast<std::uint32_t>(6 * fam + 1)).passive_magnitude());
}
inline Rules load_rules()
{
	Rules r;
	try
	{
		r.capture_time = take(5, cambc::constants::capture_time, 1, 20, r);
		r.respawn = take(60, cambc::constants::respawn_time, 1, 400, r);
		r.recall = take(5, cambc::constants::recall_time, 1, 20, r);
		r.kill_gold = take(100, static_cast<long>(cambc::constants::kill_gold), 0, 2000, r);
		r.trib_base = take(0, cambc::constants::submit_gem_base_duration, 0, 20, r);
		r.trib_min = take(1, cambc::constants::submit_gem_minimum_duration, 1, 20, r);
		const double mult = cambc::constants::submit_gem_duration_multiplier;
		const long per = mult > 0.0 ? std::lround(1.0 / mult) : 0;
		// ceil(G x mult) = ceil(G / per) only when 1/mult is a whole number (computed in integers: 30 x 0.1 > 3 in double)
		r.trib_per = per >= 1 && std::fabs(mult * static_cast<double>(per) - 1.0) < 1e-6 ? take(10, per, 1, 100, r) : take(10, -1, 1, 100, r);
		const int fam[5] = { F_MONSTER, F_TREASURE, F_TRIBUTE, F_CAPTURE, F_HUNTER };
		for (int i = 0; i < 5; ++i)
			r.raw[i] = std::lround(1000.0 * magnitude(fam[i]));
		r.monster_pct = take(15, std::lround(r.raw[0] / 10.0), 0, 100, r);    // 0.15: +15% damage to camps
		r.treasure_pct = take(10, std::lround(r.raw[1] / 10.0), 0, 100, r);   // 0.10: +10% gold
		r.trib_keep = take(67, 100 - std::lround(r.raw[2] / 10.0), 1, 100, r); // 0.33: the channel keeps 67%, rounded up
		r.capture_cap = take(3, std::lround(r.raw[3] / 1000.0), 1, 5, r);     // 3: the timer is capped at 3 rounds
		r.hunter_gold = take(50, std::lround(r.raw[4] / 1000.0), 0, 500, r);  // 50: +50 kill gold
	}
	catch (...)
	{
		++r.bad;
	}
	return r;
}

inline const Rules& rules()
{
	static const Rules r = load_rules();
	return r;
}
// Tribute channel length in owner turn ends for a bag of `gems` (rule: max(min, base + ceil(G x mult)); the Tribute emblem holder
// ceil(0.67 t)). Integers only. The same formula as the econ tribute channel-ticks helper.
inline int tribute_turns(int gems, bool holder)
{
	const Rules& r = rules();
	const int g = std::max(0, gems);
	int t = std::max(r.trib_min, r.trib_base + (g + r.trib_per - 1) / r.trib_per);
	if (holder)
		t = std::max(1, (r.trib_keep * t + 99) / 100);
	return t;
}
// Recall rounds from the decision to acting on spawn, exact by the rule (GameRules.md:275, :310): 5 countdown ticks (Home: 50%
// shorter rounded up, 3), execute at the next own turn start; a recall pre-fired at the previous turn end (the spin, kept) has one
// tick done: 4, Home 2.
inline int recall_rounds(bool home, bool prefired)
{
	const int base = rules().recall;
	const int t = home ? (base + 1) / 2 : base;
	return prefired ? std::max(1, t - 1) : t;
}
// a tribute of `gems` (0 for no gems: no channel); else tribute_turns (ceil(G/10), min 1; Tribute emblem ceil(0.67 t), min 1).
inline int tribute_rounds(int gems, bool emblem) { return gems > 0 ? tribute_turns(gems, emblem) : 0; }
// Rounds from the first turn a capturer sees itself on a cleared region (cap_on = step + 1) to the round after the reward: the
// reward lands at step + 1 + capture_time (non-holder), step + 1 + cap (an allied Capture holder from the start). The +1 is slack.
// Capture rounds left for `remaining` timer rounds; a Capture holder on the region caps the remaining time at capture_cap (3) and
// never raises it.
inline int capture_rounds(int remaining, bool holder)
{
	return holder ? std::min(rules().capture_cap, remaining) : remaining;
}
inline int capture_pay(bool holder)
{
	const Rules& r = rules();
	return 1 + capture_rounds(r.capture_time, holder);
}
// (rulestables/capture.csv): an allied Capture holder joins the region j rounds after the step-on round R (j >= 1; j = 0 is
// capture_pay(true)): the reward lands at R + min(6, max(4, j + 3)); the value counts from the timer's start (R + 1) to the round
// after the reward, as capture_pay. Equals 1 + (j - 1) + capture_rounds(capture_time - (j - 1), true) for j >= 1.
inline int capture_join_pay(int j)
{
	return std::min(capture_pay(false), std::max(capture_pay(true), j + rules().capture_cap));
}
// a champion's respawn: rules().respawn own turn-end ticks, the first at its turn end in the death round when it died before its own
// turn there (back at D + respawn), else in D + 1 (D + respawn + 1). Rounds from the first own turn that sees it dead: respawn in
// both cases. Camps: MapInfo g.respawn (SDK max_respawn_timer) is the per-group value.
inline int champ_respawn_rounds() { return rules().respawn; }

// Emblem families held by another champion (bit f = family f), read through the SDK (needs vision) and cached 10 rounds per handle;
// a failed read keeps the last bits (0 if never read) and retries in 5 rounds.
struct FamSlot
{
	std::uint32_t h = 0;
	int at = -100000;
	std::uint16_t bits = 0;
	bool used = false;
};
inline FamSlot fam_cache[16];
inline std::uint8_t fam_hint[32] = {};
inline std::uint8_t fam_hint_of(std::uint32_t h) { return fam_hint[h & 31u]; }
inline std::uint32_t fam_chg = 0; // fuel-cut bit 8: counts writes that change a slot's handle or bits
// fuel-cut bit 8: the first round families(h, ..) would read again (0: no entry). Cache state only, no rule.
inline int fam_until(std::uint32_t h)
{
	const FamSlot& q = fam_cache[fam_hint_of(h)];
	if (q.used && q.h == h)
		return q.at + 10;
	for (const auto& c : fam_cache)
		if (c.used && c.h == h)
			return c.at + 10;
	return 0;
}
inline std::uint16_t families(std::uint32_t h, int now)
{
	const FamSlot& q = fam_cache[fam_hint[h & 31u]];
	if (q.used && q.h == h && now - q.at < 10)
		return q.bits;
	FamSlot* s = nullptr;
	FamSlot* oldest = &fam_cache[0];
	{
		FamSlot& q = fam_cache[fam_hint[h & 31u]];
		if (q.used && q.h == h)
			s = &q;
	}
	if (!s)
	for (auto& c : fam_cache)
	{
		if (c.used && c.h == h)
		{
			s = &c;
			break;
		}
		if (!c.used || c.at < oldest->at)
			oldest = &c;
	}
	if (s && now - s->at < 10)
	{
		fam_hint[h & 31u] = static_cast<std::uint8_t>(s - fam_cache);
		return s->bits;
	}
	std::uint16_t b = 0;
	std::uint32_t c[84];
			if (cambc::detail::sdk_champion_items(h, c) != 0)
			{
				if (s)
					s->at = now - 5;
				return s ? s->bits : 0;
			}
			std::uint32_t acc = 0;
	#pragma clang loop unroll(full)
			for (std::uint32_t f = 0; f < 14u; ++f)
				acc |= static_cast<std::uint32_t>((c[6 * f + 1] | c[6 * f + 3] | c[6 * f + 5]) != 0u) << f;
			b = static_cast<std::uint16_t>(acc);
	if (!s || s->bits != b)
		++fam_chg;
	if (!s)
		s = oldest;
	s->h = h;
	s->at = now;
	s->bits = b;
	s->used = true;
	fam_hint[h & 31u] = static_cast<std::uint8_t>(s - fam_cache);
	return b;
}

inline bool has(std::uint16_t bits, int fam) { return ((bits >> fam) & 1u) != 0; }
// another champion's tribute channel length, with its Tribute emblem as last read (families(): needs vision, cached 10 rounds, the
// last bits kept while unseen).
inline int tribute_turns_of(int gems, std::uint32_t h, int now) { return tribute_turns(gems, has(families(h, now), F_TRIBUTE)); }

// Gold the killer earns for a champion kill (floored): (100 + Hunter 50) x (100% + VV 33 + Treasure 10 points).
// 100, 150, 110, 165, 133, 199, 214 for none, H, T, T+H, VV, VV+H, VV+T+H (BalanceChanges 2.0.0 table).
inline int kill_gold(std::uint16_t fam, int vv_pct)
{
	const Rules& r = rules();
	const int base = r.kill_gold + (has(fam, F_HUNTER) ? r.hunter_gold : 0);
	const int pct = 100 + vv_pct + (has(fam, F_TREASURE) ? r.treasure_pct : 0);
	return base * pct / 100;
}

// Monster's camp factor for pct points (GameRules.md:305), Collectors' factor for n unique completed families including itself
// (:318).
constexpr float monster_k(int pct) { return 1.0f + 0.01f * static_cast<float>(pct); }
constexpr float collectors_k(int n) { return 1.0f + 0.01f * static_cast<float>(n); }
// My damage on camps: Monster x Collectors, in this order (the float operations of MUL's constexpr table, multipliers.h make_mult_out_table).
constexpr float camp_out_k(bool monster, int mon_pct, int coll_n)
{
	float m = 1.0f;
	if (monster)
		m *= monster_k(mon_pct);
	if (coll_n)
		m *= collectors_k(coll_n);
	return m;
}
inline float camp_out_mult(std::uint32_t fam)
{
	const auto f = static_cast<std::uint16_t>(fam);
	return camp_out_k(has(f, F_MONSTER), rules().monster_pct, has(f, F_COLLECTORS) ? __builtin_popcount(fam & 0x3FFFu) : 0);
}
// The gold multiplier, percent points ADD (GameRules.md:335, :532): 100 + Vesper 33 + Treasure 10. mu::gold_mult wraps it.
inline float gold_mult(std::uint32_t fam, int vv_pct)
{
	const Rules& r = rules();
	return static_cast<float>(100 + vv_pct + (has(static_cast<std::uint16_t>(fam), F_TREASURE) ? r.treasure_pct : 0)) / 100.0f;
}
// an ability slot: cast in round C, next cast in round C + 8 (rulestables/cooldown.csv; a Vendetta kill resets both slots). The
// spell-cycle averages (spells / 8) divide by it.
inline constexpr int slot_cooldown() { return 8; }
// gold bonuses ADD (GameRules:335): x (1 + VV .33 + Treasure .10).
inline float gold_mult(bool vv, bool treasure)
{
	const Rules& r = rules();
	return 1.0f + 0.01f * static_cast<float>((vv ? r.vv_pct : 0) + (treasure ? r.treasure_pct : 0));
}
// a capture reward of `total` split among `n` receivers: an even share, the lowest champion ID (SDK handle) takes the integer
// remainder (GameRules:207).
inline int split_share(int total, int n, bool lowest)
{
	if (n <= 1 || total <= 0)
		return std::max(0, total);
	return total / n + (lowest ? total % n : 0);
}
// a gem cluster's reward and the Prospector holder's extra gems: 25% of its share of the group's cluster reward, floored once
// (GameRules:297; Q38: one cluster solo 7 -> 8, two 14 -> 17, shared by two 7 -> 8).
inline constexpr int gem_cluster_gems() { return 7; }
// a crystal hop in rounds, to a target dt walk steps past the landing: it lands 3 owner turn ends after the start and the body walks
// on the landing turn, so 3 + dt; a target on the landing itself takes 4 (GameRules.md:275, 329).
inline constexpr int crystal_hop(int dt) { return 3 + (dt >= 1 ? dt : 1); }
inline constexpr int gold_cluster_gold() { return 20; } // GameRules:187
inline constexpr int prospector_bonus(int share) { return share / 4; }
} // namespace rs

#define RSD(...) (void)0
