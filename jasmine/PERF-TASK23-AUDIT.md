# Task 23: initial offline blur audit

**Closed at user request, 2026-10-26.** Investigation complete; no optimization delivered or speedup measured. Gaussian downsampling was observed on device, disproving the blanket missing-copy premise for that path. This does not prove that no blur optimization is possible. The variable-blur approximation remains documented with unmeasured runtime impact; no further investigation or implementation is scheduled under task 23. This status supersedes open/next-work language in the historical material below.

Status: investigation only. No implementation change, build, CI run or device
access. User goal is shared UI blur correctness and performance; CC is a
benchmark. Source base is `22ef447` (rendering code unchanged from `8bd08b9`).

## Findings

The premise "downsampled copies should exist but none do" is not established.
Two different paths were conflated in the task description:

| Path | What the audit establishes | Remaining uncertainty |
| --- | --- | --- |
| Gaussian blur | CA implements explicit 2x/4x downsampling into separate GL targets. It does not universally require an IOSurface mip chain. | Which branches and effective dimensions the measured expensive passes use, and whether our rendering executes them correctly. |
| Variable masked blur | Our injected shader functions deliberately discard intermediate draws and replace the final filter with a source-texture disc blur. This bypass of CA's intended intermediate processing is confirmed in source. | Whether the stated IOSurface limitation actually applies to its intermediate texture, how the original GLES path represents its levels, and the visual/performance effect of restoring that path. |

There is a confirmed compatibility approximation worth correcting/investigating
in variable blur. There is not yet a confirmed Gaussian downsampling defect,
nor evidence that missing IOSurface levels explain all expensive blur draws.
Full-resolution blur can also be an intentional algorithm choice for some
radii/flags; full-size targets alone do not establish a correctness bug.

## Gaussian blur: source and cache evidence

The existing iPhone X QuartzCore cache disassembly has:

- `GaussianBlurFilter::render` at `0x188427854`, feeding blur parameters into
  the context; `Context::blur_surface` at `0x1883378ac` chooses the algorithm
  using parameters and context properties.
- Calls at `0x188338304`/`0x188338318` to `scale_and_dilate(0.25, 1, 4, 0)`
  followed by `downsample_blur_4(4, 1, ...)`. A corresponding Y-axis path
  exists at `0x18833834c`/`0x188338360`.
- Half-scale paths at `0x1883383f0`/`0x188338404` and
  `0x18833842c`/`0x188338440` call `downsample_blur_2`.
- Another half-scale path at `0x188338aa0` attempts `tile_downsample(2)`,
  then falls back to `downsample_box_2` at `0x188338ac0`. This is a fallback
  downsampling implementation, not evidence of a missing-mip full-size fallback.
- `scale_and_dilate` at `0x1883160a0` scales bounds and applies border padding.
  The downsample methods call `PingPongState::attach_dest`, which creates or
  reuses a target for those bounds through `PingPongState::create_surface`.
  Reuse can retain a larger physical allocation than the requested bounds.

The GLES constructor sets its final vtable to `0x1d5b2f6f8`. Cache inspection
maps its `+0x248` entry to `GLESContext::create_surface` (`0x188406a48`);
`+0x258` is the separate IOSurface constructor (`0x188406e90`). The former
creates GL texture storage through dispatch offset `0x970` (slot 301,
TexImage2D), with level 0 and RGBA/UNSIGNED_BYTE at `0x188406d74..da0`.
It conditionally calls GenerateMipmap (`0x1550`, slot 681) when flag 0x40 is
set. These offscreen textures are not inherently restricted to imported
IOSurface storage. The +0xa0 property dispatch is GLESContext::get; property
13 used by the 4x path returns 1 in this GLES implementation.

Our wrappers forward `TexImage2D` levels, `TexStorage2D` level counts,
`FramebufferTexture2D` levels, `GenerateMipmap`, and `BlitFramebuffer` to Mesa.
This does not prove every use works, but disproves treating these operations
as unconditional wrapper no-ops. Imported IOSurface resources really do start
with one level (`sweetgl.c` resource template and st_context_teximage level 0).
That restriction must be tied to a particular texture before blaming it.

## Variable blur: the confirmed approximation

`Context::variable_masked_blur_surface` at `0x188380194` requests its temporary
surface through the same create_surface vtable entry at `0x1883803ec..404`
with flags `0x20f`. It copies the source, selects texture function 0x26 at
`0x18838063c`, computes successively smaller dimensions in a loop, and selects
0x27 at `0x18838085c` for the final masked operation.

In `mesa/darwin/sweetgl/sweetca.c`, `fn_nop` uses `discard`, so the injected
0x26 shader intentionally writes no intermediate pixels. `fn_vblur` (0x27)
uses the centre plus 24 weighted source samples, with a radius controlled by
the mask and minmax_dir. It does not sample an intermediate mip chain. These
are installed to fill entries missing from QuartzCore's GLES shader table.

Thus the current variable blur is an approximation by design, rather than
evidence that an otherwise intact Gaussian mip chain fails. Its source comment
attributes the bypass to level-0-only GLES surfaces, but the temporary surface
creation above uses ordinary GL storage. That rationale needs a more precise
explanation; it is not a sufficient reason to preserve the workaround forever.
Neither visual equivalence nor a speed gain from replacing it is proven here.

## What the saved measurements do and do not prove

`logs/netlog-t16-gd1.txt:4987` and following lines show slow draws with
1127x2438/1131x2442 framebuffer, viewport and sampled-resource dimensions.
Home also has sampled 284x611 and 1082x1226 intermediates. Smaller intermediates
therefore already exist in the rendering workload; that alone does not identify
their scale relative to the original region or validate a particular blur.

`lv1` is `pipe_resource.last_level + 1` in patch 0006, a resource level count,
not a proof that a separate downsampled target never existed. Shader IDs are
driver IDs, not Gaussian/variable-blur names. The summaries retain only the ten
slowest draws/shaders per window, rather than every draw's dependencies. They
cannot reconstruct a complete blur graph. The logged 11.88 ms draw and other
times remain observations; their attribution to a missing mip chain does not.

## Reproduction and next action

Follow-up: Metal's set_surface (`0x1882edbe4`) extracts bits 1-5 of the
surface's +0x40 byte as a level and shifts target dimensions by that level.
The shared push_surface stores its level argument in those bits. GLES's
set_surface (`0x188407610`) attaches level 0 at `0x188407700` and uses base
dimensions. The native GLSL texture-function table has NULL entries for 0x26
and 0x27, as expected by install_texfns. Thus merely supplying the original
variable-blur shader expressions would not restore Metal's intermediate-level
behavior in this GLES backend. This is a backend compatibility gap, not proof
that all Gaussian downsampling is broken. Raw comparison extracts and texfns.py
stay under ignored research/t23. A [bounded diagnostic](PERF-TASK23-TRACE.md)
now addresses runtime Gaussian selection; rendering algorithms are unchanged.

Ignored evidence: `research/t23/extract.py`, `verify.py`, `properties.py`,
function extracts and `validation.json`. Run from repository root in WSL:

```
python3 research/t23/extract.py
python3 research/t23/verify.py
python3 research/t23/properties.py
```

4,645 extracted instruction encodings match the local cache. Four vtable
entries were read and resolved against the symbol inventory; the property-13
jump-table target was decoded. This verifies artifact consistency, not runtime
branch selection. Raw Apple-derived disassembly stays ignored.

Next: design a bounded runtime trace that links semantic shader/function,
texture allocation/import and level, attachment, logical region, viewport and
sampled inputs for one complete blur graph. Existing TRACE=2's process-wide
60-draw cap is insufficient. Cover Gaussian plus variable blur and a Home
backdrop; do not infer missing passes from slowest-only summaries. Resolve the
variable GLES intermediate representation before implementing a replacement.
No performance change or visual result is claimed; task 23 remains open.
