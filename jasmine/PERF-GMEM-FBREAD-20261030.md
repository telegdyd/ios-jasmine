# GMEM framebuffer read: feedback draws can read the tile (2026-10-30)

Follow-up to [GMEM stage 3](PERF-GMEM-STAGE3-20261028.md), which ended with "no global uplift". Stage 3's
blocker: every batch with a feedback draw (a draw that samples its own render target) had to stay in
sysmem, because the texture unit was assumed to read only memory. On Home those batches were
14.4 of 27.9 ms GPU per frame (1125x2436). This round asks two questions before any redesign:

1. **What are the feedback reads?** If most are framebuffer fetch (`gl_LastFragData`, the draw's own
   pixel), a GMEM tile can serve them; a read of any other pixel cannot.
2. **Can the Adreno 512 read GMEM through a texture?** a5xx has `UCHE_GMEM_RANGE_MIN/MAX` (our kernel sets
   0x100000.., j0018; Mesa gets it as `gmem_base`, SweetGPU param 4), the window a6xx's framebuffer fetch
   uses. Qualcomm's own driver offers `GL_EXT_shader_framebuffer_fetch` on a5xx (Adreno 530 extension
   lists; the string is in this phone's stock `libGLESv2_adreno.so`, and its compiler has
   `needRelativeFragcoordForFBFetch`). Mesa never implemented it for a5xx.

## Answers

**1. All of them are fetches.** Home: 33.4 needed barriers per frame, 100.0 % fetch, 0 other self-reads.
Control Center: 44.6 per frame, 100.0 % fetch. No "self-read (not a fetch)" line in the whole boot.

| Per GL flush (~frame), j0118 828x1792, production barriers (SYS_BARRIER 0) | Home | CC |
| --- | ---: | ---: |
| barrier-needed | 33.41 | 44.61 |
| feedback-fetch / selfread / both | 33.41 / 0 / 0 | 44.61 / 0 / 0 |
| batch ends at a barrier | 35.59 | 53.85 |
| batch ends at a resource dependency | 10.18 | 34.85 |
| draws | 100.0 | 189.4 |

(`tools/g2/fbreadsum.py logs/netlog-fbr1.txt research/fbread/fbr1-work.txt`; 1600 Home and 800 CC flushes of
the gpwork.py gestures.)

**2. Yes: a feedback draw reads the tile, pixel-exact.** A texture descriptor with base
`gmem_base + cbuf_base[0]`, the bin's pitch and tile mode **TILE5_2** (what `emit_mrt()` renders GMEM in)
returns the tile's contents. Every pixel of a pattern that encodes its own position came back exact:

| sweetgpu_gltest `--fbread-only` (GMEM forced) | 64x64 | 256x256 | 192x128 | 512x512 (4 bins: sysmem fallback) |
| --- | --- | --- | --- | --- |
| swap (pattern, barrier, fetch writing .grba) | 0 / 4096 wrong | 0 / 65536 | 0 / 24576 | 0 / 262144 |
| chain (two fetches + a scissored third) | 0 wrong | 0 | 0 | 0 |
| restore (no clear: tile restored from memory first) | 0 wrong | 0 | 0 | 0 |

Same with `--no-tc`. Controls: tile mode 0 (linear) or 3 instead of 2 make 87-99 % of pixels wrong in
the GMEM batches while the sysmem 512x512 stays correct, so the reads really come from the tile and its
layout is TILE5_2.

**BGRA targets need the swizzle undone.** CoreAnimation draws into BGRA IOSurfaces. a5xx samples BGRA as
memory byte order plus a Z,Y,X,W swizzle (`fd5_tex_swiz`), but GMEM holds the colour unswapped (the
resolve swaps). The first full run read red and blue exchanged (the existing feedback tests on BGRA
IOSurfaces failed: 24 30 54 instead of 30 30 48, exactly eight R/B exchanges). Clearing the descriptor's
SWAP field changed nothing (fd5 views never set it); mapping X<->Z in the swizzle for WXYZ targets
(reversal for XYZW) fixed it. Final: **`--fbread` 97/97 PASS** (all earlier gltest steps, the BGRA
feedback sequences, odd imported targets incl. 67x45, plus the new fbread step), with and without TC;
baseline `--sysbarrier-wide` 85/85. No SMMU fault, panic or hang in any boot.

## Patch 0013 (default off)

`mesa/patches/0013-freedreno-a5xx-gmem-fbread-probe.patch`:
- libsweetca: every needed barrier is counted as `feedback-fetch`, `feedback-selfread` or
  `feedback-both` (DRAWPROF), and the first 16 programs with a non-fetch self-read are logged.
- fd5 (`SWEETCA_GMEM_FBREAD=1`): a retained barrier (0008) no longer forces sysmem; views of the batch's
  target emitted in its draw IB are recorded and, if the batch renders through GMEM, rewritten in
  `fd5_emit_tile_init()` to the tile (base, pitch, TILE5_2, swizzle). **One bin at the origin only**:
  shader coordinates are absolute, the tile's are the bin's, so `fd_gmem_render_tiles()` keeps
  multi-bin fbread batches in sysmem (`fbread-sys-bins`). `SWEETCA_GMEM_FBREAD_TILE` for tests.
- gltest `--fbread` / `--fbread-only`: the probe above.

With the switch off the driver behaves as before; production library unchanged (bf5328c0), nothing flashed.

## What this does not show yet

- **No CA frame used it.** Real frames (828x1792, ~24 bins of 272 KB GMEM) are multi-bin, so every CA
  feedback batch still falls back to sysmem. No frame-rate or GPU-time number exists for this route.
- **Multi-bin needs bin-relative addressing.** Candidates: (a) load the fetch view's descriptor
  indirectly from a small buffer and write each bin's base offset there in the bin prologue
  (CP_MEM_WRITE + wait), if TILE5_2 offsets stay block-linear for bin origins on the 64x32 grid;
  (b) a per-bin constant the rewritten fetch shader subtracts from `gl_FragCoord`.
- **Barrier cost inside GMEM.** Each fetch draw keeps its in-IB barrier (CCU flush, wait for idle, UCHE
  invalidate), now executed once per bin: Home ~33 barriers x ~24 bins ~ 800 waits per frame. Their cost
  is unmeasured and could eat the gain; stage 3's per-batch timer (`SWEETCA_GMEM=1`) would measure both
  modes once multi-bin works.
- Scale, rough: at 1125x2436 (stage 3) the batches this unlocks were 14.4 ms of Home's 27.9 ms GPU, next to
  the 5.9 ms stage 3 could already move to GMEM. That is what becomes eligible, not a forecast of savings.

## Evidence (ignored `research/fbread/`, `logs/`)

Mesa VM builds `xnu/out-mesa-fbr1` (first probe), `-fbr2` (SWAP field, no effect), `-fbr3` (swizzle fix,
gltest 75bcb55f...). Round scripts `research/fbread/session{1,2,3}.sh` + logs; gltest outputs
`research/fbread/gl*.txt`, `gl3__fbread.txt` final; counts boot `logs/netlog-fbr1.txt` (temporary j0118 image
`shim/out/shim-boot-j0118-fbr1.img`: slot b args + `SWEETCA_DRAWPROF=1`, lib `/usr/local/bin/fbr.dylib`,
`B_DROP="keepsyms=1 panicwait=60"` for cmdline room). Phone files left under test names:
`/usr/local/bin/fbr.dylib` (fbr1 libsweetca, inert), `/usr/local/bin/sweetgpu_gltest-fbr3`.
