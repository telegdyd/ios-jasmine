# Step 2: shared ir3 fixes for a512

Work in progress, 2026-10-31. User authorized phone access through completion
of handoff step 2; do not start runtime bring-up (step 4) afterwards.

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

Pending validation. The upstream patch's a6xx descriptor explanation cannot
be assumed for a5xx. Our source audit found a direct a5xx reason for dword
lowering: `ir3_a4xx.c` emits LDGB/STGB with TYPE_U32 unconditionally. Passing
8/16-bit NIR memory ops to these emitters violates their register widths.
The planned adaptation asks generic NIR memory lowering for dwords and uses
atomic AND/OR for partial stores so adjacent writers preserve other bytes.

## Artifacts and device state

Ignored logs, scripts, readbacks and captures: `research/metal-step2/`.
VM builds use `tools/vm-mesa.sh mesa TAG`; no CI. No production installation
is authorized by this step. Temporary UI images retain kernel j0120on and
828x1792@2 canvas; candidate libraries live only in `/usr/local/bin`.
