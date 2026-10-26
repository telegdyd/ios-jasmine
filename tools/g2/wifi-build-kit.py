#!/usr/bin/env python3
"""Download one successful integration CI run and prepare its image kit offline.

No waits, phone commands or partition writes. Refuse stale/wrong kernel sources.
"""
import argparse
import importlib.util
import json
from pathlib import Path
import subprocess
import sys

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(HERE))
spec = importlib.util.spec_from_file_location('wifi_images', HERE / 'wifi-images.py')
images = importlib.util.module_from_spec(spec)
spec.loader.exec_module(images)


def gh(*args):
    return subprocess.check_output(['gh', *args, '--repo', 'telegdyd/ios-jasmine'], encoding='utf-8')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--run', required=True)
    parser.add_argument('--expected-head', required=True)
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--baseline', type=Path, default=ROOT / 'shim/out/shim-boot-j99-wlan.img')
    a = parser.parse_args()
    run = json.loads(gh('run', 'view', a.run, '--json', 'databaseId,headSha,headBranch,status,conclusion,url,workflowName'))
    if run['headSha'] != a.expected_head or run['workflowName'] != 'xnu':
        raise SystemExit('CI source/workflow mismatch; no artifacts downloaded')
    if run['status'] != 'completed' or run['conclusion'] != 'success':
        raise SystemExit(f"CI is {run['status']}/{run['conclusion']}; no images prepared")
    if a.out.exists():
        raise SystemExit('refusing to overwrite ' + str(a.out))
    a.out.mkdir(parents=True)
    (a.out / 'run.json').write_text(json.dumps(run, indent=2) + '\n')
    with (a.out / 'build.log').open('wb') as log:
        subprocess.run(['gh', 'run', 'view', a.run, '--repo', 'telegdyd/ios-jasmine', '--log'], stdout=log, check=True)
    logtext = (a.out / 'build.log').read_text(encoding='utf-8', errors='replace')
    if 'Wi-Fi + unwired-wrap reboot fix + framebench integration markers PASS' not in logtext:
        raise SystemExit('missing CI integration gate evidence; no images prepared')
    subprocess.run(['gh', 'run', 'download', a.run, '--repo', 'telegdyd/ios-jasmine',
                    '--name', 'xnu-kernel', '--dir', str(a.out / 'kernel')], check=True)
    kernels = list((a.out / 'kernel').rglob('kernel.development.sweet'))
    if len(kernels) != 1:
        raise SystemExit('expected exactly one development kernel in the artifact')
    images.prepare(kernels[0], a.baseline, a.out / 'images', run['headSha'], run['databaseId'])


if __name__ == '__main__':
    main()
