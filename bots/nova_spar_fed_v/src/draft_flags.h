#pragma once
// draft_flags.h: draft flags and tunables.

#define DRAFT_DASH_PP 4.0f
#define DRAFT_DASH_LO 0.05f
#define DRAFT_DASH_HI 0.30f
#define DRAFT_DASH_COST 6.0f // Rounds of dash cooldown charged to a trip that crosses holes.

// Dash-time term (draft only, map features only). Bit 1 (DTM_BIT_TIME): real turns from our spawn to the nearest altar and the
// value-weighted groups, walking v walking + dash, cooldown included (dash_walk_times). Bit 2 (DTM_BIT_SCORE, reads bit 1's result):
// dash kits except C&I gain, non-dashers except C&I lose, smoothly with how slow walking is and how much the dash saves
// (set_values). Slots: DTM_PP hundredths of a pp at x = 1, DTM_NON the walkers' loss in % of the dashers' gain, DTM_W0 the walking
// turns at which slowness is 1/2, DTM_WA the altar's weight in % (rest: groups). Bit 4 (DTM_BIT_KEEP): a hand swap (DSW cell) does
// not take a dash kit out for a walker where the term between them is at least DTM_KEEP hundredths of a pp. 0 = off.
#define DTM_BITS 31
#define DTM_PP 4000
#define DTM_NON 100
#define DTM_W0 40
#define DTM_WA 50
#define DTM_KEEP 1000
inline constexpr int DTM_TAB[7] = { 0x44544D31, DTM_BITS, DTM_PP, DTM_NON, DTM_W0, DTM_WA, DTM_KEEP }; // Draft: dash-time term.
constexpr int DTM_BIT_TIME = 1;
constexpr int DTM_BIT_SCORE = 2;
constexpr int DTM_BIT_KEEP = 4;
constexpr int DTM_BIT_VARG = 16; // Bit 16 moves Varg by dv h - dn (1 - h), h = heavy gem share: a walker on light maps, level with the dash kits on heavy ones.
constexpr int DTM_BIT_NORE = 8; // Ren takes no part in bit 8, like C&I.

// Ryth's draft value: see champ_ryth.h.
#define DRAFT_VA_PP 4.0f

// Gem-dominance draft layer. Integer switches only; N1_* are floats. Where the map's own draft features show gem_rate >=
// N1_GEM_RATIO x gold_rate (no map identity), VV gives way and C&I (and Prism) come in by gem dominance: VV +N1_E_VV x e, C&I
// +N1_E_CI x e, Prism +N1_E_PR x eR, with eR = ramp(ln((gem_rate + 5) / (0.1 gold_rate + 5)); N1_R_LO -> N1_R_HI), eG =
// ramp(gold_rate; N1_G_HI -> N1_G_LO), e = max(eR, eG). C&I's centrality bonus is scaled by e and the small-map C&I ban made
// N1_CI_SMALL x (1 - eG). Prism never goes in Marcella's slot (lineups with Prism and without Marcella get -N1_PRMA).
#define N1_GEM_RATIO 0.4f
#define N1_G_LO 60.0f
#define N1_G_HI 80.0f
#define N1_R_LO 0.8f
#define N1_R_HI 2.2f

// N1_E_VV is in champ_vesper.h; N1_E_CI and N1_CI_SMALL are in champ_ci.h.
#define N1_E_PR 9.5f
#define N1_PRMA 6.0f

// DXS (b1709, from b1669): at DXC cell 0 (Prism -> Ryth) Prism stays iff V_P + E - W p >= V_R, p = clamp((f16 - L) / (H - L)), f16 = 100 x gem share of
// mid groups (swap_feature 16). Map features only. Bit 1 = the term. E, W in tenths of lineup value. 0 = the cell as the table says.
#define DXS_BITS 1
#define DXS_E10 130
#define DXS_W10 180
#define DXS_L 55
#define DXS_H 100
inline const volatile int DXS_TAB[6] = { 0x44585331, DXS_BITS, DXS_E10, DXS_W10, DXS_L, DXS_H }; // slot 0 magic keeps it out of .bss
#define DXS_ON(b) ((DXS_TAB[1] & (b)) != 0)

// CIM (b1741, spec_cim_1109): C&I drafted more, map features only. Bit 1 (CIM_BIT_DOFF): the D1-D6 C&I draft terms off (small-map ban
// and its gem-layer soft penalty, the cluster-band demotion, the gem-layer centrality strip, the VV/CI base-lineup condition on the gem
// terms, C&I's skip in the DTM dash loop). Bit 2 (CIM_BIT_FLAT): S.base[CI] += CIM_PP10 / 10 pp, no feature term. 0 = off.
#define CIM_BITS 3
// v642 CIM: C&I flat draft value, D1-D6 off
#define CIM_PP10 125
inline constexpr int CIM_TAB[3] = { 0x43494D31, CIM_BITS, CIM_PP10 }; // slot 0 magic keeps it out of .bss
constexpr int CIM_BIT_DOFF = 1;
constexpr int CIM_BIT_FLAT = 2;
// CIMG (b1769, spec_cimg_1109): no flat C&I value on one-pack maps. Gate (CIMG_GATE): 1 one_pack() (draft memory OP_XID), 2 the
// largest group holds >= OGS_PCT % of the gems (MCL_BIT_ONEGEM's test), 3 >= 95 %. Bit 2: CIM's flat value off on gate maps. 0 = off.
#define CIMG_BITS 2
// v647 CIMG: no flat C&I bonus on one-pack maps
#define CIMG_GATE 1
inline constexpr int CIMG_TAB[3] = { 0x43494D47, CIMG_BITS, CIMG_GATE }; // slot 0 magic keeps it out of .bss
