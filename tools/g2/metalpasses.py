#!/usr/bin/env python3
"""Rank bounded M5 GPU batch intervals and retain encoded-pass associations.

These are pipeline-draining RB_DONE_TS diagnostics, not production timings.
Attachment footprints are logical size proxies, never measured RAM traffic.
    python tools/g2/metalpasses.py CAPTURE.csv [--json OUT]
"""
import argparse
import collections
import csv
import io
import json
from pathlib import Path
import re


def union_ticks(intervals):
    total = 0
    end = 0
    for start, stop in sorted(intervals):
        total += max(0, stop - max(start, end))
        end = max(end, stop)
    return total


def analyze(text):
    header, _, body = text.partition('\n')
    values = dict((k, int(v)) for k, v in re.findall(r'(commits|dropped|pending|pid)=(\d+)', header))
    if set(values) != {'commits', 'dropped', 'pending', 'pid'}:
        raise ValueError('missing capture completeness metadata')
    if values['dropped'] or values['pending']:
        raise ValueError('incomplete capture: dropped rows or pending GPU stamps')
    rows = list(csv.DictReader(io.StringIO(body)))
    descriptors, links, batches = {}, collections.defaultdict(set), {}
    shaders = collections.defaultdict(collections.Counter)
    sampled = collections.defaultdict(set)
    begun, ended = [], []
    work = collections.Counter()
    for row in rows:
        cb, p = int(row['cb']), int(row['pass'])
        v = [int(row[f'v{k}']) for k in range(20)]
        event = row['event']
        if event == 'begin':
            begun.append(cb)
        elif event == 'end':
            ended.append(cb)
        elif event == 'pass':
            if (cb, p) in descriptors:
                raise ValueError('duplicate pass identity')
            descriptors[cb, p] = v
        elif event == 'link':
            links[v[0], v[1]].add((cb, p))
        elif event == 'batch':
            key = (v[0], v[1])
            if key in batches:
                raise ValueError('duplicate context/batch identity')
            if not 0 < v[15] <= v[16] or v[16] - v[15] > 19200000:
                raise ValueError('invalid GPU timestamps')
            batches[key] = v
        elif event == 'work':
            work[v[0]] += 1
        elif event == 'shader':
            label = b''.join(x.to_bytes(8, 'little') for x in v[:12]).split(b'\0', 1)[0].decode('utf-8', 'replace')
            shaders[cb, p][label] += v[12]
            sampled[cb, p].add(tuple(v[13:20]))
        elif event == 'access':
            # M6 logical lifetime evidence has its own conservative analyzer.
            # It is not a timestamp and must never add GPU time to a pass.
            pass
        else:
            raise ValueError('unknown event: ' + event)
    if begun != ended or begun != list(range(1, values['commits'] + 1)):
        raise ValueError('incomplete command buffers')
    groups = {}
    missing_links = 0
    shared_batches = 0
    for key, v in batches.items():
        # A driver batch can implement several encoded passes. Never divide its
        # elapsed time between them or assign it to the last active replay pass.
        owners = links.get(key, set())
        if any(p not in descriptors for p in owners):
            raise ValueError('draw references unknown pass')
        if not owners and v[9]:
            missing_links += 1
        shared_batches += len(owners) > 1
        signature = tuple(v[2:9] + v[10:15])
        group = groups.setdefault(signature, dict(width=v[2], height=v[3], samples=v[4],
            colors=v[5], pipe_format=v[6], depth_format=v[7], mode=v[8],
            cleared=v[10], restore=v[11], resolve=v[12], feedback=v[13], pre=v[14],
            count=0, draws=0, gpu_ms=0., max_ms=0., encoded_passes=set(), intervals=[]))
        ms = (v[16] - v[15]) / 19200
        group['count'] += 1
        group['draws'] += v[9]
        group['gpu_ms'] += ms
        group['max_ms'] = max(group['max_ms'], ms)
        group['encoded_passes'].update(owners)
        group['intervals'].append((v[15], v[16]))
    for group in groups.values():
        group['union_ms'] = union_ticks(group.pop('intervals')) / 19200
        group['encoded_passes'] = sorted(group['encoded_passes'])
        group['target_pixels'] = group['width'] * group['height'] * group['count']
        labels = collections.Counter()
        textures = set()
        for owner in map(tuple, group['encoded_passes']):
            labels.update(shaders[owner])
            textures.update(sampled[owner])
        group['linked_shader_draws'] = dict(labels.most_common())
        group['sampled_first_two'] = sorted(textures)
    intervals = [(v[15], v[16]) for v in batches.values()]
    pass_classes = collections.Counter(tuple(v) for v in descriptors.values())
    return dict(**values, batches=len(batches), encoded_passes=len(descriptors),
        gpu_sum_ms=sum((b-a)/19200 for a, b in intervals),
        gpu_union_ms=union_ticks(intervals)/19200, shared_batches=shared_batches,
        draw_batches_without_links=missing_links,
        links_without_timed_batch=len(set(links)-set(batches)),
        work_kinds=dict(work),
        pass_classes=[dict(count=n, descriptor=list(v)) for v, n in pass_classes.most_common()],
        ranked=sorted(groups.values(), key=lambda g: g['gpu_ms'], reverse=True),
        limitation='GPU execution envelopes include pipeline drains; sums can overlap. No per-pass hardware byte counters. Draw links may span encoded passes; clear/copy-only batches can be unlinked.')


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('capture', type=Path)
    ap.add_argument('--json', type=Path)
    a = ap.parse_args()
    result = analyze(a.capture.read_text())
    if a.json:
        a.json.write_text(json.dumps(result, indent=2) + '\n')
    print(f"PID {result['pid']}: {result['commits']} CB, {result['encoded_passes']} encoded passes, "
          f"{result['batches']} batches, GPU sum {result['gpu_sum_ms']:.2f} ms, union {result['gpu_union_ms']:.2f} ms")
    for g in result['ranked'][:15]:
        print(f"{g['gpu_ms']:9.2f} ms {g['count']:5} batches {g['width']}x{g['height']} "
              f"fmt={g['pipe_format']} samples={g['samples']} colors={g['colors']} mode={g['mode']} "
              f"feedback={g['feedback']} clear={g['cleared']:x} restore={g['restore']:x} resolve={g['resolve']:x}")
    print(result['limitation'])


if __name__ == '__main__':
    main()
