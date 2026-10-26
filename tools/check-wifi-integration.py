#!/usr/bin/env python3
"""Fail closed when the XNU wrapper silently skips a repository patch.

Also check the combined Wi-Fi/reboot/framebench source before packaging.
"""
import argparse
from pathlib import Path
import re


def check(source, log=None):
    if log:
        names = {p.name for p in (Path(__file__).resolve().parents[1] / 'xnu/patches').glob('*.patch')}
        skipped = re.findall(r'Skipping patch \S*/([^/\s]+\.patch)', log.read_text(errors='replace'))
        bad = sorted(names.intersection(skipped))
        if bad:
            raise ValueError('repository patches skipped: ' + ', '.join(bad))
    markers = {
        'iokit/Kernel/arm/TopazModem.cpp': [
            'uint32_t v = sweet_board_is("xiaomi,jasmine") ? 1 : 0;',
            'uint32_t on = sweet_board_is("xiaomi,jasmine") && wifi_enabled();',
            'if (!wifi_diag || g_ms < 3000', '"wifi_diag", &wifi_diag',
            'qrtr', 'w_leave_poll'],
        'iokit/Kernel/arm/SweetGPU.cpp': [
            'OSIncrementAtomic(&sweet_gpu_wrapped_imports)',
            'OSDecrementAtomic(&sweet_gpu_wrapped_imports)', 'sweet_bench_alloc(7, -1)'],
        'iokit/Kernel/arm/SweetSurface.cpp': [
            'kIOMemoryPersistent', 'SDW pinned client memory', 'sweet_surface_pin', 'sweet_bench_alloc(2, -1)'],
        'bsd/dev/redwood_apple80211.c': ['RSSI_BOUNDS'],
        'osfmk/arm64/sweet_bench.inc': ['BC_SAMPLES 65536u'],
    }
    for name, required in markers.items():
        text = (source / name).read_text()
        for marker in required:
            if marker not in text:
                raise ValueError(f'{name}: missing {marker!r}')
    print('Wi-Fi + unwired-wrap reboot fix + framebench integration markers PASS')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', type=Path, required=True)
    parser.add_argument('--log', type=Path)
    args = parser.parse_args()
    check(args.source, args.log)
