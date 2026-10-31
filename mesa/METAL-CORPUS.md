# Metal corpus pass before step 7, 2026-10-31

No phone access. Offline only: the QuartzCore and CoreImage shaders of iOS 16.7.16 (20H392) compiled for a512
with the native tools on the VM. "Compiles" means AIR -> NIR -> ir3 -> assembled; nothing here ran on a GPU.

## Result

| Library | Functions | Before | After | Still failing |
| --- | ---: | ---: | ---: | --- |
| QuartzCore/default | 141 | 111 (step 2) | **139** | `tile_downsample_4/8` (unreachable, below) |
| CoreImage/default + portrait_filters_archive | 133 | 100 (METAL-OFFLINE.md; not re-run in step 2) | **125** | 6 SIMD shuffles, 1 pointer phi, 1 byte repack |

CA's uber shaders now compile: `fixed_frag_lph_cph/cpf` (165/167 instructions, attachment reads on units 15, 14) and
`fixed_vert_lph/lpf_gen`. With zero-default function constants, as before; CA specialises them per draw.

Builds: VM `metal-host` cq1, cq2, cq3 (final, `xnu/out-metal-host-cq3`, 7 synthetic probes PASS). iOS outputs of the
same build: libbgair `90cfa405...`, AIR compile and libbgair link PASS, **libsweetca `1441c96d...` = the step 2
candidate, byte-identical** (no shared Mesa change). Production `bb3a7a9e` and the phone untouched. Tables and logs:
ignored `research/metal-corpus/{quartzcore,coreimage}-cq3/` (and `quartzcore-cq1/`, the first run with the lowering);
VM `~/metal-offline-results/*-cq{1,2,3}`.

## What changed

Chlorophyll (`mesa/metal`, branch `adreno5xx`); parent: `tools/metal-host-local.sh` (the fetch probe now must compile).

1. **air2ir3 compiles what the device compiles.** New `air/air_lower.c` holds the runtime's NIR steps, used by both
   `air_metal.c` and `air2ir3.c`: the a5xx attachment-read and VS SSBO->UBO lowerings and `air_nir_lower_for_gallium`
   (finalize_for_gallium's three passes, moved). The tool then calls `ir3_shader_from_nir` as freedreno's
   `ir3_shader_state_create` does. Before, the tool ran `ir3_finalize_nir` (the runtime never does), passed NULL to
   `nir_lower_compute_system_values` (the trap the runtime's comment describes) and refused framebuffer fetch.
   Compute kernels get an 8x8x1 threadgroup as a stand-in for the dispatch's.
2. **Framebuffer fetch: units the shader leaves free.** Step 5 reserved units 12..15 and refused any shader declaring a
   texture or sampler there. The uber shader declares textures up to 14. Now each target the shader really reads
   takes the highest unit no texture instruction names; reads removed by function constants need no unit, barrier or
   sysmem pass (`fbfetch_targets` is narrowed to what is read). 20 QuartzCore functions + the uber shader.
3. **ffma on Mesa 26.** Mesa 26 split NIR's multiply-add: `ffma` is always fused, `ffma_weak` may be either (what
   `ffma` meant in Mesa 25, which Chlorophyll was written for). ir3 has only an unfused `fmad`, so every `ffma` was
   "Unhandled ALU op". `llvm.fmuladd`, Metal's `fast_fma` and `mad` are now `ffma_weak`; precise `fma()` (and the
   fmod remainder) stay fused where the GPU has it. **On a5xx precise `fma()` is unfused: a deviation from Metal's
   rule** this GPU cannot avoid without software fma. `downsample_4/8_frag_lpf/lph` (CA's blur chain).
4. **Image loads on a5xx: a Mesa inconsistency.** ir3 reads an image through LDIB unless the load is `CAN_REORDER`,
   but reserves the image's dimension constants only for `COHERENT` loads. Ours were neither: an assertion in the
   debug tool, and in the phone's release build **a read of the wrong constants**. Now loads of images the shader
   never writes are `CAN_REORDER` (texture path, as GL gets from st/mesa), loads of written ones `COHERENT`.
5. **Texture writes.** The frontend took a write's `src_type` from the call's return type (`void`, so every write was a
   0-bit `uint`); now from the value. 16-bit store values are widened to 32 bits: a5xx STIB takes full registers and
   the typed store converts to the image format (as GL on a5xx). `inplace_copy_lph`, `tile_downsample_1/2`.
6. **Pointer locals (`AIR_VAL_SLOT`).** The uber fragment shader keeps each sampler argument in a one-pointer `alloca`
   and selects between it and a constant global `unused_sampler` (`{ ptr @__air_sampler_state }`). The frontend could
   do neither (the slot existed only as a comment). Now a one-pointer local stored once in the entry block, and a
   constant global that is one pointer, resolve at translation time; the function-constant evaluator decides the
   select. A run-time choice between them, a second store, or a non-zero GEP is still refused by name.
7. **VS buffers declared read_write.** `fixed_vert_*_gen` declare buffer 1 writable but only load it; the runtime's
   a5xx UBO lowering refused it. The refusal now looks at real stores (`air_nir_writes_ssbo`).

## Not reached on purpose

- `tile_downsample_4/8`: `air.thread_index_in_quadgroup` / `quad_shuffle_xor` (a5xx has no subgroup ops). These are
  tile (imageblock) kernels; `supportsFamily` answers at most Apple3, and Apple4+ is what promises tile shaders, so CA
  should not choose them on this device. Unverified until step 7's trace.
- CoreImage: 6 portrait filters use `air.simd_shuffle_down`; `kernel_PropagateDisparity` needs a run-time pointer phi;
  `convert_rgb8_to_rgba8_buffer` a 4 x 8 -> 32-bit bitcast. None is on the UI path.

## Before and during step 7 (needs the phone)

- **libbgair changed** (fetch units, image access flags, write types, ffma, slots). Re-run the step 5/6 probes
  (`bgair_test`, `bgmtl_render_probe` incl. P10 feedback and texture writes, the registered probe) first.
- Read-only VS device buffers become UBOs bounded at 64 KiB *from the binding offset*; a larger CA vertex buffer is
  refused at the draw. Watch for "beyond the 65536-byte UBO limit" in the first backboardd trace.
- The uber shader's free units depend on CA's real function constants (more textures read leaves fewer units).
- Precise `fma()` is unfused on a5xx (item 3).
