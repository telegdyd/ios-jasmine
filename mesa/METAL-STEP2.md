# Step 2: shared ir3 fixes for a512

Completed 2026-10-31. Implementation commits: `24da65e` (rounding and probes),
`a1a360f` (narrow accesses and mandatory byte-store smoke check). Chlorophyll
submodule remains `0e2de69`; no fork changes in this step. User authorized
phone access through completion of step 2. Stopped before runtime bring-up.

## Probes

`mesa/darwin/sweetgpu_ir3test.c` constructs AIR-equivalent NIR and dispatches
through the existing Gallium/SweetGPU backend. It does not use libbgair or
install a Metal device. Patch 0020 adds its target; the VM build stages,
builds and signs it. Each run compares the entire 1024-byte output, including
guards, against independently computed CPU values. Each dispatch has 32
threads, sharing dwords for the byte/half store tests.

Eight source values include UINT_MAX, INT_MAX, INT_MIN+1 and halfway cases
around 2^24. Both unsigned and signed conversions are stored as float32 bit
patterns. Explicit RTNE and RTZ are separate controls. The negative-offset
probe reads `(id + 1) * 24 - 4`; narrow probes use unaligned byte/half offsets,
and stores place distinct lane values into adjacent byte/half fields.

## Rounding

Patch 0021 retains Chlorophyll's `ir3-round-default` explanation and hunk.
With no declared float rounding mode, `create_cov` used the zero-initialized
ROUND_ZERO field. It now selects ROUND_EVEN for float destinations. Explicit
rounding modes keep their existing behavior.

VM `metal-s2base2`, unchanged shared ir3:

| Probe | Result |
|---|---|
| default u2f/i2f | FAIL, 92/1024 bytes wrong |
| explicit RTNE | PASS, 0 wrong |
| explicit RTZ | PASS, 0 wrong |
| negative offset | PASS, 0 wrong |

VM `metal-s2round2`, rounding patch only: all four probes PASS, 0/1024 bytes
wrong. A first harness attempt used an unsupported local-invocation-index
intrinsic and was killed by sweetd's timeout before dispatch; corrected to
local-invocation-ID.x before collecting the above results. This was not a
GPU rounding failure.

Rounding regression: default GL has 85 PASS lines; `--glthread` has 86.
Framebuffer-read-only with glthread has 27 pixel comparisons, all exact
(29 PASS lines including glthread and final status). Temporary j0120on boot
loads `/usr/local/bin/m2r.dylib`; UI round 19:27:58-19:28:34 completed, Home
screenshot visually intact, console records zero SMMU faults/panics, ticket
errors or SpringBoard crashes. No frame-rate claim.

## Shift splitting

Chlorophyll's old `create_shift` optimization distributed a right shift over
an addition, which is invalid for negative constants. Mesa 26.2.5 has no such
rewrite. `lower_offset_for_ssbo` shifts the complete offset expression;
`ir3_nir_try_propagate_bit_shift` handles only shift ALU ops, not `iadd`.
No patch needed. The GPU negative-offset probe above independently checks
the relevant address shape. This does not assert that every offset expression
has been exhaustively tested.

## Narrow SSBO accesses

Patch 0022 adapts Chlorophyll's `ir3-ssbo-subdword`. Its a6xx descriptor
explanation cannot
be assumed for a5xx. Our source audit found a direct a5xx reason for dword
lowering: `ir3_a4xx.c` emits LDGB/STGB with TYPE_U32 unconditionally. Passing
8/16-bit NIR memory ops to these emitters violates their register widths.
The adaptation asks generic NIR memory lowering for dwords and uses
atomic AND/OR for partial stores so adjacent writers preserve other bytes.
It passes the compiler through the callback and enables generic partial-store
atomic lowering. a5xx stays on dwords; newer generations respect the existing
storage_8bit/storage_16bit compiler options.

VM `metal-s2narrow` (metal-host mode, both iOS and native compiler builds):

| GPU probe | Wrong bytes / 1024 | Result |
|---|---:|---|
| default u2f/i2f | 0 | PASS |
| explicit RTNE | 0 | PASS |
| explicit RTZ | 0 | PASS |
| negative offset | 0 | PASS |
| load8 | 0 | PASS |
| load16 | 0 | PASS |
| store8, adjacent parallel writers | 0 | PASS |
| store16, adjacent parallel writers | 0 | PASS |

The synthetic AIR `jasmine_byte` now compiles and assembles with debug
assertions enabled, emitting dword atomic AND/OR. It failed register-width
validation before this change. Final VM `metal-s2final` passes the updated
host check: all six probes, including byte store, are mandatory. Framebuffer
fetch is still explicitly refused. Final iOS renderer and GPU probe hashes
match the tested `metal-s2narrow` outputs.

Final candidate GLES results: 85 PASS lines default, 86 with glthread, and 27
exact framebuffer-read comparisons (29 PASS lines including glthread and final
status). Temporary image `shim/out/shim-boot-j0120on-metal-s2narrow.img` selects
`/usr/local/bin/m2n.dylib`. UI round 19:33:36-19:34:12 completed with visually
intact Home screenshot. Console: zero SMMU faults/panics, ticket errors and
SpringBoard crashes in this capture. This is regression evidence, not a
performance A/B measurement or exhaustive correctness proof. Direct float32
to float16 rounding was not separately probed.

## QuartzCore compile regression

Same 141 functions, same zero-default specialization constants as the offline
baseline: **111 compile**, 26 backend failures, 4 frontend failures (previously
104 / 33 / 4). All seven previous register-width failures now compile:
`buffer_image_blit_frag_lpf`, `fixed_vert_lph_gen`, `fixed_vert_lpf_gen`,
`compute_apl`, `compute_apl_fast`, `sum_apl_and_compute_dimming_factor`,
`buffer_image_blit_frag_lph`.

The remaining 26 backend failures are the same 20 framebuffer-fetch refusals,
four unhandled ffma cases, and two image-dimension assertions. This table is
compile/assemble coverage, not execution of these Apple shaders. Full updated
logs are in `research/metal-step2/quartzcore-corpus/`, also on the VM under
`~/metal-offline-results/quartzcore-step2`.


## Artifacts and device state

Ignored logs, scripts, readbacks and captures: `research/metal-step2/`.
VM builds use `tools/vm-mesa.sh mesa TAG`; no CI. No production installation
is authorized by this step. Temporary UI images retain kernel j0120on and
828x1792@2 canvas; candidate libraries live only in `/usr/local/bin`.

Candidate renderer SHA256:
`1441c96dbe9a4c0f2d4a485af401b5923c616d7e0340c67a53bdbc1464e12eca`.
Installed production library remains the baseline `bb3a7a9e...`; neither
production libraries nor boot_b were written. Test binaries and candidate
libraries remain under `/usr/local/bin`. At the end, rebooted into the
temporary charging shell: 69%, Charging; phone lock released.

Step 2 disposition: rounding ported and tested; shift splitting unnecessary;
narrow SSBO lowering ported and tested. Step 3's shader table already exists.
Next runtime work is step 4: replace libbgair's backend dependencies with
SweetGPU and run real AIR compute kernels through that runtime. None of that
runtime work was started here.
