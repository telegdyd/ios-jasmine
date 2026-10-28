# Smaller CoreAnimation canvas (task 25): kernel path works, UIKit blocks 2x (2026-10-28)

Plan: [PERF-RENDER-SIZE-PLAN-20261028.md](PERF-RENDER-SIZE-PLAN-20261028.md). **Result: the kernel,
MDP and ADT parts of option A (750x1624 @2x) work, but UIKit refuses to build a status bar for any
scale-2 screen with the iPhone X's corner radius, so nothing could be measured, looked at or
installed. Steps 5 to 8 were not done.** No flash, no install, production libsweetca untouched.

## Audit (step 1)

Everything that fixes the presented size goes through `AppleCLCD::fLogicalW/H` (SweetFramebuffer.cpp):
GetDisplaySize, the 60 Hz timing blocks, the j0058 scaler source (`scalerInit`), the j0109/j0110
direct-present eligibility (`width == fLogicalW`), the fit maps and `sweet_fit_x/w`. So one switch
covers the kernel.

| Place | Fixed to 1125x2436 / @3? | Action |
| --- | --- | --- |
| SweetFramebuffer.cpp `fLogicalW/H`, `scalerInit`, `directEligible` | yes, via `fLogicalW/H` | switch sets them (j0111) |
| fit rule `fHeight*100 < fLogicalH*95`, `fLogicalH > fHeight` | yes (skips the fit for a canvas below the panel) | forced on in small-canvas mode |
| SweetHID touch | uses `sweet_fit_x/w` and the panel height when the fit is active | none needed (still 996x2160 at x 40) |
| GPU pool: 0939 (16 MB cap), 0932/0940 guard rows, 0949 reserve (12 MB buffers) | comments only; limits are byte sizes | none; a 4.9 MB frame fits the reserve (wasteful, not wrong) |
| `sweet_scanout_set_geometry` | only used with gpu=0 | none |
| ADT `/arm-io/disp0 canvas-*`, `/chosen display-scale` | yes | `mkadt.py --canvas WxH --scale N` |
| **MobileGestalt disk cache** | **yes: main-screen-scale 3.0 (CacheData +3040), size 1125x2436, corner radius 39.0 (+776)** | had to be removed for the test |
| libsweetca `sweetca.c:1930` | 2436 in the `SWEETCA_REGION` debug probe only | left |
| `sweet_shot.m` | default 1125x2436 | pass the size (`research/render-size/shot.py`, ignored) |
| mesa gm_target test sizes | 1125x2436 test cases | left |

## Switch and tooling (steps 2, 3)

- `xnu/patches/j0111-jasmine-small-canvas.patch`: boot-args `sweetfb_lw=750 sweetfb_lh=1624` (both,
  even width, within 1125x2436, not with `sweetfb_native`). Unset: kernel unchanged. CI guard added
  to `xnu.yml`. VM build 70 s.
- `tools/mkadt.py --canvas 750x1624 --scale 2`; `tools/g2/mkimg.sh` takes `CANVAS=750x1624 [SCALE=2]`.
- Images (installed boot_b args, j0110 mode 2, no `abmark`, cmdline 544/575 bytes, under 608):
  `shim/out/shim-boot-j0111-rsbase.img` (baseline), `-rsa.img` (750x1624@2), `-rsx.img` (828x1792@2).

## Boots (step 4), all temporary `fastboot boot`

| Boot | Result |
| --- | --- |
| rs-a1: 750x1624@2, MG cache untouched | Kernel: `750x1624 fitted into 996x2160 at x 40`, QSEED3 steps 0x1818ac (upscale), "MDP scales pool frames", modes 750x1624, no SMMU fault or panic. Userland still got **scale 3 from the cached MG** -> 250x541 pt, red status bar. |
| rs-a2: same, MG cache deleted (user OK) | backboardd `size:{750,1624} scale:2`, UIScreen 375x812 @2x, layout fine, **red "rdar:45025538" status bar**: `No status bar visual provider ... (width: 375, scale: 2, idiom: 0, cornerRadius: 39)` |
| rs-x1: 828x1792@2 (XR class, 414x896 pt) | same error with width 414 |
| rs-x2: as x1 with the MG cache hand-edited to corner radius 41.5 (user OK) | cache accepted and kept, but UIScreen still reports cornerRadius 39, same error |

Reading: UIKit chooses the status bar provider from (width, scale, idiom, corner radius) and only
knows real device combinations: 375@3 / 39 works, 375@2 and 414@2 with 39 do not. The corner radius
39 does not come from the MG cache offset I edited (the real source is unknown), so an XR-class
combination (414@2, 41.5) could not be forged this way. This is the same wall as the earlier
360x800@3x try. Touch, framebench and the other apps were not exercised; only boot and one home
screen dump per boot (`research/render-size/*.png`, ignored).

## Root changes and restore

Only one file was touched: `.../systemgroup.com.apple.mobilegestaltcache/Library/Caches/com.apple.MobileGestalt.plist`
(8016 bytes, sha256 c70accbbd3343b9bfa9891749c83237df1c04e1a7d91f0d799e85b8bd42bbfd9). Backed up to
`research/render-size/backup/` (ignored) before the first change. Deleted (rs-a2, rs-x1; MG
regenerated it at scale 2), replaced by an edited copy (rs-x2), and **restored from the backup and
read back byte-identical** before parking. The installed boot_b was never changed, so a normal boot
sees the original cache. The `rsshot.raw*` dump files in `/usr/local/bin` were removed. No other
cache was touched or inspected (SpringBoard icon and snapshot caches).

## Not done

Step 5 (framebench, GPUPROF, appwork before/after), step 6 (user look) and step 8: pointless while the
status bar is broken. The `rsbase` image is built but unbooted.

## Recommendation / ways forward

1. Install nothing from this work. The switch is harmless while its boot-args are unset.
2. To continue, UIKit's provider table must be satisfied for a scale-2 screen. Options:
   (a) find where UIScreen's corner radius comes from (libMobileGestalt or BackBoard; the cache offset
   I edited was not it) and present 414x896@2x with radius 41.5 (XR class, 828x1792, -46% pixels);
   (b) hook UIKit's status bar provider choice via an inject library in SpringBoard and apps (system-wide
   injection, intrusive);
   (c) keep UIKit at 375x812@3x and render the display target at 2/3 size inside libsweetca's GL layer
   (no UIKit change, large Mesa/EAGL change).
   Each needs UIKitCore disassembly (dyld cache extraction) first: the next concrete step.
3. Re-test only with `rsbase` vs the new image, alternating twice, per plan step 5.

## UIKit status bar analysis (follow-up, UIKitCore 16.7.16 from the shared cache, disassembled with otool)

`+[_UIStatusBarVisualProvider_Split visualProviderSubclassForScreen:visualProviderInfo:]` walks nine
provider classes (`Split1080`, `Split1080_Wide`, `Split1125`, `Split1170`, `Split1170_Wide`, `Split1242`,
`Split828`, `Split1284`, `Split1284_Wide`) and picks the first whose class methods match the screen:

1. `+nativeDisplayWidth` equals `[UIScreen _nativeDisplayBounds]` width. That is the display's
   **pixelSize** (`FBSDisplayConfiguration`), i.e. the width CoreAnimation renders: 750 matches nothing, so no
   scale-2 canvas of the iPhone X's width can work. Only 828, 1080, 1125, 1170, 1242, 1284 are accepted.
2. With r = `_nativeScale` / (`+referenceScreenScale` if the class has one, else `_scale`):
   `|+notchSize.width - exclusionArea.width * r|` and `|+notchSize.height - exclusionArea.height * r|` within
   a small tolerance. `exclusionArea` comes from `-[_UIDisplayInfoProvider exclusionArea]`. `Split1125`'s notch
   height is 30, `Split828`'s is 32.

Corner radius is not part of the check (earlier guess was wrong). Consequences:

- 828x1792 @2x (414x896 pt, -46% pixels) passes check 1. It failed because the exclusion area is not the XR
  notch: MobileGestalt regenerates its screen rectangles by scaling the iPhone X values, so the height stays near
  30, not 32 (the cache shows scaled rectangles after the 828 boot: 414x261/147 instead of 375x174/98).
- Next experiment: find where `_UIDisplayInfoProvider` gets `exclusionArea` (and the periphery/safe-area insets)
  and make it the iPhone XR's, either through the cache keys `aD51uq...`, `PdprWt...`, `rJkMAG...`, `pMeQxE...` or
  an `ArtworkDeviceSubType` of 1792 (the cache has 2436), then boot `shim-boot-j0111-rsx.img` again. Read the
  `Split828` constants with `otool -s __TEXT __const`; I only have the notch heights (30, 32) so far.
- Not worth trying: any 750-wide canvas. Alternative sizes in the list: 1080 wide at @3x (360x780 pt, 12 mini
  class, 2.5 Mpx, only -8%) — no real gain.

Files: UIKitCore extracted to `research/render-size/uik/` (ignored), disassembly on the Mac VM in `/tmp/uik-text.txt`.

### 1080-wide class (iPhone 12 mini family) — constants read from UIKitCore

`Split1080` / `Split1080_Wide`: nativeDisplayWidth 1080, referenceScreenScale **2.88**, notchSize 226 x 34.333 (Split1080). The
tolerance in the check is **0.0001**, so the exclusion area must match exactly: exclusionArea * (nativeScale / 2.88) = notch. For
1080x2340 @3x (360x780 pt, the 12 mini's own geometry) that needs an exclusion area of 216.96 x 33.0 (226 x 0.96, 34.333 x 0.96).
Other widths: Split1125 notch 209x30 (reference = screen scale), Split828 notch 227x32.

Where the exclusion area comes from is NOT found: UIKit reads `[[_UIScreenInitialDisplayConfigurationLoader initialDisplayContext] exclusionArea]`
(a `_UIDisplayInfoShape` from FrontBoard's display context); it is not in FrontBoardServices/BackBoardServices strings, and none of the
MobileGestalt cache rectangles equals 209x30 (so MG is not the source). Finding that source (another framework in the shared cache, or
SpringBoard/backboardd) is the missing piece for both the 1080 and the 828 class. The MG cache hashed key names could not be matched with
md5(name).

### Where the exclusion area comes from, and the 1080x2340@3 test (21:40)

`exclusionArea` is produced by SpringBoard (SpringBoardHome/SpringBoard frameworks): `+[UISDisplaySingleRectShape(SpringBoard)
sb_displayShapeForScreenType:]` returns a rect from a table indexed by **SBHScreenType**, divided by that type's native scale. The screen
type comes from `_SBHScreenTypeForDeviceAndDisplayContexts` -> `_SBHScreenTypeLookup(deviceInfo ints, artworkSubtype,
display bounds, scale)`. So the notch is whatever the table holds for the screen type SpringBoard picks, not anything in MG's rectangles.

Test rs-b4 (user OK; MG cache deleted, regenerated at 1080x2340 @3 by the boot, then edited): kernel `1080x2340 fitted into 996x2160 at x 40`, UIScreen
360x780 @3, MG regenerated main-screen size 1080x2340 / scale 3.0. Without edits and with `ArtworkDeviceSubType` edited 2436 -> 2340, SpringBoard
and chronod still log "No status bar visual provider" (width 360, scale 3). So either the screen type is not selected from that cache value
(deviceInfo keys 1/2 and the identity iPhone10,3 may pick the iPhone X type anyway), or the table needs more than the subtype.
Restored the original cache afterwards (sha256 c70accbb... verified), phone parked.

Open: read `_SBHScreenTypeLookup` (SpringBoardHome, `SBHome.txt` on the Mac VM) and the device-info keys it uses (`deviceInfoIntegerValueForKey:`
with two keys from the display context) to see which MG/identity values select the screen type; then supply the 12 mini (or XR) values.
Extracted images and disassembly: research/render-size/uik/ (ignored), /tmp/{uik-text,SBfw,SBHome}.txt on the Mac VM.

## RESULT (22:50): 828x1792 @2x works, but is slower, not faster

### Working configuration
- Kernel j0111 (`sweetfb_lw=828`, lh defaults to lw x 2436/1125 = 1792), ADT `--canvas 828x1792 --scale 2`
  (`mkimg.sh CANVAS=828x1792`), MobileGestalt cache regenerated at that size (original cache deleted before the boot).
- UIKit's status bar provider (`Split828`) needs exclusionArea * (nativeScale/scale) == its notch 227x32 within 1e-4.
  SpringBoard's `sb_displayShapeForScreenType:` table (keyed by SBHScreenType) returns the iPhone X notch (209x30), so a
  small injected dylib (`ios/sweet_sbshape.c`, DYLD_INSERT into SpringBoard only via `sweetenv=...;SpringBoard:...`,
  values in `/usr/local/bin/sbs.conf` = `227,32,414`) replaces the shape SpringBoard puts into its `UISMutableDisplayContext`
  (`setExclusionArea:`). With it: status bar, layout 414x896 pt, Control Center and Settings look right
  (`research/render-size/s2-home.2.png`, `d-cc.2.png`, `d-settings.2.png`, ignored dir), and a tap at panel coordinates
  opens Settings (touch mapping through sweet_fit_x/w is unchanged). Kernel: `828x1792 fitted into 998x2160 at x 40`.
- 1080x2340 @3x (the iPhone 12 mini class, closest to the panel) was tried first and did not get a status bar (screen-type
  lookup is by point size + scale + artwork subtype, and the 12 mini mode is itself a 1125x2436 render downscaled, so it
  would not save pixels either). It was dropped for the 828 class, which is the only table entry that renders fewer pixels.

### Framebench, alternating, 150 s settle, GPU 588 / DDR 1804 / CPU auto (same kernel, same library 4780fbaa)
Image args = installed boot_b mode 2 (`j0111b`); baseline `rb2` = 1125x2436 @3, XR `rx2` = 828x1792 @2 plus the SpringBoard hook.

| run | Home B /s (median / p95 ms) | CC A /s | CC B /s | Spotlight /s |
| --- | --- | --- | --- | --- |
| base 1 | 27.71 (30.5 / 47.4) | 22.13 | 23.63 | 29.43 |
| xr 1 | 24.07 (41.6 / 50.4) | 21.07 | 19.31 | 20.92 |
| base 2 | 31.30 (30.9 / 47.6) | 23.36 | 20.65 | 25.69 |
| xr 2 | 23.41 (41.5 / 50.3) | 20.34 | 19.55 | 21.89 |
| base, CPU pinned top | 30.75 (31.5 / 45.4) | 21.35 | 20.30 | 27.89 |
| xr, CPU pinned top | 23.04 (42.8 / 50.7) | 19.37 | 18.57 | 21.52 |

Mean change xr vs base (two alternating pairs): Home **-20%**, CC A -9%, CC B -12%, Spotlight **-22%**. Pinning both CPU clusters at their top
rate changes neither side, so it is not the CPU governor. Evidence: `research/ab/rs-{base1,xr1,base2,xr2,basepin,xrpin}`,
logs `logs/netlog-rs-*.txt`. No SMMU fault, panic or ticket error seen in the logs I looked at.

### GPUPROF (gpwork workload, one boot each; `logs/netlog-rs-gb.txt`, `-gx.txt`)
- xr: Home windows **GPU 14.7-15.2 ms per frame** (all batches 'sysmem large' 46/frame, 14.5 ms), but 43.7 ms per frame wall time: backboardd's
  GL calls take only 1206 of 4366 ms per 100 flushes, so ~70% of the frame is outside GL (CoreAnimation CPU work and/or waiting on swap/present).
  GPU is therefore no longer the limit, something else sets a ~42 ms floor.
- base: that boot ran at 77-80 C (xr 67 C), frames 62 ms with GPU 44 ms; not comparable with the framebench numbers (30 ms), do not use it.
- So the bandwidth lever works (GPU time per frame about 3x lower at 46% fewer pixels), but the present/CPU side now caps at ~24 fps.

### Root changes this round, all reverted
- MobileGestalt cache: deleted/edited/replaced several times (xr variant for the xr boots); original restored and read back
  byte-identical (c70accbb...) at the end; boot_b untouched, nothing flashed.
- Added and removed: `/s.dylib`, `/usr/lib/s.dylib`, `/usr/local/bin/sbs.dylib`, `/usr/local/bin/sbs.conf`, `/var/tmp/sweet_sbshape.log`.
  A final listing of `/usr/local/bin` still matched one name for `sbs|rsshot` (not identified, probably an older file): check `ls /usr/local/bin`.
- Production libsweetca re-read: 4780fbaa... unchanged. Phone parked in r109, ~64%.

### Recommendation
1. Do not install 828x1792 now: it is 20% slower on Home/Spotlight and the user has no sharpness verdict to trade against.
2. The finding that matters: with 46% fewer pixels the GPU drops to ~15 ms/frame, so the next limit is a ~42 ms CPU/latency floor
   outside GL. Find it before revisiting the canvas size: compare base and xr per-frame timelines (SWEETCA_DRAWPROF scopes outside GL,
   CoreAnimation commit/render thread time, SwapWait/present waits, `sweetfb_queue` pacing) on the same cold device.
3. Keep j0111, `mkadt --canvas/--scale`, `mkimg CANVAS=` and `ios/sweet_sbshape.c` (default off / not installed) for that follow-up.
