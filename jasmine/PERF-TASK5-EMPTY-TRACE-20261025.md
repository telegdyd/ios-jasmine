# Task 5: skip disabled, empty batch trace flushes

One focused offline optimization removes unnecessary trace-worker jobs from
Mesa's batch-finalization path. It does not change GPU state emission, barriers,
batch boundaries, submission, fences or presentation. Device correctness and
frame-time validation are **pending**; no phone access or new workload was used.

## Evidence from the current capture

Used `research/framebench/20261025-first/capture/`, phase 6 (Control Center A),
`backboardd`'s `coreanimation.display.primary` thread, on-CPU records only.
The 1775 samples at 2000 us/sample give 3550 estimated ms over approximately
four seconds. Symbols match the installed active-sampler production library
(`e5fc84b1066990dbb06a6816ad5421978d84fcd2aa7c6f49d477594516847b1c`)
and framebench99 kernel. The ignored analysis helper and complete rankings are
`research/framebench/20261025-first/task5_stacks.py` and `task5-stacks.json`.
They decode the interned stack dictionary and resolve user addresses per PID,
subtracting one from return addresses, as in `framebench.py`.

| Path present in stack | Samples | Inclusive estimated CPU ms |
| --- | ---: | ---: |
| `fd5_emit_state` | 165 | 330 |
| `fd5_program_emit` (inside state emission) | 104 | 208 |
| `st_prepare_draw` | 130 | 260 |
| `fd_batch_create` | 98 | 196 |
| `fd_batch_flush` | 147 | 294 |
| `u_trace_context_process` | 65 | 130 |
| `u_trace_flush` | 8 | 16 |

These are overlapping inclusive attributions, **not additive savings**.
`fd5_program_emit` is the largest named Mesa leaf (66 samples / 132 ms), but
these stacks do not establish that its repeated register emission is redundant.
New batches and changes to programs, interpolation and private memory can require
it. Caching or omitting it would need a separate correctness argument.

The trace path has a direct source-level proof of unnecessary work in the normal
disabled case. `fd_gmem_render_tiles()` calls `u_trace_flush()` unconditionally
after `flush_ring()`. Mesa 26.2.5's `u_trace_flush()` allocates a flush object,
moves even an empty trace into it and appends it to `flushed_traces` without
checking enablement or event count. `fd_context_flush()` then calls
`u_trace_context_process()`, which submits every object to the trace worker.
This happens even with default `enabled_traces == 0` and no events to process.

Of the 65 queue-processing samples, 60 are kernel CPU, mostly condition-variable
wakeup work; five are user CPU. In 55, the caller is the retained, required
texture-barrier path `draw_prep -> fd_texture_barrier -> fd_context_flush`.
The other ten follow fence/finish flushes. This is work on the critical primary
rendering thread, not just a background-worker cost. Eight other samples are in
the trace-object allocation path.

No `MESA_GPU_TRACES` or `MESA_GPU_TRACEFILE` setting was found in the repository
or the saved session's console. The capture does not snapshot process environment
or trace contents: attribution proves execution of the path, while source proves
the default disabled/empty case is avoidable. It does not establish the exact
number of skipped jobs or that all 146 ms of those two rows will disappear.

This was the clearest confirmed removable path among the inspected costs. It is
not a claim that it is the largest possible Mesa optimization or that CPU versus
RAM bandwidth has been separated. On-CPU samples can include memory stalls.

## Change and correctness

`mesa/patches/0003-freedreno-skip-empty-trace-flush.patch` follows the unchanged
Darwin backend and diagnostic patches. It guards just that final tracing call:

```c
if (u_trace_enabled(&ctx->trace_context) || u_trace_has_points(&batch->trace))
   u_trace_flush(&batch->trace, NULL, U_TRACE_FRAME_UNKNOWN, false);
```

* Tracing disabled, empty trace: no flush object, array append or worker job.
  Normal batch destruction still calls `u_trace_fini()`.
* Any tracing enabled, including marker-only settings: original behavior,
  retaining empty-batch/frame diagnostic accounting.
* Recorded events with tracing subsequently disabled: original flush and cleanup
  behavior. The event check is retained rather than checking enablement alone.

`u_trace_enabled()` uses Mesa's atomic context read. This caller passes NULL
flush data and transfers no other ownership. Skipping it changes neither GPU
commands nor resource/fence lifetimes. `flush_ring()` still executes first.
Already queued traces are still processed by the unchanged context flush.
The existing active-sampler barrier fix remains the production baseline.

## Validation and handoff

Prepared an isolated `/tmp/jasmine-t5-offline.1JXTHA` worktree at `mesa-26.2.5`,
applied repository patches 0001 and 0002, then generated 0003. The shared WSL
Mesa tree's pre-existing edits were untouched. No regeneration of 0001 was
needed because no `mesa/darwin/` source changed.

Local checks passed:

* Compiled patched `freedreno_gmem.c` and matching `util/perf/u_trace.c` to host
  objects at `-O2` using existing Mesa generated headers and the isolated source.
* Applied all three repository patches in order against the pristine tag in an
  isolated index; resulting tree exactly matches the implementation checkout.
* `git diff --check` passed for the modified Mesa source.

Validation scripts and objects are ignored local research artifacts.
Implementation `0624366` is pushed; iOS Mesa CI
[40163837008](https://github.com/telegdyd/ios-jasmine/actions/runs/40163837008)
**passed** for that exact commit. The Mesa job completed in 2m52s; logs confirm
`freedreno_gmem.c` was patched cleanly and the library/test binaries linked and
were signed. Downloaded artifact:

* Library: `xnu/out-mesa-t5empty-trace/libsweetca.dylib`, 19,233,936 bytes.
* SHA256: `cfa9fd9c56305ed82b63f9d21b0134faf8b3ad661cf4d0d34ef6bf2e5bc8c0ea`.
* Actual ARM64 disassembly of `fd_gmem_render_tiles`: at `0x5a1bb0`, load the
  context's tracing flags; nonzero branches to flush. Otherwise call
  `u_trace_has_points` at `0x5a1bbc`; false branches to the return at `0x5a1bf4`,
  bypassing `u_trace_flush`. The normal flush path still has NULL data, unknown
  frame number and `free_data == false`.
* Saved logs/status/disassembly: ignored session files `task5-ci.log`,
  `task5-ci.json`, `task5-gmem-arm64.txt`.

This change is not installed. Device rendering checks and frame-time impact
remain pending; the user explicitly prohibited another benchmark round for
this step. No boot, clock or plugin change occurred. Do not infer a gain from
the sample attribution or historical batch counts. Task 5 overall remains open.
