# Task 24: default-off pixel gate failed

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
