# M1: caller-backed texture upload reduction

**Accepted and enabled by default.** User clarification supersedes the initial
performance-based rejection below: verified removal of unnecessary work with
preserved correctness is the objective; an aggregate CPU/FPS gain is not required.

Reference: the existing [2026-11-01 baseline](METAL-PERF-20261101.md), especially
loss-free baseline2. No replacement baseline was collected for M1.

## Attribution

One bounded mixed Home/Control Center inventory captured 120 command buffers,
42 texture objects, 72,340,664 uploaded bytes, no record overflow, no upload
failures. All observed uploads fit within the 256 MiB diagnostic hash budget.
This instrumented window is an attribution capture, not a timing measurement.
Command buffers are not displayed frames. Raw evidence stays ignored under
`research/metal-m1/`.

| Source | Shape / format | Uploaded bytes | Uploads | Content observations |
| --- | --- | ---: | ---: | --- |
| Packed no-copy image | 828x1792, ASTC 4x4 LDR (204), one mip | 65,286,144 | 44 | Initial upload + 43 identical hashes |
| Buffer-backed linear image | 431x258, A8Unorm (1), offset 64, row pitch 448 | 6,115,890 | 55 | Initial upload + 54 identical hashes |
| Other linear images | Mostly small masks / lookup textures | 938,630 | 341 | No changed hashes |

The full-screen compressed image accounts for 90.25% of observed uploaded bytes.
All linear sources together account for 7,054,520 bytes / 396 uploads. Existing
within-epoch caching already avoids 2,248 refreshes. No copied-IOSurface uploads
were observed in this window; this does not establish their absence elsewhere.
Hash equality is probabilistic diagnostic evidence, never an immutability promise.
The image's visual identity is not established by its dimensions or pointer.

## Implementation and boundaries

The dominant source comes from `newTextureWithBytesNoCopy`, not a GPU buffer.
There is no producer modification generation in that API. Enabling the existing
linear-allocation option cannot alias these arbitrary caller pages or their packed
compressed mip layout. A buffer alias would target the much smaller second source
and needs its own lifetime/coherency design.

The selected path retains an exact CPU snapshot of the meaningful packed mip chain
and uses `memcmp` at each existing refresh epoch. An exact match avoids the driver
upload. Mutations still upload and replace the snapshot. Allocation padding is not
compared; mip offsets and compressed block rows use the upload path's format
helpers. It does not infer unchanged contents from pointers or hashes.

The cache is **enabled by default**; `BGMTL_NOCOPY_CACHE=0` opts out. Memory is bounded to 2 MiB per texture and 8 MiB per process. Oversized images,
allocation failures and exhausted budget retain the original upload path. Texture
destruction returns the budget. `BGMTL_NOCOPY_CACHE=0` disables the optimization.
This adds a read/compare pass and can add a snapshot copy for changing images;
the measured static full-screen source is the intended benefit, not every upload.

The fast path applies to render sampling. Compute, attachments and explicit blits
retain their original upload behavior. CPU replacement, recorded GPU writes,
blits, mip generation and resolves invalidate snapshots, including after writes.
Existing CPU-buffer-blit epoch changes remain in force. GPU memory ownership,
submission order, render tickets and asynchronous-replay settings do not change.

A separate correctness fix invalidates the graphics state cache around texture
copies, as resolves/mip generation already do. The new copy-then-draw test exposed
stale raster state: 165 incorrect component values across the lifecycle cases;
disabling the graphics state cache eliminated them. Rebinding after copies is
required for the pixel gate, not a claimed performance optimization.

## Diagnostics

Opt in using `BGMTL_UPLOAD_PROFILE=1`, restart the intended process, then create
`/private/var/tmp/bgmtl-upload-start` after settling. The process writes one
`/private/var/tmp/bgmtl-uploads-PID.csv`: at most 120 command buffers, or eight
seconds checked at a replay boundary. It is one-shot per process. Remove the
trigger and restore the environment afterward. No payloads or per-draw logs are
written. A fixed 256-resource table reports overflow; a 256 MiB full-content hash
budget reports unclassified comparisons rather than pretending they are unchanged.
Upload bytes exclude row/allocation padding and include all packed mip block rows.
The CSV distinguishes epoch reuse from exact-content reuse and reports avoided
bytes. Profile hashing is diagnostic overhead; use a fresh process without the
profile environment for performance measurements.

## Validation

Host ASan/UBSan tests cover exact content mutation, padding, final meaningful bytes,
invalidation, memory limits/release, opt-out, inventory mip layout/accounting,
hash bounds/budget, overflow and capture termination. The GPU gate includes the
existing ASTC partial-block/mip mutation test and derivative-only edge test, plus
P16: initial data mutated before first use, unchanged reuse, mutation between
commits, two draws per commit, CPU buffer-to-texture blits, GPU texture copies,
subsequent restoration from caller memory, and direct CPU replacement. Both
RGBA8 and ASTC paths are covered, including compressed GPU copies.

Early P16 runs stalled after 13 rounds. A two-second wait-stack capture identified
Apple `_MTLCommandBuffer initWithQueue` waiting on its queue semaphore, not a GPU
copy: 51 earlier command-buffer objects + 13 new objects exhausted 64 slots in the
outer autorelease pool. P16 now drains completed objects each round. Speculative
compressed-copy fallback/omission changes were removed; the full cases remain.
There is no established ASTC-copy defect from those timeouts.

Final correctness build: `tools/vm-mesa.sh mesa m1ready`, PASS in 12 seconds,
`xnu/out-mesa-m1ready`. Metal commit `83058de`; inventory commit `306908b`.
Both GPU suites pass **29/29**, normal and `--bb`. P14 checks 1,099,392 component
values and P16 checks 4,096; both have zero mismatches. The derivative circle has
zero mismatches, including 388 edge pixels. No CI run or kernel build.

## Verified upload reduction

The optimized inventory captured 120 command buffers with no overflow or upload
failures. The full-screen ASTC source uploaded its initial 1,483,776 bytes once,
then reused exact content 35 times, directly avoiding **51,932,160 upload bytes**.
Other textures still use their original upload paths. Its total 45,575,075 actual
uploaded bytes reflects a different workload composition from the earlier bounded
inventory; the two raw totals are not a matched frame-cost comparison.

The candidate was installed with byte-for-byte readback verification, then the
profile trigger was removed and the original compositor environment restored
before restarting without profiling. Binary identities:

- libbgair: `326eaa30dcc1ccea1955b45383f5f97bdb25ec3cb83a18cf2a54fad2c0561074`
- libbgmtl: `185941370b1b67eb7256e19e1d3ab0182619e23b25c731eae74d4fbd07d3f4f4`

The first attempt after
the credit interruption failed preflight because the user had parked in the
charging shell; it collected no device workload and is not a performance result.

## Single optimized capture and initial decision (superseded)

The initial decision incorrectly required a lower whole-frame render-CPU result
before accepting the verified upload reduction. Commit `471afde` temporarily made
it opt-in. The user explicitly rejected that criterion; commit `c121e6a` restores
default enablement. The measurements below remain factual context, not an
acceptance gate. No further benchmarks were run.

After the user parked the phone during the credit break, booted the existing
installed slot b using `fastboot reboot` from 99% battery. Verified both candidate
libraries and the restored environment byte-for-byte. Exactly one standard A-only
capture at 21:39-21:41 local time: `research/metal-m1/optimized-run/`, 23,191 events,
41,066 CPU samples, **zero losses**; offline framecrit succeeded. Existing loss-free
baseline2 remains the reference. No new baseline was collected.

| Measure | Existing baseline2 | Candidate |
| --- | ---: | ---: |
| Home B swap arrivals/s | 36.20 | 34.22 |
| Control Center A swap arrivals/s | 30.82 | 29.97 |
| Control Center B swap arrivals/s | 31.37 | 28.79 |
| CC A render CPU, estimated ms/update | 28.54 | 30.23 |
| CC A CPU under Metal libraries, estimated ms/update | 14.70 | 16.22 |
| CC A GPU-outstanding proxy, estimated ms/update | 20.86 | 21.33 |

These are swap arrivals and sampling/grid estimates, not validated physical FPS.
Outstanding work includes queue/observation latency, not just GPU execution.
Home A is unsuitable for a CPU comparison: five sampled frame intervals versus
138 in baseline2; the full motion window recorded only 2.65 arrivals/s.
Fresh-boot `trustd` and `accessoryupdater` together accounted for 33.1% of sampled
non-idle CPU; their causal contribution to Home A is not proven. Boot age and
thermal state differ: candidate TSENS max 49.8 to 52.4 C, reference roughly
50-54 to 54-57 C. GPU selection remains 588 MHz, DDR 1804 MHz. One run cannot
isolate cache cost, scene/resource mix, boot activity or other factors. It does
not establish lower render CPU.

Present queue ended at zero, high-water one. All 1,246 presentation waits and two
CPU ticket waits had zero errors; no latch timeout fallback or DROP/CANCEL/ABORT.
Memory snapshots had no page waiters. Short fresh-boot footprint growth is not
leak evidence. No physical panel validation was inferred.

## Corrected acceptance and installation

User instruction: accept correctness-preserving removal of unnecessary workload;
do not chase an aggregate speedup. The packed-image path meets that criterion:
35 unnecessary uploads /51,932,160 bytes were avoided, while caller mutations and
CPU/GPU writes remain correct in both 29/29 GPU suites. Other upload paths retain
their existing behavior; this is not a claim that all M1 upload opportunities are
exhausted or that a CPU/FPS gain was demonstrated.

Metal commit `c121e6a` enables the cache by default with the existing opt-out.
VM build `tools/vm-mesa.sh mesa m1default` passes in 12 seconds. Both output
libraries are byte-for-byte identical to the `m1ready` pair that passed the normal
and compositor GPU suites. Focused ASan/UBSan tests pass for explicit enablement,
opt-out, default-on, mutation, padding, invalidation, memory bounds and release.
No repeated GPU suites or benchmarks were needed for the identical runtime.

The pair is installed in `/usr/local/bin` with byte-exact readback verification;
its hashes are recorded above. The environment remains byte-identical to the
original: only `CA_DISABLE_FRAMEBUFFER_COMPRESSION=1`, with no diagnostic or cache
override. Next iOS boot loads the optimization by default. Original ccfix backups
remain ignored locally for rollback.

Phone returned to `charge-shell.img` by temporary fastboot boot, backlight off.
No boot/GPT/partition flashing or clock-policy changes. The earlier rollback in
this report is superseded by this installation. Baseline2 and the single optimized
capture remain the only performance comparison; no speedup is claimed.

The packed-image optimization is accepted. Remaining linear-buffer upload work is
a follow-up opportunity, not a reason to disable the verified saved work.
