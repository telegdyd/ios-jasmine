# Task 24: source audit and bounded batch graph

2026-10-26. Implementation started under the approved
[plan](PERF-TASK24-PLAN.md). This milestone prepares diagnostics, not a rendering
optimization. No performance gain is claimed.

## Source provenance and findings

WSL access works with the sandbox permission override. Extracted a separate tree
from local Mesa tag `mesa-26.2.5`, commit
`f9ce5e81f30cd694726bff6d8197e509a8374ea7`, using `git archive`, then applied every
current repository patch in filename order. No shared Mesa checkout was edited.
Ignored reproduction scripts, exact source path, patch hashes and results are
under `research/t24/` (`prepare.sh`, `source-path.txt`, `patch-hashes.txt`,
`upstream-revision.txt`, `check.py`, `checks.json`).

The complete source confirms the barrier route:

1. `src/mesa/main/barrier.c::_mesa_TextureBarrierNV` sends
   `PIPE_TEXTURE_BARRIER_SAMPLER` through `ctx->pipe`.
2. `u_threaded_context.c` queues `texture_barrier` using `TC_FUNC1`. It reaches
   the driver thread in order with surrounding draws.
3. `freedreno_context.c::fd_texture_barrier` calls `fd_context_flush`.
   With reordering, that function adds flush dependencies to the last batch
   and flushes them unless the call is deferred. Removing this call is broader
   than replacing one batch-end packet: it can change when other batches retire.
4. Resource reads separately flush a different pending writer;
   resource writes order prior readers/writers. These rules must remain intact.
   They explain why framebuffer switching alone does not give a safe merge rule.

`a5xx/fd5_emit.h::fd5_cache_flush` writes the UCHE invalidate registers and then
waits for idle. It does **not** emit a color-cache flush. Existing sysmem finalization
in `fd5_gmem.c` emits `PC_CCU_FLUSH_COLOR_TS` and `PC_CCU_FLUSH_DEPTH_TS`.
`fd5_context.h::fd5_emit_flush` emits `CACHE_FLUSH_TS` and `WAIT_FOR_IDLE`.
These are useful existing primitives for an experimental retained barrier, but
their composition has not been checked by a GPU pixel test in this project.
UCHE invalidation alone must not be substituted for the current barrier.

`fd5_clear` emits fast-clear state and `CCU_RESOLVE` operations into the draw
stream, then disables fast clear. Common clear tracking updates the full scissor,
clear/restore masks and resource dependencies. A batch that later clears must
not silently leave any proposed retained-barrier subset. First candidate design:
single color attachment, no depth/stencil or MSAA, no existing clear/prologue,
global sysmem forced, durable per-batch bypass marker; split before subsequent
clears. This is a proposed subset, not yet implemented or device-validated.

GMEM choice is late. `fallback_use_bypass` chooses GMEM for a clear, any GMEM
reason, more than five draws, or MSAA. a5xx has no historical sample-based
autotune opt-in. Thus many small blended batches are admitted in the old GMEM
experiment. The batch scissor is an inclusive union, not a measurement of actual
pixel coverage. The GMEM key rounds its origin down to device alignment. a5xx
tile preparation programs resolve endpoints from clipped tile bounds; resolve
destinations use the resource's actual offset/pitch/layer stride. This improves
the address audit, but does not prove hardware burst/overfetch bounds for every
imported layout. No padding increase or GMEM default change is justified yet.

## Diagnostic implementation

Added `0007-freedreno-bounded-batch-graph.patch` and the Darwin trace controller.
The controller is independent of DRAWPROF, disabled unless explicitly enabled,
and uses one shared time window and event budget across contexts/threads.

```text
SWEETCA_BATCH_TRACE=1
SWEETCA_BATCH_TRACE_DELAY=300       # seconds after library constructor; max3600
SWEETCA_BATCH_TRACE_SECONDS=25      # max120; 0 disables
SWEETCA_BATCH_TRACE_EVENTS=12000    # max30000; 0 disables
```

Invalid numeric options fall back to defaults. The armed record prints the
effective values. First activity after the delay prints `start late_ms=...`.
The event cap or next activity after the deadline emits one terminal `stop`
record. An idle process does not wake just to print the deadline marker.
All ordinary records share a monotonically increasing sequence. Lines are
bounded; truncation is explicit. Clock failure/backward time stops the trace.

Events record screen/context/batch identity; target resource/BO, dimensions,
format/level/layers, offset and pitch; conservative bound sampler views and
same-BO target aliases; draw counts, scissor union, masks/cost; actual flushes,
context-flush flags, read/write and batch-flush dependency edges; and the chosen
sysmem/GMEM/nondraw mode. Pointer identities are temporary diagnostic hints,
not lifetime-retained objects. Do not join recycled pointers across lifetimes.
Bound views are explicitly **not proof of active shader reads**, and same-BO
identity is a conservative alias test, not proof of overlapping subresources.

Driver-thread scopes distinguish texture barriers, resource reads/writes,
capacity checks, periodic kicks and frame-submit drains. Generic context flushes
are labelled separately. The old aggregate DRAWPROF categories are unchanged;
their wrapper-thread scopes cannot be assumed to survive TC callbacks.

At the end of each CA `w_Flush`, a trace-only FIFO callback labels that context's
completed flush number. It does not submit, wait, or create a driver batch. Its
allocation/queue/logging overhead makes traced frame timing unsuitable for
performance comparison. Markers delimit **CA flush intervals**, not physical
display frames or presentation retirement. The default-off path does not queue
these callbacks. Production rendering/barrier/GMEM/kick defaults are unchanged.

Analyze a complete log with:

```text
python tools/g2/batchgraph.py LOG --json research/t24/graph.json
```

The parser excludes the leading/trailing partial flush intervals independently
for each context, rejects record gaps/truncation and nonconsecutive/lost frame
markers, and separates carry-in/unseen-draw batches. Its summary distinguishes
potential feedback from batches without observed bound-alias evidence; the
latter are **not automatically safe or profitable GMEM candidates**. Inspect
the event log for graph order, target area and clear/layout constraints.

## Validation and next action

- All seven Mesa patches apply in order to the pinned source.
- Four touched driver translation units pass local GCC syntax checks with
  diagnostic code enabled via `__APPLE__`, and with the ordinary Linux guards:
  eight checks, no warnings. These reuse the existing host build's generated
  headers and do not establish iOS ABI/link correctness.
- `mesa/darwin/test_batch_trace.c` compiles with
  `-std=gnu11 -Wall -Wextra -Werror -pthread` and passes disabled/delay/deadline,
  four-thread shared-cap, nested TLS-cause, malformed/zero-option and clock-failure
  tests against the actual controller implementation. Log assertions verify
  no out-of-window records and one cap/deadline terminal marker.
- Five parser tests pass, including interleaved contexts, carry-in batches,
  incomplete intervals, missing/truncated/malformed records and marker loss.
- iOS CI, device boot, installed-library hash and graph results are pending.
  No phone access has occurred in this milestone.

Follow-up: implementation `ccd9a88` pushed. First Mesa CI `40247120431` failed
because `fd_bt_draw` needed the existing `assert_dt` annotation for Clang's
thread-safety analysis of `bound_shader_stages`. The annotation is now added;
no warning suppression or runtime threading change. GCC checks and controller
tests pass again; the repaired iOS build remains pending. User confirmed the
phone free, own shared lock acquired, exact production library backed up and
verified as `14e32aea...`; baseline GPU588/DDR1804 observed. No test install or
boot yet. Current session state is in root NOTES.md.

**CI/boot milestone, 01:12 Budapest:** repair `ad9d787`, Mesa CI `40247556888`
passed (first failed run retained above). Signed library SHA256
`0a8d5fac5e28f6a92798bc176d6a373367f2fc67d99dcf44a10ffba4076e102f`,
20,442,096 bytes; diagnostic strings and exact installed test-name readback
verified. New GL test passes all seven steps, including sampler subchecks,
104.8 ms, exit0. Temporary image SHA256
`8d1b50d51c7855efa19345a3ae59b02d9c695f071991d8a6019bf29e7514c9ec`
booted at01:10:53; pipeline0/GPU588/DDR1804 and original j70 slot-b kernel/ADT.
Home swap-surface screenshot checked visually. Trace configured300s delay,
40s window,30000 ordinary events. Session/precheck/graph and restoration are
in progress, not yet results. Production library is untouched and backed up;
own shared phone lock remains held. No partition flash or optimization/default
change. Startup self-test FSR0x400 matches the baseline.

Next: build this diagnostic with Mesa CI, verify the artifact and prepare one
test-name library/temporary boot session once the phone is free. Run only a
bounded Home/CC/NC graph after the accessory-sync precheck; use the current
production pipeline and clocks. Preserve production rollback artifacts. If the
sync has not ended before the configured window, skip the measurement rather
than label a busy-startup graph as steady state. No speed benchmark or default
installation is justified by this diagnostic milestone.

The graph and source audit together will determine whether the proposed narrow
barrier candidate is worth implementing and how much GMEM-eligible work remains.
The current code deliberately retains all rendering barriers and dependencies.
