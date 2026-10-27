# CPU DVFS restart: both clusters, stock ceilings and thermal limits

2026-10-26. Scope requested by the user: make all eight CPUs available, allow
stock maximum frequencies, and scale with demand to control power and heat.
This supersedes the starting assumptions in HANDOFF-CPUCLK.md, not its historical
observations. Implementation is in progress; a working governor is not installed.

**2026-10-27 milestone:** [SAW4 wide voltage requests work on both clusters](PERF-CPU-VOLTAGE-20261027.md).
SIZE bit20 selects a full sixteen-bit request; delayed PMIC target/valid readings
tracked Silver872→876→872mV and both Gold supplies868→872→868mV. Clocks/APM/
MEM-ACC remained unchanged, and Gold's all-core checker passed while raised and
after restoration. The earlier voltage-commit blocker is resolved for these
small tests; full-range/PLL/array transitions remain unvalidated.

j0059a repairs the live check reference on sweetcmd-only boots before sweetgold,
then returns without OSM setup/workers. CI40410605951/e74a086 and subsequent
CI40414145643/40b6e3d pass actual ARM compilation and host/source/symbol guards.
Device startup100runs/core and live20runs/core pass on4 and8 CPUs, with each
worker on the correct CPU/MPIDR/cluster. No clock or core-count default changed.

[Current 2+2 CPU baseline](PERF-CPU-BASELINE-20261026.md) found no clear eight-core
UI gain at existing clocks, with sampled CA render work entirely on Gold.
The AMP ADT already sets the correct Jasmine Silver1843.2MHz maximum metadata.

j0102's opt-in neutral RPM probes ACK on S1/S2/S3, but a subsequent S1 request
for876mV left target/valid at872mV. Do not treat RPM ACK as voltage control.
SAW16 is the demonstrated path. Never send an implicit single-key first CPU
RPM vote; the bounded neutral probe explicitly initializes UV+enable together.

## Findings and first milestone

- Eight-core bring-up already passed on 2026-10-22 (CI 39798911718,
  `m4kf`, all-core checker zero errors). It requires `TOPAZ_4K`, AMP ADT and
  `cpus=8`. `tools/g2/mkimg.sh` supports `AMP=1 CPUS=8`. Four Gold cores remain
  the documented default because older eight-core UI comparisons regressed.
- The current kernel still has the manual Gold PLL switch and diagnostic OSM
  code; there is no working dual-cluster CPU governor or thermal clock cap.
  Gold's boot default is 1747.2 MHz; Silver was measured at 1382.4 MHz.
- The recorded OSM attempts did not start its clock/sequencer; secure writes were
  dropped. Software DVFS remains the working direction. This is an observation
  about this boot path, not proof that OSM can never work.
- Before this restart, a voltage experiment requested988mV and changed PMIC setpoints, but
  **valid voltage stayed 868 mV**. Rollback restored requested/set/valid to 868.
  APM control/status stayed in MX mode. An APM relationship remains a hypothesis;
  neither that experiment nor a SAW echo proved a usable voltage transition.
  The new SAW16 tests now establish a small-step path without switching APM.
- `spm-regulator.c` reads FTS426 voltage from offset 0x42/0x43 and writes the
  two-byte target at 0x40/0x41. The existing SAW path masks `0x700ff` in VCTL
  and PMIC_DATA_3. These paths must not be assumed equivalent. PMIC valid voltage
  is a digital status reading, not an independent physical rail measurement.

`tools/cpuclk/cpuclk_model.py` now models both controllers, including Silver's
distinct fuse fields, reference voltages and corner names. Both OSM efuse resources
in this phone's stock DT map to 0x784130; both select bin 1, CPR combo 10.
Missing fuse rows now fail instead of becoming zeros. Conflicting captures and
values wider than 64 bits also fail. `--zero` is explicitly synthetic.

The saved stock DT plus existing j39f fuse capture produce:

| Cluster | Model frequencies, MHz | Top floor / open-loop / adjusted ceiling |
| --- | --- | --- |
| Gold / apc1 / S2+S3 | 300, 1113.6, 1401.6, 1747.2, 1958.4, 2150.4, 2208 | 908 / 948 / 948 mV |
| Silver / apc0 / S1 | 300, 633.6, 902.4, 1113.6, 1401.6, 1536, 1747.2, 1843.2 | 860 / 900 / 900 mV |

These are derived tables, **not validated operating points or write recipes**.
The stock DT enables scaled-open-loop-as-ceiling; the unadjusted 1068 mV top
ceiling is not the final per-chip limit. Do not repeat the old arbitrary 988 mV
request as the next experiment. The model retains OSM LUT/register output as a
reference, even though OSM is not functioning. Software PLL switching needs its
own transition implementation, including divider handling at low steps.

## Thermal reference audit

The stock DT's thermal client IDs are not raw TSENS register indices. The
downstream [TSENS driver](https://android.googlesource.com/kernel/msm/+/6e80ff47b2884814419d9c9daee41ed6b44ea237/drivers/thermal/msm-tsens.c)
maps `qcom,client-id` through `qcom,sensor-id`. Current XNU `tsens` output is in
raw hardware order, so use the mapping before assigning per-cluster limits:

| Stock policy zone | Client ID | Raw hardware index | XNU cluster |
| --- | ---: | ---: | --- |
| cpuss-0-step (Android CPUs0-3) | 1 | 10 | Silver, XNU CPUs4-7 |
| cpu-1-0-step (Android CPU4) | 3 | 4 | Gold, XNU CPU0 |
| cpu-1-1-step (Android CPU5) | 4 | 5 | Gold, XNU CPU1 |
| cpu-1-2-step (Android CPU6) | 5 | 6 | Gold, XNU CPU2 |
| cpu-1-3-step (Android CPU7) | 6 | 7 | Gold, XNU CPU3 |

Those CPU isolation trips are105C with10C hysteresis; they are not a suitable
comfort target. Stock `quiet-therm-step` instead caps Gold at50C and Silver at53C
using an ADC thermal provider (phandle0x20, channel0x51), not the TSENS CPU
temperature. Do not apply those50/53 thresholds to raw CPU sensors or claim a
CPU-only cap reproduces stock board-temperature control. Board/skin sensing,
per-cluster caps and an independent emergency limit need separate validation.
No production thermal thresholds have been selected or installed yet.

## Implementation sequence and gates

1. **Re-establish a read-only baseline.** Use the current integrated 4K kernel
   and exact symbols; baseline four Gold, then eight cores at existing clocks.
   Capture identity, topology/psets, both PLL/RCG/SAW blocks, S1-S3 set/valid/limits,
   both APM states, MEM-ACC and valid TSENS readings. Respect the shared phone
   lock, charging-shell readiness and post-boot settling checks. Existing tools:
   `state` (Gold only), `rails`, `tsens`, plus whitelisted `r` reads for Silver.
   Use `sweetcmd=1` without `sweetosm` for these reads while retaining sweetgold.
   Important source-audit findings: `sweetosm=8` skips sweetgold (the skip is
   `sweetosm>=2`), so it is not a normal 1747 MHz baseline. Also, live `check`
   under sweetcmd alone compares against an uninitialized `osm_ref`; repair its
   reference initialization before relying on it. Until then the existing Gold
   startup checker covers all online CPUs. Do not use `sweetosm=1` casually:
   historical broad probes encountered SError on some CPRh registers.
2. **Voltage commit: small-step gate passed.** SAW4 SIZE/full-width data is now
   proven on both supplies. Audit the stock APM/MEM-ACC ordering and extend the
   bounded tests to target operating points, one cluster at a time. Capture target, SAW status,
   both Gold supply statuses, APM acknowledgement and delayed valid voltage.
   Predefine rollback. A mismatch, timeout or unreadable status rejects the step;
   it must never unlock a higher clock. Do not blindly toggle APM to test a theory.
3. **Implement a serialized transition backend for each cluster.** On an upward
   transition establish the required supply and memory/array state before increasing
   frequency; on downward transitions reduce frequency before relaxing those
   requirements. Audit crossover ordering separately. Keep a known-good clock
   source while programming a PLL; bound update/lock/settling polls and rollback.
   Avoid `str wzr` MMIO stores. Test under all-core load and during repeated ramps.
4. **Add load policy and task-13 thermal caps together.** Separate per-cluster
   requests and supported tables, fast ramp-up and hysteretic ramp-down. Track
   requested versus actual frequency and limiting reason. Enforce thermal caps
   independently of load requests. Invalid/stale sensors must prevent boost.
   Select sensor mapping, thresholds, hysteresis and recovery using the stock
   thermal policy and measured headroom; PMIC trip temperatures are not CPU/skin
   limits. No arbitrary production thresholds have been selected yet.
5. **Recheck task 6 with the governor.** Keep latency-sensitive work on Gold and
   evaluate background/spill work on Silver using XNU's actual AMP placement and
   capacity assumptions. A clock governor cannot by itself fix task placement.
   No blanket assertion that Gold must always have the higher numerical MHz:
   frequency alone does not establish relative core capacity. Compare settled
   4/8-core baseline and result with matched GPU/DDR/Wi-Fi/library/workloads.
6. **Acceptance and defaults.** Require zero checker errors on all CPUs at each
   allowed level and during transitions, measured ramp/idle behavior, thermal-cap
   entry/recovery, sustained UI stability, and power/temperature comparisons.
   Report actual display metrics where available; GL flushes are not display FPS.
   Only validated levels become available by default. Temporary `fastboot boot`
   first; installation/partition writes require the user's destructive-step
   confirmation under root AGENTS.md.

CPU power collapse remains task 12. DVFS alone does not establish good deep-idle
power, and eight online CPUs need not mean eight busy CPUs. Stock maxima are
ceilings available when load and thermal headroom allow, not all-core promises.

## Reproduction and validation

From the repository root (DTS/fuses remain local, never add them to git):

```text
python tools/cpuclk/cpuclk_model.py research/cpu-dvfs/stock.dts logs/netlog-j39f-osm.txt --cluster both
python tools/cpuclk/cpuclk_model.py research/cpu-dvfs/stock.dts --zero --cluster both
python -m unittest discover -s tools/cpuclk -p test_*.py
```

Six input-integrity tests PASS. Both actual-input and synthetic tables generate.
Gold output before/after is byte-identical (saved PowerShell transcript files SHA256
`7cbbfc65d76eb1ba5670cd06fdd9843e72867666f6e0429d1b3fe6d8e20e7927`).
Silver fuse maps checked against the saved downstream source; Silver voltage/
frequency correctness on hardware remains untested. No kernel build, CI dispatch,
phone command, clock/voltage change, root write or flash in this milestone.

References: WSL `~/cpuclk-src`, LineageOS lineage-19.1 downstream sources;
`~/jasmine-dtb/stock/dtb0.dts` SHA256
`baea4df465a2422f003166301a9fd0cadcae8632a8ef5312b1bf16c6adc00a56`.
Saved source SHA256: `cprh-kbss-regulator.c`
`2d8dcb274d0bd69fe36d73e61ef3817674ade2e102300b188fa2a2b587375f7d`;
`clk-cpu-osm.c` `914e8d9f37efe75484fc3f0b562cf3bf17a468318a17bb3af424a286bfa5fadd`;
`spm-regulator.c` `e3d12e7211b19bc4d2af24c9aaf60a2fc7f8ecaaf45f4eaea44caa2cbfc87663`.
