#!/usr/bin/env python3
"""Clock-sensitivity round on a running kernel (no boot): for each configuration set the
CPU / GPU / DDR clocks through the command port, run one standard framebench capture,
then restore the boot defaults (CPU auto governor, GPU 588 MHz, DDR 1804 MHz).

    sensround.py OUT CONFIG [CONFIG...] --kernel K --lib L [--lock PATH]

CONFIG is NAME:SETTING,SETTING... with SETTING one of
    gold=KHZ / silver=KHZ   pin a cluster (turns the auto governor off; an OPP from the boot log)
    auto                    CPU auto governor (default)
    gpu=MHZ                 "gpu clk MHZ" (j0060 levels 160..647 on this bin)
    ddr=MHZ                 "ddr MHZ" (j0064)
e.g. base:auto  cpumax:gold=2208000,silver=1843200  gpu430:gpu=430  ddr1296:ddr=1296

Each capture goes to OUT/NAME (framebench refuses existing directories). The table at the
end lists swap arrivals/s and median ms of the unsampled home-b / control-b segments and
the sampled control-a. Clocks are runtime only; a reboot also restores them.
"""
import argparse
import json
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import uibench  # noqa: E402

DEFAULTS = ['dvfs auto 1', 'gpu clk 588', 'ddr 1804']


def q(line):
    r = uibench.cmd(line, timeout=30)
    print(f'  > {line}: {(r or "NO ANSWER").splitlines()[0] if r else "NO ANSWER"}', flush=True)
    if r is None:
        sys.exit('phone stopped answering')
    return r


def apply(settings):
    lines = []
    if any(s.startswith(('gold=', 'silver=')) for s in settings):
        lines.append('dvfs auto 0')
    for s in settings:
        k, _, v = s.partition('=')
        if k == 'auto':
            lines.append('dvfs auto 1')
        elif k in ('gold', 'silver'):
            lines.append(f'dvfs set {0 if k == "gold" else 1} {v}')
        elif k == 'gpu':
            lines.append(f'gpu clk {v}')
        elif k == 'ddr':
            lines.append(f'ddr {v}')
        else:
            sys.exit(f'unknown setting {s}')
    for line in lines:
        r = q(line)
        if 'FAIL' in r or 'unsupported' in r or '?' in r.split('\n')[0][:12]:
            sys.exit(f'{line} failed: {r}')


def state():
    return {c: q(c) for c in ('dvfs stat', 'gpu state', 'ddr state', 'tsens')}


def row(out):
    s = json.loads((out / 'summary.json').read_text())
    r = {}
    for ph in ('home-b', 'control-a', 'control-b', 'spotlight-repeat'):
        m = s['phases'].get(ph, {}).get('motion', {})
        r[ph] = (m.get('updates_per_second'), m.get('median_ms'), m.get('p95_ms'))
    return r


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument('out', type=Path)
    p.add_argument('configs', nargs='+')
    p.add_argument('--kernel', required=True)
    p.add_argument('--lib', required=True)
    p.add_argument('--lock')
    a = p.parse_args()
    a.out.mkdir(parents=True, exist_ok=True)
    results = {}
    try:
        for c in a.configs:
            name, _, spec = c.partition(':')
            print(f'== {name}: {spec}', flush=True)
            for line in DEFAULTS:
                q(line)
            apply([s for s in spec.split(',') if s])
            before = state()
            cmd = [sys.executable, str(Path(__file__).parent / 'framebench.py'), 'run', '--out', str(a.out / name),
                   '--ui-ready', '--kernel', a.kernel, '--lib', a.lib]
            if a.lock:
                cmd += ['--lock', a.lock]
            rc = subprocess.run(cmd).returncode
            after = state()
            (a.out / f'{name}.clocks.json').write_text(json.dumps(dict(spec=spec, before=before, after=after, rc=rc), indent=2))
            if rc == 0:
                results[name] = row(a.out / name)
                print(f'  {name}: {results[name]}', flush=True)
    finally:
        print('== restore defaults', flush=True)
        for line in DEFAULTS:
            q(line)
    (a.out / 'sensround.json').write_text(json.dumps(results, indent=2))
    print(f'\n{"config":12} ' + ' '.join(f'{ph:>24}' for ph in ('home-b', 'control-a', 'control-b', 'spotlight-repeat')))
    for name, r in results.items():
        cells = []
        for ph in ('home-b', 'control-a', 'control-b', 'spotlight-repeat'):
            fps, med, _ = r[ph]
            cells.append(f'{fps:6.2f}/s {med:6.1f} ms'.rjust(24) if fps else 'n/a'.rjust(24))
        print(f'{name:12} ' + ' '.join(cells))


if __name__ == '__main__':
    main()
