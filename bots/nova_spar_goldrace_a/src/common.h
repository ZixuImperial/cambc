// common.h: shared includes, the flag headers, small helpers, fast readers for engine buffers and the Kit description.
#pragma once
#include <wasm_simd128.h>
#include <type_traits>
#include <cambc.h>
#include "common_flags.h"
#include "brain_flags.h"
#include "combat_flags.h"
#include "draft_flags.h"
#include "econ_flags.h"
#include "move_flags.h"
#include "plan_flags.h"
namespace nova::mu { inline constexpr int bits = 970; inline float ct_k = 1.0f; } // FB10 row 8: bits = MUL_BITS (static_assert in multipliers.h), no per-turn copy; // ct_k: bit 256 CTH, camp_threat x my camp-hit factor. MUL_TAB[1], copied once per turn by perceive (bits 64 OCB2, 128 BGX2 below)
#include "calc_fixes.h"

#include <algorithm>
#include <array>
#include <stdexcept>
#include <cmath>
#include <cstdint>
#include <cstdio>
#include <cstring>
#include <functional>
#include <memory>
#include <optional>
#include <vector>

int map_class(); // Class bits of the map (set by the draft), cached after the first good read.
unsigned map_class_compute();           // the bits from M.groups (draft: before handoff)
inline bool mcl_off(int mask) { return mask != 0 && (map_class() & mask) != 0; } // mask read first: 0 = no work
inline bool sph_pin = false; // SPH bit 4: inside fight(), steps and dash landings off my spawn are refused (true only with the bit on)
struct SphPinGuard
{
	bool on;
	explicit SphPinGuard(bool b) : on(b) { if (b) sph_pin = true; }
	~SphPinGuard() { if (on) sph_pin = false; }
	SphPinGuard(const SphPinGuard&) = delete;
	SphPinGuard& operator=(const SphPinGuard&) = delete;
};
// MCL2 bit values (map_class() >> 8): FIGHT tertile in bits 0-1 (0 farmy, 1 mid, 2 fighty), GOLDGEM tertile bits 2-3, gems/body
// tertile bits 4-5, bit 6 CLOSE (spawn-to-spawn walk <= 22), bit 7 POCKET (gems not walkable from our spawn > 0), bit 8 AC (area
// control: the top mid region holds >= 1/3 of the map's value rate or of its light value rate).
unsigned compute_map_class_bits(int T); // draft: the MCL2 bits from the draft's map analysis
void lsp_raw(int T, float* x);          // LSP (b1762): the 8 raw draft-time map features
std::uint32_t lsp_map_pack(int T);      // LSP: the 8 features standardized, 4 bits each (dmem extra LSP_XID)
bool dm2_dead(cambc::vec2 p); // DM2: p lies in a stored dead-end block (false without the field)


// N2: C&I may replace only VV. Inside n1's gate, C&I's n1 terms (C&I +N1_E_CI x e, the centrality bonus scaled by e, the soft
// small-map ban) apply only where the lineup from the plan's target (the values before any n1 term, no n1 composition term) holds
// VV, or already holds C&I. Elsewhere in the gate C&I keeps its base value, so it cannot displace HoR or Marcella. VV's, Prism's and
// the Prism-Marcella terms stay n1's. 0 = no N2. Integer switch.







// Test builds only: burn a build-time salt x 64 fuel at each turn start to perturb fuel-dependent choices (measures noise).


namespace nova {

using cambc::bitboard;
using cambc::distance_field;
using cambc::team;
using cambc::vec2;

constexpr std::uint16_t UNREACH = cambc::distance_field::unreachable;
constexpr int BIG = 1 << 28;

inline int iabs(int v) { return v < 0 ? -v : v; }
// Compile-time (a flag read per call would cost more than it saves; cheb runs about 40,000 times a game). cheb was 4% of all fuel,
// 8% of fight-turn fuel, 11% of cut-turn fuel. wasm has no integer abs or max, so each costs a shift-xor-sub or a compare-select;
// f64.abs and f64.max are one instruction each and f64 holds every int exactly, so the result is the same int for every input.
#ifdef __wasm__ // SIMD path; the native test engine (tools/cxe) has no wasm intrinsics
NOVA_INLINE int cheb(vec2 a, vec2 b)
{
	// x and y in two lanes: one sub, one abs, one max
	const v128_t d = wasm_i32x4_abs(wasm_i32x4_sub(wasm_v128_load64_zero(&a), wasm_v128_load64_zero(&b)));
	return wasm_i32x4_extract_lane(wasm_i32x4_max(d, wasm_i32x4_shuffle(d, d, 1, 1, 1, 1)), 0);
}
#else
NOVA_INLINE int cheb(vec2 a, vec2 b) { return std::max(iabs(a.x - b.x), iabs(a.y - b.y)); }
#endif
inline float clampf(float v, float lo, float hi) { return v < lo ? lo : (v > hi ? hi : v); }
// FXR (common_flags.h): the restart state. RestartTurn is not a std::exception, so the std::exception catch sites never take it.
struct RestartTurn
{
};
inline bool fxr_live = false;     // FXR_ON(1): a play turn runs under fxr_run (brain_modes.cc)
inline bool fxr_stale = false;    // FXR_ON(1): this call was suspended and resumed in a later round (a fuel jump or a round poll)
inline bool fxr_inflight = false; // FXR_ON(1): a RestartTurn or AfBail unwinds; catch (...) sites pass it on (FXR_PASS)
inline int fxr_round = -1;        // FXR_ON(1): the round this play call began in
inline long fxr_lastf = 0;        // FXR_ON(1): the last fuel read; a later read above it is a fresh budget (the call resumed)
inline int fxr_kca_stuck = 0;    // FXR bit 2: turns whose first champion retry found kca_busy still set
// Inlined: this ran 20k times a game. Uses the raw import (the engine never returns < 0; the SDK wrapper only adds a negative-value
// throw). FXR_ON(1): a stale call reads 0, so every fuel-checked job stops at its own check (its place kept as on a low-fuel turn).
NOVA_INLINE long fuel()
{
	const long f = static_cast<long>(static_cast<std::uint64_t>(cambc::detail::sdk_fuel_remaining()));
	if (fxr_live) // FXR_ON(1) only: fxr_run sets it (no flag load on this hot path)
	{
		if (f > fxr_lastf)
			fxr_stale = true;
		fxr_lastf = f;
		if (fxr_stale)
			return 0;
	}
	return f;
}
// FXR_ON(1): a fuel measurement (a cost noted or learned) reads the real budget, never a stale call's 0.
#define FXR_FUEL() (::nova::fuel())
// cambc::round_number() with the error check inline (22k calls a game).
NOVA_INLINE std::uint32_t round_number_nc()
{
	std::uint32_t r{};
	const std::int32_t c = cambc::detail::sdk_bc_round_number(&r);
	if (__builtin_expect(c != 0, 0))
		cambc::detail::check(c);
	return r;
}
[[noreturn]] void fxr_throw();
[[noreturn]] void af_throw();
// FXR_ON(1): before every action and shared-memory write, and at AF_CHECK: a stale call unwinds to fxr_run, never acts.
NOVA_INLINE void fxr_poll()
{
	if (fxr_live && (fxr_stale || static_cast<int>(round_number_nc()) != fxr_round)) // fxr_live: FXR_ON(1) only
		fxr_throw();
}
// FXR_ON(1): first statement of a catch (...) handler: a RestartTurn or AfBail unwinding is passed on, not swallowed.
#define FXR_PASS()                          \
	do                                      \
	{                                       \
		if (FXR_ON(1))                      \
		{                                   \
			if (::nova::fxr_inflight)       \
				throw;                      \
		}                                   \
	} while (0)
// SPD: spread the fuel between turns. On big maps the first full turn costs more than the setup turn leaves (first turn p50 52k, p99
// 125k, max 129k; its first econ::observe 35k in the group loop vs 8k later), so a body's setup turn could be cut inside observe and
// resumed a round later on stale state. Runtime data flag SPD_TAB[1], flag read first; 0 = off. Bit 1 WGATE: the setup turn runs
// turn() only with SPD_TAB[2] left, the measured maximum of the first turn's start..econ::observe (55.7k over 635 first turns), so
// the turn is never cut before the split point below. Bit 2 SPLIT: the first turn() of a body ends after econ::observe (then one
// start_prestep step) when the fuel left is below the measured maximum of the rest of a first turn: SPD_TAB[3] when start..observe
// cost below SPD_TAB[5], else SPD_TAB[4] (measured rest after observe: max 58.2k below 40k, 80.8k at 40k and above). The next turn
// is a steady one (max 93k).
#define SPD_BITS 1
#define SPD_WARM 56000 // bit 1: measured max start..observe of a first turn (55.7k)
#define SPD_REST_LO 0 // bit 2, start..observe below SPD_WBIG: no split (rest max 58.2k)
#define SPD_REST_HI 82000 // bit 2, start..observe at SPD_WBIG or more: measured max rest after observe (80.8k)
#define SPD_WBIG 40000
inline constexpr int SPD_TAB[6] = { 0x53504431, SPD_BITS, SPD_WARM, SPD_REST_LO, SPD_REST_HI, SPD_WBIG }; // setup turn acts only with 56k left, else next turn
inline bool spd_split = false; // SPD bit 2: turn() stopped after econ::observe
// The elk-join contest cap (in rate_for, contest <= .60) lets a body join an elk group's claimants (up to 3) only on our side. Flag
// EJC_TAB[1], read first; 0 = that cap only. Bit 1: the elk join also applies up to contest EJC_CAP/100 (100 = no cap). Bit 2: the
// same join for contested NON-elk gem groups (contest in [EJC_MLO/100, EJC_CAP/100]) up to 3 claimants.
#define EJC_BITS 2
#define EJC_CAP 60
#define EJC_MLO 35
inline constexpr int EJC_TAB[4] = { 0x454A4331, EJC_BITS, EJC_CAP, EJC_MLO }; // contested non-elk mid groups up to 3 claimants
#define OP_MEM 767
#define OP_XID 15
inline int OP_PLAY = 0;


#define FG_TAIL 15000 // A choice is skipped when its measured work would leave the turn with less than this fuel (it would suspend).
#define FG_PRESTEP_MIN 22000 // A map-analysis turn steps toward the start goal only with this much fuel left (one step can cost 14-18k).
} // namespace nova
#include "fuel_meters.h"
#include "board_views.h"
#include "fast_reads.h"
#include "kit_data.h"
