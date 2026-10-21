#!/usr/bin/env python3
"""Add (or remove) a launchd job in the phone's job cache over USB Ethernet.

iOS 16 launchd reads its jobs from /System/Library/xpc/launchd.plist (a
binary plist: LaunchDaemons maps plist paths to job dictionaries); with the
boot-arg launchd_unsecure_cache=1 it takes a modified one. This fetches the
cache with tools/sweet-fs.py (j0024), keeps the first copy it ever saw in
research/launchd.plist.orig, edits it and puts it back. The change applies
at the next boot.

    sweet-launchd.py add-sweetd        /usr/local/bin/sweetd as root, kept alive
    sweet-launchd.py remove LABEL
    sweet-launchd.py show LABEL
"""
import os
import plistlib
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
CACHE = '/System/Library/xpc/launchd.plist'
ORIG = os.path.join(HERE, '..', 'research', 'launchd.plist.orig')

SWEETD = {
    'Label': 'com.jasmine.sweetd',
    'ProgramArguments': ['/usr/local/bin/sweetd'],
    'RunAtLoad': True,
    'KeepAlive': True,
    'UserName': 'root',
    'POSIXSpawnType': 'Interactive',
    'StandardErrorPath': '/private/var/log/sweetd.log',
}
SWEETD_KEY = '/Library/LaunchDaemons/com.jasmine.sweetd.plist'


def fs(*args):
    env = dict(os.environ, MSYS_NO_PATHCONV='1')
    subprocess.run([sys.executable, os.path.join(HERE, 'sweet-fs.py'), *args], check=True, env=env)


def fetch(tmp):
    local = os.path.join(tmp, 'launchd.plist')
    fs('get', CACHE, local)
    data = open(local, 'rb').read()
    if not os.path.exists(ORIG):
        os.makedirs(os.path.dirname(ORIG), exist_ok=True)
        open(ORIG, 'wb').write(data)
        print(f'original saved to {os.path.normpath(ORIG)}')
    return plistlib.loads(data)


def store(tmp, cache):
    local = os.path.join(tmp, 'launchd.new.plist')
    open(local, 'wb').write(plistlib.dumps(cache, fmt=plistlib.FMT_BINARY))
    fs('put', local, CACHE, '--mode', '644', '--owner', '0:0')


def main():
    if len(sys.argv) < 2:
        sys.exit(__doc__)
    with tempfile.TemporaryDirectory() as tmp:
        cache = fetch(tmp)
        jobs = cache['LaunchDaemons']
        cmd = sys.argv[1]
        if cmd == 'add-sweetd':
            jobs[SWEETD_KEY] = SWEETD
            store(tmp, cache)
            print(f'{SWEETD["Label"]} added ({len(jobs)} jobs); reboot to start it')
        elif cmd in ('remove', 'show') and len(sys.argv) == 3:
            keys = [k for k, v in jobs.items() if v.get('Label') == sys.argv[2]]
            if not keys:
                sys.exit(f'no job labelled {sys.argv[2]}')
            if cmd == 'show':
                for k in keys:
                    print(k, jobs[k])
                return
            for k in keys:
                del jobs[k]
            store(tmp, cache)
            print(f'{sys.argv[2]} removed; reboot to apply')
        else:
            sys.exit(__doc__)


if __name__ == '__main__':
    main()
