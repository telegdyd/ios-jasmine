# M4 — bounded kernel submission groups

The Darwin backend now groups deferred submissions by a conservative budget of
512 buffer references and 128 command streams, replacing the original per-batch
30-buffer CPU-cost heuristic. Enabled by default; `SWEET_SUBMIT_BATCH=0` restores
the original policy. Patch `0028` contains the policy; patch `0027` contains the
opt-in inventory. Metal and GL already share this backend and its
`no_implicit_sync=true` handling for imported IOSurfaces.

## Dependency and submission inventory

`BGMTL_SUBMIT_PROFILE=1`, then creation of
`/private/var/tmp/bgmtl-submit-start`, captures up to 120 replayed command buffers
or eight seconds, checked at command-buffer end. One CSV per process is written
to `/private/var/tmp/bgmtl-submit-PID.csv`. A fixed 16,384-event table stores
records without per-event logging, allocation or clock reads. Overflow is counted;
the analysis tool rejects captures with dropped records or incomplete buffers.
The deadline is activity-driven. Disabled instrumentation still adds conditional
checks; these captures are not CPU benchmarks.

This inventory requires serialized inline replay. TLS excludes completion
workers and unrelated GL contexts. The end hook follows ticket sealing so it
includes the compositor's deferred-submit drain. Non-ticket command buffers can
submit later on completion workers; their captures do not establish complete
submission counts. Batch numbers and dependency masks are driver identities,
not GPU timestamps or display-frame IDs. Do not combine graph identities across
different screens/processes. No pixel payloads are recorded.

CSV columns `a` through `h` depend on the event:

| Event | a | b | c | d | e | f | g | h |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| begin | encoded passes | 0 | 0 | 0 | 0 | 0 | 0 | 0 |
| batch events | batch sequence | other sequence | resource address | draw count | dependency mask | detail | width | height |
| enqueue | userspace fence | 0 | BO count | command count | previously deferred commands | fence-FD request | shared implicit-sync hazard | policy permits deferral |
| group-capacity | next fence | 0 | prospective BO upper bound | prospective command bound | 0 | 0 | 0 | 0 |
| drain | 0 | 0 | deferred command count | 0 | 0 | 0 | 0 | 0 |
| kernel | last userspace fence | merged batches | union BO count | actual IB count | request bytes | 0 | 0 | 0 |
| kernel-result | userspace fence | kernel sequence | return code | 0 | 0 | 0 | 0 | 0 |

Batch events include framebuffer changes, clears, context flushes, read/write
dependencies, dependency flushes, and sysmem/GMEM/nondraw selection. Dependency
flushes finalize independently executable GPU streams; they are not necessarily
kernel calls. The initial capture has 957 batches but only 164 kernel calls.
It includes 745 read dependencies, 168 write dependencies and 170 dependency
flushes. These are required ordering relationships, not evidence for dropping
barriers. Sixty-four enqueues hit the original 30-BO heuristic.

Summarize with `python tools/g2/metalsubmit.py CAPTURE.csv --json SUMMARY.json`.
Its legacy-policy projection replays the same recorded finalized batches through
the old 30-BO/128-command rule, retaining explicit drains and compositor CB-end
drains. It reproduces all 164 calls in the original-policy capture. A projection
is a counterfactual call count, not measured CPU time or a second rendered run;
it assumes the recorded batch stream and inline compositor drain boundaries.

Final 512-reference capture: **120 command buffers, 1,388 encoded passes,
1,473 finalized batches, 121 kernel calls**, zero lost records and zero failed
submissions. All 1,473 enqueues permit deferral; one group-capacity drain remains.
Largest actual kernel request: 133 BOs and 40 IBs. On this **same batch stream**,
the old-policy projection yields **157 calls**, 36 more (22.9%). This establishes
the avoided grouping operations in the model; the 121 calls are observed.
The earlier original-policy window had 982 passes and 9,623 batch draws; the
final window has 1,388 passes and 7,652 draws. Do not interpret their raw 164/121
call totals as a matched update or CPU comparison.

## Safety boundary

The pre-append check counts pending BO references conservatively, including
duplicates and space for the new primary's command-ring BOs. It drains the
existing list **before** appending a batch that would exceed the group budget.
A single oversized batch retains immediate-submit behavior. Checking only after
append would be insufficient: the backend submits the entire list even when
the newest batch fails `should_defer()`.

The kernel supports 1,024 BOs and 240 IBs (j0054); merged groups remain below
those limits. Command counting conservatively includes an extra primary command.
Different pipes still drain separately. Fence-FD/shared-hazard checks, CPU maps,
explicit fence drains and render-ticket sealing retain their existing paths.
The same ordered streams and union resource references reach the existing
backend. This changes kernel-call grouping, with no GPU batch merge, draw-order
change, framebuffer-fetch barrier removal, MSAA change or asynchronous replay.
Deferral never extends beyond the existing inline compositor CB-end drain.

An initial 256-reference candidate fragmented groups excessively: 156 observed
calls versus 140 projected with the old policy on that candidate's batch stream.
It was not installed. The final budget is 512 references. Different UI windows
contain different draws and passes; raw totals across windows cannot establish
a matched frame speedup. Existing baseline2 is retained; no new frame benchmark
or aggregate CPU/FPS improvement is claimed.
No end-to-end tail-gap or submit-to-fence latency comparison was collected.
The unchanged explicit drain boundaries bound deferral, but do not prove a
latency improvement. Timing attribution remains separate M8 work.

## Validation

- VM `m4inventory` PASS (17 s), `m4groups` PASS (13 s), `m4ready`, `m4final`
  and `m4verify` PASS (12 s each). Final policy build: `m4bounded` PASS (14 s). No CI.
  An intermediate staging attempt used an already-patched generation base and
  failed to apply; it was corrected before building or testing that revision.
- Final 512-reference candidate: normal and compositor GPU suites **32/32**
  each. Opt-out compositor suite also **32/32**.
- New P19 follows an 80-pass render-target-to-sampler chain across two command
  buffers, with blue poison clears in every destination. **Zero wrong /40,960
  values** in each mode. Existing target-switch/recreation, framebuffer fetch,
  mutable/compressed uploads, depth and derivative-edge tests pass.
- Four-sample memoryless color/depth/resolve: three iterations with grouping
  enabled and three with opt-out, exact red center / blue corner in both.
- Shared GL suite: `PASS: all` in sysmem and forced-GMEM modes.
- Inventory ASan/UBSan checks pass for disabled collection, overflow/loss
  accounting, deadline and 120-CB termination. Analysis tests reject dropped,
  incomplete and failed-submission evidence.

Ignored captures, original M3 runtime backups and exact restoration readbacks
are under `research/metal-m4/`. Final artifacts: `xnu/out-mesa-m4bounded`.

## Activation

Metal hooks/test commit: `91d1aa9`. Both final libraries are installed in
`/usr/local/bin` and verified byte-for-byte after installation:

- libbgair SHA256: `95cea7f9af4fb68dafe552e28216209afdd763113cb46bd07834cbcebc928189`
- libbgmtl SHA256: `3d91c9f625140fc79be442ae087449a3636f3ce363bafe1fa9720d58967c9666`

Backboardd restarted as 14945. The environment is byte-identical to the original:
`CA_DISABLE_FRAMEBUFFER_COMPRESSION=1` only, with profiling disabled and no
submission-policy override. Benchmark/profiler are idle; GPU completed 13973/13973.
Maximum final TSENS reading is 69.6 C after correctness workloads; it is not a
performance-comparison window. The original M3 pair/environment was restored
byte-exact after each of the three diagnostic windows before final activation.
Temporary test binaries/libraries and the three inventory CSVs were removed.
The final cleanup also tried to unlink the trigger already removed by capture
restoration and received ENOENT; installation/readback had already succeeded.
The phone remains running iOS. No reboot, flash, partition, kernel or clock
changes, and no physical-panel validation claim.
