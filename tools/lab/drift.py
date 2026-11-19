"""drift.py - the 2-group drift check of ADR 0006's base reuse (owner ruling, 28 Oct).

After a KEEP, the next release may reuse that KEEP's NEW half as its BASE half instead of playing a fresh one, if the
half finished under 2 h before the submit and a drift check passes: 2 of its groups are played again on the same live
build, and at least 70% of the games must be byte-identical (same replay) to the originals. Bots are deterministic, so
a game that differs means the opponent resubmitted (or the platform changed) since the half was played.

  drift.py compare OLD_SET NEW_SET [--json]
      Pairs the games of two set dirs (or one drift dir) by (opponent, map, seat) and compares their replay bytes
      (x_ID/replay.repl26a). Prints identical / paired; a game of NEW_SET with no partner counts as different.
  drift.py run PFX TAG [--family lean:L1] [--dry-run]
      Plays one group of PFX_T and one of PFX_P again (the first line of each tier's layout file, the same opponent and
      maps) as set TAG (diag.sh, so /data/USER/plat/TAG and TAG.log), then compares them with PFX's games and writes
      /data/USER/plat/TAG.json {pfx, tag, identical, games, share, pass, at}. Creates 2 unranked groups: only the build
      session (autoship.py) runs it, never while another set plays. --dry-run prints the groups and plays nothing.
Exit 0 pass, 1 fail (share < 70%), 2 usage or error."""
import hashlib, json, os, subprocess, sys, time

REPO = '/homes/USER/cambc'
PLAT = os.environ.get('RELQUEUE_PLAT') or '/data/USER/plat'
LAYOUT = '/data/USER/mf'
SHARE_MIN = 0.70


def games(d):
    """{(opp, map, side): replay sha256 or None} of set dir d (matches.txt: id map side result opp)."""
    out = {}
    for l in open(os.path.join(d, 'matches.txt')):
        p = l.split()
        if len(p) < 5:
            continue
        f = os.path.join(d, 'x_%s' % p[0], 'replay.repl26a')
        out[(p[4], p[1], p[2])] = hashlib.sha256(open(f, 'rb').read()).hexdigest() if os.path.exists(f) else None
    return out


def compare(old_dirs, new_dir):
    """(identical, games, lines): NEW's games against their partners in any of old_dirs."""
    old = {}
    for d in old_dirs:
        old.update(games(d))
    new = games(new_dir)
    same, L = 0, []
    for k in sorted(new):
        o, n = old.get(k), new[k]
        ok = o is not None and n is not None and o == n
        same += ok
        L.append('  %-24s %-26s %s  %s' % (k[0], k[1], k[2], 'identical' if ok else 'no partner' if k not in old
                                            else 'replay missing' if None in (o, n) else 'DIFFERENT'))
    return same, len(new), L


def layout(family):
    if not family.startswith('lean:'):
        sys.exit('drift.py: only lean layouts (lean:NAME) are supported, not %s' % family)
    nm = family[5:]
    return ['%s/lean_%s_%s.txt' % (LAYOUT, nm, t) for t in ('top', 'near')]


def run(pfx, tag, family, dry):
    for s in ('_T', '_P'):
        if not os.path.exists('%s/%s%s/matches.txt' % (PLAT, pfx, s)):
            sys.exit('drift.py: %s%s has no matches.txt (not finished)' % (pfx, s))
    if os.path.exists('%s/%s' % (PLAT, tag)) or os.path.exists('%s/%s.log' % (PLAT, tag)):
        sys.exit('drift.py: %s/%s exists: a drift tag is played once' % (PLAT, tag))
    lines = []
    for f in layout(family):
        first = [l for l in open(f) if l.strip() and not l.startswith('#')][:1]
        if not first:
            sys.exit('drift.py: empty layout file %s' % f)
        lines += first
    print('drift %s -> %s: replays\n  %s' % (pfx, tag, '  '.join(lines)))
    if dry:
        return 0
    gf = '%s/%s.groups' % (PLAT, tag)
    open(gf, 'w').write(''.join(lines))
    d = '%s/%s' % (PLAT, tag)
    with open('%s/%s.log' % (PLAT, tag), 'w') as log:
        rc = subprocess.run(['sh', 'tools/lab/diag.sh', gf, tag, d, '--zips'], cwd=REPO, stdout=log, stderr=subprocess.STDOUT).returncode
    if rc or not os.path.exists(d + '/matches.txt'):
        sys.exit('drift.py: diag.sh exit %s, no matches.txt in %s' % (rc, d))
    same, n, L = compare(['%s/%s_T' % (PLAT, pfx), '%s/%s_P' % (PLAT, pfx)], d)
    share = same / n if n else 0.0
    ok = n >= 8 and share >= SHARE_MIN
    res = dict(pfx=pfx, tag=tag, identical=same, games=n, share=round(share, 3), share_min=SHARE_MIN, groups=[l.split()[1] for l in lines],
               **{'pass': ok}, at=time.strftime('%Y-%m-%d %H:%M:%S UTC', time.gmtime()))
    tmp = '%s/%s.json.tmp%d' % (PLAT, tag, os.getpid())
    json.dump(res, open(tmp, 'w'), indent=1)
    os.replace(tmp, '%s/%s.json' % (PLAT, tag))
    print('\n'.join(L))
    print('DRIFT %s: %d of %d games byte-identical (%.0f%%, need %.0f%% of at least 8) -> %s' % (
        pfx, same, n, 100 * share, 100 * SHARE_MIN, 'PASS' if ok else 'FAIL'))
    return 0 if ok else 1


def main():
    a = sys.argv[1:]
    if len(a) >= 3 and a[0] == 'compare':
        same, n, L = compare([a[1]], a[2])
        if '--json' in a:
            print(json.dumps(dict(identical=same, games=n, share=round(same / n, 3) if n else 0.0)))
        else:
            print('\n'.join(L))
            print('%d of %d games byte-identical (%.0f%%)' % (same, n, 100 * same / n if n else 0))
        return 0
    if len(a) >= 3 and a[0] == 'run':
        fam = a[a.index('--family') + 1] if '--family' in a else 'lean:L1'
        return run(a[1], a[2], fam, '--dry-run' in a)
    print(__doc__)
    return 2


if __name__ == '__main__':
    sys.exit(main())
