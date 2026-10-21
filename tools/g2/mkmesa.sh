#!/bin/bash
# Regenerate mesa/patches/0001-freedreno-darwin-backend.patch from mesa/darwin/
# (run in WSL): ~/ios-work/mesa is Mesa 26.2.5 (tag ddaf85e) + one commit made
# here by mesa/darwin/apply.py; the old commit is dropped and made again.
#   wsl bash "/mnt/c/Users/teleg/Documents/Code/Xiaomi A2/ios-jasmine/tools/g2/mkmesa.sh"
set -e
R="/mnt/c/Users/teleg/Documents/Code/Xiaomi A2/ios-jasmine"
cd ~/ios-work/mesa
git log --oneline -1 | grep -q "freedreno: darwin backend" && git reset -q --hard HEAD~1
python3 -I "$R/mesa/darwin/apply.py" .
git add -A
git -c user.name=telegdyd -c user.email=telegdyd93@gmail.com commit -q -m "freedreno: darwin backend for the SweetGPU IOKit driver (ios-jasmine)"
git format-patch -1 --stdout > "$R/mesa/patches/0001-freedreno-darwin-backend.patch"
git diff --stat HEAD~1
