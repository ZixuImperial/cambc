# Team shared memory: unused code space (v650, 9 Nov)

Read from live v650 (bots/nova_b10121_bb14): comms.cc, econ_comms_protocol.cc (ecp), brain_claims.cc. The team has 8 bytes = 64 bits (GameRules.md:405-413), readable and writable by every body (dead ones too), seen at once by later bodies in the same round (interactions.md). Purpose: new messages (a crew request, a danger warning) can ride in unused code values with no layout change before a repack.

Notation: ng = camp groups, na = altars (4 in the examples), n = bodies (CLAIM_SLOTS 6), c6 = ceil(W/6) x ceil(H/6) fight cells (49 on 40x40, 121 on 64x64).

## Which layout runs

- **A (normal):** draft memory valid and n x bit_width(8ng+63) + w + 1 <= 64. In A the claim encoding is always slim 4: the full-claim test and the slim test are the same expression (comms.cc:213, :229) and `sl` is the constant 4 (:220), so slim 2 and the full-code path (comms.cc:567-582) are dead.
- **B:** n x bit_width(8ng+63) + w + 1 > 64 (comms.cc:209-213); in practice 6 bodies with ng >= 25. With 5 bodies, A holds up to ng ~120.
- **C:** draft memory invalid, or ng > 126 (comms.cc:189).
- There is no event field in A or B: `L.ebits = L.ek = 0` (comms.cc:205-206); every event goes through the channel (`L.ev2`, comms.cc:204, :641-659).

## Fields

| Field | Width (bits) | Defined codes | Unused codes | Typical (5 bodies unless noted) | Impossible values | Notes |
|---|---|---|---|---|---|---|
| A claim slot (x n) | cbw = bit_width(2ng+12) (comms.cc:221) | 2ng+13: 0 idle/dead, 1 fight, 2..ng+1 heading to g, ng+2..2ng+1 engaged on g, 2ng+2 retreat, 2ng+3..2ng+12 coming (comms.cc:42-59) | 2^cbw - (2ng+13) per slot | ng 12: 6 bits, 27 spare; ng 20: 6, 11; ng 30: 7, 55; ng 40: 7, 35 | Coming: 48 states (ETA x octant x HP) fold into 10, so ETA 0 never decodes (comms.cc:57, :73); idle buckets 0-3 all -> 0; the heading bucket is dropped. **ng = 7, 39, 103: the retreat code never occurs** (bug below) | Slots >= n forced to 0 (comms.cc:237, :287) |
| B claim slot (x n) | bit_width(2ng) (comms.cc:199) | 2ng+1: 0, g, ng+g (comms.cc:629) | 2^w - (2ng+1) | ng 30, 6 bodies: 6 bits, 3 spare; ng 40, 6 bodies: 7 bits, 47 spare | - | No fight, retreat or coming states (ckind never 4 or 5) |
| C claim byte (x 6) | 8 | 2 x min(ng,127) + 1 | 256 - that | - | 0x80 alone; groups >= 127 write 0 (comms.cc:587) | Rare layout |
| C event, bytes 6-7 | 16 | subject+1 x type (3 bits) x stamp (5 bits) | - | - | - | Shares its bits with the channel (hazard 1) |
| Channel entry (x k) | ew = bits(D) + 1 (ecp:33-36); top bit = parity | D = 1 + 8ng (camp state) + 16ng (respawn bucket) + 3 x c6 (fight cell rally/commit/stop) + ng (crew call) + 4(ng+na) (news) (ecp:53-59) | 2^(ew-1) - D in the tail, plus in-range holes (next column) | ng 12: ew 10 / 11 (40x40 / 64x64), tail spare 0 / 296; ng 20: 11 / 11, 280 / 64; ng 30: 12, 1014 / 798; ng 40: 12, 724 / 508 | Respawn buckets 0 and 1 never sent (rem >= 2: ecp:497-508; T2_LO econ_comms_fields.cc:69): **2ng dead codes**; TAKEN / CLEARED on altar subjects (intel.cc:420, :427): **2na dead codes**; code 0 with parity 1; qk round codes dead (qk_rbase always 0, econ_state.cc:43, ecp:68) | Parity = post round & 1, so the reader knows t or t-1 (ecp:179); both parities legal for every code. Camp states 0-7 all used. Event types 6, 7 (sighting, contest) dropped in A and B (ecp:665). k is sized with 4 codes per fight cell (comms.cc:424) but ew uses 3 |
| Middle free bits | 64 - n x cbw - k x ew (B: n x bit_width(2ng)) | - | all | A: 12-18 bits; B ng 30, 6 bodies: 4; B ng 40, 6 bodies: 10 | - | Free for a new spare_alloc after camp_news_init |

The ng 12 / 40x40 / na 4 case has exactly 512 defined channel codes, so its tail spare is 0; each extra altar adds 4 codes.

**How k is chosen** (ecp:38-61): k = min(2, (spare_bits - slim_saved) / ew_old), with ew_old = bits(D + c6) + 1; a channel exists only if k x ew <= 32. In A this is (64 - n x cb2) / ew_old, so the bits the slim fold freed stay unused. Results: 5 bodies, ng <= 20 -> k = 2; 6 bodies in A -> k = 1; 5 bodies, ng >= 30 -> k = 1; B, ng 30, 6 bodies -> k = 2.

## Where new messages fit, no layout change

- **Channel in-range holes (every layout, every map):** 2ng dead respawn-bucket codes (rc + 16g + {0, 1}) and 2na dead altar codes. A per-group crew request fits on bucket 0 and a per-group danger warning on bucket 1, with no change to ew. This is the only spare that exists on every map, including the ng 12 / 40x40 case whose tail spare is 0.
- **Claim slot (A only):** a per-group crew request needs ng spare per slot: fits at ng 12 (27) and ng 30 (55), not at ng 20 (11) or ng 40 (35). A fixed-size message ("danger, octant 0-7" = 8 codes, or a 1-code "need crew") fits every A case. In B only 3 spare at ng 30.
- **Channel tail:** a per-cell danger warning needs c6 codes (49 / 121): fits everywhere except ng 12 / 40x40 (0) and ng 20 / 64x64 (64 < 121).
- **Middle bits:** a new spare_alloc after camp_news_init gives 12-18 bits in A, only 4 in B ng 30 with 6 bodies.

## Decode hazards (add a decode branch before each default)

1. **Layout C channel / event clash: NOT A BUG (b1774):** layout C returns at comms.cc:189 before L.top = 64, so top stays 48 (comms.cc:29) and the channel sits below the event bytes. Original (wrong) note: in C, spare_low = n x 8 (comms.cc:441), so the channel (ecp:61) sits on bits 48-63, the event bytes 6-7: channel posts read as events on the C path (comms.cc:286) and raw event writes (comms.cc:683) corrupt channel entries.
2. **Unknown A slot value:** falls into the else at comms.cc:73 and decodes as "coming" (ETA 1, octant 0, hurt): mates read it as coming to a fight (econ_travel_gates.cc:222 busy; brain_help_fight.cc:81 counts it in c1) and its group claim is lost.
3. **Unknown B value above 2ng:** decodes as engaged on group c - ng - 1 >= ng (comms.cc:369): an out-of-range group index for any reader.
4. **Channel codes past the news range:** the else at ecp:225 turns them into ENEMY / TAKEN news with subject >= ns; legacy_in only rejects subjects >= 255 (comms.cc:427).
5. **Reusing the dead bucket codes:** today's reader would apply them as a respawn due now or in 1 round (ecp:212); a reader branch is needed before that line.
6. **News writer overflow (latent):** subjects bounded by t2_rcrew, not ns (ecp:652); an overflowing code is cut by the entry mask (ecp:681-683) and wraps into a camp code.

## Bugs found by this audit

- **Retreat never sent at ng = 7, 39, 103** (comms.cc:51): the guard `2ng+50 < 2^bit_width(2ng+49)` was written for slim 2's width; under slim 4 the retreat code 2ng+2 always fits, but the guard fails when 2ng+49 is one less than a power of two, so a retreat goes out as "fight" and retreating() (combat_team.cc:639) is never true for those mates.
- ~~Layout C channel / event clash~~ (withdrawn: top stays 48 in C). Retreat guard: 3/1,198 fresh maps (b1774).

Not checked: per-map na counts; whether build_plan always runs before the first comms::read; how often layout C occurs.
