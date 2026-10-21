"""Minimal dyld shared cache reader: vaddr -> bytes across subcache files, stub decoding."""
import os, struct, glob

DSC = os.path.expanduser('~/ios-work/gl/dsc/dyld_shared_cache_arm64')


class Cache:
    def __init__(self, base=DSC):
        self.maps = []  # (addr, size, fileoff, path)
        for p in sorted(glob.glob(base + '*')):
            if p.endswith('.symbols'):
                continue
            with open(p, 'rb') as f:
                hdr = f.read(0x20)
                if not hdr.startswith(b'dyld_v1'):
                    continue
                moff, mcnt = struct.unpack_from('<II', hdr, 0x10)
                f.seek(moff)
                for i in range(mcnt):
                    addr, size, foff, maxp, initp = struct.unpack('<QQQII', f.read(32))
                    self.maps.append((addr, size, foff, p))
        self.files = {}

    def read(self, va, n):
        for addr, size, foff, p in self.maps:
            if addr <= va < addr + size:
                f = self.files.get(p) or open(p, 'rb')
                self.files[p] = f
                f.seek(foff + va - addr)
                return f.read(n)
        return None

    def u32(self, va):
        b = self.read(va, 4)
        return struct.unpack('<I', b)[0] if b else None

    def u64(self, va):
        b = self.read(va, 8)
        return struct.unpack('<Q', b)[0] if b else None


def sx(v, bits):
    return v - (1 << bits) if v & (1 << (bits - 1)) else v


def adrp(insn, pc):
    if insn & 0x9f000000 != 0x90000000:
        return None
    imm = ((insn >> 29) & 3) | (((insn >> 5) & 0x7ffff) << 2)
    return (pc & ~0xfff) + (sx(imm, 21) << 12)


def resolve_stub(c, va):
    """Follow a stub (adrp/add/br or adrp/ldr/br[aa]) to its target. Returns (kind, target)."""
    i0, i1, i2 = c.u32(va), c.u32(va + 4), c.u32(va + 8)
    if i0 is None:
        return ('nomap', None)
    page = adrp(i0, va)
    if page is None:
        return ('code', va)
    if i1 & 0xffc00000 == 0x91000000:  # add x16, x16, #imm
        return ('direct', page + ((i1 >> 10) & 0xfff))
    if i1 & 0xffc00000 == 0xf9400000:  # ldr x16, [x16, #imm*8]
        slot = page + ((i1 >> 10) & 0xfff) * 8
        ptr = c.u64(slot)
        # chained pointer in GOT; cache GOTs hold plain or auth pointers; mask high bits
        return ('got', slot, ptr)
    return ('unknown', va)
