#pragma once
// brain_flags.h: turn flags and tunables.

// Bug-fix flags (runtime data flag; 0 = trunk). Bit 1: shop_recall's "bank first" refuses only when want_bank is true, so a bag
// under the bank bar doesn't block a shop trip. Bit 2: prism_can_win_race reads a visible mate's bag from the SDK; al.gems is 0 on
// calm turns. Bit 4: observe() reads a shield that expired this turn start (GameRules.md:122; last seen with 1 turn left, HP not
// down) as no hit. Bit 8: refresh_self after a kept spin, so later steps of the turn know the recall channel is on. Bit 16: my_burst
// at d = range + 1 does not add a walk-excluding spell to the walk-and-hit (GameRules.md:428): Marcella at d2 read Strength + 2F, a
// false kill_now. Tie-break seek (runtime data flag; 0 = trunk). GameRules.md:27: r2000 compares tributed gems, gold earned, kills,
// then Team B wins. A kill pays gold, so on a 0-0-0 game one kill decides it. TSK_BITS bit 1: as Team A with nothing to do (no gems,
// no gold, nothing tributed by either team, no target for TSK_WAIT turns), walk at the enemy spawn: a loss is the tie-break's result
// anyway. Bit 2: Team B too (it loses more often than it wins in tests, leave off).
#define TSK_BITS 1
#define TSK_WAIT 60
inline constexpr int TSK_TAB[3] = { 0x54534B31, TSK_BITS, TSK_WAIT };
#define KILL_STEP_FLAG_BITS 10
inline constexpr int KILL_STEP_FLAG_TAB[2] = { 0x42383631, KILL_STEP_FLAG_BITS };

// A body whose move is still unused at the end of the turn it finished its target group steps onto a free spawn tile of that group,
// so the capture clock starts one round earlier (GameRules:122, :194; capture() itself runs only next turn). Bit 1: when I am the
// capturer (should_capture). Bit 2: also when a mate outranks me. Runtime data flag KS_TAB[1] (0 = trunk). Called from spin_on_turn_end, the
// last call of the turn, so no later spell in the turn is excluded by the walk.
#define KS_BITS 1
inline constexpr int KS_TAB[2] = { 0x4B535031, KS_BITS }; // Kill, then step on the camp tile.
#define KS_ON true

// Bank step: a carrier whose bank walk ends in submit range starts the tribute in the same turn, so the channel ticks on the arrival
// turn and completes a round earlier (GameRules:116, :273). Bit 1: every walk made inside bank(). bank_step_turn re-runs bank()'s
// start gates on the new tile. Runtime data flag BS_TAB[1] (0 = trunk), called from spin_on_turn_end.
#define BS_BITS 1
inline constexpr int BS_TAB[2] = { 0x42533831, BS_BITS }; // Move, then tribute in one turn.
#define BS_ON true

#define HSL_OK(c)

// RGB (rgb): brain and movement bugs. 0 = nova_b9968_rgf3r. Bits (kept after the firing read): 1 = a re-perceive keeps a foe recall verdict, 4 = move mask invalidated after a mid-turn perceive, 8 = tm2 coming set only on a taken step, 16 = walk_cast_end uses the real round.
#define RGB_BITS 29
inline const volatile int RGB_TAB[2] = { 0x52474231, RGB_BITS }; // slot 0 magic keeps it out of .bss
#define RGB_ON(b) ((RGB_TAB[1] & (b)) != 0)
