# DDR and RPM bus-clock governor (power plan item 1): design

Status 2026-10-29: **built (j0114), on by default (mode 1) since j0114d; temporary boots only so far.** Owner: the item-1 session. Plan:
[POWER-PLAN-20261029.md](POWER-PLAN-20261029.md). Results: "Bring-up results" at the end.

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

## Bring-up results (2026-10-29, temporary `fastboot boot` only, nothing flashed)

Kernels j0114 (first), j0114b (+ CPU-load trigger, UFS only with the display off), j0114c (defaults below).
Images `shim/out/shim-boot-j0114{,b}-gt.img` = the installed boot_b's args (j0113 `-test` variant, no `abmark`)
+ `sweetpwrlog=30`; `-j0114c-gt.img` has `sweetddrgov=2` instead. Logs `logs/netlog-j0114-gt.txt`,
`logs/netlog-j0114b-gt.txt`. Framebench `research/framebench/ddrgov-{1-off,2-on,3-on,4-off}/`.

Design changes made from the measurements:
- UFS requests raise only while the display is off **and** bus clocks are lowered: background I/O comes about
  once a second (screen on and off) and kept FULL alive for good; UFS DMA is not DDR-limited at either floor.
- CPU-load trigger (display on): the busiest core over the j0104 DVFS sampler's 20 ms window >= `cpu` % (60)
  raises, for CPU work without memory traffic (latency-bound, as Mesa's).
- `bw` default 2000 MB/s (10 ms bwmon spikes over 1000 MB/s are routine on the idle home screen; idle average
  ~175-900 MiB/s).
- **Bus clocks default off** (`bus=0`): see the power table.

Behaviour (observed):
- Raise latency (RPM ack, 20 us polling): bimc alone 0.06-2.0 ms, bimc + 5 buses 2.2-4.4 ms. 0 failed votes in
  ~600 transitions. Readback after a down-vote: 766-768 MHz (idle-on), 398 MHz for the 200 MHz request (the RPM
  rounds up; snoc 20, cnoc 33, cnoc_periph 33 MHz). Raises read back 1804 every time.
- Display off/on (power key over the command port) twice: key raises to FULL ~3 ms before `display on`, no panic,
  no SMMU fault. Not checked by eye.
- Idle home screen, display on, cpu=60: IDLE_ON residency ~15-25 % (CPU bursts every 1-2 s); cpu=90 ~50 %, cpu=0
  ~75 %.
- The lock screen after boot renders continuously (~50 flushes/s, GPU ~60 % busy): no idle there at all.

Power, paired A/B on one boot (`tools/g2/fgab.py`: alternating 20 s windows, order flipped every cycle, fuel-gauge `batt`
every 1 s, first 4 s dropped). USB connected and the battery discharging the whole time (charger input
saturated, so load changes show 1:1 in the battery current); absolute values are not comparable with the
unplugged -437 mA, the differences are.

| Display | Governor setting vs off | Difference (positive = saves) | n |
| --- | --- | ---: | ---: |
| off | DDR floor 200 + all 5 buses low | **-20.8 mA** (sd 7.4, costs more) | 8 |
| off | buses low only (DDR 1804) | -0.6 mA (sd 1.5) | 6 |
| off | DDR floor 200 only | **+11.0 mA** (sd 5.1) | 6 |
| on, idle home | floor 768, cpu=60 / cpu=0 | not measurable (drift -215 -> -157 mA over 6 min swamps it; < ~10 mA) | 2+2 windows |

So lowering the NoC clocks buys nothing (the RPM probably keeps the CX corner for other votes, e.g. ipa/ce1/
qdss at max) and, together with the DDR floor, costs ~21 mA (guess: slower MMIO and memory keep the polling
drivers' CPU work out of WFI longer). The DDR floor alone saves ~11 mA with the screen off. This is far below the
plan's 50-120 mA estimate: the screen-off floor is elsewhere (CPU WFI only, GPU never off, display pipeline,
polling drivers; power plan items 2-7).

Performance, framebench on j0114b, one boot, ABBA (off, on, on, off), swap arrivals/s, mean of two runs:

| Phase | off | on (mode 1, cpu=60) | Change |
| --- | ---: | ---: | ---: |
| spotlight first / repeat | 26.18 / 28.60 | 25.93 / 28.58 | -1.0 / -0.1 % |
| home-a | 41.16 (run 1 invalid: 0.31/s, no motion) | 40.96 | -0.5 % |
| home-b | 41.15 | 40.89 | -0.6 % |
| control-a | 28.65 | 28.40 | -0.9 % |
| control-b | 28.62 | 29.00 | +1.3 % |

All within the spread between the two runs of the same setting (spotlight +-4-5 %, control-b +-2.7 %, home-b
+-0.5 %): no regression measurable; 4 of 6 phases are slightly lower with it on, so not proven equal either.
The gestures arrive while the governor is already FULL (hold, CPU trigger), so this run does not exercise a
raise from idle; a timer-driven animation from IDLE_ON was not measured.

Recommendation: `sweetddrgov=2` (only with the display off, DDR floor only): ~11 mA with the screen off and no
change at all while the screen is on. Mode 1 adds no measurable saving for a small, unmeasured risk on
non-input animations.

j0114c (`sweetddrgov=2` as a boot-arg, `logs/netlog-j0114c-gt.txt`): mode 2 and bus mask 0 from the defaults,
screen on stays FULL, display off -> IDLE_OFF in 0.3-0.9 ms with no raises while dark (UFS no longer counts),
DDR reads 398-400 MHz there; key and display-on raise back (0.16-1.0 ms). A readback right after a down-vote can
still show 1804: the RPM acks before the switch has finished (harmless for down-votes).

**On by default (j0114d, user's decision 2026-10-29: scaling is the proper configuration, not only a power
item).** `sweetddrgov=1` is the kernel default; `sweetddrgov=0` restores the fixed `sweetddr` rate. Temporary boot
`shim/out/shim-boot-j0114d-test.img` (args byte-identical to the installed boot_b's j0113 test variant, no
governor boot-arg; `logs/netlog-j0114d-test.txt`): mode 1 from boot, 0 failed votes. Framebench
`research/framebench/ddrgov-5-default-on` (different boot, sanity only): home-b 41.53/s, control-a 30.44,
control-b 31.03, spotlight 29.43 / 30.22, at or above the earlier governor-off runs; home-a had no motion
(the same framebench artifact as run 1-off). Slot-b image ready, not flashed: `shim/out/shim-boot-j0114d-slotb.img`
(f867f6b1...; args identical to the installed j0113 slot-b image).
