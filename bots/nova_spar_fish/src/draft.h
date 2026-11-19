// Draft v3: map analysis and the replicated map features on the first (10x fuel) turn, lineup values from the fitted
// table (team-size values, map slopes, composition terms judged on the whole lineup), a 1 pp near-tie band settled by
// the map evidence, explicit-regret pick order, and draft-memory encoding. No map identity, no fixed lineup or core,
// no counter terms: everything comes from the map's runtime features.
#pragma once
#include "common.h"

namespace nova::drafting {

#define PZB_NGCL 15
#define PZB_SH1000 393

// Kit-layer flags: see champ_ci.h.

#define MI_ALTD 17

// Swap cells: DSW_N cells of 7 ints {code, f1, lo1, hi1, f2, lo2, hi2}; a cell fires where every feature test with f > 0 holds (lo
// <= value <= hi). The first cell whose band holds and whose FROM is fielded without its TO wins; DSWAP (screen builds) takes
// precedence. Features: 1 team size, 2 area W*H, 3 s2s (spawn walk + 1; none = 9999), 4 altar tiles, 5 alt_d (walk to the nearest
// altar neighbour; none = 9999), 6 camp gold (one capture of every camp), 7 100 x gold / gems, 8 100 x cluster gem share, 9 100 x
// heavy gem share (groups with a camp of Strength >= 60), 10 camp groups, 11 hole %, 12 wall %, 13 gems. DSW_MASK (runtime data, bit
// k = cell k on); 0 = no cell fires.
#define DSW_N 8
// Cells: 0 VV->Varg on team size 3; 1 Vendetta->Marcella where camp gold == 0; 2-5 Vesper -> the first missing of Vendetta, Heart,
// Marcella, else Ryth where s2s <= 60; 6 Vendetta->Ryth on one altar tile. Order = priority (the first cell whose band holds wins an
// overlap). DSW_ALL: master switch: 0 = every cell off (data only, the same code).
#define DSW_ALL 1
// Rule cells, read after every live layer, in DSW format ({code, f1, lo1, hi1, f2, lo2, hi2}, first match wins). Extra features for
// these cells: 14 Tsup = 1000 / gems per round of our side + half of mid at respawn rate, 15 100 x gem share of groups with a golem
// or monolith, 16 100 x gem share of mid groups, 17 own-side-only Tsup, 18 1 if no altar is clearly ours. DXC_MASK 0 = off.
#define DXC_N 6
#define DXC_MASK 31
#define DXC0_C 22
#define DXC0_F1 14
#define DXC0_L1 394
#define DXC0_H1 99999
#define DXC0_F2 0
#define DXC0_L2 0
#define DXC0_H2 0
#define DXC1_C 37
#define DXC1_F1 13
#define DXC1_L1 0
#define DXC1_H1 0
#define DXC1_F2 0
#define DXC1_L2 0
#define DXC1_H2 0
#define DXC2_C 40
#define DXC2_F1 13
#define DXC2_L1 0
#define DXC2_H1 0
#define DXC2_F2 0
#define DXC2_L2 0
#define DXC2_H2 0
#define DXC3_C 33
#define DXC3_F1 13
#define DXC3_L1 0
#define DXC3_H1 0
#define DXC3_F2 0
#define DXC3_L2 0
#define DXC3_H2 0
#define DXC4_C 39
#define DXC4_F1 13
#define DXC4_L1 0
#define DXC4_H1 0
#define DXC4_F2 0
#define DXC4_L2 0
#define DXC4_H2 0
#define DXC5_C 0
#define DXC5_F1 0
#define DXC5_L1 0
#define DXC5_H1 0
#define DXC5_F2 0
#define DXC5_L2 0
#define DXC5_H2 0
inline constexpr int DXC_TAB[2 + 7 * DXC_N] = { 0x42383633, DXC_MASK,
	DXC0_C, DXC0_F1, DXC0_L1, DXC0_H1, DXC0_F2, DXC0_L2, DXC0_H2,
	DXC1_C, DXC1_F1, DXC1_L1, DXC1_H1, DXC1_F2, DXC1_L2, DXC1_H2,
	DXC2_C, DXC2_F1, DXC2_L1, DXC2_H1, DXC2_F2, DXC2_L2, DXC2_H2,
	DXC3_C, DXC3_F1, DXC3_L1, DXC3_H1, DXC3_F2, DXC3_L2, DXC3_H2,
	DXC4_C, DXC4_F1, DXC4_L1, DXC4_H1, DXC4_F2, DXC4_L2, DXC4_H2,
	DXC5_C, DXC5_F1, DXC5_L1, DXC5_H1, DXC5_F2, DXC5_L2, DXC5_H2 };
// Per-champion additive draft values in pp x 100 after every hand term. Order Ry VV Ve CI St Pr Ma Wi Re Va Ta HoR. ECDV_ON 0 = zero
// work.
#define ECDV_ON 1
#define ECDV_RY 0
#define ECDV_VV 0
#define ECDV_VE 0
#define ECDV_CI 0
#define ECDV_ST 0
#define ECDV_PR 0
#define ECDV_MA 0
#define ECDV_WI 0
#define ECDV_RE 0
#define ECDV_VA 600
#define ECDV_TA 0
#define ECDV_HOR 0
inline constexpr int ECDV_TAB[2 + 12] = { 0x45434456, ECDV_ON, ECDV_RY, ECDV_VV, ECDV_VE, ECDV_CI, ECDV_ST, ECDV_PR, ECDV_MA,
	ECDV_WI, ECDV_RE, ECDV_VA, ECDV_TA, ECDV_HOR };
#define DS_ARM 162
#define DS_ARM_F 1
#define DS_ARM_LO 3
#define DS_ARM_HI 3
#define DS_ARM_F2 0 // dr67b: optional second condition for cell 0 (feature, lo, hi; 0 = none)
#define DS_ARM_LO2 0
#define DS_ARM_HI2 0
// DSW cell 3 code on 3-body maps where its TO kit is not yet fielded (0 = off; 162 = Vesper -> Varg).
#define D3T 162
inline constexpr int D3T_TAB[2] = { 0x44335431, D3T };
#define DSW_MASK 254 // Cells 0-7 on (cell 7: Prism -> Vendetta where camp gems <= 60).
inline constexpr int DSW_TAB[2 + 7 * DSW_N] = { 0x44535743, DSW_ALL * (DSW_MASK),
	DS_ARM, DS_ARM_F, DS_ARM_LO, DS_ARM_HI, DS_ARM_F2, DS_ARM_LO2, DS_ARM_HI2,
	115, 6, 0, 0, 0, 0, 0,
	50, 0, 0, 0, 0, 0, 0,
	194, 0, 0, 0, 0, 0, 0,
	114, 0, 0, 0, 0, 0, 0,
	18, 3, 0, 60, 0, 0, 0,
	19, 4, 1, 1, 0, 0, 0,
	54, 13, 0, 60, 0, 0, 0 };

// One draft turn: always picks (falls back to the table's marginal values on any failure) and writes draft memory.
void play_draft();

} // namespace nova::drafting
