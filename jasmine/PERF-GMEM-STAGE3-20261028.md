# GMEM plan stage 3: per-batch selection (2026-10-28)

Work in progress. The pixel gate passes; the corrected mode-2 performance comparison is still running.
Nothing installed in production or flashed. This report covers stage 3 of
[the GMEM plan](PERF-GMEM-PLAN-20261028.md).

## Build and correctness

Mesa CI [40717125371](https://github.com/telegdyd/ios-jasmine/actions/runs/40717125371)
passed on macOS 15, head `26ad0b2` (driver change `d7db729`). Artifacts:

- libsweetca SHA256 `d39a3243e297816f799dbee5ed564cfcc32151c47fa35122a8d85208174b203d`.
- sweetgpu_gltest SHA256 `27a1dcb006c50d647caf35679dfc5a49a2ea7ac59fb2f8ba46711950f6fc186f`.
- Local evidence: ignored `research/t24/stage3/ci-40717125371/` and `gate-ci40717125371/`.

The test library was copied as `/usr/local/bin/libsweetca-s3.dylib`, with exact readback.
The **16-case pixel gate passed**: sysbarrier off/on/wide, force-GMEM off/wide, timed rule,
forced feedback diagnostics, and the informational pitch override, each with TC on/off.
Fourteen cases had 84 individual PASS checks; two diagnostic cases had 44. No FAIL lines.
The required GMEM decisions were observed on 1127x2438 (200), 1131x2442 (100), and
1125x2436 (200). These totals include the informational override cases.
Production library `4780fbaa...` matched before and after; the test executable was removed.
The gate boot log had zero SMMU faults, panics, or ticket/submit errors.

## Selection and extent audit

Patch 0010 remains off by default. `SWEETCA_GMEM=1` times each batch kind twice in sysmem
and twice in GMEM, then selects the faster mode with a 110% margin. Subsequent timing is
sampled at 1/8 uses and the other mode retried at 1/64. A single uncleared draw is not explored.
The key includes batch hash, draw count, cost, dimensions, clear and restore masks.
Depth/stencil, MSAA, layers, queries, tessellation, tiled/UBWC resources, and retained-feedback
batches stay in sysmem. A qualifying prefix can split before the first feedback barrier.

GMEM imports require rows aligned to the a5xx `gmem_align_w` (64 pixels), as upstream does.
For each target, offset + pitch * align(height,32) must fit in the BO, including the kernel's
full 128 KiB scratch mapping after imported buffers. This is a mapped-extent check, not a
claim that the resolve stays inside the logical IOSurface allocation. The pixel tests check
visible output and canaries; earlier tests observed block writes into row/tail padding in both
sysmem and GMEM. Kernel-default 4544-byte rows remain rejected normally; 4608/4864-byte rows
are exercised through GMEM. The test-only pitch override also passed, but remains disabled.

The earlier sample-count scheme is abandoned: enabling SAMPLES_PASSED broke large full-screen
quads even in sysmem. The current selector uses RB_DONE_TS timestamps, not sample counting.

## Measurement validity: truncated first profiling image

The original `s3gp-g1` image silently truncated its command line to 607 bytes and ended in
`swee`, dropping `sweetgpu_tickets=1`. Baseline and `s3gp-g0` retained that argument.
That first GMEM boot measured 106.6 batches/frame and 85.7 ms wall time on Home, but it is
**invalid for comparison with mode 2**. Its 25.50 ms GPU time cannot be presented as a GMEM gain.
No SMMU fault, panic or ticket/submit error appeared in that boot. Static Home/CC dumps had no
obvious corruption; this does not establish correctness in motion.

`s3gp-g1-fixed` uses the same shim, kernel and ADT as `s3gp-g0`, adds `SWEETCA_GMEM=1`,
and omits explicit `sweetgpu_debug=0` (the kernel variable defaults to zero). Its 604-byte
command line retains `sweetgpu_tickets=1`; payload round-trip verified.
Image SHA256 `d87902c85c8c88701087a00839a73321f25e42590685144f7c84bd4b1f31c2bd`.
`tools/mkpayload.py` now rejects oversized or NUL-containing command lines before reading inputs.
Boundary checks verified 608-byte rejection, NUL rejection, and 607-byte acceptance.

## Measurements and recommendation

Same-library GMEM-off control `s3gp-g0`, Home: 1000 trimmed frames, 101.5 draws,
18.6 batches, 27.46 ms GPU/frame, consistent with the earlier stage-2 baseline (27.40 ms).
The corrected GMEM profiling boot and alternating framebench runs are pending.
No installation recommendation yet; the user's motion check and explicit installation approval
remain outstanding.
