# Task 24: first driver batch graph

2026-10-26. One authorized diagnostic session, not a speed benchmark.
Source `ccd9a88` plus annotation repair `ad9d787`; Mesa CI `40247556888` PASS.
[Source audit and controls](PERF-TASK24-AUDIT.md).

## Observed graph

All **20,960 event prefixes are consecutive**. Forty complete CA flush intervals,
288-327, lie between the 41 FIFO markers287-327. The leading/trailing partial
intervals are excluded. In those interior intervals every flushed batch's draw
records are exactly1 through its final draw count. This supports the counts
below, not displayed FPS or GPU execution time.

| Interior mixed Home/CC/NC graph | Count | Per CA flush interval |
| --- | ---: | ---: |
| Draws | 3970 | 99.25 |
| Batch flushes, all sysmem | 1575 | 39.38 |
| Ended under texture-barrier cause | 616 | 15.40 |
| Ended under resource-read cause | 646 | 16.15 |
| Ended under periodic-kick cause | 186 | 4.65 |
| Ended under generic context-flush cause | 122 | 3.05 |
| Other causes | 5 | 0.13 |

These are **batch endings attributed to a call stack**, not API call counts.
For example,121 periodic-kick context-flush calls ended186 batches, including
dependencies. Do not remove186 supposed kicks. There are534 barrier-caused
context-flush calls in these intervals; they ended616 batches. The separate
`texture-barrier` event describes the current batch, when one exists, not every
barrier call.

The1125x2436 main-target class has667 batches and2171 draws. Of these batches,
356 have a bound view whose BO aliases a target;311 do not, including46 zero-draw
batches (not necessarily zero-work batches). There are **84 batches of6-13 draws without observed bound-alias evidence**,
none with an observed clear event. Their scissor unions cover the target, but
that does not establish actual pixel coverage or profitability. Some13-draw
non-alias batches end at a barrier, before the following feedback draw.

This last observation matters: retaining every barrier could merge these large
non-feedback islands into feedback batches that must stay sysmem. The first
retention experiment should preserve large islands rather than maximize batch
size blindly. Likewise, resource-read splits remain as common as barriers;
removing barrier splits alone does not imply a handful of batches per frame.
No per-workload performance or shared-UI speed gain was measured.

## Console integrity and parser repair

The device console inserts process prefixes inside long records and sometimes
concatenates successive records without a newline. Some tail fields are damaged.
The original newline-based parser consequently merged records and allowed a
damaged tail key to overwrite the header sequence number. Repaired host parsing
frames by the explicit record prefix and preserves the first occurrence of each
key. A regression test reproduces both observed framing defects; six host tests
pass.

All required count/identity/alias fields used above survive; the independent
`detail.py` assertions verify every event number, all41 frame markers and every
interior batch's complete draw numbering. `complete_record_fields=false` is
reported explicitly. **Do not use this capture as proof of complete per-batch
restore/resolve masks or byte-accurate packet state.** Future diagnostics should
emit short explicitly framed physical fragments. No new phone round was spent
to conceal or work around this transport limitation.

## Session and restoration

- Exact diagnostic library/readback SHA256
  `0a8d5fac5e28f6a92798bc176d6a373367f2fc67d99dcf44a10ffba4076e102f`;
  GL test7/7 PASS, sampler subchecks included, exit0.
- Temporary image `8d1b50d51c7855efa19345a3ae59b02d9c695f071991d8a6019bf29e7514c9ec`
  booted01:10:53 Budapest. Original j70 slot-b kernel/ADT preserved;
  pipeline0, GPU588, DDR1804. No partition flash.
- Home swap-surface screenshot visually checked. Bounded Home/CC/NC gestures
  sent across the trace window. This is not independent visual confirmation of
  every intermediate UI state or of an app workload.
- Accessory-sync precheck:2.984008 s, zero drops; neither named task had an
  on-CPU sample. This passes the precheck, not proof of permanent inactivity.
- Start was158 ms late;40-second deadline ended the trace at20960 events, below
  its30000-event cap. No new runtime GPU/SMMU fault or panic found. Startup
  self-test FSR0x400 also exists in the production baseline.
- Ordinary slot-b boot restored via `fastboot reboot` at01:17:54; active slot b
  checked. Production injection path, EAGL context and DDR1804 verified from
  the new boot log. Lock-screen swap-surface screenshot visually checked.
- Production before/after bytes match, SHA256
  `14e32aea4121e9c8a357da8f5e6322fe572a85f1c22e496990af0e687cb19261`.
  Production library was never replaced. Own test library/binary and both sets
  of screenshot files removed; own collectors ended, profiler idle, own shared
  phone lock released. Phone is back in ordinary production iOS.

Ignored evidence/reproduction: `research/t24/boot-trace.txt` SHA256
`0dac2345a136379f99c50278c3ee913b539a41edcf0037b8d4a4d42c1cd2739d`,
`graph.json`, `detail.py`, `detail.json`, `batches.json`, `timeline.jsonl`,
`sync-check.*`, `artifact.json`, `image.json`, restoration logs/screenshots and
`cleanup.json`. Device dumps and screenshots remain outside git.

## Next implementation gate

Prepare a default-off sysmem-only barrier candidate using the existing a5xx
color flush, completion wait and UCHE invalidate primitives. Initially reject
clears/prologues, depth/MSAA, unproved formats/layouts, large non-feedback islands,
active queries/streamout and any other pending batch in the context. The last
restriction preserves the global-drain semantics that would otherwise be lost
for untracked aliases. Split before a later clear and retain a durable bypass
veto. Keep all real dependencies, fences and kick cadence. GPU pixel-reference
tests must pass with the option on/off and TC on/off before a performance trial.
Task24 remains open; no rendering optimization or GMEM default has shipped.
