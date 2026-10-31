# Metal step 6: iOS 16 process-local registration

Completed 2026-10-31 with the user's Step 6 authorization. Chlorophyll
`c3ef65a` (origin/adreno5xx), parent build integration `ffae38b`.
Local macOS VM build `metal-s6c`, artifacts `xnu/out-mesa-metal-s6c`; no CI.

## Result

`MTLCreateSystemDefaultDevice()` returns our `BGMTLDevice` on the phone when
the test injector is enabled. Two separate final processes each obtained the
same device on repeated calls, registry ID `0x10000b512`, and each passed all
25 render-probe checks with zero failures. The probe links Apple's frameworks
only: `otool -L` shows no Chlorophyll dependency, and its undefined symbols
include `MTLCreateSystemDefaultDevice`, not `bgmtl_create_device`.

This satisfies Step 6's test-process completion criterion. Plugin installation
and compositor use remain separate work; no root bundle/plist was installed.

## Implementation

`inject/bgmtl_inject.m` selects the jasmine injector when built with
`RWA_SWEETGPU`. The Bergamota implementation remains under the other branch.
The jasmine path requires both `BGMTL_ENABLE=1` and executable basename
`bgmtl_registered_probe`. It has no backboardd path, Renegade feature flag,
state files, kill-switch files, persistent preferences, or GPU-ready claim.
Actual SweetGPU device/screen creation is the availability check.

The constructor calls iOS 16's `MTLCreateSystemDefaultDevice` to initialise
Metal enumeration before `MTLAddDevice`. It refuses to replace an existing
device. It then registers Chlorophyll and logs the selected class and pointer
identity. The original device reference is kept for the process lifetime.
Diagnostic callbacks preserve unknown-selector and command-buffer failure
messages in captured stderr. No unknown-selector messages appeared in either
final probe; the oversized-buffer negative test emitted its expected failure.
This injector is limited to short-lived test processes and has no compositor
recovery/watchdog policy.

The registered probe builds the existing render-probe source with
`BGMTL_REGISTERED_PROBE`. It gets its device exclusively through Apple's
system-default API and checks class, registry ID and repeated-call identity
before running the render suite. Negative modes check the stock device and
whether dyld actually inserted the injector.

The minimal iOS root has no `/usr/bin/env`. New `bgmtl_exec` sets the two
per-exec variables and execs the requested test. All files live in
`/usr/local/bin`; the test does not require a root-image change. The existing
kernel sweetenv mechanism can supply the same environment on a temporary
boot, for example an entry for
`bgmtl_registered_probe:DYLD_INSERT_LIBRARIES=/usr/local/bin/bgmtl_inject.dylib,BGMTL_ENABLE=1`.
The final checks used `bgmtl_exec`, not a new sweetenv boot configuration.

## Device checks

Temporary `fastboot boot shim/out/shim-boot-j0120on-slotb.img`; no flash.
Final side files: `libbgair.dylib`, `libbgmtl.dylib`, `bgmtl_inject.dylib`,
`bgmtl_registered_probe`, `bgmtl_exec`, the two metallibs and a renamed probe
copy for the executable-name gate check.

| Case | Observation |
| --- | --- |
| No insertion | Device nil, injector absent, PASS |
| Inserted, flag 0 | Device nil, injector present, PASS |
| Inserted, flag absent | Device nil, injector present, PASS |
| Inserted, flag 1, renamed executable | Device nil, injector present, PASS |
| Enabled, run 1 | BGMTLDevice, stable identity, registry b512; 25 PASS / 0 FAIL |
| Enabled, run 2 | BGMTLDevice, stable identity, registry b512; 25 PASS / 0 FAIL |
| New process after both enabled runs, no insertion | Device nil, injector absent, PASS |

Each render run covered texture read/sample/write, triangle pixels, nearest/
inline/linear/high-slot texture quads, depth, two-target framebuffer feedback,
12 IOSurface CPU/GPU visibility rounds (zero wrong), and expected refusal of
the unsupported MSAA feedback pipeline and oversized vertex device buffer.
The latter returns command-buffer status 5 and the explicit 65536-byte UBO
limit error; it is a passing negative test.

Captured final console (`netlog-metal-s6c.txt`): zero SMMU fault, SWEET PANIC,
kernel panic, ticket/submit error, SpringBoard crash or bgmtl-process crash
matches. Counts are observations of this capture, not a claim about all
system activity. Link/signature checks also passed. Raw outputs, scripts and
readback stay ignored under `research/metal-step6/`.

## Build history and unchanged production

- `metal-s6a`: injector and framework-only probe built. Stock-device test
  passed; attempted `/usr/bin/env` launch failed because that program is absent.
- `metal-s6b`: added explicit inserted-but-inert validation and diagnostics.
- `metal-s6c`: added the standalone environment launcher; final checks above
  all passed. Build scripts passed `bash -n`, source diffs passed whitespace
  checks, and ad-hoc signatures verified on the VM.

Final SHA256:

```text
libbgair.dylib          9ee150ce31ddd9d9578925e4b735e848666bdc2ce0ae36a084ceb83f5c1328ab
libbgmtl.dylib          64bf4baf2314ed50857114fd3d85f2d724fac6bee81f14796abe05d1de6fe88b
libsweetca.dylib        1441c96dbe9a4c0f2d4a485af401b5923c616d7e0340c67a53bdbc1464e12eca
bgmtl_inject.dylib      a82877b423045f973309844c759008786d2644216d5c638eb8e769c8b06b0318
bgmtl_registered_probe 8b56bee52ca0ab5fe6c8defb91a598356cd626a3e0e43754d745af179a84164a
bgmtl_exec             7f481c2f59b8ff776e4c18182c56d9a3e719f1ad3d1bb3b98d0a25e50cadebb2
```

All three GPU runtime libraries are byte-identical to Step 5, including the
shared GLES candidate. No shared Mesa changes or new GLES/UI candidate round.
Production libsweetca readback remains
`bb3a7a9ef7927bd189e9b74c8799610df7f4abec26bcb958b5712d688a12a445`.
Installed boot_b and `/s.dylib` remain unchanged. Finally parked using temporary
`fastboot boot shim/out/charge-shell.img`: 75%, Charging; phone lock released.

## Next boundary

STOP before Step 7. Next work is selecting iOS 16 QuartzCore's Metal renderer
and establishing an isolated temporary compositor test, including recovery
and shared-screen/resource behaviour. This step makes no compositor or
performance claim. Step 5 limitations still apply (including large VS device
buffers and overlapping feedback primitives). Root plugin/bundle/plist
installation, installed boot changes and production renderer replacement
still require separate approval.
