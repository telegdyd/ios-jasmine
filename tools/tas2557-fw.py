#!/usr/bin/env python3
"""Decode a TI TAS2557 PPC3 firmware file (vendor /firmware/tas2557_uCDSP.bin).

Format from Xiaomi jasmine kernel sound/soc/codecs/sdm660_cdc/tas2557-core.c (fw_parse*).
Usage:
  python tools/tas2557-fw.py FW.bin            # list PLLs, programs, configurations, calibrations
  python tools/tas2557-fw.py FW.bin -v         # also dump every block's commands
  python tools/tas2557-fw.py FW.bin --c PROG CONF OUT.inc
      # write a C table (uint8_t book, page, reg, value... runs) for: program PROG, its PLL,
      # configuration CONF, as tas2557_set_program/load_configuration would load them.
      # The output is derived from vendor firmware: keep it out of git.
"""
import struct
import sys

PPC_DRIVER_CRCCHK = 0x200
PPC_DRIVER_CONFDEV = 0x300
PPC_DRIVER_MTPLLSRC = 0x400
PPC_DRIVER_CFGDEV_NONCRC = 0x101


class R:
    def __init__(self, b):
        self.b, self.o = b, 0

    def u8(self):
        v = self.b[self.o]; self.o += 1; return v

    def u16(self):
        v = struct.unpack('>H', self.b[self.o:self.o + 2])[0]; self.o += 2; return v

    def u32(self):
        v = struct.unpack('>I', self.b[self.o:self.o + 4])[0]; self.o += 4; return v

    def fixed(self, n):
        v = self.b[self.o:self.o + n]; self.o += n; return v.split(b'\0')[0].decode('latin1')

    def cstr(self):
        e = self.b.index(b'\0', self.o); v = self.b[self.o:e].decode('latin1'); self.o = e + 1; return v


def block(r, drv):
    t = r.u32()
    pchk = pck = ychk = yck = 0
    if drv >= PPC_DRIVER_CRCCHK:
        pchk, pck, ychk, yck = r.u8(), r.u8(), r.u8(), r.u8()
    n = r.u32()
    data = r.b[r.o:r.o + 4 * n]; r.o += 4 * n
    return dict(type=t, pchk=pchk, pck=pck, ychk=ychk, yck=yck, n=n, data=data)


def tdata(r, drv):
    name = r.fixed(64); desc = r.cstr(); nb = r.u16()
    return dict(name=name, desc=desc, blocks=[block(r, drv) for _ in range(nb)])


def parse(b):
    r = R(b)
    assert b[:4] == b'5552', 'bad magic'
    r.o = 4
    fw = dict(size=r.u32(), crc=r.u32(), ppc=r.u32(), fwver=r.u32(), drv=r.u32(), ts=r.u32(), ddc=r.fixed(64))
    fw['desc'] = r.cstr(); fw['family'] = r.u32(); fw['device'] = r.u32()
    drv = fw['drv']
    fw['plls'] = []
    for _ in range(r.u16()):
        name = r.fixed(64); desc = r.cstr()
        fw['plls'].append(dict(name=name, desc=desc, block=block(r, drv)))
    fw['programs'] = []
    for _ in range(r.u16()):
        name = r.fixed(64); desc = r.cstr(); mode = r.u8(); boost = r.u16()
        fw['programs'].append(dict(name=name, desc=desc, mode=mode, boost=boost, data=tdata(r, drv)))
    fw['configs'] = []
    for _ in range(r.u16()):
        name = r.fixed(64); desc = r.cstr()
        devs = 1
        if drv >= PPC_DRIVER_CONFDEV or (PPC_DRIVER_CFGDEV_NONCRC <= drv < PPC_DRIVER_CRCCHK):
            devs = r.u16()
        prog, pll, rate = r.u8(), r.u8(), r.u32()
        src = srcrate = None
        if drv >= PPC_DRIVER_MTPLLSRC:
            src, srcrate = r.u8(), r.u32()
        fw['configs'].append(dict(name=name, desc=desc, devs=devs, prog=prog, pll=pll, rate=rate, src=src,
                                  srcrate=srcrate, data=tdata(r, drv)))
    fw['cals'] = []
    if len(b) - r.o > 64:
        for _ in range(r.u16()):
            name = r.fixed(64); desc = r.cstr(); prog, conf = r.u8(), r.u8()
            fw['cals'].append(dict(name=name, desc=desc, prog=prog, conf=conf, data=tdata(r, drv)))
    fw['end'] = r.o
    return fw


def commands(blk):
    """Yield ('w', book, page, reg, bytes) / ('sleep', ms) like tas2557_load_block."""
    d, n, i = blk['data'], blk['n'], 0
    while i < n:
        bk, pg, off, val = d[4 * i:4 * i + 4]
        i += 1
        if off <= 0x7F:
            yield ('w', bk, pg, off, bytes([val]))
        elif off == 0x81:
            yield ('sleep', (bk << 8) + pg)
        elif off == 0x85:
            ln = (bk << 8) + pg
            p = d[4 * i:]
            bk, pg, off = p[0], p[1], p[2]
            yield ('w', bk, pg, off, bytes(p[3:3 + ln]) if ln > 1 else bytes([p[3]]))
            i += 1
            if ln >= 2:
                i += ((ln - 2) // 4) + 1


BT = {0: 'PLL', 0xd: 'PGM_ALL', 1: 'PGM_DEV_A', 8: 'PGM_DEV_B', 3: 'CFG_COEFF_A', 0xa: 'CFG_COEFF_B',
      4: 'CFG_PRE_A', 0xb: 'CFG_PRE_B', 5: 'CFG_POST', 6: 'CFG_POST_POWER'}


def show_blocks(blocks, verbose, ind='    '):
    for bl in blocks:
        cmds = list(commands(bl))
        nb = sum(len(c[4]) for c in cmds if c[0] == 'w')
        print(f"{ind}block type {bl['type']:#x} ({BT.get(bl['type'], '?')}) {bl['n']} cmds -> {len(cmds)} ops, "
              f"{nb} bytes, pchk {bl['pchk']}/{bl['pck']:#x} ychk {bl['ychk']}/{bl['yck']:#x}")
        if verbose:
            for c in cmds:
                if c[0] == 'sleep':
                    print(f"{ind}  sleep {c[1]} ms")
                else:
                    print(f"{ind}  B{c[1]} P{c[2]} R{c[3]:#04x} <- {c[4][:16].hex()}{'...' if len(c[4]) > 16 else ''}"
                          f" ({len(c[4])})")


def emit_c(fw, prog, conf, out):
    """Program blocks (PGM_ALL/DEV_A), PLL of the config, config blocks: PRE_A, COEFF_A, POST, POST_POWER."""
    p = fw['programs'][prog]; c = fw['configs'][conf]
    seq = []
    order = [('program', [b for b in p['data']['blocks'] if b['type'] in (0xd, 1)]),
             ('pll', [fw['plls'][c['pll']]['block']]),
             ('cfg_pre', [b for b in c['data']['blocks'] if b['type'] == 4]),
             ('cfg_coeff', [b for b in c['data']['blocks'] if b['type'] == 3]),
             ('cfg_post', [b for b in c['data']['blocks'] if b['type'] == 5]),
             ('cfg_post_power', [b for b in c['data']['blocks'] if b['type'] == 6])]
    with open(out, 'w') as f:
        f.write(f"/* generated by tools/tas2557-fw.py from vendor tas2557_uCDSP.bin: program {prog} \"{p['name']}\", "
                f"configuration {conf} \"{c['name']}\" ({c['rate']} Hz). Do not commit. */\n")
        f.write("/* runs: book, page, reg, len (0 = sleep, then ms in the next byte pair), data... ; 0xff ends */\n")
        for tag, blocks in order:
            f.write(f"static const uint8_t tas_fw_{tag}[] = {{\n")
            for bl in blocks:
                for cm in commands(bl):
                    if cm[0] == 'sleep':
                        f.write(f"\t0, 0, 0, 0, {cm[1] >> 8}, {cm[1] & 0xff},\n")
                    else:
                        _, bk, pg, rg, data = cm
                        for k in range(0, len(data), 200):
                            ch = data[k:k + 200]
                            f.write(f"\t{bk}, {pg}, {rg + k}, {len(ch)}, " + ", ".join(str(x) for x in ch) + ",\n")
            f.write("\t0xff\n};\n")
    print(f"wrote {out}")


def main():
    b = open(sys.argv[1], 'rb').read()
    fw = parse(b)
    v = '-v' in sys.argv
    if '--c' in sys.argv:
        i = sys.argv.index('--c')
        emit_c(fw, int(sys.argv[i + 1]), int(sys.argv[i + 2]), sys.argv[i + 3])
        return
    print(f"size {fw['size']} (file {len(b)}), parsed to {fw['end']}; PPC {fw['ppc']:#x} fw {fw['fwver']:#x} "
          f"driver {fw['drv']:#x} DDC '{fw['ddc']}' desc '{fw['desc']}' family {fw['family']} device {fw['device']}")
    for i, pl in enumerate(fw['plls']):
        print(f"PLL {i}: '{pl['name']}' '{pl['desc']}'")
        show_blocks([pl['block']], v)
    for i, p in enumerate(fw['programs']):
        print(f"program {i}: '{p['name']}' '{p['desc']}' appmode {p['mode']} boost {p['boost']}")
        show_blocks(p['data']['blocks'], v)
    for i, c in enumerate(fw['configs']):
        print(f"config {i}: '{c['name']}' '{c['desc']}' devs {c['devs']} program {c['prog']} PLL {c['pll']} rate "
              f"{c['rate']} pllsrc {c['src']} {c['srcrate']}")
        show_blocks(c['data']['blocks'], v)
    for i, c in enumerate(fw['cals']):
        print(f"calibration {i}: '{c['name']}' program {c['prog']} config {c['conf']}")
        show_blocks(c['data']['blocks'], v)


if __name__ == '__main__':
    main()
