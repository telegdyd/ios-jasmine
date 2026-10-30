# GMEM framebuffer read: feedback draws can read the tile (2026-10-30/31)

**Bottom line (2026-10-31 00:25): the route works on real CoreAnimation frames, pixel-correct, but GMEM does not
pay on this GPU. With an ideal per-batch choice it would save 1.2 ms (Home) / 2.3 ms (Control Center) of GPU per
frame; the timed rule as built loses 0.6 / 2.4 ms instead. Keep it off; not installed.** Details in
"Multi-tile and real frames" at the end.

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
  `fd5_emit_tile_init()` to the tile (base, pitch, TILE5_2, swizzle). **First version: one bin at the origin only** (superseded on 2026-10-31 by multi-tile, below):
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

## Multi-tile and real frames (2026-10-31)

**Addressing.** fbread batches (a retained barrier with `SWEETCA_GMEM_FBREAD`) get one column of full-width bins
(`gmem_key.strips`, minx 0; 828x1792 -> 28 bins of 832x64), so a bin is only rows `yoff..`. Each view of the target is
loaded a second time, indirectly (`CP_LOAD_STATE4` `SS4_INDIRECT`), from a 64-byte slot in a per-context upload buffer
(`emit_fbread_slots`, deduplicated per batch). Sysmem batches leave the slot as the memory view. GMEM batches get
the tile view in the slot (TILE5_2, bin pitch, swizzle), and every bin prologue writes the slot's base
`gmem_base + cbuf_base - yoff * pitch` (49-bit, wrapping below zero) with `CP_MEM_WRITE`, then `CP_WAIT_MEM_WRITES`,
`CP_WAIT_FOR_ME` and a UCHE invalidate. Wider than 1024 px (tile_max_w) cannot be one column: sysmem.
`SWEETCA_GMEM_FBREAD=1` now also sets `SWEETCA_GMEM=1` and `SWEETCA_SYS_BARRIER=2` in libsweetca. Test settings can
come from `<library path>.env` (NAME=VALUE lines, read by a constructor; sweetenv wins), for lack of cmdline room.

**Correctness.** gltest (VM build fbr4) `--fbread-only`, TC and no-TC: 28/28, every pixel exact, on 832x512,
832x1792, 828x1792 BGRA IOSurface (CoreAnimation's frame), 512x512 and the single-bin sizes; the 1125x600 BGRA target
falls back to sysmem as designed. Full `--fbread` 112/112. Control with `SWEETCA_GMEM_FBREAD_TILE=0`: every
multi-tile target 99.8-99.9 % wrong (so they really read GMEM), 1125x600 still 0 wrong (sysmem). The negative-base
wrap works. Real frames (boot B below): Home and Control Center screen dumps match boot A (labels, icons,
materials, blur); 0 SMMU faults, panics or hangs in all boots.

**Performance.** Temporary j0118 boots, same library twice (`/usr/local/bin/fbr5.dylib`, settings file), GPUPROF +
DRAWPROF, `tools/g2/gpwork.py` gestures, `research/fbread/abprof.py` (first/last window dropped):

| GPU ms per frame | Home | Control Center |
| --- | ---: | ---: |
| A: switch off (fbr5) | 14.85 | 17.08 |
| B: `SWEETCA_GMEM_FBREAD=1` (fbr5) | 15.52 | 20.76 |
| B again (fbr7, ideal-choice counters) | 15.45 | 19.48 |

GL flush interval: Home 22.4 -> 21.6-22.4 ms, CC 29.7 -> 30.7-31.7 ms. Batches per frame 55.8 -> 18.5 (Home),
101.8 -> 56.5 (CC), as in stage 2.

Per committed decision with history (fbr7 counters, the timed rule's EMA times of the same batch kind):

| Per frame | Home | CC |
| --- | ---: | ---: |
| decisions (of them GMEM) | 14.2 (2.8) | 41.9 (12.8) |
| all in sysmem | 11.82 ms | 16.74 ms |
| all in GMEM | 16.32 ms | 30.91 ms |
| ideal (faster mode each) | 10.62 ms | 14.47 ms |
| fbread batches: sysmem -> ideal | 5.60 -> 4.95 ms (4.5 decisions) | 9.52 -> 8.30 ms (16.2) |

Reading:
- GMEM loses for most batch kinds: restore + resolve of the frame (~12 MB at 828x1792) costs as much as their draws,
  and fetch-heavy batches pay a barrier per fetch per bin (28 bins). Some kinds win: the main BGRA composite (6 draws,
  one fetch) 3.8 ms in GMEM against 4.4-6.1 ms in sysmem.
- The ceiling of the whole route is the "ideal" row: -1.2 ms Home, -2.3 ms CC of GPU per frame, before exploration.
  The timed rule pays more than that in exploration and retries, because CA's batch kinds (draw count, cost) change
  with every animation frame.
- Home frames are also render-thread CPU bound (~16 ms, [bottleneck report](PERF-BOTTLENECK-20261029.md)), so even
  the ideal 1.2 ms of GPU would barely show as frame rate.

**Recommendation: stop GMEM work here.** Patch 0013 stays in the series, default off (the barrier classification
counters and the gltest probe are useful). If GMEM is ever revisited: a static rule for the main composite only
(no exploration), and fewer per-bin barriers for fetches that do not overlap earlier draws.

Builds: `xnu/out-mesa-fbr4` (multi-tile gltest), `-fbr5` (A/B library), `-fbr7` (ideal-choice counters).
Rounds: `research/fbread/session4.sh`-`session7.sh`, logs `logs/netlog-fbr4.txt`, `logs/netlog-fbr6-{A,B}.txt`,
`logs/netlog-fbr7-B.txt`, screen dumps `research/fbread/fbr6-{A,B}-{home,cc}.*.png`. Phone files (test names):
`/usr/local/bin/fbr5.dylib` (fbr7 library), `fbr.dylib`, `sweetgpu_gltest-fbr4`; settings file removed.
