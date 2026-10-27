# Chlorophyll on jasmine (Adreno 512): port map

Chlorophyll (`mesa/metal`, fork https://github.com/telegdyd/Chlorophyll, branch `adreno5xx`) is the Metal driver of
Bergamota (iOS 18 22H352, Poco F1, Adreno 630). This file lists every place it depends on Bergamota's kernel, on a6xx or on
iOS 18, read from upstream 787338f on 2026-10-28. Nothing here has been built or run on jasmine yet.

## 1. Kernel / libdrm layer (must change)

Chlorophyll talks to Bergamota's kernel through a libdrm stand-in (`gpu/freedreno-sweet/sweet_drm.c`, not in the fork).
We have no libdrm: our `mesa/darwin/` backend talks to SweetGPU's IOKit user client directly.

| Chlorophyll | Where | jasmine equivalent |
| --- | --- | --- |
| `drmOpenWithType("msm", ...)` then `fd_drm_screen_create_renderonly(fd, NULL, &config)` | `air/air_metal.c:528-565` | our `xf86drm.h` stub returns -ENODEV for `drmOpenWithType`. Do what `sweetgl.c:100-106` does: `open("/dev/null")` + `fd_screen_create(fd, &config, NULL)`; the darwin backend ignores the fd |
| `sweet_drm_surface_bo(-1, &sb)`: IOSurface id -> handle, size, iova, offset, pitch, w, h, format, planes | `air_metal.c:253-261`, `:1664` | no direct call. Import with `WINSYS_HANDLE_TYPE_FD`, `.handle = IOSurface id`, as `sweetgl.c:291` does (-> `darwin_bo_from_iosurface`, selector 6). Pitch/size/format must come from `IOSurfaceGet*` in userland instead of the kernel's answer |
| `WINSYS_HANDLE_TYPE_KMS` + `sb.handle` | `air_metal.c:1677` | `WINSYS_HANDLE_TYPE_FD` + IOSurface id; offset = base address & page mask (see `sweetca.c:2574`) |
| `sweet_drm_bo_sync(-1, handle, 0, 0)`: CPU cache clean / clean+invalidate of a surface | `air_metal.c:1741`, `:1831` (`rwa_texture_flush_surface`), callers in `src/bgmtl.m:1284`, `:1658` | **none**: SweetGPU has no sync selector (darwin_priv.h lists 0-7). libsweetca never needed one. Open question: is our IOSurface import coherent, or does it need a new selector? Start as a no-op and test for stale pixels |
| `sweet_drm_info(-1, &info)` -> GPU ready / lost | `src/bgmtl.m:1999-2023`; `bgmtl_gpu_state` used by `inject/` and `plugin/` | SWEETGPU get-param (selector 0), or treat "screen created" as ready |
| `sweet_drm_take_wait_error` (weak) | `src/bgmtl.m:1009-1017` | weak import, absent = fine |
| `extern int fd_mesa_debug`, sets bit 9 for framebuffer-fetch passes | `air_metal.c:7238`, `:7580` | bit 9 is still `FD_DBG_SYSMEM` in 26.2.5. Symbol must be exported from our build |
| `build-ios.sh`: builds `freedreno-sweet`, libdrm.pc, Bergamota cross file, Mesa 25.0.7 meson options | `build-ios.sh` | replace with a job in `.github/workflows/xnu.yml` on our mesa-26.2.5 + `mesa/patches` tree, `-Dfreedreno-kmds=msm` as libsweetca uses |

## 2. Mesa patches (all nine fail `git apply --check` on mesa-26.2.5)

Checked against `~/ios-work/mesa` (052f0a0 = 26.2.5 + darwin backend) with a temporary index.

| Patch | Why it fails | Needed on a5xx? |
| --- | --- | --- |
| `air-frontend` (adds `src/compiler/air` subdir) | `src/compiler/meson.build` context moved | yes, trivial |
| `air-ir3` (libbgair / air_metal build targets) | `ir3/ir3_cmdline.c` no longer at that path; freedreno `meson.build` changed | yes, redo by hand |
| `ir3-round-default`, `ir3-shift-split`, `ir3-ssbo-subdword` | ir3 sources changed | probably yes (ir3 is shared a5xx/a6xx); check each against 26.2.5 first, some may be fixed upstream |
| `fd-bo-cache-keep`, `fd-bo-cache-skip-busy`, `fd-bo-new-purge-retry` | `freedreno_bo{,_cache}.c` changed | maybe: workarounds for Bergamota's kernel memory limits; re-evaluate against SweetGPU |
| `fd6-fb-barrier-reorder` | a6xx file | no (a6xx only) |

## 3. a6xx assumptions in `air_metal.c` (a5xx differs)

From Mesa 26.2.5 `freedreno_screen.c`:

- **Framebuffer fetch**: `caps->fbfetch` is a6xx-only, so 0 on a5xx. Chlorophyll uses it for CoreAnimation's SDF shaders
  (`air_metal.c:7570-7590`). Needs an emulation: copy the attachment and bind it as a texture.
- **Sample shading**: a6xx-only.
- **Images/SSBOs**: a6xx uses bindless (`IR3_BINDLESS_*_COUNT`); a5xx shares 24 slots between images and buffers.
  `shader_buffer_offset_alignment` is 4 on a5xx (64 on a6xx); no `linear_image_pitch_alignment` set on a5xx.
- Comments and refusals name a6xx limits: vertex formats via `fd6_vertex_format` (`:5316-5546`), MSAA 1/2/4
  (`:1580`), Z formats (`:1495`), compute threads via `fd6_get_compute_state_info` (`:612-633`, `:3474`), UBO alignment
  64 (`:111`, `:4082`). Most query the screen, so they adapt, but every message and hardcoded number needs checking.
- `src/bgmtl.m:514`: pitch aligned to 64 "freedreno a6xx pitch alignment"; `registryID` 0x10000b630.

Compute (`has_compute`), formatted image load/store and draw-indirect are available on a5xx.

## 4. iOS 18 vs iOS 16 (likely the bigger job)

jasmine runs iOS 16.7.x; Chlorophyll targets iOS 18 22H352.

- `src/bgmtl.m` subclasses private `_MTLDevice`/`_MTLResource`/... and adds `MTLDeviceSPI`. Ivars/selectors were read
  from the iOS 18 shared cache; iOS 16's Metal.framework must be checked class by class.
- `plugin/chlorophyll_plugin.m` hooks `MTLIOAccelServiceGlobalContext -init` (iOS 18), and `inject/` uses
  `MTLAddDevice` and Renegade's `bgmtl` launch flags (Bergamota tooling). Both need iOS 16 equivalents and our own launch path (sweetenv).
- AIR bitcode / metallib versions in iOS 16's QuartzCore are older; `air/air_bitcode.c` and `air_metallib.c` must
  accept them. Their `results/` corpus is iOS 18 only.

## 5. One process, two Mesas (unverified guess)

backboardd already loads libsweetca. If libbgair links its own copy of Mesa it opens a second SweetGPU device in the same
process. Plan: build libbgair from the same 26.2.5 tree as libsweetca.
