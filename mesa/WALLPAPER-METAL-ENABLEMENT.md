# Astronomy Metal enablement, 2026-11-01

User requested Metal for wallpapers requiring it and suggested it might also fix
the CURRENT cards. Astronomy now renders Earth, Moon and Solar System in its live
editor on a temporary boot. No wallpaper was added/applied. CURRENT cards remain
a separate, unresolved snapshot problem.

## Scope and changes

Chlorophyll commits (local, not pushed):

- `8e54e39`: render encoders retain bound pipelines, buffers, textures and samplers
  until they are replaced or the encoder is destroyed. Recorded work retains its
  own references through replay. This fixes Astronomy releasing a newly loaded
  texture after binding it, before the draw was recorded. Bound-resource pointers
  previously became stale; the crash was in `bgRecordDraw`'s texture retain loop.
  Diagnostic pixel peeks in compressed uploads were removed, and vertex/index
  trace previews now check their buffer bounds.
- `97234d5`: exact `AegirPoster` registration allowlist entry, still requiring
  `BGMTL_ENABLE=1`, plus its own optional `bgmtl-poster.env` configuration.
  `BGMTL_POSTER_SDR=1` installs process-local format setters that map XR550..555
  to BGRA8 or BGRA8 sRGB consistently in CAMetalLayer, texture descriptors and
  render-pipeline color attachments. Other formats are unchanged.

This is an SDR compatibility path, not native XR/HDR support. The device continues
to report `supportsExtendedXR10Formats=NO`. NanoUniverse unconditionally requests
an XR drawable despite that answer, and also hard-codes XR in intermediate
textures and PSOs; mapping only the layer causes an 81-versus-555 attachment
mismatch. Mapping the descriptors as well fixes the live editor.

The tested compositor remains the installed ASTC version. Aegir's separate runtime
and injector are in `/usr/local/p/`; no other application/extension gains a Metal
device from this change. Existing gallery previews for Color and Emoji render
without this registration; no need for Metal was established for their providers.

## Verification

All builds used the local macOS VM, no CI:

| Build | Observed result |
| --- | --- |
| wallpaper-aegir1 | Injector built; device opens FD512. Live process throws CAMetalLayerInvalid, unsupported extended range format. |
| wallpaper-aegir2 | Layer SDR fallback reaches NanoUniverse shaders/textures; unsafe trace peek past ASTC block rows causes SIGSEGV. |
| wallpaper-aegir3 | Trace-safe runtime gets through texture upload; first draw exposes unretained bound texture. |
| wallpaper-aegir4 | Resource ownership fix; GPU suite 27 pass / 0 fail, plain and --bb. Live renderer advances to explicit attachment-format mismatch. |
| wallpaper-aegir5 | Consistent descriptor SDR mapping; live Earth, Moon, Solar System render. Runtime libraries byte-identical to aegir4; only injector changed. |

The strengthened P5 binds pipeline/vertex buffer/texture/sampler and releases the
caller's references before drawing, then compares all 4,096 output pixels. Both
full GPU-suite modes pass. Existing P14 also remains exact for 1,099,392 sampled
ASTC channels, including mip chains and CPU-memory refresh. Real Astronomy uploads
include 4096x4096 ASTC images and mip chains down to 1x1; its starfield, threshold
and post shaders compile and submit successfully after the fixes.

Evidence (ignored local device artifacts):

- `research/wallpaper-metal/aegir/trace1716.txt`: successful live-editor commit,
  matching format 81 in the actual attachment and PSO, and populated pixels.
- `top.png`: live Earth editor with current date/time.
- `moon.png`, `solar.png`: live Moon and Solar System editors.
- `probe4-plain.txt`, `probe4-bb.txt`: full GPU suites.
- `console1.txt` through `console7.txt`: raw boot-ring captures, which include the
  earlier failed experiments. Do not treat their historical crashes as final-run
  failures or claim they are all crash-free.

## CURRENT cards

They remain gray. Unified logs identify a separate PosterBoard exception in
`PBFHomeScreenPreviewViewBuilder buildView`: a nil object is inserted into an
NSDictionary. Preferences reports failed HomeScreen/CoverSheet snapshot requests.
Local disassembly of that builder shows home appearance/snapshot/silhouette view
construction, not a direct Metal-device request. This does not prove Metal is
irrelevant deeper in the call chain, but enabling Astronomy has not fixed it.
No poster configuration or snapshot cache was deleted/reset.

## Final candidate and deployment

Candidate image: `shim/out/shim-boot-j0120on-wallpaper-metal-slotb.img`, 17,498,112
bytes, SHA256 `fd966e00844e391f4804040e92d7c497541c18ffe4c6cd4940287f44e03be42b`.
Its payload's kernel, ADT and segments are byte-identical to the tested temporary
image; only the boot arguments differ. The boot-image ramdisk was extracted in
memory and checked byte-for-byte against the intended payload. It uses the normal
installed compositor path, adds Aegir's scoped injection, and retains `abmark=b`.
The explicit `sweetgpu_debug=0` is omitted to fit the 608-byte boot-argument field;
the kernel variable's default is zero. GPU timing/pause and display-ticket settings
are preserved. Earlier temporary-image diagnostic-only flags omitted to fit the
entry were `-noprogress`, `wdt_test=no_user_checkin`, and `panicwait=60`; `wdt=-1`
remains explicit.

Aegir libraries:

```
libbgair 176d9a119148fe3bf59f19f5cd0b31bc141651f76ebdb3672bc94312468c889a
libbgmtl a7e526cfc2924ce814e64cbd4facdd403dd6663c7cb7088a339a6441bc8b7a85
```

Exact readbacks of `/usr/local/p/i.dylib` and `libbgmtl.dylib` match aegir5 outputs.
The poster env file now contains only `BGMTL_POSTER_SDR=1`; global trace marker was
removed. No production compositor libraries, Apple executables, root bundle/plist,
or boot partition were changed. The old installed image remains
`shim/out/shim-boot-j0120on-metal-slotb.img` (the installed ASTC libraries still
load with it).

Final exact-image temporary boot passed: fastboot send/boot OKAY, SweetGPU up in
16 seconds. `research/wallpaper-metal/aegir/quiet-gallery.png` shows the gallery;
`quiet-editor.png` shows live Earth Detail with current date/time, all trace
diagnostics off. Earth, Moon and Solar System were also verified in aegir5 before
this final boot. Final console `console-final.txt` records zero AegirPoster,
SpringBoard or backboardd crashes, zero SMMU faults, zero queue fallback and zero
no-copy upload errors. Final ticket sample: 7412 begin/seal, zero abort/stale/error/
timeout, no live tickets. One PosterBoard SIGABRT remains during snapshot/gallery
initialization; the CURRENT preview issue has not been fixed. No performance or
HDR accuracy claim is made.

Injector SHA256:
`b2c3f1b39cb34688c6f79e4b4a63e3c03a899325cd3aca4a1f7c9d98632550e5`.
Phone is left in the live Earth Detail editor on the temporary final candidate;
the Add button was never pressed. Plain reboot still returns the installed
ASTC-only image, where Aegir Metal is not enabled. Side files are staged and exact
readbacks pass. Permanent installation would flash this candidate to boot_b;
AGENTS.md requires explicit confirmation before that destructive step. The image
is ready for that decision; do not flash without confirmation. Rollback image is
the preserved prior installed Metal image; no GPT or other partition change is
part of the proposed installation.
