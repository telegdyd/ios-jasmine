# Task 23: shared UI blur correctness and performance plan

Runtime investigation: [device audit](PERF-TASK23-DEVICE-AUDIT.md). Gaussian
downsampling observed through 74x156 and 72x42 intermediates. The universal
missing-copy premise is disproved for the observed path. Variable-blur source
compatibility gap remains; runtime execution/impact was not captured. No blur
algorithm fix or speedup delivered; next work must follow these findings.

Initial offline investigation: [audit](PERF-TASK23-AUDIT.md). Gaussian has
explicit separate-target downsampling; a universal missing IOSurface mip chain
is not established. Variable blur deliberately bypasses intermediate draws and
uses an approximate source blur. Next: bounded complete-graph diagnostics to
resolve actual Gaussian selection and variable-blur intermediate representation.

User scope clarification: Control Center is a benchmark, not the optimization
boundary. The goal is higher frame rates across the UI. Investigate Gaussian
and variable blur and their shared texture/storage/copy paths; fix any confirmed
incorrect handling everywhere that uses the affected path. Do not gate a shared
fix on which UI is visible. Preserve intended appearance and effective blur
radius; do not lower blur quality globally as a shortcut. Correctness defects
and performance opportunities must be distinguished in the results.

Status: pre-build plan, 2026-10-25. User requested task 23 and a plan before
building. Read root and jasmine handoffs, task 23, the GPU timing report and
PERF-TASKS ground rules. Starting branch `jasmine`, HEAD `8bd08b9`; tracked
worktree clean. No build, CI dispatch, device access or implementation yet.

## 1. Establish the actual blur path

Use saved gd1/gd2 logs and shader evidence to identify the expensive CC passes
and their inputs. Inspect the local QuartzCore disassembly and GL dispatch
calls for GaussianBlurFilter, filter_backdrop and capture_backdrop. Verify
storage levels, mip generation, attachment levels, downscales and errors;
distinguish IOSurface-backed textures from ordinary GL allocations. A comment
about variable blur is not proof that Gaussian blur has the same failure.

The current wrappers forward TexStorage2D's levels, GenerateMipmap and
FramebufferTexture2D's level. Inspect their actual backing/storage and copy
paths before deciding which operation fails. Keep task 16 ticket ownership
and task 5's threaded-context fence-reference fix intact.

## 2. Obtain a bounded diagnostic and matched baseline

First check existing captures for sufficient evidence. If insufficient, prepare
opt-in diagnostics for one CC opening. Existing TRACE=2 logs only the first 60
draws process-wide, likely exhausted before CC; provide a bounded targeted
window rather than unbounded draw logging. Include texture storage provenance,
mip/attachment levels and relevant operation errors if existing logs lack them.
Present the concrete diagnostic change before its first build.

At the device stage, establish phone availability and take the shared lock;
verify the actual image, library hashes, pipeline mode and clocks. Use DDR 1804,
the current kernel/pipeline and settled accessory sync for both variants.
Collect the missing matched baseline with existing tools. Keep verbose tracing
separate from performance measurements. Per-draw timestamp drains make those
times upper bounds; use matched per-batch/frame measurements for overall gain.

## 3. Choose and implement one focused correction

Prefer restoring CA's intended reduced-resolution/mip path if evidence shows it
is broken. Otherwise recognize the proven blur pass sequence and downsample
explicitly, preserving blur radius in screen pixels, coordinates, edge borders,
alpha and compositing. A substitute shader is a fallback after the path is
understood. Do not select passes solely by framebuffer dimensions. Preserve
notification-centre variable blur, other rendering and GL state/lifetimes.
Audit the existing sca_nop/sca_vblur workaround as part of this investigation;
do not assume it is correct or exempt from improvement. Prefer a shared fix
over special treatment of CC. If multiple blur algorithms need separate
corrections, document their coverage and validate each affected path.
Keep a diagnostic disable switch and retain the exact production library for
rollback; test under a separate library filename.

## 4. Validate, build and compare

Review state restoration, allocation/error cleanup, resizing and surface reuse;
run appropriate local compilation/checks before one Mesa CI build via gh. Record
the source commit, CI run ID and artifact hash. Use temporary fastboot boot for
the test and the same measurement configuration as baseline. Minimize rounds;
repeat only when variance or a failure prevents a conclusion. Inspect GPU/SMMU
faults and compare CC A/B medians plus GPU time/frame and the expensive passes.
Use Home/dock/folder backdrops and Notification Centre alongside CC to verify
coverage, GPU work and frame intervals. Include available in-app blur cases.
Report benefits by workload: a shared blur fix does not imply that scenes
without blur or with other bottlenecks improve by the same amount.

## 5. Visual review and completion

Ask the user to check CC and notification-centre blur, including transitions,
edges, text and transparency. Acceptance: no full-resolution CC blur pass over
about 2 ms in gpudraw, lower CC GPU time/frame and CC A/B medians at DDR 1804,
and user-confirmed matching appearance. Treat these as targets, not a promised
UI-wide speedup. CC thresholds are benchmark criteria, not sufficient proof of
completion: confirm correct shared handling and assess other affected blur
paths, including variable blur and already reduced-resolution backdrops.
Record any remaining incorrect blur paths explicitly. Do not call task 23
complete merely because CC improved. Do not promise a
10 ms gain. Install at the production library path with the fix enabled by
default only after validation. Follow the project's plain-reboot completion
rule; obtain the required destructive-step confirmation before any boot_b
flash. No partition-layout or root-data changes belong to this task.

Commit completed changes and update both handoffs after milestones with exact
build/boot results, device state, rollback location and remaining work. Keep raw
captures, device identifiers and Apple artifacts out of git. Task 23 remains
open until device and default-install acceptance is complete.
