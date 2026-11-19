#pragma once
// move_flags.h: movement flags and tunables.

// Opening dash use: Heart and Vendetta should not spend their dash on r3/r4 for a 2-tile gain on the walk and then walk many rounds
// to a far hole crossing. Bit 1: the hs3 shortcut field also roots the launches with the best walk-from-spawn + walk-after total
// (h.v = the largest root's walk after). Bit 2: the opening step builds its group's hs3 shortcut in the foreground. Bit 4: a plain
// travel dash waits while a top group's hs3 decision is pending on a thin-hole map, up to OPD_R rounds. Runtime data flag (0 = off).
// Bit 16: bit 4 holds only while a hole tile lies within 1 of the next 8 walk steps.
#define OPD_BITS 4
#define OPD_R 40
inline constexpr int OPD_TAB[3] = { 0x4F504431, OPD_BITS, OPD_R };

// GSP: the walk guard is dropped whole when I stand inside any zone of its list (move_retreat.cc AvoidFoeReach), lethal zones included
// (Combat spec_gsp_1109, Rule Checker CONFIRMED). Runtime data flag GSP_TAB[1], read first; 0 = off. Bit 1: inside the union, guard with
// the lethal-burst zones (appended last, from gsp_lf) that don't contain me, unless I stand in a lethal zone. Bit 2: inside the union,
// guard with every zone, plain or lethal, whose disc doesn't contain me. A zone I stand in is never walled.
// v655 GSP: walk guard keeps lethal zones inside plain reach (GSP)
inline int gsp_lf = -1; // GSP: the index of the first lethal-burst zone in this turn's walk-guard list

// SWD (b1756, spec_swd_1109): the travel dash on farm-stage walks that never ask for one. Runtime data flag SWD_TAB[1], read first;
// 0 = off. Bit 1: a plain step_to_set walk (cd_mode 0) on a farm or errand turn (brain marks swd_r; not while capturing) tries the
// plain travel dash down its own search field first, then steps from the landing, as the collection branch does. Not on a walk out
// of camp or foe reach (econ_tank_support safe set, go_home's threat scan: swd_block). Bit 2: respawn_stage's walk toward a respawning
// group (econ_staging.cc, Step 0's try_move caller, 32 dash-ready turns/g) dashes down the group field when the landing stays outside
// the wait band (field - dash range > PLAN_WAIT_DIST); then the stage runs again from the landing.
// v673 SWD: farm walks travel-dash (+respawn stage)
inline int swd_r = -1000;     // SWD: the round brain reached the farm or errand stage (bit 1)
inline int swd_block = -1000; // SWD: a keep-out or bail walk this round: no plain dash
// BHX (b1791 move/draft bug hunt, Rule Checker confirmed 10 Nov; build_b1791_bughunt.md). Runtime data flag, read first; 0 = v707.
// Bit 1 HLD1: landing_wakes_camp skips a camp tile in sight with no living camp (nothing to hit or wake, GR:826, INT:105); unseen
// tiles keep the veto. Bit 2 CDL1: the altar walk's three early exits reset collect_dash(2) (the mode is for that walk only).
// Bit 4 RNB1: in the null-reach draft mode (draft_internal.h rule (b)), VGF and the swap / exchange cells never add a non-dasher
// (a null pick) nor take the dashers past S.max_dash.
// v711 BHX: baked at its shipped value
#define BHX_BITS 7
inline constexpr int BHX_TAB[2] = { 0x42485831, BHX_BITS }; // slot 0 magic keeps it out of .bss

// EPW (b1839, RC X236 EPW1): the priced-escape A* (Ep9Run::search) stops when pops x (TCF_EP9K + ncamp) > TCF_EP9W 1800, tested every
// 16 pops: 16 x 119 > 1800, so every search stops at pop 16 and EP9_POPS 600 never binds; a real detour then falls back to the damaging
// shortest walk. Runtime data flag EPW_TAB[1], read first; 0 = off. Bit 1: the work limit is clamp((fuel() - EPW_F0) / EPW_DIV,
// TCF_EP9W, EPW_MAX), fuel read once per search (EP9_POPS and the 60k entry gate stay).
#define EPW_BITS 1
#define EPW_F0 45000
#define EPW_DIV 8
// v716 EPW: priced escape A* fuel-scaled work cap
#define EPW_MAX 70000
inline constexpr int EPW_TAB[5] = { 0x45505731, EPW_BITS, EPW_F0, EPW_DIV, EPW_MAX }; // slot 0 magic keeps it out of .bss
