#!/usr/bin/env python3
"""Download one successful integration CI run and prepare its image kit offline.

No waits, phone commands or partition writes. Refuse stale/wrong kernel sources.
"""
import argparse
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import time

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(HERE))
spec = importlib.util.spec_from_file_location('wifi_images', HERE / 'wifi-images.py')
images = importlib.util.module_from_spec(spec)
spec.loader.exec_module(images)


def gh(*args):
    return subprocess.check_output(['gh', *args, '--repo', 'telegdyd/ios-jasmine'], encoding='utf-8')


def fetch_log(run, path):
    jobs = [job for job in run['jobs'] if job['name'] == 'build' and job['conclusion'] == 'success']
    if len(jobs) != 1:
        raise SystemExit('expected exactly one successful kernel build job')
    command = ['gh', 'api', '--allow-escape-sequences',
               f"repos/telegdyd/ios-jasmine/actions/jobs/{jobs[0]['databaseId']}/logs"]
    # Large run-log downloads can fail with HTTP/2 stream cancellation. Fetch
    # the single build job directly, retrying without changing saved artifacts.
    env = os.environ.copy()
    env['GODEBUG'] = env.get('GODEBUG', '') + ',http2client=0'
    for attempt in range(3):
        with path.open('wb') as log:
            result = subprocess.run(command, stdout=log, env=env)
        if result.returncode == 0:
            return
        if attempt < 2:
            time.sleep(2)
    raise SystemExit('build log download failed after three attempts; retry with --resume')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--run', required=True)
    parser.add_argument('--expected-head', required=True)
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--baseline', type=Path, default=ROOT / 'shim/out/shim-boot-j99-wlan.img')
    parser.add_argument('--resume', action='store_true', help='resume an incomplete download for the exact same CI source')
    a = parser.parse_args()
    run = json.loads(gh('run', 'view', a.run, '--json', 'databaseId,headSha,headBranch,status,conclusion,url,workflowName,jobs'))
    if run['headSha'] != a.expected_head or run['workflowName'] != 'xnu':
        raise SystemExit('CI source/workflow mismatch; no artifacts downloaded')
    if run['status'] != 'completed' or run['conclusion'] != 'success':
        raise SystemExit(f"CI is {run['status']}/{run['conclusion']}; no images prepared")
    if a.out.exists():
        previous = json.loads((a.out / 'run.json').read_text()) if (a.out / 'run.json').is_file() else {}
        if not a.resume or previous.get('headSha') != a.expected_head or previous.get('databaseId') != run['databaseId'] or (a.out / 'images').exists():
            raise SystemExit('refusing to overwrite ' + str(a.out))
    else:
        a.out.mkdir(parents=True)
    (a.out / 'run.json').write_text(json.dumps(run, indent=2) + '\n')
    fetch_log(run, a.out / 'build.log')
    logtext = (a.out / 'build.log').read_text(encoding='utf-8', errors='replace')
    if 'Wi-Fi + unwired-wrap reboot fix + framebench integration markers PASS' not in logtext:
        raise SystemExit('missing CI integration gate evidence; no images prepared')
    subprocess.run(['gh', 'run', 'download', a.run, '--repo', 'telegdyd/ios-jasmine',
                    '--name', 'xnu-kernel', '--dir', str(a.out / 'kernel')], check=True)
    kernels = list((a.out / 'kernel').rglob('kernel.development.sweet'))
    if len(kernels) != 1:
        raise SystemExit('expected exactly one development kernel in the artifact')
    sums = kernels[0].parent / 'SHA256SUMS'
    if not sums.is_file():
        raise SystemExit('kernel artifact is missing its CI SHA256SUMS')
    expected = {parts[1].lstrip('*'): parts[0] for line in sums.read_text().splitlines()
                if len(parts := line.split()) == 2}.get(kernels[0].name)
    if expected != hashlib.sha256(kernels[0].read_bytes()).hexdigest():
        raise SystemExit('kernel does not match the CI SHA256SUMS')
    images.prepare(kernels[0], a.baseline, a.out / 'images', run['headSha'], run['databaseId'])


if __name__ == '__main__':
    main()
