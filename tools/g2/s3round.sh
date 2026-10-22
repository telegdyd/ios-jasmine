#!/bin/bash
# G2 step 3 round: boot IMAGE (backboardd with libsweetca through sweetenv), record the
# live log, and once sweetd answers dump the display's swap surfaces (sweet_shot -s) at
# the given delays. The phone keeps what is in /usr/local/bin; PUSH="file ..." from
# xnu/out-mesa goes there first (only when the phone is up before the reboot).
#   bash tools/g2/s3round.sh IMAGE NAME [SHOT_DELAYS...]   (default delays: 15 60)
# Kernel log: logs/netlog-s3-NAME.txt, shots: logs/netlog-s3-NAME.txt.shotN.txt and
# .shotN.ID.raw (one per swap surface; tools/g2/shot2png.py makes PNGs)
cd "/c/Users/teleg/Documents/Code/Xiaomi A2/ios-jasmine" || exit 1
export MSYS_NO_PATHCONV=1
IMG=${1:?image}
N=${2:?name}
shift 2
DELAYS=${*:-15 60}
LOG=logs/netlog-s3-$N.txt
for b in $PUSH; do
	python tools/sweet-fs.py put "xnu/out-mesa/$b" /usr/local/bin/$b --mode 755 || exit 1
done
python tools/sweet-run.py "$IMG" "$LOG" --secs ${SECS:-240} > "$LOG.run" 2>&1 &
RUN=$!
sleep 20
for i in $(seq 1 90); do
	python -c "import socket; socket.create_connection(('169.254.7.2', 5143), timeout=3)" 2>/dev/null && break
	sleep 3
done
echo "# sweetd up at $(date +%T)"
k=0
prev=0
for d in $DELAYS; do
	sleep $((d - prev))
	prev=$d
	k=$((k + 1))
	python tools/sweet-sh.py --timeout 60 /usr/local/bin/sweet_shot -s /usr/local/bin/sweet_shot.raw > "$LOG.shot$k.txt" 2>&1
	echo "# shot $k at $(date +%T):"
	grep "^sweet_shot: surface\|surfaces of" "$LOG.shot$k.txt"
	for f in $(python tools/sweet-fs.py ls /usr/local/bin | grep -o "sweet_shot[.]raw[.][0-9]*"); do
		python tools/sweet-fs.py get /usr/local/bin/$f "$LOG.shot$k.${f##*.}.raw" > /dev/null 2>&1
		python tools/sweet-fs.py rm /usr/local/bin/$f > /dev/null 2>&1
	done
done
wait $RUN
echo "# log done at $(date +%T)"
grep -c "|backboardd| sweetca" "$LOG"
grep -n "SMMU fault\|SWEET PANIC\|panic(cpu\|not imported" "$LOG" | head
