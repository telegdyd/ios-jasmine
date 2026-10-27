#!/usr/bin/env python3
"""Live register access on the phone for the CPU clock work (j0045).

    osmctl.py 'r 0x179c3004; state'      one or more commands (';'-separated)
    osmctl.py                            interactive: one line per command, empty line quits

Needs sweetcmd=1 or sweetosm=. For status reads on the normal sweetgold clock,
use sweetcmd=1 without sweetosm. sweetosm=8 computes tables but skips sweetgold
(the clock code skips it for all sweetosm>=2). Live check on sweetcmd-only boots
requires j0059a; older kernels leave its reference unset.
Commands (osfmk/arm64/sweet_osm.c, osm_cmd_one):
  r ADDR [N]   read N (1..16) words          w ADDR VAL   write, then read back
  tr ADDR      TZ IO read                    tw ADDR VAL  TZ IO write, TZ read back
  check        pinned-core workload/errors; printed ~MHz is a Gold-calibrated timing proxy
  tsens        temperatures                  state        PLL / RCG / OSM / CPRh / SAW
  table        this chip's CPRh corners      prog         CPRh + SAW + OSM programmed, not enabled
  spmi SID ADDR [N]   PMIC register read     rails        PM660 S1-S3 (APC supplies) voltages
  cpuvolt 0|1 [mV]   j0103: Gold(0)/Silver(1) SAW16 helper; omit mV for status
                     writes need sweetcpuvolt=1; Gold 868/872, Silver 872/876 only
  dvfs stat         j0104+j0104a: status, rail validity, load and failure counters
  dvfs auto 0|1     disable/enable demand scaling; requires sweetdvfs=1
  dvfs set 0|1 KHZ  Gold(0)/Silver(1) stock OPP; disable auto first
  dvfs restore      disable auto and restore boot clocks, rails and APMs
                     sweetdvfsauto=0|1 controls initial auto; thermal=off
Sequences (j0048): one line runs back to back in the kernel.
  m ADDR MASK VAL     read-modify-write      d US         delay      t   us since line start
  poll ADDR MASK VAL [US]   wait for a value; a timeout skips the rest of the line
  rep N        run the rest of the line N times (stops at a failed poll)
SAW4 voltage writes need SIZE bit20 and a full sixteen-bit payload/status check;
the old eight-bit examples did not commit PMIC voltage. Validated neutral Gold
868 mV example (hold the phone lock and confirm live rails before writing):
  'w 0x17812c1c 1; m 0x17812900 0x17ffff 0x100364; m 0x1781204c 0x17ffff 0x100364; poll 0x17812c18 0x3ffff 0x364 2000; t; rails'
See jasmine/PERF-CPU-VOLTAGE-20261027.md for limits and actual readback evidence.
Prefer j0103's serialized cpuvolt helper for these bounded steps: it checks both
Gold rails, verifies delayed PMIC readback, and attempts rollback on failure.
Its fault latch requires reboot. Raw w/m/tw commands bypass that mutex and its
checks; do not mix them with helper transactions. The newer DVFS controller has
passed full stock OPP sweeps on both clusters and uses the same mutex. Physical
UI acceptance remains open after a frozen screen; see
jasmine/PERF-CPU-DVFS-20261027.md. Raw writes also bypass DVFS transaction checks.
Direct accesses are limited to the clock / OSM / CPRh / SAW / APCS / GCC / TSENS blocks.
Goes over the USB command port (TCP 5141, the same as tools/sweet-cmd.py).
"""
import socket
import sys

HOSTS = ('169.254.7.2', '192.168.7.2')
PORT = 5141


def send(line, timeout=30):
    for host in HOSTS:
        try:
            with socket.create_connection((host, PORT), timeout=3) as s:
                s.sendall(line.encode() + b'\n')
                s.settimeout(timeout)
                data = b''
                while True:
                    chunk = s.recv(4096)
                    if not chunk:
                        break
                    data += chunk
                return data.decode(errors='replace').rstrip('\n')
        except OSError:
            continue
    raise SystemExit(f'no command port at {" or ".join(HOSTS)}:{PORT}')


def main():
    if len(sys.argv) > 1:
        print(send(' '.join(sys.argv[1:])))
        return
    while True:
        try:
            line = input('osm> ').strip()
        except EOFError:
            break
        if not line:
            break
        print(send(line))


if __name__ == '__main__':
    main()
