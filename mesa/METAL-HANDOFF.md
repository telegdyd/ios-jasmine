# Handoff: Metal on jasmine (Chlorophyll on the Adreno 512)

Written 2026-10-31 for the agent that starts the port. Scope: get iOS 16.7's Metal clients (CoreAnimation, apps) drawing
on the Adreno 512 through Chlorophyll, the Metal driver of Bergamota (iOS 18, Poco F1, Adreno 630). Read this, then
[METAL-PORT.md](METAL-PORT.md) (the call-site map: every place Chlorophyll depends on Bergamota's kernel, on a6xx or on
iOS 18), then the top of the root [NOTES.md](../NOTES.md) and `AGENTS.md` for the project rules. Chlorophyll's own
[README](metal/README.md) and [docs/FIXES.md](metal/docs/FIXES.md) explain what it does and which CA bugs it already hit.

## 1. Why this route

Chlorophyll translates AIR (the shader IR inside `.metallib` files) to NIR, compiles it with freedreno's ir3 and implements
the Metal API over Gallium freedreno. freedreno supports a5xx and already drives our GPU (libsweetca, CoreAnimation's GLES
renderer, installed as production). The other 6xx route we read, ios-flame (metal2vulkan on Turnip), needs Vulkan,
and Mesa has no Vulkan driver for a5xx. Chlorophyll is also the more mature one: about 41 fps in its swipe test,
backboardd/SpringBoard/apps on the GPU.

## 2. Where things stand (2026-10-31)

**Step 2 completed on the phone:** [METAL-STEP2.md](METAL-STEP2.md).
Parent commits `24da65e` / `a1a360f`: rounding and narrow SSBO fixes validated
on a512; shift-split patch unnecessary in Mesa 26.2.5. Eight focused GPU probes
PASS, GLES/glthread/framebuffer-read comparisons exact after each shared
change, temporary UI boots normal with no fault/panic/ticket/crash lines.
Final local VM `metal-s2final` passes six mandatory AIR compile probes.
QuartzCore coverage is now 111/141 (seven register-width failures fixed).
Production renderer and boot_b unchanged; phone parked in charging shell,
69%, Charging. User authorized work through step 2 only: stop here. Step 3's
table exists; next runtime task is step 4 (libbgair/SweetGPU compute).
The following entries describe earlier milestones.


**Further offline milestone:** [METAL-OFFLINE.md](METAL-OFFLINE.md).
Chlorophyll `0e2de69` pushed: native macOS AIR/a512 compiler, probes and corpus
runner. VM `metal-host7` passes its offline checks. All 141 QuartzCore functions
from cached iOS 16.7.16 20H392 tested: 104 compile, 33 ir3 failures (20 are
explicit framebuffer-fetch refusals), 4 frontend failures. Two CoreImage
libraries: 100/133 compile. Inputs/tables in ignored research storage; no phone
access, no shared ir3 edits. Step 2 audit found the old shift-splitting rewrite
absent; rounding/narrow accesses still need investigation and device validation.

**Update: step 1 completed offline**, see [METAL-STEP1.md](METAL-STEP1.md).
Chlorophyll local commit `ff309fc` adapts AIR to Mesa 26.2.5; patches 0017/0018
and the local build integration compile the frontend and runtime C for iOS arm64.
VM `metal-s1e`: existing outputs pass, libsweetca byte-identical to production;
libbgair link still lacks three documented backend symbols. No phone access.
User requested stopping before device access: stop before step 2's regression
checks. Fork push was explicitly authorized by the user and `ff309fc` is now on
origin/adreno5xx; the parent pointer is recorded in the publication milestone. The following bullets describe
the original starting state, not the completed step 1.

- Fork: https://github.com/telegdyd/Chlorophyll. `main` = upstream ry-diffusion/Chlorophyll @ `787338f`; our work goes on
  branch **`adreno5xx`** (same commit, **no changes yet**, pushed). Remote `upstream` is set in the local clone.
- Checked out as submodule **`mesa/metal`** on `adreno5xx`, clean. Its nested submodules `mesa` (25.0.7) and `libdrm`
  (2.4.124) are **deliberately not initialised**: we build against our Mesa 26.2.5 + `mesa/patches` tree. Do not run
  `git submodule update --recursive`.
- Nothing built, nothing run on the phone. Read-only findings so far (details in METAL-PORT.md):
  - all 9 Chlorophyll Mesa patches fail `git apply --check` on 26.2.5;
  - a5xx has no framebuffer fetch (`caps->fbfetch` = 0), which CA's rounded-corner/SDF shaders use (our GL path
    already emulates it, step 5);
  - our `xf86drm.h` stub's `drmOpenWithType` returns -ENODEV; SweetGPU has no cache-sync selector;
  - every private iOS 18 Metal class/initialiser `src/bgmtl.m` subclasses exists in iOS 16.7 with the same superclass;
    `MTLCopyAllDevices` is not exported on 16.7; the plugin route (`IOAcceleratorES` -> `MetalPluginName` bundle)
    matches, and our kernel patch 0138 already publishes an empty `IOAcceleratorES`.

## 3. Ground rules (from AGENTS.md / the user)

- Chlorophyll code changes: commit on `adreno5xx` **inside `mesa/metal`**, push to the fork (`origin`), then commit the
  bumped submodule pointer in ios-jasmine (branch `jasmine`). Keep `NOTICE.md` / `LICENSE.hackios-userland` and the
  per-file notices; mark our changes "jasmine" like Chlorophyll marks its own.
- Build on the local macOS VM (`tools/vm-mesa.sh mesa TAG` -> `xnu/out-mesa-TAG`), not CI. It tars `mesa/` (the
  submodule included) and builds uncommitted edits. One build at a time (shared lock). CI only if `ssh mac true` fails.
- The phone: temporary `fastboot boot` images and test binaries/libraries in `/usr/local/bin` are fine. **Ask the user
  before** installing anything in the iOS root outside `/usr/local/bin` (a bundle in `/System/Library/Extensions`,
  launchd plists), changing what the installed boot_b loads, or replacing production `libsweetca.dylib`.
- libsweetca is production. Anything that changes shared Mesa code (ir3 patches, BO cache) must leave libsweetca's
  output unchanged: run `sweetgpu_gltest` (pixel-exact) and a UI round before calling a step done.
- Apple files (metallibs, extracted frameworks, dumps) go in `research/` (git-ignored), never in git.
- Update the active handoff in root `NOTES.md` after each step: commits (both repos), build tags, exact results, log
  files. Say what is measured and what is guessed.
- The phone CPU is ARMv8.0 (no PAC): build **arm64**, not arm64e as Chlorophyll's scripts do (`plugin/build.sh`,
  `build-ios.sh`), and `-mios-version-min=16.0` (our `mesa/ios-arm64.ini`).

## 4. Steps

Each step ends in something checkable. Do them in order. Step 1 needs no phone;
step 2's required GL/UI regression checks need the phone after each shared ir3
change. Step 3's shader compilation is offline if metallibs are already available.

### Step 1: get the AIR front end into our Mesa build

- Decide where forward-ported Chlorophyll patches live. Suggested: as numbered files in `mesa/patches/` (after 0016),
  so `tools/mesa-local.sh` applies them like ours, with the original Chlorophyll patch name in the file name. Keep
  Chlorophyll's `patches/` untouched (they target 25.0.7).
- Copy (or symlink, as Chlorophyll's `build-host.sh` does) `mesa/metal/air/*` into the stage tree's
  `src/compiler/air/` in `mesa-local.sh`, after the patch loop and before the rsync into `mesa-src`.
- Forward-port `air-frontend` (only `src/compiler/meson.build` context moved) and the build-target part of `air-ir3`
  (`air2nir`, `libbgair` shared library in `src/gallium/drivers/freedreno/meson.build`; `ir3_cmdline.c` moved in
  26.2.5, find its new path).
- Done when: `tools/vm-mesa.sh mesa TAG` still builds the existing outputs and `air_metal.c` / `air_to_nir.c` compile
  for iOS arm64 (link errors in libbgair are fine at this point; list them).

### Step 2: the ir3 patches, one at a time

- `ir3-round-default`, `ir3-shift-split`, `ir3-ssbo-subdword`: for each, check whether 26.2.5 already fixes it, port
  what is still needed, and say which AIR construct needs it (read the patch's comment and FIXES.md).
- These change ir3 for libsweetca too. After each: `sweetgpu_gltest` all pixel-exact, and the shader output for
  libsweetca unchanged (compare `ir3` disassembly of a few CA programs, or a UI round with a screenshot vs the last one).
- Skip for now: `fd6-fb-barrier-reorder` (a6xx file; the a5xx equivalent question is our patches 0008/0016) and the
  three `fd-bo-*` patches (workarounds for Bergamota's 4096-GEM-handle kernel limit; revisit only if SweetGPU shows
  the same failure).
- Done when: all three are ported or shown unnecessary, libsweetca unchanged.

### Step 3: compile iOS 16's real shaders off the device

- Pull the metallibs: QuartzCore's and a few system ones (CoreImage, SpringBoard's) from the phone or the iOS 16.7
  root image, into `research/metallib/`. AIR/metallib versions of iOS 16 files were never checked (METAL-PORT.md 4).
- Build `air2nir` (and `ir3_compiler` with the AIR input from `air-ir3`) for the macOS VM host, targeting gpu id 512.
  Chlorophyll's `build-host.sh` is the recipe (it targets a630; ours needs no libdrm stand-in if the host build can
  use the darwin backend or a null one; untested).
- Done when: a table of every QuartzCore function -> NIR ok / ir3 (a512) ok / failure reason. This is the real
  size of the a5xx gap; expect framebuffer-fetch shaders (`[[color(n)]]` reads) to fail.

### Step 4: libbgair on the device (compute first)

- Replace the libdrm stand-in in `air/air_metal.c` with our darwin backend (METAL-PORT.md section 1 has every call site):
  - `drmOpenWithType` + `fd_drm_screen_create_renderonly` -> `open("/dev/null")` + `fd_screen_create(fd, &config, NULL)`,
    as `mesa/darwin/sweetgl/sweetgl.c:100-106`;
  - `sweet_drm_surface_bo` / `WINSYS_HANDLE_TYPE_KMS` -> `WINSYS_HANDLE_TYPE_FD` with the IOSurface id, as
    `sweetgl.c:291`, pitch/size/format from `IOSurfaceGet*`, offset as `sweetca.c:2574`;
  - `sweet_drm_bo_sync` -> no-op first; test for stale pixels (open question below);
  - `fd_mesa_debug` must be exported from our build.
- Add `libbgair.dylib` and Chlorophyll's `test/bgair_test.c` (compute kernels from `test/bg_kernels.metal`) to the
  `mesa` mode of `tools/mesa-local.sh`, signed like `sweetgpu_gltest`.
- Run it on a temporary boot through sweetd (`tools/g2/fdtest-round.sh` pattern: push from `xnu/out-mesa`, run, log).
- Done when: compute kernels give correct results on the Adreno 512, no SMMU fault/panic, log in `logs/`.

### Step 5: the Metal device (`src/bgmtl.m`) in a test process

- Fix the a6xx assumptions (METAL-PORT.md section 3): pitch alignment 64 (`bgmtl.m:514`), `registryID` 0x10000b630,
  UBO alignment 64, `fd6_*` queries, MSAA/Z format refusals, compute thread limits; images/SSBOs share 24 slots on
  a5xx. Prefer querying the screen over new hardcoded numbers.
- Framebuffer fetch: a5xx has no hardware fbfetch, but **libsweetca already solves the same problem for CA's GL path**:
  sweetca (in `mesa/patches/0001-freedreno-darwin-backend.patch`, search `OBJ_FBFETCH` / `fbfetch_unit`) rewrites
  `gl_LastFragData[0]` into a read of the render target's own texture on the last texture unit (nearest sampler,
  level 0), and the feedback barrier between the writing and the fetching draw is our patches 0008/0016
  (`SWEETCA_SYS_BARRIER`, default on). GMEM reads of the tile also work (0013, default off, did not pay). Do the
  same for AIR: lower the `[[color(n)]]` read to a texel fetch of the attachment, bound as a texture, and issue the
  same barrier. That is also how Chlorophyll's a6xx sysmem path reads it (FIXES.md "Black corner wedges",
  "Control Center blur"). Background: `jasmine/PERF-GMEM-FBREAD-20261030.md`, NOTES.md 2026-10-30 23:40.
- Build a libbgmtl/test target and run Chlorophyll's probes in a plain test process, not backboardd:
  `bgmtl_probe`, `bgmtl_quad_probe` (also checks provoking vertex), `bgmtl_render_probe`.
- Done when: the probes pass on the phone.

### Step 6: registering the device

- Test process first: `inject/bgmtl_inject.m` with `MTLCreateSystemDefaultDevice` instead of the missing
  `MTLCopyAllDevices` (`:341`, `:389`), loaded with `DYLD_INSERT_LIBRARIES`; replace Renegade's `bgmtl` flag and
  `/private/var/tmp/bgmtl-bb.*` gating with our sweetenv / boot-args.
- Plugin route (later; root change, ask the user): kernel publishes `MetalPluginName` / `MetalPluginClassName` on our
  `IOAcceleratorES` behind a boot-arg (Bergamota's xnu 0232 equivalent), bundle from `plugin/` in
  `/System/Library/Extensions`.
- Done when: `MTLCreateSystemDefaultDevice()` returns our device in a test process and a probe draws through it.

### Step 7: backboardd on Metal

- Find what makes iOS 16 QuartzCore pick its Metal renderer (`metal_new_context`) over GLES ([GPU.md](../jasmine/GPU.md)
  G0.1 has the GL side), and whether libsweetca and libbgair can share one Mesa screen / SweetGPU device in one process
  (METAL-PORT.md section 5; build both from the same tree).
- Temporary boot with a `sweetenv=backboardd:...` boot-arg; compare against the GLES renderer with the existing UI
  rounds (`tools/g2/uiround.sh`, `uibench.py`) and screenshots (`sweet_shot`).
- Done when: lock and home screen draw through Metal, with frame times measured against the GLES path. Making it
  the default needs the user's OK.

## 5. Open questions (unverified)

- Is our IOSurface import CPU/GPU coherent, or does Metal's `synchronizeResource`/`replaceRegion` need a SweetGPU
  cache-sync selector (Chlorophyll calls `sweet_drm_bo_sync` at `air_metal.c:1741`, `:1831`)? libsweetca never needed one.
- Framebuffer-fetch cost on a5xx under Metal: in GL, CA needs 33 (Home) to 45 (CC) feedback barriers a frame, all
  fetches (NOTES.md 2026-10-30 23:40); Metal's CA renderer may issue a different number.
- iOS 16 metallib/AIR versions: `air_metallib.c` refuses nothing on version, but the AIR intrinsics may differ.
- Unknown SPI methods iOS 16 QuartzCore sends: `bgmtl.m` answers unknown selectors with zero and logs them; collect
  the log in step 6/7.
