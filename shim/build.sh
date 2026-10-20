#!/bin/bash
# Build the shim and wrap it in an Android boot image for `fastboot boot`.
#   BOARD=jasmine (default): Mi A2. Boot header v0, gzip Image + appended DTB,
#     the same layout as the Nura/pmOS boot.img this ABL boots. The payload
#     (if any) goes in the v0 ramdisk; ABL passes it in /chosen linux,initrd-*.
#     JASMINE_DTB: a DTB ABL accepts for this board (default ../dtb/jasmine.dtb,
#     extracted from the Nura boot.img with tools/extract-dtb.py).
#   BOARD=topaz: boot image v4. The topaz (Xiaomi) ABL ignores v1/v2 images
#     and drops the v4 boot ramdisk, so the payload is appended to the Image
#     behind _end (loader.c).
set -euo pipefail
cd "$(dirname "$0")"
BOARD=${BOARD:-jasmine}
CC=aarch64-linux-gnu-gcc
OBJCOPY=aarch64-linux-gnu-objcopy
CFLAGS="-O2 -ffreestanding -nostdlib -fno-pic -mgeneral-regs-only -mstrict-align -fno-stack-protector -Wall -Wextra"
case "$BOARD" in
	jasmine) CFLAGS="$CFLAGS -DBOARD_JASMINE"; SRCS="start.S shim.c console.c mmu.c fdt.c loader.c" ;;
	topaz) CFLAGS="$CFLAGS -DBOARD_TOPAZ"; SRCS="start.S shim.c console.c mmu.c fdt.c loader.c ufs.c" ;;
	*) echo "unknown BOARD=$BOARD" >&2; exit 1 ;;
esac
mkdir -p out
OBJS=
for f in $SRCS; do
	$CC $CFLAGS -c $f -o out/${f%.*}.o
	OBJS="$OBJS out/${f%.*}.o"
done
# The image runs wherever ABL puts it with no relocation pass: only the
# header's image_size (start.o, linked at 0) may be an absolute address.
abs=$(aarch64-linux-gnu-readelf -r ${OBJS/out\/start.o/} | grep -c ABS64 || true)
[ "$abs" = 0 ] || { echo "error: $abs absolute relocations in C objects" >&2; exit 1; }
$CC $CFLAGS -static -T shim.ld -Wl,--build-id=none -Wl,--no-warn-rwx-segments -Wl,-N $OBJS -o out/shim.elf
$OBJCOPY -O binary out/shim.elf out/Image
# ABL copies the file; pad to image_size so .bss/stacks exist as zeroed bytes.
size=$((16#$(aarch64-linux-gnu-nm out/shim.elf | awk '$3=="_end"{print $1}')))
truncate -s "$size" out/Image

# Ramdisk: an xnu payload (tools/mkpayload.py) if given as $1, else an empty
# newc cpio (ABL dislikes a zero-size ramdisk on some builds) -> diagnostics.
(cd out && rm -rf rd && mkdir rd && cd rd && find . | cpio -o -H newc --quiet | gzip -9 > ../ramdisk.bin)

if [ "$BOARD" = jasmine ]; then
	DTB=${JASMINE_DTB:-../dtb/jasmine.dtb}
	[ -f "$DTB" ] || { echo "error: no DTB at $DTB (see tools/extract-dtb.py)" >&2; exit 1; }
	RD=out/ramdisk.bin
	[ -n "${1:-}" ] && RD=$1
	gzip -9 -n -c out/Image > out/Image.gz
	cat out/Image.gz "$DTB" > out/Image.gz-dtb
	# Offsets as in the Nura boot.img (base 0); ABL uses its own load addresses.
	${MKBOOTIMG:-mkbootimg} --header_version 0 --pagesize 4096 --base 0 \
		--kernel_offset 0x8000 --ramdisk_offset 0x1000000 --second_offset 0xf00000 --tags_offset 0x100 \
		--kernel out/Image.gz-dtb --ramdisk "$RD" --cmdline "console=null" -o out/shim-boot.img
else
	if [ -n "${1:-}" ]; then
		truncate -s $(( (size + 0xfff) & ~0xfff )) out/Image
		cat "$1" >> out/Image
		python3 -c 'import os,struct,sys; f=open(sys.argv[1],"r+b"); f.seek(16); f.write(struct.pack("<Q", os.path.getsize(sys.argv[1])))' out/Image
	fi
	${MKBOOTIMG:-python3 /home/makr/work/topaz/mkbootimg_src/mkbootimg.py} --header_version 4 --kernel out/Image --ramdisk out/ramdisk.bin \
		--os_version 13.0.0 --os_patch_level 2025-01 \
		--cmdline "console=null" -o out/shim-boot.img
fi
# Host render of the console layout.
gcc -O1 -Wall -D"BOARD_$(echo "$BOARD" | tr a-z A-Z)" -o out/host_test console.c host_test.c && ./out/host_test
ls -l out/Image out/shim-boot.img
