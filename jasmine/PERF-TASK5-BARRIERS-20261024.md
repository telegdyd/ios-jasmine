# Task 5: barriers for active samplers (2026-10-24)

This implements the first optimization identified by the
[draw-path diagnostics](PERF-TASK5-DIAGNOSTICS-20261024.md).

The matched comparison against the exact previously installed task-4 production
library shows a **small observed gain: +3.0% home and +5.4% Control Center swap
arrivals/s**, with correct active-sampler state and no new regression in the
rendering checks. These are arrival rates, not confirmed distinct displayed FPS.

| Net comparison, draw counters disabled | Original production | New library |
| --- | ---: | ---: |
| Home swap arrivals / second | 31.11 | 32.05 |
| Control Center swap arrivals / second | 18.51 | 19.51 |
| Home GL elapsed ms / flush | 24.82 | 24.14 |
| Control Center GL elapsed ms / flush | 40.16 | 37.57 |
| Home display-thread CPU ms/s, six-second sample | 766 | 727 |
| Control Center display-thread CPU ms/s, six-second sample | 895 | 892 |
| Home Mesa/wrapper user + support CPU ms/s | 498 | 448 |
| Control Center Mesa/wrapper user + support CPU ms/s | 589 | 582 |

Both repeats favor the new library. Each variant has two ~30-second windows per
workload; the first includes a six-second kernel sampling capture, the second
is entirely unprofiled. The old production library was read back before the
test and byte-hashes to task 4's artifact:
`8a2defaa9e8974b126014193142754062758a7c38699ee7df8f19cb3506990f3`.
Across the diagnostic baseline, optimized and original-production comparisons,
six six-second CPU profiles contain 340120 records, zero dropped. This is a
same-day sequential comparison with two repeats, not a statistical confidence
bound; background work and animation states still vary.

## Cause and change

`draw_prep()` used to issue a texture barrier whenever the current render-target
texture matched any held 2D texture binding. It checked all 32 units. The reserved
framebuffer-fetch unit stays bound after switching away from a fetch shader, so
that stale binding could split a batch even when the next shader did not read it.
Other unused bindings could do the same.

The wrapper now intersects those matching bindings with Mesa's active graphics
program sampler units. `sgl_sampled_2d_units()` reads the linked programs'
`SamplersUsed`, `SamplerUnits` and `TexturesUsed` state, which Mesa updates on
program switches, sampler uniforms and relinking. It includes vertex samplers
and sampler arrays. The sweetgl frontend dispatches GL synchronously; this does
not query uniforms or maintain another sampler cache on every draw. Derived
`Texture.Unit[]._Current` state would be stale until draw validation, so it is
deliberately not used.

Any active sampler reading the render-target texture still gets the barrier,
including ordinary 2D reads as well as the emulated framebuffer-fetch uniform.
It conservatively treats all statically active sampler uses as possible reads;
it does not attempt to infer per-pixel control flow. Rendering/presentation
synchronization and `glFinish` are unchanged.

Active-sampler gating is the library default. `SWEETCA_ACTIVE_BARRIERS=0` restores
the old behavior for comparisons. With `SWEETCA_DRAWPROF=1`, `barrier-needed` and
`barrier-skipped` count matched bindings that do or do not require the barrier.
Collection is disabled normally.

## Build and tests

Implementation commit `8877ff1`, [Mesa CI 40053566696](https://github.com/telegdyd/ios-jasmine/actions/runs/40053566696)
passed. Library SHA256:
`e5fc84b1066990dbb06a6816ad5421978d84fcd2aa7c6f49d477594516847b1c`.
Artifacts under `xnu/out-mesa-t5active/`; raw console logs, profiles and scripts
under ignored `research/t5/`.

Local Mesa helper/test syntax checks passed; patches apply in order to a clean
Mesa worktree. Added GL regressions check link defaults, sampler-array remaps,
one-element remaps, unused texture bindings, shaders with no samplers, program
switches, relink resets, vertex plus fragment samplers and program unbinding.
These inspect the next draw's state before draw validation runs.

The IOSurface render-target regression was restored by fixing the previously
identified stride/offset argument swap in `sgl_surface_create_iosurface()`.
This helper is used by the GL test; CA's import path was already correct.

On the phone, all seven `sweetgpu_gltest` steps pass, including the nine sampler
state assertions and both IOSurface render-target checks (readback and actual
surface memory).

`sweetca_test` has one pre-existing failure in both exact diagnostic baseline and
optimized libraries: image orientation differs from the CPU reference. Both
report exactly 9958/65536 mismatching pixels: image 9201, rounded 119, opacity 0,
rotated 144, text 494. The reported GPU samples and full difference/rounded maps
match between the two outputs. This is regression evidence, not a claim that
the CPU-reference test passes or that every output pixel was compared between
libraries. Rounded framebuffer-fetch samples remain correct. The unrelated
image-orientation issue is not changed in this task.

Captured actual home and Control Center swap surfaces show the expected icons,
rounded panels and backdrop blur. The render-server screenshot API returned
black here; actual swap-surface captures were used instead.

## Profiling-off result against the step-1 diagnostic build

| Same gesture workload | Legacy | Active samplers | Change |
| --- | ---: | ---: | ---: |
| Home swap arrivals / second | 31.05 | 32.05 | +3.2% |
| Control Center swap arrivals / second | 18.45 | 19.51 | +5.7% |
| Home GL elapsed ms / flush | 24.92 | 24.14 | -3.1% |
| Control Center GL elapsed ms / flush | 40.51 | 37.57 | -7.2% |
| Home draw-wrapper calls / flush | 72.7 | 73.2 | similar work |
| Control Center draw-wrapper calls / flush | 182.0 | 181.6 | similar work |
| Home display-thread CPU ms/s, six-second sample | 765 | 727 | -4.9% |
| Control Center display-thread CPU ms/s, six-second sample | 894 | 892 | similar core usage, higher throughput |
| Home Mesa/wrapper user + support CPU ms/s | 486 | 448 | -7.7% |
| Control Center Mesa/wrapper user + support CPU ms/s | 601 | 582 | -3.1% |

These are small observed gains across two repeats, not confidence bounds or
confirmed displayed-FPS gains. The four profiles contain 227427 records, zero
dropped. Home spends more time waiting in submission/scanout paths after its
CPU work becomes cheaper; the whole GL elapsed reduction is smaller than its
user-CPU reduction. Control Center is still dominated by the display thread.
This fixes one source of overhead; task 5 overall remains open.
The reference here is `8a3ed2b` with collection disabled. A separate comparison
against the exact pre-existing production task-4 library is recorded below.

## Warm counter check

| Per GL flush, except percentages | Previous diagnostics, home / CC | Active samplers, home / CC |
| --- | ---: | ---: |
| Draw-wrapper calls | 72.8 / 181.5 | 72.6 / 182.4 |
| Actual finalized batches | 54.5 / 107.6 | **30.7 / 87.0** |
| One-draw batches | 80.3% / 76.3% | **33.9% / 61.6%** |
| Needed wrapper barriers | not separated | 13.9 / 28.7 |
| Skipped inactive-binding barriers | not separated | **25.4 / 25.3** |
| Program-cache hit rate | 100% / 100% | 100% / 100% |

The warm optimized counter run selected nine home reports (900 flushes) and
five Control Center reports (500 flushes), after the same settling/warmup rule.
It delivered 31.80 / 19.66 swap arrivals/s, agreeing with the profiling-off
result. Actual batch finalizations fall about 44% home and 19% Control Center.
The modest throughput gain relative to the large count reduction shows why the
batch counts alone were not a performance forecast. Many remaining dependencies
are real, and draw validation, state setup, GPU/scanout synchronization and CA
work still cost time.

## Measurement method

Same existing j69b kernel, four Gold cores at 1747 MHz, GPU 588 MHz, DDR ~1296 MHz.
All test boots are temporary `fastboot boot` images; graphics libraries and tests
are isolated from the production library until validation is complete.

Use the same ten-second home warmup, two ~30-second home swipe windows and two
Control Center open/close windows per variant as step 1. Profiling-off runs
compare actual UI behavior; the first repeat of each workload additionally has
a six-second CPU sample/census capture. Downloads happen after motion finishes.
A separate counter-enabled boot checks whether the proposed cause changed.

The baseline boot spent its startup interval uploading/running isolated tests;
the accepted optimized boot explicitly settled for 120 seconds after EAGL
initialization, then woke/unlocked and ran the ten-second warmup. An earlier
counter-enabled round began much earlier in startup and had a large fence-wait
tail (22.1 home / 16.5 Control Center swap arrivals/s). It is retained in the raw
data but excluded from the steady-state performance comparison. The counter
test was repeated with the explicit settling interval; the warm data above is
used for the steady-state conclusion.

## Installation and remaining work

Installed the CI library at `/usr/local/bin/libsweetca.dylib` (mode 755). The
exact old library is retained at
`research/t5/libsweetca-production-before-active.dylib` for rollback. A plain
slot-b reboot at 04:49:17 loaded the production path with active-sampler gating
enabled by default and draw diagnostics disabled; no environment override was
needed. Current kernel and slot-b image were retained; no partition flash. The preceding shutdown
hit the existing root-unmount hang and needed user Power+Volume Down recovery.

The final ten-second home and ten-second Control Center checks completed at
04:50:45, profiler idle/empty and GPU jobs completed, GPU 588 MHz / DDR ~1296 MHz.
The user confirmed iOS boot and visually reported no regression, while remaining
unsatisfied with performance. That is consistent with this being a small gain.

The next performance pass should stay on Mesa's CPU draw setup/state emission.
In warm Control Center, state-tracker preparation is about 4.46 elapsed ms/flush,
a5xx state emission 4.87 ms inclusive (2.87 ms of program emission is nested),
and batch create/finalize 3.08/3.26 ms exclusive. These are opportunities to
investigate, not additive or removable frame-time savings. Trace repeated dirty
state and allocation/validation causes before changing behavior. The display
thread remains ~89% on CPU, Mesa/wrapper user plus support ~65% of its CPU;
explicit fence waiting is only ~0.57 ms/flush here. Pipelining remains a stronger
overlap lead on home and needs the task-16 linked timeline before estimating gain.

The phone was returned to the r109 charging console after the checks, backlight
off. At ~04:58 the charger reported online/Charging, battery current +742187 µA,
4058827 µV, 64% (up from 63%). Parking float is now 4050000, below the reported
4400000 design/max; the previous 3.945 V float was at/below battery voltage.
The fuel-gauge status label still reports Discharging despite those charger and
capacity readings; this discrepancy is recorded in NOTES. Task-owned collectors
stopped and phone lock released.

For 100-flush diagnostic reports, drop the first complete report in each sliced
workload and select moving windows with >1000 ms GL elapsed time per report.
Flushes are not frames. Nested stage timers measure elapsed time, including
descheduling and blocking; inclusive scopes overlap. `SWEET FPS` counts swap
arrivals, not confirmed distinct display latches or input-to-display latency.
Any measured throughput gain must be described with that limit.
