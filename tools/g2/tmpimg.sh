#!/bin/sh
# Temporary boot image for kernel TAG with the exact command line and ADT of an existing payload:
#   tools/g2/tmpimg.sh TAG [REF]     (REF payload tag, default scan138-tmp; ADT jasmine-m7slotb.adt)
# -> shim/out/shim-boot-TAG-tmp.img; checks cmdline and ADT are byte-identical to REF's.
set -eu
cd "$(dirname "$0")/../.."
tag=${1:?usage: tmpimg.sh TAG [REF]}
ref=shim/out/payload-${2:-scan138-tmp}.bin
cmd=$(python -c "import sys;b=open(sys.argv[1],'rb').read();print(b[0x48:0x48+608].split(b'\0')[0].decode())" "$ref")
MSYS_NO_PATHCONV=1 wsl -e bash -c "python3 tools/mkpayload.py xnu/out-jasmine-$tag/kernel.development.sweet shim/out/jasmine-m7slotb.adt shim/out/payload-$tag-tmp.bin --cmdline '$cmd' >/dev/null && bash shim/build.sh shim/out/payload-$tag-tmp.bin > shim/out/build-$tag-tmp.log 2>&1 && cp shim/out/shim-boot.img shim/out/shim-boot-$tag-tmp.img"
python - "$ref" "shim/out/payload-$tag-tmp.bin" <<'PY'
import struct, sys
def info(p):
    b = open(p, 'rb').read(); o, s = struct.unpack_from('<QQ', b, 0x20)
    return b[0x48:0x48 + 608], b[o:o + s]
a, n = info(sys.argv[1]), info(sys.argv[2])
assert a == n, 'cmdline or ADT differ'
print('cmdline and ADT identical to', sys.argv[1])
PY
ls -la shim/out/shim-boot-$tag-tmp.img
