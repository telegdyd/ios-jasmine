# Handoff: G2, CoreAnimation on the Adreno 512

Written 2026-10-21 ~21:45 for the next agent. Scope: GPU acceleration of the iOS 16 userland on the Mi A2
(jasmine, SDM660, Adreno 512). Read this, then [GPU.md](GPU.md) (plan, G0.1 research, G2 log) and the top of
[NOTES.md](NOTES.md) (whole-project state). The repo root `AGENTS.md` and `NOTES.md` are the upstream
sweet/topaz projects' and still apply where they talk about rules.

## 1. Where things stand

The GPU pipeline works end to end in test programs. CoreAnimation does not use it yet: the UI is still drawn by
CA's CPU renderer.

| When (2026-10-21) | Milestone | Evidence |
| --- | --- | --- |
| 20:35 | Mesa freedreno drives the Adreno 512 from iOS userland: `sweetgpu_fdtest` clears a render target | `logs/netlog-j30-fdtest.txt` |
| 20:49 | First triangle (ir3 shaders, varyings) | `logs/netlog-j31-tri.txt` |
| 21:09 | OpenGL ES 3.1 through our `sweetgl` frontend: `sweetgpu_gltest` clear, GLSL triangle, blended texture, depth | `logs/netlog-j31-gl.txt` |
| 21:33 | The GPU renders into IOSurfaces and samples them, no copies (kernel j0032, gltest steps 5-6) | `logs/netlog-j32-iosurface.txt` |

All checks are pixel-exact against computed expectations (0 wrong pixels). Last commits on `jasmine`:
`0203d31` (j0032 result), Mesa patch commit before it. Last good CI runs: kernel j0032 `39661563719`, Mesa
`39661351032` (repo `telegdyd/ios-jasmine`).

**Phone state at handoff:** booted from the test image `shim/out/shim-boot-j32-gpu.img` (temporary
`fastboot boot`, kernel j0032 with `sweetgpu=4 gpumhz=266 sweetwdt=20 sweetgpu_debug=1`). **Slot b is
unchanged (standalone kernel j0024)**; nothing was flashed for G2. If the phone sits in the charging shell with
the screen off, the user did that on purpose; it is not an error.

## 2. Ground rules (from the user; do not relax them)

- **Ask before anything destructive or that changes the phone's iOS root**: flashing any partition, GPT, writing
  files into the iOS root other than test binaries in `/usr/local/bin`, changing launchd plists, replacing
  frameworks. `fastboot boot` of test images is fine without asking. Never write outside the iOS window of the
  disk. Keep the Nura (Android) server restorable from the backup in `Xiaomi A2/backup/` (not in git).
- **Do not set up launchd jobs or remote runners yourself.** The user wrote and installed `sweetd` (the program
  runner on the phone); you may use it.
- Keep device dumps, serial numbers and Apple artifacts (IPSW, shared cache, extracted binaries) out of git.
- Prefer root-cause fixes over workarounds, even when the benefit looks equal.
- Say clock times ("at 21:33"), not "this morning".
- Commit and push each milestone, update GPU.md/NOTES.md with exact results, run IDs and log files.
  Commit trailer: `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`. XNU patch commits use
  `-c user.name=telegdyd -c user.email=telegdyd93@gmail.com` (the WSL tree has no identity).
- The user lets the agent drive and is hardware-savvy; report results plainly, including failures.

## 3. The stack as built

### Kernel: SweetGPU (`iokit/Kernel/arm/SweetGPU.cpp`, `bsd/dev/sweet_gpu.c`; patches j0026-j0032)

Published as IOService `SweetGPU` once the GPU is up and its self-test passed (boot-arg `sweetgpu=4`). User
client selectors:

| Sel | Call | In | Out |
| --- | --- | --- | --- |
| 0 | get param | param (ready, chip id, gpu id, GMEM size/base, VA start/size, rings, timestamp) | value |
| 1 | buffer new | size, flags (bit 0 GPU read-only) | handle, GPU VA |
| 2 | buffer free | handle | |
| 3 | submit | struct: u32 n, u32 0, n x {u64 IB GPU VA, u32 dwords, u32 0} | seqno |
| 4 | wait | seqno, timeout ms | (kIOReturnTimeout) |
| 5 | completed | | last seqno done |
| 6 | import IOSurface (j0032) | surface id, flags | handle, GPU VA, size, pixel offset |
| 7 | buffer info (j0032) | handle | GPU VA, size |

`IOConnectMapMemory64` with memory type = handle maps a buffer. One GPU address space for everybody (SMMU
context bank 0, 4K pages, VA from 32 GiB up to 60 GiB, **bump allocator, never reused**). Buffers are cacheable;
the kernel cleans and invalidates **all** of a client's buffers around every submit, wait and completion query
(write-combined IOBufferMemoryDescriptors panic this kernel, see GPU.md). Submits are CP_INDIRECT_BUFFER_PFE per
IB plus a CACHE_FLUSH_TS fence that is polled (no interrupts). `sweetgpu_debug=1` logs every call and sleeps
150 ms per line, and runs a 1 s hang check per submit: slow, but it shows where a hang happened. Panics go out on
the live log connection (j0030).

IOSurfaces are our own kernel implementation (`SweetSurface.{h,cpp}`, sweet patch 0046 and later):
`sweet_surface_copy(id)` returns the surface with its `IOMemoryDescriptor *memory` (kernel buffer, wrapped client
memory, topaz scanout pool or the panel's physical window).

### Mesa: `mesa/darwin/` → `mesa/patches/0001-freedreno-darwin-backend.patch`

Mesa 26.2.5. `mesa/darwin/apply.py` writes everything into a Mesa tree; `tools/g2/mkmesa.sh` turns that into
the single patch CI applies. Contents:

- `src/freedreno/drm/darwin/` (`darwin_*.c/h`): freedreno's kernel backend over the SweetGPU user client
  (IOKit declared by hand: the iPhoneOS SDK has the library, not the headers). On Darwin a
  `WINSYS_HANDLE_TYPE_FD` handle is an **IOSurface id** (`bo_from_dmabuf` → selector 6).
- `include/darwin-drm/xf86drm.h`: libdrm stand-in.
- `sweetgpu_fdtest` (gallium-level test: clear, triangle).
- `src/gallium/frontends/sweetgl/`: **sweetgl**, our GL ES frontend (st/mesa without EGL/DRI, modelled on Haiku's
  hgl). API in `sweetgl.h`: `sgl_display_create`, `sgl_context_create(dpy, es_major, share)`,
  `sgl_surface_create` (offscreen RGBA8 + depth/stencil), `sgl_surface_create_iosurface` (render into an
  IOSurface), `sgl_tex_image_iosurface` (texture from an IOSurface, via `st_context_teximage`),
  `sgl_make_current`. Public GL ES entry points (`glClear`...) are compiled into it from
  `gen_gldispatch_mapi.py glesv2`. Visual is single-buffered FRONT_LEFT; `flush_front` is a no-op.
- `sweetgpu_gltest`: GL ES 2 calls, 6 steps, checks every pixel, prints `PASS: all`.

CI (`.github/workflows/xnu.yml`, job `mesa`, `-f build=mesa`) cross-builds with `mesa/ios-arm64.ini` and
`-Dgles2=enabled`, signs both test binaries ad hoc, artifact `mesa-ios`.

## 4. How to work

**Kernel change:** edit in WSL `~/xnu-8796` (the full patched tree, one commit per patch, HEAD = j0032),
commit, `git format-patch -1 --stdout > ".../ios-jasmine/xnu/patches/j00NN-jasmine-<name>.patch"` (next number:
j0033), commit + push the patch, then
`gh workflow run xnu.yml -R telegdyd/ios-jasmine --ref jasmine` (artifact `xnu-kernel`, ~5 min). There is no
local XNU compiler; CI is the compile check, so read your diff carefully.

**Mesa change:** edit `mesa/darwin/`, then `wsl bash tools/g2/mkmesa.sh` from the repo directory (regenerates
the patch), `wsl bash tools/g2/mesahost.sh -k 0 src/gallium/frontends/sweetgl/sweetgpu_gltest` for a quick Linux compile
check (darwin backend and `__APPLE__` code are not compiled there), commit + push, then
`gh workflow run xnu.yml -R telegdyd/ios-jasmine --ref jasmine -f build=mesa`.

**Phone round:** `bash tools/g2/gpu-round.sh KERNEL_RUN MESA_RUN TAG` (Git Bash; `-` as KERNEL_RUN reuses
`xnu/out-jasmine-TAG` and its image). It waits for both runs, downloads them, builds
`shim/out/shim-boot-TAG-gpu.img` (`tools/g2/mkimg.sh`), boots it (`tools/sweet-run.py`: reboots a running
kernel over the command port into fastboot, `fastboot boot`, records the live log), waits for
`SweetGPU service published` and sweetd, pushes the binaries (`tools/sweet-fs.py put`) and runs them
(`tools/sweet-sh.py`). `BINS=` and `SECS=` override. Run it in the background; a round takes 3-4 minutes after
the builds. Phone over USB Ethernet at 169.254.7.2 (or 192.168.7.2): 5140 live log, 5141 commands (`reboot`),
5142 file service, 5143 sweetd. A hung phone needs power + volume down.

**Pitfalls seen:** set `MSYS_NO_PATHCONV=1` in Git Bash; Git Bash heredocs and sed mangle backslashes (a `\n`
in a C string became a real newline and broke the j0032 build): write files with an editor tool or a Python
script file; Python on Windows needs `newline='\n'`; `wsl bash /mnt/c/...` paths need `MSYS_NO_PATHCONV=1`.

**Research tools (WSL):** blacktop `ipsw` 3.1.739 in `~/ios-work/tools`, the iOS 16.7.16 IPSW in
`~/ios-work/ipsw`, its dyld shared cache in `~/ios-work/gl/dsc/`, earlier dumps in `~/ios-work/gl/out/`
(OpenGLES, GLEngine, AppleMetalGLRenderer, QuartzCore strings and symbols, `qc.s` = QuartzCore disassembly).
`ipsw dyld xref` ran out of memory before; prefer `ipsw dyld disass --image X` and grep.

## 5. Next steps, in order

> **Update 2026-10-21 ~23:00:** [joranv1/ios-sailfish](https://github.com/joranv1/ios-sailfish) (Pixel 1,
> Adreno 530) runs CoreAnimation on freedreno by our route 2. GPU.md "G2 comparison with ios-sailfish" lists
> what CA needed there and **replaces steps B-D below with its four next steps** (j0033 kernel prerequisites,
> their EAGL layer ported onto our sweetgl, backboardd via the `sweetenv` boot-arg). Step A is done.
> **2026-10-21 23:39: its step 1, kernel j0033, passed on the phone** (GPU.md "j0033 result"). Round scripts now
> take `EXTRA_ARGS` (boot-args), `IOS_RUN` (ios-tools) and `PUSH`, and keep test output in `LOG.tests`;
> `tools/g2/ci-wait.sh` re-runs CI jobs no macOS runner picked up. Phone state: running the j0033 test image.
> **Step 2 brief for the next agent: [HANDOFF-G2-STEP2.md](HANDOFF-G2-STEP2.md).**

### Step A: decide how CoreAnimation reaches our GL (research only, nothing on the phone)

**Done 2026-10-21 ~22:00**: results and recommendation (route 2, EAGL on sweetgl, tested first through CARenderer
in a standalone program) in GPU.md "G2 step A"; the route still needs the user's confirmation. What follows is the
original brief.

OpenGLES.framework lives in the dyld shared cache, so a replacement file on disk is ignored. Two routes:

1. **Renderer plugin (G0.1):** OpenGLES matches the IOKit class `IOAcceleratorES` and loads
   `/System/Library/Extensions/<IOGLESBundleName>.bundle` when `IOGLESDefaultUseMetal` is false. A kernel-published
   service plus our bundle on disk, no iOS binary patched. Cost: our bundle must implement Apple's private
   `gld*` interface (133 functions, list in `gld-symbols-ios16.txt`) under Apple's GLEngine front end.
2. **Interposition in backboardd:** a dylib injected into backboardd only (DYLD_INSERT_LIBRARIES via its launchd
   plist; needs the user's OK since it changes the root) that interposes the `gl*` functions and EAGL methods
   CoreAnimation uses and routes them to sweetgl. Interface is ours and possibly much smaller.

Deliverables: (a) the exact list of OpenGLES symbols QuartzCore imports (functions and ObjC classes/selectors:
`EAGLContext`, `renderbufferStorage:fromDrawable:`, `presentRenderbuffer:`, `texImageIOSurface:...`), and which
of them the GLES renderer (`gles_new_context`, `ogl-renderer.cpp`, `rendererWithEAGLContext:options:`) really
calls; (b) how QuartzCore chooses the GLES renderer over Metal and the software one (`CA_ENABLE_OGL`,
`CA_DISPLAY_TYPE`, Metal device presence, `IOAcceleratorES`); (c) the `gld*` signatures actually used by GLEngine,
from AppleMetalGLRenderer and GLEngine disassembly; (d) a recommendation with sizes. Write it into GPU.md and
**bring the route decision to the user before touching the iOS root.** HackiOS/topaz took a GL route on Adreno 610
(`git fetch topaz` and check whether they published their CA side; it would be largely reusable).

### Step B: kernel prerequisites (j0033), independent of the route

- **Row alignment:** freedreno a5xx needs bytes per row in multiples of 256 (64 px x 4 B); SweetSurface aligns to
  64 (`SWEET_SURFACE_ROW_ALIGN`, also reported to IOSurface.framework by limits selector 13 at +0/+4). A 1125-wide
  BGRA surface gets 4544 and `resource_from_handle` refuses it. Raise to 256 (the topaz direct scanout and the CPU
  copy path both take any pitch; check scanout's 16-byte alignment rule still holds) and test that the UI still
  shows normally.
- **GPU VA reuse:** `sweet_gpu_vm_alloc` is a bump allocator (28 GiB). A renderer that creates and frees surfaces
  for hours runs out. Add a free list (or a simple range allocator) and free on buffer free.
- **Cache maintenance cost:** every submit/wait/completed cleans+invalidates every buffer of the client. With
  full-screen surfaces (11 MB each) this will dominate. Options: flush only buffers referenced by the job (needs
  a BO list in submit, like msm), track dirty state, or get write-combined user mappings of kernel-cacheable pages
  working (the panic was XNU changing cache attributes of a page outside managed RAM; see GPU.md j0028-j0031).
- Optional: wrapped IOSurfaces whose memory starts inside a page (selector 6 returns the offset; Mesa refuses
  non-zero offsets today, `darwin_bo_from_iosurface`).

### Step C: EAGL on sweetgl

Whatever the route, implement the EAGL behaviours CA needs on top of sweetgl: context create/share/current,
renderbuffer storage from a CAEAGLLayer drawable as an IOSurface (`sgl_surface_create_iosurface`), present
(flush + hand the IOSurface to CA/IOMFB), `texImageIOSurface` (`sgl_tex_image_iosurface`). sweetgl will need a
per-thread current context lookup and probably GL ES 3.0 reporting (iOS tops out at 3.0; Mesa offers 3.1).
Test with a small standalone app first (a CAEAGLLayer, or a program that draws into IOSurfaces and swaps them
through IOMobileFramebuffer), run via sweetd.

### Step D: backboardd

Switch CA's render server to the GLES renderer and run it on the GPU. Expect shader compile time on first frames
(no shader cache: `-Dshader-cache=disabled` on the host build; check the iOS build) and missing GL features to show
up here. Turn `sweetgpu_debug` off for any speed judgement (it sleeps 150 ms per log line).

### Later (open items from earlier sessions, details in GPU.md / NOTES.md)

GPU interrupts instead of polled fences; RPM CX vote and higher GPU clocks (now 266 MHz); VBIF halt before GPU
power-off; an unexplained SMMU CB0 FSR 0x400 seen during bring-up; the panic buffer section came out empty in
the j0030 panic test; implicit sync between processes sharing a surface (`darwin_bo_cpu_prep` is a no-op);
README not yet updated for G2. Outside G2: faster USB, CPU DVFS and all 8 cores, Wi-Fi.

## 6. Files

| Path | What |
| --- | --- |
| `jasmine/GPU.md` | Plan, research, dated G2 log (read the G2 section) |
| `jasmine/NOTES.md` | Project state; kernel patch list (j0031/j0032 lines) |
| `jasmine/gld-symbols-ios16.txt` | The 133 `gld*` names |
| `xnu/patches/j0026..j0032-*.patch` | SweetGPU kernel driver |
| `mesa/darwin/`, `mesa/patches/0001-*.patch` | Mesa backend, sweetgl, tests (source and generated patch) |
| `mesa/ios-arm64.ini`, `.github/workflows/xnu.yml` | Cross build |
| `tools/g2/` | `gpu-round.sh`, `fdtest-round.sh`, `mkimg.sh`, `mkmesa.sh`, `mesahost.sh` |
| `tools/sweet-{run,fs,sh,cmd,netlog}.py` | Phone access |
| `logs/netlog-j3*-*.txt` | Logs of the G2 rounds |
| WSL `~/xnu-8796`, `~/ios-work/mesa` (+ `build-host`), `~/ios-work/venv`, `~/ios-work/gl` | Working trees and research data |
