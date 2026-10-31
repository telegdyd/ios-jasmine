# Metal step 7: backboardd on Metal (in progress)

2026-10-31, user: "re-run the probes, then start step 7". Temporary `fastboot boot` only; side files in
`/usr/local/bin`; no flash, no root bundle/plist, production libsweetca untouched. Raw logs, scripts and shots:
ignored `research/metal-step7/`.

## Probe re-run with the corpus-pass libbgair (PASS)

VM `metal-s7a` (libbgair `90cfa405` = corpus cq3; libbgmtl, injector, libsweetca `1441c96d` byte-identical to
step 6). Temporary boot of the installed `shim-boot-j0120on-slotb.img`, two rounds each:

| Probe | Result per round |
| --- | --- |
| bgair_test | 3 passed, 0 failed |
| bgmtl_probe | 11 passed, 0 failed |
| bgmtl_quad_probe | output identical to step 5 |
| bgmtl_render_probe | 25 passed, 0 failed (incl. expected 64 KiB UBO refusal) |
| registered probe (bgmtl_exec 1) | 25 passed, 0 failed |

Stock process after: no device, injector absent. Console: 0 SMMU faults, panics, ticket errors, crashes.
Production readback `bb3a7a9e...` unchanged.

## How backboardd gets Metal

`EAGLServer::renderer()` tries `CAMetalContextCreate()` first (GPU.md G2 step A); with a Metal device present it
uses `new_metal_context`. So no CA patching: the step 6 injector, allowed in `backboardd` too (still needs
`BGMTL_ENABLE=1`), registers the device before CA asks. Image `research/metal-step7/mkimg-mtl.sh` ->
`shim/out/shim-boot-j0120on-metal-s7bb.img`: installed j0120on settings, sweetenv
`backboardd:DYLD_INSERT_LIBRARIES=/usr/local/bin/bgmtl_inject.dylib,BGMTL_ENABLE=1,BGMTL_BB=1` (no libsweetca in
backboardd, so no GL fallback in this boot; a plain reboot returns to installed boot_b).

## Rounds

1. **r1** (`metal-s7b`): CA picked BGMTLDevice, loaded QuartzCore's default.metallib, then aborted "Metal failed to
   build render pipeline": colour attachment format **551** (`RGB10A8_2P_XR10_sRGB`) unknown. backboardd crash loop
   (sig 6), launchd respawns. Fix: 551 stands in as BGRA8 sRGB, beside Chlorophyll's 550 -> BGRA8.
2. **r2** (`metal-s7c`): no crash; ~20 pipelines (uber shader, blurs, home affordance, overdrive). The user saw the
   boot "glitchy and pretty broken". Log: 19,389 refusals in 5 min of client IOSurfaces with 288/352/544-byte rows
   (a5xx imports multiples of 64 only), and BGR5A1 (Metal 43) refused (a5xx has B5G5R5A1, not R5G5B5A1).
3. **r3** (`metal-s7d`, image s7bb with `BGMTL_BB=1`): **zero refusals, zero crashes/faults/command-buffer
   failures**. Lock screen drawn through Metal with correct colours (wallpaper, clock, status bar, camera button)
   in the swap-surface captures (`s7-r3-shot*.png`), BUT the captures show moving horizontal black bands with ragged
   edges, and CA's render-into-our-surface capture (`sweet_shot` default mode) came back all black.

Fixes in r3:
- Sampled IOSurfaces whose pitch is not a multiple of 64 (and that CA asked only to sample; usage not Unknown) become
  textures of own memory with the pixels copied in, re-copied whenever the surface seed moves (libsweetca's
  `copy_surface` approach). Writable/RT ones are still refused, the refusal now names CA's usage.
- Metal 43 BGR5A1 resolves to `B5G5R5A1` when the screen lacks R5G5B5A1; `rwa_texture_write` / `rwa_texture_read`
  exchange the red and blue fields. IOSurface imports of format 43 would show red/blue exchanged (not seen).

## Open (next)

- **The black bands.** Guess, not verified: the CPU-side captures read stale cache lines (`BGMTL_BB` skips the
  per-commit clean/seed bump; a new surface's zeros are black), so the captures may not show what the panel shows.
  Alternative: CA swaps before the GPU finished the frame. Needs the user's look at the panel and/or a capture that
  cleans caches first; then check `waitUntilScheduled`/present ordering against IOMFB swap.
- One ASTC_4x4 no-copy texture refresh computes its row as 832 bytes for 828 texels (texel rows instead of block
  rows) in `bgmtl.m` `rwaTexture` (`_ncLength / height`): refused once per boot.
- Unimplemented selectors answered zero: `setCompletionQueue:`, `setGPUPriority:` (command queue).
- Not yet: unlock/home screen, UI rounds, frame times vs GLES, libsweetca + libbgair in one process.
