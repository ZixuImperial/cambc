#pragma once
// champ_vesper.h: this champion's rule card, passive and hooks. Shared code asks here; see champions.h for the layout. Vesper Vale
// (GameRules.md:524-554). Ranged 3, HP 1000 +100, Str 35 +5, Focus 100 +10. PASSIVE: +33% gold from captures and kills, adding with
// Treasure's +10 to 43% (interactions.md:85, 155); gems unaffected. Code: vesper_layer::gold_pct, the percent every gold formula
// takes. Slot 0: reset. Slot 1: dash 2 (reach after a dash is 2 + 3 = 5, interactions.md:26).
#include "common.h"
#include "world.h"
#include "rules.h"

namespace nova::vesper_layer {
// PASSIVE: the percent points this kit adds to gold (GameRules.md:532); percent points add with Treasure
inline int gold_pct(const Kit* k) { return k && k->bonus_gold ? rs::rules().vv_pct : 0; }
} // namespace nova::vesper_layer


namespace nova::vesper_layer {
inline constexpr int VV_LANDING_CROWD = 1; // Vesper Vale's landing: at most this many other enemies can reach it
// ---------------------------------------------------------------- WHO
inline bool me() { return W.me.type == cambc::champion_type::vesper_vale; } // I am Vesper Vale
inline bool kit(const Kit& k) { return k.bonus_gold; }                       // this kit is Vesper's (+33% own gold)
// ---------------------------------------------------------------- SHOP
inline bool shop_capture_first(const Kit& k) { return k.bonus_gold; }        // econ make_build: Capture moves to slot 3 (with Marcella)
inline bool shop_build(const Kit& k) { return k.bonus_gold; } // econ make_build: her Strength build (healers excluded at the site)
// ---------------------------------------------------------------- TARGETS
inline bool targets_own_gold(const Kit& k) { return k.bonus_gold; }          // planner: her own gold captures rank 100 + gold/2 better
inline bool gold_carrier(const Kit& k) { return k.bonus_gold; }              // plan_carriers: she is the team's gold carrier
// ---------------------------------------------------------------- FIGHT
inline bool fight_dash() { return me(); } // combat fight_vesper_dash (champ_vesper.cc): the dash into range
} // namespace nova::vesper_layer

// ---------------------------------------------------------------- DRAFT (draft_*.cc set_values)
#define DRAFT_VV_PP 6.0f
#define DRAFT_VV_LO 0.0f
#define DRAFT_VV_HI 1.5f
#define N1_E_VV -9.0f
namespace nova::vesper_layer {
inline constexpr float DF_VV_PP = DRAFT_VV_PP; // Draft feature family: her hand-set term
// draft set_values: Vesper is not played on maps where gold is required: her +33% pays with the map's gold rate
inline float draft_gold(float gold_rate) { return DF_VV_PP * std::clamp((gold_rate - DRAFT_VV_LO) / (DRAFT_VV_HI - DRAFT_VV_LO), 0.0f, 1.0f); }
// Left in the draft files: the n1 shared term block's Vesper add and C&I's gate term for Vesper (champ_ci.h draft).
} // namespace nova::vesper_layer

// ---------------------------------------------------------------- a team with Vesper Vale opens together (VOP) A team with Vesper
// Vale (P.carrier_gold) opens together on the best near gold group, so its first big capture is hers (+33% gold) and capture_recall
// lands her on the spawn with it. Flag VOP_BITS, 0 = off. Bit 1: the opening group and the stick (opening_choice seeds the crew's
// claims; refresh_target keeps them on it). Bit 2: she ranks first for its capture (cap_rank). A group qualifies with gold >=
// VOP_GMIN, no monolith or golem, walkable, spawn walk <= VOP_DMAX, contest <= VOP_CON % and walk + clear (crew base damage) + 6 <=
// VOP_TMAX; best gold per round. VOP_CREW bodies go with her (tank order, never the healer or a Prism carrier). The stick ends at
// round VOP_END, on capture, on a failed group, with 2+ foes near, or for a mate once the group is cleared.
#include <array>
#define VOP_BITS 3
#define VOP_GMIN 100
#define VOP_DMAX 24
#define VOP_CON 55
#define VOP_TMAX 45
#define VOP_CREW 4
#define VOP_END 60
inline constexpr int VOP_TAB[8] = { 0x564F5031, VOP_BITS, VOP_GMIN, VOP_DMAX, VOP_CON, VOP_TMAX, VOP_CREW, VOP_END }; // slot 0 magic keeps it out of .bss
// VOC (b1871, spec_voc_1111): the opening pack carries on to a chain of groups v[0..K-1] (v[0] = VOP's group), each link chosen by
// VOP's loop with the walk from the previous link's anchor (1.25 x cheb), v[0..k] excluded, own side only (d_home <= d_enemy).
// Bit 1: K = 2; a member moves on to the next link when its link is cleared (the carrier once her capture pays), she ranks first on
// every link, and a non-carrier member yields a link's tiles to her while she is in sight within VOC_NEAR. Bit 2: K = 4, links
// after v[0] have no round limit and end by state only. Bit 4: links k >= 1 with an elk take gold >= VOC_ELK_GMIN, valued gold + 2 x gems.
#define VOC_BITS 1
#define VOC_NEAR 12
#define VOC_WITH 16
#define VOC_ELK_GMIN 60
inline const volatile int VOC_TAB[2] = { 0x564F4331, VOC_BITS }; // slot 0 magic keeps it out of .bss
#define VOC_ON(b) ((VOC_TAB[1] & (b)) != 0)
namespace nova::econ::vesper_open
{
void claim(std::array<int, 8>& cl, std::array<bool, 8>& done); // start of the opening choice: the crew's claims on the group (bit 1)
void rate(int choice, float* out_rate, int* out_crew); // end of the opening choice: my crew rate when I hold it (bit 1)
bool keep(); // refresh_target: true keeps me on the group this turn (bit 1)
int rank(int gi, int slot); // cap_rank: the rank change for slot on group gi (bit 2)
bool hold_off(int gi); // VOC bit 1: capture(): a non-carrier member yields chain group gi's tiles to her (she is in sight near it)
} // namespace nova::econ::vesper_open
