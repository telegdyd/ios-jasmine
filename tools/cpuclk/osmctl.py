#!/usr/bin/env python3
"""Live register access on the phone for the CPU clock work (j0045).

    osmctl.py 'r 0x179c3004; state'      one or more commands (';'-separated)
    osmctl.py                            interactive: one line per command, empty line quits

Needs sweetcmd=1 or sweetosm=. For status reads on the normal sweetgold clock,
use sweetcmd=1 without sweetosm. sweetosm=8 computes tables but skips sweetgold
(the clock code skips it for all sweetosm>=2). The historical live check needs
sweetosm reference initialization; with sweetcmd alone its reference is unset.
Commands (osfmk/arm64/sweet_osm.c, osm_cmd_one):
  r ADDR [N]   read N (1..16) words          w ADDR VAL   write, then read back
  tr ADDR      TZ IO read                    tw ADDR VAL  TZ IO write, TZ read back
  check        workload: this core (~MHz) + all cores x 20 (errors)
  tsens        temperatures                  state        PLL / RCG / OSM / CPRh / SAW
  table        this chip's CPRh corners      prog         CPRh + SAW + OSM programmed, not enabled
  spmi SID ADDR [N]   PMIC register read     rails        PM660 S1-S3 (APC supplies) voltages
Sequences (j0048): one line runs back to back in the kernel.
  m ADDR MASK VAL     read-modify-write      d US         delay      t   us since line start
  poll ADDR MASK VAL [US]   wait for a value; a timeout skips the rest of the line
  rep N        run the rest of the line N times (stops at a failed poll)
  e.g. 'w 0x17812c1c 1; w 0x17812900 0x3b4; poll 0x17812c18 0x300ff 0xb4 2000; t; rails'
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
