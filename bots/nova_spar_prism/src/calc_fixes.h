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
// bk5 CTK (b1486; bank bk5b hand rebase onto v708): bit 1 HPT, a camp tie between mates goes to the higher priority: q = the
// nearest-foe q + 3 x carrying + HP tier (0..3), so a healthier mate acts first and takes the ties, carriers last; tie_prio recomputes
// mates with the same rule. Runtime data flag, read first; 0 = off.
// v745 CTK: fpb5 bank bundle bk5b+ehc3s+rts
#define CTK_BITS 1
inline constexpr int CTK_TAB[2] = { 0x43544b31, CTK_BITS }; // slot 0 magic keeps it out of .bss
