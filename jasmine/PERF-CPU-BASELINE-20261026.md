# Current CPU baseline: four Gold versus eight cores

2026-10-26, task2/task6 restart. Eight cores work, but these two matched repeats
do not establish a UI performance gain at the existing clocks. Keep the current
default while developing demand scaling, thermal caps and verified voltage control.

## Configuration and method

Temporary images only, accepted integrated kernel d42bfb4 / CI40398100808,
SHA256 `4f9c55643af4913da5fda53556a3f835a2a705d1d07a6f4e4516509b1b184589`.
Same 4K kernel, AMP ADT, shim, production library, Wi-Fi and boot arguments;
the two images differ only in `cpus=4` / `cpus=8`. No CPU voltage changes.
`tools/cpuclk/images.py` generates them with independent roundtrip/header/hash
checks recorded locally. `sweetosm` is omitted, retaining the normal manual
Gold clock. `sweetcmd=1 sweetddr=1804` is explicit in both variants.

- Gold1747.2MHz, Silver's boot PLL1382.4MHz, GPU588MHz (measured587-588), DDR1804.
- PMIC S1 set/valid872mV; S2/S3 set/valid868mV; APM and MEM-ACC registers0.
- Production library read back SHA256
  `14e32aea4121e9c8a357da8f5e6322fe572a85f1c22e496990af0e687cb19261`.
- Startup checker: four and eight CPUs, 100 runs each, zero errors.
- Home screen checked from render-surface dumps; user separately confirmed that
  the horizontal artifacts in one dump are absent from the physical screen.
- Post-unlock accessoryupdater/trustd settling checked with3s profiles. No
  sync-process CPU samples in the measured Home/Control windows of valid runs.
- Existing `framebench.py` standard workload twice per variant, matching symbols.
  Zero event/sample drops. Capture/symbolication is separate from screenshots.

Baseline4 boot23:15; clean fastboot23:23:27; baseline8 followed. Four-core runs
preceded eight-core runs; boot/order/thermal variation is not randomized. End
TSENS maxima58.2/58.5C on four,60.2/60.8C on eight. This is not a power
measurement or proof that the core count caused the temperature difference.

## Rendering arrival results

Rates are swap arrivals during scripted motion, **not displayed FPS**. Intervals
are milliseconds. CTL-clear remains an unvalidated scanout proxy; no physical
frame-counter observations were captured. No additive speedup estimate is justified.

| Cores / capture | Home B arrivals/s | Home B median / p95 | Control B arrivals/s | Control B median / p95 |
| --- | ---: | ---: | ---: | ---: |
| 4 / baseline4-a | 21.84 | 47.79 / 51.85 | 20.23 | 46.72 / 70.51 |
| 4 / baseline4-b | 21.57 | 47.44 / 51.80 | 21.19 | 45.12 / 64.35 |
| 8 / baseline8-b | 22.10 | 46.89 / 52.99 | 20.50 | 47.09 / 73.20 |
| 8 / baseline8-c | 20.28 | 48.12 / 53.70 | 19.97 | 52.63 / 70.44 |

Control A arrivals/s: four20.62/21.34, eight20.44/20.34. The old roughly
twofold eight-core regression was not reproduced. The current small mixed
differences and tails do not support choosing eight as a performance default.

All sampled on-CPU CoreAnimation primary-display-thread records were on Gold:
1103/1552 samples in the four-core runs,1646/1666 in the eight-core runs,
**zero on Silver**. This does not prove every worker or every unsampled interval
was placed well, but it does not support reusing the old render-thread-on-Silver
diagnosis. Task6 should use this current evidence before changing scheduling.

## Exclusions and evidence

`baseline8-a` is excluded: its initial gate ran before unlock, then sync resumed
after unlock. Sampled Home A trustd/accessoryupdater were about638/439ms/s.
The post-unlock gate and repeated captures replaced it. In `baseline4-a`, Home A
had no swap arrivals and is excluded by the existing analyzer; Home B and Control
remain usable. These exclusions are retained explicitly, not silently discarded.

Ignored local evidence: `research/cpu-dvfs/`, including image manifests,
baseline4/8 boot logs and screenshots, production readback, settle profiles,
`baseline4-{a,b}` and `baseline8-{a,b,c}` framebench directories,
`comparison.json`, and charging/reboot records. Raw device data is not in git.
Baseline4 shutdown reported zero GPU imports/pins at RootUnmount and actual
fastboot return. Baseline8 also returned to actual fastboot before parking.
No new runtime GPU/SMMU fault observed; startup FSR0x400 is the known baseline.

The diagnostic checker repair and RPM supply probe have their own CI/device
gates in [the active DVFS plan](PERF-TASK2-DVFS.md); they are not speed gains.
