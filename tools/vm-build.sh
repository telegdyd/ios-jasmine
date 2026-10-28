#!/bin/sh
# Kernel build on the local macOS VM instead of GitHub Actions (no runner queue; ~1 min warm).
#   tools/vm-build.sh TAG        -> xnu/out-jasmine-TAG/kernel.development.sweet (as from CI)
# Sends this checkout's xnu/patches and tools (uncommitted edits included) to the VM, runs
# tools/build-local.sh there and copies the kernel back. Then tools/g2/mkimg.sh TAG as usual.
# Env: VM (ssh host, default mac), TOPAZ_4K (passed through, default 1).
# One build at a time: the VM has one build tree, so a lock directory there serializes callers.
set -eu
cd "$(dirname "$0")/.."
tag=${1:?usage: vm-build.sh TAG}
vm=${VM:-mac}
out=xnu/out-jasmine-$tag

until ssh "$vm" 'mkdir ~/topaz-xnu-build/.lock 2>/dev/null'; do
	echo "VM build busy ($(ssh "$vm" 'cat ~/topaz-xnu-build/.lock/owner 2>/dev/null')), waiting" >&2
	sleep 20
done
ssh "$vm" "echo '$(hostname) $tag' > ~/topaz-xnu-build/.lock/owner"
trap 'ssh "$vm" "rm -rf ~/topaz-xnu-build/.lock"' EXIT

tar czf - --exclude=__pycache__ xnu/patches tools | ssh "$vm" 'rm -rf ~/ios-jasmine/xnu/patches ~/ios-jasmine/tools && mkdir -p ~/ios-jasmine && tar xzf - -C ~/ios-jasmine'
t0=$(date +%s)
if ! ssh "$vm" "cd ~/ios-jasmine && TOPAZ_4K=${TOPAZ_4K:-1} tools/build-local.sh"; then
	echo "build failed; full log: ssh $vm cat topaz-xnu-build/build.log" >&2
	exit 1
fi
echo "built in $(($(date +%s) - t0)) s"
rm -rf "$out"
mkdir -p "$out"
scp -q "$vm:topaz-xnu-build/out/kernel.development.sweet" "$vm:topaz-xnu-build/out/SHA256SUMS" "$out/"
(cd "$out" && sha256sum -c SHA256SUMS)
