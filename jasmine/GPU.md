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
