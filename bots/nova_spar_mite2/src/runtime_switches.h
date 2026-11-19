#pragma once
// runtime_switches.h: A behaviour switch read at run time from one data array, so a candidate that flips a slot differs from its
// base ONLY in these data bytes: same code bytes, same addresses, same instruction counts (fuel) on every path that does not read
// the flipped slot. Games then change only where the feature is reached. Rules: - slot 0 holds RSW_MAGIC (nonzero: the table always
// sits in initialised data, never in .bss; also findable in the wasm); - one slot per switch, 0 or 1 (or a small int); never change
// the table's size or order, only append; - read a slot only AFTER the feature's own trigger test (`trigger && rsw(RSW_...)`), so
// off-trigger paths never read it; - flip a candidate by editing its value below and nothing else. SLOT REGISTRY (this enum is it;
// one owner per slot, named in the comment; a retired slot is never reused): HS_BANK (the econ hs3 bank code): the value of slot
// RSW_HS_BANK: bit 1 = bank walks, bit 2 = target groups outside the top 3. A data byte only: a copy with 0 compiles to the same
// code.
#define HS_BANK 3
namespace nova
{
inline constexpr int RSW_MAGIC = 0x21575352;
enum : int
{
	RSW_SLOT_MAGIC = 0,
	RSW_DOM_COMMIT = 1, // 1 = on, 0 = off
	RSW_DOM_YIELD = 2, // reserved; 0 here
	RSW_DASH_LOOK = 3, // reserved; 0 here
	RSW_CREW_CHIP = 4, // reserved; 0 here
	RSW_HS_BANK = 5, // HS_BANK (econ.h): bit 1 = hole-dash shortcut on bank walks, bit 2 = on every target group, 0 = off
	RSW_N = 64
};
inline constexpr int RSW_TAB[RSW_N] = {
	RSW_MAGIC,
	1,
	0,
	0,
	0,
	HS_BANK,
};
static inline int rsw(int i) { return RSW_TAB[i]; }
} // namespace nova
