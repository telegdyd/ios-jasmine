#!/bin/sh
# A/B of the j0136 idle poll steps on one boot: ab.sh TAG "MODEM USB" ...
cd "$(dirname "$0")/../.."
tag=$1; shift
for mode in "$@"; do
  name=$(echo "$mode" | tr ' ' _)
  python -c "import sys; sys.path.insert(0,'tools/g2'); import prof; print(prof.cmd('idlepoll $mode').strip())"
  sleep 3
  python tools/g2/prof.py fetch research/cpu-idle-20261105/$tag-$name --secs 20 --us 2000 --census 20000 >/dev/null 2>&1
  python research/cpu-idle-20261105/tally.py research/cpu-idle-20261105/$tag-$name 6 | head -8
  echo "usb ping: $(ping -n 20 192.168.7.2 | tail -1)"
  echo "wifi ping: $(ping -n 20 192.168.1.186 | tail -1)"
done
