#!/usr/bin/env python3
"""Per-phase drawevent totals of a gpwork.py run (0013 barrier classification).

    python tools/g2/fbreadsum.py LOG WORK

LOG: the live netlog; WORK: gpwork.py's output (marker lines "HH:MM:SS name line N").
Each libsweetca DRAWPROF report covers 100 GL flushes (about 100 frames); a report belongs
to the phase whose line range holds its "drawprof v1" header.
"""
import re
import sys

KEYS = ('barrier-needed', 'barrier-skipped', 'feedback-fetch', 'feedback-selfread', 'feedback-both',
        'flush-barrier', 'flush-resource-dependency', 'flush-context', 'flush-frame',
        'batch-draws', 'sysbarrier-retained', 'fbread-gmem', 'fbread-sys-bins')


def main():
    log, work = sys.argv[1], sys.argv[2]
    marks = {}
    for ln in open(work, errors='replace'):
        m = re.match(r'\d\d:\d\d:\d\d (.+) line (\d+)$', ln.strip())
        if m:
            marks[m.group(1)] = int(m.group(2))
    phases = [('home', marks.get('home start'), marks.get('home end')),
              ('cc', marks.get('cc start'), marks.get('cc end'))]
    lines = open(log, 'rb').read().decode(errors='replace').split('\n')
    for name, a, b in phases:
        if a is None or b is None:
            print(f'{name}: markers missing')
            continue
        reports = 0
        tot = {}
        cur = None
        for ln in lines[a:b]:
            if 'drawprof v1: enabled 1' in ln:
                reports += 1
                cur = True
            m = re.search(r'drawevent: (\S+) (\d+)', ln)
            if m and cur:
                tot[m.group(1)] = tot.get(m.group(1), 0) + int(m.group(2))
        flushes = 100 * reports
        print(f'{name}: {reports} reports ({flushes} flushes)')
        for k in KEYS:
            if k in tot:
                print(f'  {k:28s} {tot[k]:8d}  {tot[k] / max(flushes, 1):7.2f} per flush')
        need = tot.get('barrier-needed', 0)
        if need:
            f, s, both = (tot.get(k, 0) for k in ('feedback-fetch', 'feedback-selfread', 'feedback-both'))
            print(f'  of needed barriers: fetch only {100 * f / need:.1f} %, other self-read only {100 * s / need:.1f} %, '
                  f'both {100 * both / need:.1f} %')
    for ln in lines:
        if 'self-read (not a fetch)' in ln:
            print(ln.strip()[:240])


if __name__ == '__main__':
    main()
