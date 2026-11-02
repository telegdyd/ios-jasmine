# M7 callback readiness fix — 2026-11-02

The [M7 review finding](METAL-M7-REVIEW.md) is fixed in Metal commit **b595b76**.
This closes the late-callback bug, not the remaining M7 destination-admission and
compositor-trial work. Compositor async remains opt-in/off; no runtime was installed.

## Behavior

Public command-buffer Error status no longer implies scheduled or completed
callback readiness. Separate flags are zero-initialized with the command buffer.
Registration and delivery use the same `@synchronized(self)` monitor. Before a
delivery finishes, new registrations append to that event's handler queue.

The event's existing delivery point drains a FIFO snapshot outside the monitor,
then drains registrations added during those callbacks. Only an empty drain
publishes Delivered. Consequently a handler added from another handler or another
thread cannot run ahead of the already queued snapshot. Registrations after
delivery retain the previous immediate-delivery behavior, outside synchronization.
No ordering is imposed on arbitrary post-delivery registrations across already
completed command buffers.

Scheduled and completed readiness stay independent. Public Error status remains
Error; ticket/fence retirement still runs through M7's existing paths. External
callbacks never run under the command buffer's monitor. No extra worker, wait,
GPU barrier or context-lock policy was introduced. The runtime and host regression
include the same `src/bg_callback_delivery.h` implementation.

## Validation

**Deterministic Foundation host regression**, macOS ASan/UBSan:

```
sh mesa/metal/test/run-callback-delivery.sh
```

PASS covers registrations before failure, after Error while an earlier CB blocks
completion, while the failed CB's own fence is pending, during handler delivery,
and after delivery. Reentrant and cross-thread registration must remain behind
the current snapshot. The cross-thread registration completes while the original
handler is running, detecting accidental callback invocation under the monitor.
Fifty rounds of 64 concurrent registrations race empty-drain publication and
assert exactly-once delivery. Scheduled readiness and preserved Error status are
checked independently. Restoring the old `_status>=3/4` shortcuts makes the same
test fail its expected-empty-log assertion (negative control).

**Actual runtime GPU regressions:** P21 blocks an earlier completion callback,
executes a later CB with a clear followed by a deliberate oversized-buffer error,
then registers a handler after Error is observed. It verifies the late handler
stays pending, nested registration runs exactly once, post-delivery registration
runs exactly once and Error remains Error. P20 remains the 32-CB mixed-success/
error FIFO/status/pixel test.

| Final-source isolated mode | GPU suite | P21 coverage |
| --- | --- | --- |
| Normal | 37/37 PASS | Late error retirement |
| Compositor, forced sysmem | 37/37 PASS | Late error retirement |
| Compositor, eligible GMEM | 37/37 PASS | Late error retirement |
| Compositor, async replay | 37/37 PASS | Late error retirement |
| Compositor, async + deferred scheduled delivery | 37/37 PASS | Late error retirement and deferred path |
| Compositor, synchronous completion | 37/37 PASS | Queue-blocking P21 deliberately skipped; P20 exercises inline completion |

P20 reports 32/32 scheduled/completed callbacks, zero order/status errors and zero
wrong final values in all six modes. P21's synchronous skip is explicit because
blocking its earlier completion on the calling thread would deadlock the test
setup; host tests cover readiness independently of GPU timing. No compositor
process or physical-panel async test was performed.

VM builds: `m7callbacks` PASS13s, `m7callbacksfinal` PASS14s, final explicit-header
revision `m7callbackverify` PASS13s. Final artifacts:
`xnu/out-mesa-m7callbackverify`. No CI or kernel build.

- Candidate libbgair SHA256: `9f165365fd23f13d8c9bff4adb72896b4c16cd882e2c2a4cfc6003cab1743c48`
- Candidate libbgmtl SHA256: `de9bf3794f63dd953639cd28ca2ca4f47c381c037ac6644effa145fe6b6e1478`

## Device state and remaining work

Only isolated processes used the candidate runtime in
`/private/var/tmp/metal-m7callbacks`. All test files were removed and that directory
was verified empty. All four installed libraries and both compositor/poster env
files were read back before and after and remain byte-exact. No installed file
replacement or setting override occurred. Original compositor M4 and wallpaper
pairs remain active; no async/profiling flags were added to their envs.

Final diagnostics: benchmark active=0/busy=0, profiler idle, GPU completed
1208/1208, power-collapse mode1/on, HWCG on, display on, TSENS max49.8C. Shared
phone lock released. No boot, flash, partition, kernel or clock-policy change.
The preceding temporary m7ack kernel remains the device boot state. Evidence,
readbacks, host/negative controls and six suite logs stay ignored under
`research/metal-m7-callback/`.

M7 remains partial: BEGIN refusals, the eight-ticket cap and all imported writable
destination admission still need their scoped ownership/refusal/retry design,
followed by actual compositor reuse/sleep/wake and panel validation. This fix
does not enable async by default, claim a speedup, or alter M1–M4/M6 behavior.
