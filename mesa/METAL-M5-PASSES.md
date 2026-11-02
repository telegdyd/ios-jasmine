# M5 — GPU pass and client attribution

The compositor's largest measured class is the **828×1792, single-sample,
two-BGRA8-attachment system-memory pass**. The next M6 investigation should audit
the second attachment's clear, preservation, store and consumer lifetime in these
passes. Eliminate an attachment/copy only after proving the consumer does not
need it; evaluate GMEM separately with actual framebuffer-fetch eligibility.
This task adds diagnostics and attribution, without changing rendering policy.

## Collector and interpretation

Patch `0029` and Metal commit `3b880d7` add `BGMTL_PASS_PROFILE=1` diagnostics.
Create `/private/var/tmp/bgmtl-pass-start` after clients settle. Each process
captures at most 120 replayed command buffers or eight seconds of activity,
then harvests outstanding stamps on subsequent command-buffer boundaries.
The two-second pending deadline is also activity-driven. Keep motion running
past the eight-second deadline for slower clients; an idle process does not
have a timer that exports its capture. Restart the process to rearm.
Output: `/private/var/tmp/bgmtl-pass-PID.csv`.

A fixed 65,536-row table records descriptors, shader labels, draw-to-batch
edges, copy/resolve/mipmap work kinds, batch metadata and GPU start/end stamps.
No pixel contents are collected. There is no per-draw logging, allocation or
clock read. Disabled diagnostics retain conditional checks. Table overflow,
GPU timestamp-ring overflow and unharvested stamps invalidate complete-cost
claims. The analyzer rejects dropped/pending data and incomplete command buffers.
Shader labels are truncated to 95 bytes and are descriptive classes, not unique
shader identities. The texture summary records slots zero and one, which can
both be unbound even when later slots are populated; it is not a complete
sampled-resource inventory.

The existing a5xx `RB_DONE_TS` path uses the 19.2 MHz GPU counter. These are
**pipeline-draining execution envelopes**, not submit-to-fence measurements.
The instrumentation can change overlap and cache behavior. A batch may implement
multiple encoded passes: draw edges retain that relationship, and its duration
is never divided among shaders or charged once to every pass. Clear/copy-only
batches can lack draw edges. Batch identity is `(process, context, sequence)`;
the active pass at batch finalization is not assumed to own all its work.
Report interval unions as well as sums, because measured envelopes can overlap.

No new batch splits, GPU waits, barriers, attachment actions, resolves, ticket
handling or asynchronous replay policy are introduced. Collection requires
serialized inline Metal replay; completion-worker finalization is outside its
TLS scope. Missing timed-batch links are reported explicitly.

Analyze a capture with:

```
python tools/g2/metalpasses.py CAPTURE.csv --json SUMMARY.json
python -m unittest discover -s tools/g2 -p test_metalpasses.py
```

Descriptors contain target width/height, samples, active color count, eight Metal
color formats, four-bit-per-slot load/store actions, resolve-target mask, depth
format/actions and stencil format/actions. Batch fields include actual dimensions,
sample/color count, first pipe color format, depth format, sysmem/GMEM/nondraw mode,
draw count, clear/restore/resolve masks, feedback and pre-barrier counts.
Work-kind records distinguish explicit copies, resolves and mip generation from
render passes. These describe requested/executed operations, not RAM transactions.

## Measured compositor ranking

The final-source 65,536-row `m5safe` windows have zero dropped or pending records.
Both contain 120 command buffers. These windows are diagnostic workload samples,
not matched frames or a performance comparison.

| Window | Encoded passes | GPU batches | Sum, ms | Interval union, ms | Largest class, ms |
| --- | ---: | ---: | ---: | ---: | ---: |
| Home | 3,502 | 3,654 | 3,088.59 | 2,085.66 | 2,503.96 |
| Control Center | 2,491 | 2,521 | 2,556.21 | 1,740.13 | 1,732.20 |

The largest class accounts for 81.1%/67.8% of the compositor's summed diagnostic
envelopes. Its driver masks are clear `0x8`, restore `0x4`, resolve/store `0xc`:
color 1 clears, color 0 preserves contents, and both are stored. In these
single-sample batches the driver's `resolve` mask means attachment writeback,
not an MSAA resolve. Encoded descriptors agree: two `BGRA8Unorm` attachments,
load actions Load/Clear, store actions Store/Store, no resolve targets.
Driver pipe format 105 is `B8G8R8A8_UNORM`. No depth attachment or feedback
barrier is recorded in this class.

Linked shader labels are predominantly
`fixed_vert_lph_spc+fixed_frag_lph_cph`, plus `luma_boost_lph` and attachment
clears. These labels identify compositor work; they do not isolate a shader's
execution cost. Smaller 209×450/830×1794 classes include downsample and narrow
blur shaders. In Control Center, 684×424 batches total 258.68 ms and 830×1794
batches total 176.89 ms in this window. Do not prioritize blur merely from its
visual prominence or remove required edge/helper-lane behavior.

One 828×1792 BGRA8 attachment has a nominal logical footprint of 5,935,104 bytes;
two occupy 11,870,208 bytes. Repeated preservation/clear/writeback makes these
passes a concrete traffic candidate. These are **logical footprints**, not
measured bus bytes or a lower bound on external traffic: partial coverage,
caches, compression and implementation details matter. The existing whole-GPU
RAM-starved ratio cannot identify the stalled pass or prove removable traffic.
Per-pass hardware byte counters remain unavailable in this collector.

## Client coverage and remaining M5 work

**M5 is partially complete.** The compositor inventory and concrete M6 candidate
are established. Wallpaper execution-time and traffic attribution remain open;
this report does not establish a whole-GPU ranking between the two clients.

In the final-source four-second sampled job windows:

| Window | backboardd kernel calls / IBs | Collections wallpaper kernel calls / IBs |
| --- | ---: | ---: |
| Home | 86 / 2,417 | 12 / 12 |
| Control Center | 95 / 1,701 | 12 / 12 |

All submit TIDs in these windows map to a process; event/sample losses are zero.
Job events are sample-window-only and have a different duration from the 120-CB
GPU capture. These counts are not GPU time or bytes. Observed submit-to-fence
median/p95 envelopes are 22.64/30.48 ms Home and 15.95/34.66 ms Control Center,
including queueing and delayed completion observation. They must not be added
to or substituted for GPU timestamp durations.

Read-only loaded-image inspection confirms Collections uses the separate
`/usr/local/p/` libraries. Both pairs were instrumented temporarily and restored;
both existing env files contained the diagnostic configuration. Nevertheless, no nonempty wallpaper timestamp export was obtained.
Extending motion beyond the activity deadline and precreating mobile-owned
output files also produced empty wallpaper exports. Thus file ownership alone
did not resolve it. Loaded libraries alone do not prove that their replay hooks
ran with profiling enabled. The failure's cause is **not established**.

Next concrete M5 action: inspect the active wallpaper client's effective
configuration and whether it enters `bgReplayFrom:`/`sweet_m5_begin`, then distinguish
unarmed collection from failed export. Kernel framebench currently starts its
user-stack/VM-map whitelist with backboardd, SpringBoard, PosterBoard and
Preferences, excluding the wallpaper renderer. A targeted wallpaper-only
user-stack capture or read-only process inspection is more useful than repeating
full UI/counter benchmarks. Do not assign the wallpaper's twelve jobs the
compositor's average duration or silently exclude them from a whole-GPU claim.

## Instrumentation overhead and reference

Two profiling-disabled Home/Control Center references use the installed runtime,
the same gesture commands and four-second CPU/job-event windows. They have zero
event/sample loss. Their swap arrivals were 23.72/21.55 per second; the first
instrumented pair measured 22.91/23.97. Temperatures, startup activity and client
mix differ, so these numbers **do not isolate overhead or establish a speedup**.
The established baseline2 remains the production baseline; no new standard
framebench baseline was taken.

A deterministic calibration uses the same diagnostic pair, 40 identical
207×448 R8 Gaussian-blur command buffers per process, alternating OFF/ON/ON/OFF.
After excluding five startup iterations, the two mean wall times are
3.767/3.784 ms OFF and 4.014/3.987 ms ON: averaged means increase about **6.0%**.
Temperatures stay around 49–52 C and all four sampled outputs agree exactly:
center 231, edge 113, corner 0. These are commit-plus-completion wall times,
including CPU, queueing and scheduling. They quantify perturbation for this
small deterministic workload, not GPU-only overhead or a correction factor for
full-screen compositor batches. Startup totals and individual iterations are
retained in ignored evidence.

The separate whole-GPU counter attempt requested 12 seconds and the kernel
confirmed an actual **10,000 ms** window. Input stopped on a command-port
connection timeout after about seven seconds; there is no admissible matched
counter/workload result. GPU power collapse was restored to mode 1 (on) in
`finally` and verified by readback; hardware clock gating and clock selections
were unchanged. Use the previously recorded ten-second whole-GPU measurements
in `METAL-PERF-20261101.md` only as historical context, not as bytes attributable
to these new passes. No repeated counter benchmark was run.

## Validation and runtime state

- Local VM `m5inventory` PASS (14 s), `m5final` PASS (17 s), `m5ready` PASS
  (16 s), `m5bounded` PASS (12 s), final `m5safe` PASS (13 s). No CI.
  The initial inventory build missed a header include; fixed before GPU testing.
  The final revision honors `SWEETCA_GPUPROF=0` after bounded collection stops.
- Normal and compositor GPU suites pass **32/32** on the final source, including
  target switches, framebuffer fetch, mutable/compressed uploads, derivatives
  and the 80-pass RAW chain. Instrumented deterministic MPS output matches OFF.
- Collector ASan/UBSan tests cover disabled mode, trigger, shader aggregation,
  edge/stamp bounds, duplicate stamps, 120-CB stop, capacity loss, deadline and
  pending export. Reproducible source: `tools/g2/metalpass_collector_test.c`,
  compiled with the patched `src/freedreno/drm/darwin` include directory.
- Four analyzer tests cover overlapping/out-of-order timestamps, shared-pass
  ownership, shader/sample metadata and rejection of incomplete evidence.
- The richer initial 16,384-row captures overflowed and were rejected; they
  support no complete-cost claim. Earlier client attempts also missed truncated
  process names and the separate poster runtime path. They remain diagnostic
  evidence, not all-client attribution.

All captures, exact runtime backups/readbacks, calibration source/output and
scripts remain ignored under `research/metal-m5/`. The wallpaper uses separate
`/usr/local/p/{libbgair,libbgmtl}.dylib`, verified from loaded process images;
backboardd uses `/usr/local/bin/`. Both pairs and both environment files must
be restored after diagnostics. Do not infer wallpaper timing from compositor
counts or attribute whole-GPU counters to backboardd. No physical-panel FPS,
end-to-end latency improvement or optimization benefit is claimed by M5.

Final cleanup verified all four original libraries and both environment files
byte-for-byte again. The compositor retains the installed M4 pair
(`95cea7f9…` / `3d91c9f6…`); wallpaper retains its original pair
(`0d9fb5a2…` / `eaf44cde…`). The injector is unchanged. Benchmark/profiler are
idle, GPU jobs completed 22,520/22,520, power collapse mode 1, final maximum
TSENS 54.3 C. Task-specific binaries, CSVs, empty precreated outputs and
trigger are removed; the remote diagnostic directory is empty and the shared
phone lock is released. The phone remains running iOS. No reboot, flash,
partition, kernel or clock changes. Main implementation commit: `d07f64a`.
