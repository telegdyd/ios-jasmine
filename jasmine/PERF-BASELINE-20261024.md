# Current UI bottleneck: first measurement pass, 2026-10-24

Measured 03:14-03:22 Europe/Budapest, on the existing running slot-b boot.
No reboot, flash, software installation, clock/voltage change, new kernel, or CI run.

## Finding

CPU-side rendering is the strongest current optimization target for sustained home-screen
and Control Center motion. CoreAnimation's display thread spends roughly 75% and 82-85%
of wall time on a CPU, respectively. Mesa/libsweetca and its support-library work account
for about 63-66% of that thread's **on-CPU** time. Task 5 is therefore still relevant after
the buffer-cache and daemon fixes. This does not establish the number of milliseconds
that an optimization would remove from a displayed frame.

There are secondary costs: GPU submission/fence waits on the home screen, GPU memory
stalls, substantial SpringBoard work, and shader compilation on the first measured
Spotlight opening. Average GPU utilization alone cannot exclude GPU-limited individual
frames. A frame timeline or controlled clock comparison is needed for that attribution.

## Configuration and evidence

- Four Gold cores at 1747 MHz, from the captured boot log and current PLL/RCG state.
- GPU requested 588 MHz, measured 587-588; DDR 1294-1296 MHz, scaling off, vote 0.
  `gpu state` reports the half-rate BIMC clock (~648); `ddr state` reports DDR (~1296).
- `sweetfb_sync=1`, hardware display scaling, current task-4 Mesa heaps, task-7 daemon
  changes and task-14 ADT MAC fix. `sweetfps=1` is absent from this boot's arguments.
- Downloaded `/usr/local/bin/libsweetca.dylib`, 19,217,072 bytes. SHA256
  `8a2defaa9e8974b126014193142754062758a7c38699ee7df8f19cb3506990f3`
  exactly matches `xnu/out-mesa-t4final/mesa-ios/libsweetca.dylib` (CI 39903986273).
- Kernel symbols: `xnu/out-jasmine-j69b/kernel.development.sweet`, SHA256
  `8e66552aa0cc79ee45e5a5d9276958ae243b24e2a951bb37643a66e8a250f04f`.
  This is the expected active-handoff kernel; there was no independent live kernel UUID
  check (`/usr/sbin/sysctl` is absent). Profile metadata reports kernel slide 0.
- Sensor range before CPU captures: approximately 45-52 C. Immediately after some
  unprofiled motion, up to 56 C; back near 45-51 C when settled. No clock changes observed.
- Raw profiles, matching dylib, full reports, local measurement/analysis scripts and
  `events.jsonl`/`netlog.txt` remain ignored under `research/perf-firstpass-20261024/`.
  Do not commit these files or Apple artifacts.

## Method

Nine six-second CPU captures, all with zero dropped records: idle; home-a/home-b;
control-a/control-b; spotlight-a/spotlight-b; home-lowrate/control-lowrate.
The initial captures use 1 ms on-CPU sampling and a 2 ms waiting/runnable census of
backboardd and SpringBoard. The lower-rate checks use 2 ms / 5 ms. On-CPU sampling
covers other processes too. Downloads occur only after the gestures finish.

Each moving capture begins at home after a Home key and 2 s settling. Home: alternate
250 ms left/right swipes at y=1200 with 100 ms rests, eight pairs in ~6.4 s. Control
Center: 300 ms top-right pull, 400 ms rest, Home, 300 ms rest, six cycles in ~6.5 s.
Spotlight: 250 ms downward center swipe, same rests/Home, six cycles in ~6.1 s.
The profile covers the first six seconds, not the small final gesture overrun.
First measured use is not a guaranteed cold boot: the phone was already running.

Each workload was also run without sampling, then with a separate six-second
`ddr bw 6000 bg` counter window, without its synthetic memory load. Counter collection
is separated from CPU profiling because it runs its own kernel polling thread.
The script completed the same number of gesture cycles without sampling. This checks
execution continuity, not exact frame-rate overhead. The lower-rate profiles provide
the stronger cross-check on the CPU diagnosis.

## Display-thread time

All numbers are **milliseconds per second of the capture**, not ms/frame. On-CPU values
come from sampling; waiting/runnable values are approximate census estimates, which
can race thread transitions and are not an exact additive accounting.

| Workload | On CPU | Waiting | Runnable | Mesa/wrapper user CPU | Support/malloc under GL | QuartzCore user CPU |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| Home a | 750 | 177 | 71 | 367 | 103 | 151 |
| Home b | 760 | 168 | 73 | 375 | 108 | 149 |
| Control Center a | 822 | 108 | 12 | 417 | 122 | 168 |
| Control Center b | 844 | 102 | 18 | 430 | 121 | 181 |
| Spotlight a | 404 | 552 | 59 | 167 | 52 | 90 |
| Spotlight b | 642 | 303 | 58 | 288 | 89 | 140 |
| Home, lower sampling rate | 750 | 179 | 83 | 367 | 102 | 147 |
| Control Center, lower sampling rate | 848 | 113 | 15 | 422 | 123 | 184 |

Home b's remaining CPU work includes 104 ms/s in the kernel and 24 in CA support code.
Control b has 87 kernel and 26 CA support. Kernel GPU-driver allocation is no longer
the dominant CPU cost. In the captured 600-frame summaries, all 600 frames use the MDP
and zero use the CPU display copy.

Home's display thread waits about 89-90 ms/s in the submit call and 52-62 ms/s in
`darwin_pipe_wait`. Submission can include panel/surface waits inside the driver;
these categories must not all be labelled GPU execution. Control Center's corresponding
waits are only about 13-16 and 10 ms/s. Many other census records are short/transitional
and have stale-looking trap values: they do not diagnose a particular lock bottleneck.

## Inside the rendering CPU cost

Warm capture inclusive stack shares below are percentages of the display thread's
on-CPU samples. **They overlap and must not be summed.**

| Path | Home b | Control Center b |
| --- | ---: | ---: |
| `w_DrawElements`, including preparation and periodic kicks | 57.4% | 52.2% |
| `draw_prep`, including downstream work | 12.7% | 10.2% |
| `fd5_emit_state` | 10.1% | 8.9% |
| `fd_batch_create` | 7.3% | 7.4% |
| `fd5_program_emit` | 6.1% | 5.4% |

Task 5 should next distinguish repeated validation/state setup from batch creation,
resource dependencies/barriers, uploads and the every-32-draw kick. These profiles locate
the work but do not yet establish which repeated operations can safely be removed.
`fd5_program_emit` is state/program emission, not proof of shader compilation.

## GPU counters and other processes

| Separate counter workload | Busy Mcycles/s | Approx. busy at 588 MHz | RAM-starved Mcycles/s | VBIF Mbeats/s |
| --- | ---: | ---: | ---: | ---: |
| Idle | 0 | rounds to 0% | 0 | 0 |
| Home | 268 | 46% | 121 | 80 |
| Control Center | 202 | 34% | 126 | 65 |
| Spotlight | 203 | 35% | 93 | 58 |

The RAM-starved counter is a reason to retain memory behavior as a secondary lead,
not evidence that raising DDR will improve frames. No DDR scaling experiment was run
here. Do not interpret these overlapping counters as an additive frame-time breakdown.
The legacy CPU bandwidth counter prints impossible multi-million-MB/s values and is
excluded; its units/calibration need separate attention.

Idle CPU: kernel_task 25.3, SpringBoard 21.5, backboardd 5.8, launchd 4.5, mediaserverd
1.0 ms/s. A nanotimekitcompaniond launch costs 16 ms/s over this window; bluetoothd
still respawns. Neither resembles the old two-core retry storm.

SpringBoard's main thread uses 711-743 ms/s during home swipes and 428-473 during
Control Center. It is a substantial upstream producer, so optimizing only Mesa will
not remove all CPU work. Spotlight itself uses 507-652 ms/s across its captures.

Spotlight a includes 46 ms/s (~276 ms across six seconds) waiting in
`ir3_get_shader -> util_queue_fence_wait`; Spotlight b has no captured shader-worker
wait. The display thread also spends much of Spotlight a in its run-loop receive,
while Spotlight, SpringBoard, searchd and kbd do work. Its lower render-thread activity
is not evidence of a faster frame; startup/producer behavior differs from steady motion.

## Decision and limits

Proceed with task 5's draw-path breakdown first. Track home and blur-heavy Control
Center separately. Keep producer CPU work, GPU submission/panel waits and first-use
shader hitches separate from steady Mesa CPU work.

This pass does **not** produce trustworthy current FPS, frame percentiles, touch-to-display
latency, or an exact frame critical path. GL flushes are not presents; the old
`profsplit.py` frame detector depends on sampling a now-microsecond `present()` path.
The existing FPS log is off on this boot. The next instrumentation pass should timestamp
swaps/latches and GPU jobs before promising milliseconds of visible improvement.

Phone left running at its original clocks with all submitted GPU jobs completed;
no panic, GPU fault or hang during the measurements. No CI build was necessary.
At 03:24 the final command check reports profiler idle and GPU 12516/12516 completed.
The local console collector was stopped and our shared phone lock released.
