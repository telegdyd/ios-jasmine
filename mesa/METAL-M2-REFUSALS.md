# M2 — repeated texture refusal diagnostics

Implemented in Metal commit `8c82bae` on 2026-11-02. Exact repeated texture
creation failures avoid logging while retaining the original refusal result.
This removes verified unnecessary output; no aggregate CPU or FPS gain is claimed.

## Behavior and bounds

`bg_texture_refused` aggregates `(creation path, complete reason)` in a fixed
16-entry table with 512-byte reason storage, protected by a dedicated mutex.
The first original message is unchanged. Subsequent identical failures increment
a saturating 64-bit count instead of entering `bg_log` (stderr, console, and
optional trace-file output). Every five seconds of refusal activity, pending
counts are printed with their original reasons. No timer or worker is added.
An idle process can retain an unreported final partial interval until another
refusal; process exit does not flush it.

Different reasons and ordinary/no-copy creation paths remain separate. Replacement
flushes pending counts before announcing the new reason. A key longer than storage
is printed normally rather than truncated into a false match. Consequently,
arbitrary distinct-reason churn can still print repeatedly; the output reduction
applies to recurring failures fitting the bounded working set. Other diagnostics
are unchanged. Successful creations do not enter this code.

No texture formats, resource ownership, return values, fallback decisions,
rendering, clock settings, or scheduling policies change. Unsupported creation
still returns `nil` on every attempt.

## Format-500 caller evidence

`BGMTL_REFUSAL_CALLERS=1` optionally records one descriptor and at most 16
module-relative stack PCs per process when a format-500 refusal occurs. It is
disabled in the installed environment. It does not dump texture contents.

The first short compositor window did not reproduce the request. One settled
retry captured backboardd 11258 requesting a 1105×1160 IOSurface texture, type 2,
usage `0x1` (sampled), storage 0. The caller is QuartzCore, beginning at module
offsets `0x9ae60`, `0xa9e48`, `0xa3448`; symbol names are redacted in that image.
Five summaries report 2, 87, 132, 135 and 77 suppressed repeats: 433 repeated
error outputs replaced by five summaries, after the first useful error.
This is a diagnostic window, not a matched frame benchmark. The console stream
also contains historical original-runtime messages; they are not candidate output.

Repeated requests therefore continue despite the same refusal. In `texture_of_shape`,
the unsupported-format check precedes Gallium resource allocation; this change
does not remove the Objective-C wrapper allocation or the caller's retry/fallback
work. The private format's layout and the downstream fallback cost remain unknown.
Supporting it requires separate local format evidence and pixel validation.

## Validation and activation

- Host clang ASan/UBSan: PASS, including 100,000 repeats, distinct reasons/paths,
  periodic summaries, eviction, oversized keys, and counter saturation.
- Local VM builds: `m2refusal` PASS (13 s), `m2ready` PASS (11 s), final
  `tools/vm-mesa.sh mesa m2final` PASS (12 s). No CI runs.
- Final normal and compositor (`--bb`) GPU suites: **30/30 each**. P17 performs
  1,000 unsupported format-500 creations: all return nil, one refusal line.
  Format 501 produces its own line; supported RGBA creation still succeeds.
  Existing derivative edges and mutable/compressed no-copy lifecycle checks pass.
- Existing baseline2 is retained. No new baseline or performance-score gate.

Final artifacts: `xnu/out-mesa-m2final`. libbgair is byte-identical to M1:
`326eaa30dcc1ccea1955b45383f5f97bdb25ec3cb83a18cf2a54fad2c0561074`.
libbgmtl SHA256:
`0487f224f3bb87d6d224f9c104710e84e92d4bfd29901e55b8276acc676b4a5c`.

M2 libbgmtl is installed in `/usr/local/bin`, with both libraries verified by
byte-for-byte readback. Backboardd restarted as 11426 with the original environment
(`CA_DISABLE_FRAMEBUFFER_COMPRESSION=1` only). Final benchmark/profiler are idle,
GPU jobs completed 4717/4717 at the state check. Temporary M2 device files were
removed; the shared phone lock is released. The phone remains running iOS.

Evidence and original-runtime backups remain ignored under `research/metal-m2/`:
`final-suite-{normal,bb}.txt`, `caller-settled-console.txt`, `before-*`,
`restored-*`, and installed readbacks/state. Both diagnostic windows restored the
original M1 runtime and environment byte-for-byte before final activation.
No reboot, flash or partition changes were needed; the phone was already in iOS.
