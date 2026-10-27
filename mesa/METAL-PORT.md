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

## 4. iOS 18 vs iOS 16: checked 2026-10-28, mostly compatible

jasmine runs iOS 16.7 (cache header "OS Version 16.7", WSL `~/ios-work/gl/dsc`); Chlorophyll targets iOS 18 22H352.
Checked offline with ipsw 3.1.739 (`class-dump`, `dyld symaddr`, `dyld macho --strings`, `dyld disass --quiet`; full
symbolicated disassembly runs WSL out of memory) plus a small ADRP/ADD scanner over `ipsw dyld extract ... Metal`.
Scratch outputs (not in git): session scratchpad `m16/`.

**Private classes and selectors `src/bgmtl.m` uses: all present in iOS 16.7 Metal**, same superclasses:
`_MTLDevice : NSObject`, `_MTLObjectWithLabel : NSObject`, `_MTLResource`, `_MTLCommandQueue`, `_MTLCommandBuffer`,
`_MTLCommandEncoder`, `_MTLLibrary` (`: _MTLObjectWithLabel`), `_MTLComputePipelineState`, `_MTLRenderPipelineState`,
`_MTLSamplerState`, `_MTLDepthStencilState` (`: NSObject`). The super initialisers it calls exist on those exact classes:
`-[_MTLCommandQueue initWithDevice:descriptor:]`, `-[_MTLCommandBuffer initWithQueue:retainedReferences:synchronousDebugMode:]`,
`-[_MTLCommandEncoder initWithCommandBuffer:]`, `-[_MTLComputePipelineState/_MTLRenderPipelineState initWithDevice:pipelineStateDescriptor:]`,
`-[_MTLSamplerState initWithDevice:samplerDescriptor:]`, `-[_MTLDepthStencilState initWithDevice:depthStencilDescriptor:]`,
`-[_MTLDevice initWithAcceleratorPort:]`, `-[_MTLDevice targetDeviceInfo]`. Protocols `MTLDevice`, `MTLDeviceSPI` exist.
`bitcodeData`, `newBinaryArchiveWithDescriptor:error:`, `supportsFamily:`, `supportsFeatureSet:`, `featureProfile` appear
in the dump. (bgmtl.m's own comment: its registration methods came from hackios measurements on iOS 16.5.)
Not checked: ivar layouts (irrelevant to subclasses under the non-fragile ABI) and every SPI method QuartzCore 16 calls
(unknown ones reach bgmtl's zero-answer forwarding and get logged).

**Device registration (`inject/`)**: `MTLAddDevice` is exported (0x181a1b368). It checks `conformsToProtocol:` MTLDevice
and MTLDeviceSPI, then sends `initLimits`, `initFeatureQueries`, `allowLibrariesFromOtherPlatforms` to the device.
**`MTLCopyAllDevices` is NOT exported on iOS 16.7** (the inject dlsyms it to build `_deviceArray` before MTLAddDevice and
stays stock when it is missing). `MTLCreateSystemDefaultDevice` does the same `dispatch_once(MTLDeviceArrayInitialize)`,
so call that instead (it returns nil with no device). Change in `inject/bgmtl_inject.m:341`, `:389`.

**Plugin route (`plugin/`)**: iOS 16.7 has no `MTLIOAccelServiceGlobalContext` and no
`processPendingCreateIOAccelServiceRequests`, but the same mechanism runs synchronously in `MTLRegisterDevices`
(0x181b144c8, called from the MTLDeviceArrayInitialize block): `IOServiceGetMatchingServices(IOServiceMatching("IOAcceleratorES"))`,
for each service `getMetalPluginClassForService` (0x181a3c7c8): registry property `MetalPluginName` ->
`[NSBundle bundleWithPath:@"/System/Library/Extensions/<name>.bundle"]` -> `classNamed:` registry `MetalPluginClassName`,
else `principalClass` -> must be `isSubclassOfClass:_MTLDevice` (class ref resolved to `_OBJC_CLASS_$__MTLDevice`) ->
`[[cls alloc] initWithAcceleratorPort:service]` -> `MTLAddDevice`. So `chlorophyll_plugin.m` works as is apart from the
comments. Kernel side: our patch `xnu/patches/0138-topaz-empty-ioacceleratores.patch` already publishes an empty
`IOAcceleratorES` (`sweetaccel=0` disables it); adding `MetalPluginName`/`MetalPluginClassName` behind a boot-arg is the
equivalent of Bergamota's xnu 0232.

**Launch gating**: inject uses Renegade's `bgmtl` flag and `/private/var/tmp/bgmtl-bb.*` files (Bergamota tooling); we
use sweetenv / boot-args. Rewire only, no Metal dependency.

**AIR / metallib versions**: not checked against real files (the iOS 16 root image is on the other machine,
`/run/media/dipa/android/ios-sweet-ipsw/`). `air/air_metallib.c` reads the MTLB major/minor version but refuses nothing
on it; `air_bitcode.c` only checks the bitcode magic. Next: pull QuartzCore's and a few system metallibs off the phone (or
the root image) and run `air2nir` on them on the host.

## 5. One process, two Mesas (unverified guess)

backboardd already loads libsweetca. If libbgair links its own copy of Mesa it opens a second SweetGPU device in the same
process. Plan: build libbgair from the same 26.2.5 tree as libsweetca.
