# GPU acceleration plan (Adreno 512)

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
