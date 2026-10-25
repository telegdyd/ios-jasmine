# One-shot frame bottleneck benchmark

Proposed 2026-10-25; planning only. No benchmark implementation or device run yet.
This is the initial, bounded part of PERF-TASKS task 18, using task 19's CPU
attribution where possible. It does not implement the performance fixes.

## Contract

One command against an already running iOS boot, about 60-90 seconds of device
activity, one report, then exit. No automatic reboot, flash, library replacement,
clock sweep, retry round, or sustained-test loop. A missing capability or unavailable
phone produces a useful error, not an attempt to boot or recover it.

Proposed interface (does not exist yet):

```text
python tools/g2/framebench.py run --out research/framebench/<tag>
python tools/g2/framebench.py report research/framebench/<tag>
```

`run` also generates the report; `report` only reanalyzes saved data offline.
Default maximum device activity is 90 s, excluding a separately bounded readiness
check. Set a separate transfer/analysis deadline and print both timings. Target
compact export under 1 MiB and completion within roughly two minutes on an already
settled boot; measure actual transport speed before promising that total.

The missing frame trace requires a one-time kernel build and temporary boot for
setup. CI/setup time is separate from benchmark runtime. No repeated boot matrix.
The initial version should reuse the installed Mesa library and existing sampling
stacks; new per-draw Mesa instrumentation is unnecessary for this first ranking.

## Reuse and add

Reuse gesture commands from `tools/g2/uibench.py`, the sampler/census and symbolizer
in `tools/g2/prof.py`, and attribution from the ignored first-pass scripts under
`research/perf-firstpass-20261024/`. Promote the needed analysis into tracked tools
instead of depending on ignored files. Do not use `uiround.sh` or `profround.sh` as
the runner: they invoke the boot workflow. Do not use `profsplit.py`'s sampled
`AppleCLCD::present` detector to count current frames.

Add a runtime-enabled, preallocated binary event buffer in the kernel, disabled
outside the benchmark and automatically stopped at its deadline. Record:

- Phase/gesture boundaries and injected input receipt, on the device clock.
- Swap begin/end, swap ID, surface ID plus write generation, and presentation mode.
- GPU job enqueue, actual ring submission, observed fence completion, sequence ID,
  output-buffer/surface association, and wait enter/exit with reason.
- Display flip programming, observed hardware latch/refresh evidence, replacement,
  and surface retirement. Record the observed status/reason, not just `fShownID`.
- Existing panel/surface-protection waits separately from GPU-fence waits.

Use one kernel monotonic epoch shared with sampler records. Export timebase, epoch,
record version, sequence numbers, buffer capacity/usage and dropped-event counts.
Associate all jobs writing a frame with its presentation; a frame can contain
many jobs. Never join solely to the nearest timestamp. Reusing a surface object
does not imply reusing its old contents: the write generation matters.

Do not print an event per draw or stream/download data during measured motion.
Leave fences, SwapWait behavior and surface lifetimes unchanged. Read sensors and
state at phase boundaries, not through continuous command-port polling.

### Validate the display observation first

In j0058, `AppleCLCD::retireLatched()` advances `fShownID` when CTL_FLUSH clears
**or after 50 ms**. Its timeout branch is not hardware evidence of scanout.
Instrument those cases separately. A delayed poll also timestamps observation,
not necessarily the instant of latch.

Validate the existing status bit against refresh/scanout state and known static
and alternating test presentations during tooling development. Prefer an existing
hardware refresh/line/status observation over introducing heavy polling. Establish
observation resolution and the measured refresh period. If no trustworthy signal
is available, explicitly mark display FPS/percentiles unavailable and report
swap-to-hardware-observation proxies. Do not silently relabel these as display FPS.
Do not turn a difficult latch investigation into repeated benchmark boots.

### Fix export cost as part of the tool

The earlier raw profile transfer is documented around 20 KB/s; dumping several
full stack captures could dominate the run. Add a bounded compact export with
interned stacks and compact timestamp/thread/stack-ID samples, or phase/bucket
stack aggregates where full samples are unnecessary. Preserve enough sample timing
to relate sampled CPU/wait state to slow-frame intervals. Export only the captured
portion, with matching image mappings and exact symbol identities.

Use a length-aware binary response in the existing network service, after capture,
instead of repeated hex commands. The current command reply is string-based, so
this needs an explicit protocol addition, not binary bytes passed to `strlen`.
Cap data and deadlines; report truncation or insufficient sampling and lower
confidence rather than silently dropping evidence or retrying the workload.

## One fixed schedule

Acquire the existing shared phone lock or fail quickly if occupied. Discover the
reachable USB address once. Check command/trace/profiler capabilities, no other
capture active, and the home/unlock state; record actual kernel/library identity,
core topology, measured CPU/GPU/DDR clocks, temperatures and time since UI startup.
Do not assume the older j69b/j0070 notes describe the current running boot.

Use an already settled UI: the earlier comparison used 120 s after EAGL init.
If startup state is unknown or still busy, report it and stop or explicitly label
the capture unsettled; do not conceal another two-minute wait in the timed test.

| Phase | Approximate duration | Evidence |
| --- | ---: | --- |
| Idle | 3 s | Background CPU, initial memory/GPU state |
| Spotlight opening, then reopening | 8-10 s total | First-observed versus repeat hitch; never call this cold boot |
| Home/Control Center warmup | 8 s | Warm the steady-motion paths; exclude from their score |
| Home A | 10 s | Frame trace; sample CPU/census for 4 s inside motion |
| Control Center A | 10 s | Frame trace; sample CPU/census for 4 s inside motion |
| Home B | 10 s | Same gestures, frame trace only |
| Control Center B | 10 s | Same gestures, frame trace only |
| Final idle | 5 s | Post-motion recovery, temperature, outstanding jobs/memory |

Use a fixed finite gesture list with device-side phase markers. Reuse home swipes
and Control Center pull/Home dismissal patterns, shortened to fit the schedule.
Settle/reset to home between phases and include that time in the 90 s limit.
Start with 2 ms on-CPU sampling / 5 ms census for backboardd and SpringBoard;
record the actual periods. Include a short sampled first-Spotlight window if it
fits the data budget. Collect everything before download, so the profiler and
gesture player do not contend for the shared command port.

Tag commanded motion, animation-tail allowance and intentional holds separately.
Compute motion metrics from predefined motion windows; never select windows by
high CPU use or discard intervals because they exceed 150 ms. Include no-update
time at the beginning/end of each motion window and report a partial final stall.
Keep first-use, home and blur-heavy results separate. A/B are two segments within
one invocation, not repeated benchmark runs or boot variants.

## Report and priority decision

For each workload, report new latched presentation generations per active second,
update-interval median/p95, descriptive p99/max with sample count, no-update stalls,
and repeated/missed refresh opportunities against the observed refresh period.
Count replaced/dropped swaps separately. Identical pixels across different render
generations are not ruled out by IDs; do not claim a pixel-difference measurement.
Show phase totals as well as percentiles so freezes cannot disappear from the score.

Link the worst intervals to sampled CPU stacks/runnable/waiting state and the
GPU/swap/display events. CPU samples estimate costs; inclusive stack rows overlap.
Ring-submission to observed completion includes dispatch and completion-observation
delay; it is not pure GPU execution time. If GPU busy counters are used, prefer
validated lightweight boundary snapshots; the existing `ddr bw ... bg` polling
worker needs its overhead checked before combining it with this capture. Exclude
the earlier implausible CPU-bandwidth readings.

| Evidence during slow motion | Task to prioritize |
| --- | --- |
| Display thread running in draw validation, state/program emission, batch setup | 5; name the largest measured function group and next focused experiment |
| Rendering starved upstream while SpringBoard does layout/transaction work | 19; only claim producer causality with matching IPC/transaction evidence, otherwise label a lead |
| Large runnable delay or work on unsuitable cores | 6 investigation; an actual 4/8-core comparison remains separate |
| Submitted GPU work/panel waits serialize otherwise available CPU work | 16, using task 18's linked evidence and a conservative overlap bound |
| Shader-worker wait on first-observed opening, absent on repeat | 17 for hitches, separate from warmed FPS |
| Allocation/pressure stalls or buffer-free blockage | 20 or 14 before further speed work |
| Actual service/storage waits during a captured transition | 21 for that delay; do not infer boot latency |

The report should end with one recommended next task, its evidence and confidence,
the next two candidates, and one concrete follow-up experiment. Rank recoverable
critical-path time and frequency, then implementation effort; do not rank by global
CPU/GPU utilization alone or add overlapping timers into a promised speed gain.
Mark unknown time and unproven causality explicitly. Current evidence favors task 5,
especially Control Center, but this run must be allowed to change that conclusion.

Compare sampled A against trace-only B for gross perturbation; variation includes
animation/background differences, so this is an overhead check, not a precise
calibration. Validate trace-only versus tracing-disabled overhead once during tool
development on the same boot, plus parser checks for reused surfaces, multiple
jobs, timeouts, dropped records and stalls at phase boundaries. Do not repeat
calibration on every invocation. Tail percentiles in a short run are descriptive,
not confidence bounds.

This one shot cannot validate reboot-persistent shader caching, cold boot/storage,
4-versus-8-core benefit, leaks or thermal behavior over many minutes, or power
management savings. Keep those tasks unranked for sustained FPS unless this capture
finds relevant evidence. Full physical touch-to-photon and causal input latency
can follow later in task 18; they are not prerequisites for the first ranking.

## Stop behavior and deliverables

On success: stop captures, fetch once, generate `report.md` and `summary.json`,
preserve a compact timeline and exact manifest/symbol references under ignored
`research/`, return home, release only this invocation's lock, and exit.

On timeout/loss/freeze: stop issuing gestures, preserve partial evidence, use at
most one short existing stuck-thread census if the command port responds, and
exit nonzero. Never reboot/retry automatically; if the phone watchdog resets it,
record that and stop. Any existing parking policy is a separate explicit action,
not a hidden reboot at the end of a measurement command.

Implementation deliverables: runtime frame-event capture and compact export,
`tools/g2/framebench.py`, reusable analysis/parser checks, and one baseline report.
Build instrumentation once, check it locally before CI, then use one temporary
setup boot. Readiness/transport/latch failures should produce a bounded partial
report with the exact missing capability, not start an open-ended bring-up loop.
