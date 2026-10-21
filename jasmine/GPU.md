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

### G1: the GPU in the kernel (1-2 weeks)

- An **RPM client** (SMD) for the votes the GPU needs (GPU rail, GPU and bus clocks). The same client can raise
  the RAM and bus clocks, so it pays twice (see the memory bandwidth measurement in NOTES.md).
- Power up the GPU, load the microcode, start the command processor and run a ring:
  **"the GPU executes our commands"** (a memory write, then a fill or a copy), with fences.
- First real use: let the GPU do the per-frame **scale and copy into the flip buffer** that the CPU does today
  (AppleCLCD::composeFit). Small but tangible, and it proves DMA, IOMMU and fences.

### G2: CoreAnimation on the GPU (weeks to months)

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
