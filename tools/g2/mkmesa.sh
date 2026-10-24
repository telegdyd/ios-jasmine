#!/bin/bash
# Regenerate mesa/patches/0001-freedreno-darwin-backend.patch from mesa/darwin/
# (run in WSL). Generate from a temporary checkout of Mesa 26.2.5 so another
# agent's work, and later Mesa patches, are never reset or folded into 0001.
#   wsl bash "/mnt/c/Users/teleg/Documents/Code/Xiaomi A2/ios-jasmine/tools/g2/mkmesa.sh"
set -euo pipefail
R="/mnt/c/Users/teleg/Documents/Code/Xiaomi A2/ios-jasmine"
M="$HOME/ios-work/mesa"
D=$(mktemp -d /tmp/jasmine-mesa.XXXXXX)
git -C "$M" worktree add --quiet --detach "$D" mesa-26.2.5
trap 'git -C "$M" worktree remove --force "$D" >/dev/null 2>&1' EXIT
cd "$D"
python3 -I "$R/mesa/darwin/apply.py" .
git add -A
git -c user.name=telegdyd -c user.email=telegdyd93@gmail.com commit -q -m "freedreno: darwin backend for the SweetGPU IOKit driver (ios-jasmine)"
git format-patch -1 --stdout > "$R/mesa/patches/0001-freedreno-darwin-backend.patch"
git diff --stat HEAD~1 HEAD
for p in "$R"/mesa/patches/000[2-9]-*.patch; do
  [ -e "$p" ] || continue
  git apply --check "$p"
  git apply "$p"
done
echo "Mesa patches apply in order"
