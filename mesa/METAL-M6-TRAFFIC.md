# M6 - intermediate traffic audit and GMEM eligibility

**Partially complete; no traffic optimization promoted.** The largest M5 class
contains required attachment feedback that the original frontend failed to mark
in the batch metadata. Its second attachment cannot safely be removed from the
current evidence. The remaining single-draw class can use the existing per-batch
GMEM selector, but the bounded deterministic trial shows no useful work removal
and higher completion wall time. GMEM remains opt-in, default off. Installed
M1-M4 libraries and all original environment settings are retained.

## Attachment and consumer audit

The measured 828x1792 single-sample dual-BGRA8 class requests Load/Clear and
Store/Store, without MSAA resolve targets. Its driver clear/restore/store masks
are `0x8/0x4/0xc`. Color0 preservation is required for partial redraws. The
second attachment participates in the rounded-corner save/restore scheme
documented beside `rwa_render_draw`: save the destination's corner patches,
render the layer, then fetch both attachments to restore outside its shape.
The actual retained texture-read barriers in the new capture confirm that
attachment data is live within these batches. This is not a dead intermediate.

`BGMTLRenderEncoder` records the requested per-attachment clears independently
of draws, and `rwa_render_clear` issues each clear with its own mask. Removing
the second clear would change untouched texels seen by a later fetch. Removing
the attachment would remove those saved pixels. Post-pass deadness has NOT been
established: M5 records dimensions/actions and draw associations, not complete
resource identities, aliases, external consumers or CPU readback lifetimes.
Store/Store is therefore retained. No blur size/quality, derivative helper-lane
behavior, MSAA resolve, shadow copy-back or render-ticket protection is changed.

## Corrected feedback constraint

Metal's `fd5_feedback_barrier` emits sysmem cache maintenance directly. It bypasses
the GL barrier helper that marks `a5xx_sysmem_barrier`, so M5's zero feedback/pre
fields did **not** establish GMEM eligibility. The production forced-sysmem
configuration masked this missing constraint; enabling the optional selector
without correcting it would be unsafe.

The fix marks retained barriers as sticky sysmem-only, explicitly excludes GL's
experimental tile-fetch descriptors, and records the retained barrier count and
draws before the first barrier. Later clears retain their existing ordered
sysmem blitter path and batch behavior. Patch `0030` also carries the fetching
draw's constraint through dependency tracking to the actual emitting batch:
an empty-batch barrier fallback or a dependency-triggered batch replacement
cannot leave the eventual texture-fetch draw eligible for GMEM. The frontend
sets a context flag only around that draw; the driver applies the sticky batch
constraint after tracking. No extra barrier, flush or resolve is introduced.

## Bounded compositor evidence

Both Home windows contain 120 replayed command buffers, zero dropped rows and
zero pending stamps. The existing eight-second/120-CB collector and activity tail
were used; motion ran for 14 seconds. Wallpaper was left running on its original
runtime. These are different diagnostic workloads, not matched-frame timings.

| Window | Passes / batches | GPU envelope sum / union, ms | Fullscreen fetching batches / draws / ms | Fullscreen nonfetching batches / draws / ms |
| --- | --- | --- | --- | --- |
| Sysmem, retained-marker revision | 2619 / 2682 | 1950.96 / 1374.66 | 301 / 3466 / 1209.27 | 168 / 168 / 359.06 |
| Forced eligible GMEM, final constraint | 3085 / 3178 | 2648.61 / 2601.47 | 310 / 3874 / 1470.61 | 229 / 239 / 676.21 |

The first window's fullscreen fetching work accounts for 62.0% of all summed
compositor envelopes; all marked fetching batches together account for 70.9%.
The final-source GMEM trial tiles eligible nonfetching batches, while all marked
fetching batches stay in sysmem. No GMEM batch reports a retained feedback
barrier. This validates selection boundaries, not a UI speedup. Counts, draw mix,
source revision and temperatures differ; neither raw totals nor per-batch means
from these windows establish a before/after performance change. The constraint
also covers fetching draws without a retained barrier, so mode 3 can have a zero
retained-barrier count.

GPU timestamps are pipeline-draining execution envelopes. No hardware bus-byte
measurement or lower end-to-end frame cost has been established. M5's wallpaper
GPU-time/export gap remains open; these are compositor-only findings.

## Same-pair deterministic GMEM trial

`test/bgmtl_traffic_probe.m`, built by `tools/mesa-local.sh`, reproduces a concrete
828x1792 dual-BGRA8 Load/Clear, Store/Store pass with one ordinary draw. It loads
blue color0, draws red with alternating quarter/half-width scissors, and clears
color1 green. Color1's draw write mask is explicitly None; its clear must still
be stored. Both complete attachment images are checked after 40 command buffers.
The test checks preservation, target reuse and independent MRT clear/write masks.

Use the same paired libraries with `FD_MESA_DEBUG=sysmem`, alternating
`SWEETCA_GMEM=0/2/2/0`, and pass `bg_render.metallib 40` to
`bgmtl_traffic_probe`. Discard the first five iterations of each process. Profiling
is disabled. GMEM selection was confirmed from the bounded first-selection log.

| Mode | Mean commit/completion wall time, ms | Median, ms | Full-image result |
| --- | ---: | ---: | --- |
| Sysmem A | 2.362 | 2.172 | 0 wrong / 2967552 pixels |
| Eligible GMEM A | 3.576 | 3.497 | 0 wrong / 2967552 pixels |
| Eligible GMEM B | 3.500 | 3.297 | 0 wrong / 2967552 pixels |
| Sysmem B | 1.760 | 1.763 | 0 wrong / 2967552 pixels |

These wall times include encoding, CPU work, queueing and completion observation;
they are not GPU-only durations or bytes. Clocks/power policy were unchanged,
maximum TSENS was 56.6 C. This small trial does not reproduce CA shader cost or
prove a universal GMEM regression. It does show that tiling this single-draw
shape is not an established traffic optimization: GMEM adds tile restore/store
and binning work without demonstrated removal of repeated sysmem accesses.
No verified useful optimization is being rolled back because of a noisy score.

An initial exploratory probe left writes enabled for a shader's absent color1
output; half of color1's alpha values became zero. That experiment fails its
pixel gate and supplies no accepted timing evidence. The final probe explicitly
masks that output. The general absent-output semantics need separate investigation;
no renderer fix or private-CA write-mask behavior is inferred from this observation.

## Validation and handoff

- Local VM: `m6guard` PASS14s, `m6retained` PASS12s, `m6tracked` PASS21s,
  `m6final` PASS12s. Final `m6traffic` PASS13s. No CI. The first traffic-probe
  link used the wrong device-factory symbol; fixed before device execution.
  Subsequent probe diagnostics and explicit write-mask revisions each built.
- Final normal, compositor forced-sysmem and forced-eligible-GMEM suites:
  **35/35 each**. P10 now covers an ordinary MRT seed followed by retained
  feedback, a later clear of only color1, a partial fetching redraw preserving
  color0, and a separate empty-batch fallback. Both paths check 5624 exact values.
  Existing derivative, mutable/compressed upload and 80-pass dependency tests pass.
- MSAA 4x color/depth/resolve: three iterations with GMEM selector off and on,
  exact red center/blue corner. Shared GL sysmem and forced-GMEM: `PASS: all`.
- M5 analyzer: 4/4 tests pass. Both new captures pass its completeness checks.
- The final traffic build's two libraries are byte-identical to `m6final`, whose
  complete suites were tested. Four deterministic runs check every output pixel.

Evidence, scripts, exact backups and readbacks are ignored in `research/metal-m6`.
Both temporary compositor installations restore the M4 pair and environment
byte-for-byte in `finally`; the wallpaper pair/environment were never replaced.
Final cleanup verifies all four original libraries and both environments again,
removes both task CSVs, the trigger and all task binaries, and releases the shared
phone lock. No reboot, flash, partition, kernel or clock changes, new performance
baseline, physical-panel/FPS claim or optimized runtime installation.
Final GPU completion is 27156/27156, power collapse mode 1, profiler/benchmark
idle, maximum TSENS 56.3 C. Metal implementation commit: `587e6b8`.

**Remaining M6 work:** collect bounded resource/alias identities and all intervening
consumers for the second attachment, including next-pass loads/samples, copies,
resolves and external/CPU exposure. Establish actual pipeline write/fetch masks.
Only then consider a proven dead store/intermediate or a smaller scratch region
with pixel coverage of rounded corners, partial redraws and blur borders. The
current evidence does not authorize attachment deletion or GMEM for fetching draws.
Lower target GPU traffic/busy time and end-to-end cost are still unestablished.
