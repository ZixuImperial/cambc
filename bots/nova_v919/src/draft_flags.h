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
// b2350 PKX (RC X788 + X728, VV; draft bug-bar bundle). Runtime data flag PKX_TAB[1], read first; 0 = live. Bit 1 PKIX1: write_plan's
// guard uses the TRUE group/altar counts (as read_plan does), so a map with > 200 groups or > 40 altars no longer stores indices
// pack_prism_plan refuses (which lost every packed extra). Bit 2 WGLP1: WGL judges Willow v Marcella on the lineup we field (the plan
// with Prism held on pz_viable seats, swap_by_cell_table's form). Bit 4 WGLR1: WGL's two replans run only when both fit the fuel guard.
// Bit 8 DPBX1: write_plan leaves bytes 748-758 zero (no reader) instead of a second plan_for_map().
// v855 PKX: DPBX1 skip unused second plan_for_map
#define PKX_BITS 8
inline constexpr int PKX_TAB[2] = { 0x504B5831, PKX_BITS }; // slot 0 magic keeps it out of .bss
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

// DPR (b1833, RC X313 DPR1 + DPR2; identical, pairs with hmx1): sweep_fronts_dpr in place of sweep_fronts. DPR1: a walk label carries
// the step k that pushed it (q | (k + 1) << 8) and on pop skips the neighbours it shares with its parent (their minq is already <= this
// label's qw); spawn and dash labels test all 8. DPR2: pops split into the front list, then the bucket (same order); hopm pointer hoisted.
// Falls back to sweep_fronts when q could pass 8 bits (DTM_TMAX + 2 x cooldown >= 256). 0 = off.
// v730 DPR: sweep skips parent's neighbours (DPR, X313)
#define DPR_BITS 1
inline constexpr int DPR_TAB[2] = { 0x44505231, DPR_BITS }; // slot 0 magic keeps it out of .bss
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
// OHD (b1829, Deep spec_osd_1110.md: draft for one-source heavy maps). Baked at its shipped value (OHD_TAB is constexpr; no runtime flag). Class (draft-time
// map data only): the largest gem group holds >= OHD_TAB[2] % of the map's gems and holds an elk, golem or monolith (ohd_class,
// draft_turn.cc). On class maps, on the first draft turn: bit 1 Varg -> Willow; bit 2 Varg -> Marcella; with no Varg fielded, the
// lowest-base fielded pick that is not C&I, Prism or a pick a stronger rule forced (base > 500) goes. Bit 4 (bit 1's pre-stated
// adaptation): Vendetta -> Willow (Varg kept).
#define OHD_BITS 2
// v727 OHD: OHD bit 2 re-run (rare)
#define OHD_SHARE 70
inline constexpr int OHD_TAB[3] = { 0x4F484431, OHD_BITS, OHD_SHARE }; // slot 0 magic keeps it out of .bss

// HMF (b1839, RC X259 HFR1 confirmed by TB /data/zw4424/st/tb_x259/result.md): on dense hole maps the draft turn's cut is in
// mark_shortcut_hops (draft_map_features.cc): it enters with ~9.1M and never leaves (no fuel test; the hopm != 0 memo skips only tiles
// that found a hop, so open tiles are recomputed up to 8x), so the pick is random. Runtime data flag HMF_TAB[1], read first; 0 = off.
// Bit 1 HMD1 (play-identical): a launch tile is marked done after its first computation, whatever the result. Bit 2 HMF1: a fuel test
// every row; at the reserve the marking stops and dash_walk_times takes the existing no-dash-times path (dtm_ok false). Bit 4 HFR1a:
// sweep_fronts tests the fuel every 64 labels inside a front and bounds its label list by (fuel - reserve) / 40 (the sweep now runs on
// hole maps with ~7M left). Bit 8 TWS1 (as tws1b, identical): travel_write's k-list stores the k nearest by partial_sort, not a full
// sort (3-3.7M on 90-130-group maps once the freed fuel lets the travel table finish).
// v741 HMF: hop marking fuel-safe, ported onto DPR (X320)
#define HMF_BITS 15
inline constexpr int HMF_TAB[2] = { 0x484D4631, HMF_BITS }; // slot 0 magic keeps it out of .bss
// HMS (b1833, RC X301 HMS1; bundle with HMF): mark_shortcut_hops visits classify_tiles' gap list (DashWalk::gaps, filled only with the
// bit on) instead of scanning every tile for mo == 2. Same tiles visited, hopm a pure function of mo: identical. 0 = off.
// v741 HMS: hop marking fuel-safe, ported onto DPR (X320)
#define HMS_BITS 1
inline constexpr int HMS_TAB[2] = { 0x484D5331, HMS_BITS }; // slot 0 magic keeps it out of .bss
// DFA (b1833, RC X301 DFA1): sweep_fronts' two frontier buffers are default-initialised (new DashCell[]) instead of value-initialised
// vectors; every cell read (ci < nc) was written first. Identical. 0 = off.
// v741 DFA: hop marking fuel-safe, ported onto DPR (X320)
#define DFA_BITS 1
inline constexpr int DFA_TAB[2] = { 0x44464131, DFA_BITS }; // slot 0 magic keeps it out of .bss
// NRN (b2339, owner directive 12 Nov: "don't bring ren as we haven't optimised him"; "Never draft tavi and stellar either"; "Just dont
// consider them in the draft"): Ren, Tavi and Stellar are never drafted. Baked on (house-form constexpr table). Bit 1: after set_values
// each of the three sits 1000 below every other kit; a swap cell whose TO is one of them does not apply; a planned or greedy pick of one
// is skipped.
#define NRN_BITS 1
inline constexpr int NRN_TAB[2] = { 0x4E524E31, NRN_BITS }; // slot 0 magic keeps it out of .bss

// NCF (b2377, spec_ncf_1113, owner replay 01a1d2b4 "we should always have one realistically ... or Vendetta worst case"; port of NCC b2119's form).
// Decided once on our first draft turn after every live layer, from our own plan and map values (never foe picks): a FIELDED lineup (plan, Prism
// when viable, this turn's choice, VGF and forced-Ryth Marcella predicted) with no carry (Prism, Vesper, Marcella, Vendetta; ncf_carry_mask,
// one place to swap onto the shared roster helper) fields one in its lowest-S.base seat that is not C&I (and not already picked). Later turns
// run live's draft on a virtual have (TO shown as FROM), so TO takes FROM's own pick step. Bits: 1 TO = Vendetta; 2 TO = Vesper where
// F_MONO >= .5, else Marcella (Vendetta when a live layer removed both); 4 only in 3-pick drafts. 0 = off.
// v881 NCF: swept v881: shipped value with no ledger record
#define NCF_BITS 5
inline constexpr int NCF_TAB[2] = { 0x4E434631, NCF_BITS }; // slot 0 magic keeps it out of .bss

// b2390 DCO (VV X927-5): skip one DSW swap cell (DSW_TAB is constexpr, so a runtime data flag). Runtime data flag DCO_TAB[1], read first;
// 0 = v911. Bit 1: DSW cell 3 (Vesper -> Heart; Vesper -> Varg on 3-body maps, D3T) never fires; bit 2: DSW cell 4 (Vesper -> Marcella)
// never fires. Cell 2 untouched. No draft fuel is used.
// v914 DCO: DCO skip DSW cell 3 Vesper to Heart
#define DCO_BITS 1
inline constexpr int DCO_TAB[2] = { 0x44434F31, DCO_BITS }; // slot 0 magic keeps it out of .bss
