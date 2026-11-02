# Metal performance tasks

Status (2026-11-02): M1's packed-image upload elimination is accepted and enabled
by default: verified unnecessary uploads are removed with pixel correctness
preserved. See [M1 results and decision](METAL-M1-UPLOADS.md).
M2 is implemented and validated (2026-11-02): exact repeated refusal output is
removed, with 30/30 normal and compositor GPU checks. See
[M2 results and remaining format question](METAL-M2-REFUSALS.md).
M3 removes unused binning state emission for forced-system-memory batches;
the inventory measures one state emission per draw instead of two. See
[M3 results and safety boundary](METAL-M3-STATE.md).
M4 now bounds deferred submission groups instead of rejecting individual
30-BO batches: 121 observed kernel calls, versus 157 projected by the old policy
on the same recorded batch stream; final normal/compositor/opt-out suites pass
32/32. See [M4 results and measurement limits](METAL-M4-SUBMITS.md).
M5 instrumentation and compositor attribution are implemented; full-screen
two-attachment passes supply an M6 candidate. Wallpaper GPU-time/traffic
attribution remains open, so M5 is partially complete. See
[M5 evidence and remaining client gap](METAL-M5-PASSES.md).
M6 is partially investigated: corrected Metal feedback eligibility, validated
sysmem/GMEM selection, and rejected unproven attachment removal/global GMEM.
No traffic optimization promoted; see [M6 audit and remaining work](METAL-M6-TRAFFIC.md).
M7-M8 remain proposed.

User clarification: optimize unnecessary work, not benchmark scores. A verified
work reduction with preserved correctness does not require an aggregate FPS or
CPU-time speedup for acceptance. Reuse recorded baselines and keep validation
bounded; do not roll back useful optimizations merely because a noisy whole-frame
capture shows no speedup.

Evidence: [fresh profile](METAL-PERF-20261101.md). Earlier experiments and known
failure cases: [speed ideas](METAL-SPEED-IDEAS.md), [step 7](METAL-STEP7.md).

The recorded baseline is j0126 with the clean ccfix libraries: roughly 36 Home and
31–32 Control Center swap arrivals/s. Render CPU is approximately 25/29 ms per
update; whole-GPU busy work is approximately 20 ms per swap in separate counter
windows. These estimates overlap, use different windows, and cannot be added.
60 updates/s provides a 16.7 ms budget: CPU and GPU both need improvement.

## Order and dependencies

| ID | Task | Priority | Dependency | Main outcome |
| --- | --- | --- | --- | --- |
| M1 | Attribute and reduce CPU texture uploads | First | Upload inventory before implementation | Less CPU copying and upload traffic |
| M2 | Deduplicate repeated refusal diagnostics | Early, contained change | None | Less logging on the render thread |
| M3 | Reduce state emission and resource tracking | Next | Batch/draw inventory | Less CPU work per draw/batch |
| M4 | Reduce flush and submission overhead | Next | Dependency graph and submit inventory | Fewer unnecessary batch/submit operations |
| M5 | Attribute GPU time and traffic by pass/client | Early investigation | None | Identify the real GPU traffic sources |
| M6 | Reduce GPU intermediate/copy traffic | After M5 | M5 attribution | Less RAM traffic and GPU busy time |
| M7 | Make asynchronous replay safe | Larger change | Reproduce and fix ticket race first | Overlap CA work with driver replay |
| M8 | Identify remaining completion/presentation stalls | After earlier savings; record timeline earlier if useful | Safe M7 for async conclusions | Shorter frame chain and fewer long gaps |

M1 and M5 supply the most useful missing evidence. M2 is a small independent
candidate. M3/M4 overlap: one successful batch change can affect both, so measure
them separately before claiming combined savings. This ordering does not authorize
simultaneous device workloads or concurrent VM builds.

## M1 — Attribute and reduce CPU texture uploads

**Why:** `rwaTexture -> rwa_texture_write -> util_copy_box -> memmove` accounts for
approximately 24% of render CPU on Home and 17% in Control Center. That is roughly
5–6 ms per sampled update: the largest directly measured target in our code.

**Work:** Add opt-in, bounded aggregate diagnostics for refreshed textures. Record
source kind (`_linSrc`, `_ncBytes`, copied IOSurface), dimensions, pixel format,
mip count, source/resource identity, bytes uploaded and upload count per frame.
Separate first upload, content update and repeated unchanged content. Attribute the
largest sources before choosing an implementation. Investigate a GPU-readable alias
of buffer-backed linear textures where layout, alignment, lifetime and cache
coherency permit it. Otherwise use an existing producer modification generation if
one is valid, or retain a copy path for mutable sources. Diagnostics must not dump
pixel payloads or print one line per draw in the performance build.

**Where:** `mesa/metal/src/bgmtl.m`, especially `rwaTexture`, `rwaTextureSampledLocked`,
`newLinearTextureWithDescriptor:...` and `newTextureWithBytesNoCopy:...`;
`mesa/metal/air/air_metal.c`, texture creation/import/write paths.

**Risks:** Caller memory can change between commits without our knowledge; pointer
identity does not establish unchanged contents. Sharing backing memory changes
synchronization and ownership. Respect mip/block pitches, unaligned rows, CPU cache
cleaning, CPU blits and resource destruction. A hash/memcmp pass may cost as much as
the upload. `RWA_LINEAR_SAMPLED` already exists; enabling it alone is not proof of
zero-copy aliasing of caller memory.

**Done when:** The largest upload sources and their lifecycle are documented; one
safe path demonstrably avoids unnecessary uploads while preserving mutable
contents. CPU/frame measurements provide context, not an aggregate-speedup gate.
Pixel tests cover initial data, mutation after creation and between commits,
multiple draws per commit, CPU blits, and relevant mip/compressed formats. The
normal and compositor GPU correctness suites pass, including derivative edges.
The full 5–6 ms is an opportunity bound, not a promised saving.

## M2 — Deduplicate repeated refusal diagnostics

**Why:** Rejected pixel-format-500 sampled textures generate repeated messages with
tracing off. `bg_log` takes about 3%/2% of render CPU on Home/CC; kernel console
transmission also appears in the profile.

**Work:** Retain the first useful error and aggregate identical repeats with a
bounded key/count table or rate limit. Emit a periodic suppressed-count summary;
keep distinct failure reasons visible. Separately record which caller requests
format 500 and whether refusal causes repeated allocation attempts or a costly
fallback. Establish the private format's meaning from local evidence before
considering support; format support is a separate follow-up if justified.

**Where:** `bg_log` and texture-creation refusal paths in `bgmtl.m`.

**Risks:** Hiding new failures, unbounded diagnostic state, synchronization overhead,
or accidentally altering fallback behavior while changing logging.

**Done when:** Repeated failures produce bounded output; new reasons remain visible;
the renderer returns the same result for unsupported textures. Verified skipped
log/console operations establish work reduction; matched profiles can supply CPU
context but are not a promotion gate under the user's clarification above.
Any gain from format support requires its own
correctness evidence and measurement.

## M3 — Reduce batch state emission and resource tracking

**Why:** CC spends about 11% of render CPU under `fd5_emit_state` and 6% under
`batch_draw_tracking` (Home: roughly 7% and 4%). Existing equal-bind caching already
removes some per-draw work; remaining cost includes new-batch re-emission.

**Work:** Count render passes, batches, draws per batch, dirty-state transitions and
resource insertions per command buffer. Identify repeated tracking of the same
resource and full state emission after target changes. Then make one focused
change: deduplicate a proven repeated reference, narrow invalidation where valid,
or avoid a redundant pass/batch transition. Preserve the driver state that must be
restored for each independently executable command stream.

**Where:** `air_metal.c` state cache/binding paths and the patched Mesa a5xx
`fd5_emit_state`, `fd5_program_emit`, batch resource-tracking code. Keep repository
patches synchronized with any edits to the build tree.

**Risks:** Missing dependencies, stale constants/samplers/attachments, or freed
resources used by a later submission. State can be unchanged in the application
and still need re-emission in a new GPU batch.

**Done when:** Fewer measured state/tracking operations preserve draw results
across target switches, resource rebinding,
feedback, destruction/recreation and new command buffers. Report overlapping
costs as inclusive rather than adding their percentages. CPU per matched frame
provides context; verified unnecessary-work elimination is sufficient under the
user's acceptance criterion above.

## M4 — Reduce batch flush and kernel submission overhead

**Why:** `flush_submit_list` accounts for around 3% Home / 5% CC render CPU. The
sampled timeline averages roughly 2 Home and 3–4 CC jobs per update. Some batches
are dependencies between offscreen passes; fewer submissions may also reduce
state/allocation churn.

**Work:** Record a bounded graph of batches, resource read/write dependencies,
flush reasons, kernel submissions and buffer counts. Distinguish required GPU
ordering from an avoidable CPU flush or kernel call. Check whether Metal gets the
same applicable bounded dependency handling as the existing GL path. Evaluate
deferred submission or aggregation without changing draw order or dropping
framebuffer-fetch barriers. A multi-batch submission and a merged GPU batch are
different changes and should be tested independently.

**Where:** `air_metal.c` render/flush paths, Mesa batch dependency handling,
`flush_deferred_submits` and `flush_submit_list`, relevant `mesa/patches`.

**Risks:** Dependency cycles, longer queue latency, early ticket sealing, missing
cache barriers and hangs when a texture transitions from render target to sample.

**Done when:** Submits or avoidable flushes per matched update decrease, with lower
submission CPU and no increase in long gaps/queue latency. Read-after-write,
framebuffer fetch, MSAA resolve and present-ticket correctness remain intact.

## M5 — Attribute GPU time and traffic by pass and client

**Why:** Whole-GPU counters show roughly 52% RAM-starved/busy cycles and about
20 ms GPU busy per swap in separate counter windows. They include wallpaper and
other clients, so they do not identify which compositor pass is responsible.

**Work:** Collect bounded per-client and per-pass timing/traffic evidence. Group
passes by target dimensions, format, sample count, attachment count, load/store
actions, clears, copies, resolves and feedback. Correlate these with GPU timestamps
where supported and job events. Separate compositor from wallpaper work while
preserving the visible workload. Measure instrumentation overhead and obtain an
uninstrumented reference. Record actual counter duration (currently clamped to
10 seconds), power-state handling and temperatures.

**Where:** `bgReplayFrom:` pass boundaries, `air_metal.c`, existing Mesa GPU profiling
patches and kernel counter/event tools.

**Risks:** Profiling can serialize work or alter batch selection; submit-to-fence
latency includes queueing and observation delay. Whole-GPU counter ratios alone
do not prove a pass is bandwidth-bound or that all stalled cycles are removable.

**Done when:** A ranked pass/client inventory explains the major GPU cost and
identifies a concrete M6 candidate. Report execution timing separately from fence
latency and avoid attributing wallpaper cycles to backboardd.

## M6 — Reduce intermediate, copy and sysmem GPU traffic

**Why:** CPU savings alone do not remove the measured GPU work exceeding one
16.7 ms period. Full-screen intermediates, blur chains, copies and attachment
traffic are candidates; M5 must establish their actual contribution.

**Work:** For the largest measured candidate, eliminate redundant copies or
intermediates where the consumer can safely use the existing resource. Audit
attachment load/store actions and resolve requirements. Evaluate GMEM for passes
without the framebuffer-fetch restrictions that require sysmem. If batching policy
is global, investigate safe per-pass selection instead of assuming all passes
need the same policy. Treat MSAA resolves and derivative helper lanes as required
correctness behavior; they cannot be removed to improve timings.

**Where:** Metal pass recording/replay, `air_metal.c` attachment and feedback paths,
a5xx GMEM/sysmem selection and the existing MSAA/feedback Mesa patches.

**Risks:** Lost preserved pixels, invalid partial redraws, feedback corruption,
unsupported GMEM combinations and silent missing resolves.

**Done when:** Matching pixels and UI behavior accompany lower GPU bytes/busy time
on the target pass and lower end-to-end frame cost. Cover partial redraws,
rounded edges, blur borders, multiple attachments, MSAA and wallpaper rendering.
Do not change visible blur quality or resolution merely to make a benchmark faster.

## M7 — Make asynchronous command replay safe

**Why:** Earlier r26 experiments improved CC swap throughput by about 15% by
moving replay off the CA render thread. That is historical evidence, not a gain
reproduced on the current runtime. A boot-time stale render ticket caused permanent
presentation fallback and visible corruption; async therefore remains disabled.

**Work:** Reproduce the encode-to-submit ticket/epoch race with bounded diagnostics.
Document ticket ownership, begin/seal/abort and display-epoch changes. Design a
recovery that preserves display protection—for example, reject/drop an invalid
frame while retaining the last valid displayed frame, then recover on a valid
ticket. Evaluate beginning tickets later only if it still protects all writes.
Check surface reuse, context-lock contention, command-buffer lifetime and scheduled/
completed callback ordering before enabling worker replay experimentally.

**Where:** `bgmtl.m` ticket helpers, commit/replay worker and completion handling;
kernel render tickets / `rejectFrame` / presentation fallback logic, beginning
with `xnu/patches/j0110-jasmine-render-tickets.patch` and later patches.

**Risks:** Drawing into displayed memory, tearing/black bands, stale-ticket loops,
deadlocks and reporting command completion before GPU work is finished. Never
present an untracked in-flight surface as a performance workaround.

**Done when:** A targeted race reproducer passes, approximately ten temporary boot
trials and display sleep/wake/reuse stress show no persistent fallback or exposed
in-flight drawing, and normal/compositor GPU suites pass. Obtain the user's visual
panel check before promotion; quantify fresh inline/async differences on matched
settled runs. Kernel builds use the VM; permanent flashing still needs confirmation.

## M8 — Identify remaining completion and presentation stalls

**Why:** Earlier async traces suggested CA often starts a frame after the previous
command buffer completes. Current runs show isolated 170–200 ms CC gaps and longer
Spotlight boundary gaps, but do not establish their cause. Current render-runnable
time is tiny, so scheduler placement is not the first optimization.

**Work:** Correlate frame/command-buffer creation, encode, commit, replay, submit,
scheduled handlers, actual fence completion, completed handlers, swap admission
and presentation. Include off-CPU stacks and producer activity. Separate CPU/GPU
work from unnecessary queue handoffs, delayed notifications, display protection
and missing new transactions. Investigate repeatable long gaps separately from
steady-state throughput. If a callback or handoff adds avoidable delay, shorten
that path while preserving Metal completion semantics and render-ticket protection.

**Where:** `bg_tm`/command queues/completion handlers in `bgmtl.m`, framebench events,
presentation/ticket diagnostics and scheduler stack samples.

**Risks:** Declaring completion prematurely, reordering callbacks, allowing excess
frames in flight or increasing touch latency while improving throughput.

**Done when:** The slow frame chain has an attributed cause; any change removes
the measured delay, preserves callback order and protection, and improves either
tail gaps or end-to-end latency without harming the other. CPU samples alone are
insufficient proof of what a sleeping thread waits for.

## Follow-up tasks if the next profiles justify them

- **Uniform uploads / `RWA_CB_DELTA`:** Reproduce the earlier wrong-shape result
  with offset uniform blocks, establish a5xx addressing/cache behavior, and build
  a pixel regression before enabling the optimization. Its present benefit has
  not been quantified separately; do not repeat the expensive uniform memcmp
  experiment that already lost performance.
- **Recorded-work allocation/lifetime:** Command-buffer deallocation currently
  costs around 2% of render CPU. Profile BGWork allocation, retains and frees;
  consider an arena/C record array if those costs remain material. Preserve retained
  resources, blocks, error exits and asynchronous lifetimes. This is smaller than M1.
- **Threaded Gallium context:** After safe async replay, evaluate a further driver
  worker only if replay remains serially critical. Audit context ownership,
  transfers, readbacks and fences first; another queue can add latency or copies.

## Shared validation and handoff

Each implementation needs its own matching build and correctness gate before a
performance decision. Build on the macOS VM, one build at a time. Compare repeated,
settled workloads with matching wallpaper/UI/clocks and comparable temperature;
record exact binaries and environment. Prefer loss-free A-only CPU sampling to a
full buffer from A+B sampling. Validate uninstrumented builds and report CPU per
update, upload/submit counts, GPU work and tail gaps alongside swap arrivals/s.
These measures are not physically validated displayed FPS, and percentages from
inclusive stacks must not be summed. Verify settings restoration and update
NOTES.md after each milestone. Keep device dumps and Apple artifacts ignored.
