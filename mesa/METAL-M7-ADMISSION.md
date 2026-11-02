# M7 imported-write admission â€” 2026-11-02

Metal implementation/tests commit `ef74183`.
Implemented and validated in isolated processes; **not installed**. This closes
the known log-and-proceed BEGIN refusal and silent eight-ticket limit for the
implemented command-buffer texture-write paths. M7 as a whole remains partial:
actual compositor async sleep/wake/reuse, hardware presentation admission and
panel acceptance are still outstanding. Async remains off in the installed M4
runtime. No speedup or elimination-of-work claim is made.

## Ownership and failure policy

- Preserve encode-time BEGIN for render/color/resolve/depth/stencil attachments,
  and acquire before recording blit/mipmap destinations or writable shader images.
  Attachment reservation is conservative: a declared attachment can be reserved
  even if later write masks suppress a draw. Sample-only image inputs are not
  admitted as writable destinations.
- Each CB has a fixed **32-destination** set, deduplicated by imported IOSurface
  identity. The 33rd destination produces an explicit CB Error. A fixed process
  registry has **1024 entries**, with the same fail-closed capacity behavior.
  Neither bound silently permits untracked writes.
- Registry entries retain a standalone ownership token (completion group plus
  committed flag), not a CB or a non-retained pointer to a possibly dying CB.
  Committing enters completion/scheduling groups before publishing the token as
  committed. Successful ticket retirement removes entries. Unresolved destruction
  leaves a bounded quarantined identity, without a dangling object pointer.
- A known **committed** prior producer permits one completion wait, at most one
  second, outside the context lock and callback monitor. The kernel BEGIN is then
  checked again exactly once. Completion of our producer does not override a
  queued/showing/retiring surface, epoch rejection or another unknown owner.
- Uncommitted prior owners cannot be waited on: the caller might need to commit
  them itself. Unknown/quarantined owners, replay-time contention, timeout, capacity
  and refused BEGIN fail explicitly before executing this CB's recorded work.
  The backend does not identify every external refusal as a particular display
  state; those refusals remain authoritative, rather than guessed/retried away.

An admission failure preserves all recorded dependent operations but fails the
**entire** CB before replay; it does not skip one draw/dispatch and execute later
dependent operations. Its callbacks still follow the fixed readiness/FIFO paths,
and Error remains Error. Acquired tickets are ABORTed on the proof that no CB
resource-write work executed. A partial replay error remains different: it still
flushes and requires the existing real drain/proof before relinquishing protection.
Failed retirement preserves unresolved protection and registry state.

## Destination collection and mutable argument records

`bg_work_admission.h` collects colour/depth/stencil attachment destinations,
resolve destinations, texture copies, buffer-to-texture blits and mip generation.
Separate depth and stencil attachment textures are explicitly refused because the
existing renderer has one depth/stencil attachment; it must not silently ignore
the second destination.

New AIR entry points enumerate declared writable image resources from the same
resource/member metadata used by dispatch/draw binding. Both compute and graphics
stages are covered, including argument-buffer members resolved through the
existing encoder records. Read-only resources do not get image-write tickets.
Unsupported/unbound writable images fail collection, rather than execute without
protection. Unsupported vertex image bindings remain refused; this task does not
add new binding features.

Admission accessors retrieve existing buffer/texture objects without refreshing
caller data, copying buffers, binding state or dispatching. At replay, all shader
destination records are resolved again **before any work** under the existing
whole-CB context lock. If an argument record changed to another imported texture,
that destination needs a successful BEGIN too, or the entire CB fails. Replay-time
collection never waits for another producer while holding the outer context lock.
Argument-encoder record mutation uses the same context locking; concurrent unsafely
mutated application memory is not a newly supported synchronization mechanism.

This scope is the implemented recorded-command texture-write paths. Standalone
direct CPU texture API calls outside a CB retain their existing synchronization
contract; arbitrary application aliases/pointers are not discovered by this set.
Existing M1â€“M4, callback delivery, M6 sticky sysmem/feedback protection, kernel
queue protection, barriers and ordered submissions are retained. No BEGIN moved
to a later point as a substitute for missing encode-time protection.

## Validation

Reproducible actual-method Foundation host sanitizer tests:

```
sh mesa/metal/test/run-write-admission.sh
sh mesa/metal/test/run-callback-delivery.sh
```

Admission ASan/UBSan PASS covers 32 destinations, repeated-ID deduplication, the
33rd-target cap, uncommitted owner refusal, known committed producer retirement on
another thread (which needs the same context lock), authoritative external refusal
after that wait, a one-second timeout without another BEGIN, quarantined identities
and process registry capacity. Callback ASan/UBSan remains PASS for late/reentrant/
concurrent delivery, independent scheduling/completion readiness and Error status.

Final build `tools/vm-mesa.sh mesa m7admissiondone`: **PASS, 13 s**,
`xnu/out-mesa-m7admissiondone`. No kernel build or CI. Preliminary builds passed
while the policy/probes were developed. An initial probe link omitted libbgair;
the tool recipe now links it explicitly. A shell CRLF build failure was fixed
before the next build. Neither build failure reached device execution.

Final-source GPU suites: **47/47 each** in normal, compositor sysmem, eligible-GMEM,
async, async+deferred-scheduled and synchronous modes. P20/P21 callback regressions
remain intact (P21's existing queue-specific synchronous skip is unchanged).
New P22 checks:

- All 32 imported destinations clear correctly, covering the old eight-ticket gap.
- The 33rd destination explicitly refuses the CB and a private first-operation
  sentinel proves none of its dependent replay ran.
- An uncommitted same-surface owner refuses without writing; the original producer
  still commits and produces exact pixels.
- A manually opened unknown generation refuses the CB, preserving its dependent
  private sentinel, until the explicit owner acknowledges it.
- Imported texture blits and direct compute image writes complete with exact pixels.
- A writable argument-buffer member changed after encode is admitted at preflight,
  writes the new destination and preserves the original. If changed to an unknown
  pending destination instead, its earlier dependent clear is not replayed.

The argument-member probe uses the existing raw AIR encoding-record API: public
Apple `_MTLFunction` argument-encoder reflection asserts for this shim and was not
added as a feature. A first probe attempt exposed that unsupported reflection and
was rejected. Earlier imported readback checks also attempted reads of intentionally
ABORTed generations; the kernel correctly refuses those reads. Final refusal
tests use private dependent sentinels, and successful read buffers are poisoned
before use so a failed read cannot look like a previous pixel result. The final
argument test uses neutral channels to isolate admission/target identity, rather
than infer unrelated BGRA image-store channel semantics.

Focused MSAA4x memoryless colour/depth/resolve probe: **three iterations each**
with eligible-GMEM selector off/on, exact centre `ffff0000`, corner `ff0000ff`,
zero failures. No driver/shared-GL policy changed in this task. Existing actual
kernel ticket harness results remain the preceding M7 evidence, not new tests here.

Final candidate hashes:

- libbgair: `9306470194d935d627e8221732aa8c38d1e4d753b2d20ab00771ae0219a6c34b`
- libbgmtl: `d9cfc18b14b963407914075414345f9756f249e0dbc646b9f200e467c2d82e72`

## Device cleanup and remaining M7 work

Fresh preflight found the phone's display off, unlike the preceding handoff.
The first imported-target attempt consequently failed closed on suspended ticket
capability; it is not successful pixel evidence. Subsequent isolated tests woke
the display using the existing framebuffer power selector and returned it off in
`finally`. The actual compositor was never put into async mode.

Only `/private/var/tmp/metal-m7admission` held candidate runtime/test files; these
were removed and the directory verified empty. Four installed libraries and both
environment files were read back before/after each diagnostic and again after
the focused extras, byte-identical. Compositor remains M4 `95cea7f9â€¦/3d91c9f6â€¦`,
wallpaper `0d9fb5a2â€¦/eaf44cdeâ€¦`; original env values are unchanged. No production
activation, reboot, flash, partition, kernel or clock-policy change.

Final benchmark/profiler idle, GPU `17873/17873`, power collapse mode1/HWCG on,
display off restored, maximum final TSENS44.0 C; shared phone lock released.
Evidence/backups/scripts/readbacks remain ignored in `research/metal-m7-admission`.

Next M7 milestone: review this policy and its explicit failure behavior, then a
bounded actual compositor async trial across same-surface reuse and display
sleep/wake, including real admission rejection and fault/quarantine behavior.
User panel acceptance and a later installation decision remain outstanding.
No default compositor async enablement or throughput/latency claim follows from
these isolated tests.
