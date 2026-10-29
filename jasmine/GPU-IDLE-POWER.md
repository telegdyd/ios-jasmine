# Adreno 512 idle power management (power plan item 2): design

Status 2026-10-29: **built (j0115, j0115b) and measured on temporary boots; default off; nothing flashed.** Owner: the item-2 session. Results: "Bring-up results" at the end. Plan:
[POWER-PLAN-20261029.md](POWER-PLAN-20261029.md). Previous item and measurement method:
[DDR-GOVERNOR.md](DDR-GOVERNOR.md). GPU bring-up facts: [GPU.md](GPU.md) (G1 findings, j0060).

## Rule and the facts it rests on

- No performance trade-off: the GPU runs at `gpumhz` (588) whenever it has work. Power is saved only while it has
  none: clock gating inside the GPU while it is on (no speed cost, the hardware ungates in a few cycles), and the GX
  domain switched off after an idle gap and always with the display off.
- Today (j0114d, boot_b): `gpu_power_on` (j0018) brings CX GDSC, the GFX LDO in BHS mode under GX GDSC control,
  GX GDSC, gfx3d / RBBM timer / RBCPR branches up once at boot; `gpu_set_clock` (j0060) moves gfx3d to a GPU PLL at
  588 MHz with the RPM CX vote at NOM (`gpucxfloor`, the AP's only CX vote). Nothing changes afterwards: GX on,
  PLL running, no HWCG (`gpu_cp_test` follows a5xx_hw_init "without clock gating"). `gpu_power_off` (GX off) runs
  only after a failed step or a hang.
- Reference: downstream kgsl for sdm660 (`~/lin660` in WSL: drivers/gpu/msm/adreno_a5xx.c, sdm660-gpu.dtsi):
  - a512 HWCG table `a512_hwcg_regs` (56 registers), then `RBBM_CLOCK_CNTL = 0xAAA8AA00`, `RBBM_ISDB_CNT = 0x182`;
    for a512 (not a530/a540) this is done at every power-up in `a5xx_regulator_enable`, bracketed by
    `RBBM_CLOCK_CNTL = 0x55` (halt sp_input_clk) and clearing its low byte afterwards.
  - `a5xx_regulator_disable` returns early for a512: no GPMU / SPTP / RAC sequencing (a512 has no GPMU).
  - a512 has `ADRENO_CPZ_RETENTION`: the zap shader state survives GX collapse, kgsl does **not** call TZ on resume
    (the `SCM_SVC_BOOT 0xA` "zap resume" call is skipped); after CP_ME_INIT it only sends `CP_SET_SECURE_MODE 0`.
  - The GPU SMMU node has `qcom,retention` and its clocks are the GCC ones (gpu_cfg_ahb, gpu_bimc_gfx, bimc_gfx),
    not gpucc: its configuration survives GX off as long as CX GDSC and those clocks stay on.
  - kgsl `qcom,idle-timeout = <80>` ms before SLUMBER (GX off).

## What is switched off, and what stays

| | GPU busy | GPU on, idle | GPU off (collapsed) |
| --- | --- | --- | --- |
| GPU core clocks | 588 MHz | HWCG gates idle blocks | gfx3d branch off, RCG on XO, both GPU PLLs off |
| GX GDSC / BHS | on | on | **off** (BHS opens with the GDSC, clamp set) |
| CX GDSC, SMMU, GCC GPU clocks | on | on | on (keeps SMMU state and page-table TLB ops working) |
| RPM CX vote | `gpumhz` level (NOM) | same | same by default; optional lower level only with the display off (step 2b) |
| Ring, firmware, page tables, fences | DRAM | DRAM | DRAM (retained; nothing re-copied) |

## Step 1: hardware clock gating (first, alone)

- `gpu_hwcg(bool on)`: the a512 table from kgsl (values copied verbatim, register offsets from a5xx_reg.h), the two
  top-level writes, bracketed as `a5xx_regulator_enable` does. Called at the end of the a5xx_hw_init part of
  `gpu_cp_test`, and at every resume.
- Live switch for A/B: `gpu cg 0|1` (GPU idle under `gpu_lock`, like `gpu clk`). Boot-arg `sweetgpucg=0|1`.
- Risk: none expected for speed (kgsl ships it on); a hang on a block that never ungates would show as a job
  timeout, so the first boot runs the self-test and framebench with it on.

## Step 2: GX power collapse when idle

### Off path (GPU power thread)

A kernel thread (style of the ddrgov / j0104 worker: `assert_wait_deadline` + `thread_block`) sleeps until a
deadline set by each submit (`last_submit + hold`) or a display-off kick. On wake, under `gpu_lock`:

1. idle check: `sweet_gpu_completed() == gpu_seqno`, `CP_RB_RPTR == wptr`, `RBBM_STATUS` busy bits clear, no
   "keep on" holder (command port, self-test), and `now - last_submit >= hold` (display on) or the display is off.
   Otherwise re-arm and sleep.
2. As msm `a5xx_pm_suspend` for this core: VBIF XIN halt (mask 0xf, as a540/a512's VBIF) and wait for the ack,
   release; `RBBM_BLOCK_SW_RESET_CMD 0x003c0000` then 0 (VBIF FIFO reset before collapse).
3. gfx3d branch off, RCG to XO, the running GPU PLL off; GX GDSC collapse, wait PWR_ON = 0, clamp (as
   `gpu_power_off`, without the CP halt and RBBM reset that only make sense after an error).
4. state OFF; counters for `gpu pc`.

`hold` = `sweetgpupc_hold=MS`, default **80 ms** (kgsl's sdm660 idle-timeout): above the longest gap between frames
of a running animation (30 Hz panel, ~33 ms), so a moving UI never collapses between frames. Display off: collapse
right after the framebuffer's `drainPresent` (hold 0).

### On path (resume)

`gpu_resume()` under `gpu_lock`, called by `sweet_gpu_submit` when the state is OFF (sync: the job is written into
a running CP), and by the pre-wake path below:

1. GX on exactly as in `gpu_power_on` (BCR reset, AON reset, unclamp, GDSC on, retain-mem, branches), gfx3d on XO.
2. gfx3d to `gpumhz` without the two 2 ms clock measurements and the log line of `gpu_set_clock` (a fast variant;
   the CX vote is still in place, so no RPM call).
3. a5xx_hw_init register writes (factored out of `gpu_cp_test` into `gpu_hw_init()`, shared by boot and resume),
   then `gpu_hwcg(true)`; CP instruction bases point at the firmware copies still in the GPU window.
4. SMMU: read back SMR0 / S2CR0 / CB0 SCTLR / TTBR0; with `qcom,retention` they should be intact. If not, rewrite
   the CB0 / SMR / S2CR registers only (never `smmu_identity`'s table rebuild, which would drop every client
   mapping), log it once.
5. Ring restarts empty (`sg.wptr = 0`, CP_RB_BASE/CNTL), `CP_PFP_ME_CNTL = 0`, CP_ME_INIT, `CP_SET_SECURE_MODE 0`
   (CPZ retention: no TrustZone call). If the CP stays secure (first job faults or the mode switch times out),
   fall back once to the SCM zap-resume call (`SCM_SVC_BOOT 0xA`, args 0, 13), then to `gpu_zap_load`; logged.
6. GPU perf counters (j0064, ddrgov's GPU-busy input) are re-armed on the next `sweet_gpu_bus_counters` call.

Expected cost (to be measured, reported by `gpu pc`): GX on tens of us, PLL lock ~50-100 us, register init a few
us, CP_ME_INIT ~100 us (G1), CP_SET_SECURE_MODE ~550 us (G1's ring_kick timing): **~0.8 ms**, against a 33 ms
frame. If the measured first-submit stall is above 1 ms, step 5 becomes pipelined: the init packets go into the
ring ahead of the job and the submit returns without waiting (the CP executes them in order), with a resume marker
(`CP_MEM_WRITE` to scratch) checked by the power thread.

**Pre-wake** so input-driven frames never pay it: the existing ddrgov hooks (`sweet_ddrgov_activity` for touch and
keys, `sweet_ddrgov_display(1)` for display on) also kick the GPU power thread, which resumes the GPU right away,
while the app records its first frame on the CPU (16+ ms). Only frames that start without input (timers,
notifications) can pay the resume, once per >= 80 ms idle gap.

### Everything else that touches GPU registers

Reading a GPU register with GX off hangs the bus, so every path is checked:

| Caller | With GX off |
| --- | --- |
| `sweet_gpu_submit` | resumes first (under `gpu_lock`, which it already takes) |
| `sweet_gpu_completed` / `sweet_gpu_wait` (SweetSurface, SweetGPU, display waits) | fence in DRAM: unchanged |
| `sweet_gpu_vm_map` / `vm_unmap` (TLB invalidate through SMMU registers) | SMMU is on CX with GCC clocks on: allowed; checked on the first bring-up boot before anything else |
| `sweet_gpu_bus_counters` (ddrgov thread, every 10-50 ms) | takes `gpu_lock`; GX off -> returns "no GPU work" without a register read |
| `sweet_gpu_param(8)` (Mesa timestamp) | GX off -> the arch counter (also 19.2 MHz); on -> RBBM always-on as today |
| `gpu clk`, `gpu state`, self-test | hold the GPU on for the command |
| heartbeat (`sweetgpu_debug=2`), `sweet_gpu_hang_check` | skip the core read when off / unchanged (error path) |

Power state and `gpu_ready` stay separate: `gpu_ready` false still means "broken, no service".

## Step 2b (optional, separate A/B): CX vote while the GPU is off and the display is off

The RPM CX vote at NOM is the AP's only CX vote, and the MDP/DSI clocks (not voted by this kernel, and possibly
still scanning with the display off: unverified) may need it. So by default the vote **stays**. `sweetgpupc_cx=LEVEL`
(e.g. 0x80 SVS) lowers it only while the GPU is off **and** the display is off, and restores the `gpumhz` level
(RPM ack, 0.06-2 ms per the ddrgov measurements) before GX on; the display-on hook restores it before the panel
sleeps out. Tested and measured separately; enabled only if it saves measurable power and shows no display or
bus fault over repeated display off/on.

## Step 3 (optional, only if 1-2 measure well): idle-but-powered frequency drop

Not designed in detail now. With HWCG and an 80 ms collapse, the idle-on window is short; likely nothing to gain.

## Switches and visibility

- `sweetgpupc=0|1|2`: 0 off (today's behaviour), 1 on (idle hold + display off), 2 only with the display off.
  `sweetgpupc_hold=MS` (80), `sweetgpupc_cx=LEVEL` (0 = keep the vote). `sweetgpucg=0|1` (HWCG).
  Defaults: off until acceptance, as with the DDR governor; then the user decides on the default.
- Command port: `gpu pc` (state, mode, hold, counts of collapses / resumes / pre-wakes, residency on / off, resume
  latency min / avg / max, first-submit stall, last 16 transitions with reason), `gpu pc on|off|offonly` (live A/B
  on one boot), `gpu pc hold MS`, `gpu cg 0|1`, `gpu pc stress N` (N collapse -> self-test cycles in the kernel).
  Optional `SWEET GPUPC:` line per transition (`gpu pc log 1`).

## Implementation

New patch `j0115-jasmine-gpu-idle-power.patch`: mostly `bsd/dev/sweet_gpu.c` (HWCG table, `gpu_hw_init()` factored
out of `gpu_cp_test`, resume / collapse, power thread, `gpu pc` / `gpu cg` commands, guards above); in
`bsd/dev/sweet_ddrgov.c` two forwarding calls (activity for touch/key/display -> GPU pre-wake, display on/off -> GPU)
and the `ddrgov` / `SWEET PWR` lines gain the GPU power state. No Mesa or SweetGPU.cpp change.

## Test and acceptance

Temporary `fastboot boot` images only (installed boot_b args + the new boot-args), battery >= 30 %, nothing flashed
without the user's OK. Built on the VM (`tools/vm-build.sh j0115`).

1. **HWCG** (step 1), one boot: self-test PASS, then framebench ABBA (FRAMEBENCH.md standard run, `gpu cg 0` / `1`,
   like research/framebench/ddrgov-*). Pass: not slower within run spread. fgab.py `"gpu cg 0" "gpu cg 1"` screen
   on idle (GPU powered) and during a steady animation if one can be held.
2. **Collapse bring-up**: `sweetgpupc=1`: first collapse / resume with SMMU and register readbacks logged, a vm
   map/unmap while off, `gpu pc stress 1000`, display off/on 10x, a few minutes of normal UI. Pass: 0 SMMU faults,
   0 job timeouts, no hang, resume latency logged.
3. **Performance**: framebench ABBA with `gpu pc off` / `on` on one boot; plus a non-touch case (a notification or
   a timer animation from idle) comparing first-frame times. Pass: not slower within noise.
4. **Power** (fgab.py, alternating 20 s windows, first 4 s dropped): screen off `"gpu pc off" "gpu pc on"`, screen
   on idle on Home the same; step 2b separately (`gpu pc cx 0` vs `0x80`, screen off). Pass: a saving with it on.
5. Then propose the default (`sweetgpupc=1`, `sweetgpucg=1`) and a boot_b image to the user.

Known limits: the lock screen after boot renders at ~50 flushes/s (ddrgov findings), so the GPU never idles there;
that is a separate item (what animates), not this one.

## Bring-up results (2026-10-29, temporary `fastboot boot` only, nothing flashed)

Patch `xnu/patches/j0115-jasmine-gpu-idle-power.patch` (sweet_gpu.c, sweet_ddrgov.c, sweet_pmic.c), VM builds
`xnu/out-jasmine-j0115` and `-j0115b` (b = + `batt icl`, the measurement aid below). Images
`shim/out/shim-boot-j0115-test.img` (a8b92df5...) and `-j0115b-test.img` (28e237af...): kernel + the j0114d ADT +
the installed boot_b args byte-identical (the 607-byte command line has only 16 bytes left, so both features were
switched live over the command port; defaults off). Logs `logs/netlog-j0115-test.txt`, `logs/netlog-j0115b-test.txt`.

Behaviour (observed):
- `gpu pc stress 200` twice (HWCG off, then on) + the UI: **800+ collapse/resume cycles, 0 failures, 0 SMMU
  rewrites, 0 zap resumes**: the SMMU keeps its state over GX off (qcom,retention) and CP_SET_SECURE_MODE 0 alone
  works after every resume (a512 CPZ retention confirmed). Stress resume 283-554 us (avg 348), collapse 16-162 us.
- Real use (mode 1, hold 80 ms): the idle home screen collapses within 80 ms of the last frame; resume in the submit
  path avg ~650-950 us (max 2.7 ms once; 3.4 ms when the step-2b CX vote had to be restored). Touch pre-wake works
  (`pre-wakes` counter; e.g. a swipe from idle resumed in 466 us before its first submit).
- 10 display off/on cycles with unlock (power key = `key 0`; `key 3` is Home): GX off while dark, back on unlock,
  0 failures. Framebench runs below: no job timeout, no SMMU fault, no panic in either log.

Performance, framebench on j0115, one boot, swap arrivals/s, mean (min-max) of the runs per setting; order
off, on, on, off, cg, pc, pc, cg, off, on, on (`research/framebench/gpupc-1..11-*`); "on" = HWCG + collapse,
"cg" = HWCG only, "pc" = collapse only; run 1's home-a excluded (no motion, the same artifact as ddrgov run 1):

| Phase | off (3) | on (4) | cg (2) | pc (2) | on / cg / pc vs off |
| --- | ---: | ---: | ---: | ---: | --- |
| spotlight first | 25.32 (23.4-27.0) | 25.18 (23.9-27.3) | 25.38 (25.1-25.7) | 25.23 (24.2-26.2) | -0.6 / +0.2 / -0.4 % |
| spotlight repeat | 29.12 (26.7-33.1) | 28.50 (26.2-32.5) | 26.55 (26.2-26.9) | 27.19 (27.0-27.4) | -2.1 / -8.8 / -6.6 % |
| warmup | 37.97 (37.4-38.9) | 37.42 (37.0-37.8) | 37.73 (37.5-38.0) | 38.38 (38.3-38.5) | -1.5 / -0.6 / +1.1 % |
| home-a | 41.03 (41.0-41.1) | 40.40 (39.9-41.0) | 41.00 (40.6-41.4) | 40.89 (40.8-41.0) | -1.5 / -0.1 / -0.4 % |
| control-a | 28.76 (28.4-29.0) | 28.83 (28.3-29.4) | 29.09 (28.8-29.4) | 29.12 (28.8-29.4) | +0.2 / +1.1 / +1.2 % |
| home-b | 40.94 (40.4-41.4) | 40.95 (40.5-41.2) | 40.74 (40.6-40.9) | 40.66 (40.6-40.7) | 0.0 / -0.5 / -0.7 % |
| control-b | 28.75 (28.3-29.1) | 29.60 (29.1-30.7) | 28.95 (28.6-29.3) | 29.60 (28.6-30.6) | +3.0 / +0.7 / +3.0 % |

Spotlight repeat drifts with time over the series (33 in run 1, 26-28 from run 4 on), so its cg/pc values (mid-
series) are not a feature effect. home-a "on" is 1.5 % lower on average, but its later runs (41.00, 40.32) sit in
the off range and off has only two valid samples; no phase is lower in every run. Median and p95 frame times are
unchanged. Conclusion: no regression measurable within run-to-run noise; not proven equal to better than ~1.5 %.
A gesture runs while the GPU is already on (pre-wake, frames < 80 ms apart): ~15 collapses per framebench run.

Power, paired A/B on one boot (`tools/g2/fgab.py 8 20`, alternating 20 s windows, order flipped each cycle, first
4 s dropped). The battery was made to carry the load with USB data up by `batt icl 100 3600` (j0115b: USB input
limited to 100 mA for up to an hour, restored by the charger thread or `batt icl 0 0`), so load changes show 1:1
in the battery current; absolute values are not the unplugged ones, the differences are.

| Display | A | B | B-A (positive = saves) | n |
| --- | --- | --- | ---: | ---: |
| on, idle home | both off | HWCG + collapse | **+70.3 mA** (sd 58; median cycle +76; first/last cycle outliers) | 8 |
| off | both off | HWCG + collapse | **+58.5 mA** (sd 23, all cycles positive) | 8 |
| off | both off | HWCG only | **+52.4 mA** (sd 14.5) | 8 |
| off | HWCG only | HWCG + collapse | **+12.1 mA** (sd 9.3) | 8 |

So clock gating is most of the saving with the screen off (an idle 588 MHz GPU with every clock running), GX
collapse adds ~12 mA (leakage behind the head switch, PLL); together ~60 mA screen off and ~70 mA screen-on idle,
against the plan's 40-100 mA estimate and the ~437 mA screen-off total.

Step 2b (CX vote while off): `gpu pc cx 0x80` sent the SVS vote (RPM acked), but PM660L S3 (VDD_CX) stayed at
860 mV (`spmi 3 0x1a40 2` = 0x035c before and while low): the RPM holds CX up for other voters (likely the DDR/bus
clocks), so lowering our vote saves nothing here. Not pursued; `sweetgpupc_cx` stays 0. Step 3 (idle frequency
drop) not needed: with HWCG and an 80 ms collapse the idle-but-powered window is short.

Next: the user decides the defaults (`sweetgpucg=1 sweetgpupc=1` as the kernel default, as the DDR governor went,
then a slot-b image).
