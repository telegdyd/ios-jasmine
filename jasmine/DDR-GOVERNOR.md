# DDR and RPM bus-clock governor (power plan item 1): design

Status 2026-10-29: **design, not built.** Owner: the item-1 session. Plan: [POWER-PLAN-20261029.md](POWER-PLAN-20261029.md).

## Rule and the facts it rests on

- No performance trade-off: the DDR runs at the full rate (1804 MHz, `sweetddr=`) whenever there is work, and a
  frame never *starts* at a low rate. Power is saved only in real idle gaps and with the display off.
- The phone is DDR-bound (PERF-BOTTLENECK-20261028.md): DDR 1296 costs 15-24 % frame rate; below 1296 Mesa's
  CPU work also grows steeply (+21 % at 1017, +60 % at 768, GPU.md j0064). So the CPU side of a frame needs the
  full rate too, not just the GPU side.
- Today (j0113 boot_b): `sweetddr=1804` does the j0064 handoff (every sdm660 RPM clock voted to its maximum in
  both sets, RPM scaling on) and one bimc vote; nothing changes afterwards. Any RPM clock we lower stays low
  until we raise it; with scaling on and no bimc vote the RPM may pick a low DDR rate (20-60 % slower), so
  the governor always holds an explicit bimc vote.
- An RPM request today waits for the ack in 1 ms `delay()` steps, so one vote costs >= 1 ms (the "~23 ms" of
  `ddr MHZ` is mostly its own 20 ms settle delay). The raise latency matters: see "Raise path".

## States

| State | When | bimc (DDR) | snoc, cnoc, cnoc_periph, aggre2_noc, mmssnoc_axi |
| --- | --- | --- | --- |
| FULL | any work, and for `hold` after it | `sweetddr` (1804) | handoff max (as today) |
| IDLE_ON | display on, idle for `hold_on` (1000 ms) | `floor_on` (768, tunable) | max (unchanged) |
| IDLE_OFF | display off, idle for `hold_off` (200 ms) | `floor_off` (200, tunable) | low (19.2 MHz request; the RPM rounds up) |

- With the display on only bimc moves: the MDP scans out of DRAM through mmssnoc_axi, and cnoc slows every MMIO
  access (touch, GPU, UFS registers), so the buses stay at max while the screen is on.
- ipa, ce1, qdss and the XO buffers are not touched (modem data path, crypto, debug; separate item if worth it).
- Only the **active set** is voted on transitions (one RPM request per clock instead of two). The sleep set keeps
  the handoff values; it is only used once the AP power-collapses (item 4), which will set it on purpose.

## Raise path (work starts at the full rate)

Every hook calls `sweet_ddrgov_activity(src, sync)`. Fast path, the normal case while working: state is FULL
-> store the timestamp, return (one atomic load and store, no lock). Slow path (state is IDLE_*):

| Hook | Where | Mode |
| --- | --- | --- |
| GPU submit | `sweet_gpu_submit` (bsd/dev/sweet_gpu.c), before the ring write | **sync**: the vote is acked before the GPU sees the job |
| touch report, key press | `sweet_hid_touch`, `sweet_hid_key` (SweetHID.cpp; touch/keys poll threads) | **sync**: a touch-down raises 16+ ms before the UI's first frame |
| display on | `kSweetFBRequestPowerChange` on, before `setPanelOn(true)` | **sync** (buses and bimc; panel sleep-out takes 120 ms anyway) |
| display off | the same, after `drainPresent` | starts `hold_off` |
| present / swap | SweetFramebuffer swap | timestamp only (keeps FULL alive) |
| UFS request | sweet_ufs.c submit | async kick (wakes the governor thread) |
| CPU memory traffic | bimc bwmon4 MON2 (CPU port), read by the governor thread every 10 ms while not FULL | async; raise when > `bw` MB/s (threshold set from a measurement, see below) |

"sync" means the caller takes the governor mutex and does the RPM vote itself; all hook sites are preemptible
thread context that already blocks (lck_mtx in the submit path). A second caller meanwhile waits on the same
mutex, then sees FULL. To keep the sync cost small, `rpm_request` polls the ack every 20 us instead of every
1 ms (same 1 s timeout; all RPM callers get it). Expected raise: bimc ~0.2-1 ms, all six clocks a few ms
(measured and reported by `ddrgov`).

What can still start at a low rate (honest limits):
- CPU-only work that begins without input, GPU submit or present (a timer-driven animation's first frame's CPU
  recording, background work with the screen off) runs at `floor_on` / `floor_off` until the next 10 ms bwmon
  sample sees its traffic or its first GPU submit raises. With the display on that is at most one frame's CPU part
  for non-input animations; touch-started work is never affected. If this shows up, `floor_on` can be raised
  (1296 keeps Mesa's CPU cost at the full-rate value per j0064) or IDLE_ON disabled (`sweetddrgov=2`: scale only
  with the display off).
- With the display off the first ~1-3 ms of a UFS/Wi-Fi burst can run at the low bus rate before the async
  raise. Not user-visible; `bus=0` keeps the buses at max if it matters.

## Step-down path

The governor thread (style of j0104's worker: `assert_wait_deadline` + `thread_block`) samples every 50 ms in
FULL, every 10 ms in IDLE_ON (bwmon trigger), every 50 ms in IDLE_OFF. FULL -> IDLE_ON when the display is on,
nothing has triggered for `hold_on`, GPU busy cycles (j0064 counters) were 0 over the last sample and bwmon is
under `bw`. FULL/IDLE_ON -> IDLE_OFF when the display is off and nothing triggered for `hold_off`. IDLE_OFF ->
IDLE_ON never happens directly: display on raises to FULL first.

## Switches and visibility

- `sweetddrgov=0|1|2`: 0 off (old fixed `sweetddr` behaviour, the default until acceptance), 1 on, 2 on but only
  with the display off. Needs `sweetddr=` (the handoff and the full rate); without it the governor stays off.
- `sweetddrgov_on=MHZ`, `sweetddrgov_off=MHZ`, `sweetddrgov_hold=MS`, `sweetddrgov_bw=MBPS`, `sweetddrgov_bus=0|1`.
- Command port: `ddrgov` (state, votes, bimc readback, counts and time per state, raises by source, last 16
  transitions with reason and vote latency), `ddrgov on|off|offonly` (live, for A/B on one boot), `ddrgov set
  on=MHZ off=MHZ hold=MS bw=MBPS bus=0|1`, `ddrgov log 0|1` (a `SWEET DDRGOV:` line per transition).
- Power plan step 0 in the same patch: `sweetpwrlog=S` prints every S seconds `SWEET PWR:` with the fuel-gauge
  current averaged over 1 s samples (min/max), voltage, display state and the governor's residency in that
  window; command `batt` prints one reading. Lines buffer in the kernel log while unplugged.

## Implementation

New patch `j0114-jasmine-ddr-governor.patch`: new `bsd/dev/sweet_ddrgov.c` (governor, `ddrgov`, `batt`,
`SWEET PWR`); small hooks in sweet_gpu.c, SweetHID.cpp, SweetFramebuffer.cpp, sweet_ufs.c, sweet_usb.c (command
dispatch); sweet_ddr.c exports its bimc set/readback and a once-configured bwmon MON2 reader; sweet_rpm.c gets an
active-set-only, unlogged clock vote and the 20 us ack polling. Default off: kernels with this patch and no
`sweetddrgov=` boot exactly as today.

## Test and acceptance

Temporary `fastboot boot` images only, battery >= 30 %, nothing flashed without the user's OK.

1. Bring-up: boot args of the installed boot_b + `sweetddrgov=1 sweetpwrlog=30`. Check `ddrgov` transitions,
   bimc readback per state, raise latencies; look at the screen in IDLE_ON at `floor_on` (MDP underrun shows as
   glitches); display off/on 10x cleanly. Measure idle bwmon traffic to set `bw`.
2. Performance: framebench (FRAMEBENCH.md standard run) on one build, governor on vs off, alternated twice
   (A/B/A/B, live `ddrgov on/off`). Pass: on is not slower than off within run-to-run noise. Plus a non-touch
   check: a timer-driven animation's frame times from idle (e.g. a notification) on vs off.
3. Power: unplugged, `SWEET PWR` 5 min screen off and 5 min screen on idle on Home, governor on vs off (the user
   unplugs/replugs). Pass: lower current with it on.
4. Then propose `sweetddrgov=1` in the installed boot_b (user's OK) or as the default.
