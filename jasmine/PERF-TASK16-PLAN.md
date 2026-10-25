# Task 16 plan: pipelined rendering and presentation

Working plan for [PERF-TASKS](PERF-TASKS.md) task 16, written 2026-10-25 after the
task-5 threaded context ([report](PERF-TASK5-THREADED-20261025.md)) made the
per-frame `glFinish` the largest wait on CoreAnimation's display thread.
**Status: S0 complete (2026-10-25); S1 not started.**
Nothing here is measured yet unless a step's result says so.

**How to use this file.** Each step below is sized for one agent. Take the next
step whose dependencies are done, set its tracker row to `in progress` with your
name and the clock time, and on finishing fill in the result line (commits, CI
run IDs, capture directories, numbers) and set it to `done`. A step that disproves
the plan's premise sets the gate it feeds to `fail` and stops; do not work around
a failed gate without the user. Read [For every agent](PERF-TASKS.md#for-every-agent)
first: phone lock, battery check, accessory-sync precheck, ground rules, and
"done means on the phone".

## Tracker

| Step | Work | Needs | Phone | Status | Owner / result |
| --- | --- | --- | --- | --- | --- |
| [S0](#s0-establish-the-baseline-and-bases) | Establish the baseline, source bases and patch number | — | read-only | done | Codex, 2026-10-25 15:01 Budapest; installed SHA256 `14e32aea4121e9c8a357da8f5e6322fe572a85f1c22e496990af0e687cb19261`; slot b recorded j0070; base `bfb61629aa90e9e44d85ea929ddffbe6a5a78222`, `/home/teleg/xnu-t16` (`t16`); j0100 reserved. See S0 result. |
| [S1](#s1-critical-path-budget-from-existing-captures) | Critical-path budget from existing captures | S0 | no | todo | |
| [S2](#s2-how-coreanimation-uses-its-swap-surfaces) | How CoreAnimation uses its swap surfaces | — | no | todo | |
| [S3](#s3-surface-lifecycle-audit-and-invariants) | Surface lifecycle audit and invariants | — | no | todo | |
| [G1](#gates) | Gate: is there enough overlap to win? | S1, S2 | — | open | |
| [S4](#s4-design-review) | Design review with the user | G1, S3 | no | todo | |
| [S5](#s5-kernel-sleep-instead-of-spin-in-the-present-path) | Kernel: sleep instead of spin in the present path | S0, S3 | yes | todo | |
| [S6](#s6-kernel-render-tickets) | Kernel: render tickets (surface pending/ready) | S4 | — | todo | |
| [S7](#s7-kernel-present-queue) | Kernel: present queue, SwapWait on flip | S4, S6 | — | todo | |
| [S8](#s8-neutral-boot-of-the-new-kernel) | Neutral boot: new kernel, old library | S5-S7 | yes | todo | |
| [S9](#s9-libsweetca-mode-1-flush-and-submit-no-gpu-wait) | libsweetca mode 1: flush + submit, no GPU wait | S8 | yes | todo | |
| [S10](#s10-libsweetca-mode-2-no-driver-drain) | libsweetca mode 2: no driver drain (tickets) | S9 | yes | todo | |
| [G2](#gates) | Gate: do modes 1/2 gain without regressions? | S9, S10 | — | open | |
| [S11](#s11-conditional-remove-the-swap-surface-limit) | Conditional: remove the swap-surface limit | G2 + S2 | yes | todo | |
| [S12](#s12-matched-validation) | Matched validation, sustained run, user's look | G2 | yes | todo | |
| [S13](#s13-make-it-the-default) | Make it the default, slot b, docs | S12 | yes | todo | |

S1, S2, S3 and S5 can run in parallel (S5 is independent of the queue design and
worth having even if G1 fails). S6 and S7 share `SweetFramebuffer.cpp`/`SweetGPU.cpp`:
one agent, or strictly one after the other.

## What the investigation found (2026-10-25)

### Today's frame on the display thread

1. CA draws through libsweetca. Every 32 draws `kick_after_draw` has the driver
   thread (`gdrv0`, Mesa's threaded context) flush and send Mesa's deferred submits
   to the kernel ([sweetca.c `kick_after_draw`](../mesa/darwin/sweetgl/sweetca.c),
   `sgl_kick` in [sweetgl.c](../mesa/darwin/sweetgl/sweetgl.c)).
2. CA calls flush. `w_Flush` writes shadow targets back and calls **`glFinish()`**:
   the display thread waits for `gdrv0` to drain its queue and submit (the
   "driver drain"), then for the GPU fence ([sweetca.c `w_Flush`](../mesa/darwin/sweetgl/sweetca.c)).
3. CA calls `IOMobileFramebufferSwapEnd` (selector 5). With `sweetfb_sync=1` (the
   default since j0056) the kernel's `AppleCLCD::swap()` runs on CA's thread: it
   **spins** (`IODelay(100)`, up to 25 ms) until the previous flip latched, then
   `present()` -> `directPresent()` -> `sweet_surface_cpu_access()` waits for the
   surface's last GPU job (j0055 `gpuSeqno`, ~0 today because of `glFinish`) and
   `scanScaled()` programs VIG0 (j0058). Hold sets rotate (`fShowHold` ->
   `fRetireHold`), `noteShown()` records the swap as ended.
4. CA's `IOMFBDisplay::can_update_` polls `SwapWait(N)` before drawing into swap N's
   surface again. j0058's rule (`sweetfb_swapwait=1`): N is done once a *later swap
   ended*. A GPU submit writing a surface that is still retiring (later frame
   flipped, not latched) waits in the submit ioctl for the latch, **spinning** up
   to 50 ms (`sweet_fb_gpu_write_wait`).

Sources: [j0055](../xnu/patches/j0055-jasmine-display-waits-for-gpu.patch),
[j0058](../xnu/patches/j0058-jasmine-display-scale.patch), current kernel source
`~/xnu-wifi` (WSL) `iokit/Kernel/arm/SweetFramebuffer.cpp` (`swap`, `showDirect`,
`presenter`, `swapWait`, `retireLatched`, `sweet_fb_gpu_write_wait`).

### The wait budget (threaded2 capture, Control Center A, 4 s CPU window)

From [the threaded-context report](PERF-TASK5-THREADED-20261025.md), about 77 swap
arrivals in the window, 53 ms median interval:

| Display thread, per arrival | ms |
| --- | ---: |
| On CPU (CA + GL validation) | ~22.9 |
| GPU fence wait in `glFinish` | ~10.5 |
| Driver-thread drain in `glFinish` | ~9.1 |
| Runnable, waiting for a CPU | ~6.4 |
| Rest (SwapEnd, run loop) | ~4 |
| `gdrv0` on CPU, per arrival | ~17.7 |

If presentation no longer blocked the display thread, the frame would be bounded by
max(CA thread CPU ~23, `gdrv0` ~18, GPU time per frame, panel period) instead of
their partial sum. **That is a ceiling of roughly 25-30 ms against 53 ms in Control
Center, not a prediction**: GPU time per frame is not measured (only the residual
fence wait is), the swap-surface limit below may serialize the frames anyway, and
Home already showed 765 ms/4 s runnable time, so more concurrency can turn into CPU
contention on the 4 Gold cores.

### Constraints the design must handle

- **C1. Ordering.** With the threaded context and merged submits, when CA's thread
  leaves `w_Flush` without waiting, the frame's last submit may not have reached the
  kernel yet. The surface's `gpuSeqno` then names an earlier kick's job, and
  `present()` or another process's `IOSurfaceLock` would read unfinished pixels.
  Replacing `glFinish` with `glFlush` alone is wrong, not merely slow.
- **C2. Two swap surfaces and SwapWait.** CA draws into two swap surfaces (ids 2
  and 4, GPU.md "The flicker found"). If SwapEnd returns before the flip, "a later
  swap ended" no longer means the earlier surface left the panel: CA would draw into
  the surface on the panel, and `sweet_fb_gpu_write_wait` returns at once for a
  *shown* (not retiring) surface. SwapWait must become "a later swap's flip was
  programmed". With two surfaces CA may then have to wait for frame N's GPU work
  before it starts N+1, which removes most of the overlap unless CA prepares N+1
  before it needs the surface. Unknown: S2 answers it.
- **C3. Write-wait on the driver thread.** Since task 5, GPU submits run on
  `gdrv0`; `sweet_fb_gpu_write_wait` now stalls the driver thread (and spins a core)
  until the latch.
- **C4. Spinning.** `swap()`, `showDirect()` and the write-wait poll the MDP's
  CTL_FLUSH bits with `IODelay(100)`; GPU completion is polled too (`sweet_gpu_wait`,
  `delay(50)`; no GPU interrupt is used). On a CPU-bound 4-core system a spinning
  kernel thread costs render time.
- **C5. The old presenter thread.** `sweetfb_sync=0` still starts a kernel presenter
  thread with a two-deep queue (`fQRec`, `presenter()`, `showDirect()`). It predates
  j0058's retire logic and spins for the latch; useful as a starting point, not
  usable as it is.
- **C6. Latch signal.** jasmine has no physical frame counter mapping (`fIntf1` is
  null, topaz-only); the latch is seen only by polling CTL_FLUSH, with a 50 ms
  timeout fallback (framebench events 14/15). Correctness of the new SwapWait rests
  on this signal; zero 50 ms fallbacks were seen in the first framebench session.
- **C7. GPU completion time.** Framebench event 21 records when someone *observed*
  the fence, not when the GPU finished, so GPU time per frame is not measured.
- **C8. Genuine waits stay.** `w_Finish`, `w_FinishObjectAPPLE`, `glReadPixels`,
  shadow write-back and CPU locks must keep their full semantics.
- **C9. Sources and numbers.** `~/xnu-8796` `jasmine-merge` is at j0070; the newest
  kernel line is `~/xnu-wifi` (`wifi`, j0071-j0099) plus framebench (`codex/framebench`,
  also numbered j0099). The patch number j0099 is used twice. Assign task 16's patch
  only after S0 checks every branch; the next free number is at least j0100.

## Proposed design (to be confirmed in S4)

**Surface states:** free -> rendering (CA's GL work queued) -> submitted (last job's
seqno known) -> queued for present -> scanning (on the panel) -> retiring (later
flip programmed, not latched) -> free.

**Invariants** (S3 makes this list complete and checks the code against it):

1. Never program a flip to a surface whose frame is not fully submitted and complete.
2. Never let the GPU write a surface that is scanning or retiring.
3. `SwapWait(N)` is done only when a later swap's flip has been programmed.
4. A surface is held until it is free (no reuse, no free, no pool give-back earlier).
5. CPU readers (`IOSurfaceLock` without AvoidSync, display copies) wait for pending
   *and* submitted work.
6. The queue holds at most one frame beyond the one scanning (bounded latency); a
   frame whose ticket times out is dropped, never shown, and counted.
7. Every wait sleeps; none spins longer than a few microseconds.
8. Both modes switch off at runtime-free cost: kernel boot-arg and libsweetca env.

**Mechanism:**

- **Kernel present queue** (`sweetfb_queue=1`): SwapEnd takes holds, enqueues the
  record and returns. A presenter thread sleeps until the queued frame's surface is
  ready (ticket cleared, `gpuSeqno` complete) and the previous flip latched, then
  programs the flip and rotates the j0058 hold sets; `noteShown` moves to that point.
  Wakeups come from the submit and completion paths, or a short sleep while polling
  CTL_FLUSH; a GPU completion interrupt is an optional later improvement.
- **Render tickets** (two new SweetGPU user-client selectors): on CA's thread,
  `w_Flush` marks the target surface *pending* (one cheap call, before SwapEnd can
  happen); a driver-thread callback queued after the flush sends the deferred submits
  (as `sgl_kick_driver`) and then marks the surface *ready at the client's last
  submitted seqno*. This fixes C1 without waiting on CA's thread and without
  interposing CoreAnimation's IOMobileFramebuffer calls.
- **libsweetca modes** (`SWEETCA_PIPELINE`): 0 = today (`glFinish`); 1 = flush and
  wait only until the frame is submitted (driver drain, no GPU wait; no tickets
  needed); 2 = tickets, no drain wait. Mode 1 is the safe first step and isolates
  how much of the gain is GPU overlap versus driver overlap.

Rejected for now: interposing `IOMobileFramebufferSwapEnd` so the driver thread
calls it (shared-cache calls may not be interposable, and SwapEnd's caller-visible
results would change); a blind `glFinish` -> `glFlush` swap (C1); a larger
batch-cache or timeout instead of ordering.

## Gates

- **G1 (after S1 + S2):** proceed to implementation only if (a) the display
  thread's GPU-fence + drain wait is still a large share of the frame on the current
  library, and (b) S2 shows CA can do useful frame work before it needs the next
  swap surface, *or* that a third swap surface is achievable. If only (a) holds,
  re-scope around S11 with the user. If (a) fails, stop and report; S5 still stands
  on its own.
- **G2 (after S9 + S10):** at least one mode shows shorter presentation intervals
  in matched captures with zero new held draws, no dropped-frame storm and bounded
  queue latency. Otherwise record the result and stop; do not install.

## Steps

### S0. Establish the baseline and bases

**Goal:** everyone works from the same facts.

- Record the installed libsweetca hash (expected `14e32aea…`, Mesa CI `40170072509`,
  threaded context + leak fix) by read-only retrieval, and which image slot b runs
  (NOTES.md "Slot b = iOS"; the framebench99 image was booted temporarily).
- Decide the kernel source base for task 16 (expected: `wifi` `f7c66dd` + framebench
  j0099 from `codex/framebench`) and create a worktree
  (`git -C ~/xnu-8796 worktree add ~/xnu-t16 -b t16 <base>`).
- List every `jasmine-jNNNN` on all branches and in `xnu/patches/`; reserve the first
  free number for task 16 in PERF-TASKS and here (j0099's double use is noted in C9).
- Confirm `topaz_surface_drawn()` returns at once on jasmine (`gGPULock` null?).

**Done when:** this file's S0 row holds the hashes, base commit, worktree path and
the reserved number. No boot needed beyond the read-only check.

### S1. Critical-path budget from existing captures

**Goal:** a per-frame budget for the current library, offline.

- Inputs: `research/framebench/20261025-threaded2/` and the matching symbols; if
  the installed final library differs from the fix+dump build used there, say so.
- Per swap arrival in each usable segment (CC A/B, Home A/B, Spotlight repeat): the
  display thread's CPU, driver drain, GPU fence wait, time inside SwapEnd (events
  11->12), SwapWait polls that found "not done" (event 18), runnable time; `gdrv0`'s
  CPU and its time in `sweet_fb_gpu_write_wait` (event 19); GPU job submit->observed
  completion (events 20/21, labelled as an upper bound per C7).
- The overlap ceiling per segment as in the table above, with its assumptions.

**Deliverable:** a section "S1 result" appended to this file (tables, script path
under `research/t16/`). **Done when:** G1(a) can be answered with numbers.

### S2. How CoreAnimation uses its swap surfaces

**Goal:** know whether CA can overlap frame N+1's work with frame N's presentation.
Offline, in the iOS 16 shared cache (QuartzCore, IOMobileFramebuffer), using the
existing `ipsw` workflow (NOTES.md "GUI path research").

- How many swap surfaces `IOMFBDisplay`/`CA::WindowServer` allocate, and what sets the
  count (a framebuffer property, a default, the swap queue depth).
- In a frame: which CPU work (layer tree commit, preparation, offscreen passes)
  happens before CA checks `can_update_` and binds the swap surface; what CA does
  when `can_update_` says no (skip the tick, retry, block).
- What SwapEnd's caller uses from the call (return value, out data) and how SwapBegin
  IDs relate to SwapWait IDs (our "never begun" branch in `swapWait`).

**Deliverable:** "S2 result" section with symbol names/addresses and the answer to
G1(b). No phone.

### S3. Surface lifecycle audit and invariants

**Goal:** the complete state machine and hazard list before code changes. Offline.

- Kernel: every place that sets/clears `fPendHold`, `fShowHold`, `fRetireHold`,
  `fQHeld`, `gpuSeqno`, `drawn`, pool take/give and `sweet_hold`; the sync and
  presenter paths; `swapWait`; `sweet_fb_gpu_write_wait`; IOSurfaceLock;
  what happens on power-off, console takeover, panic and multi-layer (composeFit)
  frames.
- Mesa/libsweetca: TC flush paths (`PIPE_FLUSH_ASYNC`, fences, `callback`), when
  darwin's merged submits reach the kernel, the kick, shadow write-back, readbacks,
  and which IOSurface is the frame's target at `w_Flush` (needed for tickets).
- Interactions: task 14's selector-2 buffer-free freeze (longer holds), task 5's
  batch/fence leak fix (fences outliving batches).

**Deliverable:** "S3 result" section: state diagram, the invariant list checked
against code (file:function for each), hazards with the mechanism that covers them.

### S4. Design review

Update "Proposed design" from S1-S3 (queue depth, ticket calls, SwapWait rule,
write-wait handling, timeouts, counters, boot-args/env names, framebench events for
ticket/queue/flip). Write the test plan for S8-S12 with the risk of hangs stated.
**Done when:** the user approves the design in chat (quote and time in the row).

### S5. Kernel: sleep instead of spin in the present path

**Independent of the queue; may ship on its own.** Replace the CTL_FLUSH spins in
`swap()`/`showDirect()` and the 100 us spin in `sweet_fb_gpu_write_wait` with
sleeping waits (short `assert_wait_deadline`/`IOSleep`-style waits, or a wakeup from
the vsync/latch timer), keeping every timeout and the j0058 semantics. Add counters
for time slept versus spun. Measure: one framebench capture before/after on the same
day (after the precheck), plus held draws and the SWEET FB 600-frame line.
**Done when:** CPU time in those paths is gone from the profile, no new held draws,
no flicker by the user's eye; then it rides along with S13 (or is installed earlier
if the user wants it alone).

### S6. Kernel: render tickets

Two SweetGPU user-client selectors: *pending(surface id)* and *ready(surface id)*,
the latter setting `gpuSeqno` to the calling client's last submitted seqno and
clearing pending; a generation counter so a stale ready cannot clear a newer pending.
`sweet_surface_cpu_access` and `directPresent` wait for pending to clear (bounded;
timeout logged and counted, never shows the frame). Framebench events for both.
Unused by today's library, so behavior-neutral. Build on CI in the S0 worktree.

### S7. Kernel: present queue

`sweetfb_queue=1` (default 0 in this step): SwapEnd enqueues (depth 1 beyond the
frame on the panel, blocking SwapEnd only when full), the presenter waits as in the
design, programs the flip, rotates holds as j0058 does, calls `noteShown` at the
flip; SwapWait done only after a later flip was programmed; ticket timeout drops the
frame and releases its holds. Counters: queue depth, SwapEnd->flip and flip->latch
times, drops, write-waits. Same CI build as S6 if done by one agent.

### S8. Neutral boot of the new kernel

Test kernel (`fastboot boot`) with S5-S7, today's library (`glFinish` on), first
`sweetfb_queue=0` then `=1`. Expected: no change in arrivals/intervals beyond noise,
zero held draws, no drops, no flicker, no hang over a 10-minute uiround series.
Say before the round that it may hang (`sweetwdt=20`). **Done when:** both settings
are neutral; any difference is explained before S9.

### S9. libsweetca mode 1: flush and submit, no GPU wait

`SWEETCA_PIPELINE=1`: `w_Flush` keeps shadow write-back, then flushes and waits only
until the frame's submits are in the kernel (driver-thread callback + fence check, no
GPU wait). Requires `sweetfb_queue=1`. Mesa CI, `sweetgpu_gltest` 7/7, install as a
test library (keep the rollback copy), one framebench capture against S8's
queue-on baseline. Watch held draws, ticket/queue counters and the user's eye.

### S10. libsweetca mode 2: no driver drain

`SWEETCA_PIPELINE=2`: pending call on CA's thread in `w_Flush`, ready call from a
driver-thread callback after the kick; CA's thread does not wait for the drain.
Same tests as S9, plus a CPU-reader test: IOSurfaceLock of the swap surface from
another process right after a flush (`sweet_shot` or a small test) must see the
finished frame.

### S11. Conditional: remove the swap-surface limit

Only if S2 and G2 show that two swap surfaces serialize the frames or that
write-waits dominate `gdrv0`. Options to scope with the user: a third swap surface
(if S2 found the switch), or a GPU-side wait (the submit carries a wait on a latch
counter that the presenter writes, instead of blocking the ioctl). Separate design
note and approval; do not start it from this plan alone.

### S12. Matched validation

On one settled boot per variant (accessory-sync precheck), two framebench captures
each: baseline (queue off, mode 0), and the winning mode. Report presentation
intervals (median, p95, p99), arrivals and CTL-clear rates, SwapBegin->latch and
SwapEnd->flip latency, queue depth, drops, held draws, CPU per arrival on both render
threads, and spin/sleep counters. Label swap arrivals and CTL clears as proxies (C6).
Then a 10-minute uiround series without a hang, GL and CA tree tests (the known
image-orientation mismatch is pre-existing), and the user's visual check.

### S13. Make it the default

Kernel defaults (`sweetfb_queue=1` or no boot-arg needed), libsweetca default mode,
the patch exported as the reserved `jNNNN`, cherry-picked onto the kernel line slot b
uses, slot b image rebuilt and flashed per "Done means on the phone", first boot
checked, then NOTES.md "Slot b = iOS", GPU.md (baseline and result) and PERF-TASKS
task 16 updated. Keep the env/boot-arg switches as the rollback path.

## Risks and rollback

- **Flicker or torn frames** if an invariant is wrong: held-draw counter, user's eye;
  rollback `sweetfb_queue=0` / `SWEETCA_PIPELINE=0`.
- **Hangs** from a lost ready call or a wedged presenter: every wait bounded and
  counted; `sweetwdt=20`; say before risky rounds. Never reload modules live.
- **More CPU contention** (Home runnable time) can eat the gain: S1 and S12 report
  runnable time; task 6 (8 cores) and task 21 are the levers, not this task.
- **Added latency** from queueing: depth is bounded to one frame and measured.
- **Task 14** (selector-2 buffer-free freeze) may surface more often with longer
  holds; take its census before rebooting if a freeze occurs.

## S0 result (2026-10-25, complete)

**Source base:** `/home/teleg/xnu-t16`, branch `t16`, clean at
`bfb61629aa90e9e44d85ea929ddffbe6a5a78222`. Created from Wi-Fi
`f7c66ddc6c4e25c18a6052914f3354cc6e0d9170`, then cherry-picked framebench
`fbcaec907adc0c73b0f5d59d74f2b28db1381b06` without conflicts. The latter was
originally based on `fde1ca9` (j0070); this new base retains Wi-Fi j0071-j0099,
including wrapped-surface unwiring, plus framebench. `git diff --check HEAD^ HEAD`
passes. Existing source worktrees were not changed. No new build or CI run;
this combined source base has not been compiled or booted.

**Reservation: j0100 for task 16.** Audited all refs reachable by `git log --all`
in the WSL kernel repository, all local/remote host-repository branches' exported
patch paths, current `xnu/patches/`, and the task reservations. Highest used number
is j0099, with two distinct uses: `f7c66dd` (unwired wraps/reboot dump) and
`fbcaec9` (framebench). Lower gaps already reserved for other tasks remain reserved.
Ignored inventory evidence: `research/t16/kernel-patch-inventory.txt` and
`research/t16/exported-patch-inventory.txt` (current checkout only for the latter).

**Installed library: verified by fresh read-only retrieval.**
`research/t16/libsweetca-installed.dylib` is 19,234,288 bytes, SHA256
`14e32aea4121e9c8a357da8f5e6322fe572a85f1c22e496990af0e687cb19261`,
matching Mesa CI `40170072509`, the local final artifact
`xnu/out-mesa-t5tcfinal/libsweetca.dylib`, and the previous readback
`research/t5tc/libsweetca-final-installed.dylib`.
The earlier threaded2 capture used the fix+dump library, whose local artifact
`xnu/out-mesa-t5tcfix/libsweetca.dylib` hashes to
`bb543dc9b37fa10411ce87f609d34eec633575909257b5b98e0e7ef8949e0363`.
The current temporary boot now loads the final on-disk library; do not conflate
it with the fix+dump library in that saved capture.

**Persistent slot b:** latest recorded flash is j0070, kernel CI `40059091430`,
`shim/out/shim-boot-j70-slotb.img` (17,354,752 bytes; local SHA256
`97c57697df86a8bfd6922111f63c89ad7d7d8db9928e1a1023910f6d621c0f88`),
first-boot log `logs/netlog-j70-slotb.txt`. This supersedes the older j69b paragraph
under "Slot b = iOS". The framebench99 image was a temporary boot, not a slot-b
flash. Current partition contents were not independently retrieved in S0.

**topaz_surface_drawn(): confirmed no GPU wait on jasmine, by source.** In
`iokit/Kernel/arm/RedwoodGPU.cpp:227`, it returns true unless both `surface->drawn`
is nonzero and static `gGPULock` is non-null. The sole allocation of `gGPULock` is
in `RedwoodGPUStart():332`, called only by `topaz_adreno_thread()` in
`TopazAdreno.cpp:1230`. `AppleCLCD::start()` in `SweetFramebuffer.cpp:487-491`
invokes `topaz_adreno_init()` only inside `if (topaz)`; jasmine follows the
`jasmineMdp()` path. Thus jasmine leaves this lock null and the function returns
without waiting. Its actual synchronization is the SweetGPU `gpuSeqno` path.

**Device check and final state:** user granted exclusive access and allowed skipping
the phone lock, then clarified the phone had been in the charging shell and put it
in fastboot. `fastboot getvar current-slot` returned `b`. One temporary
`fastboot boot shim/out/shim-boot-framebench99.img` succeeded (send 0.476 s,
boot 0.166 s); image SHA256
`6ce2603f1b23ca3c9fed827dcb4e4d1115a6b21aaadb9ad854471640fd30281b`,
existing kernel CI `40160680219`. This is the existing instrumented image,
not a build of the new combined source base. Ignored evidence:
`research/t16/boot.txt`, `boot-final.txt`, `netlog-client.txt`,
`netlog-final-client.txt`. Boot log shows GPU self-test expected values and
backboardd creating its Mesa FD512 context. Battery line: 59%, 3826 mV,
external=1, charging=1. No visual UI check claimed. Phone left in this iOS boot;
no collectors left running, no lock held. No flash, software installation,
benchmark, clock change or new CI run. Accessory-sync profiling was unnecessary:
S0 reads identity only and makes no performance measurement. S1 has not started.
Results are kept here, per the user's instruction; NOTES.md files are unchanged.
