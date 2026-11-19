#pragma once
// item_upgrades.h: Item plan constants and upgrade flags (Power or Bruiser, build plans per strategy).
#define TB_MIN_PCT 30
// Runtime data flags (table magic 'PWL1'); 0 = off. Bruiser(X) = 5 X + 1 of each other stat; Power(X) = 6 X. On a kit whose Focus is
// worth ~0, Bruiser(X) v Power(X) is one shard of the other damage/Health stat against one more X: Power only pays on the stat with
// the higher marginal value. bit 1: kits with the per-kit measured value (measured Focus value per shard, % of a Strength shard)
// below the set minimum take Power, not Bruiser, for their Strength stat emblems; emblem_rank scores those Power entries like
// Bruiser (order unchanged). bit 4: the same kits take Power for their Health stat emblems too. bit 2: the shop tail's Health share
// per kit: the per-kit Health-share slot = 10 x (early + 1) + (late + 1), early = Health entries of the first 4 tail entries, late =
// Health entries of every later 4 (0..4); 0 = the default tail. bit 8: kits in the PWL_TK mask (1 << champion_type) take the main
// stat for the early Bruiser(Health) tank entry (melee path).
#define PWL_BITS 1
#define PWL_TK 0
#define PWL_FMIN 25
#define PWL_H0 0
#define PWL_H1 0
#define PWL_H2 0
#define PWL_H3 0
#define PWL_H4 0
#define PWL_H5 0
#define PWL_H6 0
#define PWL_H7 0
#define PWL_H8 0
#define PWL_H9 0
#define PWL_H10 0
#define PWL_H11 0
#define PWL_H12 0
inline constexpr int PWL_TAB[17] = { 0x50574C31, PWL_BITS, PWL_FMIN, PWL_H0, PWL_H1, PWL_H2, PWL_H3, PWL_H4, PWL_H5, PWL_H6,
	PWL_H7, PWL_H8, PWL_H9, PWL_H10, PWL_H11, PWL_H12, PWL_TK };
// KBD: a fixed head for one kit's build. Runtime data flags (KBD_TAB, magic 'KBD1'); 0 = off. bit 1: Willow's row; bit 2: Ren's row.
// A row is up to 6 emblems, each item id + 1 (family x 6 + stat x 2 + 1; stat 0 Strength, 1 Focus, 2 Health; 0 ends the row). The
// row goes to the front of make_build's list; a family already in the row leaves the rest of the list (Bruiser and Power: one entry
// of that stat), and emblem_rank leaves the row alone. Willow: Prospector Strength, Jungle Health. Ren: Bruiser Strength, Jungle
// Health, Durability Strength, Prospector Health, Skirmish Health.
#define KBD_BITS 1
#define KBD_W0 55
#define KBD_W1 29
#define KBD_W2 49
#define KBD_W3 19
#define KBD_W4 47
#define KBD_W5 0
#define KBD_R0 37
#define KBD_R1 29
#define KBD_R2 13
#define KBD_R3 59
#define KBD_R4 71
#define KBD_R5 0
inline constexpr int KBD_TAB[14] = { 0x4B424431, KBD_BITS, KBD_W0, KBD_W1, KBD_W2, KBD_W3, KBD_W4, KBD_W5, KBD_R0, KBD_R1, KBD_R2,
	KBD_R3, KBD_R4, KBD_R5 };
// Measured Focus value of one shard as % of one Strength shard, per champion_type (ryth, vesper, vendetta, cassi, issac, stellar,
// prism, marcella, willow, ren, varg, tavi, heart).
inline constexpr int PWL_FV[13] = { 100, 0, 0, 100, 0, 100, 100, 100, 100, 100, 100, 100, 100 };
                       // Health, then Bruiser only (no Power, no Monster); 2 main : 1 Health for ranged and Vesper Vale
#define ITM_ECON_N 2
#define ITM_RAID_N 2
#define ITM_CENTER_N 1
#define ITM_PROS_BASE_N 6
#define ITM_FORCE_PLAN -1 // tests only: -1 = the plan of strat::mode(); k = the plan of mode k whatever the game's mode
// Prospector's map gate: gem clusters hold >= ITM_CLU_MIN100 % of the camp gems in the groups on our half and the centre (contest <=
// 0.6, walk reachable, no monolith), and those groups hold >= ITM_GOLD_MIN gold (so it can be bought early).
#define ITM_CLU_MIN100 15
#define ITM_GOLD_MIN 200
