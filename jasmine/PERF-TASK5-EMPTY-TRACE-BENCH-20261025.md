# Empty-trace optimization: device benchmark, 2026-10-25

**No meaningful overall frame-time improvement was demonstrated.** The targeted
trace-worker overhead disappeared from the sampled display-thread stacks, but
Home/Control Center throughput changed by only about 1–2%, median intervals did
not improve, and repeated Spotlight was slower in this pass. This is a validated
removal of unnecessary work, not a demonstrated smoothness win.

The user authorized this new-build benchmark explicitly after the earlier offline
work. Ran the standard framebench once. No Wallpaper workload, clock sweep,
automatic benchmark retry or repeated test-boot loop.

## Build, installation and checks

* Implementation `0624366`, Mesa CI `40163837008` passed; previous handoff
  `af758b7`. [Source reasoning and build validation](PERF-TASK5-EMPTY-TRACE-20261025.md).
* Installed `xnu/out-mesa-t5empty-trace/libsweetca.dylib` as production
  `/usr/local/bin/libsweetca.dylib`, mode 0755. Retrieved it again and verified
  SHA256 `cfa9fd9c56305ed82b63f9d21b0134faf8b3ad661cf4d0d34ef6bf2e5bc8c0ea`.
* Previous production library was backed up and verified against baseline SHA256
  `e5fc84b1066990dbb06a6816ad5421978d84fcd2aa7c6f49d477594516847b1c`.
* New CI build's `sweetgpu_gltest` passed **all seven steps**, including nine
  active-sampler assertions and IOSurface render/readback/texture checks.
* Home swap-surface screenshot visually matched the expected Home layout before
  capture. No kernel panic or nonzero GPU hardware fault observed in the log.
* Current required plugins retained; no plugin, CPU/GPU/DDR clock, voltage or
  root-image changes applied. No CPU-versus-RAM bandwidth conclusion from this run.

Setup needed a temporary iOS boot to transfer the library from the charging
console, then one restart into the measurement boot to load the new production
library. Both used the same `shim/out/shim-boot-framebench99.img` as the baseline;
no partitions flashed. One final temporary r109 boot returns the phone to its
standing charging-console state. These are setup/parking, not benchmark retries.

## Comparable workload and results

Compared against `research/framebench/20261025-first/capture/`, the current
plugin-enabled active-sampler baseline, not earlier disabled-plugin benchmarks.
Same standard host schedule, kernel/image/arguments and configured clocks:
four Gold cores at 1747 MHz, GPU 588 MHz, DDR about 1296 MHz with scaling off.
Both captures began 145 seconds after their measurement boot. Same primary CPU
sampling period 2 ms and census period 5 ms. Current raw data is ignored under
`research/framebench/20261025-empty-trace/` (`capture/`, `comparison.json`,
`task5-stacks.json`, `gltest.txt`, boot/setup/parking logs and exact libraries).

New activity **59.89 s**, total collection/export **66.36 s**; runner exit 0.
6,927,761 bytes exported, 6340 events / 38376 samples / 12830 stacks,
**zero event or sample drops**. Baseline collection/export was 66.28 s.

These are **swap-arrival rates and intervals**, not confirmed displayed FPS or
physical touch-to-display latency. Lower intervals are better.

| Segment | Updates/s before → after | Rate change | Median interval before → after | p95 before → after |
| --- | ---: | ---: | ---: | ---: |
| Home B | 20.34 → 20.63 | +1.4% | 48.90 → 49.30 ms | 54.50 → 53.43 ms |
| Control Center A | 14.13 → 14.49 | +2.5% | 70.01 → 70.87 ms | 86.91 → 86.19 ms |
| Control Center B | 13.97 → 14.07 | +0.7% | 70.90 → 73.00 ms | 85.65 → 88.61 ms |
| Repeated Spotlight | 22.92 → 13.73 | −40.1% | 47.04 → 63.40 ms | 71.50 → 73.37 ms |

Combined Control Center rate: **14.05 → 14.28 updates/s (+1.6%)**. The tiny rate
changes do not consistently agree with median/p95 improvements and cannot be
separated from run variation in this single before/after comparison.

Home A remains unverified: zero baseline arrivals, one new arrival during about
9.6 s of commanded motion. Exclude it from comparisons. Spotlight windows are
only about 1.6 s each; the repeated window's worst boundary-inclusive no-update
interval grew from 84 to 331 ms. Record this slowdown; there is insufficient
evidence here to establish whether it is a reproducible regression or a transient
startup/producer delay. It prevents describing the round as a clear net win.

## Did the intended change work?

Yes, the targeted calls disappeared from the current Control Center A primary
display thread's on-CPU sample. Same 4 s window and 2 ms sample weight:

| Inclusive path | Baseline samples / estimated ms | New samples / estimated ms |
| --- | ---: | ---: |
| `u_trace_context_process` | 65 / 130 | 0 / 0 |
| `u_trace_flush` | 8 / 16 | 0 / 0 |

New `u_trace_has_points` has one / 2 ms sampled observation. Missing samples are
not proof of zero instruction cost; the source/compiled guard and changed stacks
together support removal of empty trace jobs. Inclusive rows are not additive
guaranteed savings. Baseline queue-processing samples were mostly kernel wakeups.

Overall primary-render CPU was **3550 → 3526 estimated ms (−0.7%)**. Mesa user CPU
was 2274 → 2314 ms; other kernel CPU 248 → 124 ms. The four-second sample contained
58 → 57 swap arrivals: estimated render CPU per arrival was **61.21 → 61.86 ms**.
This is a sample-window ratio, not an exact displayed-frame cost. Neither overall
CPU nor interval results demonstrate a useful net speedup.

The substantial remaining paths still include draw dispatch, state emission and
batch/fence processing. For example `fd5_emit_state` has 165 → 164 inclusive
samples. That locates cost, not proof that state emission can safely be omitted.
Continue source-backed task-5 work only against a confirmed avoidable cost.

## Comparison limits and final state

This is one new capture against a prior capture, not an interleaved statistical
A/B. Temperatures started higher: baseline sensor range 51.4–60.2 C, new
57.6–66.6 C. Captured clock states agree, but background activity and boot/cache
history differ. Do not infer a large gain, a proven regression, or exclusion of
RAM bandwidth from this result. No further rounds were started.

No saved page waiters or GPU buffer allocation failures in either standard
capture. Display latch observation remains unvalidated; no physical frame-counter
events were captured. New library is left installed, with the old exact library
backed up under the ignored session directory. Diagnostic test/screenshot files
were removed from the phone. Phone parked in r109; charging verification and lock
release are recorded in the active NOTES handoff.
