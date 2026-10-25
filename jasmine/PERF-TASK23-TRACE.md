# Task 23 bounded pass diagnostic

This is a diagnostic library, not a blur fix or a performance benchmark.
`SWEETCA_PASS_TRACE=1` enables it; absent/other values leave it off.
It does not enable TRACE=1/2, consume GL errors, read pixels, alter shaders,
force a flush or change render storage. GL metadata queries and synchronous
logging perturb execution: never use its frame/GPU timings as a speed result.

The window starts relative to the library constructor's monotonic timestamp:

| Variable | Default | Maximum |
| --- | ---: | ---: |
| SWEETCA_PASS_TRACE_DELAY | 180 seconds | 3600 |
| SWEETCA_PASS_TRACE_SECONDS | 12 seconds | 30 |
| SWEETCA_PASS_TRACE_DRAWS | 1200 | 3000 |

The time window is fixed, not extended by idle time. All contexts share one
draw budget. If no draws occur, the end marker appears at the next draw.
Copy/mipmap/blit events have a separate 8000-event cap; hitting it marks the
graph incomplete. ES2 contexts are excluded from draw snapshots. Invalid
numeric values fall back to defaults. Zero duration/draw limit records no draws.

Each pre-draw snapshot records context, sequence, age, CA flush count, program,
actual draw FBO/texture/attachment level/completeness, tracked target base size,
viewport, scissor and blend enable. It logs all tracked nonzero bound 2D textures
with actual binding, base/max level, minification filter and dimensions for
levels 0-3. Bound textures are not necessarily sampled: identify active sampler
use from the shader. Separate sampler-object state is not captured.

Imported IOSurface IDs and attempted-storage generation counters are provenance
hints, not retained objects or proof that a GL allocation succeeded. Zero means
private, copied or unknown; use actual GL dimensions and errors if available.
Names beyond tracking-array limits have unknown provenance. Fragment sources
are queried once per linked program, capped at 8191 bytes; weighted-candidate
is a heuristic label, not proof that a shader is a Gaussian pass. Source fragments
may contain newlines; preserve raw log text. Allocation failure can omit source
and provenance metadata, not rendering. Sources are captured again after relink.

First and last frames can be partial; interpret complete interior pass chains.
A draw record describes an attempted draw after preparation, before ticket
admission; it is not proof of successful GPU execution. Pair with available
GPU/fault evidence before claiming a rendered result.

Device plan: install under `/usr/local/bin/libsweetca-t23trace.dylib`, preserve
the current kernel/ADT/pipeline/clocks in a temporary image, override only the
library and diagnostic environment. Verify loaded identity. Allow accessory
sync to settle before the fixed window; exercise Home, CC and Notification
Centre inside it. If a phase or complete chain is absent, report that absence
rather than infer correct/incorrect rendering. Do not install this as production.

Local check: ignored `research/t23/test-pass-trace.py` generates a C harness;
gcc C11 with `-Wall -Wextra -Werror -pthread` passes disabled-path, time/draw-cap,
active-unit restoration, source capture, provenance reset and invalid-option
checks. This mocks GL, so the real iOS build and device checks remain necessary.
