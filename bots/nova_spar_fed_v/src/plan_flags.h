#pragma once
// plan_flags.h: plan flags and tunables.

// One-gem-source maps race the dominant gem group. Runtime data flag OGS_TAB, read first (0 = off): the draft sets MAPCLASS bit 4
// ONEGEM (one group holds >= OGS_PCT % of the map's gems) only while OGS_BITS != 0. Bits (econ and brain code): 1 START:
// siege_start_gate skips the stat-ratio test on that group when the crew's walk + clear time < its respawn time; 2 SGA: siege_turn's
// mid-clear 'contested' abort is skipped while present >= foes and the present crew's clear time <= the earliest seen foe arrival; 4
// HOLD: a body of the operation on that group above OGS_HOLD_HP % does not recall (heal/shop/flee/low hp) once the group is >= half
// cleared. 8 REM (every map, no class gate): a big group seen alive below SG_HPMIN health left is a normal target in rate_for and
// the filler.
#define OGS_BITS 8
#define OGS_PCT 70
#define OGS_HOLD_HP 30
inline constexpr int OGS_TAB[4] = { 0x4F475331, OGS_BITS, OGS_PCT, OGS_HOLD_HP }; // Slots: magic, bits, OGS_PCT, OGS_HOLD_HP. Bit 8: a 'big' group is judged by what remains of it.
