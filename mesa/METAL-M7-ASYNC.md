# M7 — cancellation recovery and replay ownership (partial)

2026-11-02. **M7 remains partial.** The cancellation/submit race now has a
deterministic reproducer and a tested recovery fix. Async compositor replay is
still opt-in and has not been installed or promoted. Admission/refusal coverage
and an async compositor/panel trial remain necessary. No speedup is claimed.

## Established failure and implemented recovery

The host harness compiles the actual assembled kernel functions, with stubs for
locks, display ownership and reference releases. On the old source:

1. BEGIN retains the surface backing and records its owner/generation/epoch.
2. Display-off cancels the pending generation and advances the render epoch.
   The backing stays retained until the producer acknowledges its writes.
3. The producer submits and calls SEAL. The old terminal-status branch returns
   `kIOReturnAborted` without detaching the backing.
4. Metal ignored that return and discarded its ticket list. The presenter cannot
   establish cancellation quiescence while the backing remains attached.

The unmodified source fails the harness's cancellation acknowledgement assertion.
Patch **j0127** accepts a valid post-BEGIN submit proof as an acknowledgement for
an explicitly cancelled ticket. It detaches backing and records the seqno while
keeping `status=2` (aborted) and `cancelled=true`. The generation never becomes
ready, even after that seqno completes. Wrong owner, wrong epoch, absent/evicted
proof and changed owner error count do not release backing. Repeated ACKs are
idempotent only for the same seqno.

Existing job retains and the presenter's backing/GPU-seqno checks cover execution
after the acknowledgement. A cancelled queued frame still must quiesce before
its snapshot can be released. This does not permit unprotected writes or make a
cancelled frame displayable. Normal next-generation admission remains subject to
pending backing and queued/scanning/retiring/quarantined surface checks.

`rejectFrame(...,16,...)`, the non-candidate ticket-readiness failure seen in the
historical boot, now drops that transaction while retaining the protected queue
and previous displayed frame. Other fallback reasons are unchanged. This is a
scoped correction, not a general recovery implementation for every GPU/display
fault or timeout.

## Metal worker and retirement changes

- Check every ticket SEAL/ABORT result. A refused SEAL or missing seqno requires
  a successful fence drain before ABORT relinquishes ownership. Failed waits or
  acknowledgements retain unresolved entries; deallocation cannot turn an
  unknown in-flight write into an unprotected abort. Such failures remain errors,
  not successful recovery claims.
- Flush earlier recorded work even when a later replay operation fails. The old
  error path could omit the flush and then abort the tickets.
- Hold the context mutex throughout one replay. The former per-work unlock let
  encoding/context operations enter a replay whose shared refresh epoch and
  M3/M4/M5 profiling scopes were still active. The fair mutex now hands off at
  command-buffer boundaries. This protects ownership; reduced lock latency is
  not established.
- Deliver failed command buffers on the serial completion queue, alongside
  successful ones, and preserve error status after their fence wait. The old
  inline failure branch could overtake earlier pending completions. Bound
  completion-thread Objective-C temporaries with an autorelease pool.

The tested C retirement helper is used by the runtime, rather than duplicated
in its tests. P20 queues 32 command buffers, releases encoding autorelease pools,
injects a deliberate oversized-buffer draw error in the middle, and checks
scheduled/completed ordering and status plus exact final target pixels.

M1–M4 implementation and M6's sticky feedback/sysmem constraint are retained.
FIFO GPU submissions, group limits and required drains are unchanged. Holding
the context across replay removes one known profile-scope interleaving hazard;
it does not establish complete worker-thread attribution. No worker profile is
interpreted as a measured work reduction in this milestone.

## Validation

Local VM only; no CI:

| Build | Result | Artifact |
| --- | --- | --- |
| Kernel `m7ack` | PASS, 55 s | `xnu/out-jasmine-m7ack` |
| Mesa `m7retire` | PASS, 14 s | preliminary retirement implementation |
| Mesa `m7fifo` | PASS, 13 s | queued success/error callback regression |
| Mesa `m7epoch` | PASS, 14 s | adds isolated hardware epoch probe |

The final two Mesa builds' library pairs are byte-identical. An initial temporary
image-helper invocation failed due to CRLF in its argument; line endings were
corrected and the image was built before any boot attempt. One temporary
`fastboot boot shim/out/shim-boot-m7ack-m7ack.img` succeeded. No partition flash.

- Actual-source host harness: old source reproduces the retained-backing failure;
  patched source passes ASan/UBSan. Covers normal incomplete/completed fences,
  epoch changes before/after submit, query/BEGIN stale epoch, suspension and closed
  owner, wrong owner/epoch/proof, pending reuse, display states 1–4, repeated ACK,
  next generation and actual reason-16 rejection policy. Host display-state stubs
  are not physical panel evidence.
- Runtime retirement helper ASan/UBSan: successful SEAL, refused SEAL followed by
  drain/abort, failed wait retaining ownership, failed ABORT, and missing seqno.
- GPU suites: **36/36** each normal, compositor sysmem, eligible GMEM and async
  compositor mode on the pre-existing kernel. Full async suite repeated on the
  temporary M7 kernel: **36/36**. P20 has 32/32 scheduled/completed callbacks,
  zero order/status errors and zero wrong final values in each run.
- Isolated hardware backend probe on M7 kernel: normal submission, display epoch
  cancellation before replay/submit, and cancellation after submit/before SEAL.
  Generations 1–6, epochs 2–4, seqnos 28–33; every SEAL and fence wait succeeds.
  Each cancellation recovers on the **same backing**, then a fresh generation
  produces exact green/alpha pixels. A second BEGIN while pending is refused.
  The probe submits no display record and does not exercise compositor admission.
- Hardware trace: **57 events, zero dropped**, no CPU samples. Two event-37
  cancellation records (`reason=2`) are followed by cancellation submit ACKs
  (`reason=3`, seqnos 30 and 32). Event 35 includes epoch changes and the
  unconditional framebuffer-client-close notification; these are not all queue
  fallbacks. The bounded boot log has no `QUEUE FALLBACK`, panic or GPU-fault
  diagnostic. No assertion that reason-16 presentation rejection was exercised
  on hardware: that branch is covered by the actual-source host test.
- New-kernel MSAA 4x colour/depth/resolve, three iterations each selector off/on:
  exact red centre/blue corner. Shared GL sysmem and forced-GMEM: `PASS: all`.

## Remaining admission audit — do not enable compositor async yet

`bgTicketFor:` still logs BEGIN refusal and proceeds, and silently stops collecting
after eight tickets. Render encoding covers colour/resolve attachments, but
depth/stencil, writable compute textures and blit destinations do not have a
complete imported-surface admission policy. These are source observations, not
claims that a current CA frame actually uses each path. The isolated GPU suites
do not prove that ignored refusal is safe under delayed worker replay.

Next: collect a bounded per-command-buffer set of actual imported destinations;
cover all writes before they can execute; distinguish a prior worker's pending
generation from a displayed/retiring surface; and define bounded refusal/retry
that preserves ordered callbacks and the last valid displayed frame. Do not move
BEGIN to replay without proving protection for earlier CPU/GPU writes and display
admission. Do not silently discard dependent recorded work or use a boot-long
protection fallback as recovery. Then exercise queued same-surface reuse and the
actual compositor across display sleep/wake and obtain the user's panel check.

The hardware probe deliberately tests the backend protocol directly on an
offscreen surface. It is not a worker/compositor race reproducer or a panel test.
True-fault fallback/quarantine beyond reason 16 remains unaudited for async.

## Final device state

All four installed libraries and both environment files read back byte-exact to
preflight. Compositor remains M4 (`95cea7f9…` / `3d91c9f6…`); wallpaper remains
`0d9fb5a2…` / `eaf44cde…`. Environment files contain only
`CA_DISABLE_FRAMEBUFFER_COMPRESSION=1` and `BGMTL_POSTER_SDR=1`, respectively.
No async or profiling flag was added to either process. No compositor/wallpaper
library replacement took place. Isolated binaries were removed and the remote
`metal-m7` directory verified empty. Diagnostics idle; shared phone lock released.

The phone remains on temporary **m7ack** with the original installed M4 userland;
a normal reboot returns to the installed boot image. No permanent activation is
pending. Evidence, downloaded/readback binaries, boot logs and event records stay
ignored under `research/metal-m7`. See NOTES.md for final commits and idle state.
