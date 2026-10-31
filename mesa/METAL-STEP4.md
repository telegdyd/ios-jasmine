# Metal step 4: SweetGPU runtime compute

2026-10-31. Step 4 complete; Step 5 not started.

Chlorophyll commit `6eee3f0` (origin/adreno5xx) adapts `air_metal.c` under
`RWA_SWEETGPU`: open /dev/null, create the same freedreno screen as sweetgl,
close the original fd, and reject software mode in this hardware-only build.
IOSurface metadata comes from IOSurfaceLookup/Get*, with the page-relative
base offset used by sweetca. Import handles carry WINSYS_HANDLE_TYPE_FD and
the IOSurface ID. Cache-sync is explicitly a no-op because SweetGPU exposes
no selector. The original Bergamota implementation remains for other builds.
`fd_mesa_debug` is a strong reference to the copy linked into libbgair; nm
confirms no unresolved backend/debug symbols. It need not be exported to a
separate dylib because runtime and freedreno are in the same binary.

Parent build integration requires the complete libbgair link, signs it and
bgair_test for arm64 / iOS 16, sets the executable's @executable_path rpath,
and compiles bg_kernels.metallib locally. The patch loop now explicitly exits
on any git-apply failure (the surrounding error handler previously masked
intermediate failures). Patch 0020's context follows the updated 0018 comment.

## Validation

Local VM only, no CI. `metal-s4a` failed on the iOS SDK header name; corrected
to IOSurfaceRef.h. `metal-s4b` built and linked all required targets. First
final attempt caught stale context in 0020; corrected along with fail-fast
patch application. `metal-s4final2` then built successfully, including the
Step 2 probe target and signed runtime/test. `bash -n tools/mesa-local.sh`
and code whitespace checks passed.

Temporary `fastboot boot shim/out/shim-boot-j0120on-slotb.img`, matching the
installed kernel/settings; no flash. Charging-shell reboot initially returned
to installed iOS, then command-port reboot allowed the temporary boot.
Only /usr/local/bin/{libbgair.dylib,bgair_test,bg_kernels.metallib} added.

| AIR kernel | CPU-checked output per run | Result |
| --- | --- | --- |
| bg_add | 1,024 floats, a + 2*b | exact |
| bg_copy | 4,096 patterned uints | exact |
| bg_groupsum | 32 group sums of 64 inputs | exact |

Three runs of metal-s4b and one final-build run: each reports FD512,
RWA_SOFTWARE unset, 3 checks passed / 0 failed, exit 0. This executes AIR
from the generated metallib through the runtime, Gallium, ir3, and Adreno 512;
it is not the Step 2 hand-constructed NIR test. Console captures have zero
SMMU faults, panics, ticket/submit errors, or SpringBoard crash lines.
These are correctness runs, not a performance benchmark.

Final libbgair SHA256:
`4bae4215e80e011804bebe91ee6cc2c8d7119edf70fe79731442081f8c716325`.
Built libsweetca remains byte-identical to the Step 2 candidate:
`1441c96dbe9a4c0f2d4a485af401b5923c616d7e0340c67a53bdbc1464e12eca`.
No shared ir3/backend changes in this step, so no new GLES/UI regression round
was needed. Production libsweetca and installed boot_b were not replaced. Production readback
SHA256 is bb3a7a9ef7927bd189e9b74c8799610df7f4abec26bcb958b5712d688a12a445.
Phone parked with temporary charge-shell.img: 75%, Charging; lock released.

Artifacts: xnu/out-mesa-metal-s4final2. Ignored raw logs, scripts and production
readback: research/metal-step4/{build-*.log,run.txt,compute-*.txt,netlog.txt,
final.txt,final-compute.txt,final-netlog.txt,park.txt}. Apple/device data stays
out of git.

## Limits and next work

Buffer compute is validated. Texture compute, imported IOSurface coherence,
rendering and Metal API registration are not established by these tests.
The no-op surface sync must be tested with CPU/GPU surface patterns before
using it for compositor output. Existing upstream surface-import cache lifetime
and a6xx pitch/limit assumptions also remain to audit during Step 5.

Next: Step 5, adapt/query a512 limits in src/bgmtl.m, build a test-process Metal
device and run compute/quad/render probes, including texture and IOSurface
visibility checks. Framebuffer fetch still needs a5xx lowering. Production or
root bundle/plist installation requires the user's separate approval.
