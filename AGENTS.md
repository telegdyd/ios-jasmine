# Working on ios-sweet

- Read `NOTES.md` before starting; it contains the project goal, hardware facts,
  current blocker, local artifact locations and the next concrete action.
- The user switches agents frequently. Update the active handoff in `NOTES.md`
  after each milestone and before stopping. Record commits, CI run IDs, exact
  build/boot results and unfinished work. Distinguish observations from guesses.
- Commit completed changes.
- Build on the local macOS VM by default, not GitHub Actions (no runner queue):
  `tools/vm-build.sh TAG` for the kernel (~1 min) -> `xnu/out-jasmine-TAG`,
  `tools/vm-mesa.sh mesa|ios TAG` for Mesa and ios-tools -> `xnu/out-mesa-TAG` /
  `xnu/out-ios-TAG`, `tools/g2/gpu-round.sh vm vm TAG` for a whole GPU round.
  They build this checkout including uncommitted edits, so nothing needs pushing
  first. One build at a time (a lock on the VM; another session's build makes
  yours wait). Use CI (`gh`, `.github/workflows/xnu.yml`) only if the VM is
  unreachable (`ssh mac true` fails) or the user asks for it.
- Device bring-up uses temporary `fastboot boot` images. Preserve the Android
  installation and partition backups. The user approved (2026-10-15) using
  internal UFS for iOS and said Android may be deleted: the iOS root goes
  into the existing `userdata` partition (no GPT changes). Keep bootloaders,
  recovery, modem, persist and the backups intact, and confirm each
  destructive step with the user before running it.
- Keep device dumps, serial numbers and downloaded Apple artifacts out of git.
