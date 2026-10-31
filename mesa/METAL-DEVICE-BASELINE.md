# First phone check (2026-10-31)

This is the device baseline before handoff step 2's shared ir3 changes, not
completion of step 2 or Metal GPU execution. User authorized phone access for
one step, followed by a report.

Used existing VM artifact `xnu/out-mesa-metal-s1e`: signed ARM64 iOS `air2nir`
and statically linked `sweetgpu_gltest`. Test files were copied under
`/usr/local/bin` with `-metal-baseline` names. No boot, flash, production
library replacement, or boot-setting change.

Installed `/usr/local/bin/libsweetca.dylib` was read back. SHA256:
`bb3a7a9ef7927bd189e9b74c8799610df7f4abec26bcb958b5712d688a12a445`, matching
the established production build and step 1 output.

## Checks

- ARM64 `air2nir --list` lists all seven synthetic Metal functions.
- `air2nir` translates `jasmine_add`, `jasmine_u2f`, `jasmine_negative`,
  `jasmine_vertex`, and `jasmine_fragment` on the phone, each exit 0.
  This executes the frontend on the CPU; it does not execute these shaders.
- GLES test identifies `OpenGL ES 3.1 Mesa 26.2.5`, renderer `FD512`.
- Five GL runs (default, explicit glthread-off environment, barrier off,
  narrow barrier, wide barrier) each exit 0 with 85 PASS lines, zero FAIL
  lines, and `PASS: all`. Pixel comparisons report zero wrong pixels.
  The standalone test enables glthread only with `--glthread`; default and
  the explicit environment-off run therefore cover the same thread mode.
- UI gesture round completed at 19:14:11–19:14:47 without losing the command
  port. Captured Home screenshot is visually intact (icons, dock, wallpaper,
  widget and text). This is a visual baseline, not an A/B performance result.
- Console collector connected but received no kernel console payload; therefore
  this round cannot establish a zero-fault/panic count from logs. Processes
  returned normally and the UI remained responsive.
- Phone left in installed iOS with display on, charging, kernel-reported 71%,
  39.3 C. Shared phone lock released. Test files remain under `/usr/local/bin`.

Raw logs, readback, synthetic input, screenshot, and the exact round script
are in ignored `research/metal-device-baseline/`. Apple input and device
captures are not committed.

## Next

First investigate the integer-to-float rounding patch on a512 with a focused
runtime probe, before and after the compiler change. Then repeat pixel tests
and a UI comparison with the candidate library on a temporary boot. Keep the
production renderer unchanged until separately approved. The shift-split
rewrite is absent in Mesa 26.2.5; narrow SSBO accesses remain a separate gap.
