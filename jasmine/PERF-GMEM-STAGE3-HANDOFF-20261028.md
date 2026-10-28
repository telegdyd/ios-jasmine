# GMEM handoff: finish the whole GMEM work (2026-10-28, paused in stage 3)

Brief for the agent that finishes the GMEM work in [the GMEM plan](PERF-GMEM-PLAN-20261028.md), from
the rest of stage 3 through installation on the phone.
- **Stage 1 (pixel gate trustworthy): done.** Two driver bugs fixed: 0009 and the IOSurface lock in
  `darwin_bo_cpu_prep`, commit 97c59cf. Not installed.
- **Stage 2 (fewer batches): done.** `SWEETCA_SYS_BARRIER=2`, commit 167c44a. 3x fewer batches but
  no GPU gain by itself. Not installed.
- **Stage 3 (GMEM per batch): in progress** (below).
- **Then:** the user's eye-check, a possible tuning round, and installation (tasks 9-12).

**Done means:** a production `libsweetca.dylib` with stages 1-3 enabled is installed and verified on
the phone, or there is a measured reason not to install it, written down and agreed with the user. Read
`AGENTS.md`, the top entries of `NOTES.md` (stage 3 PAUSED handoffs, 06:55 and the later one in
26ad0b2) and the plan first. Stage 2 context: [stage 2 report](PERF-GMEM-STAGE2-20261028.md).

## Goal

Per-batch GMEM (on-chip tile rendering) instead of forced sysmem, for a **global** frame-rate
uplift. DRAM bandwidth is the bottleneck ([bottleneck report](PERF-BOTTLENECK-20261028.md)), and
with task 16 mode 2 installed, GPU time is now frame time. Deliver a measured, pixel-gated test
library and a recommendation. **Installing is the user's decision.**

## Ground rules

- Temporary boots and test names only: `/usr/local/bin/libsweetca-s3.dylib`, `sweetgpu_gltest-<tag>`.
- Never replace `/usr/local/bin/libsweetca.dylib` (production, sha 4780fbaa...) and never flash
  without the user's OK.
- Boot iOS only at 30% battery or more. iOS test boots drain 20-25% per hour, and the phone
  browns out near 11%.
- Park the phone in the r109 charging shell between boots: `research/t24/stage3/park.sh`
  (backlight 0, charge voltage 4050000).
- Use a private phone lock.
- Keep each wait command under ~10 minutes. Don't run long foreground loops.
- Update `NOTES.md` after each milestone. Commit and push to `jasmine`.

## Current state

**Phone:** r109 charging shell, 75% at 16:24.
- installed boot_b: j0110 mode 2, sha 9096026c...;
- production library unchanged;
- `/usr/local/bin/libsweetca-s3.dylib` = dab30309, an old build without the extent fix (replace it);
- `/usr/local/bin/libsweetca-s2.dylib` = 1772b043 (stage 2). Both test libraries are inert.

**Code:** all pushed to `jasmine`, latest 26ad0b2.
- Patch `mesa/patches/0010-freedreno-a5xx-gmem-select.patch` is off by default.
- Switches:
  - `SWEETCA_GMEM=1`: the timed rule.
  - `SWEETCA_GMEM=2`: force GMEM (tests).
  - `SWEETCA_GMEM_LOG=1`: log every decision, and why a target is unsafe.
  - Rule tuning: `SWEETCA_GMEM_MARGIN` (default 110%), `SWEETCA_GMEM_SAMPLE` (8), `SWEETCA_GMEM_RETRY` (64).
  - Tests only: `SWEETCA_GMEM_BIN`, `SWEETCA_GMEM_PITCH_ANY=1`.
- **The rule:** each batch kind is timed on the GPU twice in sysmem and twice in GMEM, then uses
  the faster mode. GMEM must win by the margin.
- **Never GMEM:** retained feedback barriers, depth/stencil, MSAA, layered, query, tessellation
  or tiled/UBWC batches, or targets that fail the extent check.
- **Extent check (fixed in d7db729):**
  - rows must be a multiple of 64 px (the a5xx GMEM alignment);
  - offset + pitch * align(h, 32) must fit within the buffer size, plus the full 128 KiB scratch pad (j0033) for imported buffers.
- If the draws before the first feedback barrier would go GMEM, the batch is split there.
- gpuprof has feedback classes (`sysfb`, `fb/pre`).

**Findings so far:**
- Don't use the GPU's sample counter. With SAMPLES_PASSED on, large targets lose the second
  triangle of full-screen quads, about 1.37M of 2.75M pixels wrong, in sysmem as well.
- Forced GMEM with counting off passed 54/54 GMEM-target checks and the barrier-off, wide-barrier
  and diagnostics cases, with binning on and off. The six stage 2 cases pass.
- Sysmem already writes in 16x4 blocks: row padding up to the 16-px rounding and 2 rows past a
  2438-row image get overwritten. Padding beyond that rounding never changed.
- Before d7db729 every imported IOSurface was rejected. The test surfaces had 4544-byte rows
  (1136 px, not a multiple of 64); the kernel's reported buffer size is correct. CA's frame
  surfaces have 4608-byte rows (1152 px) and should pass now.
  **Unknown:** CA's 1127x2438 and 1131x2442 intermediates.
- `tools/g2/appwork.py` (Settings scroll, General sub-page, Safari open/close) works, checked by
  screen dumps. It does one edge-swipe back first because Settings reopens on its last page.

**Baseline** (GPUPROF boot `s3gp-base`, stage 2 lib with `SWEETCA_SYS_BARRIER=2`; no SMMU fault,
panic or ticket error). Screen dumps of Home, CC, NC and Settings from this boot are in
`research/t24/stage3/`.

| Phase, per frame | Draws | Batches | GPU ms |
| --- | ---: | ---: | ---: |
| Home | 101.7 | 18.6 | 27.40 |
| Control Center | 193.6 | 55.8 | 32.99 |
| Settings scroll | 127.5 | 26.7 | 9.82 |
| Settings sub-page | 64.4 | 12.1 | 5.13 |
| App open/close | 67.9 | 14.6 | 16.98 |

**CI:**
- Mesa runs 40699351392, 40705035918 and 40707645611 were cancelled: "job was not acquired"
  (GitHub's macOS runners).
- Run 40710191541 (macos-13, head d7db729) was queued as of 16:24.
- Dispatch only one run at a time: the workflow's concurrency group cancels the in-progress run.

## Remaining tasks

1. **Get a build of d7db729.** Check run 40710191541 with `gh run view`. If it was cancelled,
   dispatch one new run and wait. Download the library and the `sweetgpu_gltest` artifact into
   `research/t24/stage3/ci-<run>/`.
2. **Push the library** as `/usr/local/bin/libsweetca-s3.dylib` and verify the readback hash.
   Check that the production library is still 4780fbaa.
3. **Pixel gate:**
   `python research/t24/stage3/gate.py research/t24/stage3/ci-<run>/mesa-ios/sweetgpu_gltest research/t24/stage3/gate2 1`
   - 16 cases. All must pass, and it must log GMEM decisions on 1125x2436, 1127x2438 and 1131x2442.
   - If the intermediates are still rejected, read the `SWEETCA_GMEM_LOG` reason and fix it
     (the `SWEETCA_GMEM_PITCH_ANY=1` case shows whether 1136-px rows work in GMEM). Rebuild, re-gate.
4. **GPUPROF boot `s3gp-g1`** (`SWEETCA_GMEM=1,SWEETCA_GMEM_LOG=1` plus the stage 2 env) with
   `research/t24/stage3/s3run.py`. Images are in `shim/out`; rebuild them only if the env must change.
   - Summarise with `bash research/t24/stage3/summ3.sh s3gp-g1` and compare to the baseline table.
   - Report how many batches go GMEM per phase and which kinds.
   - Confirm no SMMU fault, panic or ticket error.
5. **Frame rate:** framebench boots `s3fb-base` and `s3fb-g1`, **twice each**, alternating
   (`s3run.py` / `tools/g2/abround.py`, 150 s settle). Report Home B, CC A/B and Spotlight rates
   with median/p95.
6. **Visual check:** screen dumps of Home, CC, NC, Settings and an app in the `g1` boot, compared
   with the baseline dumps. List anything that differs. The user still has to check motion by eye.
7. **Write `jasmine/PERF-GMEM-STAGE3-20261028.md`:**
   - the rule, the extent/overrun audit and the sample-counter finding;
   - gate results, before/after tables and health;
   - a recommendation (install as is / tune / drop).
   Update the stage 3 line in the plan and `NOTES.md`, commit, push, and park the phone.
8. **Clean up:** remove `/usr/local/bin/libsweetca-s2.dylib` from the phone (stage 2 is
   superseded). Leave `libsweetca-s3.dylib` if it's the recommended candidate.

### After stage 3: finish GMEM

9. **Tuning round (only if the gain is weak).** Home's big batches contain self-sampling (feedback)
   draws, which stay sysmem. The split at the first feedback barrier only moves the part before it
   to GMEM. If Home's GPU ms barely moves, use the gpuprof `sysfb` / `fb/pre` columns to see how
   much Home time sits after the first barrier, then try one of these:
   - **Per-barrier split:** end the batch at each feedback barrier and let every segment choose
     GMEM or sysmem.
   - **Resolve mid-pass:** in GMEM, resolve to memory before the feedback draw and restore after.
     Only worth it if a segment does enough work to pay for one resolve plus one restore of the
     target.

   Also tune `SWEETCA_GMEM_MARGIN` / `SWEETCA_GMEM_SAMPLE` if the rule flaps between modes. Measure
   each change the same way as tasks 4-5. Stop once a variant doesn't beat the previous one.
10. **User eye-check.** Tell the user what to look at, and wait until they've checked it.
    - Build a temporary boot image like the installed boot_b, but loading `libsweetca-s3.dylib`
      with the chosen env.
    - The user looks at motion on the phone: Home paging, Control Center open/close, Notification
      Center, Settings scroll and sub-pages, opening and closing apps, the keyboard, and the lock
      screen.
    - Fix any glitch they report, re-gate and re-check.
11. **Install (needs the user's explicit OK).**
    - Build one production library from the final source with stage 1 (0009 and the
      `darwin_bo_cpu_prep` fix), stage 2 (`SWEETCA_SYS_BARRIER=2`) and stage 3 (`SWEETCA_GMEM=1`).
    - Decide whether the switches go in as library defaults or in boot_b's `sweetenv`. sweetenv
      values are comma-separated, 512 bytes at most; changing it means reflashing boot_b with the
      same procedure as `research/t16port/flash-mode2.py`: backup, boot_b only, exact readback,
      boot_a and GPT checks.
    - Back up the current `/usr/local/bin/libsweetca.dylib` (4780fbaa) both on the phone and in
      `research/`.
    - Replace the library and verify the readback hash.
    - Normal boot: unlock, check that GMEM decisions are logged (briefly with
      `SWEETCA_GMEM_LOG`, then off), and check there is no SMMU fault, panic or ticket error.
    - Run one framebench, take screen dumps, and confirm the slot is marked successful.
    - Write down the rollback (restore the backed-up library, and the boot_b backup if it was
      reflashed).
12. **Close out.**
    - Add an "Installed" section to the stage 3 report and the final status to the plan.
    - Add a dated bullet to `jasmine/PERF-TASKS.md` (task 24 done) and the NOTES handoff.
    - Remove the test libraries from the phone, commit, push, and park the phone in the charging
      shell.

Out of scope: kernel changes, unless GMEM needs one (for example the IOSurface row pitch). Ask the
user first.

## Files

- `research/t24/stage3/`: `gate.py`, `s3run.py`, `one.py`, `summ3.sh`, `s3sum.py`, `park.sh`;
  `scripts/` regenerates patch 0010.
- WSL Mesa tree: `~/ios-work/mesa-t24s3`.
- `tools/g2/appwork.py`, `tools/g2/abround.py`, `tools/g2/gpwork.py`, `tools/g2/uibench.py`
  (command port 5141).
