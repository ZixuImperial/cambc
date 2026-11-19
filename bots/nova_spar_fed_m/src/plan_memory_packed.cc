// plan_memory_packed.cc: Packed draft memory: layout and readers.
#include "plan_internal.h"
namespace nova {
namespace dmem {
namespace {
constexpr std::uint8_t PK_VERSION = 2;
constexpr std::uint8_t PRISM_MAGIC = 0x50, PRISM_VERSION = 1; // Prism block header (see champ_prism.cc).
constexpr std::size_t PK_HEAD = 4;                            // magic, version, groups, altars
struct BW // the buffer is zeroed and holds 8 spare bytes past cap, so a 64-bit load and store never leave it
{
	std::uint8_t* p;
	std::size_t cap, bits = 0;
	bool over = false;
	void put(std::uint32_t v, int w)
	{
		if (bits + static_cast<std::size_t>(w) > cap * 8)
		{
			over = true;
			return;
		}
		std::uint64_t x;
		std::memcpy(&x, p + (bits >> 3), 8);
		x |= static_cast<std::uint64_t>(v) << (bits & 7);
		std::memcpy(p + (bits >> 3), &x, 8);
		bits += static_cast<std::size_t>(w);
	}
};
struct BR // rolling 64-bit window, about 10 instructions a field
{
	const std::uint8_t* p;
	std::size_t cap, i = 0;
	std::uint64_t acc = 0;
	int nb = 0;
	std::uint32_t get(int w)
	{
		if (nb < w)
		{
			std::uint32_t x = 0;
			if (i + 4 <= cap)
				std::memcpy(&x, p + i, 4);
			else if (i < cap)
				std::memcpy(&x, p + i, cap - i);
			i += 4;
			acc |= static_cast<std::uint64_t>(x) << nb;
			nb += 32;
		}
		const std::uint32_t v = static_cast<std::uint32_t>(acc & ((1ULL << w) - 1ULL));
		acc >>= w;
		nb -= w;
		return v;
	}
	std::size_t bits() const { return i * 8 - static_cast<std::size_t>(nb); }
};
int bw(unsigned x) { return static_cast<int>(std::bit_width(x)); }

std::array<std::uint8_t, 1024> img{};
std::size_t img_n = 0;
int loaded = 0; // 0 not yet, 1 raw (old image or nothing), 2 expanded.
std::size_t xt_len = 0, xt_at = 0, xt_E = 0;
const std::uint8_t* pk_dist = nullptr; // 2 bytes per group, then per altar
const std::uint8_t* pk_acc = nullptr;  // group access, 2 bits each
const std::uint8_t* pk_aacc = nullptr; // altar gated + access, 4 bits each
struct Extra
{
	std::uint32_t v;
	std::uint8_t id, w, set;
};
std::array<Extra, 16> ex_w{}, ex_r{};
int ex_wn = 0;
std::vector<std::uint8_t> dmf_blob_w; // The draft's tail blob, appended by pack when it fits.
std::size_t xc_bit = 0; // XC: absolute bit offset of the compact XT block in cambc::draft_memory
long xc_cost = 0; // Compact-block draft: fuel pack() spent on the compact block since the last compact_encode_cost(true)
                         // (one-time work, kept out of the handoff's cost estimates: the 100k draft turns read them)
std::vector<std::uint8_t> xc_ckey, xc_cbits; // XC draft: the block last encoded (bytes, + pass) and its bits; a repack copies them
bool xc_has = false;

// Rice codes with an escape (unary quotient < 15, else 15 zeros, a one, the value in 10 bits).
constexpr int XC_FMT = 1, XC_ESC = 15;
struct RR // LSB-first bit reader from any bit offset; reads past the end give zeros (then `bad`).
{
	const std::uint8_t* p = nullptr;
	std::size_t cap = 0, i = 0;
	std::uint64_t acc = 0;
	int nb = 0;
	bool bad = false;
	RR() = default;
	RR(const std::uint8_t* p_, std::size_t cap_, std::size_t bit) : p(p_), cap(cap_), i(bit >> 3)
	{
		fill();
		const int r = static_cast<int>(bit & 7);
		acc >>= r;
		nb -= r;
	}
	void fill() // to >= 33 bits (byte loads: a 4-byte memcpy is a libc call here, ~50 fuel)
	{
		while (nb <= 32)
		{
			std::uint32_t x = 0;
			if (i + 4 <= cap)
				x = static_cast<std::uint32_t>(p[i]) | (static_cast<std::uint32_t>(p[i + 1]) << 8) | (static_cast<std::uint32_t>(p[i + 2]) << 16) |
					(static_cast<std::uint32_t>(p[i + 3]) << 24);
			else
				for (std::size_t k = 0; k < 4 && i + k < cap; ++k)
					x |= static_cast<std::uint32_t>(p[i + k]) << (8 * k);
			acc |= static_cast<std::uint64_t>(x) << nb;
			i += 4;
			nb += 32;
		}
	}
	unsigned get(int w) // w <= 32
	{
		if (w <= 0)
			return 0;
		if (nb < w)
			fill();
		const unsigned v = static_cast<unsigned>(acc & ((1ULL << w) - 1ULL));
		acc >>= w;
		nb -= w;
		return v;
	}
	unsigned rice(int k)
	{
		if (nb < 32)
			fill();
		const std::uint64_t lo = acc & ((1ULL << (XC_ESC + 1)) - 1ULL);
		if (lo == 0)
		{
			bad = true;
			return 0;
		}
		const int u = __builtin_ctzll(lo);
		acc >>= u + 1;
		nb -= u + 1;
		if (u >= XC_ESC)
			return get(10);
		return (static_cast<unsigned>(u) << k) | get(k);
	}
};
// XC decoder core, resumable: it emits the old block's bytes in order (header, S, routes; then G row by row; then the checksum), so
// the draft checks the exact bytes champions will read and champions turn each row into their tables. Lower bounds: a walk >= max(1,
// box gap) (Chebyshev gap of the camp-tile boxes; S: our spawn's box), quantised like the stored value.
struct XcDec
{
	RR r;
	std::size_t n = 0;
	int scale = 1, kg = 0, kf = 0, kd = 0, cb = 0, ib = 0;
	unsigned mode = 0, nr = 0;
	std::vector<int> bx;            // x0, y0, x1, y1 per group
	std::vector<std::uint8_t> wk;   // 1 = walkable group
	std::vector<std::uint8_t> head; // header, S and routes bytes
	std::uint8_t row[512];          // the last row's G bytes
	std::size_t rlen = 0;
	int sp[4] = { 1 << 20, 1 << 20, -(1 << 20), -(1 << 20) };
	void geo() // the boxes (draft and champions alike: camps and our spawn are static)
	{
		bx.assign(4 * n, 0);
		for (std::size_t a = 0; a < n; ++a)
		{
			int* b = bx.data() + 4 * a;
			b[0] = b[1] = 1 << 20;
			b[2] = b[3] = -(1 << 20);
			if (a < static_cast<std::size_t>(M.ng))
				for (const int ci : M.groups[a].members)
				{
					if (ci < 0 || ci >= M.nc)
						continue;
					const vec2 p = M.camps[static_cast<std::size_t>(ci)].pos;
					b[0] = std::min(b[0], p.x);
					b[1] = std::min(b[1], p.y);
					b[2] = std::max(b[2], p.x);
					b[3] = std::max(b[3], p.y);
				}
		}
		sp[0] = sp[1] = 1 << 20;
		sp[2] = sp[3] = -(1 << 20);
		bbforeach(M.my_spawn,
			[&](vec2 p)
			{
				sp[0] = std::min(sp[0], p.x);
				sp[1] = std::min(sp[1], p.y);
				sp[2] = std::max(sp[2], p.x);
				sp[3] = std::max(sp[3], p.y);
			});
	}
	int lg(std::size_t a, std::size_t b) const { return lbq(gap4(bx.data() + 4 * a, bx.data() + 4 * b)); }
	int ls(std::size_t a) const { return lbq(gap4(sp, bx.data() + 4 * a)); }
	int lbq(int gap) const { return std::min(254, scale == 1 ? std::max(1, gap) : (std::max(1, gap) + scale - 1) / scale); }
	static int gap4(const int* A, const int* B)
	{
		if (A[2] < A[0] || B[2] < B[0])
			return 0;
		return std::max(std::max(std::max(0, B[0] - A[2]), A[0] - B[2]), std::max(std::max(0, B[1] - A[3]), A[1] - B[3]));
	}
	// header .. routes, the boxes, the G parameters; false: refuse the block
	bool begin(const RR& r0, std::size_t n_, const std::uint8_t* acc)
	{
		r = r0;
		n = n_;
		if (!xt_group_count_ok(n) || r.get(4) != static_cast<unsigned>(XC_FMT))
			return false;
		scale = static_cast<int>(r.get(8));
		mode = r.get(8);
		nr = r.get(5);
		if (scale < 1 || (mode != 0 && mode != 255 && mode > 8) || nr > static_cast<unsigned>(XT_MAXR))
			return false;
		wk.assign(n, 0);
		for (std::size_t a = 0; a < n; ++a)
			wk[a] = ((acc[a >> 2] >> ((a & 3) * 2)) & 3) == ACC_WALK ? 1 : 0;
		geo();
		head.clear();
		head.reserve(6 + n + 16 * nr);
		head.push_back(XT_MAGIC);
		head.push_back(XT_VERSION);
		head.push_back(static_cast<std::uint8_t>(n));
		head.push_back(static_cast<std::uint8_t>(scale));
		head.push_back(static_cast<std::uint8_t>(mode));
		head.push_back(static_cast<std::uint8_t>(nr));
		const int ks = static_cast<int>(r.get(3));
		for (std::size_t a = 0; a < n; ++a)
		{
			if (!wk[a])
			{
				head.push_back(255);
				continue;
			}
			const unsigned v = r.rice(ks);
			const int qv = v == 0 ? 255 : ls(a) + static_cast<int>(v) - 1;
			if (v != 0 && qv > 254)
				return false;
			head.push_back(static_cast<std::uint8_t>(qv));
		}
		for (unsigned i = 0; i < nr; ++i)
		{
			const unsigned gi = r.get(8), x = r.get(8), y = r.get(8), len = r.get(6);
			if (gi >= n || len == 0 || len > static_cast<unsigned>(XT_MAXRL))
				return false;
			head.push_back(static_cast<std::uint8_t>(gi));
			head.push_back(static_cast<std::uint8_t>(x));
			head.push_back(static_cast<std::uint8_t>(y));
			head.push_back(static_cast<std::uint8_t>(len));
			const std::size_t o = head.size();
			head.resize(o + (len * 3 + 7) / 8, 0);
			for (unsigned j = 0; j < len; ++j)
			{
				const unsigned bit = 3 * j, v = r.get(3);
				head[o + (bit >> 3)] |= static_cast<std::uint8_t>((v << (bit & 7)) & 255);
				if ((bit & 7) > 5)
					head[o + (bit >> 3) + 1] |= static_cast<std::uint8_t>(v >> (8 - (bit & 7)));
			}
		}
		if (mode == 0)
			kg = static_cast<int>(r.get(3));
		else if (mode != 255)
		{
			kf = static_cast<int>(r.get(3));
			kd = static_cast<int>(r.get(3));
			cb = static_cast<int>(std::bit_width(mode));
			ib = static_cast<int>(std::bit_width(static_cast<unsigned>(n - 1)));
		}
		return !r.bad;
	}
	std::size_t rows() const { return mode == 255 ? 0 : n; }
	// Row a's G bytes into row[0..rlen); false: refuse the block. The reader and the row live in locals here (registers: a member
	// reader next to byte stores is reloaded after every store, ~240 fuel an entry), copied back once.
	bool next(std::size_t a)
	{
		RR q = r;
		std::uint8_t out[512];
		std::size_t k = 0;
		const int* A = bx.data() + 4 * a;
		const int* B0 = bx.data();
		bool ok = true;
		if (mode == 0)
		{
			const bool wa = wk[a] != 0;
			for (std::size_t b = a + 1; b < n; ++b)
			{
				if (!wa || !wk[b])
				{
					out[k++] = 255;
					continue;
				}
				const unsigned v = q.rice(kg);
				const int qv = v == 0 ? 255 : lbq(gap4(A, B0 + 4 * b)) + static_cast<int>(v) - 1;
				if (v != 0 && qv > 254)
				{
					ok = false;
					break;
				}
				out[k++] = static_cast<std::uint8_t>(qv);
			}
		}
		else if (mode != 255)
		{
			const unsigned cnt = wk[a] ? q.get(cb) : 0;
			if (cnt > mode)
				ok = false;
			int prev = 0;
			for (unsigned j = 0; ok && j < cnt; ++j)
			{
				const unsigned b = q.get(ib);
				if (b >= n || b == a)
				{
					ok = false;
					break;
				}
				const int qv = j == 0 ? lbq(gap4(A, B0 + 4 * b)) + static_cast<int>(q.rice(kf)) : prev + static_cast<int>(q.rice(kd));
				if (qv > 254)
				{
					ok = false;
					break;
				}
				out[k++] = static_cast<std::uint8_t>(b);
				out[k++] = static_cast<std::uint8_t>(qv);
				prev = qv;
			}
			for (unsigned j = cnt; ok && j < mode; ++j)
			{
				out[k++] = 255;
				out[k++] = 255;
			}
		}
		r = q;
		for (std::size_t t = 0; t < k; ++t)
			row[t] = out[t];
		rlen = k;
		return ok && !r.bad;
	}
};

const std::uint8_t* raw_bytes() { return reinterpret_cast<const std::uint8_t*>(cambc::draft_memory.data()); }
NOVA_INLINE void load_prism_memory_section(BR& r, std::uint8_t* b, std::size_t ng, std::size_t na)
{
	b[0] = PRISM_MAGIC;
	b[1] = PRISM_VERSION;
	b[2] = static_cast<std::uint8_t>(r.get(4));
	b[3] = static_cast<std::uint8_t>(r.get(8));
	const int wa = bw(static_cast<unsigned>(na)), wg = bw(static_cast<unsigned>(ng));
	for (int k = 0; k < 2; ++k)
	{
		const unsigned a = r.get(wa);
		b[4 + k] = a == na ? 255 : static_cast<std::uint8_t>(a);
	}
	for (int k = 0; k < 2; ++k)
		b[6 + k] = static_cast<std::uint8_t>(r.get(8));
	for (int k = 0; k < 4; ++k)
	{
		const unsigned g = r.get(wg);
		b[8 + k] = g == ng ? 255 : static_cast<std::uint8_t>(g);
	}
	int sum = 0;
	for (int i = 0; i < 23; ++i)
		sum += b[i];
	b[23] = static_cast<std::uint8_t>(sum & 255);
}
void load()
{
	if (loaded)
		return;
	loaded = 1;
	const std::size_t sz = cambc::draft_memory.size();
	if (sz < PK_HEAD)
		return;
	const std::uint8_t* m = raw_bytes();
	if (m[0] != MEM_MAGIC || m[1] != PK_VERSION)
		return;
	const std::size_t ng = m[2], na = m[3];
	BR r{ m + PK_HEAD, sz - PK_HEAD };
	img_n = r.get(11);
	img[0] = MEM_MAGIC;
	img[1] = MEM_VERSION;
	img[9] = static_cast<std::uint8_t>(r.get(5));
	img[10] = img[12] = static_cast<std::uint8_t>(ng);
	img[11] = img[13] = static_cast<std::uint8_t>(na);
	img[14] = static_cast<std::uint8_t>(r.get(8));
	img[15] = static_cast<std::uint8_t>(r.get(4));
	// Distances and access stay in the raw bytes: decode_memory reads them in place, at the cost of a plain read per group (bit-packing
	// them would cost 100 fuel a group on the setup turn and save about 2 bits a group).
	const std::size_t ats = PK_HEAD + 4; // The 28 bits above end inside byte PK_HEAD + 3.
	pk_dist = m + ats;
	pk_acc = pk_dist + 2 * (ng + na);
	pk_aacc = pk_acc + (ng + 3) / 4;
	r = BR{ pk_aacc + (na + 1) / 2, sz - static_cast<std::size_t>(pk_aacc + (na + 1) / 2 - m) };
	const std::size_t rest_at = static_cast<std::size_t>(pk_aacc + (na + 1) / 2 - m);
	if (r.get(1)) // Prism plan 736-747; 748-758 had no reader, 759 is its checksum over the bytes kept
		load_prism_memory_section(r, img.data() + 736, ng, na);
	if (r.get(1)) // Bytes 760-766.
	{
		img[760] = 0xB7;
		for (int i = 0; i < 6; ++i)
			img[761 + static_cast<std::size_t>(i)] = static_cast<std::uint8_t>(r.get(8));
	}
	if (r.get(1)) // strategy schedule 768-831 (no writer while no draft_plan is set)
		for (std::size_t i = 768; i < 832; ++i)
			img[i] = static_cast<std::uint8_t>(r.get(8));
	const int nx = static_cast<int>(r.get(4));
	for (int i = 0; i < nx; ++i)
	{
		const int id = static_cast<int>(r.get(4)), w = static_cast<int>(r.get(6));
		const std::uint32_t v = r.get(w);
		ex_r[static_cast<std::size_t>(id & 15)] = { v, static_cast<std::uint8_t>(id), static_cast<std::uint8_t>(w), 1 };
	}
	if (r.get(1)) // Whole bytes, read in place (bit-packing it saves about 12% but costs 20-30k fuel on the setup turn).
	{
		xt_len = r.get(10);
		if (xt_len == 0) // The compact block follows in the bit stream.
		{
			xc_has = true;
			xc_bit = rest_at * 8 + r.bits();
		}
		xt_at = rest_at + ((r.bits() + 7) >> 3);
		if (xt_at + xt_len > sz)
			xt_len = 0;
	}
	xt_E = 16 + 3 * (ng + na);
	loaded = 2;
}
} // namespace

View view()
{
	load();
	if (loaded == 2)
		return { reinterpret_cast<const std::byte*>(img.data()), img_n };
	return { cambc::draft_memory.data(), cambc::draft_memory.size() };
}

bool in_place(const std::uint8_t*& dist, const std::uint8_t*& acc, const std::uint8_t*& aacc)
{
	load();
	if (loaded != 2)
		return false;
	dist = pk_dist;
	acc = pk_acc;
	aacc = pk_aacc;
	return true;
}
const std::uint8_t* travel_block_base(std::size_t& size)
{
	load();
	if (loaded == 2)
	{
		size = xt_len ? xt_E + xt_len : 0; // no block: travel_decode's size check refuses it
		return raw_bytes() + xt_at - xt_E; // travel_decode reads from offset E
	}
	size = cambc::draft_memory.size();
	return raw_bytes();
}

// Header count at packed offset pk, whole-byte offset old; -1 with no readable memory.
static int memory_count(std::size_t pk, std::size_t old)
{
	const std::size_t sz = cambc::draft_memory.size();
	if (sz < PK_HEAD)
		return -1;
	const std::uint8_t* m = raw_bytes();
	if (m[0] != MEM_MAGIC)
		return -1;
	if (m[1] == PK_VERSION)
		return m[pk];
	return m[1] == MEM_VERSION && sz >= 16 ? m[old] : -1;
}
int total_groups() { return memory_count(2, 12); }
int total_altars() { return memory_count(3, 13); }

void extra_put(int id, std::uint32_t v, int bits)
{
	if (id < 0 || id > 15 || bits < 1 || bits > 32)
		return;
	auto& e = ex_w[static_cast<std::size_t>(id)];
	if (!e.set)
		++ex_wn;
	e = { v, static_cast<std::uint8_t>(id), static_cast<std::uint8_t>(bits), 1 };
}

std::uint32_t extra(int id, std::uint32_t fallback)
{
	if (id < 0 || id > 15)
		return fallback;
	load();
	const auto& e = ex_r[static_cast<std::size_t>(id)];
	return loaded == 2 && e.set ? e.v : fallback;
}

int extras_count() { return ex_wn; }

void extra_clear(int id)
{
	if (id < 0 || id > 15)
		return;
	auto& e = ex_w[static_cast<std::size_t>(id)];
	if (e.set)
	{
		e.set = 0;
		--ex_wn;
	}
}

void plan_memory_blob_set(const std::vector<std::uint8_t>& b)
{
	if (b.empty() || b.size() > 1000)
		return;
	dmf_blob_w = b;
	extra_put(DMF_BLOB_XID, static_cast<std::uint32_t>(b.size()), 10);
}

void plan_memory_blob_clear()
{
	dmf_blob_w.clear();
	extra_clear(DMF_BLOB_XID);
}

bool blob_pending() { return !dmf_blob_w.empty(); }

const std::uint8_t* blob(std::size_t& n)
{
	n = 0;
	load();
	if (loaded != 2)
		return nullptr;
	const auto& e = ex_r[static_cast<std::size_t>(DMF_BLOB_XID)];
	const std::size_t sz = cambc::draft_memory.size();
	if (!e.set || e.v == 0 || e.v + PK_HEAD > sz)
		return nullptr;
	n = e.v;
	return raw_bytes() + (sz - e.v);
}

long compact_encode_cost(bool reset)
{
	const long v = xc_cost;
	if (reset)
		xc_cost = 0;
	return v;
}

bool compact_block_present()
{
	load();
	return loaded == 2 && xc_has;
}

namespace {
XcDec xd;          // champions: the compact block's decoder
int xd_stage = 0;  // 0 not begun, 1 header .. routes read (xt_raw), 2 tables allocated, rows from xd_row
std::size_t xd_row = 0;
int xd_s1 = 0, xd_s2 = 0;
void compact_checksum_add(const std::uint8_t* b, std::size_t k)
{
	for (std::size_t i = 0; i < k; ++i)
	{
		xd_s1 += b[i];
		xd_s2 += xd_s1;
	}
	xd_s1 %= 255;
	xd_s2 %= 255;
}
long xd_rowbytes(std::size_t a) { return xd.mode == 0 ? static_cast<long>(xd.n - 1 - a) : 2L * static_cast<long>(xd.mode); }
long xd_rowcost(std::size_t a) { return 300L + 40L * xd_rowbytes(a); }
} // namespace
bool compact_head_expand(std::size_t n)
{
	if (xd_stage >= 1)
		return true;
	if (!compact_block_present() || pk_acc == nullptr)
		return false;
	if (!xd.begin(RR(raw_bytes(), cambc::draft_memory.size(), xc_bit), n, pk_acc))
		return false;
	xt_raw = xd.head; // The old block's header, S and routes: the route records read from here (XT bit 4).
	xt_scale = std::max(1, xd.scale);
	xt_mode = static_cast<int>(xd.mode);
	xt_nr = static_cast<int>(xd.nr);
	xt_ro = 6 + n;
	xt_go = xd.head.size();
	xd_s1 = xd_s2 = 0;
	compact_checksum_add(xd.head.data(), xd.head.size());
	xd_stage = 1;
	return true;
}

int compact_block_mode()
{
	if (!compact_block_present())
		return -1;
	RR r(raw_bytes(), cambc::draft_memory.size(), xc_bit + 12);
	return static_cast<int>(r.get(8));
}
int compact_block_build(long reserve, bool partial)
{
	const std::size_t n = static_cast<std::size_t>(xt_n);
	// All of it now when the bar holds (reserve + 6000 + 6 n^2 + 30 a byte of the block: the decode costs about that), so the tables
	// come no later than the whole-byte block's; else, in the background (partial), row by row in spare fuel.
	{
		long left = 0; // block bytes not decoded yet
		if (xd_stage < 1)
			left += 6L + static_cast<long>(n);
		const int md = xd_stage >= 1 ? static_cast<int>(xd.mode) : xt_mode;
		const std::size_t r0 = xd_stage < 2 ? 0 : xd_row;
		if (md == 0)
			left += static_cast<long>((n - r0) * (n - r0 - 1) / 2);
		else if (md > 0 && md <= 8)
			left += 2L * md * static_cast<long>(n - r0);
		const bool all = fuel() >= reserve + (xd_stage < 2 ? 6000L + 6L * static_cast<long>(n * n) : 0L) + 30L * left;
		if (!all && !partial)
			return 0;
	}
	if (xd_stage < 1)
	{
		if (fuel() < reserve + 3000L + 60L * static_cast<long>(n))
			return 0;
		if (!compact_head_expand(n))
			return -1;
	}
	if (xd_stage < 2)
	{
		if (fuel() < reserve + 6000L + 6L * static_cast<long>(n * n))
			return 0;
		auto dec = [](std::uint8_t v) { return decode_distance(v, xt_scale); };
		xt_s.assign(n, UNREACH);
		for (std::size_t a = 0; a < n; ++a)
			xt_s[a] = dec(xd.head[6 + a]);
		xt_d.assign(n * n, UNREACH);
		xt_der.assign(n * n, 0);
		for (std::size_t a = 0; a < n; ++a)
			xt_d[a * n + a] = 0;
		xd_row = 0;
		xd_stage = 2;
	}
	std::uint16_t* d = xt_d.data();
	const int sc = xt_scale;
	for (; xd_row < xd.rows(); ++xd_row)
	{
		const std::size_t a = xd_row;
		if (fuel() < reserve + xd_rowcost(a))
			return 0;
		if (!xd.next(a))
			return -1;
		compact_checksum_add(xd.row, xd.rlen);
		if (xd.mode == 0)
			for (std::size_t j = 0, b = a + 1; j < xd.rlen; ++j, ++b)
			{
				d[a * n + b] = d[b * n + a] = decode_distance(xd.row[j], sc);
			}
		else
		{
			xt_raw.insert(xt_raw.end(), xd.row, xd.row + xd.rlen); // travel_close_step reads the k-list ids here
			for (std::size_t j = 0; j + 1 < xd.rlen; j += 2)
			{
				const std::size_t b = xd.row[j];
				if (b < n && b != a)
				{
					const std::uint16_t v = decode_distance(xd.row[j + 1], sc);
					if (v < d[a * n + b])
						d[a * n + b] = d[b * n + a] = v;
				}
			}
		}
	}
	const unsigned c1 = xd.r.get(8), c2 = xd.r.get(8);
	if (xd.r.bad || c1 != static_cast<unsigned>(xd_s1) || c2 != static_cast<unsigned>(xd_s2))
		return -1;
	xd_stage = 3;
	xd.bx.clear();
	xd.head.clear();
	return 1;
}
// The Prism plan at b. False: a slot out of range.
NOVA_INLINE bool pack_prism_plan(BW& w, const std::uint8_t* b, std::size_t ng, std::size_t na)
{
	if (b[2] > 15)
		return false;
	w.put(b[2], 4);
	w.put(b[3], 8);
	const int wa = bw(static_cast<unsigned>(na)), wg = bw(static_cast<unsigned>(ng));
	for (int k = 0; k < 2; ++k)
	{
		if (b[4 + k] != 255 && b[4 + k] >= na)
			return false;
		w.put(b[4 + k] == 255 ? static_cast<std::uint32_t>(na) : b[4 + k], wa);
	}
	for (int k = 0; k < 2; ++k)
		w.put(b[6 + k], 8);
	for (int k = 0; k < 4; ++k)
	{
		if (b[8 + k] != 255 && b[8 + k] >= ng)
			return false;
		w.put(b[8 + k] == 255 ? static_cast<std::uint32_t>(ng) : b[8 + k], wg);
	}
	return true;
}
bool pack(const std::vector<std::uint8_t>& in, std::vector<std::uint8_t>& out)
{
	const std::size_t sz = in.size();
	if (sz < 16 || sz > 1024 || in[0] != MEM_MAGIC || in[1] != MEM_VERSION)
		return false;
	const std::size_t ng = in[10], na = in[11];
	const std::size_t E = 16 + 3 * (ng + na);
	if (in[12] != ng || in[13] != na || E > XT_END || sz < E || in[9] > 31 || in[15] > 15)
		return false;
	out.assign(1024 + 8, 0);
	out[0] = MEM_MAGIC;
	out[1] = PK_VERSION;
	out[2] = static_cast<std::uint8_t>(ng);
	out[3] = static_cast<std::uint8_t>(na);
	BW w{ out.data() + PK_HEAD, 1024 - PK_HEAD };
	w.put(static_cast<std::uint32_t>(sz), 11);
	w.put(in[9], 5);
	w.put(in[14], 8);
	w.put(in[15], 4);
	// In place for decode_memory: whole-byte distances, then 2-bit group access, then 4-bit altar gated + access.
	std::uint8_t* d0 = out.data() + PK_HEAD + 4;
	std::uint8_t* ac = d0 + 2 * (ng + na);
	std::uint8_t* aac = ac + (ng + 3) / 4;
	std::size_t o = 16;
	for (std::size_t i = 0; i < ng; ++i, o += 3)
	{
		if (in[o + 2] > 3)
			return false;
		d0[2 * i] = in[o];
		d0[2 * i + 1] = in[o + 1];
		ac[i >> 2] |= static_cast<std::uint8_t>(in[o + 2] << ((i & 3) * 2));
	}
	for (std::size_t i = 0; i < na; ++i, o += 3)
	{
		if (in[o + 2] > 15)
			return false;
		d0[2 * (ng + i)] = in[o];
		d0[2 * (ng + i) + 1] = in[o + 1];
		aac[i >> 1] |= static_cast<std::uint8_t>(in[o + 2] << ((i & 1) * 4));
	}
	const std::size_t rest_at = static_cast<std::size_t>(aac + (na + 1) / 2 - out.data());
	w = BW{ out.data() + rest_at, 1024 - rest_at };
	const bool has_prism = sz >= 760 && in[736] == PRISM_MAGIC && in[737] == PRISM_VERSION;
	w.put(has_prism ? 1 : 0, 1);
	if (has_prism && !pack_prism_plan(w, in.data() + 736, ng, na))
		return false;
	const bool has_om = sz >= 768 && in[760] == 0xB7;
	w.put(has_om ? 1 : 0, 1);
	if (has_om)
		for (std::size_t i = 761; i < 767; ++i)
			w.put(in[i], 8);
	bool has_st = false;
	if (sz >= 832)
		for (std::size_t i = 768; i < 832; ++i)
			has_st = has_st || in[i] != 0;
	w.put(has_st ? 1 : 0, 1);
	if (has_st)
		for (std::size_t i = 768; i < 832; ++i)
			w.put(in[i], 8);
	w.put(static_cast<std::uint32_t>(ex_wn), 4);
	for (const auto& e : ex_w)
		if (e.set)
		{
			w.put(e.id, 4);
			w.put(e.w, 6);
			w.put(e.w >= 32 ? e.v : (e.v & ((1u << e.w) - 1u)), e.w);
		}
	// The same checks as travel_decode; a block it would refuse is not stored (it reads as no block either way).
	bool has_xt = false;
	const std::size_t n = ng;
	int mode = 0, nr = 0;
	std::size_t go = 0, glen = 0;
	if (xt_group_count_ok(n) && E + 8 + n <= XT_END && sz >= E + 8 + n && in[E] == XT_MAGIC && in[E + 1] == XT_VERSION && in[E + 2] == n)
	{
		mode = in[E + 4];
		nr = in[E + 5];
		has_xt = mode == 0 || mode == 255 || mode <= 8;
		std::size_t p = E + 6 + n;
		for (int i = 0; i < nr && has_xt; ++i)
		{
			if (p + 4 > sz || p + 4 > XT_END || in[p + 3] == 0 || in[p + 3] > XT_MAXRL || in[p] >= n)
				has_xt = false;
			else
				p += xt_rbytes(in[p + 3]);
		}
		go = p;
		glen = mode == 0 ? n * (n - 1) / 2 : (mode == 255 ? 0 : n * static_cast<std::size_t>(mode) * 2);
		if (has_xt && (go + glen + 2 > sz || go + glen + 2 > XT_END))
			has_xt = false;
	}
	w.put(has_xt ? 1 : 0, 1);
	std::size_t xt_len = 0;
	if (has_xt)
	{
		xt_len = go + glen + 2 - E;
		w.put(static_cast<std::uint32_t>(xt_len), 10);
	}
	if (w.over)
		return false;
	std::size_t end = rest_at + ((w.bits + 7) >> 3);
	if (has_xt)
	{
		if (end + xt_len > 1024)
			return false;
		std::memcpy(out.data() + end, in.data() + E, xt_len);
		end += xt_len;
	}
	if (!dmf_blob_w.empty() && ex_w[static_cast<std::size_t>(DMF_BLOB_XID)].set) // The tail blob, last; too big: pack fails, pack_and_submit_draft_memory retries without it.
	{
		if (end + dmf_blob_w.size() > 1024)
			return false;
		// The engine's buffer is always 1024 bytes and a shorter submit leaves the old bytes past it: the blob goes at the very end, the
		// gap is zeroed, and the whole 1024 bytes are submitted.
		std::memcpy(out.data() + (1024 - dmf_blob_w.size()), dmf_blob_w.data(), dmf_blob_w.size());
		end = 1024;
	}
	out.resize(end);
	return true;
}
// The tail blob, a bit stream: 4 bits version (1); 1 bit DM3: 3 bits slots, per slot 8 gi, 6 nr, 10 vmin, nr x bw(w*h - 1) root tile
// indices (y * w + x); 1 bit DM2: 7 bits bw, 7 bits bh, bw x bh bits (3x3 blocks, row-major).
namespace {
constexpr int DMF_VER = 1;
struct Dm3Slot
{
	int gi = -1, vmin = 0, nr = 0;
	std::array<std::uint16_t, 63> roots{};
};
std::array<Dm3Slot, 7> dmf_d3{};
int dmf_d3n = 0, dmf_st = 0, dmf_d2w = 0, dmf_d2h = 0;
std::vector<std::uint8_t> dmf_d2; // one byte per block (decoded once)
int dmf_tw() { return bw(static_cast<unsigned>(std::max(1, G.w * G.h - 1))); }
void read_tail_blob()
{
	if (dmf_st)
		return;
	dmf_st = 1;
	std::size_t n = 0;
	const std::uint8_t* b = blob(n);
	if (!b || n == 0)
		return;
	BR r{ b, n };
	if (static_cast<int>(r.get(4)) != DMF_VER)
		return;
	if (r.get(1))
	{
		const int ns = static_cast<int>(r.get(3)), tw = dmf_tw();
		for (int k = 0; k < ns && k < 7; ++k)
		{
			Dm3Slot& d = dmf_d3[static_cast<std::size_t>(k)];
			d.gi = static_cast<int>(r.get(8));
			d.nr = static_cast<int>(r.get(6));
			d.vmin = static_cast<int>(r.get(10));
			for (int j = 0; j < d.nr; ++j)
				d.roots[static_cast<std::size_t>(j)] = static_cast<std::uint16_t>(r.get(tw));
		}
		dmf_d3n = std::min(ns, 7);
	}
	if (r.get(1))
	{
		dmf_d2w = static_cast<int>(r.get(7));
		dmf_d2h = static_cast<int>(r.get(7));
		if (dmf_d2w * 3 >= G.w && dmf_d2h * 3 >= G.h && dmf_d2w * dmf_d2h > 0)
		{
			dmf_d2.assign(static_cast<std::size_t>(dmf_d2w * dmf_d2h), 0);
			for (auto& x : dmf_d2)
				x = static_cast<std::uint8_t>(r.get(1));
		}
		else
			dmf_d2w = dmf_d2h = 0;
	}
}

} // namespace

bool launch_record(int gi, int& vmin, const std::uint16_t*& roots, int& nr)
{
	read_tail_blob();
	for (int k = 0; k < dmf_d3n; ++k)
	{
		const Dm3Slot& d = dmf_d3[static_cast<std::size_t>(k)];
		if (d.gi == gi)
		{
			vmin = d.vmin;
			nr = d.nr;
			roots = d.roots.data();
			return true;
		}
	}
	return false;
}


// Draft (DMF bits 1/2): build the blob once, on the big first draft turn, and hand it to pack. Returns the fuel it spent.
long build_tail_blob(long reserve)
{
	static bool done = false;
	if (done || !M.done() || fuel() < reserve + 1000000)
		return 0;
	done = true;
	const long f0 = fuel();
	std::vector<std::uint8_t> buf(1024 + 8, 0);
	BW w{ buf.data(), 1000 };
	w.put(DMF_VER, 4);
	bool any = false;
	std::vector<Dm3Rec> recs;
	econ::draft_launch_scan(recs, reserve);
	const int tw = dmf_tw();
	int ns = 0;
	for (const auto& r : recs)
		ns += (r.gi >= 0 && r.gi <= 255 && r.roots.size() <= 63 && r.vmin >= 0 && r.vmin < 1024) ? 1 : 0;
	ns = std::min(ns, 7);
	w.put(ns > 0 ? 1 : 0, 1);
	if (ns > 0)
	{
		any = true;
		w.put(static_cast<std::uint32_t>(ns), 3);
		int k = 0;
		for (const auto& r : recs)
			if (k < ns && r.gi >= 0 && r.gi <= 255 && r.roots.size() <= 63 && r.vmin >= 0 && r.vmin < 1024)
			{
				++k;
				w.put(static_cast<std::uint32_t>(r.gi), 8);
				w.put(static_cast<std::uint32_t>(r.roots.size()), 6);
				w.put(static_cast<std::uint32_t>(r.vmin), 10);
				for (const std::uint16_t t : r.roots)
					w.put(t, tw);
			}
	}
	std::vector<std::uint8_t> d2;
	int bw2 = 0, bh2 = 0;
	w.put(0, 1);
	if (any && !w.over)
	{
		buf.resize((w.bits + 7) >> 3);
		plan_memory_blob_set(buf);
	}
	return f0 - FXR_FUEL();
}

} // namespace dmem

bool xt_dense() { return xt_dn; }
bool travel_table_build(long reserve)
{
	if (xt_dn)
		return true;
	if (!xt_ok)
		return false;
	const std::size_t n = static_cast<std::size_t>(xt_n);
	if (xt_cx) // The tables straight from the compact block (background: row by row over turns; foreground: all or nothing).
	{
		const int st = dmem::compact_block_build(reserve, reserve < 60000);
		if (st < 0)
		{
			xt_cx = false;
			xt_ok = false;
			xt_raw.clear();
			xt_d.clear();
			xt_s.clear();
			xt_der.clear();
			return false;
		}
		if (st == 0)
			return false;
		xt_cx = false;
		xt_dn = true;
		return true;
	}
	if (fuel() < reserve + 6000L + 6L * static_cast<long>(n * n) + 30L * static_cast<long>(xt_raw.size())) // measured 2-28k
		return false;
	const std::uint8_t* m = xt_raw.data();
	const std::size_t sz = xt_raw.size();
	auto dec = [](std::uint8_t v) { return decode_distance(v, xt_scale); };
	xt_s.assign(n, UNREACH);
	for (std::size_t a = 0; a < n && 6 + a < sz; ++a)
		xt_s[a] = dec(m[6 + a]);
	xt_d.assign(n * n, UNREACH);
	xt_der.assign(n * n, 0);
	std::uint16_t* d = xt_d.data();
	for (std::size_t a = 0; a < n; ++a)
		d[a * n + a] = 0;
	std::size_t o = xt_go;
	if (xt_mode == 0)
	{
		for (std::size_t a = 0; a < n; ++a)
			for (std::size_t b = a + 1; b < n && o < sz; ++b, ++o)
				d[a * n + b] = d[b * n + a] = dec(m[o]);
	}
	else if (xt_mode != 255)
	{
		const std::size_t k = static_cast<std::size_t>(xt_mode);
		for (std::size_t a = 0; a < n; ++a)
			for (std::size_t j = 0; j < k && o + 1 < sz; ++j, o += 2)
			{
				const std::size_t b = m[o];
				if (b < n && b != a)
				{
					const std::uint16_t v = dec(m[o + 1]);
					if (v < d[a * n + b])
						d[a * n + b] = d[b * n + a] = v;
				}
			}
	}
	xt_dn = true;
	return true;
}

// k-list blocks store only each group's k nearest: the missing pairs are filled with walks through stored neighbours (upper bounds),
// a few rows per call in spare fuel, XT_PASSES passes over every row (each pass extends the paths).
namespace {
int xt_cl_row = 0, xt_cl_pass = 0;
bool xt_cl_done = false;
constexpr int XT_PASSES = 3;
} // namespace
void travel_close_step_slow(long reserve);
// The first early-out test is inline at the call site (saves a call and frame a turn), the rest out of line.
__attribute__((always_inline)) void travel_close_step(long reserve)
{
	if (xt_cl_done || !xt_dn)
		return;
	travel_close_step_slow(reserve);
}
__attribute__((noinline)) void travel_close_step_slow(long reserve)
{
	if (xt_mode == 0 || xt_mode == 255)
	{
		xt_cl_done = true;
		return;
	}
	const std::size_t n = static_cast<std::size_t>(xt_n), k = static_cast<std::size_t>(xt_mode);
	const long row_cost = 2000L + 16L * static_cast<long>(k * n);
	std::uint16_t* d = xt_d.data();
	const std::uint8_t* m = xt_raw.data();
	const std::size_t sz = xt_raw.size();
	while (fuel() > reserve + row_cost)
	{
		const std::size_t a = static_cast<std::size_t>(xt_cl_row);
		std::uint16_t* ra = d + a * n;
		for (std::size_t j = 0; j < k; ++j)
		{
			const std::size_t o = xt_go + (a * k + j) * 2;
			if (o + 1 >= sz)
				break;
			const std::size_t c = m[o];
			if (c >= n || c == a || ra[c] == UNREACH)
				continue;
			const int dac = ra[c];
			const std::uint16_t* rc = d + c * n;
			for (std::size_t b = 0; b < n; ++b)
				if (rc[b] != UNREACH && dac + rc[b] < ra[b])
				{
					const int v = std::min(60000, dac + static_cast<int>(rc[b]));
					ra[b] = static_cast<std::uint16_t>(v);
					d[b * n + a] = static_cast<std::uint16_t>(v);
					xt_der[a * n + b] = xt_der[b * n + a] = 1;
				}
		}
		if (++xt_cl_row >= xt_n)
		{
			xt_cl_row = 0;
			if (++xt_cl_pass >= XT_PASSES)
			{
				xt_cl_done = true;
				return;
			}
		}
	}
}

const std::uint16_t* travel_table(int* n, const std::uint16_t** spawn, const std::uint8_t** derived)
{
	if (!xt_dn || xt_d.size() != static_cast<std::size_t>(xt_n) * static_cast<std::size_t>(xt_n) || xt_s.size() != static_cast<std::size_t>(xt_n) ||
		xt_der.size() != xt_d.size())
		return nullptr;
	*n = xt_n;
	*spawn = xt_s.data();
	*derived = xt_der.data();
	return xt_d.data();
}

namespace {
void decode_memory()
{
	const auto mem = dmem::view();
	if (mem.size() < 16)
		return;
	auto byte = [&](std::size_t i) { return std::to_integer<std::uint8_t>(mem[i]); };
	if (mem.size() > OP_MEM)
		OP_PLAY = dmem::extra(OP_XID, byte(OP_MEM)) != 0 ? 1 : 0;
	else // BB8P: the extra does not depend on the memory length
		OP_PLAY = dmem::extra(OP_XID, 0) != 0 ? 1 : 0;
	if (byte(0) != MEM_MAGIC || byte(1) != MEM_VERSION)
		return;
	strat::set_mode(byte(15)); // The draft's choice.
	if (mem.size() >= strat::BLOCK_END)
	{
		std::uint8_t sb[strat::BLOCK_END - strat::BLOCK_AT];
		for (std::size_t i = 0; i < sizeof sb; ++i)
			sb[i] = byte(strat::BLOCK_AT + i);
		strat::set_block(sb, sizeof sb); // The draft's schedule, if it wrote one.
	}
	P.flags = byte(3);
	const int scale = std::max<int>(1, byte(9));
	const std::size_t ng = byte(10), na = byte(11);
	if (byte(12) != std::min<std::size_t>(static_cast<std::size_t>(M.ng), 255) || byte(13) != std::min<std::size_t>(static_cast<std::size_t>(M.na), 255))
		return;
	if (ng != static_cast<std::size_t>(M.ng) || na != static_cast<std::size_t>(M.na) || 16 + 3 * (ng + na) > mem.size())
		return;
	std::size_t o = 16;
	const std::uint8_t* pkd = nullptr;
	const std::uint8_t* pka = nullptr;
	const std::uint8_t* pkb = nullptr;
	const bool pk_ip = dmem::in_place(pkd, pka, pkb); // The same values, read from the stream.
	for (std::size_t i = 0; i < ng; ++i, o += 3)
	{
		auto& g = M.groups[i];
		g.d_home = decode_distance(pk_ip ? pkd[2 * i] : byte(o), scale);
		g.d_enemy = decode_distance(pk_ip ? pkd[2 * i + 1] : byte(o + 1), scale);
		g.access = pk_ip ? static_cast<std::uint8_t>((pka[i >> 2] >> ((i & 3) * 2)) & 3) : byte(o + 2);
		if (g.d_home != UNREACH && g.d_enemy != UNREACH)
			g.contest = static_cast<float>(g.d_home) / std::max(1.0f, static_cast<float>(g.d_home + g.d_enemy));
		else
			g.contest = g.d_home != UNREACH ? 0.0f : 1.0f;
	}
	for (std::size_t i = 0; i < na; ++i, o += 3)
	{
		auto& a = M.altars[i];
		const std::uint8_t ab = pk_ip ? static_cast<std::uint8_t>((pkb[i >> 1] >> ((i & 1) * 4)) & 15) : byte(o + 2);
		a.d_home = decode_distance(pk_ip ? pkd[2 * (ng + i)] : byte(o), scale);
		a.d_enemy = decode_distance(pk_ip ? pkd[2 * (ng + i) + 1] : byte(o + 1), scale);
		a.gated = (ab & 1) != 0;
		a.access = static_cast<std::uint8_t>((ab >> 1) & 3);
	}
	if (byte(14) > 0)
		P.s2s = (byte(14) - 1) * scale;
	M.mark_distances_known();
	P.from_memory = true;
	std::size_t xsz = 0;
	const std::uint8_t* xm = dmem::travel_block_base(xsz);
	travel_decode(xm, xsz, ng, na);
}
} // namespace
namespace prism {
// Decoding of the Prism block the draft wrote (write_plan in draft_prism.cc).
void read_plan()
{
	PL = Plan{};
	// Without a plan: clusters and gold from the map itself (no distances needed), the default cap, no safe altar.
	{
		int clu = 0, gold = 0;
		for (const auto& g : M.groups)
		{
			gold += g.gold;
			if (g.n_clu > 0)
				clu += g.gems;
		}
		PL.flags = static_cast<std::uint8_t>(1 | (clu >= 30 ? 2 : 0) | (gold >= PC_GOLD_TREASURE ? 4 : 0));
	}
	const auto mem = dmem::view();
	if (mem.size() < PLAN_END || !P.from_memory || 16 + 3 * (static_cast<std::size_t>(M.ng) + static_cast<std::size_t>(M.na)) > PLAN_AT)
		return;
	std::array<std::uint8_t, N> b{};
	for (std::size_t i = 0; i < N; ++i)
		b[i] = std::to_integer<std::uint8_t>(mem[PLAN_AT + i]);
	if (b[0] != MAGIC || b[1] != VERSION)
		return;
	int sum = 0;
	for (std::size_t i = 0; i + 1 < N; ++i)
		sum += b[i];
	if ((sum & 255) != b[N - 1])
		return;
	PL.ok = true;
	PL.flags = b[2];
	PL.cap = 4 * static_cast<int>(b[3]);
	for (int k = 0; k < 2; ++k)
	{
		const int ai = b[4 + k];
		PL.altar[k] = (ai != 255 && ai < M.na) ? ai : -1;
		PL.altar_t[k] = b[6 + k];
	}
	for (int k = 0; k < 4; ++k)
	{
		const int gi = b[8 + k];
		PL.groups[k] = (gi != 255 && gi < M.ng) ? gi : -1;
	}
}
} // namespace prism
} // namespace nova
