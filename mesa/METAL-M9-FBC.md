# M9: CA_DISABLE_FRAMEBUFFER_COMPRESSION, fd5, and framebuffer compression

Research only. No production code, no env change, no phone access, no push.

## Blocker: WSL is inaccessible from this sandbox

The files are in WSL as the follow-up said, but the DSH process sandbox refuses
to start WSL:

- `wsl.exe -e bash -lc '…'` and `wsl.exe -d Ubuntu -- echo hi` both return
  `Wsl/E_ACCESSDENIED`;
- `cmd /c wsl ...` returns the same;
- `\\wsl.localhost\Ubuntu\home` and the other distro names return
  `PermissionDenied`.

The VM also has no `~/ios-work`/`ipsw`, and `research/dsc/` is absent, so no
copy of the QuartzCore image is readable here. I therefore **cannot extract or
disassemble `CADeviceUseFramebufferCompression` in this environment**, and the
caller/check trace remains unresolved. The user-provided symbol names
(`CADeviceUseFramebufferCompression`, `CAEnableFramebufferCompression`) are
consistent with the string evidence but were not independently disassembled
here.

The remaining findings below are from the Mesa/bgmtl source and the capture
logs; they do not answer the exact QuartzCore checks.

## 1. What bgmtl answers today

Searched `mesa/metal/src/bgmtl.m` and `air_metal.c` for the compression
selectors CA would use:

- There is **no** `supportsLossyCompression`, `supportsLosslessCompression`,
  `supportsFamily` compression special case, `MTLTextureCompressionType`,
  `setCompressionType:`, `allowGPUOptimizedContents`, or compression property
  implementation. The only compression-related source terms are the UBWC/tiling
  checks in air.
- `-supportsFamily:` answers Apple1..Apple3 by default (`bgmtl.m:893-903`);
  `BGMTL_FAMILY` can raise the ceiling, but there is no compression capability
  answer.
- `-newTextureWithDescriptor:` (`bgmtl.m:1026-1029`) passes the descriptor’s
  pixel format/usage/storage to `BGMTLTexture`; no compression type or
  allow-GPU-optimized flag is read. The IOSurface variant
  (`:1055`) likewise ignores descriptor compression.
- Unsupported/private format 500 is refused before allocation by the format
  table (`air_metal.c:1234-1296`, `:1493-1496`); the caller-evidence hook is
  `bgmtl.m:123-136`.

**Inference (not observed):** if QuartzCore asks for lossless/lossy
compression, absent selectors answer the default (NO/nil); CA’s compressed path
cannot engage. Removing `CA_DISABLE_FRAMEBUFFER_COMPRESSION` therefore cannot
make a5xx compression real by itself. The one framebench after removing it
(Home 29.2/s, CC A 22.1, CC B 27.0, Spotlight 18.5) was confounded and showed
no gain (`notes.md` top; `logs/fb-fbc-on.txt`). The flag should stay removed;
there is no evidence it helps.

### Format 500

`logs/netlog-fbc-on.txt:3888` and `logs/netlog-m8pe1-install.txt:3888` both
report the same refusal: a `1105x1160`, type 2, usage `0x1` sampled IOSurface
texture, `pixelFormat 500`. This is a private/compressed-looking sampled format,
but the evidence does **not** establish its layout or that it is CA framebuffer
compression. Refusal counts in these two logs are 202 vs 81, but the captures
are different lengths/conditions, so that is not a normalized A/B and does not
show a flag effect. The earlier M2 evidence (`mesa/METAL-M2-REFUSALS.md:29-51`)
also found no layout/pixel mapping and refused it; supporting 500 would need a
separate format mapping and pixel validation.

## 2. fd5 UBWC status

Observed in the Mesa tree used by the VM build:

- `get_best_layout` gates UBWC with
  `bool ubwc_ok = is_a6xx(screen) && !is_props_is_a702;`
  (`freedreno_resource.c:1328`); a5xx therefore never selects
  `FD_LAYOUT_UBWC`.
- `fd5_layout_resource` can mark `ubwc` only if the caller passes
  `FD_LAYOUT_UBWC` (`a5xx/fd5_resource.c:26-38`), which the gate above prevents.
- The a5xx emitter still writes zero UBWC flag-buffer registers and comments
  “when we support UBWC” (`a5xx/fd5_gmem.c:179`).
- `DRM_FORMAT_MOD_QCOM_COMPRESSED` is selected by the common resource layout only
  for a6xx (`freedreno_resource.c:1089-1095,1328-1353`).

**Conclusion:** fd5 cannot produce UBWC resources in this tree. Any plan that
answers CA’s compression queries and backs textures with UBWC is not
implementable on Adreno 512 without a new fd5 UBWC layout/emit/flag-buffer
implementation (and a kernel/display story for the flag buffer).

Upstream’s `fdl_layout.h` says UBWC color compression is “a5xx+” and exposes
`fdl5_layout_image` plus `ubwc_slices`/`ubwc_layer_size` (public Mesa mirror:
`src/freedreno/fdl/freedreno_layout.h`). So the hardware/layout concept exists;
our tree’s `is_a6xx` gate is the local blocker. A concrete fd5 UBWC enablement
would need:

1. let `get_best_layout` choose `FD_LAYOUT_UBWC` for a5xx, with
   `DRM_FORMAT_MOD_QCOM_COMPRESSED` and `fdl5_layout_image(..., ubwc=true)`;
2. program `RB_MRT_FLAG_BUFFER(i)` address/pitch/array-pitch and
   `RB_DEPTH_FLAG_BUFFER` from the UBWC slices; today `fd5_gmem.c:179-186` and
   `:225-228/:284-287` write zeros;
3. set the fd5 texture descriptor’s UBWC/flag-buffer fields and tile/flag mode
   (the local fd5 texture path has no UBWC field setup);
4. teach `fd_resource_ubwc_enabled`/offset and the readback paths: `getBytes`,
   `replaceRegion`, and `rwa_texture_read_unlocked` currently refuse/gate UBWC
   (`air_metal.c:2606-2621,7994,8022`), so CPU access must decompress or refuse;
5. keep the final CA/IOSurface/display surface linear and add a resolve/
   decompress at the end of the pass (the display path reads the IOSurface
   linearly), or teach the kernel scanout about the flag buffer;
6. make CA request the compressed surface/format if it is to benefit from the
   framebuffer path; `rwa_texture_from_surface` currently imports linear only
   (`air_metal.c:1900-1912`).

This is a driver feature (layout + emit + descriptor + resolve + validation),
not a contained bgmtl change. Upstream a5xx UBWC work exists in the kernel
(`drm/msm` UBWC config for a5xx), but Mesa’s a5xx path here is still gated off.

### Cheaper bandwidth levers in this stack

- **Tiled non-UBWC a5xx layouts:** `get_best_layout` already returns
  `FD_LAYOUT_TILED` for implicit non-linear resources
  (`freedreno_resource.c:1349-1358`); imported/display IOSurfaces are forced
  linear (`:1320-1326`). GPU-private intermediates can stay tiled; the final
  surface cannot without a resolve. This is already mostly in use.
- **Format choices:** CA’s own RGBA8/BGRA8 vs wider formats; bgmtl cannot
  transparently change a layer’s pixel format without changing the app’s
  contract.
- **Reduce full-screen passes/blur/overdraw:** the sweep’s DDR sensitivity
  points here, but it is not framebuffer compression.
- **GPU-private intermediates:** already tiled; making them UBWC is the fd5
  feature above.

### IOSurface import and final scanout

- `rwa_texture_from_surface` imports with
  `.modifier = DRM_FORMAT_MOD_LINEAR` (`air_metal.c:1900-1912`) and
  `resource_from_handle`; imported IOSurfaces are CPU-visible/linear by
  construction. CA drawables/final surfaces are this path (`:1946-1987`).
- The display/sweetfb path reads the final IOSurface linearly. A compressed
  final attachment would need a resolve/decompress at the end; intermediates
  could remain compressed only if they are GPU-private, which fd5 cannot do
  (above).

**DRAM estimate:** the clock sweep shows DDR 1804→1296 costs Home −17% and
CC −20/−21%, while GPU clock barely matters (`NOTES.md` clock-sweep entry).
That bounds the bandwidth opportunity, not a UBWC win. No fd5 UBWC exists, so
there is **no implementable measured estimate** from this stack. Typical UBWC
color traffic wins are tens of percent of color bandwidth, but that is a
general property, not a measurement here.

## 3. Fix ranking / why no contained fix

1. **CA queries + UBWC backing** — not possible on fd5; would require a new
   fd5 UBWC resource layout, flag-buffer setup in fd5_emit, and scanout resolve.
   Not contained; high risk.
2. **Independently allocate GPU-private intermediates as UBWC** — same fd5
   blocker; not contained.
3. **Smaller formats / removing redundant passes** — outside this flag and not
   a compression implementation; no source change made.
4. **Do nothing to the flag** — keep `CA_DISABLE_FRAMEBUFFER_COMPRESSION`
   removed as the user did. The current stack does not advertise compression and
   the one removal capture showed no gain.

**No production fix was implemented.** The smallest real fix would be: obtain
the QuartzCore/IOSurface compressed path evidence, add an fd5 UBWC-capable
layout/emit path, keep imported/final display surfaces linear with an end-of-pass
resolve, and gate it behind an env switch for A/B. That is a driver feature, not
a contained bgmtl change; CPU readback/getBytes/replaceRegion would also need
decompress/refuse handling.

## Files / tests

- Report: this file.
- No `mesa/metal` or `bgmtl` code changed; no env changed.
- No tests or build are part of this deliverable. The report is committed
  because the task requested it; no Apple binaries or disassembly are included.
