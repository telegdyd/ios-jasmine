# M7 closing - 2026-11-03

Closing pass over the M7 items left by `METAL-M7-TRIAL.md` and
`METAL-M7-ADMISSION.md`: ticketed-at-replay in the compositor, j0127
cancelled-SEAL, fault/quarantine, and same-surface pending reuse. The Metal changes
are Metal `327bf2f` (on `9ff68e9`); `git -C mesa/metal show 327bf2f` is
the source of every `mesa/metal` reference below. Build
`xnu/out-mesa-m7close4`, libbgmtl
`05866ab6bd60e44a0974bbc882c62a93ccd89a4da48f654d29aacd14cc920022`, libbgair
`62eed9e44e6556083ad0541f5b3ed62aafa905df08ebf21d2688a8cd9f010807`.
**Not installed**; the compositor remains the M4 pair and async is trial-only. M7
is still partial.

## Scope

The closing set was: admission of a destination first discovered at replay in the
real compositor; the j0127 cancelled-ticket SEAL acknowledgement; fault/quarantine
behaviour; and reuse of a surface whose prior producer was still pending. The
device results below are isolated-process results, not a compositor trial.

## Changes

### Replay-mode log

`bgmtl.m:1452-1462` logs one replay-mode line per process when `BGMTL_BB` or
`BGMTL_ASYNC` is set: `BGMTL replay: async (chlorophyll.replay)`, or
`BGMTL replay: inline (async=0 sync=0 trace=0)` when a predicate is off. Run 7 and
the panel check had the environment line only, no positive replay proof
(`research/metal-m7-trial/run7/results.json`, `replay_thread_seen=false`,
`confirmed=false`; the panel netlogs have no replay line). Async silently goes
inline when `/private/var/tmp/bgmtl.sync` or `bgmtl.trace` exists; the log
distinguishes the modes instead of inferring from the environment.

### Admission accounting

`bg_write_admission.h`: each command buffer now has `_ucount` beside `_tcount` and
`_dcount` (`:31-35`, `:95-106`, `:151`). A deferred destination that becomes
unticketed at replay moves from `_dsurf` to `_ucount` (`:100-101`); a committed
unticketed destination increments it at encode (`:151`). The cap is
`_tcount + _dcount + _ucount` (`:140`), so unticketed destinations count against
it. A replay reticket is always logged (`bg_suspended_event(1)`, `:34`, `:98`); a
failed retry pops `_dsurf` (`:105`).

### Failed submit versus an empty fence

`mesa/darwin/darwin_pipe.c:222-227` records a failed submit and returns `-EIO`, but the pipe
flush returns `void`, so the kernel seqno stays 0. `sweet_gpu_wait(0, ...)` returns
0 immediately (`research/wallpaper-metal/pride2/k/sweet_gpu.c:1501-1518`): the
zero-kfence fence "waited" trivially and the CB reported Completed although
nothing ran. `bgmtl.m:1712-1725` now samples `rwa_submit_failures`
(`air_metal.c:4880-4886`) before `rwa_flush`, reads the fence seqno after it, and
fails the CB with `GPU submit failed; command buffer did not run` when the seqno is
0 **and** `darwin_submit_errors` moved.
A failed submit seals with seqno 0, so tickets take the drain plus ABORT path
(`bgmtl.m:1726-1733`). Test-only `BGMTL_TEST_SUBMIT_ERROR=1`
(`air_metal.c:4892-4915`) fails one pre-kernel submit; ignored with `BGMTL_BB`.

### Async replay crash in run 9

**Observation.** Run 9 P2 (async) killed backboardd with SIGSEGV; P1 (inline, same
build) did not (`run9/results.json`, P2 `CRASH backboardd` 6, P1 0). The fault was
exactly at the end of a `0xF0000` `VM_MEMORY_LAYERKIT` mapping, tag 51:
`0x10ee64000-0x10ef54000`, far `0x10ef54000` (`run9/netlog.txt:91949-91954`).
Symbols: `util_copy_rect` row `memcpy` <- `u_default_texture_subdata` <-
`rwa_texture_write` <- `-[BGMTLTexture rwaTexture]` (`_linSrc`) <-
`rwaTextureSampled` <- `bgReplayFrom` on `chlorophyll.replay`; run6/run7 profiler
metadata gave libbgmtl +0x1cc000 and libbgair +0x1030000. No earlier netlog among
501 scanned had it.

Two fixes, both in `bgmtl.m`:

- Length check: `rwa_texture_region_bytes` (`air_metal.c:2311-2320`) computes the
  bytes a region spans; the refresh refuses with a log when it exceeds
  `buffer length - offset` (`bgmtl.m:2387-2398`).
- Lifetime: async replay reads caller memory for `newBufferWithBytesNoCopy` /
  `newTextureWithBytesNoCopy` through our own `vm_remap` alias (`bg_pin_caller`,
  `bgmtl.m:205-231`), so CA unmapping a layer buffer cannot fault replay. Used at
  `:912`, `:1111`; re-upload (`:1125`) and CPU copies/fills/blits read `_source`
  (`:1122-1124`, `:1323`, `:1326`, `:1660-1662`). Alias released at dealloc
  (`:1118`, `:2258`). Inline is unchanged: no remap when `bg_async_replay()` is false.

**Inference.** This was a lifetime/unmap of caller memory, not a region overrun:
inline reads inside commit, before CA can unmap; async reads later. Run 12, built
with only the length check (`xnu/out-mesa-m7close2`), logged no
`linear texture refresh` refusal, so the failing read was inside the claimed
length. The length check stays as a separate fail-closed guard.

### Same-surface reuse

**Observation.** P25 inline failed 2 of 20 iterations on m7close3 with kernel BEGIN
`-EBUSY` (`-16`) (`research/metal-m7-suspend/close3/p25-native.txt:11`): entries
were released at replay end, but the kernel keeps a sealed ticket's surface busy
until its submit retires, so the next writer reached BEGIN too early.
**Fix.** `bgReleaseAdmissionOwners` now runs at completion, after fence release and
before `bgCompleteFrom`, at both sites (`bgmtl.m:1757-1759` synchronous/trace,
`:1776-1778` asynchronous). The next writer then takes the existing bounded
one-second wait on the committed producer.

## New probes and host tests

`test/bgmtl_render_probe.m`:

- P24 `--cancelled-seal-wait=FILE` (`:149-201`, flag `:311`), 9 checks: encode a
  ticketed clear with the display on, commit after the runner's power-off marker,
  require Completed via the j0127 cancelled ACK, wait for wake, require a different
  epoch, and reuse the same backing with exact pixels.
- P25 `--pending-reuse` (`:203-245`), 3 checks: 20 iterations of a committed
  producer plus an immediate consumer on one imported surface, FIFO completion,
  final pixels from the second clear; then an uncommitted-owner refusal that leaves
  the original producer's pixels intact.
- P26 `--submit-error` (`:247-277`), 3 checks: the synthetic submit failure must
  fail the command buffer, ABORT its ticket, and leave the next imported and plain
  submissions working.

`test/bgmtl_ticket_probe.m` scenario 2 repeats SEAL on the cancelled ticket: the
same seqno returns `0x0` (idempotent ACK), `seqno+1` returns `0xe00002eb`
(`kIOReturnAborted`), not Busy (`:50-57`). Host sanitizer tests PASS under
ASan/UBSan: `write_admission_test` covers the 32 cap with unticketed destinations,
the replay-reticket log and sealed-surface reuse
(`test/write_admission_test.m:313-365`); `ticket_retire_test` covers drain/ABORT
and failed-retirement paths; callback delivery remains PASS. Runner instructions
are in `test/README-m7-closing.md`.

## Device results (isolated, close4)

All in `research/metal-m7-suspend/close4`, one build, each case isolated. Counts are
the probe's `== result: N checks passed, 0 failed`.

| Case | Native | Async | Evidence |
| --- | ---: | ---: | --- |
| Six suite modes (normal, `--bb`, gmem, async, defer, sync) | 47/47 each | - | `suite-*.txt` |
| P23 display-off | 39/39 | 39/39 | `p23-display-off-*.txt` |
| P23 encode-off, commit after wake | 42/42 | 42/42 | `p23-wake-*.txt` |
| P24 cancelled SEAL | 9/9 | 9/9 | `p24-*.txt` |
| P25 pending reuse | 3/3 | 3/3 | `p25-*.txt` |
| P26 submit error | 3/3 | skip (`BGMTL_BB`) | `p26-native.txt` |
| Ticket probe `--display-epochs` | PASS | - | `ticket.txt` |

The async cases printed `BGMTL replay: async (chlorophyll.replay)` themselves
(`p24-async.txt`, `p25-async.txt`), so async replay was positively active there.
Restore was byte-exact each run for the four installed libraries and both env files;
the remote directory was empty and the display was left as found
(`close4.console.txt:214`).

**P24 kernel evidence.** Event 37 shows a display-cancel row (`d=2`) followed by
the same-generation ACK (`d=3`) with non-zero `c` (proven seqno): `c=44751` native,
`c=44753` async (`close1/p24-*-events37.json`); close4 repeats it. That is
kernel-side j0127 evidence, not only the probe's Completed status.

## Fault and quarantine

**Research conclusion, not a test.** The kernel SMMU terminates faults without
reporting them to the GPU (read 0, write dropped, FSR keeps the record;
`research/wallpaper-metal/pride2/k/sweet_gpu.c:977-983`), and logs them only at the
next submit (`:1265-1267`, `:1402`). One ring, no GPU hang recovery:
`sweet_gpu_hang_check` runs only under `sweetgpu_debug` and takes the GPU down, not
recovering it (`:1520-1534`;
`research/t14/t14src/iokit/Kernel/arm/SweetGPU.cpp:893-894`). Prior real hangs
needed a reboot (`NOTES.md:1093-1095`). No real fault test was run; it would cost a
reboot. The M7 contract is covered by P26's synthetic submit failure and
`ticket_retire_test`'s retained/quarantine drain failures. GPU hang recovery is a
kernel task outside M7.

## Ticketed at replay in the compositor

**Observation.** No trial produced a ticketed-at-replay admission. Every suspension
line was `1 deferred, 0 ticketed at replay, 0 unticketed` (`run9/results.json:153`,
`:285` for P1 and P2); the one deferred frame per sleep is replayed long before
wake. **Inference.** The path is the one P23 `--display-wake-wait` async exercises,
which passes 42/42: probe coverage, not compositor observation. Retickets are now
always logged, so any occurrence is visible in the next trial log.

## Trial infrastructure

`research/metal-m7-trial/trial.py` (git-ignored) gained:

- Async confirmation from the replay log, not the env line (`:114-116`,
  `:589-600`, `:1284`), and a stale-marker check for
  `/private/var/tmp/bgmtl.sync`, `bgmtl-bb.sync` and `bgmtl.trace` before any async
  phase (`:604`, `:1202`).
- Retries for read-only queries and swipes only (`:135-138`). Runs 10/11/13/15
  aborted on socket timeouts/resets around `wifip2pd`/`bluetoothd` launches;
  side-effecting commands are never retried.
- P24-based j0127 kernel evidence: a validate P24 run whose bench epoch is still
  current establishes the ACK on this boot (`:467-488`, `:502`).
- `--async-only` to run P2 without P0/P1 (`:2045-2047`).

## Compositor trials (m7close4)

Before the fixes: run 9 (m7close) P2 crashed once (above); run 12 (m7close2, length
check only) P2 was clean with no refusal line. With m7close4, three async-only trials
(`trial.py --async-only`, runs 16-18, kernel evidence from the close4 P24 ACK):

| run | active workload | CB failures / refusals | backboardd pid changes | async confirmed | screenshots non-uniform | restore |
|---|---|---|---|---|---|---|
| 16 | 87.5 s | 0 | none | yes (`BGMTL replay: async`) | 12/12 | byte-exact |
| 17 | 98.0 s | 0 | none | yes | 12/12 | byte-exact |
| 18 | 90.8 s | 0 | none | yes | 12/12 | byte-exact |

Each phase had one `display suspended` diagnostic (deferred 1, ticketed at replay 0,
unticketed 0), no `linear texture refresh` refusal, no QUEUE FALLBACK, reason 16,
GPU fault/hang, CRASH or panic line. The run 18 P2-wake3 screenshot was viewed clean.
P25 was rerun twice more (close4-p25a interrupted, close4-p25b 3/3 native+async).
Three clean runs after one crash in four earlier async runs bound but do not prove the
absence of the crash; the lifetime fix removes the fault class, the length check the
geometry class.

## Remaining / not claimed

- Installation decision: user; async stays uninstalled, no default enablement.
- A real GPU fault was not tested by design; fault/quarantine remains argued from
  kernel configuration and the synthetic submit-failure path.
- Ticketed-at-replay was not observed in the compositor; only the equivalent P23
  isolated path passed.
- No throughput, latency or power claim is made; the counts and P24/P25 results are
  correctness evidence only.
