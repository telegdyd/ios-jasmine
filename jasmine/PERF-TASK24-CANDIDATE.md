# Task 24: small sysmem batch barrier experiment

2026-10-26. Prepared after the [first batch graph](PERF-TASK24-DEVICE-AUDIT.md).
**Default off; not installed or GPU-validated. No measured gain.**

## Concrete change

Patch `0008-freedreno-a5xx-sysmem-barrier-experiment.patch` adds an optional
a5xx barrier hook. `SWEETCA_SYS_BARRIER=1` enables the experiment only when
`FD_MESA_DEBUG` also forces sysmem. Otherwise the existing global flush remains.

A barrier is retained only for a current unflushed draw batch with1-5 draws,
one linear level0 two-dimensional RGBA8/BGRA8 color attachment, one sample,
no depth/stencil, clear, prologue, tessellation, dependencies, outstanding
context fence, active queries or streamout. The hook also checks the screen's
batch cache under its lock and rejects **any other pending batch of this
context**. This preserves the global-drain behavior for otherwise untracked
aliases rather than assuming ordinary resource tracking covers every alias.

The five-draw limit is deliberately conservative: the existing fallback starts
favoring GMEM above five draws, and the graph contains large alias-free islands
terminated by barriers. Keeping their existing boundaries leaves that future
opportunity intact. This is not a calibrated profitability threshold.

For an eligible batch the draw stream receives:

1. Existing `PC_CCU_FLUSH_COLOR_TS` event to publish color-cache writes.
2. Existing `fd5_emit_flush`: `CACHE_FLUSH_TS` and `WAIT_FOR_IDLE`.
3. Existing `PC_CCU_INVALIDATE_COLOR` event.
4. Existing `fd5_cache_flush`: UCHE invalidate registers and `WAIT_FOR_IDLE`.

These primitives already exist in the a5xx driver; **this new composition still
requires real GPU pixel tests**. It is not established correct by compilation.
The batch receives a durable bypass veto, checked after the ordinary GMEM
decision, and `fd_batch_needs_flush` updates its ordering and clears an obsolete
last-fence reference. Any later common fast clear first flushes the retained
batch and selects a fresh one before clear tracking/emission. Resource
dependencies, fence ownership, patch0004's leak fix, periodic kicks, presentation
mode, and forced-sysmem production default remain in place.

## Pixel-reference tests and gate

The GL test gains a real IOSurface feedback test, using two color-only imported
linear targets and a third texture name aliasing the first target's IOSurface.
Each feedback draw samples the same pixel once and adds a known RGB increment;
barriers precede draws, and readback occurs only after each complete sequence.
The test checks:

- Eight successive feedback draws with no intermediate read/finish.
- Feedback followed by a clear, then feedback in a partial scissor.
- Target switches/revisits with another target pending.
- Sampling a distinct imported texture name aliasing the current target.
- Preservation of the other target's expected pixels.

Run the new signed `sweetgpu_gltest` under a test name in this four-process
matrix, with no changes to backboardd's production injection:

```text
sweetgpu_gltest --sysbarrier-off
sweetgpu_gltest --sysbarrier-on
sweetgpu_gltest --sysbarrier-off --no-tc
sweetgpu_gltest --sysbarrier-on --no-tc
```

The flags set the environment **before** display/context creation and force
`sysmem,nofp16` for both sides. The on cases must print
`sweetca: sysbarrier retained (experimental forced-sysmem-only)` and pass every
pixel-reference check; without that marker, fallback success does not validate
the changed path. There are now eight GL-test steps. A failure, hang, GL error,
or new GPU/SMMU fault stops validation and precludes a performance trial.

Local checks: all eight patches apply to the pinned source; six driver files
pass twelve GCC syntax checks (host and Apple guards), with no warnings.
Trace-controller tests and six batch-parser tests pass. iOS CI now passes;
the GPU test matrix and retained-path pixel correctness remain pending. The previous seven-step
device pass belongs to diagnostic `ad9d787`, not this new candidate.

**Build ready:** source `8b6f7e0`, Mesa CI `40250210168` PASS. Signed library
SHA256 `4b7eb493bde16938979679d7a714036fc70cb5f41a31a4884368ed23ebe13311`;
signed GPU test SHA256
`68fcde5cf3232193e75a9ad2be8eda3f6e4a16004641af42b479eba2bb57fae3`.
Both Mach-O headers and expected experimental/test strings checked. Artifacts
under ignored `research/t24/barrier-ios/`; exact CI provenance and hashes in
`barrier-ci.json` and `barrier-artifact.json`. The bounded matrix runner is
`research/t24/barrier-test.py`: acquires a fresh shared lock, installs only the
test-name GL binary, checks its readback hash, runs the four processes, verifies
production bytes unchanged and removes its own binary/lock. On failure it stops
and keeps its own lock for recovery. No planned reboot or CA library replacement.
Fresh phone-free authorization requested; no candidate phone access yet.

After the GPU gate, separately coordinate matched baseline/candidate performance
captures using the current pipeline0/GPU588/DDR1804, same kernel, test-name
libraries and temporary boots. Require a lower actual batch/submit burden and
improved uninstrumented frame results; a saved batch does not prove fewer DRAM
bytes or higher FPS. Do not combine this first experiment with enabling GMEM.
No further phone round has been scheduled or performed for this candidate.
