# Metal step 1: AIR builds against jasmine Mesa 26.2.5

2026-10-31. No device access. User requested stopping before device access.

Chlorophyll `adreno5xx` commit **ff309fc1512e932a840856e3687b524a0bea71f4**
adapts AIR's NIR and Gallium consumers to Mesa 26.2.5. Original MIT notices and
licence are preserved; changes are marked jasmine. Its Mesa/libdrm submodules
remain uninitialised; upstream patches remain untouched.

Parent patches 0017/0018 add the AIR frontend and libbgair target. The local build
stages `mesa/metal/air/` after applying patches. AIR code remains separate from
libsweetca: no shared ir3 changes were made. The old `ir3_cmdline.c` and its
`ir3_compiler` executable target are absent from pristine 26.2.5, rather than just
relocated. Step 3 needs a new offline compiler harness; this was not implemented.

Compatibility edits: shader-stage names, NIR builder floating-point controls
(conservatively use `nir_fp_no_fast_math` where the old builder requested exact),
block ownership, shader creation, copy propagation, metadata invalidation and
range analysis; Gallium screen capabilities/options, sampler and constant-buffer
bindings, value-based framebuffer surfaces and explicit clear write masks.
These edits compile; their runtime behaviour is not yet tested.

## Build results

VM reachable using Windows/Git Bash SSH (`mac`, configured in Windows SSH config).
WSL's SSH configuration lacks this alias; do not interpret that as VM downtime.
No CI runs.

- `metal-s1a`: first rejected a malformed patch hunk; corrected, then Meson
  rejected the old `inc_mapi` name. No completed artifact.
- `metal-s1b`: production targets passed; AIR failed on Mesa 25 API names.
- `metal-s1c`: frontend and air2nir linked; runtime still had nine compile errors.
- `metal-s1d`: frontend and runtime C compiled; only libbgair link failed.
- **`metal-s1e`**: final `tools/vm-mesa.sh mesa metal-s1e` exited 0.
  Production targets and mandatory AIR compile targets passed. The explicitly
  allowed experimental library link failed on exactly these symbols:
  `_null_sw_create`, `_sweet_drm_bo_sync`, `_sweet_drm_surface_bo`.

Final artifact: `xnu/out-mesa-metal-s1e/`, including `air2nir`,
`air-build-status.txt`, `air-build.log`, and the five existing signed outputs.
VM logs: `~/topaz-mesa/{patch,build,air-build}.log` (overwritten by later builds).
`file`, `vtool -show-build`, and `codesign --verify` confirmed air2nir is signed
Mach-O arm64, platform IOS, minimum 16.0 (SDK 18.0). It is not a macOS host tool
and was not executed. No real iOS metallibs were compiled in this step.

Final libsweetca SHA256:
`bb3a7a9ef7927bd189e9b74c8799610df7f4abec26bcb958b5712d688a12a445`,
identical to local `xnu/out-mesa-t28b/libsweetca.dylib` (the production build).
This is a binary comparison, not a fresh device regression test.

The build script now fails on production ninja failure instead of accepting
old files. AIR frontend/runtime compile failure also fails the build; only
libbgair linking is allowed to remain incomplete and is labelled in the artifact.

## Stop point and next work

Stop before step 2's first shared ir3 change: it requires pixel-exact
`sweetgpu_gltest` and a UI regression round after each patch. The handoff's old
claim that steps 1–3 need no phone contradicted those checks. Step 3 can compile
shaders offline if the iOS 16 metallibs are already available; otherwise obtaining
them from the phone is also device access. Step 4 requires real GPU execution.

No phone commands, boots, file transfers or installations were performed.

Publication pending: automatic approval review rejected the combined commit/push
command because exporting code to the fork requires separate user approval.
Commit ff309fc was subsequently created locally. Do not assume it is on origin.
Once the user authorizes pushing to `telegdyd/Chlorophyll` branch `adreno5xx`,
push it, then commit the parent submodule pointer as the handoff requires.

Publication update: user explicitly approved push; ff309fc is now pushed to
`telegdyd/Chlorophyll` branch `adreno5xx`. The parent publication commit records
the submodule pointer. The earlier rejection above is historical.
