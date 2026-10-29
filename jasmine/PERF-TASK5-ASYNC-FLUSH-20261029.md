# Task 5: CoreAnimation's per-frame glFlush without the threaded-context drain (2026-10-29)

**Installed 2026-10-29 23:05 (user OK):** production libsweetca = bf5328c0 (0001-0011), plain reboot verified
(`logs/netlog-t5af-installed.txt`, tickets balanced, 0 errors, Home dump correct); previous 4780fbaa kept as
`/usr/local/bin/libsweetca-pre-t5async.dylib`.

**Result: +10 % Home, +6-12 % Control Center, +9 % Spotlight swap arrivals in an ABBA of temporary
boots, same kernel, same args, only the library differs.** The render thread no longer runs or waits for
the driver thread at `glFlush`. Not installed (production stays 4780fbaa); installing needs the user's OK.

## The cost (profile evidence)

CA ends every frame with `glFlush` (`IOMFBDisplay::finish_update` -> `w_Flush`). In ticket mode 2 the
wrapper calls the real `glFlush()`, and Mesa's `_mesa_flush()` makes it **synchronous** once any
IOSurface is bound (`ctx->Shared->HasExternallySharedImages`, set by `st_context_teximage`): `tc_flush`
without `PIPE_FLUSH_ASYNC` goes to `tc_sync`, which **executes the still-unqueued TC batch on the calling
thread** and then waits for gdrv0 to finish the queued ones.

Inclusive render-thread cost (goldab-auto capture, installed 4780fbaa, per frame): `w_Flush` 1.55 ms in CC
(1.6 in Home), of which `tc_batch_execute` (freedreno draws + batch flushes run inline) ~1.2 ms, plus
1.3-1.95 ms waiting in `tc_sync` (framecrit `wait-shader`). Same size in Home and CC: about 20 % of the
Home render thread's Mesa time.

Mode 2 does not need the drain: every write to a shared surface opens a kernel render ticket before the
write (`ticket_draw` -> `sgl_ticket_write`), the ticket callback queued right after the flush
(`sgl_ticket_flush` -> `sgl_render_driver`) flushes the driver pipe on gdrv0 and seals the tickets with
the submit's seqno, and the display/present queue waits for the seal. Unknown targets already fall back
to `glFinish` (`ticket_sync_frame`), modes 0/1 are unchanged.

## Change

`mesa/patches/0011-sweetgl-mode2-async-flush.patch` (commit `d4b9718`): new `sgl_flush_async()` in
sweetgl.c = `FLUSH_VERTICES` + `st_glFlush(ctx, PIPE_FLUSH_ASYNC)` (the same flush `_mesa_flush` does
without shared images; TC queues the flush call and hands the batch to gdrv0, where freedreno flushes
the driver pipe exactly as before). `w_Flush` uses it in mode 2. `SWEETCA_SYNC_FLUSH=1` restores the
synchronous flush for comparisons.

## Build and correctness

- VM builds (Mesa 26.2.5 + patches): B `xnu/out-mesa-t5async` = 0001-0011, libsweetca SHA256
  `bf5328c0...`; A `xnu/out-mesa-t5base` = 0001-0010 only, `fba37b89...` (same source otherwise, so the
  A/B differs only by 0011). Note A is HEAD, not the installed 4780fbaa (which predates 0008-0010
  work); A's rates match today's 4780fbaa runs (CC A 29-31/s, Home B 40-41/s).
- Pixel gate, `sweetgpu_gltest` of the B build (f47a77d1...) on the installed boot: plain run 9 steps
  PASS, `--sysbarrier-off`, `--sysbarrier-on`, both with `--no-tc`, all PASS, `--feedback-diagnostics`
  45/45 PASS, 0 FAIL lines (`research/t5async/gl*.txt`). gltest does not go through `w_Flush`, so the CA
  path was checked on the B boots:
- B boots: tickets begin/seal/abort 2064/2063/0 and 2104/2103/0 (the 1 is the live ticket),
  stale/error/timeout 0/0/0, present queue high-water 1, `submit errors 0, sticky status 0`, no
  ticket/submit fallback line, no panic, no SMMU fault, GPU hw fault 0. Same as the A boots.
- Screen dumps after each run (`research/ab/t5af-*/shot.*.png`, sweet_shot -s): Home identical between
  A and B apart from the clock and the animated wallpaper. The user has not looked at motion on the phone.

## A/B (ABBA, 2026-10-29 22:32-22:53)

Temporary boots of `shim/out/shim-boot-j0118-t5lib1.img` (A, SHA256 51ebce4f...) and `-t5lib2.img`
(B, 70992e73...): installed boot_b's j0118 test args (no abmark) with backboardd's
`DYLD_INSERT_LIBRARIES` pointed at `/usr/local/bin/libsweetca1.dylib` / `libsweetca2.dylib` (side copies;
production file untouched). `tools/g2/abround.py`: boot, unlock, 150 s settle, standard framebench.
CPU auto, GPU 588, DDR 1804 (governor on), TSENS 50-53 C, charging, 63-64 %. A first A round
(`t5af-a1-partial`) stopped on one command-port timeout in control-b (no fault in its log; same flake as
`goldab-pin`); repeated once as `a1n`.

| Swap arrivals/s | A1 | B1 | B2 | A2 | A mean -> B mean |
| --- | ---: | ---: | ---: | ---: | ---: |
| Home B | 40.67 | 44.22 | 45.11 | 40.36 | 40.5 -> **44.7 (+10.2 %)** |
| Control Center A | 30.64 | 32.53 | 31.52 | 29.95 | 30.3 -> **32.0 (+5.7 %)** |
| Control Center B | 28.29 | 31.82 | 31.73 | 28.58 | 28.4 -> **31.8 (+11.7 %)** |
| Spotlight repeat | 32.33 | 35.47 | 36.65 | 33.97 | 33.2 -> **36.1 (+8.8 %)** |

Medians: Home B 24.0/24.5 -> 21.5/21.7 ms; CC B 34.3/34.1 -> 30.3/30.1 ms; p95 not worse (Home B
30.6/29.9 -> 29.7/28.9, CC B 43.5/44.5 -> 37.0/36.9). Both B runs beat both A runs in every phase.

Per Control Center A frame (`tools/g2/framecrit.py`, `research/ab/t5af-*/framecrit.txt`; symbols need
the library under the phone's name, `research/t5async/sym/libsweetca{1,2}.dylib`):

| ms per frame | A1 | A2 | B1 | B2 |
| --- | ---: | ---: | ---: | ---: |
| Frame (mean) | 33.5 | 33.7 | 30.9 | 31.9 |
| Render thread on CPU | 24.2 | 25.3 | 24.4 | 25.6 |
| of it CoreAnimation | 11.6 | 12.4 | 12.1 | 12.5 |
| of it Mesa | **10.0** | **10.0** | **9.4** | **9.8** |
| `w_Flush` inclusive (Mesa part) | 1.33 | 1.38 | ~0 | ~0 |
| Waiting for gdrv0 at glFlush (`tc_sync`) | **1.95** | **1.34** | **0** | **0** |
| gdrv0 on CPU | 17.6 | 17.6 | 18.6 | 19.1 |
| GPU occupancy (upper bound) | 21.4 | 22.0 | 22.5 | 23.3 |
| Frames on 2 / 3 periods | 96 / 7 | 101 / 4 | 105 / 4 | 107 / 4 |

- The flush's inline batch execution and the drain wait are gone from the render thread; that work
  (~1 ms) now runs on gdrv0 (+1.0-1.5 ms there, in parallel).
- Render-thread **Mesa time fell only ~0.4 ms per frame**, not the full ~1.3 ms that `w_Flush` cost:
  `w_DrawElements` grew by ~0.2-0.3 ms per frame in B and total on-CPU time per frame stayed ~25 ms.
  Why is not established (guesses: more TC batch hand-offs/back-pressure now that gdrv0 runs alongside,
  or cache contention with gdrv0). The frame-time gain comes mostly from removing the 1.3-2 ms wait.
- Control Center still lands on 2 periods (render CPU ~25 ms > 16.7); the gain shows as fewer 3-period
  frames and in the swap rates.

Home A (the CPU-sampled Home phase) had **no frames in all five captures, A and B alike** (the "home-a
stall" first seen in perfnow-20261029), so there is no Home per-frame split; Home numbers above come from
Home B (unsampled). The stall is library-independent and worth its own look: it now reproduced 5 of 5
on temporary boots.

## State and next

- Phone back on the installed boot_b j0118 (plain reboot via fastboot, slot b), production
  `/usr/local/bin/libsweetca.dylib` readback 4780fbaa before and after. Side files left on the phone:
  `/usr/local/bin/libsweetca1.dylib`, `libsweetca2.dylib`, `sweetgpu_gltest-t5async`,
  `t5af-shot.raw.*` (remove or keep for the install).
- To ship: install `xnu/out-mesa-t5async/libsweetca.dylib` (0001-0011, bf5328c0...) as production (user
  OK required; userland only, no flash), then a plain reboot check and the user's look at motion. It
  also carries 0008-0010 relative to 4780fbaa (all default off / sysmem-only per their reports).
- Tooling gotcha found: `tools/vm-mesa.sh` exits 0 and copies the **previous** build's outputs when
  ninja fails (`mesa-local.sh` runs `ninja ... || true`, then only `test -f`). Check `build.log`.
- Evidence (ignored): `research/ab/t5af-{a1-partial,a1n,b1,b2,a2}/` (captures, framecrit.txt,
  mesainc.txt, shots), `logs/netlog-t5af-*.txt`, `research/t5async/` (gltest output, abba.sh/log).
