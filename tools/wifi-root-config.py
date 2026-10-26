#!/usr/bin/env python3
"""Seed configd's Wi-Fi service in a mounted offline iOS root (never a device).

Usage: sudo python3 tools/wifi-root-config.py MOUNTED_ROOT
Existing services, set membership, service order and Wi-Fi credentials are kept.
"""
import argparse
import copy
import os
from pathlib import Path
import plistlib
import uuid


def configure(original):
    data = copy.deepcopy(original)
    services = data.setdefault('NetworkServices', {})
    sid = next((key for key, service in services.items()
                if service.get('Interface', {}).get('DeviceName') == 'en0'), None)
    if sid is None:
        sid = str(uuid.uuid4()).upper()
        services[sid] = {
            'DNS': {}, 'IPv4': {'ConfigMethod': 'DHCP'},
            'IPv6': {'ConfigMethod': 'Automatic'},
            'Interface': {'DeviceName': 'en0', 'Hardware': 'AirPort',
                          'Type': 'Ethernet', 'UserDefinedName': 'Wi-Fi'},
            'Proxies': {'ExceptionsList': ['*.local', '169.254/16'], 'FTPPassive': 1},
            'SMB': {}, 'UserDefinedName': 'Wi-Fi'}
    sets = data.setdefault('Sets', {})
    current = data.get('CurrentSet', '')
    if not current.startswith('/Sets/') or current[6:] not in sets:
        key = str(uuid.uuid4()).upper()
        sets[key] = {'UserDefinedName': 'Automatic'}
        data['CurrentSet'] = '/Sets/' + key
    else:
        key = current[6:]
    network = sets[key].setdefault('Network', {})
    network.setdefault('Service', {})[sid] = {'__LINK__': '/NetworkServices/' + sid}
    network.setdefault('Interface', {}).setdefault('en0', {}).setdefault('AirPort', {})
    order = network.setdefault('Global', {}).setdefault('IPv4', {}).setdefault('ServiceOrder', [])
    if sid not in order:
        order.append(sid)
    data.setdefault('__VERSION__', 20191120)
    return data


def apply(root):
    root = Path(root).resolve()
    if not (root / 'System/Library/xpc').is_dir():
        raise ValueError('expected a mounted offline iOS root with System/Library/xpc')
    path = root / 'private/var/preferences/SystemConfiguration/preferences.plist'
    path.parent.mkdir(parents=True, exist_ok=True)
    original = plistlib.loads(path.read_bytes()) if path.exists() else {}
    data = configure(original)
    if data == original:
        print('Wi-Fi configd service already configured')
        return
    backup = path.with_suffix('.plist.before-wifi')
    if path.exists() and not backup.exists():
        backup.write_bytes(path.read_bytes())
        os.chmod(backup, 0o600)
    temporary = path.with_suffix('.plist.wifi-tmp')
    temporary.write_bytes(plistlib.dumps(data, fmt=plistlib.FMT_BINARY))
    os.chmod(temporary, 0o644)
    if hasattr(os, 'chown'):
        os.chown(temporary, 0, 0)
    temporary.replace(path)
    print('Configured Wi-Fi on en0 (DHCP / automatic IPv6)')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('root', type=Path)
    apply(parser.parse_args().root)
