#!/bin/bash
# G2 step 2 quick round on a phone that is already up (no reboot): download a Mesa CI run,
# push sweetca_test + libsweetca.dylib through sweetd, run the test with the live kernel log attached.
#   bash tools/g2/s2quick.sh MESA_RUN NAME
# Test output: logs/netlog-s2-NAME.txt.tests, kernel log (the ring so far + the run): logs/netlog-s2-NAME.txt
cd "/c/Users/teleg/Documents/Code/Xiaomi A2/ios-jasmine" || exit 1
export MSYS_NO_PATHCONV=1
G="/c/Program Files/GitHub CLI/gh"
R=${1:?mesa run}
N=${2:?name}
LOG=logs/netlog-s2-$N.txt
rm -rf xnu/out-mesa
"$G" run download $R -R telegdyd/ios-jasmine -n mesa-ios -D xnu/out-mesa || exit 1
python tools/sweet-netlog.py "$LOG" --wait 20 --for ${SECS:-90} > /dev/null 2>&1 &
NL=$!
for b in libsweetca.dylib sweetca_test; do
	python tools/sweet-fs.py put "xnu/out-mesa/$b" /usr/local/bin/$b --mode 755 || exit 1
done
python tools/sweet-sh.py --timeout 60 /usr/local/bin/sweetca_test > "$LOG.tests" 2>&1
echo "# sweetca_test exit $? at $(date +%T)" >> "$LOG.tests"
wait $NL
grep -v "^  \|^ GPU\|^ CPU" "$LOG.tests" | cut -c1-300
grep -n "SMMU fault\|SWEET PANIC\|panic(cpu" "$LOG" | head
