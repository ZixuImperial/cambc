// calc_fixes.h: Corrections to damage and cost calculations. Integer switches only; every one at 0 leaves the uncorrected
// calculation.
#pragma once
// Fish tier rank. Runtime data flag FTR_TAB[1], read first; 0 = off. Bit 1: my base priority is P.prio - 7 q, where q = HP tier
// (edges 75/50/25%, FTR_TAB[2] points of hysteresis) + carrying gems. Hurt bodies and carriers act last, so a healthy tied mate
// takes the camp hit. The 40/35/38 and Cassi-Issac combo overrides stay on top. Bit 2 TIE: the in-team camp-tie readers (takes_tie,
// combat camp damage, the ally-acts-before-me test) read mv::tie_prio: my own base; for a mate in sight that already acted this
// round, its real next-round priority(); for one that has not, its value recomputed from its HP and gems with the same rule
// (body-local, so mates agree). Bit 2 needs bit 1. Bit 8 PAN (with bit 1): q = carrying + 2 (13 - nearest visible foe distance) once
// a foe is within 12 (nearest_foe_acts_last_q), so the body nearest a foe acts last and carriers act after non-carriers. Bit 4 is
// reserved.
#define FTR_BITS 11
inline constexpr int FTR_TAB[4] = { 0x46545231, FTR_BITS, 3, 0x31525446 }; // magic, bits, hysteresis points, end magic
