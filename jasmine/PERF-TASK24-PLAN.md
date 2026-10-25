# Task 24: batch reduction and selective GMEM

2026-10-26. Investigation and proposed implementation plan; no rendering change,
build, CI dispatch, phone access or new measurement. Starting HEAD `b58d1c5`.
Task 24 remains open. This document is the review deliverable requested by the user.

## Recommendation

Proceed in two independently measurable steps: retain safe texture-feedback
barriers inside **sysmem** batches, then enable **selective GMEM for batches
without feedback**. Do not simply remove forced sysmem or disable barriers/kicks.
The saved GMEM experiment already regressed Home and CC substantially.

Important limitation: a larger batch containing feedback is still a sysmem batch.
Reducing barrier splits may reduce CPU work and submits without reducing blended
framebuffer DRAM traffic. It does not itself prove that enough GMEM-eligible work
remains to reach the task's estimated 15-20 ms Home GPU time. Treat that number as
an aspiration, not a forecast or acceptance threshold backed by measurements.

## Evidence checked

- Read root NOTES.md, task rules, task 23-25 brief, GPU timing report and task-5
  threaded-context report. Latest handoff records production pipeline 0, DDR1804,
  GPU588 and library `14e32aea...`; historical GPU rounds used pipeline 2 and a
  different kernel. Device state was not freshly checked. The task registry's
  older installed-library line is not the latest handoff.
- Re-ran `python tools/g2/gpuwin.py logs/netlog-t16-gd2.txt` and the same command
  for `netlog-t16-gm1.txt`. At gd2 line 8821 (1804 portion): 30 batches/100-flush
  normalized frame, GPU 32.1 ms, 13.8 barrier + 10.1 resource-dependency + 4.9 context
  flushes. Full-target sysmem classes account for 23.0 ms. At gm1 line 5426:
  GPU 59.4 ms, with 12.5 full-target GMEM batches costing 48.0 ms. These windows are
  historical workload aggregates, not matched individual frames or displayed FPS.
- Existing framebench report: Home B median 32.9 ms at DDR1804 (gd2); earlier
  DDR1296 sysmem 41.1 ms versus GMEM 55.9 ms. Do not compare those DDR variants as
  an isolated GMEM experiment. Per-draw timestamps serialize the GPU; their
  timings are upper bounds and should not be the final performance benchmark.
- Current `mesa/darwin/sweetgl/sweetca.c:1584`: `draw_prep` already distinguishes
  active sampled units from stale bindings through `sgl_sampled_2d_units`.
  Necessary feedback still calls `sgl_texture_barrier` at 1642. Reimplementing the
  stale-binding optimization would duplicate existing work.
- `sweetgl.c:443` forwards to `_mesa_TextureBarrierNV`. Saved patched Mesa
  source under ignored `research/t16/s3-mesa` has `fd_texture_barrier` at 155:
  unconditional `fd_context_flush`; its comment explicitly identifies an in-batch
  bypass cache flush as a possibility, with future GMEM selection the obstacle.
- `sweetca.c:1690` / `sweetgl.c:462`: default kick interval 32; the TC callback
  flushes the driver batch and submits deferred work. Removing kicks could reduce
  splitting while also reintroducing CPU/GPU idle bubbles. Context counts do not
  identify callers and cannot all be attributed to kicks.
- Saved `freedreno_batch.c:584` flushes a different pending writer when a
  resource is sampled. These producer/consumer edges preserve correctness;
  a render-target switch alone is not evidence of an unnecessary dependency.
- Saved `freedreno_gmem.c:701` chooses bypass late; it has no task-24 feedback
  veto. Tile dimensions are clipped at375-390. Neither proves actual a5xx resolve
  access bounds. Kernel patch j0033 and saved kernel source define128 KiB of
  scratch VA after allocations. Padding is containment, not proof of correct
  output or isolation: padding aliases one scratch page.

Local limitation: WSL source access returned `Wsl/E_ACCESSDENIED`. Driver checks
above use the saved task-16 source subset, whose earlier provenance audit is in
`PERF-TASK16-PLAN.md`. The full a5xx clear/cache/resolve and autotune sources must
be checked against pristine Mesa 26.2.5 plus all current patches before coding;
the exact cache packet sequence and safe clear cases are **not yet established**.
No upstream-version assumptions are required for the conclusions above.

## Proposed sequence and gates

### 1. Finish the offline command-stream and resource audit

Reconstruct pristine Mesa 26.2.5 with all repository patches in an isolated
directory. Record revision, patch inventory and source hashes. Trace GL texture
barrier through state tracker, TC, resource tracking and a5xx draw emission.
Inspect `fd5_cache_flush`, sysmem clear/blit handling, GMEM restore/resolve,
autotune fallback and `max_scissor` aggregation. Separate ordering requirements:
prior color writes must finish and reach texture-visible memory; texture caches
must not return old pixels. Do not substitute a guessed flush/invalidate sequence.

Specify an explicit per-batch feedback/bypass invariant. A batch retained across
an in-batch barrier must remain sysmem until retirement, including future draws,
FBO revisits, clears and debug overrides. Detect self-sampling at the first draw
too, not only when a previous batch exists at a barrier. Audit imported resource
aliases, views, levels and texture-unit tracking: GL texture-name equality is
not sufficient as a general driver safety predicate. Keep existing dependency,
fence and TC ownership rules, including patch 0004's batch-leak fix.

Gate: a documented supported subset and exact packet/order design. Clear/blit,
depth/stencil, MSAA and other unproved cases retain the existing split. If no
useful safe subset remains, report that before spending a device round.

### 2. Capture the batch graph, then implement the smallest safe change

Extend existing opt-in diagnostics with a bounded driver-thread event stream:
frame/flush epoch, context and batch IDs, target resource/alias identity,
producer->consumer dependency, flush caller/reason, feedback mark, clear masks,
draw count, scissor union, selected mode and reason. Count actual flushes as well
as barrier calls. Associate kicks with driver batches, not just wrapper draw IDs.
Use counters/full bounded records rather than only slowest-batch summaries;
TRACE=2 stops at 60 draws and is unsuitable for a late steady-state graph.
Reuse task 23's trace bounds/provenance machinery where useful, but its pre-draw
records alone do not reveal driver batch ownership or flush causes.

First candidate, behind a default-off switch: a5xx in-batch texture barrier for
the proven sysmem subset, with a durable bypass veto. Keep global sysmem forced
for its first comparison. Do not remove active feedback barriers or genuine
render->copy->blur->composite dependencies. Preserve submission cadence initially.

Gate: pixel correctness plus fewer actual splits; then measure CPU, GPU and
submit count separately. A batch-count improvement alone is not a traffic win.

### 3. Admit only profitable, safe batches to GMEM

After the graph shows how much eligible work survives, add a conservative a5xx
selector. Reject feedback batches unconditionally. Preserve other driver bypass
requirements. Initially restrict to understood color-only targets/formats and
exclude unproved imported layouts; keep small/low-overdraw batches in sysmem.

Compare estimated blended pixel traffic saved against restore/resolve bytes for
the touched tiles, plus measured tiling overhead. Draw count alone is insufficient:
many icons in a full-screen viewport are not many full-screen blended layers.
Current scissor union is an upper bound on coverage; collect useful coverage
estimates before choosing numeric thresholds. Keep an explicit mode/reason log.
The selector must be able to retain a profitable isolated GMEM batch even if
the entire frame cannot become a handful of batches.

Do not initially derive new scissors from arbitrary client vertex arrays. That
requires transforms, indices, clipping, edge coverage and shader-position proof;
an incorrect bound silently drops pixels. Driver-native conservative bounds or
known existing CA scissors are the first candidates. Native framebuffer-fetch
support is a separate feasibility audit if feedback dominates; do not assume
a5xx supports a usable on-chip implementation in this GLES path.

Gate: demonstrate lower total GPU time/traffic rather than a faster single batch.
If feedback contamination dominates, consider splitting at a profitable boundary
or revising feedback representation only after the graph supports it. Do not
bundle blur algorithms, presentation pipelining or screen geometry into task 24.

### 4. Validate with few, interpretable rounds

- Before CI: apply every patch in order; compile touched driver files where a
  usable cross-toolchain exists. Add meaningful pixel-reference GL tests:
  repeated feedback with known expected pixels, clear->feedback, feedback->clear,
  target switch/revisit, aliases, partial scissors and multiple program/sampler
  changes. Run TC on/off; exercise both eligible and forced-fallback cases.
- Add resolve-boundary tests for odd heights, imported offsets/pitches and the
  actual 1125x2436 target. Check bottom/right rows and guard regions with distinct
  contents. Bound real resolve addresses using a5xx packets and layout, not just
  bin geometry or absence of faults. Do not grow scratch padding as a correctness
  fix. Record existing boot self-test faults separately from new runtime faults.
- Use `gh` for one Mesa CI candidate build with independent switches for barrier
  retention and selective GMEM. Check build/logs/artifact hashes. Install under a
  test name and temporarily boot; preserve exact production rollback artifacts.
- In a phone-free scheduled session, acquire the shared lock and verify current
  kernel/library hashes, pipeline, clocks and UI. Warn of possible hang and use
  the established recovery path. Complete the accessory-sync precheck before
  timed captures. Match temperature, clocks and pipeline within comparisons.
- First one bounded graph/correctness session; then select only promising
  variants for paired same-day baseline/candidate captures (two per variant per
  project rules, interleaved where practical). Batch timing for diagnosis;
  uninstrumented framebench for performance; DDR counters in matching windows.
  Do not run per-draw timing over GMEM or treat flushes as displayed frames.
- Report Home A/B, CC A/B and repeated Spotlight separately. Ask for visual
  checks of Home/dock/folder, CC, NC and an app; inspect GPU/SMMU/panic logs and
  complete a sustained transition check before installing defaults. Include
  task 16 mode 2 regression validation if it has shipped by then; current mode 0
  must have its own matched baseline.

Kicks are a separate experiment only if the graph shows meaningful avoidable
splits. Compare retained 32 against a justified larger interval/adaptive scheme,
watching GPU idle gaps and frame latency. Never select KICK=0 solely for fewer
batches. Actual external-visibility flushes/fences remain mandatory.

### 5. Ship only the measured winner

Require reproducibly lower Home GPU time and Home B median, reduced traffic
consistent with the claimed mechanism, no material regressions elsewhere, and
correct pixels/no new runtime faults. Record variance and p95; do not invent an
FPS claim without displayed-frame evidence. A handful of batches is a useful
diagnostic goal, not a substitute for these outcomes.

After the user's visual check and root-change authorization, install the winner
on by default, verify the production hash and plain-reboot behavior, and record
the rollback. A library-only change need not cause an unrelated kernel/slot
reflash; if boot defaults require a slot-b update, prepare the exact image and
confirm the destructive step under AGENTS.md before flashing. Update NOTES.md,
GPU.md and task status with commits, CI IDs, hashes and exact results.

## Next concrete action after review

Finish step 1's isolated full-source audit and write the cache/clear/bypass design.
Then implement bounded batch-graph instrumentation and the narrowly gated sysmem
barrier candidate. No phone round is scheduled by this plan. Potential payoff is
large, but the eligible-batch graph and safe barrier mechanism remain the two
unresolved feasibility questions.
