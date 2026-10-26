"""Summarize SWEETCA_BATCH_TRACE logs. CPU graph only; never a speed benchmark.

python tools/g2/batchgraph.py LOG [--json OUTPUT]
Only intervals between consecutive FIFO frame-end markers of the same context
are included. Bound-view aliases are conservative, not active sampler proof.
"""
import argparse
from collections import Counter
import json
from pathlib import Path
import re


def analyze(text):
    records = []
    errors = []
    previous = 0
    fragmented = 0
    # The device console can concatenate successive records and insert its
    # process prefix inside a long record. Frame by our explicit prefix, never
    # by newlines, and never let a damaged tail overwrite the header sequence.
    chunks = re.split(r'(?=sweetca: batchtrace e=\d+)', text)[1:]
    for chunk in chunks:
        line = chunk.splitlines()[0]
        fragmented += '|backboardd|' in line or '|SpringBoard|' in line
        fields = {}
        for key, value in re.findall(r'(\w+)=([^\s|]+)', line):
            fields.setdefault(key, value)
        try:
            number = int(fields['e'])
        except (ValueError, KeyError):
            errors.append('malformed record')
            continue
        if number != previous + 1:
            errors.append(f'record gap {previous}->{number}')
        previous = number
        if fields.get('truncated') == '1':
            errors.append(f'truncated record {number}')
        kind = fields.get('event')
        try:
            if kind == 'frame-end':
                int(fields['frame'])
            if kind in ('draw', 'flush'):
                int(fields['draws'])
                fields['batch']
            if kind == 'bound-view':
                int(fields['aliases'], 16)
                fields['batch']
        except (ValueError, KeyError):
            errors.append(f'malformed fields in record {number}')
            continue
        records.append(fields)

    # Markers delimit CA flush epochs, not physical presentation or GPU time.
    pending = {}
    last_frame = {}
    frames = []
    lost = set()
    for record in records:
        ctx = record.get('ctx')
        if not ctx:
            errors.append('record missing context')
            continue
        event = record.get('event')
        if event == 'frame-marker-lost':
            lost.add(ctx)
        if event == 'frame-end':
            frame = int(record['frame'])
            if ctx in last_frame:
                if frame != last_frame[ctx] + 1 or ctx in lost:
                    errors.append(f'nonconsecutive/lost frame marker for {ctx}')
                else:
                    frames.append((ctx, frame, pending.get(ctx, [])))
            pending[ctx] = []
            last_frame[ctx] = frame
            lost.discard(ctx)
        else:
            pending.setdefault(ctx, []).append(record)

    summary = {
        'records': len(records), 'complete_flush_intervals': len(frames),
        'errors': errors, 'valid': bool(records) and not errors,
        'stop_seen': 'batchtrace stop ' in text,
        'console_fragmented_records': fragmented,
        'complete_record_fields': not fragmented,
        'interpretation': 'CA flush intervals; bound aliases conservative; no GPU timing or displayed FPS',
        'contexts': {},
    }
    for ctx, number, events in frames:
        result = summary['contexts'].setdefault(ctx, {
            'intervals': 0, 'draw_records': 0, 'flushes': 0,
            'flush_causes': Counter(), 'mode_selections': Counter(),
            'dependency_edges': 0, 'potential_feedback_batches': 0,
            'batches_without_bound_alias_evidence': 0,
            'carry_in_or_unseen_draw_batches': 0,
            'frame_numbers': [],
        })
        result['intervals'] += 1
        result['frame_numbers'].append(number)
        batches = {}
        for event in events:
            kind = event.get('event')
            if 'batch' in event:
                key = (event.get('screen'), event['batch'])
                batch = batches.setdefault(key, {'first_draw': None, 'alias': False, 'flush': None})
            else:
                batch = None
            if kind == 'draw':
                result['draw_records'] += 1
                if batch['first_draw'] is None:
                    batch['first_draw'] = int(event['draws'])
            elif kind == 'bound-view':
                batch['alias'] |= bool(int(event['aliases'], 16))
            elif kind == 'flush':
                result['flushes'] += 1
                result['flush_causes'][event['cause']] += 1
                batch['flush'] = int(event['draws'])
            elif kind in ('select-sysmem', 'select-gmem', 'select-nondraw'):
                result['mode_selections'][kind] += 1
            elif kind in ('read-dependency', 'write-dependency', 'write-after-write'):
                result['dependency_edges'] += 1
        for batch in batches.values():
            if batch['flush'] is None or batch['flush'] == 0:
                continue
            if batch['first_draw'] != 1:
                result['carry_in_or_unseen_draw_batches'] += 1
            elif batch['alias']:
                result['potential_feedback_batches'] += 1
            else:
                result['batches_without_bound_alias_evidence'] += 1
    return summary


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('log', type=Path)
    parser.add_argument('--json', type=Path)
    args = parser.parse_args()
    result = analyze(args.log.read_bytes().decode('utf-8', 'replace'))
    output = json.dumps(result, indent=2)
    if args.json:
        args.json.write_text(output + '\n', encoding='utf-8')
    print(output)
    return 0 if result['valid'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
