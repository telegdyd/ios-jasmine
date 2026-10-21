# Mesa for jasmine (G2)

Mesa freedreno (Gallium, a5xx) on ios-jasmine's SweetGPU kernel driver (patch j0026), built for the
iOS 16 userland with Xcode's iPhoneOS SDK on the CI (`gh workflow run xnu.yml --ref jasmine -f build=mesa`).

- `patches/`: applied in order to Mesa `mesa-26.2.5`. 0001 adds `src/freedreno/drm/darwin/`, a backend
  that talks to the SweetGPU IOKit user client instead of Linux's msm DRM ioctls, and `sweetgpu_fdtest`,
  the first on-device test (gallium only: clear a render target on the GPU, read it back).
- `ios-arm64.ini`: the meson cross file.

The patches are made from a Mesa checkout in WSL (`~/ios-work/mesa`, one commit per patch).

Sources of the patch: `darwin/` (written into a Mesa tree by `darwin/apply.py`; `tools/g2/mkmesa.sh` regenerates
`patches/0001-freedreno-darwin-backend.patch` from it). See `jasmine/HANDOFF-G2.md`.
