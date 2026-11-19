#pragma once
// draft_flags.h: draft flags and tunables.

#define DRAFT_DASH_PP 4.0f
#define DRAFT_DASH_LO 0.05f
#define DRAFT_DASH_HI 0.30f
#define DRAFT_DASH_COST 6.0f // Rounds of dash cooldown charged to a trip that crosses holes.

// Dash-time term (draft only, map features only; baked, bits 1-16 all on, only bit 16 is still tested). Bit 1: real turns from our
// spawn to the nearest altar and the value-weighted groups, walking v walking + dash, cooldown included (dash_walk_times). Bit 2 (reads
// bit 1's result): dash kits gain (C&I too since v642, CIM D6), non-dashers lose, Ren takes no part (bit 8), smoothly with how slow
// walking is and how much the dash saves (set_values). Slots: DTM_PP hundredths of a pp at x = 1, DTM_NON the walkers' loss in % of the
// dashers' gain, DTM_W0 the walking turns at which slowness is 1/2, DTM_WA the altar's weight in % (rest: groups). Bit 4: a hand swap
// (DSW cell) does not take a dash kit out for a walker where the term between them is at least DTM_KEEP hundredths of a pp.
#define DTM_BITS 31
#define DTM_PP 4000
#define DTM_NON 100
#define DTM_W0 40
#define DTM_WA 50
#define DTM_KEEP 1000
inline constexpr int DTM_TAB[7] = { 0x44544D31, DTM_BITS, DTM_PP, DTM_NON, DTM_W0, DTM_WA, DTM_KEEP }; // Draft: dash-time term.
constexpr int DTM_BIT_VARG = 16; // Bit 16 moves Varg by dv h - dn (1 - h), h = heavy gem share: a walker on light maps, level with the dash kits on heavy ones.

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
// v634 DXS: keep Prism at DXC0 unless mid share high
#define DXS_H 100
inline constexpr int DXS_TAB[6] = { 0x44585331, DXS_BITS, DXS_E10, DXS_W10, DXS_L, DXS_H }; // slot 0 magic keeps it out of .bss

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
// VGF (b1762, spec_vgf_1109, VV Design; mechanism = b1756's stored VSM strict swap): field Vesper in Marcella's seat on gold-form maps.
// Baked at v679 (always on; VGF_TAB[1] is not read). On a map where farmable gold per farmable gem (F_GOLD_PC / F_GEM_PC) >=
// VGF_R100 / 100 (gem supply 0 with gold > 0 passes; no gold or no features fails), one capture of every group's gold / (team_size() + 1)
// >= VGF_GPB (the + 1 applies with or without C&I), the plan holds Marcella and not Vesper, and holds no Prism with Prism's plan not
// viable: the turn that would pick Marcella picks Vesper (just before the pick, after every live rule), and on later turns the plan sees
// Vesper as Marcella, so every rule that reads our picks goes on as live.
#define VGF_BITS 1
#define VGF_R100 600
// v679 VGF: Vesper takes Marcella seat on gold-form maps
#define VGF_GPB 193
inline constexpr int VGF_TAB[4] = { 0x56474631, VGF_BITS, VGF_R100, VGF_GPB }; // slot 0 magic keeps it out of .bss
namespace nova::drafting {
bool vgf_gate(); // draft_values.cc
} // namespace nova::drafting

// VGE (b1789, spec_vge_1110, owner: "more gold farming == VV"): VGF's map gate reads Vesper's gold edge E = F_GOLD_PC - 6 x F_GEM_PC.
// Runtime data flag VGE_TAB[1], read first; 0 = off. Bit 1: the ratio test (F_GOLD_PC / F_GEM_PC >= VGF_R100 / 100) is replaced by
// E >= VGE_E0 (the gold-per-body floor stays). Bit 2 (placebo, for the read only): the live gate, but VGF off where VGE_E0 <= E < 2 VGE_E0.
#define VGE_BITS 1
// v684 VGE: VGF gate reads Vesper gold edge E >= 40 (VGE)
#define VGE_E0 40
inline constexpr int VGE_TAB[3] = { 0x56474531, VGE_BITS, VGE_E0 }; // slot 0 magic keeps it out of .bss
// PKT (b1786, owner rule via Deep owner_01a1c4e8_1110.md). Runtime data flag, read first; 0 = v695. Bit 1: the Prism plan's pocket route
// (plan_for_map: uncontested cluster gems near our spawn >= PZ_POCKET_MIN) does not make her viable where vgf_gate() holds (gold-dominant
// map features), so Vesper can take the seat there. The gold-free and gem/gold-ratio routes are unchanged.
// v696 PKT: baked at its shipped value
#define PKT_BITS 1
inline constexpr int PKT_TAB[2] = { 0x504B5431, PKT_BITS }; // slot 0 magic keeps it out of .bss
