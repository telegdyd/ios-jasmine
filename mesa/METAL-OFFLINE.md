# Metal offline compiler baseline, 2026-10-31

Update after shared ir3 Step 2: QuartzCore now compiles 111/141, with all seven
register-width failures fixed. See [METAL-STEP2.md](METAL-STEP2.md) for phone
validation and updated corpus results. Counts below are the original baseline.

No phone access. Shared ir3 code and installed libraries remain unchanged.
Chlorophyll `adreno5xx` commit `0e2de69bc3fe39fff0ac8a1e322eb33546256b73`
is pushed to `telegdyd/Chlorophyll`. It adds a native compiler harness, synthetic
AIR probes and an isolated per-function corpus runner.

## Build and reproduction

`tools/vm-mesa.sh metal-host TAG` first validates the existing iOS build, then
builds native macOS `air2nir` and `air2ir3` with compiler assertions enabled in
`~/topaz-mesa/mesa-src/build-host`. Softpipe/GLES are configuration prerequisites
for full NIR; neither compiler creates a screen or GPU device. The tools link
compiler libraries, not SweetGPU. Their profiling hooks are explicit no-ops.

Final successful build: **metal-host7**, outputs `xnu/out-metal-host-metal-host7/`.
Both native tools are Mach-O x86_64 (the VM's architecture). Five synthetic
compute/vertex/fragment shaders compile and assemble for a512. The byte-store
probe fails ir3 validation (`IR3_REG_HALF`); framebuffer fetch is explicitly
rejected pending emulation. Those two failures are recorded, not counted as
successful GPU operations. Shell syntax checks and Python parsing passed.

Earlier host builds: 1/2 linked headers-only NIR; 3 exposed missing profiling
hooks; 4/5 exposed harness lifetime errors (variant creation already assembles
and discards temporary IR); 6 reached the byte-store validation gap. These
harness problems were fixed before the real corpus was run. No CI runs.

`libbgair` retains step 1's three unresolved backend symbols. The iOS build's
libsweetca remains byte-identical to production, SHA256
`bb3a7a9ef7927bd189e9b74c8799610df7f4abec26bcb958b5712d688a12a445`.

## Offline iOS 16 inputs and measurements

Found existing WSL IPSW:
`/home/teleg/ios-work/ipsw/iPhone10,3_16.7.16_20H392_Restore.ipsw`.
Its BuildManifest identifies `087-86698-044.dmg` as OS. Extracted that image to
`/tmp/jasmine-metal-offline`, mounted with `apfs-fuse -o ro`, and copied 21
QuartzCore/CoreImage metallibs to ignored
`research/metallib/ios16-20H392/`. `manifest.json` records paths, sizes and SHA256.
No SpringBoard metallib was found in the SpringBoard paths checked. The mount
was unmounted and the temporary extracted DMG deleted; cached IPSW preserved.
VM copies: `~/metal-offline-inputs/20H392/`.

Measured with a512, the current unmodified shared ir3, and zero-default function
constants (not every pipeline specialization). Every QuartzCore function has a
row in the table. Success means translation, compilation and assembly only.

| Library | Functions | NIR failure | ir3 failure after NIR | ir3 success |
| --- | ---: | ---: | ---: | ---: |
| QuartzCore/default | 141 | 4 | 33 | 104 |
| CoreImage/default | 58 | 2 | 25 | 31 |
| CoreImage/portrait_filters_archive | 75 | 6 | 0 | 69 |

Per-function `functions.tsv`, `functions.json`, extracted slices and full logs:
`research/metal-corpus/quartzcore-20H392/` and
`research/metal-corpus/coreimage-20H392/`. VM originals are under
`~/metal-offline-results/` with those same directory names. Apple files and
shader dumps are not committed.

QuartzCore failure classes:

- 20 framebuffer-fetch functions: explicitly refused because a5xx needs the
  attachment-texture emulation in handoff step 5.
- 7 ir3 load/register-width validation failures at ir3_validate.c:578.
- 4 downsample fragment shaders: unhandled `ffma` (float/half variants).
  Do not replace fused arithmetic with separate operations without addressing
  its precision semantics.
- 2 image-dimension assertions in `get_image_offset`, ir3_a4xx.c:216.
- 2 AIR program-scope initializers are not accepted as plain constants:
  `fixed_frag_lph_cph`, `fixed_frag_lph_cpf`.
- 2 AIR input failures: `air.thread_index_in_quadgroup`, functions
  `tile_downsample_4` and `tile_downsample_8`.

CoreImage adds SIMD shuffle, pointer-phi and vector/word-repacking frontend gaps,
and more half-register validation failures. See its table for exact functions.

Run another corpus on the VM (all paths refer to the VM):

```sh
cd ~/ios-jasmine
~/topaz-mesa/venv/bin/python3 mesa/metal/tools/jasmine-corpus.py \
  --air2nir ~/topaz-mesa/out-metal-host/air2nir \
  --air2ir3 ~/topaz-mesa/out-metal-host/air2ir3 \
  --out ~/metal-offline-results/NAME LIB.metallib
```

## Read-only step 2 audit

No ir3 patch was applied. This is evidence for deciding the next changes,
not device validation or a completed step 2.

| Upstream patch | Mesa 26.2.5 observation | Next action |
| --- | --- | --- |
| ir3-round-default | `create_cov` uses `set_cat1_round` now, but an undefined rounding mode still leaves the default field; synthetic u2f disassembly has plain `cov.u32f32`. | Port carefully, then measure rounding and run GL/UI regressions on the phone. No a512 runtime claim yet. |
| ir3-shift-split | Old `create_shift` add-splitting is absent. `lower_offset_for_ssbo` shifts the complete offset, and the remaining propagation helper handles shifts, not iadd. Synthetic negative-index kernel compiles. | The original patch's targeted rewrite is unnecessary on this version. Runtime negative-offset correctness remains untested. |
| ir3-ssbo-subdword | Current memory-access sizing can still choose 8/16-bit accesses. Synthetic a512 uchar store fails ir3 validation. a5xx uses its own byte-sized SSBO descriptors, unlike the a6xx R32 descriptor premise of the patch. | Investigate a5xx narrow-access lowering; do not transplant the a6xx workaround blindly. |

## Next work and device boundary

Useful offline targets remain: the four QuartzCore frontend failures, multiply-add
semantics and half-register/image-dimension lowering; the remaining extracted
CoreImage libraries can also be compiled. Each needs focused validation before
making runtime claims. Do not mark steps 2/3 complete as a whole: step 2's
required pixel-exact GL/UI tests and all GPU execution still need the phone.
The user has not authorized phone access yet.
