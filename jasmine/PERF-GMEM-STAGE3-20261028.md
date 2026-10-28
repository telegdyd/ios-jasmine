# GMEM plan stage 3: per-batch selection (2026-10-28)

**Result: 16/16 pixel-gate cases pass, but the current timed per-batch rule does not provide a
global frame-rate gain. Keep it disabled; do not install this candidate as-is.** Two complete
alternating baseline/GMEM framebench pairs confirm essentially unchanged Home/CC B rates,
with a regression in sampled CC A. Production remains unchanged.
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
Fourteen cases had 84 individual PASS checks; two diagnostic cases had 44: 1264 checks total. No FAIL lines.
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

Same-library GMEM-off control `s3gp-g0` versus corrected `s3gp-g1-fixed`, j0110 mode 2,
GPU 588 MHz / DDR 1804 / CPU auto, no clock changes. Home/CC discard first and last
100-frame windows. In-app windows include idle and phase boundaries; their wall times are
not frame rates. Settings sub-page content is not demonstrated identical across the boots,
so it is not an acceptance metric.

| Phase | g0 GPU ms/frame | g1 GPU ms/frame | g0 / g1 batches/frame | g1 GMEM batches/frame |
| --- | ---: | ---: | ---: | ---: |
| Home (1000 frames each) | 27.46 | 27.94 | 18.6 / 19.4 | 2.67 |
| Control Center (300 / 400 frames) | 34.61 | 36.75 | 55.4 / 62.6 | 13.22 |
| Settings scroll | 8.80 | 9.73 | 25.4 / 25.7 | 1.2 full-screen, plus small |
| App open/close | 18.62 | 17.88 | 16.1 / 17.3 | 1.2 full-screen, plus small |

Home has 1.7 full-screen GMEM batches costing 5.86 ms/frame, but retained-feedback full-screen
sysmem still costs 14.37 ms/frame (g0: 15.73). CC has 3.2 full-screen GMEM batches costing
6.47 ms/frame, and 5.67 feedback splits/frame. Extra splits and restore/resolve/exploration
costs are plausible explanations for the lack of net gain; this is an inference, not a
separately isolated measurement. The profile's top GMEM passes include 1131x2442 and 1125x2436,
so the real CA intermediate does reach GMEM. Unsafe decisions remain uncommon; this image
does not enable per-decision reason logging.

Both valid profiling boots have zero SMMU faults, panics, or ticket/submit errors. The
corrected g1 shows live BEGIN/SEAL with zero stale/error/timeout counters in the checked logs.
Static Home and CC dumps show no obvious corruption relative to baseline (clock/battery differ).
Settings list and Safari content also look intact; scroll position/content differ between captures.
Notification Center is not visually signed off: baseline and GMEM surface dumps both contain
banded/stale regions, and the date/header differs between individual surfaces. This may involve
capture timing or rendering; the cause is not established here and it is not evidence of a
GMEM-specific regression. These captures cannot substitute for the user's motion check.
## Framebench

Order: `s3fb-base1`, excluded partial `s3fb-g1a`, `s3fb-g1a2`, `s3fb-base2`, `s3fb-g1b`.
The four valid runs captured and exported successfully, with zero event/sample drops and no
SMMU fault, panic, or ticket/submit error. Both images retain the full mode-2, queue and ticket
arguments. Baseline uses stage-2 lib `1772b043`; GMEM uses the pixel-gated `d39a3243`.
Each boot waits 150 seconds after unlock before the standard framebench workload.
GPUPROF/DRAWPROF are disabled. Framebench itself samples CPU during A phases; Home B, CC B
and Spotlight repeat do not use those CPU sampling windows. No clock changes.

Each cell is **swap arrivals/s (median/p95 interval in ms)**. These are update observations,
not independently validated physical displayed FPS.

| Phase | Baseline 1 | GMEM 1 | Baseline 2 | GMEM 2 |
| --- | ---: | ---: | ---: | ---: |
| Home B | 33.90 (28.17/45.66) | 32.88 (28.18/46.23) | 32.28 (28.30/50.86) | 32.95 (29.00/46.90) |
| CC A | 25.30 (37.33/56.81) | 22.51 (40.17/65.17) | 23.56 (38.56/62.16) | 22.85 (41.47/70.25) |
| CC B | 24.16 (37.22/63.55) | 23.58 (39.85/60.80) | 23.58 (39.10/67.41) | 23.42 (39.76/63.98) |
| Spotlight repeat | 26.26 (34.44/66.04) | 27.81 (35.00/56.16) | 25.74 (34.02/67.44) | 25.32 (34.51/77.81) |

Descriptive means of the two run rates: Home 33.09 -> 32.92 (-0.52%), CC A 24.43 -> 22.68
(-7.18%), CC B 23.87 -> 23.50 (-1.56%), Spotlight 26.00 -> 26.57 (+2.18%). These are not
pooled rates or confidence intervals. The apparent Spotlight gain is not repeatable across
the two pairs, and the Home/CC B changes are smaller than observed baseline variation.
There is no basis for claiming the intended global uplift. No consistent p95 improvement.
Evidence: ignored `research/ab/<run>/` manifests, summaries and reports; `logs/netlog-<run>.txt`.

`s3fb-g1a` is excluded: command-port timeout during Home A after 23.3 seconds, and metadata
export also timed out. Spotlight repeat was 25.35/s and warmup 31.00/s, but Home A had no swap
arrivals during commanded motion; Home B and CC were not captured. GPU completed 4271/4271
afterward, no SMMU fault/panic/ticket error, and reboot/park succeeded. The cause is unresolved;
neither a GPU hang nor a clean acceptance run is established. A fresh bounded attempt is
`s3fb-g1a2`, which completed, as did `s3fb-g1b`. Framebench now records the exact command/snapshot that fails, without changing
timeouts or retrying commands.

## Recommendation and remaining work

**Keep SWEETCA_GMEM off. Do not promote the current selector.** It passes the bounded pixel
tests and reaches real CA targets, but neither the valid GPU profile nor two framebench pairs
show the intended benefit. There is also an unresolved partial capture and no user motion
sign-off. Stage 1's correctness fixes and stage 2's barrier work remain valuable separate work;
this result does not install them in production.

Further tuning has not been attempted in this run: no per-barrier split, mid-pass resolve,
or margin/sample/retry sweep. If continuing GMEM, start with the ~14.4 ms/frame left in Home's
full-screen retained-feedback passes and measure a separately pixel-gated redesign. Do not
repeat the rejected image or treat the original truncated profiling result as valid. Otherwise,
the user can accept leaving this rule off and choose the next optimization. No kernel change
or production installation is proposed on the present evidence.

## Final device state

Production `/usr/local/bin/libsweetca.dylib` was read back after the final framebench:
SHA256 `4780fbaaafcf680cbf709f4c40512499576ba09e3442f62ace41e7031ee214b8`, unchanged.
Both temporary `libsweetca-s2.dylib` and `libsweetca-s3.dylib` were removed; the pixel-gate
executable had already been removed. CI libraries remain in ignored local artifact directories.
Future temporary boots using those paths must copy the test libraries first.

Phone parked in r109 charging shell at 18:01: battery 71%, positive charging current,
backlight 0, charge voltage 4050000. Both private session/framebench locks released.
No production-library replacement, flash, kernel change, or clock change during this evaluation.
The payload truncation guard is commit `649993e`; framebench failure logging is `ac758d5`.
