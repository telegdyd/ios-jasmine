#!/bin/bash
# Build first with tools/vm-mesa.sh mesa m9ubwc1 so the UBWC headers exist.
set -euo pipefail
cd "$(dirname "$0")/.."
vm=${VM:-mac}
ssh "$vm" true
ssh "$vm" 'mkdir -p /tmp/m8tl'
tar cf - -C mesa/metal src air test | ssh "$vm" 'tar xf - -C /tmp/m8tl'
ssh "$vm" 'set -eu; for test in /tmp/m8tl/test/run-*.sh; do echo "== $test"; sh "$test"; done'
