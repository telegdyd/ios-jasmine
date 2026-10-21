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
- **Running our programs on the phone** is up to the user for now (an automated safety check stops me from
  setting up launchd jobs that start them); `sweet-fs.py` puts binaries on the root and fetches their output.
- **CoreAnimation:** to decide after the first milestone: a GL ES implementation in place of OpenGLES.framework for
  backboardd, or the `gld*` renderer plugin (G0.1).

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
