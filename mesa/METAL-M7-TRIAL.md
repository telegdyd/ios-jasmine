# M7 compositor trial - 2026-11-02

First bounded trial of the M7 candidate on the real compositor. Run 6 completed
P0/P1/P2; runs 1-5 aborted on harness bugs, not on the candidate. **Not installed.**
The compositor remains the M4 pair; async was trial-only. The trial script is
ignored at `research/metal-m7-trial/trial.py`; its `results.json`, `netlog.txt`
and run artifacts are ignored under `research/metal-m7-trial/`.
## Setup
- Candidate `xnu/out-mesa-m7admissiondone`: libbgair `9306470194d935d6...c34b`,
  libbgmtl `d9cfc18b14b96340...2e72`.
- Installed M4: libbgair `95cea7f9...189`, libbgmtl `3d91c9f6...666`; env only
  `CA_DISABLE_FRAMEBUFFER_COMPRESSION=1`. Wallpaper `0d9fb5a2.../eaf44cde...`,
  env `BGMTL_POSTER_SDR=1`; never written.
- Kernel: temporary m7ack image. The launchd boot-args in the console ring match
  `shim/out/payload-m7ack-m7ack.img`'s payload exactly and do not match the
  installed boot_b image; the ring also contains the M7-admission session. j0127
  is therefore present (j0127 cancelled-ticket ACK patch).
- Phases, each after a backboardd restart: P0 installed M4 + original env; P1
  candidate inline; P2 candidate + `BGMTL_ASYNC=1`. P2 inherited the P1 pair; it
  did not rewrite the libraries.
- Same workload each phase: 15 s home swipes, five Control Center open/close
  cycles, three display sleep/wake cycles, screenshots after wake and at end.
- Thermal pacing: cooldown to <55 C before a phase (180 s cap); pause at >=72 C,
  resume at <60 C (240 s cap, abort on cap); hard abort at >=80 C. P0/P1/P2
  cooldowns 5.11/70.38/75.36 s; thermal pauses 0/5.72/11.08 s. Active workload
  84.62/77.38/75.48 s (pause time excluded).
- Harness issues fixed across runs 1-5 are listed at the end. Run 6 restore was
  byte-exact for the four libraries and both env files; the remote temp directory
  was empty and the display was left on.
## Results
Ticket deltas are first-to-last `SWEET FB: tickets` lines within the phase slice.
Held/submits are sums of the periodic `SWEET GPU: backboardd` lines, not total jobs.

| Phase | active/paused s | ticket d begin/seal/abort | epoch | sleep/wake | CB failures | held/submits | faults/crashes | reason16/fallback |
| --- | --- | --- | --- | ---: | ---: | --- | ---: | ---: |
| P0 M4 | 84.62/0 | +1046/+1047/0 | 25 -> 28 | 3 | 0 | 20/1324 | 0 | 0 |
| P1 inline | 77.38/5.72 | +1086/+1087/0 | 28 -> 32 | 3 | 9 | 21/1151 | 0 | 0 |
| P2 async | 75.48/11.08 | +724/+724/0 | 33 -> 36 | 3 | 9 | 820/842 | 0 | 0 |

Absolute ticket abort=457 and error=231 are boot-cumulative and unchanged; stale
and timeout stayed 0. Epochs advance on display cancellation (`sweet_ticket_cancel`
in `xnu/patches/j0110-jasmine-render-tickets.patch`). P1's +4 includes the phase
restart transition; P0 and P2 advanced by 3 over their three sleep/wake cycles.
All guard lines were `q/s/r 0/0/0`; no reason-16 drop or queue fallback occurred.
## Policy review finding: display-off refusal
**Observation.** During each display-off interval the candidate failed three
command buffers, three times per phase: 9 in P1 and 9 in P2. Each line is:

`command buffer failed: imported destination N BEGIN refused (-45); no writes replayed`

The value is `-ENOTSUP` from `darwin_ticket_begin` (`mesa/darwin/darwin_device.c:65-66`)
when `darwin_ticket_query` reports capability bits other than the full 15. While
the display is asleep the render tickets are suspended, so the query cannot offer
the queue capability. This happens **before** any kernel BEGIN: no ticket is
opened and the kernel ticket begin/seal/abort counters do not move. P0's M4
runtime logged `render tickets: begin failed -45` three times and continued
(log-and-write); the candidate fails the whole command buffer with no writes.

**Risk, not observed.** CoreAnimation is not known to observe the command-buffer
Error. The refused surfaces can therefore keep stale content, and a later partial
redraw using Load (the M6 feedback case) could expose it after wake. This was not
seen: screenshots failed for an unrelated size reason (below) and there is no
panel check yet. Display-off writes cannot scan out, so refusing them protects
nothing on the panel. A candidate policy direction, **not implemented**, is to
distinguish "capability suspended/display off" from a real ownership refusal
without weakening protection on wake. That would need proof that no unsealed
generation is presented after wake and an explicit epoch semantics argument; it
must not turn a real pending/unknown owner into a silent write.
## Async P2
**Observation.** `BGMTL registration: BGMTL_ASYNC=1` was read from
`bgmtl-bb.env`; `BGMTL_BB` is set by `bgmtl_sweet_inject.m:113`; no trace or
sync mode was used. The worker queue is named `chlorophyll.replay` in
`bgmtl.m`. The profiler did not directly identify that thread: `SWEET CLPC`
top-5 and `p2-prof.meta` contain no such name, and GCD queue labels are not
pthread names. `replay_thread_seen=False` is a tooling limitation, not evidence
that async was off.

**Inference.** The SweetGPU counter `drew into a surface the display holds`
(j0056/j0109) changes from 20/1324 in P0 and 21/1151 in P1 to **820/842 in P2**.
This is consistent with replay completing on a worker after display hand-off.
It is not thread-level proof. Ticket live/high was similar between phases
(P2 live=1 in 7/8 samples vs P1 6/10).
## Not established
- Panel correctness and visual acceptance; screenshots were all
  `sweet_shot: 0 surfaces of 1125x2436` because the compositor presents 828x1792.
  The right invocation is `sweet_shot -s OUT 828 1792`; this is a tooling fix,
  not evidence from run 6.
- The j0127 cancelled-SEAL acknowledgement path (no cancellation ACK case occurred).
- True GPU fault/quarantine behavior; no fault, hang, panic or `CRASH backboardd`.
- Same-surface pending-reuse refusals; none occurred.
- That the 9 display-off refusals are harmless to later loads/panel content.

## Harness issues fixed in runs 1-5

- Run 1: restart/wake failed; single press then 8 s poll, no blind double press.
- Run 2: `key 3` is Home, not power; power is `key 0` with a 50 ms hold.
- Run 3: 76 C abort; added 72/60/80 C pacing and in-place partial phase records.
- Run 4: `gpu pc` history `collapse (display off)` was read as current state; now
  only the first status line is parsed.
- Run 5: a failed `sweet_shot` aborted the trial; screenshots are now non-fatal.

## Next

1. Decide the display-off admission policy: suspended capability versus real
   ownership refusal, with wake-epoch/presentation proof.
2. Rerun with `sweet_shot -s OUT 828 1792`; obtain panel/user checks after wake
   in both candidate-inline and candidate-async phases.
3. Exercise j0127 cancelled-SEAL, true fault/quarantine, and same-surface
   pending-reuse refusals.
4. Only then consider installation; no default async enablement follows.
