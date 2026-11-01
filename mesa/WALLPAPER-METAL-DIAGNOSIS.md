# Wallpaper diagnosis, 2026-11-01

Investigation requested after the installed Metal boot. Read-only phone inspection;
no reboot, wallpaper selection, renderer replacement, build, CI run or flash.
Raw device logs and crash report are ignored under `research/wallpaper-metal/`.

## ASTC repair, 2026-11-01 (subsequent authorized implementation)

Chlorophyll commit `b5bfde9` replaces the no-copy `length / height` heuristic
with format-aware packed 2D mip uploads. It checks the full mip chain against the
allocation length before reading it, handles partial blocks, and ignores trailing
allocation padding. A short allocation or unsupported texture shape is refused
at texture creation. Existing upload stride validation remains intact.

Further local CoreAnimation analysis: `MetalContext::update_texture` rounds the
memory length to a page before calling `newTextureWithBytesNoCopy`. Consequently,
dividing length by block-row count would also be incorrect. The length bounds the
allocation; the format and mip dimensions determine the packed image layout.

Local VM build `wallpaper-astc3` passed (no CI). New P14 runs the real GPU sampler
against ASTC 4x4 constant-color blocks at 144x144, 224x487, 828x9, and 13x9 with
four mip levels. It checks every mip, page-rounded trailing bytes, CPU mutations
between command buffers, and refusal of an allocation one byte too short.
The final comparison explicitly rejects NaNs as well as wrong finite values:

| Libraries | Mode | Full suite | P14 |
| --- | --- | --- | --- |
| Installed-version metal-s7s | plain, --bb | 26 pass / 1 fail each | 1,098,980 failures (includes four missing short-buffer refusals) |
| wallpaper-astc3 | plain, --bb | 27 pass / 0 fail each | zero wrong / 1,099,392 sampled channels |

Temporary image `shim/out/shim-boot-j0120on-wallpaper-astc.img` was accepted by
fastboot (send/boot OKAY) and booted the existing kernel with candidate libraries
isolated in `/usr/local/w/`. After gallery loading settled, the category icons,
Collections preview and Color preview render correctly. Astronomy remains blank.
CURRENT cards remain gray even after visiting the gallery. Thus this fixes the
confirmed compressed-image upload fault, not every Wallpaper problem.

`research/wallpaper-metal/gallery-settled.png` preserves the repaired gallery;
`current-final.png` preserves the remaining gray cards. The captured candidate
boot ring through the gallery has zero no-copy refresh/refusal errors, GPU SMMU
faults, command-buffer failures, backboardd crashes, or SpringBoard crashes.
Final ticket samples show zero fallback/stale/error/timeout. AegirPoster still
has 28 crashes in that captured ring; its separate Metal scope is unchanged.

Installed: production libbgair/libbgmtl were first backed up and verified against
metal-s7s, then replaced with the candidate and read back byte-for-byte. SHA256:

```
libbgair 176d9a119148fe3bf59f19f5cd0b31bc141651f76ebdb3672bc94312468c889a
libbgmtl 090b6f6cff59977129732adaafc1d398085a08f20050e851993eed3315669395
```

A plain reboot (`fastboot reboot`, no flash) into the existing installed Metal
boot_b succeeded. The installed boot's gallery again shows correct category
icons and Collections/Color previews (`research/wallpaper-metal/installed.png`).
Its 100-second captured console has zero no-copy errors, GPU faults, command
failures, SpringBoard/backboardd crashes, or queue fallback. AegirPoster still
crashes (24 in that capture). Rebuilt libsweetca and the injector are byte-identical
to metal-s7s and were not replaced. No kernel/boot partition, poster database,
wallpaper selection, or process registration was changed.

Phone left running the installed Metal boot with the ASTC fix and the gallery
open. Rollback if needed: restore the two `production-before-*.dylib` backups
from `research/wallpaper-metal/` to their original `/usr/local/bin/` names and
plain reboot. Astronomy registration and CURRENT snapshot diagnosis remain next.

## Confirmed compositor upload bug

The current boot console contains 4,227 `no-copy texture refresh` rejections:

```
227 bytes per row for 144 texels of MTLPixelFormatASTC_4x4_LDR, which need 576
235 bytes per row for 224 texels of MTLPixelFormatASTC_4x4_LDR, which need 896
832 bytes per row for 828 texels of MTLPixelFormatASTC_4x4_LDR, which need 3312
```

`mesa/metal/src/bgmtl.m`, `-[BGMTLTexture rwaTexture]`, computes the CPU
no-copy upload stride as `_ncLength / _shape.height`. ASTC has rows of compressed
blocks, not rows of individual pixels. `air/air_metal.c:caller_stride` correctly
requires `ceil(width / 4) * 16` bytes for ASTC 4x4 and refuses these uploads.
`rwaTexture` logs the failure but still returns the unfilled texture for sampling.
This explains how normal text/layout can coexist with black or corrupted images.

The current PosterBoard log records gallery hero icons at 72x72 points; the
installed canvas uses scale 2. Their 144-pixel width matches the rejected uploads.
Gallery snapshots also use 112.5-point widths (approximately 224/225 pixels).
PosterBoard successfully loads/writes hero `.atx` assets from the asset catalogs
for Emoji, Color and Astronomy, and successfully snapshots several Color entries.
Thus missing wallpaper bundles or a universal snapshot-provider failure cannot
explain the gallery. Failed ASTC uploads are the strongest explanation for the
black icons/cards; visual repair has not yet been tested.

Next implementation: make the no-copy memory-layout calculation format-aware
(block rows, padding, mip levels/slices and length validation), rather than divide
by pixel height. Derive/check the actual caller layout before assuming that all
memory length is one tightly packed mip. Add a focused ASTC no-copy GPU sampling
probe including a partial block dimension, build on the local VM, then verify the
same Settings gallery. The existing backend upload stride check should remain.

## Astronomy has a separate producer-side failure

The console records 36 AegirPoster SIGABRT crashes in this boot. The current
backtrace passes through abort, libc++abi terminate, objc terminate and FrontBoard
scene creation; it does not preserve the original exception backtrace/reason.
The newest saved AegirPoster `.ips` on the device is older (2026-10-27 22:33:30):
its exception backtrace reaches `__NSArrayM insertObject:atIndex:` from
`NUNIAegirRenderer getOrCreateUniformBufferforFrameBufferIndex:`, then its offscreen
render/snapshot path in NanoUniverse and `CLKUIMetalQuadView`.

Installed boot arguments inject/register Metal only in backboardd. SpringBoard
still gets `/s.dylib`; Preferences, PosterBoard and AegirPoster have no Metal
registration. The constructor in `inject/bgmtl_sweet_inject.m` also explicitly
allows only backboardd and bgmtl_registered_probe, even with BGMTL_ENABLE=1.
Therefore compositor Metal does not provide a Metal device to Astronomy's own
renderer. A nil Metal buffer causing the old array insertion exception is a
strong hypothesis, not a verified current exception reason. Enabling Metal for
the extension will need a narrowly scoped test and may expose further driver
API/shader requirements; do not assume merely extending the allowlist fixes it.

## Gray CURRENT cards: older handoff explanation is superseded

The 2026-10-27 handoff said no wallpaper configuration was selected. Current
PosterBoard logs instead show a selected Collections configuration and then a
determined active configuration. Snapshot files for it are enumerated. An initial
`currentActiveConfiguration: (null)` during startup is followed by a non-null
active configuration, so it is not evidence that none is configured now.

The gray cards could share the failed compressed-image upload path, or involve
snapshot generation/loading. Current logs also contain sandbox-extension ENOENT
messages for poster paths, but successful snapshots elsewhere mean these cannot
alone establish the root cause. Recheck the cards after the proven upload bug is
fixed; then inspect the selected configuration's snapshot content and Settings'
consumer if they remain gray. No configuration/cache was deleted or reset.

## Device state and limits

The captured boot ring has zero `SMMU fault` and zero backboardd crashes; display
ticket statistics show zero fallback and zero stale/error/timeout in its final
samples. Counts above cover the captured boot ring, not a timed reproduction.
Unified-log reads were bounded by sweetd timeouts and are partial; no new UI
interaction was performed. Installed Metal boot and libraries remain unchanged.
