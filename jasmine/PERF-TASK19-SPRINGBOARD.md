# Task 19: what SpringBoard's main thread does per frame (2026-10-31)

Question: SpringBoard's main thread was ~15 ms per Home frame and ~20 ms on the slow third of Control Center (CC)
frames (task 28), which caps Home (~57 swaps/s) and the slow CC frames. What is that time, and which part is our
port's fault?

**Answer.** About 95 % of it is genuine UIKit / ControlCenterUI / CoreAnimation work on one Gold core at 2208 MHz:
gesture handling, spring animations, blur-material weighting, layout and the CA commit. Three costs are the port's:

1. **The port's polling kernel threads run on Gold** (modem watch and USB device every 1 ms, command port, live log,
   Wi-Fi net poll, PMIC keys): ~70 ms/s of Gold CPU during motion, preempting the UI while Silver idles. Kernel j0120
   moves them to Silver (`pollE 1`): Home **+5-6 %** in both test boots, CC +0-8 %, Spotlight within spread.
2. **Home-screen icon parallax starts CoreMotion for motion sensors the port does not have** (HID page 0xff0c). CoreMotion
   retries, gives up with a FAULT log, and every fault makes libtrace run all of SpringBoard's state-capture handlers:
   0.25-1.3 s of SpringBoard CPU per dump, partly on the main thread, in most framebench runs.
   `sweet_sbshape` (the port's SpringBoard injection) can report motion effects as unsupported (`sbs-noparallax`).
   Result: see "Parallax" below.
3. The kernel still draws every console line into the boot framebuffer that nobody sees after the UI starts
   (~14 ms/s CPU across threads during CC). j0120 can switch it off (`fbcon 0`); no measurable frame gain.

Also found: the profiler's census thread itself preempted SpringBoard on Gold, so the earlier "runnable" numbers
(4-5 ms per frame) were mostly a measurement artifact (j0120: census on Silver; the real figure is 1.1-1.3 ms).

## Method

- Installed system (boot_b j0119on, libsweetca bb3a7a9e, DDR 1804, GPU 588, CPU DVFS auto), plain boot 17:22, one
  framebench capture 17:26-17:28 with the new `--sample-b` option (CPU samples in home-b and control-b too; home-a has
  never produced frames in any capture, so Home had no samples before). Capture `research/ab/t19-cap1`.
- New scripts in `research/t19/` (WSL, repo root, same symbolizer as framebench): `sbprof.py` (one thread's states,
  inclusive/self, kernel entry, waits), `slowframes.py` / `slowprof.py` (per swap interval: SpringBoard / render
  thread / gdrv0 time, profile of the slowest quartile), `cpuocc.py`, `silver.py`, `kthreads.py`, `runq.py`,
  `runkind.py` (runnable census samples: woken vs preempted), `kfunc.py`, `leafk.py`, `under.py`, `osstate.py`,
  `faultlog.py`, `faultaddr.py`, `dscxref.py` (string/call xrefs in the shared cache).
- Test rounds: temporary boots of kernel j0120 (`shim/out/shim-boot-j0120-t19.img`, installed command line minus
  abmark, production library), settings switched at runtime over the command port, framebench per round
  (`research/t19/abba.sh`).

## SpringBoard's main thread per frame (installed system, `t19-cap1`)

| | Home B (57.7/s) | CC A (40.6/s) |
| --- | ---: | ---: |
| On CPU, ms per frame | 12.7 (693 ms/s) | 9.8 (394 ms/s) |
| Waiting (run loop idle) | 3.6 | 13.6 |
| Runnable (census on Gold, mostly artifact) | 5.2 | 4.2 |
| CPU | Gold only (XNU CPU 0-3) | Gold only |

Home, inclusive ms per frame on CPU (12.7):

| What | ms |
| --- | ---: |
| Touch events -> gesture recognizers -> `SBHomeScreenOverlayController setPresentationProgress:` (the overscroll page / App Library overlay) | 3.4 |
| of which `MTMaterialView setWeighting:` (blur material: backdrop filter values per frame) | 2.3 |
| Root folder overscroll handling (`SBIconController ... didOverscrollOnLastPageByAmount:`) | 1.8 |
| Main dispatch queue: `os_state` capture handlers (the parallax fault, below) | 1.55 |
| CA commit (`CA::Transaction::commit`, run-loop observer and explicit) | 1.4 |
| Layout (`layoutSublayersOfLayer:`) | 0.9 |
| Leaf code by image: libobjc 3.2, CoreFoundation 2.8, UIKitCore 1.6, malloc 0.8, QuartzCore 0.8 | |
| Syscalls (Mach messages to backboardd, kevent) | 0.95 |

The waits are the run loop's own `mach_msg` (next event). No XPC timeouts, retry loops, lock waits or slow kernel
paths on the main thread: synchronous XPC 0.18 ms per CC frame, logging (NSLog/os_log) ~0.6 ms per slow CC frame.

### Slow frames are SpringBoard frames

Per swap interval, quartiles by length (`slowframes.py`):

| | Frame | SpringBoard main | Render thread busy | gdrv0 |
| --- | ---: | ---: | ---: | ---: |
| CC A, fastest 25 % | 16.9 ms | 5.1 (30 %) | 89 % | 67 % |
| CC A, middle 50 % | 22.4 | 6.8 (30 %) | 85 % | 69 % |
| CC A, slowest 25 % | 34.4 | 19.1 (56 %) | **66 %** | 55 % |
| Home B, slowest 25 % | 22.3 | 18.3 (82 %) | 57 % | 47 % |

In the slow CC frames the render thread idles a third of the frame waiting for SpringBoard's commit. Those 19 ms
(`slowprof.py`): the CC pull gesture 8.7 (`_updatePresentationForTransitionState` 6.8, of which the module spring
animations 6.0), CA commit 4.4, layout 3.1, the start of each pull (`beginPresentation`, modules' `viewWillAppear`,
`MRUNowPlayingViewController setOnScreen`) 2.9. All Apple code doing its normal job; nothing waits on the port.

## Port cost 1: polling kernel threads on Gold (kernel j0120, `pollE`)

kernel_task threads on CPU during CC (`kthreads.py`, installed capture): `topaz_modem_thread` 31.5 ms/s (modem
watch, `IOSleep(1)` loop), `dvfs_worker` 27 (PMIC rail read-back every 20 ms; task 2's code, left alone), AppleCLCD
presenter 23 (display, needed), `ud_thread` 18.5 (USB device, 1 ms poll), census 11 (profiler), `ud_cmd_thread` 10,
`nvt_thread` 7 (touch), `pmic_keys_thread` 3, `net_thread` 2.5. All on Gold: kernel threads prefer the P cluster,
and at kernel priority they preempt SpringBoard and the render thread while Silver is 70-99 % idle.

`xnu/patches/j0120-jasmine-poll-threads-on-silver.patch`: `sweet_thread_to_e()` soft-binds the calling thread to the
E cluster (`thread_bind_cluster_type(..., 'E', soft)`) once Silver is online; each polling loop calls it per
iteration (one load and compare). Switch: boot-arg `sweetpollE=1` or `pollE 1|0` on the command port (threads bind or
unbind on their next poll). Default off. The profiler's census thread is always bound to Silver (measurement only).
Same patch: `fbcon 0|1` on the command port sets `sweet_console_muted` (cost 3).

Two test boots of j0120, framebench swap arrivals/s (`research/ab/t19x-*`):

| Boot, round | Home B | CC A | CC B | Spotlight | Gold load in CC A (ms/s) |
| --- | ---: | ---: | ---: | ---: | ---: |
| 1 (17:38) a1 off | 41.70 | 39.53 | 37.52 | 34.41 | 2150 |
| 1 b1 both on | 44.37 | 42.97 | 41.12 | 33.52 | 1815 |
| 1 b2 both on | 44.61 | 41.20 | 39.23 | 35.01 | 1809 |
| 1 a2 off | 42.05 | 39.36 | 36.64 | 33.29 | 1944 |
| 2 (17:50) b1 both on | 47.12 | 40.76 | 43.14 | 35.13 | 1930 |
| 2 a1 off | 45.21 | 42.20 | 42.23 | 36.80 | 2049 |
| 2 p1 pollE only | 46.96 | 43.32 | 40.77 | 32.72 | 1868 |
| 2 f1 fbcon off only | 44.44 | 38.46 | 37.07 | 32.88 | 2050 |
| 2 f2 fbcon off only | 44.75 | 41.96 | 40.68 | 32.60 | 2045 |
| 2 p2 pollE only | 46.54 | 40.81 | 38.99 | 33.22 | 1856 |
| 2 a2 off | 43.38 | 39.38 | 37.55 | 32.75 | 1993 |
| 2 b2 both on | 45.66 | 41.30 | 40.82 | 32.88 | 1900 |

- **Home**: every round with the pollers on Silver (b, p: 44.4-47.1) is above every round without in the same boot
  (a, f: 41.7-45.2); means +6 % (boot 1) and +5 % (boot 2); `p` alone gives it, `f` alone does not.
- **CC**: boot 1 +7 % (A) / +8 % (B), both B rounds above both A; boot 2 within spread (A +0.5 %, B +5 %).
- **Spotlight**: within spread. Gold load in CC A falls ~150-200 ms/s; SpringBoard's real runnable time per CC frame
  1.1-1.25 ms -> 0.34-0.37 ms.
- 0 faults / panics in both boots; the threads report `SWEET POLL: thread N soft-bound to the E cluster, now on cpu 4/5`.
- Boot-to-boot level differs a lot (Home 42-45 here vs 57.7 on the installed boot), so only same-boot comparisons count.

## Port cost 2: parallax -> CoreMotion fault -> SpringBoard state dumps

`osstate.py` on the installed capture: SpringBoard ran `os_state_request_for_self` handlers in two bursts during
home-b (0.14-1.47 s and 2.24-3.10 s; 672 samples = 1.3 s of CPU, 185 of them on the main thread via
`dispatch_async_and_wait` to the main queue: `FBScene`, `SBFTraitsParticipant`, `SBHUDController`, wallpaper ...
`description`s and plist encoding). The j0120 rounds show the same in spotlight-first (~250 ms per run) and home-a
(~400 ms) of most captures.

Trigger chain (shared cache, `faultaddr.py`, `dscxref.py`, `ipsw dyld disass/dump`):

- `__os_log_impl_flatten_and_send` -> `_os_state_request_for_self`: a FAULT-level log makes libtrace capture the
  process's state.
- The faulting log is CoreMotion `CLIoHidInterface::applyAllDirtyDeviceProperties` (call at 0x1919b5180, type 0x11):
  "[CLIoHidInterface] Could not set all properties after too many retries. Giving up." Its sibling logs:
  "Service for device with usage pair {%d, %d} is not ready"; `addDevice` is called with usage page 0xff0c (Apple
  vendor motion: accelerometer/gyro). The port has no motion sensor service.
- CoreMotion is started by `SBRootFolderView _updateParallaxSettings` -> `UIView addMotionEffect:` ->
  `_UIMotionEffectCoreMotionEventProvider startGeneratingEvents`: the Home-screen icon parallax, re-enabled whenever
  the Home screen becomes visible again (after Spotlight, overlays, CC).
- UIKit decides "motion effects supported" from MobileGestalt `UIParallaxCapability` (`____UIMotionEffectsAreSupported_block_invoke`,
  plus an enable-only default `UIMotionEffectsEnabled`). On jasmine parallax can never move anything (no sensor
  data), so turning it off changes nothing visible.

Fix (default off): `ios/sweet_sbshape.c` (SpringBoard's injected `/s.dylib`) with `/usr/local/bin/sbs-noparallax`
present returns NO from `+[_UIMotionEffectEngine _motionEffectsSupported]` and `+[UIView _motionEffectsSupported]`.
`tools/mesa-local.sh` now builds it as a dylib (`xnu/out-ios-TAG/sweet_sbshape.dylib`; the ios-tools loop had been
compiling it as an executable, which never linked). The system-wide version would be `UIParallaxCapability` = false
in the MobileGestalt cache, but that key lives in the binary CacheData blob whose layout is not mapped (task 25 notes).

Test (`research/t19/mtest.sh`, image `shim-boot-j0120-t19m.img`: SpringBoard loads `/t.dylib` = this build, so the
production `/s.dylib` was not touched; all rounds `pollE 1` + `fbcon 0`; the switch file is set before each boot).
The dumps only start from the second framebench run of a boot (CoreMotion keeps retrying for a few minutes before its
first give-up), so one run per boot (round m1, 18:14-18:35) saw none either way. Round m2: one boot each, three runs:

| Boot (m2) | Run | SpringBoard state-dump samples (sampled phases) | Home B | CC A | CC B | Spotlight |
| --- | ---: | --- | ---: | ---: | ---: | ---: |
| a: parallax as installed (18:37) | 1 | 0 | 43.6 | 38.2 | 38.7 | 34.6 |
| | 2 | 259 (spotlight-first 111, home-a 148) | 42.4 | 42.1 | 38.8 | 32.5 |
| | 3 | 127 | 41.5 | 39.1 | 39.6 | 32.5 |
| b: `sbs-noparallax` (18:46) | 1 | 0 | 57.3 | 47.5 | 42.5 | 44.0 |
| | 2 | 0 | 55.0 | 46.1 | 41.8 | 37.4 |
| | 3 | 0 | 53.9 | 44.9 | 41.5 | 38.2 |

- With the switch the dumps are gone (0 in 3 runs; parallax on: 2 of 3 runs, and in s1/s2 rounds 2-4 of every boot,
  and in the installed capture). The hook logs "motion effects reported unsupported (no motion sensors)".
- The b boot is faster in every phase, but boot-to-boot spread is that large (round m1: Home 43.4 / 54.7 / 50.7 / 58.0
  for a / b / b / a), so **no frame-rate gain is claimed**; what is shown is that 0.25-1.3 s CPU bursts in SpringBoard,
  partly on its main thread, no longer happen. Worst no-update gaps did not change measurably (they come from other
  hitches as well).
- Screens identical (Home dumps `research/t19/m2/home-a1.png`, `home-b1.png`), 0 faults / panics, no SpringBoard crash.

## Port cost 3: the console drawn into the boot framebuffer (`fbcon`)

`_cnputs` -> `fbcon_transmit_data` draws each character (512 pixel stores) and clears two text rows per newline into
the boot framebuffer, which is not scanned out once CoreAnimation presents. During CC ~14 ms/s of CPU across threads:
libsweetca's report writer, SpringBoard's AppleKeyStore lock-state queries (`SWEET AKS: SpringBoard sel 17`, IOLog
per call), SpringBoard's NSLog "trying to set state of nil layer." (MRU glyph, ~14 per CC open), HID touch logs.
The boot-arg `sweetfb_noconsole=1` already mutes it after the first UI frame but is not set (no room in the 607-byte
command line). j0120 `fbcon 0`: rounds f1/f2 vs a1/a2 show no frame-rate change. CPU and power only.

## Where SpringBoard's time goes, in short

| Home frame, SpringBoard main (installed) | ms |
| --- | ---: |
| Genuine UIKit/SpringBoard/CA work | ~11 |
| Fault-triggered state dumps (average; bursts of 0.25-1.3 s) | 1.55 |
| Preempted by Gold polling threads (real runnable) | ~1 |
| Idle | 3.6 |

What remains is CPU work of iOS 16's own code on an A73 at 2208 MHz. Home already runs 57.7 of 60 swaps/s on the
installed boot; the slow CC frames need ~19 ms of SpringBoard CPU. Only a faster core (task 2's clock range is
exhausted at 2208) or less UI work would cut it. CPU DVFS limits are tasks 2/13 and were not touched.

Not port-caused / not changed: the two AppleKeyStore log lines and NSLog per CC open (negligible once the console is
not drawn), `dvfs_worker`'s PMIC read-back (27 ms/s on Gold; task 2 follow-up), the glthread worker already on Silver.

## Installed (2026-10-31 19:02, user: "Install it")

- boot_b = `shim/out/shim-boot-j0120on-slotb.img` (SHA256 bf33a55f...; kernel `xnu/out-jasmine-j0120on`, polling threads on
  Silver by default, `sweetpollE=0` or `pollE 0` turns it off; command line byte-identical to j0119on's). Flashed 19:02.
  Rollback: `fastboot flash boot_b shim/out/shim-boot-j0119on-slotb.img`.
- `/s.dylib` = `xnu/out-ios-t19/sweet_sbshape.dylib` (d18be426...) + `/usr/local/bin/sbs-noparallax`. Backup of the previous
  3fa51848...: phone `/usr/local/bin/s-pre-t19.dylib`, local `research/t19/install/s-pre-t19.dylib` (ignored). Rollback: remove
  `sbs-noparallax` (behaviour as before) or copy the backup back; reboot. The console stays drawn (`fbcon` not changed).
- Plain reboot (`research/t19/install.sh`, log `logs/netlog-t19-installed.txt`): abmark=b, glthread on, 7 `SWEET POLL` threads on
  CPUs 4-7, sbshape log "motion effects reported unsupported", 0 faults / panics / ticket errors / SpringBoard crashes, Home screen
  normal (`research/t19/install/home.png`). framebench `research/ab/t19-installed` (first run after boot): Home B 46.9/s, CC A 39.7,
  CC B 42.1, Spotlight 36.3. This boot sits in the lower part of the boot-to-boot range seen today (Home 41-58); the measured gain is
  the same-boot ABBA above, not this single capture. Phone left in iOS for the user's own look.

## Files

- `xnu/patches/j0120-jasmine-poll-threads-on-silver.patch` (now default on); VM builds `xnu/out-jasmine-j0120` (17:33, tests,
  default off) and `xnu/out-jasmine-j0120on` (18:59, installed).
- `ios/sweet_sbshape.c` (no-parallax switch), `tools/mesa-local.sh` (builds it); VM build `xnu/out-ios-t19`.
- `tools/g2/framebench.py --sample-b`.
- Images `shim/out/shim-boot-j0120-t19.img` (production SpringBoard lib) and `-t19m.img` (SpringBoard loads `/t.dylib`),
  `research/t19/mkimg.sh`.
- Captures `research/ab/t19-cap1`, `t19x-s1-*`, `t19x-s2-*`, `t19m-*`; logs `logs/netlog-t19-*`.
