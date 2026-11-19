// Draft-memory encoding/decoding and the team plan: body slots, roles and parties.
#pragma once
#include "common.h"

namespace nova {

constexpr std::uint8_t MEM_MAGIC = 0x4E; // 'N'
constexpr std::uint8_t MEM_VERSION = 1;

enum Role : std::uint8_t
{
	ROLE_LEAD = 0,
	ROLE_MEMBER = 1,
	ROLE_SOLO = 2,
};

// Strategy flags written by the draft.
enum PlanFlag : std::uint8_t
{
	PF_NO_ALTAR = 1,   // no altar reachable on foot: gold decides
	PF_SIEGE = 2,      // monoliths/golems hold most gems
	PF_FIGHT = 4,      // contested, low-supply map
	PF_ISLANDS = 8,    // much of the gem supply needs a dash
	PF_LONG_GAME = 16, // gem supply too low to expect 1000
};

struct Plan
{
	int n = 0;                                 // bodies on our team
	int my_slot = -1;                          // my index in the ally list
	std::array<std::uint32_t, 8> handle{};     // ally handles in list order
	std::array<cambc::champion_type, 8> type{};
	std::array<std::uint8_t, 8> role{};
	std::array<int, 8> party{};                // party index, -1 for none
	std::array<int, 8> capture_rank{};         // lower captures first inside a party
	std::array<int, 2> lead{ -1, -1 };         // lead slot of each party
	std::array<int, 8> prio{};                 // set_priority value: the best camp tank highest (wins camp ties)
	std::array<int, 8> tank_order{};           // 0 = best camp tank on the team
	int carrier_gems = -1;                     // stacking champion fed with gem captures (Prism, then Marcella)
	int carrier_gold = -1;                     // champion fed with gold captures (Vesper Vale)
	std::uint8_t flags = 0;
	bool from_memory = false;                  // draft memory decoded successfully
	int prism_at = -1; // v775 XCF bit 4 PSL1: prism_slot's answer, set where P.n / P.type are written
	int s2s = -1; // Spawn-to-spawn walk from draft memory byte 14 (-1: unknown).
	int n_parties() const { return (lead[0] >= 0 ? 1 : 0) + (lead[1] >= 0 ? 1 : 0); }
	int slot_of(std::uint32_t h) const
	{
		for (int i = 0; i < n; ++i)
			if (handle[static_cast<std::size_t>(i)] == h)
				return i;
		return -1;
	}
};

extern Plan P;
// v775 XCF bit 4 PSL1: the first Prism slot of P (prism_slot's loop), for the cache in P.prism_at.
inline int plan_prism_scan()
{
	for (int i = 0; i < P.n; ++i)
		if (P.type[static_cast<std::size_t>(i)] == cambc::champion_type::prism)
			return i;
	return -1;
}

// Draft side: encode the map analysis and plan flags into draft memory (encode only, or encode and submit). Byte 2 is
// the pick count and bytes 4-8 the picks, so a cached buffer can be patched and resubmitted cheaply on later turns.
std::vector<std::uint8_t> encode_draft_memory(const std::vector<cambc::champion_draft>& picks, std::uint8_t flags);

// Draft memory as a bit stream. All draft writers still fill the old image (S.mem); pack() turns it into stream version 2 at
// handoff; champions expand it back to the old image once, so readers go through dmem::view() and see the old byte offsets. Fields
// with no reader are dropped (layout and free bytes: docs/modules/draft.md). Anything out of range: pack() fails, the old image is
// written, and readers take it as version 1. Dm3Rec: one hs3 slot's launch record built by the draft (the econ launch scan).
struct Dm3Rec
{
	int gi = -1, vmin = 0;
	std::vector<std::uint16_t> roots;
};
namespace econ {
void draft_launch_scan(std::vector<Dm3Rec>& out, long reserve);
// v724 DFG: the draft runs the opening simulation for its planned lineup (slot order ty[0..n-1]) and stores each body's first group +
// crew bit in dmem extras 8 (+6), and the slot types in extra 7; false (nothing stored) when it cannot.
bool dfg_draft_plan(const std::array<cambc::champion_type, 8>& ty, int n, std::uint8_t pflags, int s2s);
extern long dfg_draft_fuel;
}
NOVA_INLINE void plan_tank_order(); // v724 DFG: the draft's lineup roles (plan_roster.cc)
NOVA_INLINE void plan_carriers();
NOVA_INLINE void plan_capture_order();
namespace dmem {
struct View
{
	const std::byte* d = nullptr;
	std::size_t n = 0;
	std::size_t size() const { return n; }
	const std::byte& operator[](std::size_t i) const { return d[i]; }
	const std::byte* data() const { return d; }
};
View view(); // The old image. Reads no host state.
bool in_place(const std::uint8_t*& dist, const std::uint8_t*& acc, const std::uint8_t*& aacc); // v2: distances and access read in place
const std::uint8_t* travel_block_base(std::size_t& size); // Where travel_decode reads, so that [E] is the EXACT_TRAVEL block's first byte.
int total_groups();          // group and altar counts the draft stored, -1 when no valid memory (same answer on every body)
int total_altars();
bool pack(const std::vector<std::uint8_t>& in, std::vector<std::uint8_t>& out); // False: keep the old image.
// A new draft field in one line each side: dmem::extra_put(ID, value, bits) before handoff; dmem::extra(ID, fallback) in play. ID
// 0-15, bits 1-32. Costs 10 bits + the value. With packing off, or when the old image was written, extra() gives the fallback.
void extra_put(int id, std::uint32_t v, int bits);
std::uint32_t extra(int id, std::uint32_t fallback);
int extras_count();
void extra_clear(int id); // Drop a field written by extra_put.
// The tail blob (the last bytes of the packed stream; length in extra DMF_BLOB_XID). Draft: plan_memory_blob_set before handoff; pack appends it
// only when it fits (pack_and_submit_draft_memory repacks without it otherwise). Champions: blob() (nullptr, n 0 when absent).
void plan_memory_blob_set(const std::vector<std::uint8_t>& b);
void plan_memory_blob_clear();
bool blob_pending();
const std::uint8_t* blob(std::size_t& n);
// Slot gi's stored hs3 launch record: vmin (best landing walk) and nr root tiles (index y * w + x) in roots; nr 0 = the scan finds
// no launch. False: no record (scan in play).
bool launch_record(int gi, int& vmin, const std::uint16_t*& roots, int& nr);
long build_tail_blob(long reserve); // Draft: build the blob once (first draft turn); returns the fuel spent.
// With the compact-travel flag bit 1 the draft stores the EXACT_TRAVEL block inside the bit stream (XT length field 0 = compact): S
// and G as Rice-coded detours over a box-Chebyshev lower bound from the camp geometry, k-list ids in bw(n-1) bits, row counts
// instead of pads, and the opening routes only with XT bit 4 (their only reader). Champions expand it once, lazily, into the same
// byte block (plus checksum) the old layout held, so every reader sees identical tables. Reader side needs no flag.
bool compact_block_present();                                  // a compact XT block is in the stream
long compact_encode_cost(bool reset);                          // draft: fuel pack() spent on the compact block (kept out of cost estimates)
int compact_block_mode();                                      // its G mode (0 triangle, 1-8 k-lists, 255 none), -1 none
bool compact_head_expand(std::size_t n);                       // champions: its header, S and routes into the XT state (cheap); false: refuse it
int compact_block_build(long reserve, bool partial); // champions: the dense XT tables from it, resumable (partial) or all at once
                                                    // 1 done, 0 later, -1 refuse the block
} // namespace dmem

// Champion side: read draft memory (map distances, flags) and assign roles. Call once MapInfo is ready.
void build_plan();

// The draft (10M fuel on its first turn) builds every walkable group's walk field once (camps block, the group's own tiles open: the
// move code's group field) and stores walks that never change in the per-map gap after the group/altar data (offset 16 + 3(ng + na),
// never past the Prism block at 736): magic, version, n, scale, mode, route count, then S: per group the camps-blocked walk from our
// spawn (ng bytes), R: opening routes: for the groups nearest our spawn, the first the stored route length steps of the walk from
// the best spawn tile (group, x, y, length, 3-bit directions), G: group-to-group walks (best approach tile of a + 1; min of both
// directions): the upper triangle, or each group's k nearest (id, dist) when the triangle does not fit, then a 2-byte checksum.
// Champions check it and fail safe (no block = no exact travel). They decode S and G into dense tables once (lazily, with fuel), so
// a read is one load. Runtime data flag XT_TAB slot 1 (bits; 0 = no draft work, no decode, no read): 1 = compute_travel on a camp
// tile of group a: every other group's walk = G(a, b) (all group fields read UNREACH on a camp tile); 2 = compute_travel, a group
// with no field: min over my 3 nearest built groups (walk <= XT_NEAR) of walk + G, and of home walk (<= XT_NEAR) + S; 4 = opening
// steps (the opening start and prestep paths) with no field follow the stored route instead of a wall-blind Chebyshev step.
#define EXACT_TRAVEL 3
inline constexpr int XT_TAB[4] = { 0x58545256, EXACT_TRAVEL, 8, 20 }; // Slots: magic, EXACT_TRAVEL bits, near-group walk limit, route length.
#define XT_V (XT_TAB[1])
#define XT_NEAR (XT_TAB[2])
constexpr std::uint8_t XT_MAGIC = 0x58, XT_VERSION = 1;
constexpr std::size_t XT_END = 736; // the Prism plan block starts here
constexpr int XT_MAXR = 16;         // opening routes stored at most
constexpr int XT_MAXRL = 40;        // longest stored route
bool travel_build_step(long reserve);                    // draft: resumable fields -> tables; true when finished
void travel_write(std::vector<std::uint8_t>& mem); // draft: put the block into the memory buffer (once the tables are done)
bool xt_ready();                               // champions: a block decoded
bool xt_dense();                               // champions: the dense tables are built (travel_table_build), reads below are valid
bool travel_table_build(long reserve);                   // champions: build the dense tables once if `reserve` fuel remains after
void travel_close_step(long reserve);              // champions: fill k-list gaps through stored neighbours (spare fuel)
const std::uint16_t* travel_table(int* n, const std::uint16_t** spawn, const std::uint8_t** derived); // champions: dense n x n walks

// Tank score used to pick party leads (higher = better camp tank).

// Camp-tank order from the engine clear simulations (0 = best): HoR, Varg, Ryth, Marcella, Ren, Issac, Vendetta,
// Vesper Vale, Tavi, Stellar, Willow, Prism, Cassi.
int camp_tank_rank(cambc::champion_type t);

} // namespace nova
