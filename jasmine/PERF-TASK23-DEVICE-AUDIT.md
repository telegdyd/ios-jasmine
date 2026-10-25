# Task 23: Gaussian downsampling observed on the phone

2026-10-25, one diagnostic session. **The observed Gaussian path does use
downsampled copies.** The hypothesis that missing IOSurface mip levels force
all Gaussian blur to full resolution is contradicted by the captured pass
chains. Variable blur remains a separate, confirmed compatibility approximation
in source; this session did not execute its replacement shader.

No blur algorithm was changed. No speed improvement or visual equivalence of a
new blur implementation is claimed. Task 23 remains open as implementation work.

## Exact build and baseline

- Diagnostic source: `e4ece21`; Mesa CI
  [40240384093](https://github.com/telegdyd/ios-jasmine/actions/runs/40240384093)
  passed, Mesa job 3m00s. Local mocked-GL harness and isolated application of all
  six Mesa patches passed first. CI log confirms the new include was applied
  and sweetca.c compiled. Diagnostic strings verified in the binary.
- Library: 20,441,584 bytes, SHA256
  `c172abc13e5a7ae63a9b93aca9e1f8e1ac5f64475e8511d45264c01df0e6d9c7`.
  Installed under a test name and read back byte-for-byte before boot.
- Live baseline was **pipeline 0**, not the earlier GPU experiments' mode 2:
  ordinary slot-b j70 image, GPU588, DDR1804, four Gold cores at 1747.
  Production library readback SHA256
  `14e32aea4121e9c8a357da8f5e6322fe572a85f1c22e496990af0e687cb19261`.
  Exact backup: ignored `research/t23/production-before.dylib`.
- Temporary image `shim/out/shim-boot-t23trace.img`, SHA256
  `540ff31a9802fa2b18406390d0f57222d8fbf3ec39041e12123c4462a196023e`.
  Repacked from slot-b image SHA256
  `823c4ee3a7e8f4365fb620a1424793e283622a178d0d930ecadd5571f77cad5a`.
  Verified identical shim, ADT and kernel payload bytes; only the library/trace
  command-line options and Android payload digest changed. No partition flash.

## Session and coverage limits

User confirmed the phone was free. Shared lock held during all phone work.
Temporary boot at 23:34:45 Budapest succeeded; injected test path and trace
options appeared in the live log. Home was visually checked using an actual
swap surface. CARenderServerRenderDisplay returned the project's known black
result and was not used to assess UI readiness.

Trace configured for constructor age 300-325 seconds, capped at 3000 draws.
The host noticed the arm marker after its constructor had already run, so host
scheduling was offset from the true window. The first recorded draw was at
age 310.629; the time-limit marker appeared at 326.743 on the next attempted
draw. Do not describe this as 25 seconds of continuously sampled UI motion.

The short precheck had zero on-CPU samples attributed to accessoryupdater or
trustd over its 2.9-second sampled interval, with no drops. Commands opened and
closed CC and Notification Centre, then swiped Home. The second planned CC/NC
pair was skipped at the bounded deadline. Home swipes reached beyond the trace
window. There is no claim of complete per-UI coverage or exact per-phase frame
attribution. The captured interior chains below are independent of that label.

Captured 2,042 contiguous pre-draw records (sequence 1-2042), CA flush counts
192-204, 33 fragment programs and 43 weighted-candidate draws. Every queried
framebuffer was complete (`0x8cd5`). Zero copy/blit/mipmap event records and
zero variable-source-disc/variable-discard shader records appeared. Absence of
the latter means variable-blur runtime coverage is missing, not that its source
workaround does not exist.

This trace intentionally changes timing through metadata queries and logging.
Pre-draw records describe attempted work, not individual GPU completion. Native
kernel diagnostics reported zero submit errors/sticky status in sampled windows.
No new runtime SMMU-fault or panic report was found; startup self-test FSR 0x400
also appears in the pre-session production log and is not a new fault.

## Observed downsample chains

One complete interior chain, CA flush count 193:

| Draw sequence | Program | Source texture | Destination texture | Destination allocation |
| --- | --- | --- | --- | --- |
| 155 | 29: four weighted samples | 27: 1127x2438 | 24 | 1082x1226 |
| 157 | 29: four weighted samples | 24: 1082x1226 | 65 | **74x156** |
| 159 | 71: fourteen weighted samples | 65: **74x156** | 24 | 1082x1226 |
| 160 | 71: fourteen weighted samples | 24: 1082x1226 | 64 | 1127x2438 |

Source declarations confirm texture0 is the sampled input. Inputs and outputs
are separate textures, attachments are level 0, and sampled levels 1-3 are
undefined for these intermediates. Source inspection links the intermediate
allocation path to ordinary GL TexImage2D storage rather than IOSurface import;
the trace records no import identity for these targets. This is downsampling
through separate textures, which does not require a mip chain on the source
IOSurface. Similar chains recur at flush counts 194 and 198-201.

Another chain at draw sequences 53/62/65/66 goes through a **72x42** intermediate.
The observed 1082x1226 intermediate can be a reused larger allocation: CA's
PingPongState reuses storage that contains the requested bounds. A large FBO or
viewport does not prove that a quad covers that entire allocation. Vertex
positions/logical draw bounds were not captured, so these sizes cannot be used
as exact shaded-pixel counts.

## Full-size passes coexist with downsampling

At flush count 202, sequences 1904-1905 ping-pong between 1127x2438 and
1131x2442. Fragment source for program 97 has **four** texture samples and
weights, followed by optional alpha division. That is distinct from program
71's fourteen samples. Thus full-size passes coexist with a functioning reduced
path; their existence does not establish a fallback caused by missing levels.
Blur parameters, weights and vertex positions are needed to explain a specific
algorithm choice conclusively. This run did not reproduce or time the old
87-instruction 11.88 ms draw, and cannot explain that exact historical draw.

There are also 461 bound-texture observations with defined levels above zero,
including 256x256/128x128/64x64/32x32. This confirms that multi-level GL textures
exist on this device; it is not evidence of a blur mip chain or proof that every
bound texture is sampled by the current program.

## Variable blur and next work

The [offline audit](PERF-TASK23-AUDIT.md) remains the evidence for the variable
path: shared code requests destination mip levels, Metal honours them, native
GLES attaches level 0 and lacks the 0x26/0x27 GLSL entries. Our 0x26 discards
intermediate work; 0x27 substitutes a centre-plus-24-sample source blur.
Metal's start_render_encoder extracts the level at `0x1882d46b4..6b8` and
calls the attachment descriptor's `setLevel:` at `0x1882d4704`, confirming
that its level request reaches the actual render attachment.
Simply adding mip levels to imported IOSurfaces would not resolve all of this.
The source comment's blanket "GLES surface level 0 only" explanation should
not be reused as proof of a Gaussian defect.

Next engineering decision: identify a real workload using variable blur before
claiming its performance impact, and design a complete level-aware/shared
replacement with preserved radius, mask and edge behavior. For Gaussian, inspect
specific costly kernels and logical bounds rather than implement a general
"restore missing downsampling" fix. Keep CC as a benchmark and assess any
confirmed defect for all callers. The initial estimated 10 ms gain remains
unproven. No additional device round is scheduled by this report.

## Reproduction and device cleanup

Ignored `research/t23/` retains the image/session scripts, host harness, raw
trace, gesture schedule, sync precheck, source extracts, CI log, readbacks,
`analysis.json` and `result.json`. `python research/t23/analyze.py` regenerates
the grouped pass evidence. Raw trace SHA256:
`3d7662bfaa617fcca1b0773b04c5d9c1fce07528760b1059b9b42711393943f1`.

After collection, rebooted through fastboot into the unchanged installed slot-b
image. Its live log loads `/usr/local/bin/libsweetca.dylib`, DDR1804, with no
passgraph arm marker. Production lock screen visually verified from its swap
surface. Own screenshot files and test-name library removed; production library
was never replaced. Shared lock released after cleanup. No collector or profiler
left running. Phone left in normal production iOS, not the diagnostic boot.
