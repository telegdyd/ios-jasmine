# Task 5, step 1: Mesa draw-path diagnostics (2026-10-24)

Task 5 remains a strong performance target. The clearest new lead is **batch churn
caused by texture barriers and resource dependencies**: most finalized batches
contain a single draw, repeatedly paying batch setup and state emission costs.
Warmed program-cache lookups all hit; shader compilation and client uploads are
not the main steady-motion cost in these runs. No optimization was made in this step.

This follows the [whole-system baseline](PERF-BASELINE-20261024.md). Its independent
CPU samples put Mesa/wrapper plus support calls at about 63–66% of the display
thread's CPU work. The old 14.6 ms/frame figure in PERF-TASKS.md predates several
fixes and should not be used as a current saving estimate.

## Build and measurement

- Diagnostics commit: `8a3ed2b`; [Mesa CI 40051205502](https://github.com/telegdyd/ios-jasmine/actions/runs/40051205502)
  passed. Mesa 26.2.5, Darwin patch 0001 plus draw diagnostics patch 0002.
- Diagnostic library SHA256:
  `7df9e5224e25d87da68a2a1adb732291f8ebfbe1a0be8ab992d94b598447e5fd`.
  Installed separately as `/usr/local/bin/libsweetca-t5diag.dylib`; production
  `/usr/local/bin/libsweetca.dylib` was left unchanged.
- Existing j69b kernel, CI `40040874776`, four Gold cores at 1747 MHz, measured
  GPU 587–588 MHz and DDR 1294–1296 MHz. Temporary RAM boots, no partition flash.
- Profiling-on image booted at 03:55:13; profiling-off image at 04:04:33.
  Both use the same kernel/library and `sweetfps=1`; only `SWEETCA_DRAWPROF=1|0`
  differs. Test images: `shim/out/shim-boot-j69b-t5on.img` and `…-t5off.img`.
- Each boot gets a ten-second home warmup, then two approximately 30-second home
  swipe windows and two Control Center open/close windows. The first window of
  each workload also captures six seconds of CPU samples (1 ms) and thread-state
  census (2 ms). Profile downloads happen after motion finishes.
- Reports cover 100 GL flushes. Discard the first complete report in each sliced
  workload, which can include earlier activity; select moving windows with more
  than 1000 ms of GL elapsed time per report. On: 18 home reports (1800 flushes),
  nine Control Center reports (900 flushes). Off: 17 home reports (1700 flushes),
  eight Control Center reports (800 flushes). Four six-second profiles total
  227,328 records, zero dropped.

Raw logs, binary profiles, matching symbols, workload scripts and generated
summaries are ignored under `research/t5/`. `tools/g2/drawsum.py` summarizes the
new counters, for example:

```sh
python tools/g2/drawsum.py research/t5/on-home-a-motion.txt --drop-first
```

## What the counters show

Counts below are per GL flush, **not per displayed frame**. A batch is Mesa's
render-target work unit; several batches can share one kernel submission. Batch
histograms count actual finalizations, excluding already-flushed early returns.
Flush reasons use the nearest instrumented cause in the active call stack.

| Counter | Home swipes | Control Center |
| --- | ---: | ---: |
| GL draw-wrapper calls / flush | 72.8 | 181.5 |
| Actual finalized batches / flush | 54.5 | 107.6 |
| Batches containing exactly one draw | **80.3%** | **76.3%** |
| Batch finalizations attributed to texture barriers | **74.5%** | **59.7%** |
| Attributed to resource dependencies | 18.8% | 32.0% |
| Kernel submissions / flush | 3.24 | 6.65 |
| Program-cache hit rate | 100% | 100% |
| Upload bytes requested / flush | 74.0 kB | 573.4 kB |

No new shader variants were observed in these selected warmed windows. The
earlier baseline's first-Spotlight compilation pause is a separate cold-path
issue; these results do not rule it out.

The nested timers measure **elapsed time, including blocking and descheduling**.
Inclusive scopes overlap; exclusive time subtracts instrumented child scopes,
but still includes uninstrumented work and pauses. Worker-thread scopes can
complete across report boundaries. Aggregate several windows; do not add
inclusive rows or label the remainder after fence waits as CPU time.

| Selected stage, elapsed ms / GL flush | Home | Control Center |
| --- | ---: | ---: |
| All GL wrappers, existing profiler | 25.09 | 41.05 |
| Explicit kernel fence wait | 3.24 | 0.59 |
| Submission build + kernel call, inclusive | 5.81 | 4.10 |
| Batch creation, exclusive | **1.77** | **3.95** |
| Batch finalization, exclusive | **1.85** | **4.09** |
| Context flush, exclusive | 1.54 | 3.39 |
| State-tracker draw preparation, exclusive | 1.91 | 4.45 |
| a5xx state emission, inclusive (includes program emission) | 2.45 | 5.14 |
| a5xx program emission, exclusive | 1.45 | 2.99 |
| Mesa state validation, exclusive | 0.53 | 1.16 |
| Program-cache lookup, exclusive | 0.15 | 0.34 |
| Upload-data operation, inclusive | 0.15 | 0.58 |
| Wrapper uniform update, exclusive | 0.09 | 0.16 |

Texture-barrier preparation itself takes 2.77 / 5.45 ms inclusive per flush;
much of that is the nested flush work above. Periodic kicks also include
submission work and waits, so their inclusive time is not an isolated CPU cost.
The submit call can block on scanout-surface reuse; fence-wait time alone does
not capture all synchronization. Rendering/presentation overlap remains the
separate task 16.

## Profiling overhead and validation

| Same-workload comparison | Home on / off | Control Center on / off |
| --- | ---: | ---: |
| GL elapsed ms / flush | 25.09 / 24.88 | 41.05 / 39.08 |
| Draw-wrapper calls / flush | 72.8 / 73.5 | 181.5 / 180.9 |
| Swap arrivals / second | 30.83 / 31.03 | 18.19 / 18.94 |
| Display-thread CPU ms / second, six-second sample | 770 / 770 | 892 / 892 |

The on/off GL elapsed difference is about +0.9% home and +5.1% Control Center;
swap-arrival throughput is about 0.7% / 4.0% lower with counters on. This is an
overhead check with two repeats per workload, not a precise overhead calibration:
the on boot preceded the off boot, background activity and temperatures vary,
and report windows do not contain identical animation states. The profiler's
`sweet_profile_leave` itself samples at about 0.5% of the display thread's CPU,
which is only part of its overhead. Treat the stage timings as approximate and
confirm any later optimization with diagnostics off.

The independent CPU census is consistent across both boots: home uses about
77% of one core on the display thread, Control Center about 89%. The off samples
attribute about 504 / 585 ms/s to Mesa/wrapper user code plus its support-library
calls (roughly 65.5% of display-thread CPU in each workload). This confirms that
the added timer output has not changed the broad CPU bottleneck diagnosis.
These exact six-second gesture phases differ from the earlier baseline, so the
higher Control Center utilization is not evidence of a regression.

All 13 modified Mesa translation units passed host syntax checks. The profiler
passed nested-scope/early-return accounting, exclusive-time bounds, four-thread
counter aggregation and disabled-mode checks with a host Mach-clock shim. Both
patches applied in order to a clean Mesa worktree; the CI library built successfully.

Five of six `sweetgpu_gltest` cases passed. Its IOSurface render-target case
failed with zero row stride in **both the diagnostic and exact task-4 baseline
test binaries**. The older installed test passes. Source inspection found a
pre-existing test-helper bug: `sgl_surface_create_iosurface()` supplies the
`bytes_per_row` and `offset` arguments to `sgl_import_iosurface()` in reverse
order. CoreAnimation does not use that helper. It is recorded separately and
was not changed in this measurement step.

## Next experiment and revised importance

Task 5 still deserves the next optimization pass. Start by explaining and
reducing unnecessary barrier-driven batch breaks, then remeasure batch count,
state emission, display-thread CPU and actual swap/latch intervals. The data
supports a repeated-cost problem more strongly than a shader-cache or upload
problem. It does **not** show that every barrier is unnecessary, or that all
batch setup time can be removed.

One source-level hypothesis to test: `draw_prep()` checks bound framebuffer
textures, including the reserved framebuffer-fetch unit; stale bindings might
request a barrier even when the current program does not sample that texture.
Trace active program sampler use and the exact producer/consumer dependency
before suppressing any barrier. Keep framebuffer-fetch ordering, blur,
offscreen passes and scanout-surface reuse correct. Validate rendered output
and obtain the user's visual check for a later behavioral change.

There is no defensible new removable-ms/frame estimate yet. The stage costs
above are an opportunity to investigate, not an additive saving forecast.
`SWEET FPS` counts swap arrivals; it does not prove distinct frames latched or
measure input-to-display latency. Task 5 step 1 is diagnostics; the overall
task remains open until a measured improvement is installed and validated.

At the end the phone was returned to the r109 charging console via temporary
`fastboot boot shim/out/nura-r109-boot_a.img`. At approximately 04:10 the battery
reported Charging, +709960 µA, 3983144 µV, 58%, with backlight 0 and charge voltage
set to 3950000. Task-owned collectors stopped; phone lock released.
