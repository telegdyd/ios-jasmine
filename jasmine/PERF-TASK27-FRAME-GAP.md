# Task 27: the Control Center frame gap (2026-10-31)

Question: with glthread installed (production libsweetca `21ca5c4d`, boot_b j0118), a Control Center frame took
~27 ms (36 swaps/s) although no pipeline stage took that long (render thread ~17-19 ms CPU, glthread worker ~5,
gdrv0 ~19, GPU ~21 occupied). Which stage idles, for how long, and why.

**Answer: the render thread slept ~6.7 ms per frame in 3 ms `SwapWait(0)` polls that could never succeed.**
CoreAnimation's `IOMFBDisplay::is_ready()` polls `SwapWait(fb, 0, 0x80000003)` after every screen wake. j0109's
present queue answered "done" for a swap only once a *later* swap latched, which can never happen for the newest
swap, so every poll ran into its 3 ms timeout. Kernel patch j0119 (`sweetfb_wait0=1`) calls `SwapWait(0)` done
once the newest swap is on the panel. ABBA (8 temporary boots): Control Center A **36.6 -> 40.4 swaps/s (+11 %)**,
Home B +6 %, Control Center B +5 %, Spotlight within spread; every B round's mean CC frame is below every A
round's; 0 faults. Not installed yet: that needs the user's OK (j0119 default on, flashed to boot_b).

## Method: a per-frame timeline from framebench's own events

No new instrumentation was needed. A framebench capture already contains kernel events with the emitting
thread: SwapBegin/SwapEnd (10/11), GPU submit / completion seen (20/21), ticket BEGIN (30, render thread,
first GPU write of the frame), SEAL (31, gdrv0 after the frame's last submit), FLIP (33, presenter), LATCH
(14), SwapWait calls over 0.1 ms with ID, duration and result (18), and the CPU samples (on CPU every 2 ms,
wait-state census with stacks). New tool `tools/g2/frametl.py` (WSL, like framecrit) joins them per swap
(ticket generation -> swap via event 39, SEAL -> seqno -> completion), prints per-frame stage times, 0.5 ms
lanes for the render thread (CA / Mesa / kernel / SwapWait / runnable / glthread wait), the glthread worker,
gdrv0 and the GPU, and a SwapWait table by waited ID relative to the last ended swap.

## Where the 27 ms went (installed configuration, `research/ab/t26-installed`, CC A)

Per frame (140 frames): period 28.2 ms mean / 26.2 median. Render thread: CA 12.6, Mesa 3.3, kernel 3.3 ms
on CPU, **SwapWait 2.9 ms sampled waiting + 1.4 ms runnable** (the census undersamples short waits; the
kernel's own SwapWait events give the full number below). gdrv0 19.1 ms on CPU, worker 4.3, GPU outstanding
23.3. From SwapEnd to the frame's SEAL (gdrv0 done) 12.0 ms, SEAL to GPU done 3.0 (median), done to FLIP 0.0,
FLIP to LATCH 9.7 (vsync).

SwapWait calls per ended swap (`frametl.py`, event 18):

| Waited swap (vs. last ended) | Calls / swap | Result | Median | ms / swap |
| --- | ---: | --- | ---: | ---: |
| newest (rel 0) | 2.1 | **all timeouts** (747 of 747) | 3.13 ms | **6.85** |
| previous (rel -1) | 0.93 | timeouts | 1.23 ms | 1.18 |
| rel -2 | 0.13 | mixed | ~1 ms | 0.14 |

The same 6.6-7.5 ms per swap of rel-0 timeouts shows up in every framebench phase: Home B 7.47, CC B 6.63,
Spotlight 6.81, idle-before 6.72, idle-after 6.82. Render thread CPU (~19.3) + SwapWait (~8.1) = 27.4 ms,
which is the frame. Stacks: `kern_SwapWait < IOMFBDisplay::is_ready < IOMFBServer::set_enabled /
Server::render_for_time` (~70 % of the wait), `IOMFBDisplay::can_update_` the rest (the rel -1 page polls).

## Why: CA's unblank flag and the queue's "done" rule

QuartzCore (iOS 16.7.16 cache, `~/ios-work/gl/out/qc.s`):

- `IOMFBDisplay::is_ready()` (0x1882f9318): if bit 3 of the display flags (+0x9f2) is set, call
  `SwapWait(fb, 0, 0x80000003)` (3 ms poll, ID 0); on success clear bit 3 and run
  `update_framebuffer_locked(0)` (0x1885324a8). The return value is only `!(flags & 4)`: a failed wait does not
  stop the frame, it just costs the timeout.
- `IOMFBDisplay::will_unblank()` (0x188383460) clears bit 2 (blanked) and **sets bit 3**: after every screen
  wake CA waits for its newest swap to complete, then applies pending framebuffer changes.

Kernel `AppleCLCD::swapWait` (j0109, queue mode): ID 0 resolves to the client's newest swap token, and a
swap is done when `fLatchedSerial > serial`, i.e. once a **later** swap latched (the rule a page's SwapWait
needs: its surface is free once replaced on the panel). For the newest swap no later swap exists while CA
waits, so bit 3 is never cleared and every `is_ready` call (2 per frame) sleeps 3 ms. Before j0109 (sync
mode) `SwapWait(0)` was done at once (`fEndID - 0 > 0`): **a regression of the present queue; task 16's A/B
(queue +22 % Home) measured the queue with this cost already included, and every later A/B had it on both sides.** It also explains j0058's old observation that the
latch rule (`sweetfb_swapwait=2`) made CA "skip vsync ticks".

## Fix: kernel patch j0119 (default off)

`xnu/patches/j0119-jasmine-swapwait-newest-latched.patch`: with boot-arg `sweetfb_wait0=1`, `SwapWait(0)` in
queue mode is done once the newest swap latched (`fLatchedSerial >= serial`), i.e. on the panel, which is what
CA's unblank logic waits for. SwapWait with a real swap ID (CA's page reuse in `can_update_`) keeps the
later-swap rule, so no surface is drawn into while scanned. Event 18 carries an id-0 flag in its last word.
Not a Mesa change, so no patch after 0014.

Build: `tools/vm-build.sh j0119` (14:04, 56 s). Images (`research/t27/mkimg.sh`, WSL): slot b's j0118
command line minus keepsyms/abmark, production library, 828x1792@2; `shim-boot-j0119-t27a.img` (without the
argument = today's behaviour) and `-t27b.img` (`sweetfb_wait0=1`, 607 of 607 command-line bytes).

## Correctness

- B boots: SwapWait(0) timeouts gone (CC: 6.7 -> 0.00 ms per swap; rel-0 calls 737-763 -> 0-4), rel -1 page
  polls unchanged (1.15-1.21 ms per swap), so page reuse still waits for the later latch.
- Every boot (8): 0 SMMU faults/panics, 0 ticket/submit errors; screen dumps after framebench's gestures
  (Home, Control Center) 0 % black, normal content (`research/ab/t27x-j0119-*/shot-*.png`).
- On B boots: `sweetgpu_gltest` all 9 steps PASS; `sweetca_test` the known 9958-pixel image-orientation
  mismatch, identical to task 26 (neither test uses SwapWait; they show nothing else moved).

## A/B (two ABBA sets, 2026-10-31 14:06-14:29 and 14:30-14:53)

`research/t27/abba.sh j0119 [ROUNDS]` (`tools/g2/abround.py`, 150 s settle, standard framebench),
battery 73 -> 67 %. Rounds a1 b1 b2 a2, then b3 a3 a4 b4. Logs `research/t27/j0119/abba*.log`.

| Swap arrivals/s | A1 | A2 | A3 | A4 | B1 | B2 | B3 | B4 | A mean -> B mean |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| Home B | 45.90 | 47.66 | 45.02 | 44.51 | 42.22 | 52.83 | 47.03 | 51.77 | 45.8 -> 48.5 (+6 %) |
| Control Center A | 35.57 | 37.16 | 36.57 | 36.95 | 36.76 | 42.22 | 39.24 | 43.45 | 36.6 -> 40.4 (**+11 %**) |
| Control Center B | 37.53 | 36.59 | 36.46 | 36.75 | 37.40 | 40.67 | 39.93 | 37.31 | 36.8 -> 38.8 (+5 %) |
| Spotlight repeat | 45.77 | 37.52 | 37.43 | 37.07 | 35.05 | 40.04 | 36.43 | 39.94 | 39.4 -> 37.9 (within spread; medians 37.3 / 38.0) |

Swap rates are noisy (B1 is low everywhere); the second set alone has both B above both A in Home, CC A and
CC B. Per CC A frame (`framecrit.py`, `research/ab/t27x-j0119-*/framecrit.txt`) the split is clean:

| ms per CC frame | A1 | A2 | A3 | A4 | B1 | B2 | B3 | B4 |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| Frame (mean) | 28.1 | 26.8 | 27.3 | 27.4 | 26.6 | 23.7 | 26.1 | 23.2 |
| Render thread on CPU | 19.9 | 18.1 | 18.6 | 18.2 | 17.1 | 17.1 | 18.3 | 16.8 |
| gdrv0 on CPU | 19.5 | 19.2 | 19.1 | 19.2 | 19.4 | 18.3 | 18.7 | 18.3 |
| GPU occupied (upper bound) | 23.6 | 21.5 | 21.9 | 21.5 | 21.7 | 20.4 | 22.2 | 20.1 |
| SwapWait(0) timeouts, ms / swap | 6.8 | 6.6 | 6.7 | 6.6 | 0 | 0 | 0 | 0 |
| Frames in 1 / 2 / 3+ periods | 52/69/5 | 55/76/3 | 56/68/6 | 52/76/3 | 68/60/5 | 92/51/5 | 68/61/5 | 103/48/5 |

Every B frame mean is below every A frame mean; one-period frames rise from ~40 % to 50-65 %.

## What limits Control Center now

With the sleep gone, the render thread idles in CA's run loop between vsync callbacks (B1: 4.8 ms per frame
in `CFRunLoopServiceMachPort < IOMFBServer::thread_body`) and in glthread syncs (CA's two `glGetError` per
frame, 1.3-1.8 ms, the worker is now busier). The frame (~23-26 ms) is set by **gdrv0 (~18.5 ms, freedreno
emit/submit) and the GPU (~20-22 ms occupied)** plus vsync quantisation: SwapEnd -> SEAL is still ~11 ms and
FLIP -> LATCH ~9 ms. The remaining SwapWait cost is CA's page poll (rel -1, ~1.2 ms per swap: the surface of
the previous swap is free only after the current one latched), a real dependency of the 3-page ring.

## Recommendation and install plan

Install j0119 with `SwapWait(0)` latched semantics **on by default** (`sweetfb_wait0=0` to turn it off), as a
new boot_b image with slot b's command line unchanged (the default flips in the kernel), plain reboot check
like task 26. Needs the user's OK (flash). Not done yet.
