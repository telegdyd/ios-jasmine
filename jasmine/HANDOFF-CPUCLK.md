# Brief: the Gold cluster's clock done properly (OSM + CPRh, DVFS)

**2026-10-26 restart:** this is a historical brief. The active dual-cluster plan
and first implementation milestone are [PERF-TASK2-DVFS.md](PERF-TASK2-DVFS.md).
Eight cores already boot with 4K pages; OSM attempts and the SAW voltage blocker
are recorded in NOTES.md. The offline model now covers Silver too. Follow the
active plan for current scope, voltage limits and diagnostic-mode caveats.

Written 2026-10-22 05:10 for the next agent, at the user's request. Scope: make XNU run the four Gold cores the way
the stock Android kernel does: Qualcomm's OSM clock sequencer with per-chip CPR voltages, frequency scaling with load,
and the hardware limits. Goals: speed (2208 MHz instead of a fixed 1747 MHz) **and** power (low clock and voltage when
idle; today the cluster runs at 1747 MHz at XBL's voltage all the time).

Read first: [HANDOFF-G2.md](HANDOFF-G2.md) §2 (the user's ground rules, they apply unchanged) and §4 (kernel CI
workflow, pitfalls), [NOTES.md](NOTES.md) item 3 under "Next" (what j0015/j0016 found), and
[HARDWARE.md](HARDWARE.md) (CPU table). This brief is self-contained otherwise.

## 1. Where things stand

- XNU runs on the **4 Gold cores only** (`cpus=4`, 16 KiB pages; the Silver cores have no 16K granule, see PLAN.md
  phase 7). XBL leaves Gold on GPLL0 (measured ~180 MHz effective), with the cluster's own PLL idle and **OSM and
  CPRh off** (OSM enable 0, CPRH_STATUS 0, SAW4 PMIC_STS 0).
- **j0015** (`sweetgold=MHz`, `xnu/patches/j0015-jasmine-gold-clock.patch`) reprograms the Gold PLL like msm-4.4
  `clk-cpu-osm.c` and moves the cluster RCG onto it, **without touching the voltage**, checked by a deterministic
  workload before and after the switch (and on all four cores 20 s later; wrong result -> back to GPLL0).
  **j0016** adds the higher table steps. Every image uses `sweetgold=1747` (1747.2 MHz, 0 errors on 4 cores at XBL's
  voltage). 1958/2150/2208 MHz were never tried: at XBL's voltage they may be unstable, and that is exactly why the
  proper way is needed.
- No cpufreq, no DVFS, no thermal throttling. TSENS is readable (logged around j0015's load check).
- Facts found on 2026-10-21 (NOTES.md): Gold PLL 0x17816000 (L 0x20, user 0xf, config 0x200d4828, mode 7), Gold RCG
  0x17811050 (cmd 2, cfg 0x401 = GPLL0); Silver PLL 0x17916000 L 0x48 (1382 MHz), RCG cfg 0x501; OSM version 0x70000;
  speed-bin fuse at 0x784130 = `0x3040008c 0x88614230`; the APC rails (PM660 S1-S3) are **not readable from the apps
  EE** (only OSM/CPRh/SAW see them).
- Phone state at the time of writing: up on the G2 test image `shim/out/shim-boot-j38-bb8.img` (kernel j0038). Slot b
  (the normal power-on boot) is the j0024 standalone kernel with `sweetgold=1747`; **do not flash it** without the
  user's OK.

## 2. The reference: the phone's own stock device tree

`~/jasmine-dtb/stock/dtb0.dts` in WSL ("SDM 660 PM660 + PM660L MTP, Jasmine", decompiled from the stock boot image)
has every table as data. Use it, not numbers from memory.

| Node | What | Key properties |
| --- | --- | --- |
| `qcom,clk-cpu-osm` (line ~2944) | OSM, both clusters | `reg` osm 0x179c0000, pwrcl_pll 0x17916000, perfcl_pll 0x17816000, apcs_common 0x179d1000, pwrcl/perfcl efuse 0x784130; `qcom,perfcl-speedbin{0,1,3,4}-v0` (LUT rows: freq, PLL/override word, ..., corner), `qcom,osm-clk-rate` 200 MHz, `qcom,l-val-base`, `qcom,apcs-pll-user-ctl`, `qcom,apm-mode-ctl` 0x179d0004/0x179d0010, `qcom,apm-threshold-voltage` 872 mV, `qcom,boost-fsm-en`, `qcom,droop-fsm-en`, `qcom,pc-fsm-en`, `qcom,ps-fsm-en`, `qcom,cc-*`, `qcom,llm-*` |
| `cprh-ctrl@179c4000` (line ~6540) | CPRh for **apc1 = Gold** | `reg` cpr_ctrl 0x179c4000, fuse_base 0x784000; `qcom,cpr-thread-id` 0; `qcom,cpr-fuse-corners` 5, `qcom,cpr-fuse-combos` 40, `qcom,cpr-speed-bins` 5, per-bin corners, `qcom,cpr-voltage-ceiling` / `-floor` (first list: ceilings 724..1068 mV, floors 588..844 mV), `qcom,corner-frequencies`, open/closed-loop fuse adjustments, `qcom,cpr-target-quotients`, `qcom,cpr-ro-scaling-factor`, `qcom,apm-crossover-voltage` 872 mV, `qcom,voltage-step` 4 mV, `mem-acc` |
| `cprh-ctrl@179c8000` (line ~6476) | CPRh for apc0 = Silver | not needed while Silver is unused |
| `qcom,msm-hw-limits` | LMh, per cluster | 0x179ce800 + 0x179c1400, 0x179cc800 + 0x179c3400 |
| `qcom,msm-cpufreq` | cpufreq tables | `qcom,cpufreq-table-4` = Gold |

Perfcl speed bin 1 LUT (from the DT): 300, 1113.6, 1401.6, 1747.2, 1958.4, 2150.4, 2208 MHz. Speed bin 0's corner
list goes to 2457.6 MHz: **which bin this chip is comes from the fuse** (0x784130), decode it, do not assume.

The algorithms (how fuses become per-corner voltages and target quotients, how the OSM LUT and sequencer are
programmed, APM and mem-acc switching, CPRh closed loop, LMh) are in the downstream msm-4.4 kernel for this phone:
`drivers/clk/qcom/clk-cpu-osm.c`, `drivers/regulator/cprh-kbss-regulator.c`, `cpr3-regulator.c`, `cpr3-util.c`,
`arch/arm64/boot/dts/qcom/sdm660*.dtsi` (Xiaomi's/LineageOS `kernel_xiaomi_sdm660` or CAF `msm-4.4` for sdm660; not on
disk, fetch it into WSL, outside the repo). Also worth checking: SoMainline's mainline work for SDM630/660 (an OSM
clock driver and a CPR3/CPRh driver were posted upstream around 2021-2022). Mainline postmarketOS (the Nura kernel)
has no CPU scaling on this SoC (HARDWARE.md).

**Open question for the user before porting code:** Linux code is GPL-2.0, our kernel patches go into XNU (APSL).
Earlier patches in this repo were written from register facts, not copied. Ask whether copying or close adaptation of
the Linux drivers is acceptable, or keep writing our own from them. (Do not decide this yourself; a wrong licence
assumption cost the previous session hours.)

## 3. The plan, in rounds with exit checks

Each phase is a kernel patch `j0039`, `j0040`, ... built by CI, booted with `fastboot boot`, gated by a boot-arg so a
boot without it is today's behaviour. Keep `sweetgold=` (j0015) working as the fallback until the end.

**Phase 0, offline (no phone):** fetch the downstream sources; write a small Python model (`tools/cpuclk/`) that
takes the fuse words and the DT properties and computes, as the downstream driver does: the speed bin, the fuse
combo, per-corner open-loop voltages, closed-loop floors/ceilings and target quotients, and the OSM LUT rows. Exit: a
table for this chip, with every formula's source line noted.

**Phase 1, read-only probe (boot-arg `sweetosm=1`):** dump the OSM, CPRh (apc1), APM, SAW and LMh register blocks and
**all** CPR fuse rows the model uses (fuse_base 0x784000) into the log; compute the LUT in the kernel too and compare
with the Python model. Writes nothing. Exit: kernel and model agree; the registers say what the DT says they are.

**Phase 2, OSM with open-loop voltages (`sweetosm=2`):** program the OSM LUT (frequency, PLL, open-loop voltage
**capped at the corner ceiling**), the sequencer, APM crossover and mem-acc as the downstream driver does; enable OSM
for the Gold cluster and hand the cluster from j0015's manual PLL to OSM at 1747.2 MHz. Then request each LUT step in
turn (OSM's per-cluster DCVS request) and run j0015's deterministic workload at each, one core and four cores. Exit:
every step correct on four cores, TSENS within limits, no hang; the LUT read back matches. If the voltage cannot be
confirmed (rails unreadable), the open-loop ceiling is the safe side; never go above a corner's ceiling.

**Phase 3, CPRh closed loop (`sweetosm=3`):** enable CPRh for apc1 (thread 0) with the fused target quotients, so
the voltage settles between floor and ceiling per chip. Read back CPRh status / SAW PMIC_STS each step. Exit: steps
still correct, settled voltages between floor and ceiling and below open loop.

**Phase 4, DVFS:** a governor in XNU that picks the LUT step from load. XNU has no cpufreq framework on non-Apple
SoCs; candidates: the scheduler's perfcontrol callouts (`sched_perfcontrol_register_callbacks`: per-core run/idle and
thread QoS, what Apple's CLPC uses) or a simple sampling governor (idle time every 20-50 ms, up fast, down slowly).
Minimum step when idle (300 MHz), top step under load. Exit: idle sits low, a workload ramps to the top within tens of
ms, j0015's checker passes during ramps, UI does not feel slower (ask the user).

**Phase 5, limits:** OSM's boost/droop/power-collapse FSMs as the DT enables them, LMh (hardware thermal and current
limits) and a TSENS trip that forces a low step. Exit: under a long all-core load the clock steps down before TSENS
hits the downstream thermal-zone limits, then recovers.

**Phase 6, power and default:** measure (see below), then propose to the user to make it the default in the G2 test
images and, with their OK, in slot b.

## 4. Power: how to measure, and two cheap wins

- There is no battery current reading on the iOS side yet (SweetBattery reports a static 100 %). Options: read the
  PM660 fuel gauge over SPMI in the kernel (current, voltage; the Nura/Linux side has `pmi8998_fg` / qcom FG code to
  learn from), or ask the user for a USB power meter reading at idle on the lock screen. Decide with the user.
- **Silver cluster:** check what the Silver cores do after the shim hands off to Gold (spinning, WFE, or PSCI
  CPU_OFF) and at what clock (XBL leaves it at 1382 MHz). If they are not off, a PSCI CPU_OFF from each (or cluster
  power collapse) is a power win independent of the rest.
- **Gold idle:** what XNU's idle does on these cores (WFI only?). PSCI CPU_SUSPEND / cluster power collapse is the
  other half of power efficiency; at least note it, it is a later step.

## 5. Risks and rules

- **Voltage is the dangerous part.** Too low: the core computes wrong results or locks up (the checker catches the
  first; the second needs power + volume down). Too high: heat. Never program a voltage above the corner's ceiling,
  never below its floor; open loop before closed loop; one change per round.
- MMIO writes: no `str wzr` stores (Qualcomm's hypervisor hangs on them, j0018/j0024 history): write a register.
- A hang needs the user (power + volume down). Say before such a round that it may hang.
- No live reload of anything on the phone; reboot instead. Never flash without the user's OK. Phone access, CI, image
  tools: HANDOFF-G2.md §4 (`tools/g2/mkimg.sh` takes `EXTRA_ARGS` and `VARIANT=`, `GPUDBG=0`; the G2 images carry
  `sweetgold=1747` in the base boot-args in `mkimg.sh`).
- Record each round in a "CPU clock" section of NOTES.md (clock times, CI run ids, logs), commit with
  `-c user.name=telegdyd -c user.email=telegdyd93@gmail.com` and the trailer
  `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`, push.
- When a restriction (this brief's or an older note's) starts costing real time, ask the user whether it still holds.

## 6. Done when

Gold runs under OSM with CPRh closed-loop voltages from this chip's fuses, scales between 300 MHz and the bin's top
step with load, steps down under thermal limits, j0015's checker passes at every step, and idle and loaded power (or
temperature, if no power reading exists) are measured against today's fixed 1747 MHz. Everything gated by a boot-arg,
written up, committed and pushed; making it the default is the user's call.
