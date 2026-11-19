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
