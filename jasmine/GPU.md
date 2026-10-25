# GPU acceleration plan (Adreno 512)

**2026-10-25 first framebench device results:** [evidence and priorities](PERF-FRAMEBENCH-20261025.md).
One instrumented boot, successful standard + bounded Settings captures, no drops.
Prioritize task 20's Wallpaper instability/memory diagnosis before speed work;
crash/restart and rapid backing growth observed, exhaustion/leak unproven. Task 5
remains the measured sustained-rendering lead; substantial trustd/accessoryupdater
CPU also deserves investigation. Home A unverified; physical counters absent on
jasmine, so no confirmed displayed FPS. Host reporting corrected; 28 tests pass.
Phone parked in verified r109 charging shell; lock released. Details in NOTES.

**2026-10-25 framebench tooling:** see [FRAMEBENCH.md](FRAMEBENCH.md) and the active
[NOTES.md](NOTES.md) handoff. j0099 adds bounded frame/GPU/CPU-stack/memory capture
and binary export; host runner reports a new plugin-enabled baseline without
assuming task 5 remains first. Twenty-four offline tests and an eight-thread
interning test pass; actual device validation awaits the user's phone-free
confirmation. CI `40160211557` and final sizing/concurrency CI `40160680219` passed.
`shim/out/shim-boot-framebench99.img` packaged and verified against the local j98
shim/ADT/args. Ready for first device validation; no phone has been accessed.
Earlier CI `40158474717` silently skipped j0099 and is not compile validation;
workflow now requires capture source and linked symbols. No device access or FPS
result yet; display observations remain labelled as proxies pending validation.

Status: planning, 2026-10-21. Today CoreAnimation renders everything on the CPU (its software renderer),
which is the main reason the UI is slow even after the Gold cores went from ~180 MHz to 1747 MHz.

## The constraint that picks the route

Two projects have iOS drawing on an Adreno GPU, by different routes:

| | UniXNU (public, Adreno 740, a7xx) | topaz / HackiOS (private, Adreno 610, a6xx) |
| --- | --- | --- |
| iOS side | own **Metal** plugin (`NativeMetal`) → metal2vulkan → Mesa **Turnip** (Vulkan) | CoreAnimation's **OpenGL ES** renderer → Mesa **freedreno** (Gallium GL) |
| Kernel side | `NativeAdreno`: GMU, CP ring, 4K SMMU, BOs, fences, user client | own driver, not published |
| Code | public: UniXNU/NativeAdreno, NativeMetal, AdrenoFirmware, AdrenoPM4, AirNir | "published once HackiOS publishes" (topaz README) |
| Fits Adreno 512? | **No.** Turnip supports a6xx/a7xx only; Mesa has no Vulkan driver for a5xx | **Yes.** freedreno's Gallium GL driver supports a5xx, the 512 included |

So jasmine takes the **GL route**: iOS 16's QuartzCore still has a GLES renderer next to the Metal and
software ones (sweet's notes: `sw_new_context`, `gles_new_context`, `metal_new_context`), and Mesa freedreno can
drive the Adreno 512. UniXNU's published GPU code is still the best template for the structure (user client,
buffer objects, GPU address space, submission ring, fences, IOSurface interplay), even though its GPU
generation and API differ.

## Stages

Each stage is useful on its own.

### G0: research (no hardware risk)

1. **What CoreAnimation's GL path needs on this root.** Which framework and driver plugin the GLES renderer
   loads (OpenGLES.framework, a GL driver bundle, IOAccelerator services), when QuartzCore picks it over the
   software renderer (environment, device capabilities, MobileGestalt), and what it asks of the kernel. This is
   the biggest unknown of the whole plan.
2. **The kernel side for the Adreno 512**, from Linux `drivers/gpu/drm/msm/adreno/a5xx_gpu.c` and the SDM660
   device tree: GPU clock controller and GDSC, RPM votes for the GPU rail and clock, microcode
   (`a530_pm4.fw`, `a530_pfp.fw`), the TrustZone zap shader (`a512_zap`, SCM call), the GPU SMMU, ring and
   fences. The firmware files are on the phone (stock `vendor` partition).
3. **Watch topaz** (`git fetch topaz`) for the HackiOS patches.

#### G0.1 findings (2026-10-21, from the iOS 16.7.16 root and its dyld shared cache)

- **OpenGL ES on iOS 16 is layered on Metal through a renderer plugin:**
  `OpenGLES.framework` → `GLEngine.bundle/GLEngine` (the GL front end) →
  `/System/Library/Extensions/AppleMetalGLRenderer.bundle/AppleMetalGLRenderer` (GL renderer that translates
  to Metal) → `AGXMetalA11.bundle` (Apple GPU driver). The bundles on disk hold only data (`default.metallib`);
  the code is in the dyld shared cache.
- **The renderer slot is a classic Apple GL driver plugin:** GLEngine looks bundles up as
  `/System/Library/Extensions/%s.bundle` (string next to `gldCreateContext`) and calls them through the
  `gld*` interface: **133 functions**, listed in [gld-symbols-ios16.txt](gld-symbols-ios16.txt)
  (`gldCreateContext`, `gldAttachDrawable`, `gldCreateBuffer`, `gldBufferSubData`, `gldClearFence`, ...).
  `libCVMSPluginSupport.dylib` (CVMS) is the shader/JIT support the plugins use.
- **CoreAnimation:** QuartzCore has `gles_new_context(void*, void*, unsigned)` next to the software and Metal
  contexts, and reads `CA_ENABLE_OGL` and `CA_DISPLAY_TYPE` (environment), which presumably select the GL
  renderer. `IOAcceleratorES` is the accelerator service class QuartzCore looks for (topaz publishes an empty
  one to skip a 30 s wait).
- **How OpenGLES picks the renderer (found with blacktop `ipsw` 3.1.739 in WSL `~/ios-work/tools`):** OpenGLES
  matches the IOKit service class `IOAcceleratorES` (or `IOAcceleratorESLegacy`) and reads three properties:
  `IOGLESBundleName` (a native GL renderer bundle), `IOGLESMetalBundleName` (the Metal-based one, normally
  `AppleMetalGLRenderer`) and `IOGLESDefaultUseMetal` (which of the two), then loads
  `/System/Library/Extensions/%s.bundle` and, through `loadGLIPlugin:sharedWithCompute:`, its `gld*` entry points.
  **So the kernel chooses the GL renderer:** our `IOAcceleratorES` (topaz already publishes an empty one) with
  `IOGLESBundleName = JasmineGLRenderer`, `IOGLESDefaultUseMetal = false` makes OpenGLES load
  `/System/Library/Extensions/JasmineGLRenderer.bundle/JasmineGLRenderer`. No binary patching of iOS.
  `AppleMetalGLRenderer` exports 131 of the 133 `gld*` names (symbols and strings dumped to `~/ios-work/gl/out`).
- **CoreAnimation side (first look):** QuartzCore has three context constructors, `sw_new_context` (0x1884409d0),
  `gles_new_context` (0x188440b4c) and `metal_new_context` (0x188440b98), reached only through a function-pointer
  table (no direct calls), plus `ogl-renderer.cpp` and `rendererWithEAGLContext:options:`. `CA_ENABLE_OGL` is read
  in what looks like the GL context setup (sub_1883da11c) and **defaults to on** (unset counts as 1). Still open:
  where the table entry is chosen (Metal device present? IOAcceleratorES? `CA_DISPLAY_TYPE`?). QuartzCore
  disassembly: `~/ios-work/gl/out/qc.s` (`ipsw dyld disass --image QuartzCore`; `ipsw dyld xref` ran out of memory).
- **So the G2 target is concrete:** a renderer bundle that exports the `gld*` interface backed by Mesa freedreno
  (instead of Metal), and CoreAnimation switched to its GLES renderer (`CA_ENABLE_OGL` for backboardd).
  Next research steps: the `gld*` signatures (disassembly of AppleMetalGLRenderer and GLEngine's calls, with
  blacktop `ipsw dyld` as sweet used it), how GLEngine picks the renderer bundle (renderer ID / plist), and what
  `gles_new_context` needs from IOSurface and the display.

### G1: the GPU in the kernel (1-2 weeks)

#### G1 findings (2026-10-21)

- **Firmware** is on the stock `vendor` partition (backup `p67_vendor_a.img`, `/firmware`): `a530_pm4.fw`
  (19652 bytes), `a530_pfp.fw` (16820), `a512_zap.mdt` + `.b00`-`.b02` and the same as one ELF,
  `a512_zap.elf` (17204; QDSP6 ELF32, one PT_LOAD at 0x5000, 0x1334 bytes). Kept out of git in
  `research/gpu-fw`; `tools/mkadt.py` puts them into `/sweet-gpu` (`pm4`, `pfp`, `zap`).
- **The GPU rail is VDD_CX through a head switch.** The stock DT feeds the GPU CPR controller from a stub
  regulator; the real path is the GFX LDO block at 0x506e000 (`qcom,sdm660-gfx-ldo`, downstream
  `msm_gfx_ldo.c`) in BHS mode (LDO mode is never allowed: `qcom,cpr-corner-allow-ldo-mode` all 0), and
  the GPU's voltage is the CX corner voted through RPM (`qcom,system-voltage` 0x40..0x180 = LOW_SVS..TURBO).
  The GX GDSC's parent supply is that regulator. Mainline has no driver for the head switch (its sdm660
  OPP table says "lacking support for the GPU regulator").
- **Mainline Linux cannot start this GPU:** with the firmware pushed into the charging shell's initramfs
  (`tools/pmos-push.py`), opening `/dev/dri/renderD128` loaded the microcode and then hard-locked a CPU on
  the first GPU register access; the shell died a few seconds later (2026-10-21 about 06:37). So there is
  no Linux reference run; our driver follows the downstream sequence instead.
- **Power-up sequence (j0018):** GCC `gpu_cfg_ahb` 0x71004, `gpu_bimc_gfx` 0x71010, `bimc_gfx` 0x7106c on;
  LDO: clear clamp (bit 31), CPR auto-bypass (bit 29), the `sdm660_ldo_config` values, then
  `enable_bhs_mode` (SW control, power source BHS, BHS enables low, BHS under GDSC control); GPU CX GDSC
  (0x5066004, status in 0x5066008); RBBM timer, RBCPR and gfx3d RCGs from XO (19.2 MHz: no PLL, no vote);
  GX GDSC (0x5066094) with BCR reset (0x5066090), AON reset and unclamp (0x5065130 bits 4 and 0); then the
  gfx3d branch (0x5066098). GPU registers are touched only once GX reports PWR_ON.
- **The GPU SMMU** (SMMU-v2 at 0x5040000, 3 stream groups, 5 context banks) comes out of the GX power-up
  faulting every stream (sCR0 `00200626`: USFCFG set; all S2CRs type fault). Context banks 2-4 belong to TZ:
  reading CB2 hung a core and the boot (Linux hides them too: arm-smmu-qcom.c "TZ protects several last
  context banks"). The hypervisor traps the global register space: it silently ignores a bypass request
  (clearing sCR0.USFCFG), and a store from WZR (any `= 0` in C) hangs it; Linux works around the same bug with
  `QCOM_DUMMY_VAL`. j0018 writes the SMMU through an asm helper with a real register only.
- **MILESTONE 2026-10-21 13:40: the GPU executes our commands** (j0018, `sweetgpu=2`,
  [logs/boot-j18-gpu2c.txt](../logs/boot-j18-gpu2c.txt)). CB0 gets a stage 1 table (AArch64 4K, 36-bit VA,
  2 MiB identity blocks) for stream 0; microcode from `/sweet-gpu`; CP on a 32 KiB ring at 0x9f000000:
  `CP_ME_INIT` done in 100 us, `CP_MEM_WRITE` to 0x9f018000 (below 4 GiB) and to a kernel page at
  0x1_04508000 (above 4 GiB) both landed, with the GPU clocked from XO (19.2 MHz) and still in secure mode.
- **2026-10-21 14:07: zap shader loaded, CP out of secure mode** (j0019, `sweetgpu=3`,
  [logs/boot-j19-gpu3b.txt](../logs/boot-j19-gpu3b.txt)): PAS 13 `init_image` (metadata in the GPU window)
  ret 0, `mem_setup 0xfed00000 + 0x2000` ret 0, `auth_and_reset` ret 0, `CP_SET_SECURE_MODE 0` executed
  (549 us), and a `CP_MEM_WRITE` after it landed. `mem_setup` with the exact image size 0x1334 (what mainline's
  `qcom_mdt_load` passes) fails with ret `0xffffffe0`: the size must be 4 KiB aligned, as downstream
  `pil_setup_region` does ("iommus and XPUs that operate on 4K chunks").
- **2026-10-21 14:25: GPU clock from GPU PLL0** (j0020, `gpumhz=160|266`): measured 159 and 266 MHz with the
  CP cycle counter (CP_ALWAYS_COUNT against the 19.2 MHz always-on counter), whole CP/zap sequence OK at both
  ([logs/boot-j20-c160.txt](../logs/boot-j20-c160.txt), [logs/boot-j20-c266.txt](../logs/boot-j20-c266.txt)).
  Higher levels (370..750 MHz) need a CX corner vote through RPM first.
- **Zap shader (how):** PAS id 13 through SCM (SMCCC SIP calls, `0x42000000 | svc << 8 | cmd`, x1 =
  arginfo): `INIT_IMAGE` (2/1, metadata = ELF header + program headers + hash segment), `MEM_SETUP` (2/2,
  the reserved region `gpu@fed00000`, 10 MiB, outside XNU's RAM), copy the PT_LOAD segment,
  `AUTH_AND_RESET` (2/5); afterwards `CP_SET_SECURE_MODE 0` on the ring.

- An **RPM client** (SMD) for the votes the GPU needs (GPU rail, GPU and bus clocks). The same client can raise
  the RAM and bus clocks, so it pays twice (see the memory bandwidth measurement in NOTES.md).
- Power up the GPU, load the microcode, start the command processor and run a ring:
  **"the GPU executes our commands"** (a memory write, then a fill or a copy), with fences.
- First real use: let the GPU do the per-frame **scale and copy into the flip buffer** that the CPU does today
  (AppleCLCD::composeFit). Small but tangible, and it proves DMA, IOMMU and fences.

### G2: CoreAnimation on the GPU (weeks to months)

#### G2 design (2026-10-21)

Mesa's freedreno talks to the kernel through a backend in `src/freedreno/drm/` (`msm/` for Linux DRM, `virtio/`).
The kernel interface was kept smaller than msm's (no BO list, relocations or submit queues: every buffer stays mapped
in the one GPU address space), so instead of emulating the DRM ioctls Mesa gets its own backend:

- **Kernel (j0026, `sweetgpu=4`):** `SweetGPU` (IOService, published once the GPU is up and a kernel self-test of
  the whole path passed) and `SweetGPUUserClient`: get-param, buffer new/free (IOBufferMemoryDescriptor,
  write-combined, mapped into the client by `clientMemoryForType` with the handle as type), submit (indirect buffers
  by GPU VA) and wait/completed fences. Behind it: j0018-j0020's bring-up as the driver's init; client buffers get
  GPU VAs from 32 GiB up in SMMU context bank 0 with 4K page tables (tables in kernel memory, cleaned for the
  non-coherent walk); submit = `CP_INDIRECT_BUFFER_PFE` per command buffer, then `CP_EVENT_WRITE CACHE_FLUSH_TS`
  of a seqno into a fence word (polled; interrupts later). Self-test: an IB in one non-contiguous kernel buffer
  writes into another with `CP_MEM_WRITE`.
- **Userland (`mesa/`, CI `build=mesa`):** Mesa 26.2.5 + `mesa/patches/0001`: `src/freedreno/drm/darwin/` (the
  SweetGPU backend; IOKit declarations of its own, the iPhoneOS SDK has the library but no headers;
  `fd_device_new` takes it on Apple platforms and ignores the fd) and `sweetgpu_fdtest`, cross-built with
  `mesa/ios-arm64.ini` (freedreno only, no GL/EGL/Vulkan/LLVM; libdrm from Mesa's subproject for the headers).
  First milestone: `sweetgpu_fdtest` clears a 64x64 RGBA8 render target on the GPU (GMEM, then resolve), waits on
  the fence and reads it back. Then a triangle (ir3 shaders), then GL ES.
- **Status 2026-10-21 16:56:** kernel j0026 built (test image `shim/out/shim-boot-j26-gpu4.img`: `sweetgpu=4
  gpumhz=266 sweetwdt=20`, not yet booted); Mesa freedreno for iOS builds (CI run 39620797449, artifact
  `mesa-ios`: `sweetgpu_fdtest`, 12.9 MB arm64, ad-hoc signed). What it took on Darwin: the drm layer's subdir
  condition, a libdrm stand-in header (`include/darwin-drm/xf86drm.h`), counting Darwin freedreno as graphics
  (`with_gfx_compute`, else NIR is headers-only and gallium lacks its shader helpers), and `renderonly.c` linked
  into the test.
- **MILESTONE 2026-10-21 20:35: Mesa freedreno drives the Adreno 512 on iOS.** `sweetgpu_fdtest` (kernel
  j0031, `sweetgpu=4 gpumhz=266 sweetgpu_debug=1`) printed `screen: FD512 (freedreno)`, cleared the 64x64
  RGBA8 render target in one submit (a 490-dword IB, fence seqno 2) and read back 0 of 4096 wrong pixels:
  `PASS: the GPU cleared the render target` (`logs/netlog-j30-fdtest.txt`; the 3.2 s are the debug mode's
  150 ms pause per log line and its 1 s hang check, not the GPU). What it took after j0026:
  - **Write-combined buffers panicked the kernel** in their first creation: a write-combined
    IOBufferMemoryDescriptor makes XNU change the cache attributes of its pages in every mapping, the physical
    aperture included, and it hit `phystokv_range: illegal PA: 0x7c994000; phys base 0x100000000` (a page
    below the kernel's managed RAM; caught by j0030). Buffers are now cacheable, and the kernel cleans and
    invalidates the client's buffers around each submit, wait and completion query (j0031; `sweetgpu_wc=1`
    brings the old path back). Costly for big buffers; write-combined user mappings of pages the kernel keeps
    cacheable, or buffers from memory XNU does not manage, are the later fix.
  - fdtest must call `glsl_type_singleton_init_or_ref()` (a GL frontend's job; ir3 builds GLSL types).
- **2026-10-21 20:49: first triangle.** fdtest's second stage clears the target again and draws one triangle
  with red, green and blue corners (gallium's TGSI pass-through shaders, so tgsi_to_nir + ir3 compile them):
  0 of 4032 checked pixels off by more than 3 from the interpolated color or the clear color (the 64 pixels on
  the hypotenuse are skipped), e.g. (16,16) = 7c 42 42 ff as computed. `PASS: the GPU drew the triangle`
  (`logs/netlog-j31-tri.txt`, same j0031 kernel). ir3 code, vertex fetch, viewport, rasterizer and varyings
  work on the first try. Next: a GL ES context (Mesa's GLES frontend on Darwin) and a GLSL test.
- **2026-10-21 21:09: OpenGL ES works on the Adreno 512.** `sweetgl` (Mesa patch, `src/gallium/frontends/sweetgl`,
  modelled on Haiku's hgl: a display owns the freedreno screen, st/mesa GL ES contexts, offscreen surfaces with
  depth/stencil, the public GL ES entry points compiled in; no EGL/DRI) reports `OpenGL ES 3.1 Mesa 26.2.5`,
  renderer `FD512`, GLSL ES 3.10, 129 extensions. `sweetgpu_gltest` passed all four steps with plain GL ES 2.0
  calls and glReadPixels: clear, a GLSL triangle with varyings and a uniform, a 2x2 texture (nearest, client-side
  vertex arrays) blended at alpha 0.5, and the depth test (`logs/netlog-j31-gl.txt`, kernel j0031). 9.6 s for the
  four steps: mostly the debug mode's log pauses plus first-time shader compiles. Mesa for iOS now builds with
  `-Dgles2=enabled`; a Linux host build in WSL (`~/ios-work/mesa/build-host`) compile-checks changes first.
  Next: the EAGL side (OpenGLES.framework's EAGLContext / renderbufferStorage:fromDrawable: on IOSurfaces),
  then CoreAnimation's renderer.
- **2026-10-21 21:33: the GPU renders into IOSurfaces and samples them, with no copies.** Kernel j0032: SweetGPU
  selector 6 maps an IOSurface's own memory (SweetSurface's kernel buffer, wrapped client memory or the panel
  window) into the GPU address space as a buffer of the client (one handle per surface and client, the buffer holds
  the surface; cacheable kinds are cleaned/invalidated around GPU work like the others), selector 7 returns a
  buffer's GPU VA and size. Mesa: the darwin backend's `bo_from_dmabuf` takes an IOSurface id (a
  `WINSYS_HANDLE_TYPE_FD` handle on Darwin), so gallium's `resource_from_handle` imports surfaces; sweetgl gained
  `sgl_surface_create_iosurface` (render target) and `sgl_tex_image_iosurface` (texture, via
  `st_context_teximage`, what EAGL's `texImageIOSurface:` needs). `sweetgpu_gltest` steps 5-6 passed first try:
  the triangle rendered into a junk-filled 64x64 BGRA IOSurface reads back right through GL and in the surface's
  memory through IOSurface.framework (top row first, as CA and the display want), and a CPU-painted BGRA
  IOSurface samples right as a texture (`logs/netlog-j32-iosurface.txt`).
  Known limits for CoreAnimation: freedreno on a5xx needs bytes per row in multiples of 256 (SweetSurface aligns
  rows to 64, so a 1125-wide BGRA surface gets 4544 and would be refused; raise `SWEET_SURFACE_ROW_ALIGN` to 256,
  scanout takes any pitch); wrapped client memory that starts inside its first page is refused for now; GPU VAs
  are never reused (bump allocator, 28 GiB), fine for tests but not for a long-running renderer; no implicit sync
  between processes. Next: the EAGL side (how CA reaches GL: OpenGLES.framework in the shared cache vs the
  `IOAcceleratorES`/`gld*` renderer bundle of G0.1), then backboardd.
- **Panics are visible now (j0030):** this board has no iBoot panic region, so `SavePanicInfo()` spins forever
  and a panic looked like a hang (ios-sapphire found the same). The panic text now goes out on the live log
  connection; `sweetpanic_test=SECS` checks it (passed 2026-10-21 20:32, `logs/netlog-j30-ptest.txt`).
- **Running our programs on the phone:** `tools/sweet-sh.py` through the user's sweetd (TCP 5143);
  `sweet-fs.py` puts binaries on the root.
- **CoreAnimation:** decided by the step A research below (2026-10-21 ~22:00): EAGL on sweetgl (route 2), not the
  `gld*` renderer plugin (G0.1). Route choice still to be confirmed by the user before anything touches the root.

#### G2 step A: how CoreAnimation reaches GL (2026-10-21 ~22:00, research only)

From the iOS 16.7.16 shared cache. blacktop `ipsw` runs out of memory on whole-cache commands, so the analysis
uses small readers in [tools/g2/dsc](../tools/g2/dsc/README.md) (dumps stay in WSL `~/ios-work/gl/out2`).

**How backboardd picks its renderer.** `CA::WindowServer::AppleDisplay::new_server` always builds an
`EAGLServer` (an `IOMFBServer` subclass) for the panel. Its constructor reads `CA_ENABLE_OGL` once (unset counts as
1) and calls `EAGLServer::renderer()`, which:

1. tries Metal: `CAMetalContextCreate()` first waits up to 300 x 100 ms for an `IOAcceleratorES` service (topaz
   0138's empty one ends the wait), then needs a Metal device; non-NULL gives `new_metal_context` + `OGL::Renderer`;
2. only if that is NULL and `CA_ENABLE_OGL` is on: `[[EAGLContext alloc] initWithAPI:3 properties:dict]`, on nil
   `initWithAPI:2`, then `setParameter:0x260 to:&0`, and **only if `[ctx API] == 3`** `new GLESContext(ctx)` +
   `OGL::Renderer`. An ES 2 context is not used;
3. otherwise no renderer: the CPU path we run today.

So backboardd switches by itself once `initWithAPI:3` returns a working context (there is no Metal device here).
`CA_DISPLAY_TYPE` plays no part in this choice.

**What GLESContext asks of EAGL** (every EAGL selector QuartzCore references): `+alloc`,
`-initWithAPI:properties:`, `-setParameter:to:`, `-API`, `-getMacroContextPrivate`,
`-attachImage:toCoreSurface:invertedRender:` (`make_buffer_current`: a display IOSurface onto the bound
`GL_TEXTURE_2D`, then an FBO on that texture; `attach_surface_texture`) and
`-texImageIOSurface:target:internalFormat:width:height:format:type:plane:invert:` (`create_surface_from_iosurface`,
`attach_surface_texture`). `+setCurrentContext:` / `+currentContext` only in `-[CARenderer render]` and
`CATextLayer`. No `renderbufferStorage:fromDrawable:` or `presentRenderbuffer:` on the server path: CA renders into
the IOMFB swap surfaces as textures and swaps them through IOMobileFramebuffer exactly as now.

**QuartzCore never calls the exported `gl*` functions** (it has no stub into OpenGLES at all), so interposing `gl*`
symbols would catch nothing. `getMacroContextPrivate` returns `{__GLIContextRec *ctx; __GLIFunctionDispatchRec
disp}` (1036 entries; OpenGLES's own `glFoo` exports reach the same struct through `tpidrro_el0[0xf0]`), kept at
`GLESContext+0x7f8`, and every call is `disp[n](ctx, args...)`. QuartzCore uses **60 entries**, listed with their
callers in [ca-gles-calls-ios16.txt](ca-gles-calls-ios16.txt): plain GL ES 2.0/3.0 (textures incl. compressed,
FBOs, shaders from GLSL source, uniforms, vertex attributes, draw arrays/elements, blend, scissor, viewport, fence
sync) plus Apple bits that map directly: `glFenceSyncAPPLE`/`ClientWaitSync`/`DeleteSync`, `glFinishObjectAPPLE`,
`glFramebufferParameteriAPPLE`, `glLabelObjectEXT` and the debug markers. Extensions probed by the constructor
(each only enables a feature): `GL_APPLE_fence`, `_texture_filter_cubic`, `_texture_xr`,
`_texture_ycbcr_basic_formats`, `_texture_ycbcr_extended_formats`, `_tile_order_rot`,
`GL_EXT_shader_framebuffer_fetch`, `_texture_filter_anisotropic`, `_texture_lod_bias`,
`GL_IMG_texture_compression_pvrtc`, `GL_KHR_texture_compression_astc_ldr`, `GL_OES_standard_derivatives`,
`_texture_float(_linear)`, `_texture_half_float(_linear)`. Overrides read there: `CA_DISABLE_WORKAROUNDS`,
`CA_MAX_TEXTURE_UNITS`, `CA_MAX_TEXTURE_SIZE`.

**Route 1 (renderer plugin under GLEngine) is a full GLD driver, so it is out.** OpenGLES's `eagl_init` dlopens
`<OpenGLES.framework>/GLEngine.bundle/GLEngine` (fixed path, served from the shared cache), resolves 18 `gli*`
entry points and calls `gliInitializeLibrary` with the matched `IOAcceleratorES` service; libGFXShared loads the
`IOGLESBundleName` bundle. GLEngine (776 KB of code) keeps all GL state, compiles GLSL itself through
libGLProgrammability to LLVM IR (`GL_FORCE_LLVM_IR_OUTPUT`) and drives the plugin with private records
(`GLDContextRec`, `GLDTextureRec`, `GLDProgramRec`, ...). `gldPopulateContextDispatch` does not reach the GL
dispatch: AppleMetalGLRenderer's copies 25 primitive callbacks (`gldClear`, `gldRenderTriangles`,
`gldRenderVertexArray`, `gldBeginElementBuffer`, ...). A plugin would have to implement the 133 `gld*` functions
over undocumented structs and translate Apple's LLVM IR into NIR.

**Getting code into backboardd.** iOS 16 dyld (`SyscallDelegate::amfiFlags`) asks
`__mac_syscall("AMFI", 90, {input flags, &output})` and takes 0 when the call fails. Our kernel registers MAC
policies "SWEET AMFI" and "Sandbox" but none named "AMFI", so dyld prunes every `DYLD_*` variable today;
`DYLD_INSERT_LIBRARIES` needs the kernel to answer that call (dyld's output bits, from its open source: 0x1 @paths,
0x2 path variables incl. `DYLD_INSERT_LIBRARIES`, 0x8 fallback paths, 0x10 print variables, 0x20 failed insertion
allowed, 0x40 interposing).

**CARenderer is a ready test harness:** `+[CARenderer rendererWithEAGLContext:options:]` builds the same
`GLESContext` + `OGL::Renderer` as the server. A standalone program can render a CALayer tree with CA's real GLES
renderer into an IOSurface, with nothing changed on the root.

**Recommendation: route 2, EAGL on sweetgl.** A library (working name `libsweetca`) that, when loaded, replaces
the EAGLContext methods above with sweetgl-backed ones (ObjC runtime) and gives CA a GLI dispatch table of its
own: 1036 entries, the 60 used ones forwarding to Mesa's GL ES (the GLIContext argument selects the sweetgl
context), all others a trap that logs its index. Estimate: 1000-1500 lines of C/ObjC on top of sweetgl, plus
sweetgl additions (per-thread current context, GL ES 3.0 reported as the API, binding an IOSurface to an existing
texture name for `attachImage:`). Order:

1. Step C as a test program: libsweetca + CARenderer + a few CALayers rendered into an IOSurface, checked pixel by
   pixel, run through sweetd. No root changes.
2. Kernel (with step B in j0033): sweet_amfi answers the dyld policy call; checked with `DYLD_INSERT_LIBRARIES` on
   a test program through sweetd.
3. Step D, **needs the user's OK**: libsweetca on the root and `DYLD_INSERT_LIBRARIES` in backboardd's launchd
   plist. Removing the key brings back today's CPU renderer.

Fallback without the plist change: publish `IOGLESBundleName` = our bundle on `IOAcceleratorES`; GLEngine dlopens
it during CA's first `initWithAPI:3`, its initializer installs the EAGL replacement and fails that attempt, and
CA's `initWithAPI:2` retry gets our ES 3 context. Works with the code as read, but leans on that retry. topaz has
not published its CA side (`89451b8` still the head at 22:00).

#### G2 comparison with ios-sailfish (2026-10-21 ~23:00, research only)

[joranv1/ios-sailfish](https://github.com/joranv1/ios-sailfish) (Pixel 1, Snapdragon 821, **Adreno 530**, a5xx
like ours; also an ios-sweet fork; public since 2026-10-21 18:19, head `ce63752`) has **CoreAnimation on the GPU**:
lock screen, home screen, Control Center, notification center blur, Settings and the stock apps rendered by
freedreno at 600 MHz, 15-35 fps (backboardd's CPU work is now the limit). Their route is **our route 2**: EAGL
methods replaced in backboardd by a dylib, CA's own `OGL::Renderer` on Mesa GL ES. That confirms step A's choice;
nothing in their tree argues for the `gld*` plugin.

| | jasmine (ours) | sailfish |
| --- | --- | --- |
| iOS root | iPhone X (`D22AP`) 16.7.16 cache | iPhone 8 (`D20AP`) 16.7.16 cache: **different addresses** (their `create_shader` 0x1884af0d8 is mid-function in ours) |
| Kernel UAPI | SweetGPU sel 0-7, own shape | sel 10-16, msm-shaped (GEM new/close, submit with bo list, cpu-prep, fence page) |
| Mesa glue | `src/freedreno/drm/darwin/` backend in Mesa (patch 0001) | Mesa almost unpatched (48-line `mesa.patch`); `sweet_drm.c` (529 lines) emulates libdrm + msm ioctls in user space |
| GL frontend | `sweetgl` gallium frontend (Haiku hgl style) | `sweetgl.c` (315 lines, st/mesa contexts) |
| EAGL / CA | not started | `eagl.c` (2235 lines): 1036-slot GLI table generated from GLEngine's layout (`gen-dispatch.py`, `ios-dispatch.txt`), EAGL swizzles, IOSurface textures via `get_egl_image` |
| Injection | planned: answer dyld's AMFI call | done: MAC policy renamed `"AMFI"` + `mpo_policy_syscall` op 0x5a → 0x7b (0139); boot-arg `sweetenv=backboardd:DYLD_INSERT_LIBRARIES=/usr/lib/sweetgl.dylib` (0104, 0163): **no launchd plist change** |
| Present | CPU `composeFit` | GPU scales into two panel buffers the MDP flips (0164) |

**What their log says CA needs beyond the 60 GLI calls of step A** (each one cost them a boot; we inherit the
answers):

- **Mesa settings:** `FD_MESA_DEBUG=sysmem,nofp16`, `IR3_SHADER_DEBUG=nofp16`. GMEM tile restore/resolve overran
  unpadded IOSurfaces and faulted the GPU on the display surface; fp16 lowering of mediump broke CA's shaders.
- **GL ES 3.1 contexts**, not 3.0 (the rect emulation needs `glGetTexLevelParameteriv`).
- **`GL_TEXTURE_RECTANGLE` emulation:** rect targets become 2D, `sampler2DRect` shaders rewritten with a per-draw
  texel scale; separate 2D/rect bindings per unit.
- **`GL_EXT_shader_framebuffer_fetch` emulation** (CA drops blend-mode layers without it): shader rewrite to sample
  a copy of the framebuffer texture, plus a texture barrier before draws that sample their own target.
- **CA's format-0 32-bit images are A,R,G,B in memory:** RGBA binding with a swizzle.
- **One Mesa resource per IOSurface**, so render-then-sample through two GL textures stays ordered.
- **Three GL texture functions missing from QuartzCore's own GL renderer** (0x14 colour matrix without premultiply:
  lock screen clock; 0x2d vibrant colour matrix: CC/App Library plates; 0x26/0x27 variable blur: notification
  centre), patched into QuartzCore's `tex_fragment_shaders` table and `create_shader`'s uniform switch at load.
  Addresses are iPhone 8 cache; their code checks the table (`"colorMatrix4x4Bias(s0)"` at 0x13) and refuses on
  ours, so we find both tables in the iPhone X cache (`~/ios-work/gl/out/qc.s`).
- **Kernel IOSurface fixes:** explicit row bytes rounded to 64 only for backboardd, as asked for others (CoreUI
  glyphs striped otherwise); surfaces created over the caller's own pages (`IOSurfaceAddress`, read-only client
  memory allowed: icons were invisible). Our topaz patches 0134/0139 cover part of this; check against their
  0157-0162.
- **a5xx pitch:** their `mesa.patch` lets linear imports use 64-byte pitch alignment
  (`fd_layout_resource_for_handle`), so the "256-byte rows" limit noted under 21:33 is solved in Mesa instead of
  raising `SWEET_SURFACE_ROW_ALIGN`.
- **GPU robustness:** SMMU faults non-fatal and logged (0155); every GPU mapping padded with 128 KB mapped to a
  shared scratch page (0156: fetch overruns hung the A530 even with faults terminated).

**Decision: keep our kernel UAPI and Mesa backend, port their EAGL layer onto it.** Ours already passes the same
tests (IOSurface render and sample included); swapping in their msm emulation would mean rewriting SweetGPU's
user client for nothing. `eagl.c` touches the GPU side in few places (`sweet_drm_import_iosurface`, `sweetgl_*`
context calls, `sweetgl_screen`, the `get_egl_image` hook), which map onto our selector 6 import and sweetgl API.

**Licence:** neither ios-sailfish nor ios-sweet carries a licence file. Ask the author (Joran Vancoillie) before
copying `eagl.c` verbatim; credit them in any case.

**Next steps (replaces step A's order):**

1. **Kernel j0033** (no root changes): sweet_amfi named `"AMFI"` with the dyld policy call; `sweetenv` boot-arg
   (several `NAME:VARS` entries); SMMU faults non-fatal; scratch-page padding of GPU mappings; IOSurface row-bytes
   and client-address fixes as far as ours lack them. Check: `DYLD_INSERT_LIBRARIES` honoured on a test program
   through sweetd.
2. **libsweetca = our sweetgl + their EAGL layer:** dispatch table generated from our GLEngine dump (verify
   `ios-dispatch.txt`'s slot layout against the iPhone X cache), Mesa env settings above, the 64-byte pitch patch,
   texture-function fixes with iPhone X addresses. Check with the CARenderer harness (step C) through sweetd, CA
   layers into an IOSurface, pixel-checked.
3. **backboardd** (needs the user's OK: the dylib goes onto the root, e.g. `/usr/lib/sweetgl.dylib`): boot with
   `sweetenv=backboardd:DYLD_INSERT_LIBRARIES=...`. A boot without the boot-arg is today's CPU renderer, so the
   root's launchd plists stay untouched.
4. Later: GPU present into flip buffers (their 0164), GPU clock above 266 MHz (needs the CX corner vote).

#### j0033 result (2026-10-21 23:39): step 1 done

Kernel j0033 (`xnu/patches/j0033-jasmine-dyld-env-gpu-vm.patch`, XNU tree commit `a00bcfd`; CI kernel run
`39668634610`, built on its 4th attempt: GitHub had no macOS arm64 runner for three 15-minute queue windows, see
`tools/g2/ci-wait.sh`; ios-tools run `39668826543`). Booted with `fastboot boot` as `shim/out/shim-boot-j33-gpu.img`
(the j0032 boot-args plus `sweetenv=sweet_envtest:SWEET_ENVTEST=1,DYLD_INSERT_LIBRARIES=/usr/local/bin/sweet_inject.dylib`).
Logs: `logs/netlog-j33-gpu.txt` (kernel), `logs/netlog-j33-tests.txt` (test output).

- **Boot unchanged** with the MAC policy renamed to `"AMFI"`: lock screen and SpringBoard come up as before.
- **`sweet_envtest`: PASS.** The kernel logs `SWEET ENV: sweet_envtest += ...` for both variables; dyld's policy call
  returns 0 with flags 0x7b; the inserted `sweet_inject.dylib`'s constructor runs and its symbol resolves.
  `/usr/local/bin` only; nothing else on the root changed.
- **GPU regression: `sweetgpu_fdtest` and `sweetgpu_gltest` PASS** (all steps incl. IOSurface target and texture).
  Buffers are now 0x24000 apart (16 KiB + the 128 KiB scratch pad), and freed VAs come back: within fdtest buffer 1
  is freed and remade at the same VA 0x800048000, and gltest, a later process, gets 0x800048000 again.
- **No SMMU fault** was recorded (`smmu_fault_note` printed nothing), so the non-fatal fault path is in place but not
  yet exercised.

**IOSurface part of step 1: no change needed.** Our topaz-derived SweetSurface already makes `IOSurfaceAddress`
surfaces over the creator's pages, with a read-only fallback (`sweet_surface_use_task_memory`), maps them cacheable,
and implements the wrap selectors (sailfish had to refuse them). Explicit row bytes are taken as asked. sailfish's
row-bytes rule (round explicit rows to 64 only when the request has more than 6 keys) is a heuristic; decide in step
2 from what CA actually asks for on our root, with Mesa's 64-byte pitch patch first.

**Next: step 2** (libsweetca: our sweetgl + an EAGL layer, checked through CARenderer). Licence question on
sailfish's `eagl.c` still open.

- Mesa freedreno (Gallium, a5xx) built for iOS (cross-compiled on GitHub's macOS runners, as XNU is) with a
  small kernel interface to the G1 driver (like UniXNU's `turnip-darwin-kmd`, but for freedreno's DRM-style
  winsys).
- Connect it to QuartzCore's GLES renderer in backboardd (CARenderServer): whatever G0.1 finds, a driver plugin
  OpenGLES loads, or an interposed context in the render server.
- If HackiOS publishes in the meantime, its CoreAnimation side is probably largely GPU-independent and reusable;
  G2 then shrinks to "freedreno on a5xx instead of a6xx". G1 is needed in every case.

## Risks

- G0.1 may show that the GLES path needs pieces that are hard to provide (private driver plugin interfaces).
- The zap shader needs a working SCM/PIL path to TrustZone from XNU; without it the GPU may refuse to leave
  secure mode.
- Mesa on Darwin: freedreno's winsys assumes Linux DRM; a Darwin backend has to be written.
- Shader compile times on first boot (UniXNU reports ~40 s for the UI's pipelines on a much faster CPU).

## Order of work

RAM bandwidth measurement (running now) → G0 → decide between G1 and 4K pages / all 8 cores, with G1's RPM
client also serving the RAM speed.

#### G2 step 2 result (2026-10-22 00:18 to 02:16): libsweetca

`libsweetca.dylib` (our sweetgl + an EAGL layer, `mesa/darwin/sweetgl/sweetca.c`) makes CA's own `GLESContext` + `OGL::Renderer` run on freedreno: `sweetca_test` renders a 6-layer tree through `+[CARenderer rendererWithEAGLContext:options:]` into a BGRA IOSurface; background, opacity, text match the CPU renderer exactly, 2290 of 65536 pixels differ (black corner wedge of a masked rounded layer). 15 phone rounds, CI Mesa runs up to `39698050816`, no SMMU fault or panic. The 60 GLI slots agree with GLEngine's own table in our cache; our QuartzCore has the same code as sailfish's, 0x4000 higher (texture-function tables at `0x1d5b48a10` and `0x18855e1e4`). IOSurface textures from `texImageIOSurface:` need a vertical flip unless CA passes `invert`. Full account: [HANDOFF-G2-STEP2.md](HANDOFF-G2-STEP2.md).

#### G2 step 2 done (2026-10-22 03:01): `sweetca_test` PASS

Cause of the black corners: the texture CA renders into (here the test's `texImageIOSurface:` texture; in
backboardd the `attachImage:` one) never gets filters set, and its default `MIN_FILTER` `NEAREST_MIPMAP_LINEAR` with
only level 0 makes it **incomplete for sampling**, which reads as `(0,0,0,1)`. So every `gl_LastFragData` read (our
`texture2D(sca_fb, ...)`) returned opaque black, and draw 10 (`mix(s1, d0, s0.a)`) painted black wherever the mask
was above 0. Fix (commit `d8503bf`): a sampler object of our own (NEAREST, CLAMP_TO_EDGE) bound once on the
reserved framebuffer-fetch unit, so the texture's own state is untouched (ES 2 contexts, which have no samplers, set
the texture's MIN_FILTER instead). The experiment modes are gone.

Mesa CI `39702791445`, run on the phone already up on the j33 image (no reboot: `tools/g2/s2quick.sh`), logs
`logs/netlog-s2-t.txt.tests` and `logs/netlog-s2-t.txt` (kernel ring + run): **1089 of 65536 pixels differ** (tolerance
8; image 826, rounded layer 119, rotated square 144, background/opacity/text 0); the rounded layer's character map
is identical to the CPU's. No SMMU fault, hang or panic. Left within tolerance: the image's quadrant edges and diagonal,
and anti-aliased edges (CPU and GPU filter and cover edges differently; not looked into further). Render took 24.6 s
with `sweetgpu_debug` on (150 ms per kernel log line), so it says nothing about GPU speed.

#### G2 step 3 (2026-10-22 03:05 to 04:12): backboardd draws the UI on the Adreno 512

**Result: the home screen and Settings are drawn by the GPU and look right** (all icon labels, status-bar clock,
"Search", dock, badges, Settings rows). backboardd runs CA's own GLES renderer on Mesa through `libsweetca.dylib`,
loaded with `sweetenv=backboardd:DYLD_INSERT_LIBRARIES=/usr/local/bin/libsweetca.dylib,SWEETCA_TRACE=1` on a
`fastboot boot` image; nothing on the root changed except files in `/usr/local/bin`. Log line:
`|backboardd| sweetca: EAGLContext ... API 3 on Mesa: OpenGL ES 3.1 Mesa 26.2.5 ..., FD512`. **No SMMU fault, GPU
hang, refused import or panic in any of the five rounds.** Widgets show "Waiting..." (app extensions do not run on
this port, known before G2). The lock screen was not captured by the dumps (the phone was unlocked by the time
SpringBoard was up); `sweetgpu_debug` was off in every round, but speed is not measured yet (the per-100-flush
timing line never printed: CA does not seem to call `glFlush` once per frame; to look at).

How the screen was checked: `sweet_shot -s` (new, `mesa/darwin/sweetgl/sweet_shot.m`) looks up the 1125x2436
IOSurfaces by id (CA's IOMFB swap surfaces, which the kernel copies to the panel) and dumps them;
`tools/g2/shot2png.py` makes PNGs (kept out of git: they show device state). `CARenderServerRenderDisplay` returns
black here and is not usable. Rounds: `tools/g2/s3round.sh IMAGE NAME DELAYS...`; images `shim/out/shim-boot-j33-bb{1,2}.img`,
`shim-boot-j34-bb{3,4}.img` (`tools/g2/mkimg.sh` now takes `GPUDBG=0` and `VARIANT=`).

| Round (log `logs/netlog-s3-X.txt`) | Image, Mesa CI | Seen | Cause, fix |
| --- | --- | --- | --- |
| a (03:13) | bb1, `39704013746` | library loads, texture-function patches install, every `initWithAPI:` falls back to Apple's EAGL | backboardd asks ~25 s before SweetGPU is published (bring-up starts after `gpudelay`, 25 s default). libsweetca now waits for the service (30 s, later 90 s) once per process. A later context in this boot did get Mesa (so its "CPU reference" dump was GPU-drawn, not CPU) |
| b (03:27) | bb2 (+`gpudelay=1`), `39704983044` | **GPU renderer live**; icons upside down, no text at all | step 2's rule flipped `texImageIOSurface:` images on `invert:NO`; that rule matched only the test, whose target was bound `invert:YES` and whose layer tree is nearly symmetric. Now flip only on `invert:YES` (Apple's meaning; sailfish does not flip either) |
| c (03:38) | bb3 (kernel j0034), `39706390879` | icons upright; only in-place labels ("Photos") show; Settings chevrons solid gray boxes | most picture surfaces are client memory starting 64/4096/8192/12288 bytes into a 16 KiB page; the darwin backend refused any offset, so they were copied. Offsets now go to freedreno as `winsys_handle.offset` (64-byte aligned only) |
| d (03:55) | bb4, `39708078084` | clock, "Search", Wi-Fi/Sounds/General shown; copied labels and chevrons invisible | **the copy path kept the `(0,0,0,R)` swizzle meant for R8 storage on a `GL_ALPHA` upload**: every copied mask sampled transparent. Fixed; the per-frame re-copy added on a wrong guess (stale snapshots) was undone, copies refresh on seed changes (as sailfish does) |
| e (04:07) | bb4, `39709137207` | **home screen correct** | |

Also added on the way: kernel **j0034** (`xnu/patches/j0034-jasmine-surface-readonly.patch`, CI `39705841200`):
read-only client surfaces (topaz 0135's `kIODirectionOut` fallback) get read-only kernel, user and GPU mappings
(they used to fail to map, which is what `0xe00002bd` in step 2 was) and refused imports log why; none was refused
in rounds c-e. libsweetca: shadow render targets for `attachImage:` surfaces the a5xx cannot render into in place
(rows of 92, 112, 4512 bytes: a texture of their own, written back into the surface before CA flushes; 5 per boot),
`MIN_FILTER LINEAR` on IOSurface textures that still have a mipmap filter, slots 603-618 (`glUniform2f` ...
`glUniformMatrix2fv`; CA calls 610 and 611), `invertedRender` logged (CA passes 0 for display surfaces).

`gpudelay=1` did not bring SweetGPU earlier (still ~25 s after backboardd's first request), so the bring-up itself
takes that long; libsweetca's wait covers it.

**`sweetca_test` is now FAIL** (round e boot, `logs/netlog-s3-e-test.txt`: 9958 of 65536 differ, the image quadrant
upside down and 494 text pixels; background, opacity, rounded layer, rotated square match). With invert meaning
what it says, the in-process CARenderer + CGImage path of the test and backboardd's display path disagree about
image orientation; the display is the ground truth. Open: find which (CARenderer's own projection or the test's
`renderInContext:` reference) and fix the test, comparing with sailfish's harness.

Licence change during this step: the sailfish author consented to adapting his code (NOTES.md, 2026-10-22 ~04:10);
`sweetca.c` was checked against sailfish's `eagl.c` for the flip rule, page offsets, mask formats, copy refresh and
the feedback barrier (theirs is the same `TextureBarrierNV` we issue).

Next: the lock screen, Control Center and notification centre (the texture-function patches 0x14/0x26/0x27/0x2d
still need to be seen working), speed (frame timing, then GPU clock), `sweetca_test` orientation, and porting what
else sailfish's `eagl.c` does that ours does not.

#### G2 step 3, speed (2026-10-22 04:15 to 05:00): cache maintenance was the slowness

After round e the user found the GPU-drawn UI **slower than the CPU renderer**. Measured, not guessed:

- **Round f** (kernel j0035, `shim-boot-j36-bb6.img`; j0035: the darwin backend sends each submit's BO list
  `fd_submit->bos`, and SweetGPU cleans and invalidates only those buffers before the job and again once it has
  completed, the msm / ios-sailfish 0150-0151 model, instead of every buffer of the client around every submit, wait
  and completion query; per-client statistics every 10 s): backboardd still spent **up to 9897 ms of 10002 ms** in
  cache maintenance (19685 MB for 95 submits). The ~10 buffers of a job include the 11 MB swap surfaces and
  full-screen textures, and `IOFlushProcessorCache` walks them line by line (`dc civac`) at about 2 GB/s.
  j0036 (`gpupause=0`: no 35 s of pauses between bring-up stages) made SweetGPU appear before backboardd starts.
- **Round g** (j0037, `shim-boot-j37-bb7.img`): above 2x L2 (2 MB) every online CPU cleans and invalidates its
  caches by set/way (`cpu_broadcast_xcall_simple` + `FlushPoC_Dcache`, as XNU's `flush_dcache_syscall` does past
  `c_bulksize_op`), **0.6 ms each, no trouble under Qualcomm's hypervisor**: 6457 submits in 10 s (from 95-1180),
  2723 ms of them in cache maintenance. Frames (libsweetca: one `glFlush` per frame) 52-190 ms apart while the UI
  moves, of which 1-6 ms in `glFinish`: the GPU itself is not the limit. ~57 submits per frame, each two whole-cache
  flushes (before, and at retirement).
- **Round h** (j0038, `shim-boot-j38-bb8.img`: a submit's pass also covers the jobs completed meanwhile): **no
  change**, round g already did ~1 whole-cache flush per submit (retirements were merged at waits); 6568 submits in
  10 s, 2789 ms in cache maintenance (20-28 %), frames 60-113 ms apart while the UI moves (1-5 ms of it in
  `glFinish`). No SMMU fault, hang or panic in rounds f-h. Logs `logs/netlog-s3-{f,g,h}.txt`.

Boot-args of these images: `sweetgpu=4 gpumhz=266 sweetwdt=20 sweetgpu_debug=0 gpudelay=1 gpupause=0
sweetenv=backboardd:DYLD_INSERT_LIBRARIES=/usr/local/bin/libsweetca.dylib`; `sweetgpu_bulk=0` turns j0037 off.
Open: why ~57 submits per frame (Mesa batches per render target, libsweetca's readbacks); GPU clock 266 MHz and the
DDR vote (sailfish 0144/0146/0147/0164 did these on MSM8996; SDM660 needs its own values).

#### Speed with 8 cores (2026-10-22 18:18 to 18:28): the Silver cores slow the UI down

Same kernel (j51, 4K pages + AMP, CI `39807738178`, Gold 1747 MHz, GPU 266 MHz, libsweetca), same boot-args, the
user swiping home pages and scrolling Settings for ~2 min each; only `cpus=` differs.

| round | cores | frame interval while moving (100-flush averages) | glFinish | submits / 10 s | one whole-cache flush |
|---|---|---|---|---|---|
| s3 h (05:00, 16K kernel) | 4 Gold | 60-113 ms | 1-5 ms | ~6500 | 0.42 ms |
| `j51-swipe` 18:18 (`logs/netlog-j51-swipe.txt`) | 8 (4 Gold + 4 Silver) | **131-239 ms** | 1.7-4 ms | 1650-4200 | 0.61-0.73 ms |
| `j51c4` 18:22 (`logs/netlog-j51c4-swipe.txt`, image `shim-boot-j51c4-osm.img`) | 4 Gold (`cpus=4`) | **54-100 ms** (bursts 17-30 ms) | 0.5-3.7 ms | 3000-7700 | 0.42 ms |

- The 4K-page kernel itself costs nothing: with 4 Gold cores it matches the 16K round h.
- With 8 cores frames take ~2x as long. Cause (XNU `sched_clutch.c`): without CLPC every thread group prefers
  pset0 (Gold) for all QoS buckets, and `sched_edge_cpu_init_completed` lets P->E migrate and steal (weight 64),
  so whenever Gold is busy (SpringBoard + backboardd + Mesa) runnable UI threads, backboardd's render thread
  included, run on an idle Silver A53 (in-order, 1382 MHz), which is several times slower per thread; nothing
  pulls them back quickly. The whole-cache flush also reaches 8 CPUs (0.42 -> ~0.7 ms, ~55 per frame).
- Fix (next): a CLPC stand-in in the kernel: UI buckets (FIXPRI, FG, IN) prefer Gold and are not stolen by Silver,
  DF/UT/BG prefer Silver (logd, mds, etc. off the Gold cores), Silver only takes UI work when Gold is overloaded.
  Then GPU buffers write-combined (no cache maintenance at all, as msm/freedreno) and fewer submits per frame.
  Until then `cpus=4` is the faster setting for the UI.

#### j0052: CLPC stand-in for the Edge scheduler (2026-10-22 18:40 to 22:15)

What it does (`xnu/patches/j0052-jasmine-clpc-standin.patch`, jasmine ADT only, topaz unchanged): once both
clusters run, every thread group (existing and new) prefers Gold for FIXPRI/FG/IN and Silver for DF/UT/BG;
Gold-preferred work goes to Silver (spill or steal) only while Gold's per-CPU runqueue depth at that QoS is >= 2
(`sweetclpc_depth=`); Silver-preferred work goes to Gold only onto an idle Gold CPU. `sweetclpc=0` = Apple's
no-CLPC defaults, `sweetclpc=2` keeps DF on Gold. A `SWEET CLPC: 10 s ms` line gives CPU ms per cluster and QoS
(order FIXPRI/FG/IN/DF/UT/BG), ms on the cluster type the thread does not prefer and the border decisions; every
30 s `SWEET CLPC: top N` names the 5 threads with the most CPU.

| round | kernel / libsweetca | frame interval while moving (100-flush averages) |
|---|---|---|
| `j51-swipe` 18:18 (reference) | j51, 8 cores, reference lib | 131-239 ms (median ~132) |
| `j51c4` 18:22 (reference) | j51, 4 Gold, reference lib | 54-100 ms (median ~81) |
| `j52-swipe` 19:22 (`logs/netlog-j52-swipe.txt`, user swiping) | j0052 (CI `39816247751`), 8 cores, reference lib | 40-226 ms (median ~96) |
| `j52s-swipe` 20:50 (`logs/netlog-j52s-swipe.txt`, user swiping) | j0052 + stats, 8 cores, reference lib (swapped in for the round) | 89-237 ms (median ~128) |
| `j52on2` 22:00 (`logs/netlog-j52on2-ui.txt`, uiround.sh) | j0053-56 + j0052 (CI `39843322577`), 8 cores, on | 158, 195, 92 ms |
| `j52off2` 22:05 (`logs/netlog-j52off2-ui.txt`) | same, `sweetclpc=0` | 155, 153, 140 ms |
| `j52c4b` 22:11 (`logs/netlog-j52c4b-ui.txt`) | same, `cpus=4` | 152, 152, 124, 199 ms |

- With the reference library, 8 cores went from ~132 to ~96-128 ms against 4 Gold's ~81 ms; the cost of one
  whole-cache flush fell from 0.61-0.74 ms to 0.44-0.63 ms (4 Gold: 0.35-0.63), i.e. backboardd's submitting
  thread now runs on Gold. With j0053-56 (frames bound elsewhere) on, off and `cpus=4` are within noise of each
  other (1-4 moving 100-frame blocks per unattended round; the summary in uibench.py needs finer frame data to
  separate them). No panic in 8 boots, `8 cores x 100 runs at once: 0 errors` in every 8-core boot.
- Placement (ms per 10 s during the gestures, j52off vs j52on, FIX/FG/IN/DF/UT/BG):
  off: Gold 2077/223/9833/1686/3827/5199, Silver 41/68/815/455/847/2488;
  on: Gold 1895/204/11398/44/71/454, Silver 2/9/1411/2580/3426/6467. The stand-in takes ~10 s of DF/UT/BG per
  10 s off Gold; UI QoS on Silver stays small.
- Found by the top list, independent of j0052: **mediaserverd** tid ~600 (pri 37, IN) uses ~12-13 s of CPU per
  30 s on Gold all the time, UI idle or not; `vmd` (BG) ~20 s per 30 s on Silver. mediaserverd is probably
  polling for audio hardware jasmine does not have: next to look at, it costs ~40 % of a Gold core.
- One cpus=4 boot (`j52c4`, 21:42, stand-in off as there is no Silver cluster) never drew a frame: backboardd and
  SpringBoard all in mach_msg (sampler lines in `logs/netlog-j52c4-ui.txt`, not in git); the rerun was fine.

#### j0053: GPU pool + lazy IOSurface upkeep (2026-10-22 19:23 to 19:50): cache maintenance ~1 % instead of ~25 %

Profile first (libsweetca since `d8d851e`, Mesa CI `39815893071`: every 100 flushes `sweetca: prof:` lines with the
time and the kernel submits per GL wrapper, plus time in the submit and wait calls). j0053 (CI `39822208684`):
Mesa's buffers from a write-combined pool of RAM XNU does not manage (0xc0000000-0xf3ffffff, 13 x 64 MB, topaz's
pool code; the shim now passes its own place, `sweetshim=0x80080000 sweetshimsz=0x26000`), and imported IOSurfaces
cleaned before a job only if the CPU wrote them (unlock without read-only, or new) and invalidated when the CPU next
reads them (lock, the display's copy). All rounds: 4 Gold cores (`cpus=4`), user swiping/using the dock ~2.5 min.

| round | boot-args | frame interval while moving | cache maintenance / 10 s | log |
|---|---|---|---|---|
| j51c4 (before) | - | 54-100 ms | 1.1-3.2 s (2000-7700 whole-cache flushes) | `netlog-j51c4-swipe.txt` |
| **j53c4** | - | **38-68 ms** | **0.05-0.22 s (0-6)** | `netlog-j53c4-swipe.txt` |
| j53nl | `sweetgpu_lazy=0` | 68-120 ms | 2-3.7 s | `netlog-j53nl-swipe.txt` |
| j53np | `sweetgpu_pool=0` | 44-97 ms | 1-2.5 s | `netlog-j53np-swipe.txt` |

- Both halves are needed: pool alone leaves the surfaces' whole-cache flushes, lazy alone leaves Mesa's buffers.
- No panic, hang or corruption from the pool. The user sees an occasional flicker (the dock while interacting) in
  every variant, also with `sweetgpu_lazy=0`, and thinks it was there before: an older bug, more visible now.
- Profile (j53c4, moving): GL is 50-85 % of the frame; `glDrawElements` ~0.3 ms per call and **~0.65 kernel
  submits per draw** (submit call ~0.13 ms each, 6-12 ms a frame). Cause: Mesa does not merge submits that name
  shared buffers (`has_shared` in `freedreno_ringbuffer_sp.c`) unless the pipe has `no_implicit_sync`; every
  imported IOSurface is shared. SweetGPU has no implicit sync, so the darwin pipe now sets it (Mesa CI `39824777796`).

#### Next, from ios-flame (NWylynko/ios-flame, Pixel 4 / Adreno 640, MIT; read 2026-10-22 20:15)

- **Write-combine panic, root cause** (their METAL-NEXT.md section 4): `osfmk/arm/pmap/pmap.c:6884`
  `pmap_sync_page_attributes_phys` does `flush_dcache((vm_offset_t)(pp << PAGE_SHIFT), ...)` on a 32-bit
  `ppnum_t`, so pages above 4 GiB lose bit 32: our j0029/j0030 panic `phystokv_range: illegal PA 0x7c994000`
  is 0x1_7c994000. Fix `ptoa(pp)` and look for other `<< PAGE_SHIFT` on `ppnum_t` (pmap.c, caches.c). Keep the
  GPU pool anyway (832 MB of GPU memory beyond XNU's 2 GB).
- **Fit on the GPU**: they scale the 1125x2436 frame onto the panel with the GPU; our presenter does it on the
  CPU (`composeFit`) every frame. Alternative: the MDP VIG pipe's own scaler.
- **Submit wrapper as msm's a5xx_submit**: compare our ring (IBs + `CP_EVENT_WRITE CACHE_FLUSH_TS`) with
  msm's a5xx (cache invalidates at start, preemption/yield packets) once the frame rate exposes GPU-side issues.
- Metal itself: their stack is metal2vulkan (Rust) on Mesa Turnip (Vulkan, a6xx/a7xx only). No open Vulkan
  driver exists for the a5xx, so not for jasmine short of writing one; CA's GLES path covers the UI.

#### The flicker found (2026-10-22 20:42 to 21:30): CoreAnimation redraws a surface before our timer copies it

- j54k (20:42, kick every 32 draws, `logs/netlog-j54k-swipe.txt`): GPU and CPU overlap again (`glFinish` 1-8 ms,
  frames 29-55 ms), but the dock flicker is back. It tracks how early the GPU starts on a frame: there with ~80
  submits a frame, almost gone with one merged submit at the frame's end, back with kicks.
- j0055 (CI `39834825880`, round j55 21:01): the display's copy and IOSurfaceLock wait for the GPU's last job
  on a surface. Not the cause: fewer than 100 waits in the round (no log line). Kept (correct, costs nothing).
- **j0056** (CI `39838118045`): unattended rounds (`sweetcmd=1`: `touch`/`swipe`/`key` on the command port;
  `tools/g2/uiround.sh` + `uibench.py` play the same gestures every round and summarise), a flicker counter
  (A-B-A sparse checksums of each copied frame), a count of GPU jobs drawing into a surface the display still
  holds, and `sweetfb_sync=1` (copy a frame at its swap, on CoreAnimation's thread, not at the next 30 Hz tick).
- Rounds j56a / j56b (21:20 / 21:26, 4 Gold cores, same gestures, `logs/netlog-j56{a,b}-ui.txt`):

| | j56a (copy at the timer tick) | j56b (`sweetfb_sync=1`) |
|---|---|---|
| GPU jobs drawing into a surface the display holds | **1130** | **0** |
| frames shown (flicker-check windows of 300) | 300 | 600 |
| frame interval under the script (median, pauses included) | 147 ms | 83 ms |
| A-B-A flashes (dock / panel) | 1 / 3 | 1 / 2, then 0 / 0 |

- Cause: CoreAnimation draws into its two swap surfaces (ids 2 and 4) without honouring our in-use count
  (state page +0x18, `sweet_hold`), so the copy at our next tick read a surface already half into the next
  frame. Copied at the swap, nothing can overwrite it first; the 30 Hz pacing (`sweetfb_hz=30`) goes too.
  A-B-A checksums catch half-drawn frames poorly (new content, not an old frame): the held-surface count is
  the measure. Next: `sweetfb_sync=1` the default on jasmine.

#### Where a moving frame goes (j0057 sampling profile, 2026-10-22 22:59 to 23:15)

**j0057** (CI `39846789084`; tested on jasmine-merge j0056 + j0057, without j0052): a sampling profiler driven
over the command port. `prof start SECS [US [CENSUS_US [NAMES]]]` arms a per-CPU running timer (as kperf's,
`RUNNING_TIMER_SWEETPROF`) that fires every US while a non-idle thread runs, on a fixed grid, and records the
interrupted thread: pid, tid, user or kernel mode, up to 16 kernel frames, user PC/LR and 32 frame-pointer frames
(user stacks read through `at s1e0r` and the physical aperture, so nothing can fault at interrupt level). A kernel
thread every CENSUS_US records each waiting or runnable thread of the named tasks (state, block hint, x16 trap,
saved user stack). At the end a meta table (kernel and shared-cache slides, task/thread names, file mappings) is
written; `prof stat`, `prof get OFF` (hex), `prof meta OFF` read it out. `tools/g2/prof.py fetch` (Windows) /
`report` (WSL: ipsw per image, the kernel's and libsweetca's Mach-O symbols), `tools/g2/profsplit.py` (per-frame
split of CA's display thread), `tools/g2/profround.sh` (a uiround with a profile). Readout is slow: ~20 KB/s
(3.2 s per 64 KiB reply), 17.5 MB took 14 min; keep windows short or sample at 2 ms.

Round j57p (`logs/netlog-j57p-ui.txt`, `logs/prof-j57p-{report,report-others,split}.txt`; samples and meta stay
local, `logs/prof-j57p.{bin,meta}` in the main checkout): 4 Gold cores at 1747 MHz, GPU 266 MHz, libsweetca "kick"
(Mesa CI `39832781792`), `sweetfb_sync=1 sweetfps=1`, uibench gestures, 20 s at 1 ms on CPU + 2 ms census of
backboardd and SpringBoard: 133339 samples, 0 dropped, no panic or hang. The profiler costs nothing visible
(100-flush blocks 112.8 / 153.8 ms during it, 124.5 ms in the same gestures before).

- **The frame thread is `com.apple.coreanimation.display.primary`** (CA::WindowServer::IOMFBServer, driven by
  `display_timer_callback`; render-server is nearly idle, 8.6 ms/s). While the UI moves it is on a CPU 85-90 %
  of the time, waiting ~10 %, runnable only 2-8 %: **one CPU-bound thread**, so a frame is that thread's time.
- In the 7 s of motion (28 x 250 ms with the thread busy) it showed **142 frames (presents), 49.3 ms each**
  (as the user's trial: 40-55 ms). Per frame:

| part | ms / frame | % |
|---|---|---|
| GL, Mesa user code (libsweetca 11.7: draw validation, state emit, batches; malloc/free under it 2.8) | 14.6 | 30 |
| GL, SweetGPU ioctls on CPU (buffer create/map/free 3.0, other syscalls 2.2, wait path 0.9, other 0.8) | 6.8 | 14 |
| GL, waiting for the GPU (`_mesa_ClientWaitSync` -> `fd_pipe_fence_finish` -> `darwin_pipe_wait`: blocked 4.9, runnable 2.6) | 7.5 | 15 |
| **display copy at the swap** (`AppleCLCD::composeFit` 8.2, rest of present/swap 0.6, latch wait 0.1) | **8.8** | **18** |
| CoreAnimation's own code (QuartzCore 5.4, libc/objc/CF 0.7) | 6.1 | 12 |
| waiting in `kern_SwapEnd` (1.7) and CA's run loop between updates (1.1) | 2.8 | 6 |
| other kernel (mach_msg 0.6, rest 0.3) and other short waits (1.9) | 2.7 | 5 |

- So **outside GL: 20.4 ms (41 %)**: display copy 8.8, CA's code 6.1, swap/run-loop waits 2.8, the rest 2.7.
  Waiting for SpringBoard's commits is not part of it (CA's thread is busy, not idle, while things move).
  **GL including the GPU wait: 28.9 ms (59 %)**. The earlier "GL ~50 %" came from libsweetca's 100-flush blocks,
  which include idle stretches and count flushes (~0.45 per present), not frames.
- Hot paths (ms per frame): `AppleCLCD::composeFit` 8.2 (CPU nearest-sample scale 1125x2436 -> 997x2160 from
  the 11 MB surface); the GPU fence wait 7.5; Mesa's draw path under `w_DrawElements` 12.4 inclusive
  (`fd_draw_vbo` 7.1, `fd5_emit_state` 2.3, `fd5_program_emit` 0.8 self); a new batch per render target,
  `fd_batch_create` 3.2 -> `fd_submit_new_ringbuffer` 2.3 -> `bo_new`/`darwin_bo_new` 2.4 plus in the kernel
  `SweetGPUBuffer::create`/`mapGPU`/`free` (page tables, cache clean) 3.0; malloc/free under Mesa 2.8; CA's
  backdrop blur (`capture_backdrop` 7.9 inclusive, `filter_backdrop` 5.3, `GaussianBlurFilter` 3.1, mostly GL
  calls inside); CA's render tree (`CA::Render::Updater::prepare_layer`/`prepare_layer0` 0.7 self).
- Not the UI's: launchd 901 ms/s (workqueue threads in xpc/kevent, launchd+0x439fb), vmd 561 (a
  `-[CoreTelephonyClient synchronousProxyWithErrorHandler:]` loop), mediaserverd 423 (an xpc connection
  cancel loop), logd 123: ~2 of 4 Gold cores (the "IN thread" the scheduler session saw; sent to it). With
  `cpus=4` they cost the frame little (CA's thread runnable 2-8 %); for 8 cores and power they matter.
- Caveats: a sample taken when interrupts come back on is charged to `ml_set_interrupts_enabled` (time with
  interrupts off); the census skips threads idle for 500 ms; frames are counted from `present()` runs, so
  only with `sweetfb_sync=1`.

**Recommendation, by ms per frame:**
1. **Display scale off the CPU, -8.8 ms (18 %)**: let the MDP scan CA's surface with the VIG pipe's scaler
   (the direct path already exists for one GPU-pool surface; it needs the 1125x2436 -> 997x2160 scale), or draw
   the fit with the GPU into a panel-size surface. Also frees CA's thread at every swap.
2. **The GPU wait, up to -7.5 ms (15 %)**: GPU clock (266 MHz now; the Adreno 512 runs to ~650 MHz with its
   DDR vote), and once (1) is in, no CPU wait at frame end (the display already waits for the GPU, j0055).
3. **Mesa buffer churn, ~-5 ms (10 %), cheapest**: reuse ring/batch buffers (freedreno's BO cache in the darwin
   backend) instead of create + GPU map + free every batch; Mesa only, no kernel build.
4. CPU clock (1747 -> 2208 MHz, OSM + CPRh): the CPU part is 37 ms of the 49.
Together 1-3 would bring a moving frame from ~49 to ~28-30 ms.

#### j0058: the MDP scales the frame, honest SwapWait (2026-10-23 00:50 to 01:55; PERF-TASKS.md task 1, done)

**j0058** (`xnu/patches/j0058-jasmine-display-scale.patch`, tested build CI `39873547890`, test branch
`j0058-display`): the CPU display copy (`composeFit`, 8.2 ms of a 49 ms moving frame) is gone. All on by default on
jasmine, no boot-arg needed.

- **VIG0's QSEED3 scaler** (pipe + 0xa00 = 0x0c905a00, stock DT `qcom,mdss-vig-scaler-off`; HW version 0x1002)
  programmed as msm-4.4 `mdss_mdp_qseed3_setup` does for RGB without a LUT: bilinear, phase steps src/dst in 21-bit
  fixed point (0x242503 / 0x2416c1), preload 4x3, pixel extension = source size; SSPP source 1125x2436, output
  996x2160 at x 40 (same window as the CPU fit, so `sweet_fit_x/w` and touch are unchanged). ABL's register values
  are saved and written back whenever VIG0 scans a panel-size buffer again (flip buffers, console, panic).
  `sweetfb_scale=0`: CPU fit as before.
- **backboardd's screen-sized IOSurfaces from the GPU pool** (below 4 GiB, contiguous, write-combined; topaz's
  `gpu=1` path, now also when jasmine's scaler is on; SweetSurface takes the pool under SweetGPU's pool lock). A
  one-layer frame (every frame after boot: mask 0x1) is scanned in place: `present` takes 7-40 us instead of ~8.8 ms,
  597-600 of every 600 frames go to the scaler. Frames with several layers still go through `composeFit`.
  `gpu_fbpool=0` turns the pool frames off.
- **Why the flicker came back with in-place scanout, and the root cause of j0056's "held draws":** CoreAnimation
  does not use IOSurface in-use for its display surfaces at all (QuartzCore calls `IOSurfaceIsInUse` only from
  backing stores, image queues and HDR code). `IOMFBDisplay::can_update_` polls
  `IOMobileFramebufferSwapWait(fb, swapID, 0x80000000)` for each queued swap (at most 2) and draws into a swap's
  surface again only once that returns 0 (`kern_SwapWait` = selector 6, scalars swap ID, timeout with bit 31 for a
  poll, 0; `finish_update` also only polls). Our selector 6 returned 0 at once.
  - j58a (SwapWait done once the swap itself latched): very smooth, heavy flicker, **1662** GPU jobs into a
    held surface. CoreAnimation asks for swap N before it draws into N's surface again, and N was still on the panel.
  - j58c (`sweetfb_swapwait=2`: N done once a later swap latched): **23** held draws, but 1973 of 3030 polls "not
    done" (664 ms per 600 frames): with two swap surfaces CoreAnimation skips vsync ticks, 11-31 frames/s.
  - **j58d (default, `sweetfb_swapwait=1`)**: N done once a later swap *ended*, and a SweetGPU submit that writes a
    pool frame the display still retires waits for the latch (`sweet_fb_gpu_write_wait`, up to 50 ms), so
    CoreAnimation's CPU work overlaps the latch: **48** held draws (0 in 9 of 12 10-s windows; the rest are draws
    into the frame on the panel, which only a later swap can free), ~50 GPU waits per 10 s of ~6 ms each. User
    (01:55): "probably the best it has ever been. No flickers, pretty smooth."
  - `sweetfb_swapwait=0`: done at once (the old behaviour; topaz's default).

| round (4 Gold, GPU 266 MHz, uibench gestures) | held draws | libsweetca 100-flush median | SWEET FPS while moving | log |
|---|---|---|---|---|
| j57p (before, CPU copy) | 0 | 124.5 ms | 10-32 | `logs/netlog-j57p-ui.txt` |
| j58a (scaler, SwapWait done when latched) | 1662 | 116.2 ms | 20-61 | `logs/netlog-j58a-ui.txt` |
| j58c (`sweetfb_swapwait=2`) | 23 | 123.2 ms | 11-61 | `logs/netlog-j58c-ui.txt` |
| **j58d (default)** | **48** | **78.8 ms** | 10-54 | `logs/netlog-j58d-ui.txt` |

Caveats: the 100-flush figure counts flushes (~0.45 per frame), not frames, and SWEET FPS depends on where the
gestures fall; no same-kernel baseline rounds and no new profile were taken (the user judged it by eye). No
flicker counter on scaled frames (A-B-A checksums would read write-combined memory each frame); the held-draw
count is the measure. Counters: `SWEET FB: 600 frames: N scaled by the MDP, M copied; SwapWait ...` and SweetGPU's
10 s line `... N waited for the panel (M ms)`. The MDP block (0x0c901000-0x0c90a000) is now open to the command
port's `r`/`w` (`tools/cpuclk/osmctl.py`) for live display register work.

Next for the frame (PERF-TASKS.md): GPU clock (task 3) now matters more, since the display waits for the GPU's last
job before a flip and SweetGPU waits for the latch; the CPU wait at frame end (`glClientWaitSync`, 7.5 ms) could go
too, as the display already waits for the GPU (j0055).

#### j0060: GPU levels up to the speed bin's top through RPM votes (2026-10-23 02:20 to 04:00; PERF-TASKS.md task 3)

**j0060** (`xnu/patches/j0060-jasmine-gpu-clock.patch`, CI `39880355430`, 4K/8-core kernel): `gpumhz=` takes any
stock level (160, 266, 370, 430, 465, 588, 647, 700, 750) up to the speed bin's top, and the command port line
`gpu clk MHZ` switches at runtime (GPU idle under `gpu_lock`, then the kernel self-test); `gpu state` reads the level,
the measured clock, the votes, the rails and the DDR clock. Defaults unchanged: images still boot `gpumhz=266`.

- **RPM client** `bsd/dev/sweet_rpm.c`: ios-sailfish's polled GLINK client (Joran Vancoillie, patches
  0100/0146/0147/0164, adapted with his consent) moved to SDM660: message RAM 0x778000 (0x7000, TOC `grt0`, both
  FIFOs 1784 bytes), doorbell APCS 0x17911008 bit 0, every store from a register. `sweet_rpm_level(type, level)`
  votes `swen` 1 + `vlvl` in the sleep and the active set. The link came up at the first try ("link up, version 1,
  rcid 2"; the RPM also opens `glink_ssr`, ignored).
- **What a level needs** (stock DT: gfx CPR `cpr4-ctrl@05061000`, gpucc `qcom,gfxfreq-corner`, kgsl pwrlevels): the
  gfx corner's own supply is a stub (GFX runs from CX through the head switch), so a level = the **CX level vote**
  (`rwcx`: 0x40 up to 266, SVS 0x80 at 370, SVS_L1 0xc0 at 430/465, NOM 0x100 at 588, NOM_L1 0x140 at 647, TURBO
  0x180 at 700/750) + the **mem-acc select** (0x1fcf004 bit 0: 1 below 465 MHz, 0 from 465) + **cx_ipeak**
  (0x1fe5040, bit 1) above 700 MHz. Order up CX, mem-acc, ipeak, clock; down the reverse (cpr3-regulator).
  The PLL ping-pongs between GPU PLL0 (RCG source 1) and PLL1 (source 3) as `clk_gfx3d_src`; VCO band 0 above
  1 GHz. Our CX vote is never below `gpucxfloor=` (default NOM): it replaces the bootloader's AP vote, and this
  kernel votes for nothing else (display, buses).
- **This phone: speed bin 0x87** (QFPROM 0x7841a0 = 0x10f80000, bits 21-28), whose top level is **647 MHz**: 700 and
  750 are refused, so the ipeak path never runs here. CX at boot is already NOM (PM660L S3 VSET 772 before any vote,
  unchanged by a NOM vote); the NOM_L1 vote raised it to 924, then 816 (the RPM's own CPR), MX followed
  (864 -> 876) without a vote. DDR (GCC debug mux `bimc_clk`, 0x19d) reads **647 MHz** in every round; sailfish's
  MSM8996 doubles this counter, and the CPU already reads 6.4 GB/s (more than a 32-bit LPDDR4 bus moves at 647 MHz),
  so the real DDR clock is probably ~1294 MHz of the stock table's 1804.

| round | what | result | log |
|---|---|---|---|
| j60a (03:13) | boot 266, then `gpu clk` 370 / 465 / 588 / 647 / 700 in one boot, uibench at each | every switch ok, measured 369 / 464 / 588 / 647 MHz, self-test PASS each, 0 GPU faults; 700 refused (bin) | `logs/netlog-j60a-clk.txt` |
| j60b (03:33) | boot `gpumhz=647`, 3 uibench plays | **backboardd stopped after 35 GPU jobs** (03:34:11, render thread inside an IOKit call from Mesa; GPU idle, all jobs done, display on); kernel and phone fine | `logs/netlog-j60b-clk.txt` |
| j60c (03:49) | boot `gpumhz=647`, uibench + 8 s profile | renders normally (300 submits / 10 s); not reproduced | `logs/netlog-j60c-ui.txt`, `logs/prof-j60c-report.txt` |

Per-level numbers (j60a, `tools/g2/clksum.py`; 4-6 moving 100-flush windows each, so noisy): GPU waits per flush
3.5 ms at 266, 2.9 at 370, 3.1 at 465, 2.9 at 588 MHz; glFinish 4.5 -> 4.2 ms; the 100-flush median did not improve
(98 ms at 266, 118-137 ms higher, within the play-to-play spread). The 647 MHz play of j60a ran (jobs 12542 ->
15724, self-test PASS) but fell after the log's end (round window too short, fixed in `clkround.sh`).

**So the GPU clock is not what holds the frame now:** 2.2x the core clock cut the GPU wait by ~15 %. The GPU's work is
bound by memory or fixed costs (fence polling, submit), and the frame by the CPU: in j60c's profile launchd (921
ms/s), vmd (524) and mediaserverd (430) take ~1.9 of the 4 Gold cores (PERF-TASKS task 7), CA's frame thread got
178 ms/s and was runnable (waiting for a CPU) 28 ms/s; SweetGPUBuffer::create is still 4.7 % of it (task 4). The
libsweetca symbols in that report are wrong (the library in `xnu/out-mesa` is not the one on the phone); kernel
frames are right.

Open: the j60b stall (once in 3 boots of this kernel, both 647 MHz boots counted; not seen in any earlier UI round).
Tools: `tools/g2/clkround.sh` (levels in one boot, `LEVELS=`, `PLAYS=`), `tools/g2/clksum.py` (per-level summary).

#### j0064: DDR clock vote through the RPM; memory is not the brake above 1296 MHz (2026-10-23 04:10 to 05:25; PERF-TASKS.md task 9)

**j0064** (`xnu/patches/j0064-jasmine-ddr-vote.patch`, CI `39889598650`, 4K/8-core kernel, test branch `j0064-ddr`):
the DDR rate follows our vote; nothing changes unless asked (no boot-arg = the bootloader's 1296 MHz, no RPM clock
handoff).

- **RPM** (`bsd/dev/sweet_rpm.c`): `sweet_rpm_clk` ("KHz " in sleep + active set) and `sweet_rpm_clk_scaling`:
  every sdm660 RPM clock of msm-4.4 `clk-smd-rpm.c` handed off at its maximum in both sets (rate clocks "KHz "
  2147484, qdss "STAT", cxo "Enab" 1, XO buffers "swen"/"pccb" 1; 19 resources), then `clk0` id 2 `Enab` 1, as
  `rpm_smd_clk_probe` does (sailfish 0146/0147 did the MSM8996 list). The first try worked: "clock handoff of 19
  resources, scaling on: ok (0 requests failed)", no bus dropped, no hang. `sweet_rpm_kvp` + command port
  `rpm a|s|as TYPE ID KEY VALUE` ('_' for a space) for raw requests.
- **`bsd/dev/sweet_ddr.c`**, command port: `ddr state` (DDR = bimc debug-mux counter x 2, snoc / cnoc / cnoc_periph /
  bimc_gfx / bimc_hmss_axi), `ddr MHZ` (handoff + scaling the first time, then the bimc vote, ~23 ms), `ddr bench`
  (one core: write / read / copy over 64 MiB + a random dependent-load chase over 64 MiB), `ddr bw [MS] [load] [bg]`
  (bus counters below; `bg` in a kernel thread with the result in the log, so uibench keeps the port). Boot-arg
  `sweetddr=MHZ` votes at GPU bring-up. The bwmon block is open to `r`/`w` (osmctl).
- **Counter factor confirmed:** votes 768 / 1017 / 1296 / 1804 read back 766 / 1016 / 1294 / 1804: GCC's `bimc_clk`
  (0x19d) counts half the DDR rate, so the bootloader leaves **1296 MHz** (stock top 1804).
- **Bus counters.** CPU: bimc bwmon4 MON2 (0x01008000, mport 0), one 54.6 ms hardware window polled every ms; its
  unit is **1 MiB**, not the DT's 64 KiB `count-unit` (a 3554 MB/s read load added 3880 MiB/s at 1296, a 3789 MB/s
  load ~4700 MiB/s at 1804 against the idle 1.8 GiB/s: 10-25 % over the known bytes, prefetch and the rest of the
  system); the legacy MON_CNT reads garbage. GPU (as kgsl's bus DCVS): busy cycles (RBBM_PERFCTR_RBBM_0, countable 6),
  VBIF AXI beats (VBIF_PERF_CNT0, countable 85), VBIF RAM-starved cycles (VBIF_PERF_PWR_CNT0).

**Round j64a** (`tools/g2/ddrround.sh`, 4 Gold, GPU 266 MHz, one boot, `logs/netlog-j64a-ddr.txt`; per-flush costs
from `tools/g2/ddrcost.py`, bench and bus medians from `tools/g2/ddrsum.py`). The 100-flush "ms each" figure mostly
measures the idle gaps of the gesture script (75-400 ms, no trend), so the comparison uses libsweetca's time inside GL
per flush over the same gestures:

| DDR MHz (order) | Mesa CPU per flush (GL - wait) | GPU wait per flush | latency (chase) | write / copy MB/s | CPU bwmon while moving | GPU RAM-starved / busy |
|---|---|---|---|---|---|---|
| 1296 bootloader | 22.4 ms | 7.3 ms | 318 ns | 7568 / 4014 | 1.9 GB/s | 13 / 21 Mcyc/s |
| 1296 (1, after the handoff) | 20.0 | 4.8 | 320 | 7584 / 3979 | 1.9 | 14.5 / 22 |
| 768 (2) | **31.1** | 6.5 | 454 | 4313 / 2661 | 1.4 | 13 / 22.5 |
| 1804 (3) | 19.5 | 5.4 | 275 | 8300 / 7604 | 2.2 | 5 / 15 |
| 1017 (4) | **24.2** | 5.6 | 366 | 5330 / 3333 | 1.7 | 17 / 22 |
| 1296 (5) | 18.6 | 2.8 | 320 | 7064 / 4440 | 1.9 | 6 / 7 |
| 1804 (6) | 18.9 | 5.3 | 276 | 9959 / 5022 | 2.2 | 7 / 22 |

(read bandwidth on one core is noisy, 3.1-6.9 GB/s with no order; latency and write repeat within 1-2 %.)

**So memory is not the brake at the bootloader's rate.** Below 1296 MHz Mesa's CPU work grows steeply (+21 % at
1017, +60 % at 768), but 1296 -> 1804 changes it by nothing measurable (19.3 vs 19.2 ms per flush, spread ~1.5 ms)
although the latency drops 14 %. The GPU spends a third to two thirds of its busy time starved for RAM (less at
1804), yet the GPU wait per flush does not follow, and the GPU is busy only ~8-25 % of the time while the UI moves:
not on the critical path. CPU traffic is ~2 GB/s of a bus that moves several times that. 1804 stays off by default
(more power for no gain); `sweetddr=1804` and live `ddr 1804` are there. Keep the DDR at 1296 or more: anything
that turns RPM clock scaling on must also vote bimc, or the RPM may pick a low rate and cost 20-60 %. No hang in ~8 min at
1804 over two plays; no dedicated 10-minute series (not needed for an off-by-default setting).

**Fresh profile j64p** (same kernel, DDR 1296, `tools/g2/profround.sh`, 10 s, `logs/prof-j64p-report.txt`; libsweetca
symbols from `xnu/out-mesa-kick`, the newest build, plausible but not checked against the phone's copy):
- launchd 901 + vmd 531 + mediaserverd 435 ms/s = **1.87 of the 4 Gold cores** in their retry loops (task 7);
  CoreAnimation's display thread is on a CPU 214 ms/s and **runnable but waiting for a CPU 45 ms/s**.
- On the display thread: kernel 40 % of its time, libsweetca 34 %, QuartzCore 15 %, malloc 6 %. Buffer churn
  (task 4): Mesa `bo_new` 12 % inclusive, `SweetGPUBuffer::create` 6.2 % self plus GPU VM map/unmap page-table work
  and cache flushes (~2.5 %); GPU fence waits in `sweet_gpu_wait`'s delay loop ~4 %; the backdrop blur
  (`capture_backdrop`) 32 % inclusive.
- `profsplit.py` finds no frames since j0058 (it counts runs inside `AppleCLCD::present`, which is microseconds
  now); needs another frame marker.

Next by this profile: task 4 (Mesa buffer reuse, Mesa build only) and task 7 (the daemon loops) before the Gold
clock (task 2).

**GPU default 588 MHz (2026-10-23 05:45).** j0060 had left the images at `gpumhz=266`. `tools/g2/mkimg.sh` now boots
`gpumhz=588`: the top level at the NOM CX corner, which the bootloader already holds (CX vset 772 mV before and
after the vote), so 2.2x the clock without a voltage increase. 647 MHz needs NOM_L1 (CX 816-924 mV, more heat on the
whole CX rail) for 10 % more clock on a GPU that is off the frame's critical path, and the open j60b stall was at a
647 boot. First boot at the default: the Mesa session's round t4b1 (`logs/netlog-t4b1-ui.txt`): measured 587 MHz,
self-test PASS, UI rendering. A later `gpumhz=` in the extra boot-args overrides the default. The j0064 DDR round
(j64a) ran at 266 MHz: its CPU-side result (Mesa CPU per flush flat 1296 -> 1804) holds; the GPU-wait part was
measured at 266 only. Task 11 (GPU DCVS) replaces the fixed level.

**Back to 266 MHz (2026-10-23 06:07).** t4d2 (the task 4 session's boot at the 588 default) froze backboardd at
startup like j60b: the UI stops after the first 10-second line ("5 submits in 29087 ms"), GPU idle with all jobs
done, CA's display thread blocked in a SweetGPU buffer free (fLock, then gpu_lock in `sweet_gpu_vm_unmap`). Across the
logs this startup freeze shows in 2 of 4 boots above 266 MHz (j60b 647, t4d2 588) and in none of 54 boots at 266; a
live switch to 588 after startup ran clean (j60a). `mkimg.sh` is back at `gpumhz=266` until PERF-TASKS task 14 fixes
the race; then 588 becomes the default again.

**Mesa buffer caches (PERF-TASKS task 4, 2026-10-23 05:40-07:30).** Profile j64p had put ~17.8 % of CA's display
thread into SweetGPU buffer create + map + free behind Mesa cache misses.
- *Diagnostic build* (e91fcb6, CI 39896710936, `xnu/out-mesa-t4diag`): bucket counters (`FD_BO_CACHE_STATS` without
  its per-miss log lines), the reason for each miss (busy entry at the bucket head with its fence, or idle entries
  with other flags), SweetGPU creates/maps/frees, every pipe's `control->fence` vs `last_fence` and the kernel's
  completed seqno, all in libsweetca's `prof:` lines; `tools/g2/cachesum.py` sums them. Upstream's `BO_CACHE_DEC`
  incremented (fixed). Round t4d3 (266 MHz, `logs/netlog-t4d3-ui.txt`):
  - **the fences are exact**: `ctrl == last_fence` in every report (pipe 1; pipe 0, the screen's, never submits), so
    the brief's first suspect (a control fence that never advances) is out;
  - **2.6 SweetGPU creates per frame** over the moving windows, 2.0 of them ring-cache misses: a frame takes ~145
    command rings from the ring cache, and when a gesture needs more rings than the last second did, the cache is
    dry (busy head = rings still in flight, ufence 2-7 ahead of ctrl) or empty, and the surplus expires 1-2 s later;
  - bo cache: 0.6 misses per frame, mostly empty buckets (CA's blur surfaces change size with the animating
    layers), some hint-only mismatches (wanted `FD_BO_HINT_IMAGE`, had `FD_BO_HINT_BUFFER`).
- *Fix* (040dc17 + 047332e): **freedreno's sub-allocation heaps on Darwin** (`use_heap`): rings and buffers under
  4 MiB are carved from 4 MiB heap blocks, as Mesa does on a6xx+. Upstream keeps a5xx off them because "userspace
  fences don't appear to be reliable enough" there; ours are exact (above), and the bo/ring caches already trust
  the same per-buffer fences. The bo cache now matches entries ignoring the `_FD_BO_HINTS` bits (the darwin backend
  allocates the same memory whatever the hint). The heaps exposed a latent darwin bug: the IB address of a
  sub-allocated ring counted its offset in the block twice (`submit_offset()` is relative to the heap block, as msm
  passes the block's handle); t4f1's first try stalled the GPU after 7 submits (CA in `glFinish`), fixed in 047332e.
- *Result* (`xnu/out-mesa-t4fix2`, rounds at 266 MHz, kick library = the previous build):

| round (`logs/netlog-*-ui.txt`) | library | busy windows | Mesa CPU / flush | GPU wait / flush | GL / flush | SweetGPU creates / flush |
|---|---|---|---|---|---|---|
| t4b2 06:15 | kick (before) | 7 | 25.9 ms | 8.7 | 34.6 | (no counters) |
| t4d3 06:05 | diagnostic (before) | 13 | 20.7 | 5.3 | 26.0 | 2.61 |
| t4f1 06:38 | heaps | 6 | 23.0 | 11.7 | 34.7 | 0.35 |
| t4f2 06:43 (profile) | heaps | 6 | 22.4 | 11.5 | 33.9 | 0.34 |
| t4f3 06:53, 12 min, gestures x3 | heaps | 27 | 19.6 | 7.6 | 27.2 | 0.11 |

  (t4b1 at 588 MHz, kick: 27.6 / 6.5 / 34.1.) The one-play rounds compare directly with t4b2 (same gestures, about
  the same draws): **Mesa CPU -3 ms per frame (-12 %)**, but the GPU wait at the frame's `glFinish` grew by the same
  amount, so the time in GL per frame is unchanged at 266 MHz: once the CPU side is shorter the frame ends waiting
  for the GPU's tail. t4d3 drew twice the frames of the other one-play rounds (89k draws vs 40-44k) and is a lighter
  mix, not a baseline for the totals. With warm caches (plays 2-3 of t4f3) creates fall to ~0.1 per frame.
- *Profile t4f2* vs j64p (CA's display thread, `logs/prof-t4f2-report-top.txt`, `--top 400`): `darwin_bo_new`
  11.6 -> 5.7 %, `darwin_bo_map` 3.6 -> <0.1 %, frees 2.6 -> 0.3 %: **17.8 -> ~6 %**. What remains is
  `realloc_bo` (4.5 %): CA's large offscreen blur surfaces, created when a gesture opens at a size no freed one has
  (empty buckets, no busy heads, no flag skips). Reusing them needs a looser size match or CA keeping its surfaces
  (sweetgl side); most of the rest is likely heap block churn (`fd_bo_new_ring` 2.9 % with the heap).
- *On the phone* (2fc0a87, CI 39903986273, `xnu/out-mesa-t4final`: the same plus IOSurface imports and handles
  held in the `prof:` line): installed in `/usr/local/bin` 07:11, plain slot b boot (`fastboot reboot`, boot_b =
  j0064 image, `abmark=b gpumhz=266`) 07:23, gestures x3 for 12 min (`logs/netlog-t4slotb.txt`): UI up, no panic,
  Mesa CPU **17.2 ms** per flush (GL 24.3, wait 7.1) over 29 busy windows, creates 0.10 per flush, SweetGPU handles
  held 155 at startup, ~236 once the caches filled, then **flat at 265-269 through the third play** (no leak).
- *What it buys.* The CPU side of a frame is cheaper and the kernel's buffer path is out of the frame, but at
  266 MHz the saving reappears as GPU wait at the frame's end, so frames are not visibly faster yet. That tail is
  probably serialization more than GPU clock (task 3: 266 -> 588 MHz cut the wait only 3.5 -> 2.9 ms): CA's frame
  ends with `glFinish`, the last batch is sent then and the CPU idles while the GPU draws it. Overlapping frame N's
  GPU tail with frame N+1's CPU work (no `glFinish` per frame in libsweetca, fences instead) is the next lever.
- *Command-port reboot can hang in shutdown*: 07:11 (`logs/netlog-t4hang.txt`) the kernel logged "syncing disks...
  Killing all processes", then nothing but the charger and USB lines for 10 min; the command port was dead, power +
  volume-down recovered it. 05:52 (t4d1, "no fastboot device 90 s after the reboot command", black screen with only
  the status bar) was most likely the same: the running backboardd had the kick library then.

#### Task 7: the XPC retry loops were our own removed daemons (2026-10-24 00:56 to 02:56; PERF-TASKS.md task 7, done)

Two of the earlier "no hardware" root changes left clients that retry at once, without backoff
(`logs/prof-j57p-report-others.txt`, confirmed on the phone):
- **mediaserverd** (one workqueue thread, 79 % inside `BTAudioHALPlugin`): XPC connection cancelled ->
  `xpc_connection_resume` -> `bootstrap_look_up_slow` -> fails -> again. The plug-in's service is
  `com.apple.BTAudioHALPlugin.xpc`; no job in the launchd cache serves it since bluetoothd's MachServices were
  emptied (2026-10-21, `tools/launchd-disable-inplace.py`).
- **vmd** (Visual Voicemail): `-[CoreTelephonyClient getActiveContexts:]` -> sync proxy -> error block
  (`_computeNotificationSetForced_sync`, an `os_log_error` each time) -> again. CommCenter is not there (no baseband,
  `tools/sweet-root-tweaks.py`).
- **launchd** (two workqueue threads, 66 % in the kernel) served those failed lookups; **logd** took the error
  logs. Neither had a loop of its own.

Fix on the phone's iOS root (no kernel change, j0062 unused): `BTAudioHALPlugin.driver` moved from
`/System/Library/Audio/Plug-Ins/HAL/` to `HAL.disabled/` (file by file through `sweet-fs.py`, which cannot rename
or remove directories: an empty `BTAudioHALPlugin.driver` folder stays in `HAL/`, harmless), and
`com.apple.voicemail.vmd` removed from `/System/Library/xpc/launchd.plist` (`tools/sweet-launchd.py remove`).
Originals in `research/t7/` (not in git). `tools/sweet-root-tweaks.py` does both for new roots.

| ms/s at idle (census, 3 s) | t7a, before (00:56) | t7b, after (01:12 boot) | t7d (02:55, after the task 14 fix) |
| --- | --- | --- | --- |
| launchd | 966 | 1.7 | 16.7 |
| vmd | 644 | - (not started) | - |
| mediaserverd | 412 | 1.3 | < 1.3 |
| logd | 139 | 0.3 | 5.7 |
| sum | **2.16 cores** | **~0.003 cores** | ~0.02 cores |
| TSENS | 51-59 C | 45-50 C | 46-51 C |

t7d's launchd is mostly the launch of nanotimekitcompaniond (fresh pids 361/362, ~70 ms/s while starting; it is
exec'd ~14 times per boot): not a steady loop, not looked at further. bluetoothd is still exec'd about every 10 s
(~20 per 4 min) from its emptied job, < 2 ms/s of launchd. Not measured: the moving frame. The one gesture round
(t7c, 01:17) hit the boot-logo freeze (task 14, lsd seeding without a Wi-Fi MAC, fixed since), so CA's runnable wait
(45 ms/s in j64p) has no after-figure yet. Not checked by the user yet: Settings, Control Center, system sounds.

#### Current bottleneck baseline (2026-10-24 03:14-03:22)

First pass after tasks 1/4/7 and the task-14 ADT fix, on the existing running slot b:
[full report](PERF-BASELINE-20261024.md). Nine six-second profiles, zero dropped samples,
separate unprofiled/counter workloads, 4 Gold at 1747 MHz, GPU 587-588, DDR ~1296;
the installed graphics library byte-matches task 4's final artifact. No new CI/build,
reboot, flash or software/clock change.

CA's display thread is on CPU ~75% for home swipes and 82-85% for Control Center;
Mesa/wrapper plus support-library work is ~63-66% of its CPU. Lower-rate sampling agrees.
`w_DrawElements` is 52-57% inclusive CPU; `draw_prep` 10-13%, batch creation ~7%
(overlapping). GPU average busy is 34-46%, with RAM-stall cycles a secondary lead.
First measured Spotlight incurs ~276 ms shader-worker waiting across six seconds;
the repeat has none. Home's SpringBoard main thread is also busy (711-743 ms/s).
Task 5 is the next steady-motion target; accurate FPS/frame latency still needs explicit
swap/latch timing, because flushes are not frames and sampled `present()` counts broke
when j0058 made it microsecond-fast. Raw data stays ignored in
`research/perf-firstpass-20261024/`. Final 03:24 check: GPU 12516/12516 jobs completed,
clocks unchanged, profiler idle; our log collector stopped and phone lock released.

#### Task 5 step 1: barrier-driven batch churn (2026-10-24 03:55–04:08)

[Draw-path report](PERF-TASK5-DIAGNOSTICS-20261024.md). Diagnostic commit `8a3ed2b`,
Mesa CI `40051205502` passed. Opt-in nested elapsed-time scopes and batch/flush-reason
counters, no rendering or synchronization change. A separate diagnostic dylib was
tested in two RAM boots of the existing j69b kernel (Gold1747/GPU588/DDR1296),
profiling on and off; production library and slot b unchanged. Two ~30 s home and
Control Center repeats per variant, four six-second CPU profiles, 227328 records,
zero dropped. Matching off samples: display thread ~77%/89% on CPU; Mesa/wrapper
user plus support calls ~65.5% of that CPU.

Of actual finalized batches, **80.3% home / 76.3% Control Center contain one draw**.
Texture barriers cause 74.5%/59.7% of finalizations; resource dependencies another
18.8%/32.0%. Program-cache hits 100% in warmed selected windows, uploads/uniforms
smaller. Batch create and finalize exclusive elapsed costs ~1.77+1.85 ms/flush home,
3.95+4.09 Control Center; state emission repeats. These are elapsed costs, not
additive CPU/frame saving estimates. Counter-on GL elapsed +0.9%/+5.1% vs off,
so later gains must be confirmed with diagnostics off. Swap arrivals measured,
distinct latch FPS/latency still unmeasured.

Next: explain which barriers current program sampler use actually requires,
preserve framebuffer-fetch dependencies, then test reducing unnecessary batch breaks.
Task 5 remains open. Surface-fence pipelining recorded separately as task 16.
Fresh and exact task-4 `sweetgpu_gltest` both expose a pre-existing stride/offset
argument swap in the IOSurface test helper (other five cases pass); CA does not
use that helper. Not fixed in this measurement step. Raw data in `research/t5/`.
On->off reboot hung at root unmount and needed user buttons; off->charging reboot
succeeded, r109 temporary charging image booted at ~04:08:30. See NOTES for final
charging verification and lock state.
