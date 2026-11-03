# M9: CA_DISABLE_FRAMEBUFFER_COMPRESSION, fd5, and framebuffer compression

Research only. No production code, no phone access, no push. (The user removed the env line from the phone; see NOTES.)

## 0. What the flag gates in iOS 16.7 QuartzCore (Claude, disassembled 2026-11-03)

Method: `ipsw dyld extract` of QuartzCore from ~/ios-work/gl/dsc (WSL, 20H392), `ipsw macho disass --force`;
CFString keys decoded from __DATA_CONST.__cfstring. Extracted binary and dump stayed in WSL /tmp (not in git).

- `CA_DISABLE_FRAMEBUFFER_COMPRESSION` is entry 61 of QuartzCore's 206-entry `CA_*` debug-env table (vm
  0x1d5b4b960, `CA_COLOR_FLUSH` .. `CA_GLOBAL_BANDWIDTH_CHECK_INTENSITY`). An init loop (0x1883794f8) reads each
  name once and stores a bool at 0x1e1df7710 + index, so this flag is byte 0x1e1df774d.
- That byte is read in three places (0x188357a48, 0x188362aa8, 0x1883bc664). Each read only matters if
  `CADeviceSupportsUniversalCompression` is true (byte 0x1e1df61c8 checked first/alongside); the framebuffer
  allocation site (0x1883bc628..) additionally requires `CADeviceUseFramebufferCompression`.
- `CADeviceSupportsUniversalCompression` = MobileGestalt answer `AoKnINTLPoKML3ctoP0AZg` (a dictionary) ->
  key `universal-buffer-compression` -> CFBool. This is Apple-GPU (AGX) hardware capability data.
- `CADeviceUseCompression` ("IOSurface Compression Enabled") = only if `CADeviceSupportsCIF10` and not
  `CADeviceIsVirtualized`, then MobileGestalt `ChipID` must be in a later part of a built-in chip-id table;
  defaults key `CAEnableIOSurfaceCompression` can override.
- `CADeviceUseFramebufferCompression` ("System UI Framebuffer Compression Enabled") = `CADeviceUseCompression`,
  overridable by `CAEnableFramebufferCompression` when `CADeviceUseCIF10` (MG `Aixt/MEN2O2B7f+8m4TxUA` +
  `CAEnableDeepFramebuffer`).
- No MTLDevice selector is involved: the decision is MobileGestalt + chip id + CA defaults, then CA asks
  IOSurface for Apple's compressed surface layouts (AGX lossless compression).

**Conclusion: on our stack the flag does nothing.** Our device identity is iPhone10,3 (A11), which has no
universal-buffer-compression; CA never reaches the env check, so removing the line is a no-op (consistent with the
one framebench run). Making CA take the path would need faked MG answers (universal-buffer-compression, ChipID,
CIF10) AND an IOSurface/bgmtl implementation of Apple's compressed surface formats AND real GPU compression
behind them (section 2: fd5 has no UBWC in Mesa) AND a linear resolve before the display reads the surface.
Faking the MG answers alone would make CA request formats we cannot back (likely refusals or corruption).
The useful part is the last two items, which do not need CA at all: driver-internal UBWC for GPU-private
render targets (section 3).

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

**No production fix was implemented.** Section 0 shows CA's path is gated on Apple-GPU MobileGestalt data and
Apple's compressed IOSurface layouts, so the realistic route skips CA: (1) an fd5 UBWC layout/emit/descriptor path
in freedreno, (2) used by air for GPU-private render targets the compositor writes and then samples (offscreen
layers, blur passes), (3) final IOSurface/display surfaces stay linear, with CPU readback/getBytes/replaceRegion on a
UBWC resource decompressing or refusing, behind an env switch for A/B. That is a driver feature (weeks, needs
on-device bring-up for fd5 flag-buffer formats), not a contained bgmtl change. Before starting it, measure how
many bytes per frame go to GPU-private intermediates vs final surfaces, since only the former would benefit.

## Files / tests

- Report: this file.
- No `mesa/metal` or `bgmtl` code changed; no env changed.
- No tests or build are part of this deliverable. The report is committed
  because the task requested it; no Apple binaries or disassembly are included.
