// Wards on hot spots, scored from map features at runtime (never from map identity): - camp groups, by value (monoliths dominate)
// and contest (central groups most, then our side), boosted when due to respawn or claimed by one of us; - altars, by how likely
// each team is to bank there; - chokepoints: narrow levels of the corridor of near-shortest routes between the two spawns; - bush
// clusters next to that corridor, to groups or to altars (a ward inside a bush sees its cluster); - any of these more where enemies
// were seen in the last 40 rounds. A ward is placed within Chebyshev 2 of its owner and recharges over 10 owner turns, so champions
// ward along their normal path: at the end of a turn with the charge ready, pick the tile within reach whose ward would see the most
// hot-spot weight (discounted where a known ally ward already looks), and place it when it beats the current ward by a margin. The
// bar drops the longer the charge waits, so a good spot is not passed up for a perfect one, and the current ward's value fades over
// 200 turns, so wards follow our activity. Fuel: the background analysis runs in resumable steps that each check their own cost;
// act() runs only with 55k left and costs at most ~20k (two new vision queries, ten spot-weight refreshes per call).
#pragma once
#include "common.h"

// While I own a ward, scout() never picks a tile on our spawn (it ran right after a recall and put the charge two tiles toward the
// enemy, i.e. in our own spawn corner, replacing the body's field ward); none left -> keep the charge (the first ward, my_ward.x <
// 0, is unaffected). Runtime data flag SCOUT_HOME_TAB[1], 0 = off. Bits: 1 = scout(); 2 = act()'s scored candidates too (a spawn
// tile whose score beat the fading field ward).

// Runtime data flag, WFS_BITS 0 = off: the opening's ward analysis and a ready charge get the turn's spare fuel before the
// background block. Bit 1: while the spot cache is not built and round <= WFS_R, ward::analyse runs at the head of the background
// block. Bit 2: same for intel::analyse. Bit 4: a ready charge with the cache built runs act() before the background block
// (otherwise it runs behind a 55k gate the block's 25-45k reserves fail). Bit 8: bit 1/2 without the round limit. Bit 16: act()'s
// fuel gate is WFS_ACTF instead of 55k (act costs <= ~20k and starts no refresh below ACT_FLOOR 22k).
// STRIPPED (FL6): no reader of WFS_TAB in this tree; deadstrip.py find WFS before arming.
namespace nova::ward {
}

namespace nova::ward {

// Background analysisnamespace nova::ward {

// Background analysis in resumable, fuel-bounded stages (group and altar spots first, then routes and bushes).
void analyse(long reserve);
// End of turn: place or move the ward when it pays.
void act();
// Ward the nearest unlit bush tile within reach now (need_hit: only after damage from no visible source). True when a ward was
// placed.
bool react(bool need_hit);
// With the charge ready, ward an unlit tile of the bush cluster next to `at` (a foe's last tile) within reach. True when placed.
bool ward_bush_by_vanished_foe(vec2 at);
// My ward sees a spawn tile of this group (its state can be read every turn).
bool watches_group(int gi);
// The per-group watch flags themselves (watches_group(gi) == gi < size && flags[gi] != 0).
const std::vector<std::uint8_t>& watch_flags();
// Changes whenever watch_flags() may have changed.
std::uint32_t watch_version();
// My ward's tile ({-1,-1} when none).
vec2 position();

} // namespace nova::ward
