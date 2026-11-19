#pragma once
// champ_ci.h: this champion's rule card, passive and hooks. Shared code asks here; see champions.h for the layout. Cassi and Issac
// (GameRules.md:432-490). One pick, two bodies with separate positions, bags and turns. PASSIVE: if either dies both die; both bags
// are lost and they grant one kill reward (interactions.md:153). Cassi: ranged 3, HP 600 +65, Str 30 +3, Focus 100 +13; slot 0 2 x
// Focus range 4, excludes walking; slot 1 stun range 4. Issac: melee, HP 900 +80, Str 45 +3, Focus 100 +10; slot 0 reset; slot 1
// dash 2.
#include "common.h"
#include "world.h"

// ---------------------------------------------------------------- flags CI loop: the pair must stay together and linked; apart at
// contact, CI_SAFE forces FLEE. All 0 = off.
#define CI_LOOP 1 // master switch: 0 = every C&I loop switch below is off; 1 = the shared, combo, hybrid, linked safe-HP and near-radius switches are on
inline constexpr int CI_LOOP_TAB[2] = { 0x4C434942, CI_LOOP }; // runtime copy of CI_LOOP (slot 0 magic keeps it out of .bss): a 0/1 flip changes one data byte, not code
#define CI_ALWAYS 0      // map-aware: 1 = link from the start on every map; 2 = on maps that pass cassi_issac_map_link_wanted()
#define CI_NEAR_R (10) // > 0 = a link forms only with the partner seen within this many tiles in the last 3 rounds
#define CI_LINK_R 4
#define CI_MAP_HEAVY_X100 60 // CI_ALWAYS 2: heavy gem share bar
#define CI_SEEN_R 12
#define CI_SEEN_AGE 8
#define CI_CONT_LO_X100 35
#define CI_CONT_HI_X100 65
#define CI_HOLD 8
#define CI_GAP 2
#define CI_BEHIND 3
#define CI_SAFE_LHP_X100 40
// The pair fights only together, healthy and clearly ahead (champ_ci.cc assess_rule_ci_safe, cassi_issac_pair_holds).
#define CI_SAFE_NEAR 7
#define CI_SAFE_GAP 5
#define CI_SAFE_HP 0.55f
#define CI_SAFE_RATIO 1.5f
#define CI_CAP_PEN 150 // Cassi and Issac's growth is split over two bodies, so gold buys them less, and Vesper Vale
                       // earns a third more: on gold groups they rank + CI_CAP_PEN + gold/2 for the capture; 0 = off

namespace nova::ci_layer {
inline constexpr int CI_MELEE_GAP = 3; // a linked ranged body keeps this far from melee while the stun is down
// ---------------------------------------------------------------- WHO
inline bool type(cambc::champion_type t) { return t == cambc::champion_type::cassi || t == cambc::champion_type::issac; } // C or I
inline bool cassi(cambc::champion_type t) { return t == cambc::champion_type::cassi; }
inline bool issac(cambc::champion_type t) { return t == cambc::champion_type::issac; }
inline cambc::champion_type partner(cambc::champion_type t) { return t == cambc::champion_type::cassi ? cambc::champion_type::issac : cambc::champion_type::cassi; }
inline bool me_cassi() { return W.me.type == cambc::champion_type::cassi; }
inline bool me_issac() { return W.me.type == cambc::champion_type::issac; }
} // namespace nova::ci_layer

// ==================================================================================== C&I DRAFT The draft's C&I terms (draft_*.cc
// set_values and the first-pick CI_BAND check). draft_*.cc keeps the shared scoring arrays (S.base, S.mt) and asks these hooks. Left
// in draft_*.cc: base_lineup_has_vv_or_ci (N2 lineup search, reads the enumerator), the DTM bit 2 loop's `c == CI` skip, DASHERS' bit(CI),
// the CI_BAND group test (cluster-only groups on our side) and the plan rebuild without C&I.
#define DRAFT_CI_PP 9.0f
#define DRAFT_CI_LO 0.25f // DRAFT: centrality = share of the walkable value in one central area both teams walk to alike
#define DRAFT_CI_HI 0.45f
#define DRAFT_CI_SMALL_AREA 1600 // DRAFT: 40 x 40; the pool's small maps are 30x30 to 40x40, the next sizes 50x40 and up
                        // On maps larger than DRAFT_CI_SMALL_AREA with gold_rate < 60, or one altar and gold_rate < 120, VV gives
                        // her slot to CI (VV -DRAFT_CI_GATE_PP, CI +DRAFT_CI_GATE_PP). Small maps keep the C&I ban.
#define DRAFT_CI_GATE_PP 10.0f
#define N1_E_CI 12.0f
#define N1_CI_SMALL 10.0f
#define CIB_OWN1000 72
namespace nova::ci_layer {
inline constexpr float DF_CI_PP = DRAFT_CI_PP; // Draft feature family: the centrality term
// a gold-free map gets the C&I-for-VV swap at any size
inline bool draft_gf_small(bool map_term, float gold) { return map_term && gold < 60.0f; }
// on large maps that are gold-free (or single-altar with little gold) C&I takes VV's slot
inline bool draft_gate(bool map_term, int area, bool gf_small, float gold, std::size_t na) { return map_term && (area > DRAFT_CI_SMALL_AREA || gf_small) && (gold < 60.0f); }
// No C&I on smaller maps (except gold-free ones)
inline bool draft_small_ban(int area, bool gf_small) { return area <= DRAFT_CI_SMALL_AREA && !gf_small; }
// n1 (gem-heavy maps): the small-map ban becomes N1_CI_SMALL's soft penalty
inline bool draft_small(int area) { return area <= DRAFT_CI_SMALL_AREA; }
// C&I is not drafted where the cluster-only groups on our side hold at most CIB_OWN1000 / 1000 of the camp gems
inline bool draft_band(long own, long tot) { return tot > 0 && 1000L * own <= static_cast<long>(CIB_OWN1000) * tot; }
} // namespace nova::ci_layer

namespace nova::combat { struct Assessment; }
// ---------------------------------------------------------------- Cassi and Issac fight weights Three C&I fight weights, applied to
// the existing scores (they are not vetoes). Flag CIF_BITS, 0 = off. Bits: 1 S3 = a late Focus-built Cassi with no mate in reach of
// the fight scales her fight ratios down by her Focus share (no change when her burst kills the focus this turn or next); 2 P2 = a
// healthy linked Issac in a fight weighs his step toward the tile between Cassi and the foe that threatens her; 4 A1 = Cassi's
// walk-in weighs the hits of ranged foes whose basic range (3) the step enters against her next hit, and holds at her spell range
// (4) when the loss wins. Hooks: combat_*.cc assess (before assess_base_stance) and fight (after fight_choose_hold), flag first.
#define CIF_BITS 6
#define CIF_S3_W 100 // S3: ratio / (1 + W/100 x Focus share)
#define CIF_A1_W 150 // A1: hold when W/100 x (ranged hits / my eff HP) > my hit / focus eff HP
// P2: tiles from the guard tile cost W/100 x HP weight each, walk-in progress 1 each
#define CIF_P2_W 100 // P2: tiles from the guard tile cost W/100 x HP weight each, walk-in progress 1 each
inline constexpr int CIF_TAB[5] = { 0x43494631, CIF_BITS, CIF_S3_W, CIF_A1_W, CIF_P2_W }; // slot 0 magic keeps it out of .bss
constexpr int CIF_BIT_S3 = 1;
constexpr int CIF_BIT_P2 = 2;
constexpr int CIF_BIT_A1 = 4;
namespace nova::ci::fight_weights
{
// P2 / A1 before the walk-in: 0 = no change, 1 = hold here (the walk-in is skipped), 2 = I stepped.
int walk(const nova::combat::Assessment& a, const Body& f, int d);
} // namespace nova::ci::fight_weights

// ---------------------------------------------------------------- Cassi and Issac builds and roles C&I builds and roles. Flag
// CIR_BITS, 0 = off. Bits: 1 = Issac Health build (Prospector/Treasure/Hunter and the main Bruiser in Health); 2 = Cassi
// Durability-Focus first, then Home-Focus; 4 = P1 camp ties (brain_*.cc set_dynamic_turn_priority: Cassi skips her CI_COMBO raise while an awake
// camp reaches her, and Issac takes one above her value, so a camp's distance tie goes to Issac; the tied body that acts first is
// hit); 8 = Cassi Power-Focus first; 16 = CIE escort (a C&I body may join one non-partner mate's group); 32 = Issac all Health,
// Durability-Health first (overrides bit 1). Bit 2 also turns Cassi's other entries to Focus. 64 = S1 Cassi's engage and flee bars
// x1.2; 128 = S2 Issac's bars x (0.85 + 0.35 g / (g + 2000)), g = team gold earned (estimated); 256 = R1 early (g < 1500): Cassi
// neither adopts Issac's group nor leash-steps, and may join one mate's crew; 512 = CI_SAFE 'apart' does not count Cassi within 2 of
// any mate; 1024 = R1 at any time (split whenever targets score it).
#define CIR_BITS 100
inline constexpr int CIR_TAB[2] = { 0x43495231, CIR_BITS }; // slot 0 magic keeps it out of .bss
namespace nova::ci::builds
{
// bits 1/2/8: rewrite the shop list for Cassi or Issac (econ upitm_post, before its partial-shard fix).
void build_pass();
// bit 4: Issac's next-round priority is one above Cassi's (mv::tie_prio) while an awake camp reaches either of us, the pair is
// within 4 and Issac is at 30%+ HP (the hurt-last order would otherwise hand Cassi the tie).
int issac_tie(int want);
// bits 64/128: scale a linked body's engage and flee bars (combat assess).
void bars(float& engage, float& flee);
} // namespace nova::ci::builds
