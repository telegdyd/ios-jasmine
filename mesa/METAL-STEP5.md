# Metal step 5: standalone a512 Metal device

2026-10-31. Step 5 complete. Chlorophyll `288d410` pushed to origin/adreno5xx.
Parent implementation commit `45fa4fc` records the build integration and pointer.
The device is made directly in a test process; nothing registers it with Metal
or loads it into backboardd. Step 6 has not started.

## Changes

`tools/mesa-local.sh` now requires and signs arm64/iOS 16 libbgmtl and the
compute, quad and render probes, with side-by-side @rpath libraries. It also
compiles bg_quad/bg_render metallibs locally. No libdrm stand-in is linked.
SweetGPU builds omit the Bergamota GPU-info dependency and use successful
screen creation as the availability check; its GPU-state helper returns unknown,
not a fabricated ready/lost state. Wait-error diagnostics come from our backend.

The Metal device queries Mesa's compute dimensions, total thread limit, shared
memory, sample support and texture-buffer alignment. Each reported dimension is
clamped to the total thread limit. Observed: registryID 0x10000b512, dimensions
512x512x64, pipeline maximum 512 total threads, 32,768 shared bytes. BGRA8 sample
support queries return yes for 1/2/4 and no for 8; this is a capability query,
not MSAA rendering validation. a5xx leaves linear_image_pitch_alignment unset;
its fd5_layout rule is 64 pixels, so the fallback depends on format block size:
256-byte BGRA rows, 1,024-byte RGBA32Float rows. Existing UBO/SSBO offset
alignment queries and format-support queries remain in use. Image/SSBO binding
counts are checked against stage caps and the a5xx shared slot budget (24).

A new gap found on the phone: Mesa a5xx exposes SSBOs only to fragment/compute,
not vertex stages. Attribute-based quads worked, but the render probe's `device`
vertex buffer was unbound and produced no geometry. Read-only vertex device
buffers now lower from SSBO to UBO loads and bind as constant buffers. Writes
and out-of-range slots are refused. The remaining bound region must fit Mesa's
65,536-byte UBO limit; a 1 MiB binding is tested and refused explicitly.
SweetGPU command buffers now report a draw refusal as an error instead of
inheriting upstream's silent skip-and-success behavior. Larger vertex device
buffers will need another implementation, such as a5xx VS SSBO state partitioning.

For attachment reads on screens without hardware fbfetch, load_output becomes
an integer-coordinate texel fetch of the attachment. Units 12..15 are reserved
for color targets 0..3; conflicting shader bindings and multisample feedback
are refused. The runtime binds those attachment views, forces sysmem and issues
the existing a5xx framebuffer/texture feedback barrier after clear and before
each fetching draw. Binding-cache state is updated too. This changes only the
private AIR runtime, not shared Mesa/ir3 or libsweetca.

SweetGPU no longer uses Bergamota's static IOSurface/GEM resource-pin cache.
Imports use the stable IOSurface ID and normal resource references. Explicit
surface sync remains a no-op; the visibility tests below exercise this choice.
The compute stress probe now waits for asynchronous command completion before
checking status/output; it previously assumed commit was synchronous.

## Validation

Local macOS VM only, no CI. Final build `metal-s5final3` passed all required
Mesa/AIR/runtime/Metal links and signing; artifacts in
`xnu/out-mesa-metal-s5final3`. Build-script syntax and code whitespace checks pass.

Temporary fastboot boot of `shim/out/shim-boot-j0120on-slotb.img`, matching the
installed kernel/settings. All added test libraries, executables and metallibs
were placed in /usr/local/bin. Two complete final-build rounds passed:

| Probe | Result per final round |
| --- | --- |
| bgmtl_probe | 11 checks passed, 0 failed; real Metal _MTLLibrary functions |
| bgmtl_quad_probe | all quads whole; index offsets, flat provoking vertex, clipping, MRT, reuse and mipmaps |
| bgmtl_render_probe | 25 checks passed, 0 failed |

Compute includes exact add/copy/group sums and 20 consecutive 65,536-element
add submissions per round with zero wrong elements. Render includes texture
read/sample/write, colored triangle (3,664 checked pixels), nearest/inline/high
texture-slot quads, linear filtering (worst error 0.00137256 within 0.01), and
depth Less (1,024 near red pixels, zero far green pixels).

Added feedback test: two RGBA32Float attachments, non-power-of-two 37x19 size,
clear followed by three full-screen fetching draws. All 5,624 final channel
values match exactly. Multisample feedback pipeline creation is refused.

Added IOSurface test: 37x19 BGRA8, 256-byte row pitch, 12 changing patterns per
round. CPU fills/unlocks the surface, GPU reads every texel to a float buffer;
then GPU clears the imported texture and the CPU reads the surface directly
under a read lock. Texture wrappers are recreated over the same ID each round.
All 12 rounds have zero wrong values/pixels, repeated in both final runs. This
supports visibility for these tested accesses; it does not establish every
cross-process synchronization or display/compositor case.

Added negative test: a 1 MiB read-only vertex device buffer returns command-buffer
status 5 and an explicit 65,536-byte UBO-limit error, rather than reporting success.
The intentional error is part of the passing probe.

Final test window in `research/metal-step5/netlog-metal-s5final3.txt` (from
its last libbgmtl upload onward): zero SMMU faults, SWEET PANIC, panic(cpu,
ticket/submit errors, SpringBoard crashes or test-process CRASH lines. The
logger replays earlier boot history, including four lines for s5c's PID 324
crash; these precede the final window. Extracted window/counts are retained
as final-window-console.txt and final-window-counts.json. Raw probe output: `bgmtl_*-metal-s5final3-r{0,1}.txt`; orchestrator
output `check-final3.txt`. These are correctness tests, not performance results.

Development results retained under research/metal-step5: s5a failed the missing
Bergamota wait-error symbol; s5b exposed the async-probe and VS-SSBO gaps; s5c's
new NIR pass crashed the test process because its insertion cursor was unset
(fixed in s5d); s5d passed the original probes; s5e failed a Mesa header include
order (fixed in s5f); s5f passed the added feedback/surface tests. s5final passed
24 checks; s5final2's new oversized-buffer check caught the silent draw skip;
s5final3 fixes that and passes 25 checks in each round. The earlier test crash
is not included in the final clean-console claim.

## Artifacts and device state

Final SHA256:

- libbgair: `9ee150ce31ddd9d9578925e4b735e848666bdc2ce0ae36a084ceb83f5c1328ab`
- libbgmtl: `64bf4baf2314ed50857114fd3d85f2d724fac6bee81f14796abe05d1de6fe88b`
- built libsweetca: `1441c96dbe9a4c0f2d4a485af401b5923c616d7e0340c67a53bdbc1464e12eca`

Built libsweetca is byte-identical to Step 4/Step 2's tested candidate. No shared
Mesa behavior changed, so no additional GLES/UI candidate round was required.
Production readback remains
`bb3a7a9ef7927bd189e9b74c8799610df7f4abec26bcb958b5712d688a12a445`.
Installed boot_b j0120on and /s.dylib are unchanged. No flash, root bundle/plist,
production renderer replacement or Metal registration occurred. Device dumps,
readback and generated binaries remain ignored, outside git.

Phone parked with temporary charge-shell.img: 73%, Charging; shared phone lock
released. Evidence: research/metal-step5/park.txt.

## Next boundary

Step 6: test-process registration/injection using iOS 16's
MTLCreateSystemDefaultDevice rather than MTLCopyAllDevices. Stop here until the
user authorizes that step. A root plugin/bundle, launchd plist, production
renderer replacement or installed boot change still requires separate approval.

Remaining limits: no compositor claim; feedback is validated between draws with
non-overlapping quad primitives, not overlapping primitives within one draw.
Feedback is single-sample/2D and reserves the last four texture/sampler units.
Only two attachments and float32 feedback were exercised; Apple half variants,
array/multisample cases, argument-buffer coverage, larger vertex device buffers,
MSAA/depth-format breadth and sustained multi-device/resource stress remain.
The offline QuartzCore coverage table was not rerun: runtime lowering is not
used by the separate compiler-only air2ir3 harness.
