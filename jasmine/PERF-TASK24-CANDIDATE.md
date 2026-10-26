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
Trace-controller tests and six batch-parser tests pass. iOS CI, GPU test matrix
and retained-path pixel correctness remain pending. The previous seven-step
device pass belongs to diagnostic `ad9d787`, not this new candidate.

After the GPU gate, separately coordinate matched baseline/candidate performance
captures using the current pipeline0/GPU588/DDR1804, same kernel, test-name
libraries and temporary boots. Require a lower actual batch/submit burden and
improved uninstrumented frame results; a saved batch does not prove fewer DRAM
bytes or higher FPS. Do not combine this first experiment with enabling GMEM.
No further phone round has been scheduled or performed for this candidate.
