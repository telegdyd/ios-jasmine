#!/usr/bin/env python3
"""Summarize saved Wi-Fi test logs offline; never certify internet/UI from logs.

Exit 0 means required log evidence exists, not that the device test is complete.
"""
import argparse
import json
from pathlib import Path
import re


def analyze(text, phase):
    faults = re.findall(r'^.*(?:panic\(cpu|modem crash reason:|slave-kernel[^\n]*FATAL|'
                        r'SMMU[^\n]*(?:fault|FAULT)|GPU[^\n]*(?:hang|timeout)).*$', text, re.M)
    required = {
        'boot': {'radio_ready': r'WLAN ON \(mission mode\)',
                 'interface_ready': r'en0 and the station are up for iOS',
                 'joined': r'\*\*\* joined .+ \*\*\*'},
        'reboot': {'wlan_off': r'wlan_mode off ok err 0', 'stop_ack': r'\(stop-ack\)',
                   'unpinned': r'SDW pinned client memory[^\n]*: 0 wrapped surfaces alive,\s*wired by 0 GPU imports and 0 pins',
                   'system_unmount': r'SDW step vfs_unmountall\(system\)'},
        'off': {'usb_ready': r'SWEET USB:'},
    }[phase]
    checks = {name: bool(re.search(pattern, text)) for name, pattern in required.items()}
    if phase == 'off':
        checks['no_radio_start'] = not bool(re.search(r'WLAN ON|modem_delay=|\*\*\* joined', text))
    stalls = re.findall(r'^SDW (?:dump[^\n]*|in [^\n]* for (?:[6-9]\d{3}|\d{5,}) ms)\s*$', text, re.M)
    # Reboot collectors receive an initial ring backlog; phase-specific required
    # evidence and faults are intentionally evaluated over the complete saved log.
    return {'phase': phase, 'checks': checks, 'fault_lines': faults,
            'shutdown_stalls': stalls, 'log_gate_pass': all(checks.values()) and not faults and not stalls,
            'still_requires': ['USB command/file service reachability', 'DHCP/DNS/internet',
                               'visual correctness', 'observed fastboot return after reboot']}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('log', type=Path)
    parser.add_argument('--phase', choices=('boot', 'reboot', 'off'), required=True)
    args = parser.parse_args()
    result = analyze(args.log.read_text(errors='replace'), args.phase)
    print(json.dumps(result, indent=2))
    raise SystemExit(0 if result['log_gate_pass'] else 1)
