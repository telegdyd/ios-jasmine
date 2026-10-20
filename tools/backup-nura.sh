#!/usr/bin/env bash
# Full backup of the Mi A2 eMMC while Nura is running, so Nura can be restored after the iOS work.
# Run from Git Bash on the PC:  bash ios-jasmine/tools/backup-nura.sh [OUTDIR]
#
# What it saves (everything is read-only on the phone except a short filesystem freeze):
#   - eMMC GPT head (LBA 0-33) and tail (last 33 LBAs), hardware boot0/boot1, partition list
#   - every GPT partition except userdata, raw, gzip'd, with the phone's sha256 of the raw data
#   - userdata (p69 holds Nura's own disk: p1 = /boot ext2, p2 = / ext4): its GPT head and tail raw,
#     and both filesystems with `e2image -ra` (used blocks only; the free space is old encrypted
#     Android data that would not compress). / and /boot are frozen for that step, with a systemd
#     timer that unfreezes them after 30 minutes if this script dies.
set -euo pipefail

PHONE=${PHONE:-teleg@192.168.1.149}   # over USB: PHONE=teleg@172.16.42.1
OUT=${1:-"$(cd "$(dirname "$0")/../.." && pwd)/backup/nura-full-$(date +%Y%m%d)"}
DISK=/dev/mmcblk1
mkdir -p "$OUT"
cd "$OUT"
log() { echo "[$(date +%H:%M:%S)] $*" | tee -a backup.log; }
r() { ssh -n -o ServerAliveInterval=15 "$PHONE" "$@"; }  # -n: never read the loop's stdin

log "output: $OUT"

# --- metadata -------------------------------------------------------------------------------
r "cat /proc/cmdline; uname -a; cat /etc/os-release; cat /etc/apk/world" > phone-info.txt
r 'for p in /sys/block/mmcblk1/mmcblk1p*; do n=${p##*p}; echo "$n $(grep PARTNAME $p/uevent | cut -d= -f2) $(cat $p/start) $(cat $p/size)"; done | sort -n' > partitions.txt
r "cat /sys/block/mmcblk1/size" > disk-sectors.txt
TOTAL=$(cat disk-sectors.txt)
log "disk: $TOTAL sectors, $(wc -l < partitions.txt) partitions"

r "sudo dd if=$DISK bs=512 count=34 2>/dev/null" > gpt-head-lba0-33.bin
r "sudo dd if=$DISK bs=512 skip=$((TOTAL - 33)) count=33 2>/dev/null" > gpt-tail-last33.bin
for b in boot0 boot1; do r "sudo dd if=${DISK}$b bs=4M 2>/dev/null" > "emmc-$b.bin"; done
log "GPT and boot0/boot1 saved"

# resumable: everything already listed here (with its file present) is skipped
touch SHA256SUMS.phone
done_() { [ -s "$1" ] && grep -q " $1\$" SHA256SUMS.phone; }
trap 'r "sudo systemctl start docker mia2-monitor" || true' EXIT

# --- userdata: Nura's disk ------------------------------------------------------------------
UD=$(awk '$2 == "userdata" {print $1}' partitions.txt)
UDSIZE=$(awk '$2 == "userdata" {print $4}' partitions.txt)
r "sudo dd if=${DISK}p$UD bs=512 count=2048 2>/dev/null" > userdata-head-1MiB.bin
r "sudo dd if=${DISK}p$UD bs=512 skip=$((UDSIZE - 33)) count=33 2>/dev/null" > userdata-tail-last33.bin
r "sudo fdisk -l ${DISK}p$UD" > userdata-layout.txt

if done_ userdata-p2-root.e2i.gz && done_ userdata-p1-boot.e2i.gz; then
	log "userdata images already saved"
else
sed -i "/ userdata-p/d" SHA256SUMS.phone
log "freezing / and /boot for the e2image step (failsafe unfreeze in 30 min)"
# One sudo for the whole frozen section: nothing in here may need to write to / or /boot.
# Only the gzip stream goes to stdout (fd 3); everything else goes to stderr.
# e2image checks that a filesystem mounted on / is writable by creating
# /.ismount-test-file, which blocks forever on a frozen /: start it first and
# freeze / as soon as it reads (services are stopped, so nothing changes meanwhile).
# The EXIT trap keeps the script's status (busybox sh returns the trap's).
r "sudo sh -c '
exec 3>&1 1>&2
set -e
set -o pipefail
systemctl stop mia2-monitor docker docker.socket || true
systemctl stop nura-unfreeze.timer 2>/dev/null || true
systemctl reset-failed nura-unfreeze.service nura-unfreeze.timer 2>/dev/null || true
sync
rm -f /dev/shm/nura-root.fifo /dev/shm/nura-root.sha /dev/shm/nura-boot.e2i
mkfifo /dev/shm/nura-root.fifo
systemd-run --unit=nura-unfreeze --on-active=30min /bin/sh -c \"fsfreeze -u /boot; fsfreeze -u /\"
trap \"rc=\\\$?; fsfreeze -u / 2>/dev/null; fsfreeze -u /boot 2>/dev/null; exit \\\$rc\" EXIT
fsfreeze -f /boot
e2image -fra /dev/loop0p1 /dev/shm/nura-boot.e2i
sha256sum < /dev/shm/nura-root.fifo > /dev/shm/nura-root.sha &
e2image -fra /dev/loop0p2 - | tee /dev/shm/nura-root.fifo | gzip -1 >&3 &
for i in \$(seq 200); do
	e=\$(pidof e2image) && grep -q \"^read_bytes: [1-9]\" /proc/\$e/io && break
	sleep 0.1
done
fsfreeze -f /
wait
fsfreeze -u /
fsfreeze -u /boot
systemctl stop nura-unfreeze.timer 2>/dev/null || true
'" > userdata-p2-root.e2i.gz
log "unfrozen"
r "sudo systemctl start docker mia2-monitor" || log "WARN: service restart failed"
r "sudo cat /dev/shm/nura-root.sha" | awk '{print $1"  userdata-p2-root.e2i.gz"}' >> SHA256SUMS.phone
r "sudo sha256sum /dev/shm/nura-boot.e2i" | awk '{print $1"  userdata-p1-boot.e2i.gz"}' >> SHA256SUMS.phone
r "sudo cat /dev/shm/nura-boot.e2i" | gzip -1 > userdata-p1-boot.e2i.gz
r "sudo rm -f /dev/shm/nura-root.fifo /dev/shm/nura-root.sha /dev/shm/nura-boot.e2i"
fi

# --- raw partitions (all but userdata), after userdata: on 2026-10-20 sustained reads hung
# the eMMC (CQE timeout) after ~3 GiB, so Nura's own data goes first ---------------------
while read -r n name start size; do
	[ "$name" = userdata ] && continue
	f=$(printf "p%02d_%s.img.gz" "$n" "$name")
	done_ "$f" && continue
	r "sudo dd if=${DISK}p$n bs=4M 2>/dev/null" | gzip -1 > "$f"   # compress on the PC: phone gzip is ~4 MB/s
	sum=$(r "sudo sha256sum ${DISK}p$n" | cut -d' ' -f1)
	echo "$sum  $f" >> SHA256SUMS.phone
	log "$f ($((size / 2048)) MiB raw, $(( $(stat -c %s "$f") / 1048576 )) MiB gz)"
done < partitions.txt

# --- verify locally -------------------------------------------------------------------------
log "verifying"
bad=0
while read -r sum f; do
	got=$(gzip -dc "$f" | sha256sum | cut -d' ' -f1)
	if [ "$got" != "$sum" ]; then log "MISMATCH $f"; bad=1; fi
done < SHA256SUMS.phone
sha256sum *.bin > SHA256SUMS.bin
[ $bad = 0 ] && log "all $(wc -l < SHA256SUMS.phone) images verified" || { log "VERIFY FAILED"; exit 1; }
du -sh . | tee -a backup.log
