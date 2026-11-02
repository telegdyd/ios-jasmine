#!/usr/bin/env python3
"""Audit bounded M6 logical texture accesses; never certify dead stores.

Replay order is submission order, not completion. Scissors bound potential writes,
not geometry coverage. Resource addresses identify logical Gallium resources only;
driver renaming, physical aliases and out-of-replay observers remain unknown.
"""
import argparse
import collections
import csv
import io
import json
from pathlib import Path

from metalpasses import analyze

KINDS = dict(enumerate(('attachment', 'clear', 'draw', 'sample', 'image',
    'copy_src', 'copy_dst', 'resolve_src', 'resolve_dst', 'cpu_read',
    'cpu_write', 'external', 'mipmap', 'destroy'), 1))
UNKNOWN = 0xffffffff


def audit(text):
    timing = analyze(text)  # Reject loss, pending stamps and incomplete CBs first.
    resources, ordered = {}, []
    active_cb = None
    for sequence, row in enumerate(csv.DictReader(io.StringIO(text.partition('\n')[2]))):
        if row['event'] == 'begin':
            if active_cb is not None:
                raise ValueError('nested replay scope')
            active_cb = int(row['cb'])
        elif row['event'] == 'end':
            if active_cb != int(row['cb']):
                raise ValueError('unmatched replay scope')
            active_cb = None
        if row['event'] != 'access':
            continue
        if active_cb != int(row['cb']):
            raise ValueError('access outside its replay scope')
        v = [int(row[f'v{k}']) for k in range(20)]
        kind, rid, logical, surface, level, layer = v[:6]
        if kind not in KINDS or not rid or not logical:
            raise ValueError('invalid M6 access identity or kind')
        identity = (logical, surface, *v[14:20])
        resource = resources.setdefault(rid, dict(identity=identity, events=[],
            logical_resource=logical, surface=surface))
        if resource['identity'] != identity:
            raise ValueError('texture lifetime identity changed')
        event = dict(sequence=sequence, cb=int(row['cb']), pass_id=int(row['pass']),
            kind=KINDS[kind], resource=rid, level=level, layer=layer,
            origin=v[6:9], extent=v[9:12], mask=v[12], detail=v[13])
        if kind == 1:
            event.update(slot=v[12], load=v[13] & UNKNOWN, store=v[13] >> 32)
        if kind == 3 and v[12] != UNKNOWN:
            event.update(write_mask=v[12] & 15, fetch=bool(v[12] & 16),
                         shader_outputs=v[13], coverage='scissor upper bound only')
        elif kind == 3:
            event.update(write_mask=None, fetch=None, shader_outputs=None,
                         coverage='depth/stencil access conservatively unknown')
        resource['events'].append(event)
        ordered.append(event)
    if not ordered:
        raise ValueError('capture has no M6 access evidence')
    # A shared IOSurface is a definite alias/observer hazard. Equal logical resource
    # addresses with distinct lifetime IDs can also be pool reuse, so never collapse
    # those into a single live allocation without lifetime boundary evidence.
    surfaces, logicals = collections.defaultdict(set), collections.defaultdict(set)
    for rid, r in resources.items():
        logicals[r['logical_resource']].add(rid)
        if r['surface']:
            surfaces[r['surface']].add(rid)
    transitions = []
    for rid, r in resources.items():
        attachments = [i for i, e in enumerate(r['events']) if e['kind'] == 'attachment']
        for a, b in zip(attachments, attachments[1:]):
            before, after = r['events'][a], r['events'][b]
            between = r['events'][a+1:b]
            transitions.append(dict(resource=rid, source=before['sequence'],
                next=after['sequence'], next_load=after['load'],
                same_cb=before['cb'] == after['cb'],
                intervening=dict(collections.Counter(e['kind'] for e in between)),
                fetching_draws=sum(e['kind'] == 'draw' and e['fetch'] for e in between),
                removable=False))
    return dict(commits=timing['commits'], accesses=len(ordered), resources=len(resources),
        operations=dict(collections.Counter(e['kind'] for e in ordered)),
        surface_aliases={str(k): sorted(v) for k, v in surfaces.items() if len(v)>1},
        logical_reuse_or_aliases={str(k): sorted(v) for k, v in logicals.items() if len(v)>1},
        transitions=transitions, graph=ordered, proven_removals=0,
        limitations=['CPU and external observers outside inline replay are unknown',
            'capture boundary is not end of resource lifetime',
            'physical backing aliases and driver renaming are unknown',
            'sample/image mip and layer ranges are unknown',
            'draw bounds do not prove full pixel replacement',
            'requested attachment store actions are not per-resource batch store events'])


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('capture', type=Path)
    p.add_argument('--json', type=Path)
    a = p.parse_args()
    result = audit(a.capture.read_text())
    if a.json:
        a.json.write_text(json.dumps(result, indent=2) + '\n')
    print(json.dumps({k: v for k, v in result.items() if k not in ('graph', 'transitions')}, indent=2))


if __name__ == '__main__':
    main()
