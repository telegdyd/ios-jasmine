# M6 bounded logical attachment lifetime audit

2026-11-02. **M6 remains partial; no traffic operation removed or candidate
activated.** This extends the [M6 feedback audit](METAL-M6-TRAFFIC.md) with a
bounded logical access graph. It does not establish complete physical backing or
observer coverage. The installed M4 runtime is retained. No speed or bus-byte
claim is made.

## Instrumentation and scope

Set both `BGMTL_PASS_PROFILE=1` and `BGMTL_LIFETIME_PROFILE=1` before starting the
process, then use M5's `/private/var/tmp/bgmtl-pass-start` trigger. The lifetime
option reduces the collection budget to **12 command buffers**; ordinary M5
captures retain 120. The same 65536-row bound, deadline, pending-stamp accounting
and activity-driven export apply. Both options default off. Patch0031 extends
patch0029; patch0030's sticky fetching-draw sysmem restriction remains intact.

The AIR layer assigns monotonically increasing texture-lifetime IDs, records the
logical `pipe_resource` address and imported IOSurface ID, and records accesses
in inline replay order. An address is **not** a physical backing ID: driver
renaming, pooled reuse and unobserved aliases remain unknown. Shared drawable
shadows naturally share their AIR texture lifetime; imports with the same
IOSurface ID are explicit alias hazards. A lifetime ID is not recycled when an
allocation or wrapper address is reused.

Recorded paths include attachment load/store intent, independent clears, actual
draws, resolved vertex/fragment/compute texture and image bindings (including
argument-buffer members), texture copies, resolves, mip generation, CPU texture
reads/uploads and surface synchronization while inside replay. Copies record both
endpoints; this includes drawable shadow copy-back when executed in scope.
Accesses are conservative: binding can precede a subsequently failed draw, and
CPU access intent can precede validation failure. They must not be interpreted
as counts of successful hardware transactions.

Each CSV `access` row uses M5's twenty-word payload:

| Words | Meaning |
| --- | --- |
| 0–3 | Kind, texture lifetime ID, logical resource address, imported surface ID |
| 4–5 | Mip and layer; `UINT32_MAX` means unknown/range |
| 6–11 | Origin xyz and extent xyz |
| 12–13 | Kind-specific mask/detail |
| 14–19 | Base width/height, last mip, layers, samples, pipe format |

Kinds 1–14 are attachment, clear, draw, sample, image, copy source/destination,
resolve source/destination, CPU read/write, external synchronization, mipmap and
destroy. Attachment mask is slot; detail packs requested load/store in low/high
32 bits. Color draw mask contains the actual Gallium RGBA write nibble and fetch
bit 4; detail is the NIR output bitset, separately from the write mask. Depth
draw access is explicitly unknown. Draw rectangles are clamped scissors, **not
proof that geometry, depth/stencil tests or fragment execution replace every
pixel**. Sample/image subresource ranges remain unknown. The row's CB/pass and
position preserve ordering, rather than a compressed shader label.

`tools/g2/metallifetimes.py` validates M5 completeness and replay scope, retains
the ordered graph, identifies surface aliases/logical reuse and enumerates all
recorded events between consecutive attachment uses. It always labels potential
removals unproven. `metalpasses.py` accepts the extra rows without charging them
GPU time. Neither analyzer treats the last capture row as resource death.

## Observed bounded window

The final-source post-restart compositor window has **12 CB / 12 encoded passes /
12 batches, zero dropped rows and zero pending stamps**. Scene provenance is not
sufficient to call it Home or rounded-corner workload coverage. It contains
144 access records over 17 texture lifetimes:

| Access | Records |
| --- | ---: |
| Attachment intent | 24 |
| Independent clear | 12 |
| Attachment draw | 72 |
| Sample binding | 24 |
| CPU upload intent | 12 |

The two alternating target pairs are 828x1792, single-sample. Color0 requests
Load/Store; color1 requests Clear/Store. Each lifetime is used in six passes.
Each pass has three draw calls, recorded once per attachment. All color0 draws
have RGBA writes, and one of the three fetches color0. Color1's draw write mask
is zero and no draw fetches color1 in **this** window. The clear still writes
color1. The NIR output bitset contains color0 only. This does not contradict the
earlier M6 window's different rounded-corner save/restore sequences; do not
generalize either capture's masks to every CA pass.

There are twenty consecutive-use transitions: ten color0 Load transitions with
a fetching draw between uses, and ten color1 Clear transitions without a
recorded color1 fetch. **All twenty cross command-buffer boundaries.** No shared
surface IDs or logical-address reuse were observed within these records; that
does not establish physical alias freedom. No copy, resolve, CPU read, external
sync, mipmap or destroy occurred inside this short replay window. Zero records
for an operation do not establish absence outside the observed scope.

## Decision and remaining limits

Color0 preservation and within-pass feedback remain necessary. Color1 is a
candidate for a broader audit in this particular pass shape, but its next clear
is separated by an unobserved interval: CPU reads, presentation/external
consumers, aliases and final lifetime are not bounded by this capture. Moreover,
Store intent is not a distinct per-resource hardware store event. In the current
sysmem path, rendering/clearing itself writes memory; deleting a descriptor's
Store setting does not demonstrate a removed hardware operation.

Consequently **zero removals are proven**. No attachment, clear, copy, store,
barrier or scratch extent is changed. There is no region proof for rounding,
blur borders or partial redraws. This is a negative result within explicit
coverage limits, not proof that every store is necessary or that no optimization
exists. Complete physical backing/alias histories, out-of-replay observers and
sampled subresource ranges remain unfinished M6 evidence. Further whole-UI
captures are not justified merely to obtain a favorable class. M7 is the next
independent implementation route in the active queue.

## Validation

- Local VM `m6life`: PASS, 17 seconds. Final `m6lifefinal`: PASS, 14 seconds,
  `xnu/out-mesa-m6lifefinal`. No CI. Initial staging failed on generated patch
  CRLF context; corrected before a successful build. The first final revision
  exposed a C-header `bool` declaration issue; corrected to the header's integer
  API convention before final validation.
- Final pair: normal, compositor sysmem and eligible-GMEM GPU suites **35/35
  each**, including existing rounded-corner/feedback, later color1-only clear,
  partial redraw/Load, mutable upload, target reuse and dependency-chain coverage.
  These verify preserved behavior, not newly reduced traffic.
- MSAA 4x color/depth/resolve, three iterations with selector off/on: exact
  red center/blue corner. Shared GL sysmem and forced-GMEM: `PASS: all`.
- Analyzer tests: **12/12** across the Metal analyzer test files, including alias
  hazards, intervening consumers, unknown depth masks, capture boundaries and
  access-scope rejection. Collector ASan/UBSan: trigger, copied access payload,
  12-CB limit, capacity/loss, pending stamps and deadline PASS.
- Final-source capture accepted by both analyzers. Timestamp sum/union 8.78 ms
  describe diagnostic pipeline-draining envelopes only, not traffic or a matched
  before/after result.

Evidence and exact restoration copies are ignored under `research/metal-m6life`.
No kernel, partition, boot, clock, blur-quality or presentation-policy change.
See the active `NOTES.md` entry for final cleanup, hashes and commits.
