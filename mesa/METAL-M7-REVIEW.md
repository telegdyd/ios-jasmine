# M7 recovery review — 2026-11-02

Reviewed parent implementation `81f714f` and Metal implementation `6bfd22c`,
including patch j0127, ticket retirement, replay/completion changes and new tests.
This is a source/host-test review; no device inspection, reboot, installation or
compositor trial was performed. Last reported device state remains temporary
m7ack kernel with original M4 userland, as recorded in NOTES.md.

## Finding: late callbacks bypass deferred error completion (P1)

The new replay path flushes partial work on an error and puts failed command
buffers on the serial completion queue. However, `bgFailWith:` publishes
`_status=5` before that queue waits for the fence. `addCompletedHandler:` still
interprets `_status >= 4` as completion and invokes a newly registered handler
immediately. A handler registered after replay failure but before the completion
worker drains that command buffer can therefore run while earlier successful GPU
work in that command buffer remains unfinished, and can overtake earlier queued
completion callbacks. A consumer may reuse or modify resources prematurely.

This is an uncovered interaction with the modified error-completion path; the
status-based shortcut itself predates M7. `addScheduledHandler:` similarly treats
Error as evidence of scheduling, even if the partial replay has not submitted yet.

The new P20 test registers every handler **before commit**, so its successful
32-CB FIFO result does not exercise late registration. Its result remains valid
for the tested case, not for all error/callback timing.

**Suggested correction:** Keep scheduling/completion delivery readiness separate
from public error status. Publish those transitions and decide whether to enqueue
or deliver newly registered handlers under the same synchronization. Preserve
the serial completion order for handlers added during failure retirement, and
never invoke external callbacks while holding that synchronization. Cover late
registration while the failed CB is waiting behind an earlier CB, while its own
fence is pending, and after delivery; assert exactly-once ordered delivery.

## Checks performed

- Generated a harness from the assembled patched kernel ticket functions and
  actual `AppleCLCD::rejectFrame` using `test_render_tickets.py`; compiled with
  WSL g++ / ASan / UBSan. PASS for the existing normal fences, cancellation ACK,
  ownership/epoch/proof/refusal/reuse/idempotence and reason-16 checks.
- Compiled the runtime `ticket_retire_test.c` with WSL gcc / ASan / UBSan. PASS
  for successful SEAL, drain/ABORT after refusal, failed waits/ABORT retaining
  entries, and missing seqno.
- Copied the actual current `addCompletedHandler:` method into a minimal
  Foundation host class on the macOS VM. Set the replay-error status before any
  completion delivery and registered a handler: it ran immediately. This is a
  deterministic status/readiness reproducer, not a real GPU or panel race test.
- Evidence remains ignored in `research/metal-m7-review/`. WSL clang was absent;
  available GCC tools ran the sanitizer checks. No kernel/Mesa rebuild or CI.

## Remaining scope and recommendation

No additional kernel ACK defect was established by this review. Host stubs do
not establish real presenter behavior, concurrency coverage or fault recovery.
The report correctly distinguishes backend epoch probing from display-record
admission and physical-panel testing.

Keep async disabled. Alongside the callback finding, retain the report's known
admission work: BEGIN refusal currently proceeds, the eight-ticket cap silently
stops coverage, and imported compute/blit/depth/stencil destinations lack complete
admission. A bounded destination set and ownership-aware refusal/retry need their
own correctness cases. Actual compositor sleep/wake/same-surface reuse, reason-16
admission on hardware and true-fault fallback coverage remain unestablished.

The cancellation ACK and partial-error flush are useful correctness milestones;
they do not close M7 or demonstrate an installed optimization. Next implementation
should address admission and callback delivery readiness before an async compositor
trial. No changes to runtime behavior were made during this review.
