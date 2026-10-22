# Brief: G2 step 2, CoreAnimation's GL renderer on our sweetgl (libsweetca)

Written 2026-10-21 ~23:50 for the agent doing step 2. Scope is **step 2 only**: a library that makes
CoreAnimation's own OpenGL ES renderer run on Mesa freedreno, proven in a standalone test program on the phone.
Putting it into backboardd is step 3 and is **not** part of this task.

Read first, in this order:

1. [HANDOFF-G2.md](HANDOFF-G2.md) §2 (ground rules) and §4 (how to work: kernel/Mesa CI, phone rounds, pitfalls).
   The rules there are the user's and apply unchanged.
2. [GPU.md](GPU.md): "G2 step A" (how CA reaches GL), "G2 comparison with ios-sailfish" (what CA needs beyond
   plain GL ES, learned the hard way on a Pixel 1) and "j0033 result" (the kernel you build on).
3. [ca-gles-calls-ios16.txt](ca-gles-calls-ios16.txt): the 60 GLI dispatch entries QuartzCore calls, with callers.

## 1. Where things stand (2026-10-21 23:39)

- **Kernel j0033** (CI run `39668634610`, artifact `xnu-kernel`) on the phone, booted with `fastboot boot` from
  `shim/out/shim-boot-j33-gpu.img`. SweetGPU user client: buffers, submit, fences, IOSurface import (selector 6).
  GPU faults are not reported to the GPU (logged as `SWEET GPU: SMMU fault before ...`), each buffer has a 128 KiB
  scratch pad after it, and freed GPU VAs are reused.
- **Mesa 26.2.5 for iOS** (`mesa/darwin/` → `mesa/patches/0001-freedreno-darwin-backend.patch`, CI `-f build=mesa`,
  last good run `39661351032`): freedreno over our `darwin` backend, and **sweetgl**, our GL ES frontend
  (`mesa/darwin/sweetgl/sweetgl.h`: `sgl_display_create`, `sgl_context_create(dpy, es_major, share)`,
  `sgl_surface_create_iosurface`, `sgl_tex_image_iosurface`, `sgl_make_current`). `sweetgpu_gltest` passes every
  step, including rendering into an IOSurface and sampling one as a texture.
- **Injection works** (`sweet_envtest` PASS): the boot-arg `sweetenv=NAME:VAR=VAL[,...]` adds environment variables
  to one executable by file name, and dyld honours `DYLD_INSERT_LIBRARIES`. Not needed for step 2 (see §3).
- **Not done:** anything between EAGL/CoreAnimation and sweetgl. CA on the phone still draws on the CPU.

## 2. The task

Build **`libsweetca.dylib`**: Mesa (freedreno + st/mesa + sweetgl) plus an EAGL layer, one dylib, built by the Mesa
CI job next to the existing tests. When loaded into a process it makes `EAGLContext` hand CoreAnimation sweetgl
contexts, so CA's built-in GLES renderer (`CA::OGL::GLESContext` + `OGL::Renderer`) runs on the Adreno 512.

### 2.1 What the EAGL layer must do (from step A; see GPU.md for addresses and callers)

CA never calls the exported `gl*` functions. It gets `{GLIContext rctx; dispatch[1036]}` from
`-[EAGLContext getMacroContextPrivate]` and calls `disp[n](rctx, args...)`. So:

- Replace, with the ObjC runtime at load (a constructor), these methods for contexts you create, and forward
  everything else to Apple's originals: `-initWithAPI:properties:`, `-dealloc`, `-API`, `-setParameter:to:`,
  `-getMacroContextPrivate`, `-texImageIOSurface:target:internalFormat:width:height:format:type:plane:invert:`,
  `-attachImage:toCoreSurface:invertedRender:`, `+setCurrentContext:`, `+currentContext`.
- `initWithAPI:3` must succeed and `-API` must return 3: backboardd only uses CA's GL renderer for an ES 3 context
  (GPU.md step A). Make it a GL ES 3.1 Mesa context: sailfish found CA's rectangle-texture emulation needs
  `glGetTexLevelParameteriv`, which is 3.1.
- **The 1036-entry dispatch table.** Slot layout: GLEngine's `gliInitDispatchTable` (each entry stored as
  `add xR, ..., _glName_Suffix` then `str xR, [xB, #off]`, index = off/8). Generate it from **our** shared cache
  (iPhone X, `~/ios-work/gl/dsc/`, tools in [tools/g2/dsc](../tools/g2/dsc/README.md)), not from sailfish's
  `ios-dispatch.txt` (iPhone 8 cache). The entries spot-checked so far agree (index 5 `glBindTexture`), but check all
  of them. Every slot gets a wrapper that makes `rctx`'s context current if it isn't, then calls Mesa's entry point;
  slots with no Mesa function log their index once and return 0. A few need hand-written versions (ARB object
  calls, `glGetString`, Apple fence/object calls, `glFlush`).
- **IOSurfaces as textures**, zero copy, through what sweetgl already does (`sgl_tex_image_iosurface`, darwin backend
  `bo_from_dmabuf` with the IOSurface id). `attachImage:` binds a display surface onto the currently bound
  `GL_TEXTURE_2D`, then CA builds an FBO on that texture. One Mesa resource per IOSurface (sailfish: otherwise
  render-then-sample through two GL textures is not ordered).

### 2.2 What CA needs beyond plain GL ES (sailfish's findings; each cost them a boot)

- Mesa environment before the screen is created: `FD_MESA_DEBUG=sysmem,nofp16`, `IR3_SHADER_DEBUG=nofp16`
  (GMEM tile load/store overran unpadded IOSurfaces; fp16 lowering broke CA's shaders).
- `GL_TEXTURE_RECTANGLE` emulation: rect targets become 2D, `sampler2DRect` shaders rewritten with a per-draw texel
  scale; separate 2D and rect bindings per texture unit.
- `GL_EXT_shader_framebuffer_fetch` emulation (CA drops blend-mode layers without it): rewrite the shader to sample
  a copy of the framebuffer texture; texture barrier before draws that sample their own render target.
- CA's "format 0" 32-bit images are A,R,G,B in memory: bind as RGBA with a swizzle.
- QuartzCore's GL renderer lacks three texture functions (0x14 colour matrix without premultiply, 0x2d vibrant
  colour matrix, 0x26/0x27 variable blur). sailfish fills QuartzCore's `tex_fragment_shaders` table and
  `create_shader`'s per-function uniform switch at load. **Their addresses are for the iPhone 8 cache and do not
  match ours.** Find both tables in our QuartzCore (`~/ios-work/gl/out/qc.s`; the table's entry 0x13 is the string
  `"colorMatrix4x4Bias(s0)"`), check the expected contents before writing, and refuse to patch on any mismatch.
  This can come last: without it only the lock-screen clock, some Control Center plates and the notification centre
  blur are wrong.
- a5xx pitch: allow 64-byte-aligned linear pitch on import in `fd_layout_resource_for_handle` (sailfish's
  `mesa.patch` does this for `__APPLE__` + a5xx) instead of raising the kernel's IOSurface row alignment.
- IOSurface row bytes: our kernel takes an explicit `IOSurfaceBytesPerRow` as given. If CA asks for rows the GPU
  cannot use, find out from real requests what it asks for before changing the kernel; sailfish's rule ("more than
  six properties means CA") is a heuristic, and the user prefers root-cause fixes.

### 2.3 The test (definition of done)

A standalone ObjC test program, **`sweetca_test`**, built in the Mesa CI job and linked against libsweetca directly
(no boot-arg, no reboot needed to load it), run through sweetd:

1. `[[EAGLContext alloc] initWithAPI:3]` returns one of our contexts, `-API` == 3.
2. `+[CARenderer rendererWithEAGLContext:options:]` (builds the same `GLESContext` + `OGL::Renderer` as backboardd)
   renders a small layer tree into a BGRA IOSurface: a solid background, a layer with an image as `contents` (a
   CGImage: the `IOSurfaceAddress` path), corner radius + `masksToBounds`, partial opacity, a sublayer transform, and
   a `CATextLayer`.
3. The reference is the same tree drawn by CA on the CPU (`-[CALayer renderInContext:]` into a `CGBitmapContext`).
   Compare per pixel with a tolerance; print the number of differing pixels, a few sample pixels, and
   `PASS`/`FAIL` lines like the other tests. Read the GPU result straight from the IOSurface's memory
   (`IOSurfaceLock`), which is how the display will see it.
4. No `SWEET GPU: SMMU fault`, hang or panic in the kernel log during the run.

**Done** = `sweetca_test` prints `PASS` on the phone, the results are written down (§4), and everything is committed
and pushed. Partial results (some layer types wrong) are worth recording too: say exactly which, with pixel values.

## 3. Constraints

- **Licence.** Neither ios-sailfish nor ios-sweet has a licence file, and the user has not decided yet whether to ask
  the sailfish author. Until a note in [NOTES.md](NOTES.md) says otherwise: **write our own code.** Using
  sailfish's repo (`github.com/joranv1/ios-sailfish`, `tools/sweetgl/`) to learn what CA needs is fine; copying its
  source is not. Credit their findings in comments and docs, as GPU.md does.
- **Phone rules** (HANDOFF-G2 §2): `fastboot boot` of test images is fine; writing test binaries and libraries to
  `/usr/local/bin` is fine; **anything else on the iOS root (`/usr/lib`, launchd plists, frameworks) needs the user's
  OK first.** Step 2 needs none of that. Do not flash partitions. Do not set up launchd jobs.
- **No injection into backboardd in this task**, not even with the `sweetenv` boot-arg: that is step 3, which
  the user approves separately.
- Prefer root-cause fixes. Kernel changes, if needed, go in as `j0034+` patches, built by CI.
- Keep Apple binaries, shared-cache dumps and device data out of git.

## 4. How to work and report

- Workflow (HANDOFF-G2 §4): Mesa changes in `mesa/darwin/`, `wsl bash tools/g2/mkmesa.sh` regenerates the patch,
  `wsl bash tools/g2/mesahost.sh ...` compile-checks on Linux first (darwin/`__APPLE__` code is not compiled there),
  then `gh workflow run xnu.yml -R telegdyd/ios-jasmine --ref jasmine -f build=mesa`. The ObjC test needs the iPhoneOS
  SDK frameworks (QuartzCore, OpenGLES, CoreGraphics, IOSurface, Foundation): add them to the Mesa job's meson build
  for Darwin, as `sweetgpu_gltest` does for IOSurface.
- GitHub's macOS arm64 runners were unavailable for about 45 minutes on 2026-10-21; wait for runs with
  `bash tools/g2/ci-wait.sh RUN...`, which re-runs jobs that no runner picked up.
- Phone round without a new kernel:
  `BINS="sweetca_test" bash tools/g2/gpu-round.sh - MESA_RUN j33 logs/netlog-s2-NAME.txt` (reuses
  `shim/out/shim-boot-j33-gpu.img`; **always pass the 4th argument**, the default log name would overwrite the
  committed j0033 log). Test output goes to `LOG.tests`, the kernel log to `LOG`. Use your own TAG for a new kernel. For a quick rerun on a phone that is already up:
  `python tools/sweet-fs.py put FILE /usr/local/bin/NAME --mode 755` and `python tools/sweet-sh.py /usr/local/bin/NAME`.
- Give long runs (CI, phone rounds) to background commands; do not poll.
- Record as you go: a "G2 step 2" section in [GPU.md](GPU.md) with dated results (clock times), CI run IDs, log files
  and what failed and why; a line at the top of [NOTES.md](NOTES.md); update [HANDOFF-G2.md](HANDOFF-G2.md) §1 and
  the phone state. Commit and push each milestone (trailer `Co-Authored-By: Claude Opus 5.5
  <noreply@anthropic.com>`; commits with `-c user.name=telegdyd -c user.email=telegdyd93@gmail.com`).
- When done, or blocked on something only the user can decide, stop and report: what passed, what did not, run IDs,
  log files, and the exact next step (step 3: libsweetca into backboardd via
  `sweetenv=backboardd:DYLD_INSERT_LIBRARIES=...`, which needs the user's OK because the library goes onto the root).

---

# Result of step 2 (2026-10-22 00:18 to 02:16): CA's GLES renderer draws on the Adreno 512, one defect left

Written 2026-10-22 ~02:20 by the agent that did the work. **Not done to the letter**: `sweetca_test` still prints
`FAIL` (2290 of 65536 pixels differ, 3.5%; the test wants at most 2%). Everything else in §2 works on the phone.
The user stopped the work at this point so that the next agent (Opus) can take the last defect.

## What exists (all committed and pushed on `jasmine`, last code commit `f39c2f4`, CI Mesa run `39698050816`)

| What | Where |
| --- | --- |
| `libsweetca.dylib`: EAGL layer + dispatch + emulations (about 1500 lines of C) | [mesa/darwin/sweetgl/sweetca.c](../mesa/darwin/sweetgl/sweetca.c) |
| 1036-slot name table and trap generator (names from our iPhone X cache) | `sweetca_slots.inc`, made by [tools/g2/dsc/genslots.py](../tools/g2/dsc/genslots.py); `glislots.py` reads GLEngine's `gliInitDispatchTable` |
| sweetgl additions: ES 3.1 contexts, `sgl_tex_image_iosurface_fmt` with one cached Mesa resource per IOSurface, `sgl_texture_barrier` | `mesa/darwin/sweetgl/sweetgl.{c,h}` |
| a5xx 64-byte pitch import (`fd_layout_resource_for_handle`, `__APPLE__` only) | `mesa/darwin/apply.py` |
| `sweetca_test.m` (ObjC; CI builds it with plain `clang`, Mesa's meson has no ObjC), meson `libsweetca` target | `mesa/darwin/sweetgl/` |
| One round: CI build + phone run | `bash tools/g2/s2round.sh NAME "message"` (commits, builds, runs on the j33 image, prints the test output) |

Output of each round: `logs/netlog-s2-NAME.txt` (kernel, only k and o kept) and `.tests` (test output). Letters a..o
are in time order (i3 is the third try of i). **No SMMU fault, hang or panic in any of the 15 rounds.** Debug mode
(150 ms per kernel log line) makes a render take 7 to 25 s; that is not GPU time.

### How it works (the design is final unless noted)

- A constructor replaces `initWithAPI:properties:`, `initWithAPI:`, `initWithAPI:sharegroup:`, `dealloc`, `API`,
  `setParameter:to:`, `getMacroContextPrivate`, `texImageIOSurface:...`, `attachImage:...`, `+setCurrentContext:`,
  `+currentContext` for our contexts (looked up by the EAGL object pointer); all other contexts go to Apple's code.
- `getMacroContextPrivate` returns `{rctx; disp[1036]}` (our struct). **Slot index = byte offset / 8 in GLEngine's
  table = (offset - 8) / 8 in the macro struct.** All 60 entries CA calls were checked against GLEngine's own
  `gliInitDispatchTable` in our cache (they agree); every other slot is a trap that logs its name once and returns 0.
  No unsupported slot was hit during the test.
- Environment set before the screen: `FD_MESA_DEBUG=sysmem,nofp16`, `IR3_SHADER_DEBUG=nofp16`.
- Emulated: rectangle textures (2D + rect bindings per unit, `sampler2DRect` rewrite with a per-draw scale),
  `gl_LastFragData` (reads the render target's texture on the last unit, texture barrier before the draw),
  `GL_EXT_shader_framebuffer_fetch` added to the extension string, the undeclared `coord_arg`, Apple ARB handles.
- QuartzCore texture-function fixes (functions 0x14, 0x26, 0x27, 0x2d): **our iPhone X cache has the same code as
  sailfish's iPhone 8 cache, 0x4000 higher** (create_shader's first four instructions are identical). Addresses:
  `tex_fragment_shaders` at `0x1d5b48a10`, create_shader's byte table at `0x18855e1e4` (entry of function 0x11).
  The library checks both tables and writes nothing otherwise. They install on the phone (log lines
  `texture function 0x.. = ...: installed`). **The new GLSL for them has not been exercised**: the test layer tree
  uses none of those functions. Env `SWEETCA_NO_TEXFNS=1` turns the patching off.
- Exported: `sweetca_installed()`, `sweetca_set_trace(n)` (1: first call of each slot + GL errors; 2: also shader
  sources, the first 60 draws, texture uploads, copies), `sweetca_set_flip(n)` (now unused).

## What passes on the phone (round o, `logs/netlog-s2-o.txt.tests`)

`[[EAGLContext alloc] initWithAPI:3]` gives our context (`OpenGL ES 3.1 Mesa 26.2.5, FD512`), `-API` is 3,
`getMacroContextPrivate`, `+setCurrentContext:`/`currentContext` work, a BGRA IOSurface binds as a texture in place
(no copy) and is the colour attachment of an FBO, `+rendererWithEAGLContext:options:` returns CA's renderer, and
rendering a 6-layer tree (background, CGImage, rounded masked layer with a child, 50% opacity, rotated sublayer,
CATextLayer) gives, against `renderInContext:` on the CPU (tolerance 8 per channel):

| Region | Differing pixels |
| --- | --- |
| background, opacity layer | 0 |
| text | 0 |
| rotated square (edge anti-aliasing) | 144 |
| image | 826 (quadrant edges and the diagonal, i.e. filtering) |
| rounded masked layer | **1320, the defect** |
| total | 2290 of 65536 |

Orientation is right without any flip: memory is top row first, which is what the display wants.
The test renders into the FBO the test binds itself (CA draws into whatever framebuffer is bound, like an app's);
`-[CARenderer setDestination:]` is not needed (see the table of tries).

## The remaining defect: black wedge at the four corners of the cornerRadius + masksToBounds layer

Character map of the layer from round o (sampled every 4 px; B black, O orange, R the red child, b background;
GPU left, CPU right, first rows):

```
bbbbbbb?RRRRRROOB?bbbbbb | bbbbbbbRRRRRRROOO?bbbbbb
bbbbBBBRRRRRRROOOBBB?bbb | bbbbRRRRRRRRRROOOOOO?bbb
bbbBBBRRRRRRRROOOOBBBBbb | bbbRRRRRRRRRRRROOOOOOOObb
```

The straight edges and the interior are right; between the background and the shape, in the corners, a band about
12 px wide is opaque black (a=ff) instead of the layer colour (the CPU reference has the layer colour nearly to the arc).

What CA does for this layer (`logs/netlog-s2-l.txt.tests` has the draw trace, `-m` the texture calls):

1. Draws 1, 2: background and image into the framebuffer (fbo 1, texture 1, 256x256).
2. `glTexImage2D(tex 3, RGBA 68x68, no data)`, then four `glCopyTexSubImage2D` of 34x34 from the framebuffer at the
   layer's four corners into the quadrants of tex 3 (the backdrop under the corners). **Read back in round n: the
   copies hold the right colour (214579ff = the background). The copies are fine.**
3. `glTexImage2D` of tex 4: **LUMINANCE_ALPHA** 256x256 with 9 mip levels, data from the client (the corner/edge
   coverage mask).
4. Draws 3 to 8: shader `color * texture2D(texture0, texcoord0_0)` with tex 4 and scissors over the layer's three
   bands, first with blend off, then on, 48 vertices each.
5. Draw 10: `mix(s1, d0, s0.a)` with s0 = tex 4, s1 = tex 3 (corner patches), d0 = `gl_LastFragData[0]` (our
   rewrite reads the framebuffer's own texture), scissor over the whole layer.
6. Draws 11 to 13: the child layer and the text.

### Hypotheses, in the order I would test them

1. **LUMINANCE_ALPHA upload.** Black is `(0,0,0,1)`: it comes out of `color * s0` if tex 4 samples as `(0,0,0,a)`, or
   out of draw 10 if s0.a is wrong. Mesa's ES3 context keeps LA as RG with a swizzle; try uploading LA (and
   LUMINANCE, ALPHA) as RGBA8 with `(L,L,L,A)` converted on the CPU in `w_TexImage2D` / `w_TexSubImage2D`, or read tex 4
   back through a temporary FBO, as round n did for tex 3.
2. **Feedback in draw 10**: it samples the framebuffer's texture (`sca_fb`) while rendering into it. The barrier is a
   `_mesa_TextureBarrierNV` before the draw; freedreno in sysmem may need more (check what `fd_texture_barrier` does on
   a5xx, or put a `glFinish` before such draws to see whether the black goes away).
3. **Texture completeness**: tex 4 has mips and CA sets `TEXTURE_MIN_FILTER` through `TexParameteri`. An incomplete
   texture samples as `(0,0,0,1)` too. Check base/max level and that every level is uploaded in the same format (the
   trace says all 9 are, 256 down to 1).
4. Precision or derivative problems in the shaders (unlikely, they are trivial).

A cheap decisive experiment for 1 and 3: before draw 10, read tex 4 (levels 0 and 1) through a temporary FBO and log a
few texels.

## Things tried (so you do not repeat them)

| Round | Test | Result |
| --- | --- | --- |
| a | first run | everything loads and the context works; the render touched nothing: CA drew into the default framebuffer, which does not exist |
| b, c | tracing on; `[CATransaction flush]` after `setLayer:` | CA now draws, with error `0x506` (incomplete framebuffer) |
| d | FBO with the surface's texture, made by the test | draws, no errors, but viewport 0x0 |
| e, f | read back the FBO; `glViewport` in the test | **first correct pixels** (background `214579ff`) |
| g | honour `invert` in the copy path | no change: CA passes `invert 0` for its images |
| h | `set_destination_texture` through the vtable (flip false/true) | no effect at all; not needed |
| i3 | flip rows of IOSurface textures when `invert` is NO | **image and text become right** (11159 to 2290 differing); this is the rule now |
| j, k | in-place import only when no flip is needed; the test binds its own target with `invert YES` | same numbers as i3 (j was a test mistake: target bound without `invert YES` was copied, nothing drawn) |
| l, m, n | per-draw state, texture calls, corner copy read-back | the trace above |
| o | character map of the rounded layer | the picture above |

Rules kept: IOSurface textures from `texImageIOSurface:` are flipped (so copied) unless `invert` is YES; surfaces bound
by `attachImage:` and the test's target are used in place. A surface whose pitch is not a multiple of 64 bytes, or an
import the kernel refuses (`darwin_bo_from_iosurface: IOSurface 11 not imported: 0xe00002bd`, seen for the 64x64 image
surface CA makes over the creator's own pages), is uploaded as a snapshot with `glTexImage2D`.

## Not done / open

- `sweetca_test` PASS (the defect above). `sweetca_set_flip` and the "mode" loop in the test are leftovers to remove.
- The test sets trace level 2 by default (shader dumps in the log); lower it when the defect is fixed.
- The IOSurface row-bytes question (§2.2 last bullet): CA's own surfaces here were 64x64 BGRA pitch 256 (refused by
  selector 6 with `0xe00002bd`, reason not looked into) and 150x24 pitch 608 (not 64-aligned, never usable in place).
  The kernel was not changed. Real display surfaces need a look in step 3.
- CA asks `glGetString(0x8a1e)` (NULL, error 0x500): harmless so far.
- GPU speed not measured (debug mode on); `glFlush` is `glFinish`.
- Nothing on the phone's root was changed; only `sweetca_test` and `libsweetca.dylib` went to `/usr/local/bin`.
- Step 3 (backboardd) is untouched and needs the user's OK.
- Commit trailers say `Claude Sonnet 5.5`, the model that did the work (the brief says Opus 5.5).
