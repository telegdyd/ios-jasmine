#!/bin/sh
# Build shim/out/charge-shell.img: the r109 Nura boot image (shim/out/nura-r109-boot_a.img)
# with tools/charge-shell/init as /init and /sbin/reboot-bootloader. Run in WSL:
#   WSL_UTF8=1 MSYS_NO_PATHCONV=1 wsl -e sh tools/charge-shell/build.sh
# Then `fastboot boot shim/out/charge-shell.img` (RAM only, active slot unchanged).
set -eu
REPO=$(cd "$(dirname "$0")/../.." && pwd)
SRC="$REPO/shim/out/nura-r109-boot_a.img"
OUT="$REPO/shim/out/charge-shell.img"
W=$(mktemp -d)
trap 'sudo rm -rf "$W"' EXIT

unpack_bootimg --boot_img "$SRC" --out "$W/img" --format mkbootimg > "$W/args"
mkdir "$W/rd"
( cd "$W/rd" && gzip -dc "$W/img/ramdisk" | sudo cpio -id --quiet )
sudo mv "$W/rd/init" "$W/rd/init.pmos"
tr -d '\r' < "$REPO/tools/charge-shell/init" | sudo tee "$W/rd/init" > /dev/null
sudo chmod 755 "$W/rd/init"
# tools/reboot-bootloader.c (static aarch64): back to fastboot without pushing it first
sudo install -m 755 "$REPO/shim/out/reboot-bootloader" "$W/rd/sbin/reboot-bootloader"
( cd "$W/rd" && find . | LC_ALL=C sort | sudo cpio -o -H newc --quiet | gzip -9 > "$W/ramdisk.new" )
cp "$W/ramdisk.new" "$W/img/ramdisk"

# shellcheck disable=SC2046
eval mkbootimg $(cat "$W/args") --output '"$OUT"'
ls -l "$OUT"
