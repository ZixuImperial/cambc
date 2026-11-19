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
#define GSP_BITS 1
inline const volatile int GSP_TAB[2] = { 0x47535031, GSP_BITS }; // slot 0 magic keeps it out of .bss
#define GSP_ON(b) ((GSP_TAB[1] & (b)) != 0)
inline int gsp_lf = -1; // GSP: the index of the first lethal-burst zone in this turn's walk-guard list
