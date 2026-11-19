// comms.cc: The 8-byte team shared-memory protocol. bytes 0..5: one claim byte per body slot: bits 0-6 = target group index + 1 (0 = none),
#include "comms.h"
#include "econ.h"
#include "plan.h"
#include "contest_play.h"
#include "champions.h"

#include <bit>

namespace nova::comms {

namespace {
std::array<std::uint8_t, 8> mem{};
std::uint16_t seen_raw = 0; // the slot bytes this body last saw and the round it first saw them
int seen_round = -1000, cur_round = 0;
std::uint16_t raw_now() { return static_cast<std::uint16_t>(mem[6] | (mem[7] << 8)); }

// Packed team word (bit 1 of the packing flag). mem[] above stays the 8-byte image, decoded at read(), so every reader goes through
// claim() and event(). Host layout, low bits first: event (stamp 5 bits, code ek bits), then cb bits per body slot, then free bits
// to bit 63. Claim code: 0 none, g = group + 1 free, ng + g engaged, so cb = bit_width(2 ng). Event code: 0 empty; 1 + (subject << 2
// | type) for news types 0-3 (subject < ng + na); then HELP cells; then type 5 crew calls (subject = group). Group and altar counts
// come from the draft's memory, the same on every body all game; with no valid memory or more than 126 groups the 8-byte layout is
// used. Turns run one at a time but a fuel-cut turn resumes later on stale state, so a write re-reads the host first and writes only
// the bytes it touches. Only the window between that read and write can lose a mate's bits, and the mate's next publish restores
// them (mem[] is re-read each turn, so write_claim sees the difference).
struct PkLayout
{
	bool init = false, on = false;
	int cb = 8, ng = 0, ns = 0, cells = 0, ek = 0, ebits = 16, top = 48;
	bool ev2 = false, c2 = false;
	int c = 1, cells6 = 0;
	// Variable claim layout, used only when the slim-layout flag is nonzero and TM2 bit 8 is in force.
	bool var = false, sq = false;
	int per = 4, hs = -1, ci_c = -1, ci_i = -1, cbits = 0;
	int slim = 0, saved = 0; // 0 off, 1 slim, 2 slim + coming; claim bits freed against the full layout
	std::array<int, CLAIM_SLOTS> off{}, wd{};
} L;
std::array<int, CLAIM_SLOTS> v_raw{}; // the field value last read or written per slot
int v_mir = -1; // TMS bit 1: the slot the healer's next write mirrors
// the slim field with compact 'coming' codes, 19 (3) or 10 (4); the retreat code at 2 ng + 2. Only reached when L.slim != 2 (the
// packing init set it from the flag).
static int slim4_of_full(int c)
{
	const int ng = L.ng;
	if (c < 4)
		return 0;
	if (c < 4 + 4 * ng)
		return 2 + (c - 4) / 4;
	if (c < 4 + 8 * ng)
		return 2 + ng + (c - 4 - 4 * ng) / 4;
	if (c >= 4 + 8 * ng + 8 && c < 4 + 8 * ng + 12 && 2 * ng + 50 < (1 << std::bit_width(static_cast<unsigned>(2 * ng + 49))))
		return 2 * ng + 2; // the retreat code
	if (c < 16 + 8 * ng)
		return 1;
	const int ci = std::min(c - 16 - 8 * ng, 47), e = ci >> 4, o = (ci >> 1) & 7, h = ci & 1; // brain tm2_coming: ETA x octant x HP
	if (L.slim == 4)
		return 2 * ng + 3 + (e == 1 && h == 0 ? o : e >= 2 ? 8 : 9);
	return 2 * ng + 3 + (e <= 1 && h == 0 ? e * 8 + o : e <= 1 ? 16 + e : 18);
}
static int full_code_from_slim4_code(int f)
{
	const int ng = L.ng;
	if (f <= 0)
		return 0;
	if (f == 1)
		return 4 + 8 * ng;
	if (f < 2 + ng)
		return 4 + 4 * (f - 2);
	if (f < 2 + 2 * ng)
		return 4 + 4 * ng + 4 * (f - 2 - ng);
	if (f == 2 * ng + 2)
		return 4 + 8 * ng + 8;
	const int x = f - 2 * ng - 3;
	if (L.slim == 4)
		return 16 + 8 * ng + (x < 8 ? 16 + x * 2 : x == 8 ? 32 : 17);
	return 16 + 8 * ng + (x < 16 ? (x >> 3) * 16 + (x & 7) * 2 : x < 18 ? (x - 16) * 16 + 1 : 32);
}
// full claim code (per-4 code) <-> the slim field
inline int claim_code_to_slim_field(int c)
{
	if (L.slim != 2) // the compact field
		return slim4_of_full(c);
	const int ng = L.ng;
	if (c < 4)
		return 0;
	if (c < 4 + 4 * ng)
		return 2 + (c - 4) / 4;
	if (c < 4 + 8 * ng)
		return 2 + ng + (c - 4 - 4 * ng) / 4;
	if (c >= 4 + 8 * ng + 8 && c < 4 + 8 * ng + 12 && 2 * ng + 50 < (1 << L.cb))
		return 2 * ng + 50; // a retreat keeps its own slim code, where the field has room
	if (c < 16 + 8 * ng)
		return 1; // in a fight: one code (the stance x HP value is unread)
	return L.slim == 2 ? 2 + 2 * ng + std::min(c - 16 - 8 * ng, 47) : 0;
}
inline int full_code_from_slim_code(int f)
{
	if (L.slim != 2) // the compact field
		return full_code_from_slim4_code(f);
	const int ng = L.ng;
	if (f <= 0)
		return 0;
	if (f == 2 * ng + 50)
		return 4 + 8 * ng + 8; // the retreat slim code -> FL1 retreat, band 0
	if (f == 1)
		return 4 + 8 * ng;
	if (f < 2 + ng)
		return 4 + 4 * (f - 2);
	if (f < 2 + 2 * ng)
		return 4 + 4 * ng + 4 * (f - 2 - ng);
	return 16 + 8 * ng + std::min(f - 2 - 2 * ng, 47);
}
// Code range (per = 1 with bit 4, else 4): 0-3 idle/dead, heading g x per, engaged g x per, 12 fight, 48 coming.
inline int claim_code_of_state(int group, bool engaged, int x)
{
	const int ng = L.ng, pe = L.per;
	if (group >= 0 && group < ng)
		return 4 + (engaged ? pe * ng : 0) + pe * group + (L.sq ? 0 : std::clamp(x, 0, 3));
	if (x >= 200)
		return 16 + 2 * pe * ng + std::min(x - 200, 47);
	if (x >= 100)
		return 4 + 2 * pe * ng + std::min(x - 100, 11);
	return std::clamp(x, 0, 3);
}
inline std::uint8_t claim_byte_image(int c)
{
	const int ng = L.ng, pe = L.per;
	if (c < 4 || c >= 4 + 2 * pe * ng)
		return 0;
	const int x = c - 4;
	return static_cast<std::uint8_t>(x < pe * ng ? x / pe + 1 : ((x - pe * ng) / pe + 1) | ENGAGED);
}
inline void set_view_claim(int s, int c)
{
	const auto su = static_cast<std::size_t>(s);
	const int ng = L.ng, pe = L.per;
	int k = 0, v = c;
	if (c < 4)
		k = c ? 1 : 0;
	else if (c < 4 + pe * ng)
		k = 2, v = (c - 4) % pe;
	else if (c < 4 + 2 * pe * ng)
		k = 3, v = (c - 4) % pe;
	else if (c < 16 + 2 * pe * ng)
		k = 4, v = c - 4 - 2 * pe * ng;
	else
		k = 5, v = c - 16 - 2 * pe * ng;
	V.ck[su] = static_cast<std::uint8_t>(k);
	V.cv[su] = static_cast<std::uint8_t>(v);
}
int c2_x = 0; // the next write's bucket
std::array<int, CLAIM_SLOTS> c2_code{};                 // the code last read or written per slot
inline std::uint8_t claim_code_memory_byte(int c)
{
	const int ng = L.ng;
	if (c < 4 || c >= 4 + 8 * ng)
		return 0;
	const int x = c - 4;
	return static_cast<std::uint8_t>(x < 4 * ng ? (x >> 2) + 1 : (((x - 4 * ng) >> 2) + 1) | ENGAGED);
}
inline void claim_code_decode_view(int s, int c)
{
	const auto su = static_cast<std::size_t>(s);
	const int ng = L.ng;
	int k = 0, v = c;
	if (c < 4)
		k = c ? 1 : 0;
	else if (c < 4 + 4 * ng)
		k = 2, v = (c - 4) & 3;
	else if (c < 4 + 8 * ng)
		k = 3, v = (c - 4) & 3;
	else if (c < 16 + 8 * ng)
		k = 4, v = c - 4 - 8 * ng;
	else
		k = 5, v = c - 16 - 8 * ng;
	V.ck[su] = static_cast<std::uint8_t>(k);
	V.cv[su] = static_cast<std::uint8_t>(v);
}
std::uint64_t word = 0; // the host's 8 bytes at the last read(), plus my own puts
std::uint64_t dec_word = 0; // The word mem[] was last decoded from.
bool dec_ok = false;
int bad_writes = 0;
__attribute__((always_inline)) void init_message_layout()
{
	if (L.init)
		return;
	L.init = true;
	const int ng = dmem::total_groups(), na = dmem::total_altars();
	if (ng < 0 || ng > 126 || na < 0 || G.w <= 0 || G.h <= 0)
		return;
	int c = 1; // Cell size of the help grid: the smallest c that gives at most 254 cells.
	while (((G.w + c - 1) / c) * ((G.h + c - 1) / c) > 254)
		++c;
	L.ng = ng;
	L.ns = ng + na;
	L.cells = ((G.w + c - 1) / c) * ((G.h + c - 1) / c);
	L.ek = std::bit_width(static_cast<unsigned>(4 * L.ns + L.cells + ng));
	L.ebits = 5 + L.ek;
	L.cb = std::max(1, static_cast<int>(std::bit_width(static_cast<unsigned>(2 * ng))));
	L.top = 64;
	L.on = true;
	L.c = c;
	L.cells6 = ((G.w + 5) / 6) * ((G.h + 5) / 6);
	L.ev2 = true;
	L.ek = 0;
	L.ebits = 0;
	if (P.n > 0)
	{
		const int cb2 = std::bit_width(static_cast<unsigned>(8 * ng + 63));
		int w = 1;
		while ((1 << w) < team_mem_code_count(ng))
			++w;
		if (L.ebits + std::clamp(P.n, 0, CLAIM_SLOTS) * cb2 + w + 1 <= 64)
		{
			L.cb = cb2;
			L.c2 = true;
		}
		{
			const int n = std::clamp(P.n, 0, CLAIM_SLOTS);
			const int sl = (4);
			const int cbw = std::max(1, static_cast<int>(std::bit_width(static_cast<unsigned>(2 * ng + 12)))); // compact widths
			int o = 0;
			for (int s = 0; s < n; ++s)
			{
				L.wd[static_cast<std::size_t>(s)] = cbw;
				L.off[static_cast<std::size_t>(s)] = o;
				o += cbw;
			}
			if (L.ebits + n * cb2 + w + 1 <= 64) // only where the full claims fit: the same information, fewer bits
			{
				L.per = 4;
				L.saved = n * cb2 - o;
				L.sq = false;
				L.slim = sl;
				L.cbits = o;
				L.cb = cbw;
				L.c2 = true;
				L.var = true;
			}
		}
	}
}

std::uint64_t read_host_shared_word()
{
	std::array<std::uint8_t, 8> b{};
	cambc::shared_memory.read(0, std::span<std::uint8_t>{ b.data(), b.size() });
	std::uint64_t w = 0;
	std::memcpy(&w, b.data(), 8);
	return w;
}

std::uint64_t lineup_mask(int w) { return w >= 64 ? ~0ULL : ((1ULL << w) - 1ULL); }
void write_memory_bits(int off, int w, std::uint64_t v)
{
	try
	{
		std::uint64_t cur = read_host_shared_word();
		const std::uint64_t m = lineup_mask(w) << off;
		cur = (cur & ~m) | ((v << off) & m);
		word = cur;
		dec_word = (dec_word & ~m) | (cur & m); // the caller set mem[] for these bits, so the next read needn't decode them again
		std::array<std::uint8_t, 8> b{};
		std::memcpy(b.data(), &cur, 8);
		const std::size_t lo = static_cast<std::size_t>(off) >> 3, hi = static_cast<std::size_t>(off + w - 1) >> 3;
		cambc::shared_memory.write(lo, std::as_bytes(std::span<const std::uint8_t>{ b.data() + lo, hi - lo + 1 }));
	}
	catch (...)
	{
		FXR_PASS();
	}
}

bool read_packed_team_word() // true: mem[] may have changed
{
	init_message_layout();
	try
	{
		word = read_host_shared_word();
	}
	catch (...)
	{
		FXR_PASS();
		return false;
	}
	if (word == dec_word && dec_ok)
		return false; // nothing changed since my last decode: mem[] is still right (my own claim and event are part of word)
	const std::uint64_t changed = dec_ok ? (word ^ dec_word) : ~0ULL;
	dec_word = word;
	dec_ok = true;
	const int n = std::clamp(P.n, 0, CLAIM_SLOTS);
	if (!L.on)
	{
		std::memcpy(mem.data(), &word, 8);
		for (int s = n; s < CLAIM_SLOTS; ++s)
			mem[static_cast<std::size_t>(s)] = 0; // free bytes of the 8-byte layout are not claims
		return true;
	}
	std::uint64_t w = word >> L.ebits, ch = changed >> L.ebits;
	if (L.var) // per-slot widths; the shared slots follow their source slot after every decode
	{
		for (int s = 0; s < n; ++s)
		{
			const auto su = static_cast<std::size_t>(s);
			const std::uint64_t m = lineup_mask(L.wd[su]);
			if (ch & m)
			{
				const int c = static_cast<int>(w & m);
				v_raw[su] = c;
				if (s != L.hs && s != L.ci_i)
				{
					c2_code[su] = c;
					mem[su] = claim_byte_image(c);
					set_view_claim(s, c);
				}
				if (L.slim && s != L.hs && s != L.ci_i) // the slim field as the full code
				{
					const int cf = full_code_from_slim_code(c);
					c2_code[su] = cf;
					mem[su] = claim_byte_image(cf);
					set_view_claim(s, cf);
				}
			}
			w >>= L.wd[su];
			ch >>= L.wd[su];
		}
		const auto follow = [&](int s, int src)
		{
			if (s < 0 || s == P.my_slot)
				return; // my own slot keeps my full code
			const auto su = static_cast<std::size_t>(s);
			int c = 0;
			if (src >= 0 && src < n && src != s)
			{
				const std::uint8_t im = mem[static_cast<std::size_t>(src)];
				const int g = static_cast<int>(im & 0x7F) - 1;
				if (g >= 0)
					c = claim_code_of_state(g, (im & ENGAGED) != 0, 0);
			}
			c2_code[su] = c;
			mem[su] = claim_byte_image(c);
			set_view_claim(s, c);
		};
		if (L.ci_i >= 0)
			follow(L.ci_i, v_raw[static_cast<std::size_t>(L.ci_i)] ? L.ci_c : -1); // before the healer, who may mirror Issac
		if (L.hs >= 0)
			follow(L.hs, v_raw[static_cast<std::size_t>(L.hs)] - 1);
		ch = 0; // the claim loop below has nothing left to read
	}
	const std::uint64_t cm = lineup_mask(L.cb);
	for (int s = 0; ch != 0 && s < n; ++s) // only the slots that moved; slots past n stay 0, nothing writes them
	{
		if (ch & cm)
		{
			const int c = static_cast<int>(w & cm);
			if (L.c2)
			{
				c2_code[static_cast<std::size_t>(s)] = c;
				mem[static_cast<std::size_t>(s)] = claim_code_memory_byte(c);
				claim_code_decode_view(s, c);
			}
			else
			mem[static_cast<std::size_t>(s)] = static_cast<std::uint8_t>(c <= L.ng ? c : ((c - L.ng) | ENGAGED));
		}
		w >>= L.cb;
		ch >>= L.cb;
	}
	if ((changed & lineup_mask(L.ebits)) == 0)
		return true;
	const int stamp = static_cast<int>(word & 31);
	const int e = static_cast<int>((word >> 5) & lineup_mask(L.ek));
	if (e == 0)
	{
		mem[6] = 0;
		mem[7] = 0;
		return true;
	}
	int type = 0, subj = 0;
	const int x = e - 1, news = 4 * L.ns;
	if (x < news)
	{
		type = x & 3;
		subj = x >> 2;
	}
	else if (x < news + L.cells)
	{
		type = EV_TYPE_HELP;
		subj = x - news;
	}
	else
	{
		type = 5;
		subj = x - news - L.cells;
	}
	mem[6] = static_cast<std::uint8_t>(subj + 1);
	mem[7] = static_cast<std::uint8_t>((type << 5) | stamp);
	return true;
}

// TEAM MEMORY VIEW (TM_TAB bit 1): the one decode of the cached image into V (claims and event as their readers see them).
void decode_claim_byte(int s)
{
	const std::uint8_t c = mem[static_cast<std::size_t>(s)];
	V.cg[static_cast<std::size_t>(s)] = static_cast<std::int8_t>(static_cast<int>(c & 0x7F) - 1);
	V.ce[static_cast<std::size_t>(s)] = (c & ENGAGED) ? 1 : 0;
}
void decode_team_memory_view()
{
	for (int s = 0; s < CLAIM_SLOTS; ++s)
		decode_claim_byte(s);
	V.ev = event();
}
}

View V;

void claim_x(int x) { c2_x = x; }
int help_c() { return L.c; }
int slim_saved() { return L.slim ? std::max(0, L.saved) : 0; }
bool slim_layout() { return L.var && L.slim != 0; } // the slim claim layout is in force (the bucket is not sent)
int team_mem_code_count(int ng)
{
	const int cells6 = ((G.w + 5) / 6) * ((G.h + 5) / 6);
	return 1 + 24 * ng + 4 * cells6 + ng + (L.ev2 ? 4 * L.ns : 0);
}
void legacy_in(int subject, int type, int round)
{
	if (subject < 0 || subject >= 255 || type < 0 || type > 7)
		return;
	mem[6] = static_cast<std::uint8_t>(subject + 1);
	mem[7] = static_cast<std::uint8_t>((type << 5) | (round & STAMP_MASK));
	V.ev = event();
}
LegacyQ lq;

namespace {
int spare_top = -1;
int spare_low()
{
	const int n = std::clamp(P.n, 0, CLAIM_SLOTS);
	return L.on ? L.ebits + (L.var ? L.cbits : n * L.cb) : n * 8;
}
}

int spare_bits()
{
	init_message_layout();
	return std::max(0, (spare_top < 0 ? L.top : spare_top) - spare_low());
}

Spare spare_alloc(int width)
{
	Spare f;
	if (width < 1 || width > 32)
		return f;
	init_message_layout();
	if (spare_top < 0)
		spare_top = L.top;
	if (spare_top - width < spare_low())
		return f;
	spare_top -= width;
	f.off = spare_top;
	f.w = width;
	return f;
}

std::uint32_t spare_get(Spare f)
{
	if (!f.ok())
		return 0;
	return static_cast<std::uint32_t>((word >> f.off) & lineup_mask(f.w));
}

void spare_put(Spare f, std::uint32_t v)
{
	if (f.ok() && spare_get(f) != (v & lineup_mask(f.w)))
		write_memory_bits(f.off, f.w, v);
}

void note_seen(int round)
{
	cur_round = round;
	const std::uint16_t r = raw_now();
	if (r != seen_raw)
	{
		seen_raw = r;
		seen_round = round;
	}
}

int rounds_since_event_slot_changed(int now)
{
	if (raw_now() != seen_raw)
		return 0;
	return std::max(0, now - seen_round);
}
int event_age_rounds(const Event& e, int now)
{
	int a = (now - e.stamp) & STAMP_MASK;
	const int f = rounds_since_event_slot_changed(now);
	if (f > a)
		a += (STAMP_MASK + 1) * ((f - a + STAMP_MASK) / (STAMP_MASK + 1));
	return a;
}
void read()
{
	if (read_packed_team_word() && TMEM_ON)
		decode_team_memory_view();
	return;
}

std::uint8_t claim(int slot)
{
	if (slot < 0 || slot >= CLAIM_SLOTS)
		return 0;
	return mem[static_cast<std::size_t>(slot)];
}

int claim_group(std::uint8_t c)
{
	return static_cast<int>(c & 0x7F) - 1;
}
void write_claim(int slot, int group, bool engaged)
{
	fxr_poll(); // FXR bit 1: a stale call never writes or acts
	if (slot < 0 || slot >= CLAIM_SLOTS)
		return;
	init_message_layout();
	if (L.var) // my full code stays in my own view; the word gets my slot's field
	{
		const int x = c2_x;
		c2_x = 0;
		const int mir = v_mir;
		v_mir = -1;
		const int c = claim_code_of_state(group, engaged, x);
		const auto su = static_cast<std::size_t>(slot);
		int f = c;
		if (L.slim) // the word gets the slim field
			f = claim_code_to_slim_field(c);
		if (slot == L.hs)
			f = mir >= 0 && mir < P.n && mir != slot ? mir + 1 : 0;
		else if (slot == L.ci_i)
			f = group >= 0 && group == cgroup(L.ci_c) ? 1 : 0;
		if (c != c2_code[su])
		{
			c2_code[su] = c;
			mem[su] = claim_byte_image(c);
			decode_claim_byte(slot);
			set_view_claim(slot, c);
		}
		if (f == v_raw[su])
			return;
		v_raw[su] = f;
		write_memory_bits(L.ebits + L.off[su], L.wd[su], static_cast<std::uint64_t>(f));
		return;
	}
	if (L.c2)
	{
		const int x = c2_x;
		c2_x = 0;
		int c = 0;
		if (group >= 0 && group < L.ng)
			c = 4 + (engaged ? 4 * L.ng : 0) + 4 * group + std::clamp(x, 0, 3);
		else if (x >= 200)
			c = 16 + 8 * L.ng + std::min(x - 200, 47);
		else if (x >= 100)
			c = 4 + 8 * L.ng + std::min(x - 100, 11);
		else
			c = std::clamp(x, 0, 3);
		if (c == c2_code[static_cast<std::size_t>(slot)])
			return;
		c2_code[static_cast<std::size_t>(slot)] = c;
		mem[static_cast<std::size_t>(slot)] = claim_code_memory_byte(c);
		decode_claim_byte(slot);
		claim_code_decode_view(slot, c);
		write_memory_bits(L.ebits + slot * L.cb, L.cb, static_cast<std::uint64_t>(c));
		return;
	}
	std::uint8_t v = 0;
	if (group >= 0 && group < 127)
		v = static_cast<std::uint8_t>(group + 1);
	if (v != 0 && engaged)
		v |= ENGAGED;
	if (mem[static_cast<std::size_t>(slot)] == v)
		return;
	mem[static_cast<std::size_t>(slot)] = v;
	decode_claim_byte(slot);
	init_message_layout();
	if (L.on)
	{
		const int g = v & 0x7F;
		if (g > L.ng)
		{
			++bad_writes;
			write_memory_bits(L.ebits + slot * L.cb, L.cb, 0);
			return;
		}
		write_memory_bits(L.ebits + slot * L.cb, L.cb, static_cast<std::uint64_t>((v & ENGAGED) ? L.ng + g : g));
		return;
	}
	try
	{
		cambc::shared_memory[static_cast<std::size_t>(slot)] = v;
	}
	catch (...)
	{
		FXR_PASS();
	}
}

Event event()
{
	Event e;
	e.raw = static_cast<std::uint16_t>(mem[6] | (mem[7] << 8));
	if (mem[6] == 0)
		return e;
	e.subject = static_cast<int>(mem[6]) - 1;
	e.type = mem[7] >> 5;
	e.stamp = mem[7] & STAMP_MASK;
	return e;
}
bool bh64_help_dropped = false;
void write_event(int subject, int type, int round)
{
	fxr_poll(); // FXR bit 1: a stale call never writes or acts
	if (subject < 0 || subject >= 255 || type < 0 || type > 7)
		return;
	const std::uint8_t s = static_cast<std::uint8_t>(subject + 1);
	const std::uint8_t t = static_cast<std::uint8_t>((type << 5) | (round & STAMP_MASK));
	if (mem[6] == s && mem[7] == t)
		return;
	const std::uint8_t o6 = mem[6], o7 = mem[7]; // TMF bit 2: restored when the channel drops this post
	const Event oev = V.ev;
	const std::uint16_t osr = seen_raw;
	const int osd = seen_round;
	mem[6] = s;
	mem[7] = t;
	V.ev = event();
	seen_raw = raw_now(); // my own post is new to me now
	seen_round = cur_round;
	init_message_layout();
	if (L.ev2)
	{
		if (type == EV_TYPE_HELP) // A dropped HELP leaves no image.
		{
			econ::bh64_lp_drop = false;
			econ::team_mem_post_legacy_event(subject, type, round);
			bh64_help_dropped = econ::bh64_lp_drop;
			if (bh64_help_dropped)
			{
				mem[6] = o6;
				mem[7] = o7;
				V.ev = oev;
				seen_raw = osr;
				seen_round = osd;
			}
			return;
		}
		econ::team_mem_post_legacy_event(subject, type, round); // TM2 bit 16
		return;
	}
	if (L.on)
	{
		const int news = 4 * L.ns;
		int code = -1;
		if (type < EV_TYPE_HELP && subject < L.ns)
			code = 1 + ((subject << 2) | type);
		else if (type == EV_TYPE_HELP && subject < L.cells)
			code = 1 + news + subject;
		else if (type == 5 && subject < L.ng)
			code = 1 + news + L.cells + subject;
		if (code < 0)
		{
			++bad_writes;
			return;
		}
		write_memory_bits(0, L.ebits, (static_cast<std::uint64_t>(code) << 5) | static_cast<std::uint64_t>(round & STAMP_MASK));
		return;
	}
	try
	{
		const std::array<std::uint8_t, 2> b{ s, t };
		cambc::shared_memory.write(6, std::as_bytes(std::span{ b }));
	}
	catch (...)
	{
		FXR_PASS();
	}
}

} // namespace nova::comms
