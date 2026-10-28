# Task 24: default-off pixel gate failed

**Resolved 2026-10-28:** see [the final section](#2026-10-28-root-causes-found-fixed-four-case-gate-pass) (two real bugs fixed, four-case gate PASS).

**Earlier readiness check, 2026-10-26 02:10:02 Budapest:** user approved the
paired baseline diagnostic session. Acquired the shared lock, but charging
shell capacity was13%, below the agreed30% threshold. Reported Charging,
+41503uA,3718984uV, chargeronline1, backlight0,float4050000. No iOS boot,
install or diagnostic ran. Left charging unchanged and released own lock.
Evidence ignored under `research/t24/diagnostic-session/`. Prior capacity16%
does not establish a charge-rate estimate or the cause of the lower reading.
Session approval is recorded but unused; wait for sufficient charge before
the bounded matrix. No automatic follow-up is scheduled.

2026-10-26, Budapest. Candidate source `8b6f7e0`, Mesa CI `40250210168`
PASS. The first GPU case failed with the experimental barrier **disabled**.
The matrix stopped; no enabled case or performance trial ran. Task 24 remains
open, candidate default off, production unchanged, no gain established.

## Exact session

The user authorized one bounded four-case session and made the phone available
in its charging shell. Acquired the shared phone lock, observed Charging, 24%
and backlight 0. Rebooted via the existing recovery helper, checked active slot
b, then `fastboot reboot` of the existing iOS installation at 01:49:11. No
partition flash or active-slot change. Boot log confirms production injection
and DDR1804. Installed only `/usr/local/bin/sweetgpu_gltest-t24barrier` and
verified its downloaded readback against the CI artifact:
SHA256 `68fcde5cf3232193e75a9ad2be8eda3f6e4a16004641af42b479eba2bb57fae3`.

At 01:51:18 ran `--sysbarrier-off`, with threaded context left at its default
and `FD_MESA_DEBUG=sysmem,nofp16`. Exit 1, eight steps in 97.9 ms. This timing
is a correctness-test duration, not performance evidence. No retained-path
marker and no reported nonzero GL error. The first seven existing steps pass.
The added feedback step reports:

| Check | Incorrect pixels | Result |
| --- | ---: | --- |
| Eight repeated feedback draws | 0 / 4096 | PASS |
| Feedback, clear, partial-scissor feedback | 4096 / 4096 | FAIL |
| Target revisit and distinct imported alias | 112 / 4096 | FAIL |
| Other pending target preserved | 0 / 4096 | PASS |

For the clear test, outside the scissor the result is `(24,36,66,255)` instead
of `(32,64,96,255)`. Inside it is `(36,42,69,255)` instead of `(44,70,99,255)`.
These values are consistent with the clear not taking effect and later
feedback adding to the earlier solid value; this is an inference, not a proven
root cause. In the alias test, the first reported stale pixels begin at
`(48,11)` and contain `(48,48,72,255)`, the preceding eight-draw result,
instead of `(68,90,117,255)`. A stale patch does not establish which cache,
import, batch, or readback boundary is wrong.

Raw case log SHA256
`0a2750c501414e351c9129cdc69a0bc32262dc766743770757ea7ba92f6291ff`.
Evidence is ignored under `research/t24/barrier-session/`: `off-tc.txt`,
`cases.json`, boot/console logs, timestamps, artifact readback and production
before/after copies. No dumps or device identifiers are committed.

## What this establishes

This build's disabled baseline does not pass the new test. It neither validates
nor disproves the retained barrier, because that path never ran. It also does
not prove the same failure in the installed production build: the test embeds
the candidate Mesa plus all current patches. Preserve that distinction.

Offline inspection confirms the disabled hook returns before emitting packets;
the new clear split is conditioned on the retained-batch flag. The wrapper uses
`_mesa_TextureBarrierNV`; the ordinary driver barrier still globally flushes.
`fd5_clear` emits the a5xx fast-clear/blit path and sysmem prep selects BYPASS.
Those are audit leads, not evidence sufficient to change the driver.

## Next gate before any speed trial

1. Preserve these failing uninterrupted sequences and their pixel expectations.
   Do not relax tolerances or insert a finish into the acceptance sequence.
2. Prepare a diagnostic test with separate checks of clear-only, draw->clear,
   feedback->clear, and clear->sample on imported linear color targets. Compare
   native clear with a solid draw in separate controls; compare the original
   path with explicit completion only in diagnostic controls. Check the target
   immediately before alias sampling and keep the final original alias test.
3. Run that diagnostic on a build predating patch0008 and on the disabled
   candidate, TC on/off. This separates a pre-existing path failure, candidate
   regression and test/lifetime problem. Audit clear ordering and imported BO
   identity/cache visibility against the outcome before making a fix.
4. Only after a supported fix passes the original disabled baseline, rerun all
   four acceptance cases. Enabled cases require the retained-path marker and
   correct pixels. Then coordinate matched performance captures separately.

No automatic repeat phone session is authorized by this stopped matrix.
No CA library replacement, clock/default change or GMEM enablement occurred.

## Offline diagnostic prepared after the failed gate

`sweetgpu_gltest --feedback-diagnostics [--no-tc]` forces the barrier OFF and
sysmem/nofp16 before display creation. It preserves the seven existing steps,
then runs separate diagnostic controls instead of the acceptance feedback step.
Without that flag the original uninterrupted acceptance sequences and pixel
expectations are unchanged. Diagnostics report all mismatches and still fail
their process if any check fails; they do not reinterpret a known failure as
a successful correctness gate.

For both imported BGRA targets and ordinary GL RGBA allocations, it checks:

- Clear-only, draw->clear, clear->sample, feedback->clear->sample.
- Explicit completion before clear and after clear as separate controls.
- A solid draw replacing only the clear operation as a separate control.
- Target switches/revisits using the same texture name or its alias.
- The target immediately before alias sampling as an intentional readback
  checkpoint control, then the same switch/revisit sequence.
- Preservation of the other target for each switch/revisit control.

The ordinary allocation control reuses the first texture name where the
imported control uses its third imported name; it does not claim to test an
independent alias. The imported third name shares the wrapper's cached pipe
resource with its first name. The 28 diagnostic checks are neither a speed
test nor a substitute for the four-case acceptance gate.

Optional workflow input `mesa_task24_controls=true` saves the normal signed
artifacts, reverses only patch0008 in the disposable CI source tree, rebuilds
and signs `sweetgpu_gltest-pre-sysbarrier`, and exports both binary hashes and
source identity in `task24-control-provenance.txt`. The original signed library
is retained untouched in the artifact directory. This control is not a build
of the installed production revision; it isolates patch0008 only.

Local GCC syntax check uses real Mesa GLES2/sweetgl declarations with external
IOSurface/CoreFoundation function declarations; this does not validate Darwin
linking or GPU behavior. All eight regenerated patches apply; reversing0008
also passes its application check. Actual iOS compile/sign remains the CI gate.
No driver fix has been made, and no further phone session has run.

**Paired build ready:** source `339bb02`, Mesa CI `40252267715` PASS (3m22s),
including the pre-experiment rebuild/sign step. Downloaded Mach-O headers,
diagnostic strings and CI-exported hashes independently checked. The retained
marker is present in the normal binary and absent from the pre0008 control.
Artifacts/provenance/logs are ignored under `research/t24/diagnostic-ios/`,
`diagnostic-artifacts.json`, `diagnostic-ci.json`, `diagnostic-build.log`.

| Signed test | SHA256 |
| --- | --- |
| Current, disabled by diagnostic mode | `087c5668b339b8705c71f2a297ce1f71b83798bce6e63ea7a0a1e5839591c684` |
| Patch0008 removed | `1ed0608b3c5eb1dae8734168707edddab0c0bd01707ec61005b2a313f05051ea` |

These are compile/sign results only; no new GPU result or root cause established.

The next bounded device diagnostic is four processes, each with a 20-second
remote execution limit: current test and pre0008 test, each with
`--feedback-diagnostics`, then each with `--feedback-diagnostics --no-tc`.
All force retention off. A completed diagnostic may exit1 because it reproduced
pixel mismatches; retain its per-check results and compare them across modes.
A missing check, timeout, nonzero GL error, retained-path marker, or new GPU/
SMMU fault aborts the session. No speed run or enabled-barrier case belongs to
this diagnostic. Use test-name binaries, verify production bytes unchanged,
remove own files and restore r109 charging afterward. First check charging-shell
battery capacity and defer the iOS boot if still low (below30%); the preceding
session ended at16%. Do not spend that remaining battery on repeated boots.

## Cleanup and final phone state

Removed the sole test binary. Production before/after bytes have identical
SHA256 `14e32aea4121e9c8a357da8f5e6322fe572a85f1c22e496990af0e687cb19261`.
No new runtime GPU/SMMU fault or panic was found in the captured console;
startup self-test FSR0x400 remains the known boot baseline. Unrelated widget
extension check-in timeouts appear in the console; no claim of a clean system
log is made. Own collectors exited. Rebooted to fastboot, verified slot b and
temporarily booted `shim/out/nura-r109-boot_a.img`. At 01:54:12, shell reports
charger online1/Charging, battery Charging, +162597 uA, 3701650 uV, 16%;
backlight readback0, charge voltage4050000. Charger current/voltage sysfs reads
return errors, so the quoted current/voltage are from qcom-battery. Shared
phone lock released only after this restoration was verified.

## 2026-10-28: root causes found, fixed, four-case gate PASS

Stage 1 of the [GMEM plan](PERF-GMEM-PLAN-20261028.md). Installed iOS (boot_b, j0110 + mode 2,
production library 4780fbaa) on the home screen; GL tests are separate processes, so no
reboot, flash or library change. Test-name binaries only, all removed afterwards; production
library readback before and after: SHA256 `4780fbaa...e214b8`, unchanged. No GPU/SMMU fault,
hang or panic in the console during either session (`netlog-diag.txt`, `netlog-fix.txt`).
Raw evidence ignored under `research/t24/stage1/`.

### Diagnostic run (before the fix)

Source `cac0ae9` (= current Mesa incl. ds8, plus 0008), Mesa CI `40618671188`
(`mesa_task24_controls=true`): test `69ec78fe...`, pre-0008 control `4c997757...`.
`--feedback-diagnostics`, each with and without `--no-tc` (`diag-cur-tc/-notc`,
`diag-pre/-pre-notc`). Same picture in all four; pre-0008 is no different, so **patch 0008
is not the cause** (its hook is off there anyway):

| Check (imported and GL-allocated targets alike) | Result |
| --- | --- |
| clear only; finish before clear; solid draw instead of clear | PASS |
| draw then clear; clear then sample; feedback then clear then sample | FAIL 4096/4096 |
| finish **after** clear (draw, clear, glFinish) | FAIL 4096/4096 |

The wrong value is always the draw's (draw then clear reads `(16,32,64)`, the solid draw,
instead of the clear `(32,64,96)`), even with a finish after the clear. So a clear that
follows a draw **in the same batch** is lost in memory; one that starts a batch works.

Separately, small failures (16-112 pixels, always whole runs of 16 pixels = 64-byte lines)
only on **imported** IOSurfaces, never on GL allocations, in checks that are otherwise
right, including the "before alias checkpoint" readback. The stale value is exactly the
**previous glReadPixels result** of that target (e.g. `(48,48,72)`, the eight-draw result, in
the original alias failure; `(0,63)` of the original clear failure also shows it). That is
the CPU cache, not the GPU. One more: `cur --no-tc` failed the old **depth** step once
(1800/3600, both quads rejected by the depth test after a depth clear at batch start).
The original acceptance `--sysbarrier-off` also reproduced on today's Mesa
(`accept-old-off-tc.txt`: clear 4096/4096, alias 16/4096).

### Root causes

1. **Sysmem clear ordering (driver).** `fd5_clear` uses the a5xx fast clear, a BLIT event
   made for GMEM. Upstream a5xx never takes a batch with clears to sysmem (the autotune
   fallback picks GMEM when `batch->cleared`); our forced `FD_MESA_DEBUG=sysmem` does, and in
   bypass mode that blit is not ordered after the batch's earlier draws (their color is
   written to memory after it). With barriers off, every `glTextureBarrierNV` ends the batch,
   which is why the acceptance clear (feedback draw, clear, barrier) shared a batch with a
   draw. Whether the blit's write is dropped or overwritten by the CCU flush is not
   distinguished (guess: overwritten). The depth flake is attributed to the same blit path
   for depth (guess; seen once in four runs, absent in all 38 runs after the fix).
2. **IOSurface CPU cache (darwin backend).** Imported IOSurfaces of kernel memory are
   CPU-cacheable, also in Mesa's mapping; the kernel keeps them up lazily (j0053):
   clean+invalidate at the CPU's next `IOSurfaceLock` after GPU work, clean before the next
   job after a writing unlock. Mesa's own CPU access (glReadPixels maps the linear imported
   resource directly) did neither: `darwin_bo_cpu_prep` was a no-op and `fd_bo_cpu_prep`
   never even called it (darwin pipes use explicit sync). Lines cached by an earlier read
   survived the GPU's later writes. GL allocations come from the write-combined pool, so
   they never showed it. Not a test bug; the test simply is the first thing that CPU-reads
   an imported surface twice.

Neither is a test bug, and neither came from 0008. No expectation, tolerance or acceptance
sequence was changed and no finish was inserted.

### Fix (commit `97c59cf`)

- `mesa/patches/0009-freedreno-a5xx-sysmem-clear-order.patch`: with `FD_DBG(SYSMEM)`,
  `fd5_clear` returns false (u_blitter clear, i.e. a draw, ordered like any draw) when the
  batch already has draws or when depth/stencil is cleared. A first-in-batch color clear
  keeps the fast clear (it passed in every run). No effect without forced sysmem.
- `mesa/darwin/darwin_bo.c` (+ `darwin_priv.h`, `apply.py`, regenerated patch 0001):
  imported buffers remember their IOSurface id; `darwin_bo_cpu_prep` looks the surface up
  once and does `IOSurfaceLock`/`IOSurfaceUnlock` (read-only unless the CPU will write), so
  the kernel invalidates before a CPU read and cleans before the GPU's next use after a CPU
  write. `fd_bo_cpu_prep` calls the backend for shared buffers on Darwin despite explicit
  sync. libfreedreno_drm now links IOSurface.framework. Costs only on Mesa CPU access to
  imported surfaces (two traps, plus a flush when the GPU wrote).

### After the fix

Mesa CI `40620265076` PASS (source `97c59cf`): test `ec7135de...`, pre-0008 control
`dd961279...`, libsweetca `bdba84c3...` (not installed). On the phone:

| Run | Result |
| --- | --- |
| `--feedback-diagnostics` current / pre-0008, TC and `--no-tc` | 4 x PASS, 45/45 checks each |
| `--sysbarrier-off` | PASS 21/21, exit 0, no marker |
| `--sysbarrier-on` | PASS 21/21, exit 0, retained-path marker printed |
| `--sysbarrier-off --no-tc` | PASS 21/21, exit 0, no marker |
| `--sysbarrier-on --no-tc` | PASS 21/21, exit 0, retained-path marker printed |
| 5 more rounds of the four cases + both diagnostics (30 runs) | all exit 0, 0 FAIL, markers only in `on` cases |

No nonzero GL error in any run. The four-case acceptance gate passes; the retained barrier
path ran and produced correct pixels in this test. That validates correctness in these
tests only; no performance claim. Production is unaffected until a library with these
fixes is installed (user decision). Open for stage 2: whether CoreAnimation itself hits
draw -> clear in one batch (a possible real glitch source today) and what the u_blitter
clear costs there; measure with GPUPROF before installing.
