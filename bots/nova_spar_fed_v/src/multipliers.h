#pragma once
// multipliers.h: Every emblem damage, gold and timer multiplier, in one place. One helper for every emblem damage / gold / time
// modifier, for my body, mates and foes (GameRules.md:277-336; engine-probed 20_interactions Q30-Q38, docs/rules/00_brief.md:4-5).
// Damage modifiers MULTIPLY: out v champions Skirmish x1.10 x Collectors (1 + .01 x families held, itself included); out v camps
// Monster x1.15 x Collectors; in from champions Durability x.90; in from camps Durability x.90 x Jungle x.70 (= x.63). HoR's low-HP
// bonus stays in combat passive_mult (hp / CURRENT max hp) and multiplies on top. Gold bonuses ADD (GameRules:335): 100 + Vesper 33
// + Treasure 10 percent. A second emblem of a family adds nothing (family bits, not counts). Runtime data flag MUL_TAB[1] (0 = off),
// read ONCE per turn in perceive into mu::bits (a plain int); every site tests mu::on(b) first (zero work at 0). Bits: 1 PAIR (the
// net pair factor attacker out x defender in, both directions, in lethal_burst_hit / lethal_burst_damage_sum's kill test / my_burst_m (kill_now) / spell_alone_kills);
// 2 FULL (eff_hp / Durability and passive_mult / Skirmish+Collectors on every body, both sides, everywhere; bit 1's explicit factor
// stands down under it); 4 COMING (unseen 'coming' mates at last-seen stats, econ grw_ls, not base x growth); 8 CAMP (econ camp
// side: my body and mates through one rule, Durability x Jungle in, Monster x Collectors out); 16 GOLD (gold value Treasure +
// Vesper, mate/foe Tribute channels, Home/Capture). 64 OCB2 (OCB bit 2: foe_of burst = basic + ONE cast, GameRules:116) and 128 BGX2
// (BGX bit 2: dash middles, Q42) at run time (their tables are constexpr). 256 CTH: mv::camp_threat (walk/flee camp zones, danger,
// capture stays) x my camp-hit factor, the econ sites that already multiply it (incoming_at, cbl_pred) stand down. 512 HOR (below).
// 2048 FGR: unseen foes in econ foe_strength_lazy projected at their own growth since first sight (intel team_body_pred). 1024 CMATE: the
// mates' camp factors in econ build_team (default off). 32 FOEOF (foe_of's burst and dps x the foe's emblem factor on me). Families:
// my own from prism (10-round cache), others rs::families OR-ed over reads (emblems are only ever bought: last-seen).
#include <cstdint>
#include "world.h"
#include "plan.h"
#include "rules.h"
#include "mapinfo.h"
#include "champ_tavi.h"
#include "champ_vesper.h"

#define MUL_BITS 970
inline constexpr int MUL_TAB[2] = { 0x4D554C31, MUL_BITS };
// MFX: runtime data flag, 0 = off; every bit needs MUL bit 2 FULL (mu::mfx is 0 without it). Under FULL, hits and eff_hp are in
// pre-Durability units (eff_hp = (hp + shield) / .9), hp + shield and camp_threat (bit 256 CTH: x Durability x Jungle) in real HP. A
// sum must stay in one unit. Bit 1 CAMP: my camp drain taken from an eff_hp health (assess, PEEL) goes real -> pre-Durability (x
// mi_inv; needs CTH), else Durability counts twice. Bit 2 FOE: foe hits compared with real hp + shield go pre-Durability -> real (x
// mi), else Durability is dropped (damage_in, capture hold, the channel checks). Bit 4 MATE: a mate's camp hits (raw Strength) taken
// from its eff_hp health: x its camp-in factor x mi_inv (Durability cancels, its Jungle .7 applies; bit 1024 CMATE stays off). Bit 8
// FAM (GameRules:337): a failed emblem read (rc 97, out of my sight) does not start the 60-round wait (retry in 3 rounds), a body
// back in sight after a gap is re-read (foes shop unseen), and a read replaces the bits (Tavi sells emblems) instead of OR-ing them.
// Bit 16 SHIELD: add_friend's ready shield (real HP) joins an eff_hp health: x mi_inv, as eff_hp treats a standing shield. Bits 32
// HPUS (brain team health), 64 SUPPOS (support tile score against f.burst), 128 SUPFOC (support retreat against a.incoming), 256 PRA
// (pair health against mates' eff_hp): my hp + shield read at a site whose other side is pre-Durability: eff_hp instead. Bit 512
// FUL: the same for FUL's bare health (no shield there): hp x mi_inv. Bit 1024 FOE2: bit 2's rule at the other sites (prism
// channel_damage_threat, econ foe_damage_over_ticks, channel_survives_known_foes). Bit 2048 FAMG: a gap in sight that the 3-round floor blocks stays pending, so the body is
// still re-read.
#define MFX_BITS 4095
inline constexpr int MFX_TAB[2] = { 0x4D465831, MFX_BITS };
#define MFX_CNT(k, c) ((void)0) // fire count: the diag copy records site k when c (new answer != old); release: nothing, c unevaluated

namespace nova::prism
{
std::uint32_t my_families(); // champ_prism.cc: my emblem family bits (has_family's cache)
}

namespace nova::mu
{
// bits (common.h): MUL_TAB[1], copied once per turn by perceive
inline bool on(int b) { return (bits & b) != 0; }
constexpr int B_PAIR = 1, B_FULL = 2, B_COMING = 4, B_CAMP = 8, B_GOLD = 16, B_FOEOF = 32, B_OCB2 = 64, B_BGX2 = 128, B_CTH = 256, B_HOR = 512, B_CMATE = 1024, B_FGR = 2048;
constexpr int CHAMP = 0, CAMP = 1;  // vs kind
constexpr int OUT = 0, IN = 1;      // damage dealt by the body / taken by the body
constexpr int F_DUR = 2, F_JUNGLE = 4, F_SKIRMISH = 11, F_COLLECTORS = rs::F_COLLECTORS;

// The rule arithmetic: the body's damage multiplier for (vs, q) from its family bits. Every product is a compile-time table
// (constexpr, the same float operations in the same order as the formula, so the values are bit-identical); rule() is an index and
// one load. The one engine-read input (Monster's magnitude, rs::rules().monster_pct) falls back to the formula when it ever differs
// from the rule value the table was built on.
constexpr int MU_MON_PCT = rs::Rules{}.monster_pct; // 15 (GameRules.md:305), the table's value
struct MuOutTab
{
	float v[2][2][2][16]; // [vs][Skirmish][Monster][Collectors' family count, 0 = no Collectors]
};
struct MuInTab
{
	float v[2][2][2]; // [vs][Durability][Jungle]
};
constexpr MuOutTab make_mult_out_table()
{
	MuOutTab t{};
	for (int vs = 0; vs < 2; ++vs)
		for (int sk = 0; sk < 2; ++sk)
			for (int mon = 0; mon < 2; ++mon)
				for (int c = 0; c < 16; ++c)
				{
					float m = 1.0f;
					if (vs == CAMP)
						m = rs::camp_out_k(mon != 0, MU_MON_PCT, c); // Monster x Collectors, :305, :318
					else
					{
						if (sk)
							m *= 1.10f; // GameRules.md:316
						if (c)
							m *= rs::collectors_k(c); // Collectors (GameRules.md:318)
					}
					t.v[vs][sk][mon][c] = m;
				}
	return t;
}
constexpr MuInTab make_mult_in_table()
{
	MuInTab t{};
	for (int vs = 0; vs < 2; ++vs)
		for (int d = 0; d < 2; ++d)
			for (int j = 0; j < 2; ++j)
			{
				float m = 1.0f;
				if (d)
					m *= 0.90f; // :307, camps too
				if (vs == CAMP && j)
					m *= 0.70f; // Jungle (GameRules.md:309)
				t.v[vs][d][j] = m;
			}
	return t;
}
inline constexpr MuOutTab MU_OUT = make_mult_out_table();
inline constexpr MuInTab MU_IN = make_mult_in_table();
// The formula (the table's definition; also the fallback for a Monster magnitude the table was not built on).
inline float emblem_multiplier_formula(std::uint32_t fam, int vs, int q)
{
	float m = 1.0f;
	if (q == OUT)
	{
		if (vs == CAMP)
			return rs::camp_out_mult(fam); // Monster x Collectors, :305, :318
		if (rs::has(static_cast<std::uint16_t>(fam), F_SKIRMISH))
			m *= 1.10f; // GameRules.md:316
		if (rs::has(static_cast<std::uint16_t>(fam), F_COLLECTORS))
			m *= rs::collectors_k(__builtin_popcount(fam & 0x3FFFu)); // Collectors (GameRules.md:318)
	}
	else
	{
		if (rs::has(static_cast<std::uint16_t>(fam), F_DUR))
			m *= 0.90f; // :307, camps too
		if (vs == CAMP && rs::has(static_cast<std::uint16_t>(fam), F_JUNGLE))
			m *= 0.70f; // Jungle (GameRules.md:309)
	}
	return m;
}
inline float rule(std::uint32_t fam, int vs, int q)
{
	const int v = vs & 1;
	if (q == OUT)
	{
		const int mon = static_cast<int>((fam >> rs::F_MONSTER) & 1u);
		if (v == CAMP && mon && rs::rules().monster_pct != MU_MON_PCT) [[unlikely]]
			return emblem_multiplier_formula(fam, vs, q);
		const int c = ((fam >> F_COLLECTORS) & 1u) != 0 ? __builtin_popcount(fam & 0x3FFFu) : 0;
		return MU_OUT.v[v][(fam >> F_SKIRMISH) & 1u][mon][c];
	}
	return MU_IN.v[v][(fam >> F_DUR) & 1u][(fam >> F_JUNGLE) & 1u];
}
// Heart of Ruin's passive (GameRules.md:816): 1 + .5 x missing share of the current max HP, shields not counted. The one live
// factor: always from the body's current hp (never cached). Bit 512 routes kit_dps's flat x1.12 (combat body_dps) and econ's
// clear-average multiplier (x1.12 at full health) through it. Heart of Ruin's own factor: heart_layer::damage_mult (champ_heart.h).
// Family bits come from econ's own-item flags (econ refresh_owned).
inline std::uint32_t own_fam(bool jungle, bool durab, bool monster)
{
	return (jungle ? 1u << F_JUNGLE : 0u) | (durab ? 1u << F_DUR : 0u) | (monster ? 1u << rs::F_MONSTER : 0u);
}
// Gold multiplier (percent points ADD, GameRules.md:335, :532): 100 + Vesper 33 + Treasure 10.
inline float gold_mult(std::uint32_t fam, int vv_pct) { return rs::gold_mult(fam, vv_pct); } // rules.h

// Champion-damage emblem code (1 byte on each Body): Durability bit 0, Skirmish bit 1, Collectors' family count << 2.
inline std::uint8_t code_of(std::uint32_t f)
{
	const int col = rs::has(static_cast<std::uint16_t>(f), F_COLLECTORS) ? __builtin_popcount(f & 0x3FFFu) : 0;
	return static_cast<std::uint8_t>((rs::has(static_cast<std::uint16_t>(f), F_DUR) ? 1 : 0) | (rs::has(static_cast<std::uint16_t>(f), F_SKIRMISH) ? 2 : 0) | (col << 2));
}
// code -> multipliers (taken, 1 / taken, dealt against champions) and the attacker x defender pair product: compile-time tables (the
// same float operations as a runtime fill, so bit-identical).
struct MuCodeTab
{
	float in[128], inv[128], out[128];
	float pair[128][2]; // [attacker code][defender Durability bit]: out x in
};
constexpr MuCodeTab make_mult_code_table()
{
	MuCodeTab t{};
	for (int c = 0; c < 128; ++c)
	{
		t.in[c] = (c & 1) ? 0.90f : 1.0f;
		t.inv[c] = 1.0f / t.in[c];
		t.out[c] = ((c & 2) ? 1.10f : 1.0f) * ((c >> 2) ? 1.0f + 0.01f * static_cast<float>(c >> 2) : 1.0f);
	}
	for (int a = 0; a < 128; ++a)
		for (int d = 0; d < 2; ++d)
			t.pair[a][d] = t.out[a] * t.in[d];
	return t;
}
inline constexpr MuCodeTab MU_CODE = make_mult_code_table();

// Last-seen family bits of another champion (OR-ed without MFX bit 8; Tavi can sell, so bit 8 replaces), with their code (written on
// each read: the event).
struct FamMem
{
	std::uint32_t h = 0;
	std::uint32_t fam = 0;
	int at = -1000;
	std::uint8_t code = 0;
	int seen = -1000; // MFX bit 8: the round perceive last had the body in sight
};
inline FamMem fam_mem[16];
inline int mfx = 0; // MFX_TAB[1] under bit 2 FULL, else 0: copied once per turn
inline int n_read = 0; // diag: SDK family reads (sighting, shop, 60-round refresh)
// One SDK read of h's emblem families (needs the item read to succeed; false otherwise). No enum_map zero fill (336 bytes of
// memory.fill = 336 fuel a read): the host writes all 84 counts or fails (then nothing is read). Emblem ids are the odd ones (6 x
// family + 2 x stat + 1).
inline bool read_fam(std::uint32_t h, std::uint32_t& out)
{
	FxmItems cnt;
	++n_read;
	if (cambc::detail::sdk_champion_items(h, cnt.v.data()) != 0)
		return false;
	std::uint32_t b = 0;
	for (std::uint32_t i = 1; i < 84u; i += 2)
		b |= (cnt.v[i] > 0 ? 1u : 0u) << (i / 6);
	out = b;
	return true;
}
// h's memory slot (probe from h & 15; h is never stored past an empty slot; a full table reuses h & 15). A new slot is read at
// once (first sighting); `fresh` says so.
inline FamMem& fam_slot(std::uint32_t h, int now, bool& fresh)
{
	FamMem* fill = nullptr;
	for (std::uint32_t k = 0; k < 16u; ++k)
	{
		FamMem& m = fam_mem[(h + k) & 15u];
		if (m.h == h && m.at > -1000)
		{
			fresh = false;
			return m;
		}
		if (m.at <= -1000)
		{
			fill = &m;
			break;
		}
	}
	if (!fill)
		fill = &fam_mem[h & 15u];
	std::uint32_t f = 0;
	fill->h = h;
	const bool ok = read_fam(h, f);
	fill->fam = ok ? f : 0u;
	fill->at = (mfx & 8) != 0 && !ok ? now - 57 : now; // MFX bit 8: a failed read retries in 3 rounds
	fill->code = code_of(fill->fam);
	fresh = true;
	return *fill;
}
inline void fam_reread(FamMem& m, int now)
{
	std::uint32_t f = 0;
	const bool ok = read_fam(m.h, f);
	if ((mfx & 8) != 0) // MFX bit 8: replace on a read; a failed read retries in 3 rounds
	{
		MFX_CNT(8, ok && f != m.fam);
		MFX_CNT(9, !ok);
		if (ok)
			m.fam = f;
		m.at = ok ? now : now - 57;
	}
	else
	{
		if (ok)
			m.fam |= f;
		m.at = now;
	}
	m.code = code_of(m.fam);
}
// Emblems change only on a shop, i.e. on the body's spawn (a dead body respawns there) or anywhere for Tavi. So a body is re-read
// when perceive sees it where it can shop (`shop`, at most every 3 rounds), else only every 60 rounds (a safety refresh). Bits are
// OR-ed unless MFX bit 8 is on (Tavi can sell: a read replaces).
inline std::uint32_t fam_of(std::uint32_t h, int now, bool shop = false)
{
	if (h == W.me.h)
		return prism::my_families();
	bool fresh = false;
	FamMem& m = fam_slot(h, now, fresh);
	if (!fresh && (now - m.at >= 60 || (shop && now - m.at >= 3)))
		fam_reread(m, now);
	return m.fam;
}
// A team slot's families (mine exact, a mate last-seen).
// Fuel (gate g13473b6e: cut-offs 1.41x with the set on): a per-round cache per slot, so the hot econ loops (group_value per group,
// build_team per slot) read an array, not fam_of's 16-slot scan.
inline int sf_round[8] = { -1, -1, -1, -1, -1, -1, -1, -1 };
inline std::uint32_t sf_val[8] = {};
inline std::uint32_t slot_fam(int s, int now)
{
	if (s < 0 || s >= P.n || s >= 8)
		return 0;
	const auto i = static_cast<std::size_t>(s);
	if (sf_round[i] == now)
		return sf_val[i];
	sf_round[i] = now;
	sf_val[i] = s == P.my_slot ? prism::my_families() : fam_of(P.handle[i], now);
	return sf_val[i];
}

// Bit 8 CAMP: my body's camp-side multiplier (q IN: camp hits on me, Durability x Jungle; OUT: my hits on camps, Monster x
// Collectors). Cached per round (my families: prism's 10-round cache), the products recomputed only when my families changed.
inline int myc_round = -1;
inline std::uint32_t myc_f = 0xFFFFFFFFu;
inline float myc_v[2] = { 1.0f, 1.0f };
inline float my_camp(int q)
{
	if (myc_round != W.round)
	{
		myc_round = W.round;
		const std::uint32_t f = prism::my_families();
		if (f != myc_f)
		{
			myc_f = f;
			myc_v[OUT] = rule(f, CAMP, OUT);
			myc_v[IN] = rule(f, CAMP, IN);
		}
	}
	return myc_v[q & 1];
}
// Bit 16 GOLD/TIME: slot s's gold multiplier (Vesper 33 + Treasure 10 points, added) and whether a body holds Tribute. Cached: the
// value per slot per round (group_value asks it per group), keyed on vv too.
inline int sg_round[8] = { -1, -1, -1, -1, -1, -1, -1, -1 };
inline int sgv_vv[8] = {}; // SGV bit 1: the Vesper value is 33, so a bool key never matched and the cache never hit for a Vesper slot
inline float sg_val[8] = {};
inline float slot_gold(int s, int vv)
{
	if (s < 0 || s >= 8) [[unlikely]]
		return gold_mult(slot_fam(s, W.round), vv);
	const auto i = static_cast<std::size_t>(s);
	if (sg_round[i] != W.round || sgv_vv[i] != vv)
	{
		sg_round[i] = W.round;
		sgv_vv[i] = vv;
		sg_val[i] = gold_mult(slot_fam(s, W.round), vv);
	}
	return sg_val[i];
}
// What a slot's holder is paid on every gold source: Vesper's passive and the holder's Treasure, adding (GameRules.md:335;
// interactions.md:85). Capture gold, Prospector's gold and Marcella's tribute gold all go through it (interactions.md:87, 88).
inline float holder_gold_mult(int s)
{
	if (s < 0 || s >= P.n) [[unlikely]]
		return 1.0f;
	return slot_gold(s, vesper_layer::gold_pct(&kit_of(P.type[static_cast<std::size_t>(s)])));
}
inline bool holds_prospector(int s) { return rs::has(static_cast<std::uint16_t>(slot_fam(s, W.round)), rs::F_PROSPECTOR); }
inline int n_gold = 0, n_trib = 0, n_time = 0; // diag: bit 16 sites reached with a modifier that changes the number
// Per-turn per-body cache: perceive writes each visible body's champion code onto it once (bits 1|2|32 only).
inline int n_fill = 0, n_fill_mod = 0; // diag: bodies filled, bodies with a modifier != 1
inline float mi(const Body& b) { return MU_CODE.in[b.mc & 127]; }
inline float mi_inv(const Body& b) { return MU_CODE.inv[b.mc & 127]; }
// Effective HP against champion damage: hp + shield (shields absorb the reduced hit), / Durability under bit 2 FULL. combat::eff_hp
// and every hand-written hp + shield (ruleslint EFFHP) read this one function.
inline float ehp(const Body& b)
{
	const float h = b.hp + b.shield;
	if ((bits & B_FULL) != 0) [[unlikely]]
		return h * MU_CODE.inv[b.mc & 127];
	return h;
}
inline float mo(const Body& b) { return MU_CODE.out[b.mc & 127]; }
// My code: from my families (prism's cache), recomputed only when they changed.
inline std::uint32_t mym_f = 0xFFFFFFFFu;
inline std::uint8_t mym_c = 0;
inline std::uint8_t my_code()
{
	const std::uint32_t f = prism::my_families();
	if (f != mym_f)
	{
		mym_f = f;
		mym_c = code_of(f);
	}
	return mym_c;
}
// The code comes from the memory slot (written on each read); the shop test (Tavi, or on its spawn) is evaluated only when a re-read
// is possible (3 rounds since the last one), the same read schedule as fam_of(h, now, shop).
inline void fill(Body& b, int now, bool sighted = true)
{
	if (b.h == W.me.h)
		b.mc = my_code();
	else
	{
		bool fresh = false;
		FamMem& m = fam_slot(b.h, now, fresh);
		const int age = now - m.at;
		bool gap = false;
		if ((mfx & 8) != 0 && sighted) // MFX bit 8: back in sight after a gap
		{
			gap = now - m.seen > 1;
			if (!gap || age >= 3 || fresh || (mfx & 2048) == 0) // bit 2048: a blocked gap stays pending
				m.seen = now;
			else
				MFX_CNT(2048, true);
		}
		if (!fresh && age >= 3 && (gap || age >= 60 || tavi_layer::fam_reread(b.type) || bbget(b.ally ? M.my_spawn : M.enemy_spawn, b.pos)))
			fam_reread(m, now);
		b.mc = m.code;
	}
	++n_fill;
	n_fill_mod += b.mc != 0 ? 1 : 0;
}
__attribute__((noinline)) inline void perceive_fill_slow(int now)
{
	W.me.mc = my_code();
	++n_fill;
	n_fill_mod += W.me.mc != 0 ? 1 : 0;
	for (auto& b : W.allies)
		fill(b, now);
	for (auto& b : W.enemies)
		fill(b, now);
	for (auto& b : W.enemies_far)
		fill(b, now);
}
inline float mult_camp_hit_to_eff_hp(float ct) // bit 1 CAMP: real camp damage on me -> eff_hp units
{
	if ((mfx & 1) == 0 || (bits & B_CTH) == 0)
		return ct;
	const float v = ct * mi_inv(W.me);
	MFX_CNT(1, v != ct);
	return v;
}
inline float mult_foe_hit_to_real_hp(float raw) // bit 2 FOE: pre-Durability foe hits on me -> real HP
{
	if ((mfx & 2) == 0)
		return raw;
	const float v = raw * mi(W.me);
	MFX_CNT(2, v != raw);
	return v;
}
inline float mult_mate_camp_hit_to_eff_hp(const Body& b, float ch) // bit 4 MATE: a mate's raw camp hits -> its eff_hp units
{
	if ((mfx & 4) == 0)
		return ch;
	const float v = ch * rule(fam_of(b.h, W.round), CAMP, IN) * mi_inv(b);
	MFX_CNT(4, v != ch);
	return v;
}
inline float mult_shield_to_eff_hp(const Body& b, float sh) // bit 16 SHIELD: a real shield -> eff_hp units
{
	if ((mfx & 16) == 0)
		return sh;
	const float v = sh * mi_inv(b);
	MFX_CNT(16, v != sh);
	return v;
}
inline float mult_my_health_eff_hp(int bit) // bits 32..256: my health at a site in eff_hp units
{
	const float h = W.me.hp + W.me.shield;
	if ((mfx & bit) == 0)
		return h;
	const float v = ehp(W.me);
	MFX_CNT(bit, v != h);
	return v;
}
inline float mult_foe_hit_to_real_hp_alt(float raw) // bit 1024 FOE2: pre-Durability foe hits on me -> real HP
{
	if ((mfx & 1024) == 0)
		return raw;
	const float v = raw * mi(W.me);
	MFX_CNT(1024, v != raw);
	return v;
}
inline void perceive_fill(int now)
{
	bits = MUL_TAB[1];
	mfx = (bits & B_FULL) != 0 ? MFX_TAB[1] : 0;
	if ((bits & (B_PAIR | B_FULL | B_FOEOF)) != 0) [[unlikely]]
		perceive_fill_slow(now);
	if ((bits & B_CTH) != 0) [[unlikely]]
		ct_k = my_camp(IN); // once per turn (my families: prism's 10-round cache)
}
// The one champion damage query: body b's multiplier against champions (q OUT: dealt; IN: taken). 1 unless perceive filled it.
inline float mult(const Body& b, int q) { return q == OUT ? mo(b) : mi(b); }
// The pure net pair factor on damage attacker a deals to defender d, champion against champion: a's Skirmish x Collectors x d's
// Durability, from the bodies' emblem codes (perceive_fill writes them when bits 1|2|32 are on; otherwise both codes are 0 and the
// factor is 1). One compile-time product (MU_CODE.pair). Under bit 2 FULL both halves already live elsewhere (the attacker's
// Skirmish x Collectors in passive_mult, the defender's Durability in eff_hp = (hp + shield) / .9, i.e. damage x .9 before the
// shield absorbs), so the pair factor is 1 there; a caller that multiplies passive_mult(a) x pair_k(a, d) against eff_hp(d) would
// otherwise count Skirmish/Collectors twice and Durability twice.
inline float pair_k(const Body& a, const Body& d) { return (bits & B_FULL) != 0 ? 1.0f : MU_CODE.pair[a.mc & 127][d.mc & 1]; }
// Bit 1 PAIR: the net factor on damage attacker a deals to defender d (a's Skirmish/Collectors x d's Durability). 1 when bit 2 FULL
// is on (eff_hp / passive_mult already carry both halves) or bit 1 is off.
inline float pair(const Body& a, const Body& d) { return (bits & (B_PAIR | B_FULL)) == B_PAIR ? pair_k(a, d) : 1.0f; }
// Bit 32 FOEOF: foe_of's dps / burst (danger_at, in_reach, the ratio) carry the foe's Skirmish/Collectors x my Durability; 1 under
// bit 2 FULL (passive_mult / eff_hp carry them there).
inline float foe_in(const Body& e) { return (bits & B_FULL) == 0 ? mo(e) * mi(W.me) : 1.0f; }
} // namespace nova::mu
