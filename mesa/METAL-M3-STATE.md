# M3 — unused batch state emission

Implemented on 2026-11-02 (Metal hooks/tests `ccb3cc7`). Forced-system-memory,
single-sample a5xx batches omit
the binning command stream that bypass rendering never executes. Actual draw
state and resource/dependency tracking retain their existing paths. The change
is enabled by default; `SWEET_A5XX_SKIP_BINNING=0` restores binning emission.

## Inventory and decision

`BGMTL_STATE_PROFILE=1`, followed by creation of
`/private/var/tmp/bgmtl-state-start`, records one aggregate inventory per process.
Collection ends after 120 replayed command buffers or eight seconds, checked at
command-buffer end. Results go to `/private/var/tmp/bgmtl-state-PID.csv`.
Replay serialization is required; this is a diagnostic for the current inline
replay configuration. It does not establish asynchronous replay safety.

Fixed storage records encoded render passes (including empty passes), driver
draws, batch creations/finalizations, draws per finalized batch, dirty-state bit
counts, tracking calls, resource reads/writes and actual resource-set insertions.
The histogram includes zero-draw batches and groups eight-or-more draws together.
No payloads or per-draw logs are produced. Disabled collection leaves counters
untouched; no clocks or timers are read on each draw. Counter instrumentation
still adds conditional checks, so these captures are operation inventories,
not CPU benchmarks. The deadline is activity-driven; an idle process does not
write an unfinished capture until another command buffer ends.

Two bounded Home/Control Center diagnostic windows produced:

| Operation | Inventory before change | Optimized inventory |
| --- | ---: | ---: |
| Command buffers | 120 | 120 |
| Encoded render passes | 1,089 | 1,089 |
| Driver draws | 10,064 | 6,885 |
| Created / finalized batches | 1,052 / 1,052 | 1,050 / 1,050 |
| State emissions | 20,128 | 6,885 |
| **State emissions per draw** | **2.00** | **1.00** |
| Program emissions | 17,608 | 6,256 |
| Resource reads / already referenced | 13,522 / 7,787 | 11,525 / 6,400 |
| Resource writes / same writer batch | 4,084 / 2,008 | 3,958 / 1,880 |
| Resource-set insertions | 7,819 | 7,205 |

The windows contain different draw mixes. Raw totals do **not** establish lower
draw counts, batch counts, CPU time or frame cost. The relevant invariant is one
state-emission call per draw instead of two: 6,885 unnecessary binning-side state
calls are avoided in the candidate window, a 50% reduction for those draws.
Program emission and vertex constants for that unused stream are also omitted.

Resource tracking already has repeated-reference fast paths: reads test the
batch mask; writes return for an existing writer batch after restoring resource
validity. Removing these checks or weakening new-batch invalidation would risk
dependencies and ownership without evidence of a safe saving. Those paths are
unchanged. The recorded 7%/11% state and 4%/6% tracking CPU shares are inclusive
profile context, not additive savings or a prediction of this change's speedup.

## Safety boundary

Patch `0026-freedreno-a5xx-unused-binning.patch` makes the decision only for
forced bypass, sample count at most one, and no optional GMEM selector. Streamout
draws retain their existing binning emission. A sticky batch flag forces bypass
at finalization, even if global debug policy later changes; a partial/missing
binning stream can never be selected for GMEM. MSAA batches retain binning and
the existing mandatory GMEM/resolve path. Ordinary GMEM decisions are unchanged.

Real draw streams still restore dirty state on new batches. There is no narrowing
of resource invalidation, removal of references, batch merge, barrier removal,
submission-policy change or presentation change. The inventory lives in patch
`0025`; matching Metal replay hooks and the pixel regression live in the Metal
submodule. Deploy the two newly built libraries together.

## Validation

- Local VM: `m3inventory` PASS (16 s), `m3skip` PASS (20 s), `m3ready` PASS
  (16 s), final `tools/vm-mesa.sh mesa m3final` PASS (19 s). No CI runs.
- Inventory build: normal and compositor GPU suites 30/30 each.
- Final build: normal and compositor GPU suites 31/31 each. New P18 checks
  target/pipeline switches, render-target sampling, scissor-preserved pixels,
  resource rebinding/recreation and two command buffers: zero wrong /4,992 values
  per mode. Existing feedback, depth, mutable/compressed uploads and derivative
  edges pass.
- Four-sample memoryless color/depth and resolve probe: three iterations with
  optimization enabled and three with opt-out, all completed. Center red
  `ffff0000`, corner blue `ff0000ff` in both cases.
- Shared GL correctness suite: `PASS: all` with default forced-system-memory
  policy and with `--gmem-force`, including clear-after-draw, feedback, restored
  targets and large imported/allocated targets.

Existing baseline2 is retained. No new frame benchmark, aggregate CPU/FPS claim
or physical-panel claim. Acceptance follows the user's verified-work-elimination
criterion; further CPU attribution and resource-tracking savings remain optional
follow-ups. M4 submission overhead and M5 GPU attribution remain separate tasks.

Ignored evidence and original M2 runtime backups: `research/metal-m3/`.
The first inventory's optional `bench snapshot` request returned an empty response
after CSV retrieval; restoration still completed byte-exact. The optimized
inventory completed successfully and also restored the original libraries and
environment byte-exact. Neither failure nor diagnostic timings are performance
measurements.

## Activation

Main implementation commit `10d4922`, Metal hooks/tests `ccb3cc7`. Final artifacts
are in `xnu/out-mesa-m3final`. Both libraries are installed in `/usr/local/bin`
and verified byte-for-byte after installation:

- libbgair SHA256: `6d0bb8b734d17d8ff6c0287416614630d04c7b5fe1238f7b6f26dd47524a95d9`
- libbgmtl SHA256: `50f19ef956ddd97d70ef04bcb70aed3246ee389ee9f9d0252f6b65263f927a57`

Backboardd restarted as 12954. The environment is byte-identical to the original:
`CA_DISABLE_FRAMEBUFFER_COMPRESSION=1` only, with profiling disabled and no
binning override. Benchmark and profiler are idle; GPU jobs completed 8903/8903.
Final TSENS maximum was 73.4 C after the diagnostic GPU workloads; their timings
are not used for performance conclusions. The phone remains running iOS, with
no reboot, flash, partition, kernel or clock-policy changes. Temporary M3 device
files and inventory CSVs were removed and the shared phone lock released.
Original M2 backups and all evidence remain ignored under `research/metal-m3/`.
