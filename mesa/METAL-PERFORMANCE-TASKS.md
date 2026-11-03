# Metal performance tasks

Reviewed 2026-11-02 against the M1â€“M6 reports, implementation patches and active
NOTES.md handoff. This is the current queue; the original task descriptions and
November 1 profile remain historical evidence, not an instruction to repeat work.

**Acceptance:** remove verified unnecessary work while preserving correctness.
An aggregate FPS/CPU gain is not required to accept a demonstrated work reduction.
Reuse existing captures and keep validation bounded. Timing can supply context;
it must not become a reason to undo correct, proven work elimination.

## Completed and installed

| ID | Accepted result | Evidence / boundary |
| --- | --- | --- |
| M1 | Exact-content reuse avoids repeated packed-image uploads; default on | 35 uploads / 51,932,160 bytes avoided in a bounded window; mutable data and GPU/CPU invalidation covered. Linear-buffer uploads remain a possible follow-up. [Report](METAL-M1-UPLOADS.md), main `7e5e11b`, Metal default `c121e6a`. |
| M2 | Repeated identical texture-refusal output is aggregated | 433 repeats replaced by five summaries after the initial error; unsupported requests still return nil. Format 500 and downstream retry cost remain unresolved. [Report](METAL-M2-REFUSALS.md), main `b5fdc8e`, Metal `8c82bae`. |
| M3 | Unused binning-state emission omitted for eligible forced-sysmem batches | One emission per draw instead of two. Actual draw state, resource tracking, MSAA/GMEM binning and streamout remain protected. Repeated-reference fast paths already exist; no further tracking removal is justified yet. [Report](METAL-M3-STATE.md), main `10d4922`, Metal `ccb3cc7`. |
| M4 | Bounded deferred submission groups replace the individual 30-BO heuristic | 121 observed calls vs 157 old-policy projected calls on the same batch stream. Limits: 512 conservative BO references / 128 commands, pre-append drain. No GPU batch merge or latency/FPS claim. [Report](METAL-M4-SUBMITS.md), main `be18737`, Metal `91d1aa9`. |

These are closed implementation milestones. Do not reopen them to obtain a new
benchmark score. Further work needs a specific remaining unnecessary operation.
The original [baseline](METAL-PERF-20261101.md) predates M1â€“M4: its CPU shares and
36 Home / 31â€“32 CC swap arrivals/s are not current installed-runtime measurements.

Last verified installed compositor pair is M4: libbgair `95cea7f9â€¦`, libbgmtl
`3d91c9f6â€¦`. Wallpaper still uses `/usr/local/p/` pair `0d9fb5a2â€¦` / `eaf44cdeâ€¦`.
M5 diagnostics and M6 feedback-safety changes are committed and tested in source,
but are **not installed**. No activation is pending from those experiments.
M6's final suites passed 35/35 in normal, forced-sysmem and eligible-GMEM modes.

## Remaining queue

| ID | Status | Revised work | Dependency |
| --- | --- | --- | --- |
| M5 | Partial | Resolve wallpaper collection/export and complete client attribution | Targeted configuration/replay inspection; compositor ranking already exists |
| M6 | Partial; deferred | Logical graph captured; no safe removal established. Reopen only for a specific operation and a strategy to cover its missing observers/backing | [Lifetime audit](METAL-M6-LIFETIMES.md); retain corrected feedback constraint |
| M7 | Done; async INSTALLED 2026-11-03 | m7close4 fixes an async CA-memory crash (run 9), a failed-submit-as-Completed gap and a same-surface reuse race; j0127 cancelled ACK (P24), pending reuse (P25), submit failure (P26) pass on device; async-only trials 16-18 clean. User panel check on m7close4 passed; installed in backboardd with BGMTL_ASYNC=1 (rollback `panel.py restore`) | [Trial](METAL-M7-TRIAL.md), [recovery](METAL-M7-ASYNC.md), [callbacks](METAL-M7-CALLBACKS.md), [admission](METAL-M7-ADMISSION.md); not installed, installed async off |
| M8 | In progress | Attribute callback/presentation delays and repeatable gaps | bg_lock completion wait removed (Metal b049aff; fence->present p50 10.2 -> 0.03 ms), INSTALLED; CA completed-handler stalls (getBytes behind replay) removed by unlocked linear readback + deferred contended destroy (Metal bd4f5fb, a9b6a0d; handler p99 18.3 -> 1.5 ms), m8gb1 INSTALLED after user panel check; bgCollectWrites lock waits open |

Recommended next: **M8** attribution (async is now installed).
The bounded M6 logical lifetime audit found no safely removable operation within
its observer coverage. Revisit M6 with a specific physical-backing/global-observer
proof strategy. M5's wallpaper gap remains a separate targeted diagnostic task.
M8 should evaluate M4's unmeasured latency implications when relevant.
This queue does not authorize concurrent device workloads or VM builds.

## M5 â€” Resolve the wallpaper attribution gap

**Already established:** The compositor collector/analyzer exists, rejects
lost/pending captures and ranks its passes. M6 corrected missing feedback markers:
the original M5 zero-feedback fields do not prove GMEM eligibility. In corrected
M6 Home evidence, fullscreen fetching batches account for 62% of summed compositor
execution envelopes. These are pipeline-draining timestamp envelopes, not bus-byte
measurements or isolated shader timings. See [M5](METAL-M5-PASSES.md) and
[M6](METAL-M6-TRAFFIC.md).

**Remaining work:** Inspect the active wallpaper process's effective profiling
configuration and entry into `bgReplayFrom:` / `sweet_m5_begin`. Distinguish failure
to arm, absent replay hooks, unfinished activity-driven collection, timestamp
harvesting and export failure. Loaded libraries and precreated writable files did
not establish successful collection. Use bounded stage counters or targeted
wallpaper-only stacks; the current framebench user-stack/map whitelist excludes
wallpaper renderers. Do not repeat whole UI/counter runs to guess which stage failed.

Once the path is understood, obtain one complete bounded wallpaper capture or
document and instrument its actual alternate submission path. Keep process/context
identities and missing timing coverage explicit. Do not assign compositor average
cost to wallpaper jobs: twelve wallpaper calls/IBs do not establish their GPU time.
Per-pass hardware byte attribution remains optional instrumentation work, not a
reason to invent bytes from attachment dimensions.

**Where:** `mesa/metal/src/bgmtl.m`, `mesa/metal/air/air_metal.c`, M5 collector in
patch0029, `tools/g2/metalpasses.py`, targeted profiler task selection.

**Done when:** Wallpaper collection behavior has an established cause and relevant
client work is attributed with complete records, or a precisely documented
instrumentation limitation remains. Whole-GPU rankings require actual client
coverage; compositor-only findings may proceed independently. Restore all four
libraries and both environment files after temporary diagnostics.

## M6 â€” Prove attachment deadness or smaller scratch coverage

**Already established:** Color1 is live within the rounded-corner save/restore
sequence. Color0 Load preserves partial redraws; the independent color1 clear can
supply pixels read by later fetches. Store/Store has no proven dead store. Current
Metal attachment texture-fetch descriptors require sysmem; GL's experimental
tile-fetch option does not make them GMEM-safe. The corrected constraint follows
the fetching draw through dependency tracking and empty-batch fallback (Metal
`587e6b8`, patch0030; main `8e64b9c`). Keep this safety fix in subsequent candidates.

The deterministic eligible-GMEM trial passed pixels but established no eliminated
operation or traffic benefit. Broad GMEM enablement and attachment deletion are
therefore removed as immediate implementation tasks. This decision does not reject
proven work elimination on the basis of noisy frame scores.

The [logical lifetime follow-up](METAL-M6-LIFETIMES.md) implements bounded texture
generation/resource/surface IDs, masks, regions and in-replay accesses. Its 12-CB
window has 144 accesses/17 lifetimes and twenty target reuse transitions, all
crossing CB boundaries. Color1 has no draw writes/fetches in that window, but
unobserved inter-CB consumers prevent clear/store removal. Physical backing
renaming/aliases, global observer coverage and sample mip/layer ranges remain
unknown. This negative result does not close M6 or authorize attachment removal;
prefer the independent M7 route over repeating whole-UI captures without a new
specific proof strategy.

**Reopening condition:** Name one actual clear/copy/attachment operation or scratch
region and explain how to establish its backing/alias identity, sampled subresource
ranges and all possible observers over the relevant interval. The existing logical
graph and write/fetch masks are completed work, not the next task. Cover CPU and
external/IOSurface access outside replay where the proposed removal requires it;
mark unknown coverage explicitly. A scoped proof for one operation is sufficient;
building an unlimited global tracer is not an objective.

For the clear-only color1 candidate, all observed reuse crossed CB boundaries.
In sysmem, clear/draw commands write memory directly: dropping requested Store
alone does not remove a distinct hardware store. Identify the command or memory
access that would actually disappear before collecting more evidence. Otherwise
retain the negative result and proceed with M7. Do not repeat general UI captures
to seek a favorable scene. Fetching-pass GMEM requires a separate valid fetch
implementation and pixel proof; it is not an environment-switch task.

**Where:** Metal pass/replay/texture code, `air_metal.c` attachment/feedback paths,
patch0029/0031 collectors and patch0030 constraint, `tools/g2/metalpasses.py` and
`tools/g2/metallifetimes.py`.

**Done when:** One proven unnecessary operation is removed, with exact pixel
coverage for rounded corners, later color1-only clears, partial redraw/Load,
resource reuse/aliases, blur borders and MSAA. Validate affected normal/compositor
and shared GL paths. Count the actual removed operation/region/bytes where
established; label logical footprint estimates separately from bus traffic.
GPU/end-to-end timing is context, not a mandatory aggregate-speedup gate.
A lifetime audit or safety fix alone leaves traffic elimination partial.

## M7 â€” Make asynchronous replay safe

**Callback review finding resolved in source:** Metal `b595b76` separates scheduled/
completed delivery flags from Error status. Shared-method host sanitizer tests cover
late, reentrant and concurrent registrations; P21 exercises delayed error retirement
on the GPU. All six isolated modes pass37/37, with the queue-specific P21 case
explicitly skipped for synchronous completion. No installed runtime changes.
See [fix and validation](METAL-M7-CALLBACKS.md).

**Implemented follow-up:** [M7 recovery audit](METAL-M7-ASYNC.md) reproduces the
cancelled-ticket backing retain, fixes proof-backed cancellation acknowledgement
without resurrecting the frame, and keeps the protected queue on reason-16 drops.
Metal checks retirement/drains, serializes replay scope, and preserves error
completion FIFO. Host sanitizer tests, isolated hardware epoch/same-backing
recovery, async GPU36/36, MSAA and shared GL pass. That milestone left admission open; the subsequent isolated implementation is
recorded below. No compositor async activation or panel acceptance is claimed.

**Admission follow-up implemented:** [M7 imported-write admission](METAL-M7-ADMISSION.md)
keeps encode-time tickets, covers recorded render/resolve/blit/mipmap and actual
writable shader-image destinations (including argument records), and revalidates
before replay. The 32-per-CB/1024-process bounds, unknown/uncommitted ownership,
timeouts and refused BEGIN fail the entire CB before recorded writes. Known
committed producers get one bounded wait outside locks, followed by authoritative
kernel recheck. Host admission/callback sanitizers and all six isolated GPU modes
pass47/47; focused MSAA4x resolve checks pass. This closes the known silent-eight/
log-and-proceed gap within implemented command-buffer paths, not full M7.

**Why still needed:** M1â€“M4 reduce work; they do not move replay off CA's thread.
Async remains opt-in/off in the installed environment. Historical r26 improved CC
throughput but exposed an encode-to-submit ticket/epoch race, persistent fallback
and visible corruption. That result is not a new gain on the M4 runtime.

**Display-off admission fixed:** Metal `9ff68e9` / main `fc90f81` defer a
suspended BEGIN, retry once at replay, and admit a still-suspended destination
unticketed; host ASan/UBSan and the isolated P23 modes pass. [Run 7](METAL-M7-TRIAL.md)
then had zero `BEGIN refused` in P1/P2 (one `display suspended` diagnostic per
phase; the logger prints only the first and every 100th event, so it is not a
total). Twelve screenshot labels each returned three non-uniform/non-black
surfaces; P1-wake1 and P2-wake3 were viewed clean; restore was byte-exact. Not installed.

**Closed (2026-11-03):** [M7 closing](METAL-M7-CLOSING.md). m7close4 (Metal `327bf2f`) adds a replay-mode log that positively confirms async in
backboardd, fixes an async-only backboardd SIGSEGV (CA layer memory under a NoCopy
buffer read on the replay worker: vm_remap alias plus a length check), makes a failed
submit an Error instead of Completed, counts unticketed destinations, and releases
admission at completion (P25 found a -EBUSY reuse race). P24 proves the j0127
cancelled ACK through the command-buffer path; ticketed-at-replay stays P23-only
evidence (always logged now); a real GPU fault is untested by design (no hang
recovery, reboot cost). **Remaining:** the installation decision (user) and a fresh
panel check on m7close4 if async is to be installed. Preserve ordered callbacks, resource lifetimes, M4 grouping/drains
and M6's sticky fetch restriction. Existing host/backend race cases and isolated
GPU destination regressions are completed evidence; do not repeat them as a
substitute for the compositor/panel gap. No default enablement or installation
follows automatically.

Existing M3/M5 diagnostics assume serialized inline replay/TLS scope. Audit their
thread ownership and coverage before interpreting worker-thread profiles; missing
records must not look like reduced work. Retain M6's sticky sysmem restriction
across worker/context handoffs and any refreshed build.

**Where:** `bgmtl.m` commit/replay/tickets/completion paths; kernel render tickets,
presentation rejection and fallback, starting with patch j0110 and later changes.

**Done when:** The race reproducer, surface reuse and display sleep/wake stress
preserve display protection and recover correctly. Use a bounded set of temporary
boot trials when boot-time epoch coverage requires it, plus affected GPU suites
and the user's panel check. No arbitrary ten-boot quota or aggregate FPS threshold
is required. Document which race scenarios were exercised and why the evidence
covers them. Permanent partition flashing still requires user confirmation.

## M8 â€” Attribute waits, callback delay and long gaps

**Why still needed:** Completion/presentation behavior was not changed by M1â€“M4.
M4's explicit drains remain, but its tail-latency effect was not measured. The
November 1 gaps and old async completion patterns are historical leads, not a
current diagnosed failure. No new whole-system baseline is required to begin.

**Remaining work:** Correlate CB creation/encode, replay start/end, submit-group
drains, scheduled handlers, actual fence completion, completed handlers, ticket
admission and presentation. Use bounded events plus off-CPU stacks. Distinguish
waiting for real GPU work from queue handoff delay, missing producer transactions
or required display protection. Inspect inline behavior now; only interpret async
behavior after M7 is safe. Investigate long gaps only if a current bounded capture
reproduces them or existing evidence establishes their cause.

**Where:** `bg_tm`, command queues and completion code in `bgmtl.m`, framebench and
presentation events, M4 drain instrumentation and targeted scheduler stacks.

**Done when:** A concrete unnecessary handoff/wait has been removed or a suspected
one is shown necessary, with ownership/callback ordering and presentation intact.
Never report scheduled/completed earlier than its contract allows. No lower
whole-frame score is required for verified redundant-wait removal. Any explicit
claim about reduced latency or tail gaps requires matching timing evidence.

## Conditional follow-ups â€” do not reopen completed milestones

- **F1: Linear-buffer uploads.** M1's smaller A8 source and other linear uploads
  remain. Use existing inventory before designing buffer aliasing/coherency or
  dirty tracking. Do not replace the accepted packed-image exact comparison or
  re-run its acceptance decision. Conditional on evidence of another safe saving.
- **F2: Format-500 retry/fallback.** M2 identifies a sampled 1105x1160 IOSurface
  request from QuartzCore; deduplicating output did not remove caller retries or
  wrapper allocation. Establish the format/layout and downstream fallback before
  adding support or negative caching. Keep the proven log reduction.
- **F3: Absent fragment output on MRT (correctness investigation).** M6's rejected
  probe wrote unexpected color1 alpha when the shader omitted color1 but its write
  mask remained enabled. The final probe explicitly masks it off. Create an
  isolated shader/output/write-mask regression and establish required semantics
  from local framework/reference evidence before changing the renderer. No active
  compositor defect or CA mask behavior is established by that probe.
- **F4: Uniform offsets / RWA_CB_DELTA.** Preserve the disabled a5xx path until the
  earlier wrong-shape case has a pixel reproducer and an established cause. Do not
  repeat the already unhelpful uniform-content comparison as a generic fix.
- **F5: Recorded-work allocation or further driver threading.** Only pursue a
  demonstrated residual allocation or serialized-replay cost. M3 already removed
  unused binning and found repeated-resource fast paths; weakening those checks is
  not a task. Further Gallium threading depends on M7's ownership/fence audit.

## Validation and handoff

Build on the local macOS VM, one build at a time; no CI unless the VM is
unreachable or requested. Check the existing regression coverage and add tests
for the actual changed behavior. Reject lost/pending attribution data. Capture
identities/operations without pixel payloads and keep Apple artifacts/device dumps
ignored. Use matched instrumentation/source when making a timing comparison;
pipeline-draining timestamp sums, unions, fence latency and bus bytes are distinct.

A same-stream projection (M4) and exact pixel-checked eliminated operations are
valid work-reduction evidence within their documented assumptions. Preserve M1â€“M4
without repeatedly benchmarking them. When timing is needed, use bounded workloads
and comparable scene/temperature, retain baseline2 as historical reference, and
make no current FPS claim from its old numbers. Restore exact libraries/envs,
verify idle diagnostics and release the shared phone lock after device work.
Update NOTES.md and commit completed milestones, distinguishing source/tested
candidates from the installed runtime.
