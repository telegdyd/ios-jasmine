# First framebench device session — 2026-10-25

**Priority: investigate task 20's Wallpaper stability/memory problem first.**
The user reports system freezes, and this session confirms wallpaper-service
crashes/restarts with rapid growth in surface backing and wired memory. The
captured window does **not** prove exhaustion or a leak. For sustained animation,
task 5 remains the strongest measured renderer opportunity. Investigate background
service CPU alongside it, before committing to scheduler or presentation changes.

## What ran

One temporary instrumented iOS boot, one standard capture, and one separate
45-second Settings capture on that same boot. No benchmark retries, partition
flashes, plugin changes, library installation, clock changes or root replacement.
Finished by temporarily booting the r109 charging console under the standing
parking request; charger online/Charging, +658202 uA, 4171376 uV, 85%, backlight
set to zero and float set to 4050000. Charging-shell verification succeeded.

The standard workload began 145 seconds after temporary boot. Home was visually
verified first. Installed `/usr/local/bin/libsweetca.dylib` was retrieved read-only:
SHA256 `e5fc84b1066990dbb06a6816ad5421978d84fcd2aa7c6f49d477594516847b1c`,
matching the supplied symbols. Kernel CI **40160680219** passed. Temporary image
`shim/out/shim-boot-framebench99.img` SHA256
`6ce2603f1b23ca3c9fed827dcb4e4d1115a6b21aaadb9ad854471640fd30281b`.
It preserves the j98 Wi-Fi baseline shim/ADT/arguments: four Gold cores at the
configured 1747 MHz, measured GPU 588 MHz, DDR approximately 1294 MHz. It does not
establish which kernel was running before the user placed the phone in fastboot.

| Capture | Device activity | Collection including export | Export | Events / samples / stacks | Drops |
| --- | ---: | ---: | ---: | --- | ---: |
| Standard | 59.86 s | 66.28 s | 6,929,139 bytes | 6,289 / 40,092 / 12,666 | 0 |
| Settings | 45.36 s | 49.33 s | 4,056,047 bytes | 9,461 / 59,666 / 3,216 | 0 |

Offline symbolication is additional bounded host time. Capture allocation was
15,630,336 bytes; legacy 48 MiB profiler storage was not allocated. Export speed
was sufficient for the short-run design. Both runners exited successfully.

Ignored raw artifacts: `research/framebench/20261025-first/`, with `capture/` and
`wallpaper/` containing reports, manifests, checkpoints and binary records.
`boot.txt` contains the session console, including events after capture ended.
Keep those diagnostics and the retrieved library out of git.

## Standard workload evidence

These are **swap-arrival observations**, not validated displayed FPS. No physical
frame-counter events were captured. Source inspection found the counter mapping
is guarded by `topaz`; jasmine leaves `fIntf1` null. A future SDM660-specific
counter mapping/validation is needed. All 668 standard CTL-clear retirements were
observed clears, with zero 50 ms timeout fallbacks; that alone does not validate
distinct scanout frames.

| Segment | Arrivals/s during commanded motion | Median interval | p95 interval |
| --- | ---: | ---: | ---: |
| First-observed Spotlight | 7.1 | 64.8 ms | 308.5 ms |
| Repeated Spotlight | 22.9 | 47.0 ms | 71.5 ms |
| Home A, CPU sampled | **Unverified: zero arrivals** | — | — |
| Home B | 20.3 | 48.9 ms | 54.5 ms |
| Control Center A, CPU sampled | 14.1 | 70.0 ms | 86.9 ms |
| Control Center B | 14.0 | 70.9 ms | 85.7 ms |

Home A cannot support a Home CPU/FPS or sampling-overhead comparison. The host
report now flags and excludes unresponsive motion segments from task ranking.
Control Center's similar A/B rates are a useful gross check, not a calibrated
overhead bound. Earlier benchmarks used different software/workloads, so these
numbers do not quantify a matched before/after regression.

In Control Center's four-second sampled window, primary display-thread estimates
include **2274 ms Mesa CPU**, 916 ms other CoreAnimation CPU, 248 ms other kernel
CPU, 56 ms cache maintenance and 65 ms GPU-fence waits. These are sampled costs,
not additive frame-time savings. First Spotlight includes about 605 ms of shader
worker wait, supporting task 17 feasibility after the stability investigation.

`trustd` and `accessoryupdater` together account for **22.8% of sampled non-idle CPU**
across usable sampled segments. Their hot stacks/retry activity deserve a task-21
background-service investigation. CPU competition's actual critical-path effect
is not established. Do not disable required plugins based on these totals.

## Wallpaper evidence and limits

Settings capture: entered Wallpaper at approximately 14 s; tapped **Add New
Wallpaper at 35.0 s**, leaving only ten seconds of gallery activity in the capture.
A swap-surface screenshot/readback occurred inside the window to identify the
button, adding observer activity. No wallpaper was selected or applied. The
gallery image itself was not verified: later screenshot attempts timed out and
their retrieved stale image must not be treated as a gallery screenshot.

| Measurement | Start | End |
| --- | ---: | ---: |
| Wired memory | 472.4 MiB | 584.1 MiB |
| Surface requested backing | 289.1 MiB | 394.2 MiB |
| GPU BO mapped bytes | 179.9 MiB | 250.8 MiB |
| GPU pool actual allocation | 163.0 MiB | 147.1 MiB |

These counters overlap; **do not sum them**. Wired memory climbed from 486 to
584 MiB in the final three seconds. PosterBoard restarted once during the capture;
the replacement reached 41.5 MiB footprint, Preferences 30.9 MiB and backboardd
85.9 MiB. The session log records a PosterBoard SIGABRT, repeated AegirPoster
SIGABRTs and extension check-in timeouts. Some occurred after capture ended.
Exception text/cause is not yet established. The log also reports a swap-file
open failure and repeated assetsd crashes, which are investigation leads.

XNU reports **1.97 GiB managed physical memory**. This matches the intentional
upper-bank memory layout in `tools/mkadt.py`; the phone's advertised 4 GB is not
the current XNU-managed amount. Reclaiming lower memory would require separate
carve-out/access validation, not an unreviewed memory-size change.

Minimum free memory was 15.0 MiB in the standard capture and 19.5 MiB in Settings,
but neither capture saw page waiters, GPU buffer allocation failures or frees in
flight at the saved checkpoints. The command service and exports remained alive.
Late sampled primary-display waits were chiefly ordinary run-loop receive,
short GPU fence waits and panel surface protection; no sampled buffer-free
deadlock was established. The manual segment's long no-update interval includes
intentional static-page time and is **not a measured 18-second system freeze**.

Therefore this session does not reproduce/prove the reported full-system memory
freeze. The short post-gallery window cannot establish retention, eventual OOM
or recovery. Follow task 20 by collecting exception/oslog and memorystatus evidence
before opening the gallery, and put the gallery trigger near the beginning of a
bounded memory capture. Attribute surviving surface/cache owners and post-exit
recovery before calling the growth a leak. Keep task 14 as a separate hypothesis.

## Tool corrections after device validation

Host reporting now excludes wireless display-thread waits from primary-render
cost, flags missing physical counters and zero-update motion, and surfaces
substantial background CPU as an investigation lead. Both saved captures were
reanalyzed offline with verified library identity recorded in their manifests.
**28 offline tests pass.** No further kernel build or benchmark run was needed.

Recommended work order for this current root: **20 stability/memory diagnosis**,
then **5 renderer CPU**, with **21 background-service diagnosis** alongside that
work; **17 shader-cache feasibility** addresses first-use hitches. The old task
ranking is not proof against the current plugin-enabled configuration.
