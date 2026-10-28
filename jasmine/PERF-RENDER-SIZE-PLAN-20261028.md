# Render fewer pixels: a smaller CoreAnimation canvas (plan, 2026-10-28)

This is [PERF-TASKS](PERF-TASKS.md) task 25 ([first notes](PERF-TASK23-25-GPU-TRAFFIC.md#25-render-at-or-nearer-the-panel-resolution)),
turned into a plan. It is written for the agent that does the work. Read `AGENTS.md` and the top
entries of `NOTES.md` first.

## Why

- **DRAM traffic is the bottleneck.** Frame rate follows the DDR clock, not the GPU or CPU clock
  ([bottleneck report](PERF-BOTTLENECK-20261028.md)). With task 16 mode 2 installed, GPU time per
  frame is the frame time.
- **GMEM didn't help.** Stage 3 found no net gain ([stage 3 report](PERF-GMEM-STAGE3-20261028.md)):
  self-sampling draws keep about half of Home's GPU time in sysmem.
- **Most traffic scales with pixel count.** CoreAnimation renders the iPhone X's **1125x2436
  (2.74 Mpx)** every frame. The MDP's QSEED3 scaler (j0058) shrinks it to **996x2160 at x=40** on
  the 1080x2160 panel. Fewer rendered pixels means proportionally fewer bytes on every screen, in
  every app. That is the global uplift the user wants.

| Option | Canvas | Scale | Points | Mpx | vs today | Upscale to 996 wide |
| --- | --- | ---: | --- | ---: | ---: | ---: |
| today | 1125x2436 | 3 | 375x812 | 2.74 | - | 0.885 (downscale) |
| **A: iPhone X at @2x** | **750x1624** | **2** | **375x812** | **1.22** | **-55%** | 1.33 |
| B: about the panel size at @3x | e.g. 996x2160 | 3 | 332x720 | 2.15 | -21% | 1.0 |

- **Option A (try first):**
  - The point size is exactly iPhone X's, so UIKit and SpringBoard layout should be unchanged.
    Only the backing scale changes.
  - Expected cost: softer text and icons (2x content scaled up 1.33x), and @3x-only artwork
    downsampled by CoreUI.
  - The upside is large: up to roughly 2x less framebuffer traffic. The real gain will be smaller,
    because textures, the wallpaper and some fixed costs don't shrink.
- **Option B (fallback):**
  - A pixel-sharp 1:1 scanout, but 332x720 pt is no real iPhone.
  - History: the old native 1080x2400 @3x (360x800 pt) gave UIKit's "No status bar visual provider
    for screen" (NOTES.md, 0061: the red rdar:45025538 status bar). That is why 0061 presents
    1125x2436.
  - Only try B if A is rejected for sharpness, and expect UIKit breakage.

## How the size is decided today (verify, don't trust)

- **Kernel**, `SweetFramebuffer.cpp`:
  - `fLogicalW/H = native ? fPanelW/H : 1125/2436`. 0061 defines `SWEET_FB_LOGICAL_W/H`; j0006
    changes it for jasmine. The boot-arg `sweetfb_native=1` presents the panel size.
  - AppleCLCD / IOMobileFramebuffer report this size to userland: GetDisplaySize, the timing
    blocks, SupportedFrameInfo.
- **Kernel, MDP scaler** (j0058): VIG0 QSEED3 source 1125x2436, output 996x2160 at x=40.
  `sweet_fit_x/w` also drives the touch mapping.
- **Kernel, surfaces:** screen-sized IOSurfaces come from the GPU pool
  (0939 contiguous ≤16 MB, 0932/0940 guard rows, 0949 screen-surface reserve). Check every sizing
  constant that assumes 1125x2436 or a 4608-byte row.
- **ADT** (`tools/mkadt.py`, around line 320):
  - `/arm-io/disp0 canvas-width/height` = 1125/2436, or the panel size with `--native`. It must
    match the kernel's presented size: with a mismatch backboardd asks for a hardware scaler that
    doesn't exist.
  - `/chosen/display-scale` = 3. libMobileGestalt (MGIOMFBSupport.c) reads it as main-screen-scale.
- **MobileGestalt disk cache:**
  `/private/var/containers/Shared/SystemGroup/systemgroup.com.apple.mobilegestaltcache/Library/Caches/com.apple.MobileGestalt.plist`
  is keyed by build and UUID only. Stale answers survived a change before (the "iPod" identity).
  **Expect the cached scale/size to override the new ADT** until this file is removed.
- **libsweetca / tools:** `sweetca.c:1930` hard-codes 2436 (a y-flip in a region test). `sweet_shot.m`
  defaults to 1125x2436. `tools/g2` scripts use touch coordinates in panel pixels, which shouldn't
  change, but check them. Grep for 1125, 2436, 4608, 1127, 2438, 1131, 2442 and 996 everywhere
  (mesa/darwin, xnu/patches, tools, shim scripts).

## Steps

0. **Builds:** use the local macOS VM, which is now fast and has no queue.
   - `tools/vm-build.sh TAG` builds the kernel (warm ~60 s), then `tools/g2/mkimg.sh TAG` makes the
     image.
   - `tools/vm-mesa.sh mesa TAG` builds libsweetca (warm ~6 s).
   - Iterate as much as you need; CI is only a final check.
1. **Audit (write it down first).**
   - Every place that fixes 1125x2436 or the 3x scale: kernel, ADT, MDP scaler, touch, GPU pool and
     reserve sizes, guard rows, libsweetca, tools.
   - Where CA gets its size and scale (IOMFB display size, MobileGestalt main-screen-scale).
   - Which userland caches depend on scale: the MobileGestalt cache, SpringBoard icon caches,
     SplashBoard app snapshots, anything under `/var/mobile/Library/Caches` keyed to the screen.
     Use `tools/sweet-fs.py ls` on the phone (read-only).
2. **Kernel switch, default off.** One new jasmine patch (next free `j01xx` number) with a boot-arg,
   e.g. `sweetfb_logical=750x1624`. It sets the presented size and the MDP scaler source from the
   same values, keeps output 996x2160 at x=40 and the touch mapping, and sizes the GPU pool, reserve
   and guard rows from the presented size. Without the boot-arg, the kernel must behave exactly as
   it does today. Add a CI guard like the task 16 ones in `.github/workflows/xnu.yml`.
3. **ADT switch:** a `tools/mkadt.py` option (e.g. `--canvas 750x1624 --scale 2`) for canvas-width/
   height and `/chosen/display-scale`. Build a test boot image from the installed boot_b args (j0110
   mode 2, `research/t16port/j0110-mode2-slotb.img`) plus the new boot-arg and ADT. Don't include
   `abmark=b`, and check the cmdline isn't truncated (guard 649993e).
4. **First boot (temporary `fastboot boot` only).**
   - If MobileGestalt still answers scale 3 or the old size, ask the user before touching its cache
     file:
     - copy the file into `research/render-size/` (ignored);
     - remove it on the phone;
     - after the test, restore it from the backup before any normal boot.
   - Do the same for any other cache you need to clear. Every change to the root must be reversible
     and listed in NOTES.
   - Check:
     - backboardd/SpringBoard come up;
     - the status bar is correct;
     - CADisplay bounds and scale from the logs or `sweet_shot`;
     - no SMMU fault, panic or ticket errors;
     - touch lands where tapped (`tools/g2/appwork.py` taps).
   - Take screen dumps (`sweet_shot` with the new size) of Home, CC, NC, Settings and Safari.
5. **Measure, same method as stage 3**, alternating, with matched clocks (GPU 588 / DDR 1804 / CPU
   auto) and a 150 s settle:
   - framebench `rs-base` vs `rs-a`, **twice each** (`tools/g2/abround.py`; Home B, CC A/B and
     Spotlight rates with median/p95);
   - one GPUPROF boot each (`tools/g2/gpwork.py`, `SWEETCA_GPUPROF=1,SWEETCA_DRAWPROF=1`; GPU ms per
     frame per phase);
   - plus `tools/g2/appwork.py` for Settings scroll and app open/close.
6. **User look.** Ask the user to judge sharpness and motion on the phone (Home, text-heavy
   Settings, Safari, the keyboard) and wait until they have. Text softness is the expected cost;
   only the user can say if it's acceptable. Option B or another geometry only if they reject A.
7. **Report** in `jasmine/PERF-RENDER-SIZE-20261028.md`:
   - the audit, the switches, the boot results, the before/after tables and health;
   - a list of every root change and how it was restored;
   - a recommendation.
   Update PERF-TASKS task 25 and NOTES, then commit and push.
8. **Install, only with the user's explicit OK.**
   - Build a boot_b image with the boot-arg and ADT.
   - Flash it with the `research/t16port/flash-mode2.py` procedure: backup, boot_b only, exact
     readback, boot_a and GPT checks.
   - Before the normal boot, settle the MobileGestalt and other caches at the new scale (or let them
     regenerate).
   - Normal boot and verify. Record the rollback: the boot_b backup plus restoring the saved cache
     files.

## Ground rules

- Temporary boots only until step 8. Never flash or replace `/usr/local/bin/libsweetca.dylib`
  (production 4780fbaa...) without the user's OK. Ask before deleting or changing any file on the
  iOS root, and back it up first.
- Boot iOS only at 30% battery or more (it browns out near 11%; test boots drain 20-25% per hour).
  Park in the r109 charging shell between boots: `research/t24/stage3/park.sh`, backlight 0,
  charge voltage 4050000.
- Use a private phone lock. Keep each wait command under ~10 minutes.
- Update `NOTES.md` after each milestone. Commit and push to `jasmine`. Keep device dumps and
  Apple artifacts out of git.

## Risks to watch

- **Stale userland caches at the wrong scale:** blurry or mis-sized icons, wrong app snapshots, or a
  normal boot that breaks after a test. The backups and restores in step 4 are mandatory.
- **UIKit or apps that assume iPhone10,3 means @3x:** check Settings, Safari and a few built-in
  apps, not just SpringBoard.
- **Touch mapping:** the touch path must still use the 996x2160 fit, not the canvas size.
- **The QSEED3 upscale ratio:** 750 -> 996 is an upscale, while today's 1125 -> 996 is a
  downscale. Verify the scaler handles it: phase steps, preload, and pixel extension.
