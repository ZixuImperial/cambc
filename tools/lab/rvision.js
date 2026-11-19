#!/usr/bin/env node
// rvision.js: engine-exact VISION and TEAM MEMORY from a replay (Tool builder 2, 4 Nov; owner + analysts: "make the website
// visualiser readable for Claude", vision of each champion, first-seen, hit from fog, what each body knew).
// usage: node tools/lab/rvision.js REPLAY.repl26a OUT.json.gz [--tiles R0 R1]
//   --tiles (4 Nov, rmap.py): also each living champion's full vision tiles at every turn start in rounds R0..R1:
//   tiles: [[round, acting body, {body: hex}], ...], hex = W*H bits row-major (bit y*W+x), most significant first per 4 tiles.
// Replays the game through the real engine (the decoder rdec.js's engine loader) and, at the start of every champion turn,
// asks the engine's visualiser for EACH champion's own vision (dead: its ward only) (Game_Visualiser_GetVisionBuffer with the perspective
// {team, champion}: the same fog the website shows for one champion, ward included). Writes:
//   turns: [[round, acting body, alive mask, mask_0, ..., mask_{n-1}], ...]  mask_i = bitmask of ENEMY bodies body i sees (a dead body: through its ward only; 7 Nov, 23,228 dead views on 4 games)
//   mem:   [[round, team0 hex, team1 hex], ...]                    the 8-byte team memory at the first turn of each round
//   bodies, teamOf, owned (bodies whose view the replay allows: every body here, both teams), steps, seconds
// Perspective facts (probed on engine 2.0.0): {2, NONE} = observer (no mask); {team, body} for a body of that team; no team-wide
// view exists (team vision = the union of its champions' views; vision is per champion by the rules). Bitboard: one u64 per
// 8x8 chunk, chunk (y>>3)*stride + (x>>3), bit (y&7)*8 + (x&7) (importmap.md; checked: every champion sees its own tile).
'use strict';
const fs = require('fs');
const zlib = require('zlib');
const R = require('/homes/zw4424/condor-work/tools/rdec.js');
const NONE = 4294967295;
const ENGINE_DIR = '/homes/zw4424/condor-work/engine'; // 4 Nov: engines tried newest first (replay v3 = engine 3.0.0), as rdec.js does
const TS = { size: 42840, nCh: 172, ch: 196, chStride: 420 }; // engine 2.0.0 timeline snapshot (rdec.js TS2)

function main() {
  const [inp, out] = process.argv.slice(2);
  const ti = process.argv.indexOf('--tiles');
  const tr0 = ti > 0 ? +process.argv[ti + 1] : -1, tr1 = ti > 0 ? +process.argv[ti + 2] : -2;
  const tiles = [];
  if (!inp || !out) { console.error('usage: node rvision.js REPLAY.repl26a OUT.json.gz'); process.exit(2); }
  const t0 = Date.now();
  const bytes = fs.readFileSync(inp);
  const vkey = f => f.replace(/\D+/g, ' ').trim().split(' ').map(Number);
  const engines = fs.readdirSync(ENGINE_DIR).filter(f => /^v\d+_\d+_\d+\.wasm$/.test(f))
    .sort((a, b) => { const x = vkey(a), y = vkey(b); for (let i = 0; i < 3; i++) if (x[i] !== y[i]) return y[i] - x[i]; return 0; });
  let E = null, ex = null, engineUsed = null;
  for (const f of engines) {
    const e = R.loadEngine(`${ENGINE_DIR}/${f}`), p = e.malloc(bytes.length);
    new Uint8Array(e.ex.memory.buffer, p, bytes.length).set(bytes);
    if (e.ex.Game_FromReplayFileBytes(p, bytes.length, e.out) === 0) { E = e; ex = e.ex; engineUsed = f; break; }
  }
  if (!E) throw new Error(`no engine in ${ENGINE_DIR} opens this replay`);
  const g = E.u64(E.out);
  E.check(ex.Game_Visualiser_Timeline_GetMain(g, E.out), 'Timeline_GetMain');
  const tl = E.u64(E.out);
  E.check(ex.Game_Visualiser_Timeline_Seek(g, tl, 0, 0), 'Timeline_Seek');
  if (ex.Game_Visualiser_TimelineSnapshotSize() !== TS.size) throw new Error(`unsupported snapshot layout in ${engineUsed} (rvision.js knows 2.0.0's; update TS)`);
  const meta = E.malloc(64);
  E.check(ex.Game_GetBitboardMetadata(g, meta), 'bitboard metadata');
  const W = E.i32(meta), H = E.i32(meta + 4), stride = E.i32(meta + 16);
  const ts = E.malloc(TS.size), buf = E.malloc(64), persp = E.malloc(16), mb = E.malloc(16);
  const turns = [], mem = [];
  let teamOf = null, n = 0, turnKey = -1, memRound = -1, steps = 0;
  const xs = new Int32Array(64), ys = new Int32Array(64), alive = new Uint8Array(64);
  const seesTile = (ptr, x, y) => (E.u8(ptr + ((y >> 3) * stride + (x >> 3)) * 8 + (y & 7)) >> (x & 7)) & 1;
  for (;;) {
    E.check(ex.Game_Visualiser_ReadTimelineState(g, ts), 'ReadTimelineState');
    E.sync();
    steps++;
    const round = E.u32(ts + 8), tIdx = E.u32(ts + 12), awaitIn = E.u32(ts + 20), phase = E.u32(ts + 24), outcome = E.u32(ts + 28);
    const cur = E.u32(ts + 60);
    const nCh = E.u32(ts + TS.nCh);
    if (nCh > 0 && !teamOf) { // bodies 0..n-1, team by perspective probe: a body accepts {its team, body}
      n = nCh; teamOf = [];
      for (let k = 0; k < n; k++) {
        const id = E.u32(ts + TS.ch + k * TS.chStride + 4);
        let t = -1;
        for (const tt of [0, 1]) { E.setU32(persp, tt); E.setU32(persp + 4, id); if (ex.Game_Visualiser_GetVisionBuffer(g, persp, buf) === 0) { t = tt; break; } }
        teamOf[id] = t;
      }
    }
    if (phase === 10 && awaitIn === 1 && cur !== NONE && teamOf) {
      const key = round * 64 + tIdx;
      if (key !== turnKey) {
        turnKey = key;
        for (let k = 0; k < nCh; k++) {
          const b = ts + TS.ch + k * TS.chStride, id = E.u32(b + 4);
          xs[id] = E.i32(b + 16); ys[id] = E.i32(b + 20); alive[id] = E.u32(b + 32);
        }
        let am = 0;
        for (let i = 0; i < n; i++) if (alive[i]) am |= 1 << i;
        const row = [round, cur, am];
        for (let i = 0; i < n; i++) {
          let m = 0;
          if (teamOf[i] >= 0) { // dead bodies too: a dead owner keeps its ward's vision (20_interactions Q33)
            E.setU32(persp, teamOf[i]); E.setU32(persp + 4, i);
            if (ex.Game_Visualiser_GetVisionBuffer(g, persp, buf) === 0) {
              const ptr = E.u32(buf);
              for (let j = 0; j < n; j++) if (alive[j] && teamOf[j] !== teamOf[i] && xs[j] >= 0 && xs[j] < W && ys[j] >= 0 && ys[j] < H && seesTile(ptr, xs[j], ys[j])) m |= 1 << j;
            }
          }
          row.push(m);
        }
        turns.push(row);
        if (round >= tr0 && round <= tr1) {
          const tb = {};
          for (let i = 0; i < n; i++) {
            if (!alive[i] || teamOf[i] < 0) continue;
            E.setU32(persp, teamOf[i]); E.setU32(persp + 4, i);
            if (ex.Game_Visualiser_GetVisionBuffer(g, persp, buf) !== 0) continue;
            const ptr = E.u32(buf);
            let hex = '', nib = 0, k = 0;
            for (let y = 0; y < H; y++) for (let x = 0; x < W; x++) {
              nib = (nib << 1) | seesTile(ptr, x, y); k++;
              if (k === 4) { hex += nib.toString(16); nib = 0; k = 0; }
            }
            if (k) hex += (nib << (4 - k)).toString(16);
            tb[i] = hex;
          }
          tiles.push([round, cur, tb]);
        }
        if (round !== memRound) {
          memRound = round;
          const hex = [0, 1].map(t => (ex.Game_Visualiser_GetSharedMemory(g, t, 0, mb, 8) === 0
            ? Array.from(new Uint8Array(ex.memory.buffer, mb, 8)).map(v => v.toString(16).padStart(2, '0')).join('') : ''));
          mem.push([round, hex[0], hex[1]]);
        }
      }
    }
    if (outcome) break;
    if (ex.Game_Visualiser_Timeline_ReplayNext(g, 1) !== 0) break;
  }
  const res = { schema: 3, replay: inp, W, H, n, teamOf, owned: teamOf.map((t, i) => (t >= 0 ? i : -1)).filter(i => i >= 0), turns, mem, tiles, engine: engineUsed, steps,
    seconds: (Date.now() - t0) / 1000 };
  fs.writeFileSync(out + '.tmp', zlib.gzipSync(JSON.stringify(res)));
  fs.renameSync(out + '.tmp', out);
  console.log(`rvision: ${turns.length} turn starts, ${mem.length} rounds, ${n} bodies (views for ${res.owned.length}) in ${res.seconds.toFixed(1)} s -> ${out}`);
}

main();
