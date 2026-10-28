#!/bin/sh
# Mesa / ios-tools builds on the local macOS VM instead of GitHub Actions (the mesa and
# ios-tools jobs of xnu.yml; no runner queue, incremental Mesa rebuilds).
#   tools/vm-mesa.sh mesa TAG    -> xnu/out-mesa-TAG (files of the mesa-ios artifact)
#   tools/vm-mesa.sh ios TAG     -> xnu/out-ios-TAG  (files of the ios-tools artifact)
# Sends this checkout's mesa, ios and tools (uncommitted edits included) to the VM, runs
# tools/mesa-local.sh there and copies the signed outputs back. tools/g2 scripts push from
# xnu/out-mesa: OUT=xnu/out-mesa writes there instead.
# Env: VM (ssh host, default mac), OUT, TASK24_CONTROLS=1 (mesa: also the gltest without patch0008).
# First time only: ssh mac sh -s < tools/vm-mesa-setup.sh (Python 3.13, bison 3.8, meson venv).
# Shares vm-build.sh's lock, so kernel and Mesa builds on the VM never run at once.
set -eu
cd "$(dirname "$0")/.."
usage='usage: vm-mesa.sh mesa|ios TAG'
mode=${1:?$usage}
tag=${2:?$usage}
case $mode in mesa|ios) ;; *) echo "$usage" >&2; exit 1;; esac
vm=${VM:-mac}
out=${OUT:-xnu/out-$mode-$tag}
src=$(git rev-parse --short HEAD)$(git diff --quiet HEAD -- mesa ios || echo -dirty)

until ssh "$vm" 'mkdir -p ~/topaz-xnu-build && mkdir ~/topaz-xnu-build/.lock 2>/dev/null'; do
	echo "VM build busy ($(ssh "$vm" 'cat ~/topaz-xnu-build/.lock/owner 2>/dev/null')), waiting" >&2
	sleep 20
done
ssh "$vm" "echo '$(hostname) $mode $tag' > ~/topaz-xnu-build/.lock/owner"
trap 'ssh "$vm" "rm -rf ~/topaz-xnu-build/.lock"' EXIT

tar czf - --exclude=__pycache__ mesa ios tools | ssh "$vm" 'rm -rf ~/ios-jasmine/mesa ~/ios-jasmine/ios ~/ios-jasmine/tools && mkdir -p ~/ios-jasmine && tar xzf - -C ~/ios-jasmine'
t0=$(date +%s)
if ! ssh "$vm" "cd ~/ios-jasmine && TASK24_CONTROLS=${TASK24_CONTROLS:-0} SOURCE=$src tools/mesa-local.sh $mode"; then
	echo "build failed; logs: ssh $vm ls topaz-mesa/*.log" >&2
	exit 1
fi
echo "built in $(($(date +%s) - t0)) s"
rm -rf "$out"
mkdir -p "$out"
ssh "$vm" "tar cf - -C topaz-mesa/out-$mode ." | tar xf - -C "$out"
ssh "$vm" "cat topaz-mesa/out-$mode.sha256" | (cd "$out" && sha256sum -c --quiet) && echo "$out: $(ls "$out" | tr '\n' ' ')"
