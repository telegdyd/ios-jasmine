"""Summarize BGMTL_SUBMIT_PROFILE CSVs; operation counts are not frame timings."""
import argparse
from collections import Counter, defaultdict
import csv
import json
from pathlib import Path
import re


def analyze(text):
    lines = text.splitlines()
    header = re.fullmatch(r'# commits=(\d+) dropped=0;.*', lines[0]) if lines else None
    if not header:
        raise ValueError('missing header or dropped inventory events')
    rows = list(csv.DictReader(lines[1:]))
    commits = defaultdict(list)
    events = Counter()
    for row in rows:
        row = dict(row)
        for key in ('cb', *'abcdefgh'):
            row[key] = int(row[key])
        commits[row['cb']].append(row)
        events[row['event']] += 1
    for cb, records in commits.items():
        if (records[0]['event'] != 'begin' or records[-1]['event'] != 'end' or
                sum(r['event'] == 'begin' for r in records) != 1 or
                sum(r['event'] == 'end' for r in records) != 1):
            raise ValueError(f'incomplete command buffer {cb}')
    if list(commits) != list(range(1, int(header[1]) + 1)):
        raise ValueError('missing or reordered command buffers')
    enqueues = [r for rs in commits.values() for r in rs if r['event'] == 'enqueue']
    kernels = [r for rs in commits.values() for r in rs if r['event'] == 'kernel']
    reasons = Counter()
    for r in enqueues:
        reasons['fence_fd' if r['f'] else 'shared' if r['g'] else
                'policy_limit' if not r['h'] else 'deferred'] += 1
    results = [r for rs in commits.values() for r in rs if r['event'] == 'kernel-result']
    if any(r['c'] for r in results):
        raise ValueError('kernel submission failure')
    if len(results) != len(kernels):
        raise ValueError('missing kernel results')
    # Counterfactual on the SAME finalized batches, not a second UI workload.
    # Compositor inline replay drains at CB end. Ignore candidate capacity drains
    # and apply the original per-submit heuristic; retain all explicit drains.
    # This predicts call counts only: timing, resource hazards, and rendering are
    # covered by device validation, not established by this replay.
    legacy_calls = pending = deferred_cmds = 0
    capacity_drain = False
    for rs in commits.values():
        for r in rs:
            event = r['event']
            if event == 'group-capacity':
                capacity_drain = True
            elif event == 'enqueue':
                capacity_drain = False
                pending += 1
                if r['f'] or r['g'] or r['c'] > 30 or deferred_cmds > 128:
                    legacy_calls += 1
                    pending = deferred_cmds = 0
                else:
                    deferred_cmds += r['d']
            elif event in ('drain', 'end'):
                if event == 'end' or not capacity_drain:
                    legacy_calls += bool(pending)
                    pending = deferred_cmds = 0
                capacity_drain = False
    return dict(command_buffers=len(commits), events=dict(events), enqueue_reasons=dict(reasons),
                merged_submits=sum(r['b'] for r in kernels), kernel_calls=len(kernels),
                legacy_policy_projected_calls=legacy_calls,
                max_kernel_bos=max((r['c'] for r in kernels), default=0),
                max_kernel_commands=max((r['d'] for r in kernels), default=0),
                per_cb=[dict(cb=cb, passes=rs[0]['a'],
                             flushes=sum(r['event'] == 'flush' for r in rs),
                             enqueues=sum(r['event'] == 'enqueue' for r in rs),
                             kernel_calls=sum(r['event'] == 'kernel' for r in rs))
                        for cb, rs in commits.items()])


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('csv', type=Path)
    p.add_argument('--json', type=Path)
    args = p.parse_args()
    report = analyze(args.csv.read_text())
    formatted = json.dumps(report, indent=2)
    if args.json:
        args.json.write_text(formatted + '\n')
    else:
        print(formatted)


if __name__ == '__main__':
    main()
