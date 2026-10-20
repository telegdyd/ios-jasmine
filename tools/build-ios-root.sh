#!/bin/bash
# jasmine: iPhone X iOS root image for the Mi A2 userdata partition, from the IPSW.
#
#   tools/build-ios-root.sh IPSW WORKDIR [SIZE]        (SIZE default 17G)
#
# 1. Takes BuildManifest.plist, the D22AP "Erase" identity's OS, SystemOS and
#    AppOS disk images and its DeviceTree out of the IPSW (only those members).
# 2. research/ipsw-x/d22ap.adt <- DeviceTree.d22ap.im4p (tools/mkadt.py copies
#    its /product node).
# 3. tools/mkiosroot.sh builds the case-sensitive journaled HFS+ root,
#    tools/sweet-root-tweaks.py applies the bring-up changes.
# 4. WORKDIR/ios16-root.simg: Android sparse image for `fastboot flash userdata`.
#
# userdata is 18171 MiB; the image must leave the last 4 MiB + 4 KiB free for
# the persistent console log (bsd/dev/sweet_ufs.c), so at most ~17.7 GiB.
# Linux needs hfsplus (WSL: build it, see jasmine/NOTES), apfs-fuse, hfsprogs,
# lzfse, img2simg, unzip, and sudo.
set -euo pipefail
[[ $# -ge 2 ]] || { sed -n '2,16p' "$0"; exit 2; }
ipsw=$(realpath "$1") work=$2 size=${3:-17G}
repo=$(cd "$(dirname "$0")/.." && pwd)
mkdir -p "$work"
work=$(realpath "$work")
cd "$work"

grep -q hfsplus /proc/filesystems || { echo "no hfsplus filesystem in this kernel" >&2; exit 1; }

unzip -o -q "$ipsw" BuildManifest.plist
read -r os sysos appos dt < <(python3 -I - BuildManifest.plist <<'PY'
import plistlib, sys
m = plistlib.load(open(sys.argv[1], 'rb'))
for ident in m['BuildIdentities']:
    info = ident['Info']
    if info.get('DeviceClass', '').lower() == 'd22ap' and info.get('RestoreBehavior') == 'Erase':
        man = ident['Manifest']
        print(man['OS']['Info']['Path'], man['Cryptex1,SystemOS']['Info']['Path'],
              man['Cryptex1,AppOS']['Info']['Path'], man['DeviceTree']['Info']['Path'])
        break
else:
    sys.exit('no D22AP Erase identity')
PY
)
echo "OS $os, SystemOS $sysos, AppOS $appos, DeviceTree $dt"
unzip -o -q "$ipsw" "$os" "$sysos" "$appos" "$dt"

mkdir -p "$repo/research/ipsw-x"
python3 -I "$repo/tools/im4p-extract.py" "$dt" "$repo/research/ipsw-x/d22ap.adt"

img=$work/ios16-root.img
rm -f "$img"
bash "$repo/tools/mkiosroot.sh" "$os" "$sysos" "$appos" "$img" "$size"

mnt=$(mktemp -d)
sudo mount -t hfsplus -o loop,force "$img" "$mnt"
trap 'sudo umount "$mnt" 2>/dev/null; rmdir "$mnt" 2>/dev/null' EXIT
sudo python3 -I "$repo/tools/sweet-root-tweaks.py" "$mnt"
df -h "$mnt"
sudo umount "$mnt"
fsck.hfsplus -f -n "$img"

img2simg "$img" "$work/ios16-root.simg"
sha256sum "$img" "$work/ios16-root.simg" | tee "$work/SHA256SUMS"
ls -l "$img" "$work/ios16-root.simg"
