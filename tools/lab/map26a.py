"""Pure-Python decoder for CAMBC 2026a .map26a files (also usable on the map embedded in a
.repl26a replay, which starts at byte 14).

Format (verified against the engine's own parser, MapBuilder_* in engine v1_0_0 wasm, for all
21 pool maps and the 17 pre-patch ladder maps; see validate_decoder.py):

  0..5    magic b"w62pam"
  6..71   theme block (ground/bush colours, flowers flag; cosmetic)
  72      u8  symmetry: 0 HORIZONTAL (x mirrored), 1 VERTICAL (y mirrored), 2 ROTATIONAL180
  73      u8  champions per team (3..5)
  74      u16 width, 76 u16 height (little endian)
  78      u16 N = number of cosmetic ground layers stored after the bush-cluster layer
  80..    4 chunk-RLE bitboards in order: bush, wall, hole, altar.
          A chunk-RLE bitboard is a sequence of u16 run lengths alternating 0-runs and 1-runs
          (starting with a 0-run) over CW*CH*64 bits, CW = ceil(W/8), CH = ceil(H/8); bit i lies
          in 8x8 chunk i // 64 (chunk index cy*CW + cx) at bit (y % 8) * 8 + x % 8.
          These layers cover the WHOLE map (both halves).
  then    value-RLE layer over W*H tiles in row-major order: (u16 value, u16 count) pairs
          (bush cluster ids; cosmetic, we recompute clusters ourselves)
  then    N chunk-RLE bitboards (cosmetic ground decoration)
  then    team A spawn area: u16 minX, minY, maxX, maxY (max exclusive); team B is its mirror
  then    u8 number of stored camps, then per camp u8 type, u8 x, u8 y. (encode() writes the same layout back;
          `python3 map26a.py --roundtrip FILE...` checks decode + encode reproduce each file byte for byte.)
          Camp types: 0 wolf, 1 elk, 2 gem cluster, 3 gold cluster, 4 monolith, 5 golem.
          Only one camp of each mirror pair is stored; the physical camps are every stored camp
          plus its mirror image (a camp on the symmetry axis maps onto itself).
"""
import io
import json
import struct
import sys
import zipfile

CAMP_TYPES = {0: "wolf", 1: "elk", 2: "gem_cluster", 3: "gold_cluster", 4: "monolith", 5: "golem"}
SYMMETRY = {0: "HORIZONTAL", 1: "VERTICAL", 2: "ROTATIONAL180"}


class _Reader:
    def __init__(self, b, off):
        self.b, self.o = b, off

    def u8(self):
        v = self.b[self.o]
        self.o += 1
        return v

    def u16(self):
        if self.o + 2 > len(self.b):
            raise ValueError("truncated")
        v = self.b[self.o] | (self.b[self.o + 1] << 8)
        self.o += 2
        return v


def _chunk_bitboard(r, W, H):
    CW, CH = (W + 7) // 8, (H + 7) // 8
    total = CW * CH * 64
    tiles = set()
    pos, val = 0, 0
    while pos < total:
        n = r.u16()
        if val:
            for i in range(pos, pos + n):
                ci, bi = divmod(i, 64)
                cy, cx = divmod(ci, CW)
                x, y = cx * 8 + bi % 8, cy * 8 + bi // 8
                if x < W and y < H:
                    tiles.add((x, y))
        pos += n
        val ^= 1
    if pos != total:
        raise ValueError(f"bitboard overrun {pos} != {total}")
    return tiles


def _value_rle(r, W, H):
    total, pos, grid = W * H, 0, {}
    while pos < total:
        v, n = r.u16(), r.u16()
        if v:
            for i in range(pos, pos + n):
                y, x = divmod(i, W)
                grid[(x, y)] = v
        pos += n
    if pos != total:
        raise ValueError("value rle overrun")
    return grid


def mirror(sym, W, H, x, y):
    if sym == 0:
        return W - 1 - x, y
    if sym == 1:
        return x, H - 1 - y
    return W - 1 - x, H - 1 - y


def decode(b, offset=0):
    if b[offset:offset + 6] != b"w62pam":
        raise ValueError("bad magic")
    r = _Reader(b, offset + 72)
    sym, cpt, W, H, N = r.u8(), r.u8(), r.u16(), r.u16(), r.u16()
    bush, wall, hole, altar = (_chunk_bitboard(r, W, H) for _ in range(4))
    clusters = _value_rle(r, W, H)
    ground = [_chunk_bitboard(r, W, H) for _ in range(N)]
    x0, y0, x1, y1 = r.u16(), r.u16(), r.u16(), r.u16()
    n = r.u8()
    stored = []
    for _ in range(n):
        t, x, y = r.u8(), r.u8(), r.u8()
        stored.append((t, x, y))
    spawnA = {(x, y) for x in range(x0, x1) for y in range(y0, y1)}
    spawnB = {mirror(sym, W, H, x, y) for (x, y) in spawnA}
    camps = {}
    for t, x, y in stored:
        camps[(x, y)] = t
        camps[mirror(sym, W, H, x, y)] = t
    return dict(length=r.o - offset, symmetry=sym, champs_per_team=cpt, W=W, H=H, n_ground_layers=N,
                bush=bush, wall=wall, hole=hole, altar=altar, bush_cluster_ids=clusters, ground=ground,
                spawnA_rect=(x0, y0, x1, y1), spawnA=spawnA, spawnB=spawnB, stored_camps=stored,
                camps=camps, theme=bytes(b[offset + 6:offset + 72]))


def _enc_bitboard(tiles, W, H):
    CW, CH = (W + 7) // 8, (H + 7) // 8
    bits = bytearray(CW * CH * 64)
    for x, y in tiles:
        bits[((y // 8) * CW + x // 8) * 64 + (y % 8) * 8 + x % 8] = 1
    runs, cur, n = [], 0, 0
    for v in bits:
        if v == cur:
            n += 1
        else:
            runs.append(n)
            cur, n = v, 1
    runs.append(n)
    out = []
    for n in runs:  # runs above 65535 are split by zero-length runs of the other value
        while n > 65535:
            out += [65535, 0]
            n -= 65535
        out.append(n)
    return struct.pack("<%dH" % len(out), *out)


def encode(d):
    """Inverse of decode(): the .map26a bytes of a decoded map (layers, cosmetic layers, theme and camp order as
    decoded; edit the sets, then encode). encode(decode(f)) == f byte for byte on every map tested."""
    W, H = d["W"], d["H"]
    b = bytearray(b"w62pam") + d["theme"]
    b += struct.pack("<BBHHH", d["symmetry"], d["champs_per_team"], W, H, len(d["ground"]))
    for k in ("bush", "wall", "hole", "altar"):
        b += _enc_bitboard(d[k], W, H)
    runs, prev, n = [], None, 0
    for i in range(W * H):
        y, x = divmod(i, W)
        v = d["bush_cluster_ids"].get((x, y), 0)
        if v == prev and n < 65535:
            n += 1
        else:
            if prev is not None:
                runs.append((prev, n))
            prev, n = v, 1
    runs.append((prev, n))
    b += b"".join(struct.pack("<HH", v, c) for v, c in runs)
    for g in d["ground"]:
        b += _enc_bitboard(g, W, H)
    b += struct.pack("<4HB", *d["spawnA_rect"], len(d["stored_camps"]))
    for t, x, y in d["stored_camps"]:
        b += struct.pack("<BBB", t, x, y)
    return bytes(b)


def read_bytes(path):
    """File bytes; a run-batch replay bundle (zip with replay.repl26a) is unpacked."""
    b = open(path, "rb").read()
    if b[:2] == b"PK":
        with zipfile.ZipFile(io.BytesIO(b)) as z:
            b = z.read("replay.repl26a")
    return b


def load(path, offset=None):
    b = read_bytes(path)
    if offset is None:
        offset = 14 if b[:6] == b"a62per" else 0
    return decode(b, offset)


def roundtrip(path):
    """True when re-encoding the decoded map reproduces the file's map bytes exactly."""
    b = read_bytes(path)
    off = 14 if b[:6] == b"a62per" else 0
    d = decode(b, off)
    return encode(d) == b[off:off + d["length"]] and (off > 0 or len(b) == d["length"])


if __name__ == "__main__":
    if sys.argv[1] == "--roundtrip":
        bad = [f for f in sys.argv[2:] if not roundtrip(f)]
        print(f"{len(sys.argv) - 2 - len(bad)} of {len(sys.argv) - 2} maps re-encode byte for byte" +
              "".join(f"\n  differs: {f}" for f in bad))
        sys.exit(1 if bad else 0)
    d = load(sys.argv[1], int(sys.argv[2]) if len(sys.argv) > 2 else None)
    print(json.dumps(dict(length=d["length"], symmetry=SYMMETRY[d["symmetry"]], champs_per_team=d["champs_per_team"],
                          W=d["W"], H=d["H"], spawnA_rect=d["spawnA_rect"], n_bush=len(d["bush"]),
                          n_wall=len(d["wall"]), n_hole=len(d["hole"]), n_altar=len(d["altar"]),
                          n_stored_camps=len(d["stored_camps"]), n_camps=len(d["camps"]))))
