# Frame-rate bottleneck on the installed configuration (2026-10-28)

Fresh measurements on the installed boot_b (kernel j0108, CI 40551286401; production
libsweetca 4780fbaa, CI 40601658380; 8 cores, CPU auto governor, GPU 588 MHz, DDR 1804 MHz).
One boot, no reboot or flash. All clock changes were runtime command-port settings, restored
afterwards (`dvfs auto 1`, `gpu clk 588`, `ddr 1804`; read back).

## Answer

**The GPU's DRAM traffic is the bottleneck.** Frame rate follows the DDR clock, hardly
follows the GPU core clock and ignores the CPU clock. Every batch renders in sysmem
(`FD_MESA_DEBUG=sysmem` set by libsweetca), so every blend, overdraw and blur pass reads
and writes the 1125x2436 framebuffer in DRAM. On top of that, frames are paced by
CoreAnimation's 16.7 ms frame clock and no frame finishes in one period: Home runs at
2 periods (30 fps) most of the time, Control Center half at 2 and half at 3 (20 fps).

## Clock sensitivity (same boot, standard framebench schedule per row)

Swap arrivals per second during scripted motion and median interval. home-b and control-b
are not CPU-sampled; control-a is. Not validated displayed FPS (framebench caveat).

| Config | Change | Home B | Control A | Control B |
| --- | --- | ---: | ---: | ---: |
| base (fb-a) | defaults | 26.27/s, 35.8 ms | 22.61/s, 44.0 ms | 22.65/s, 42.4 ms |
| base2 (last) | defaults | 27.09/s, 35.5 ms | 22.05/s, 44.1 ms | 22.01/s, 44.6 ms |
| cpumax | Gold 2208 / Silver 1843 pinned | 26.99/s, 35.6 ms | 21.68/s, 46.6 ms | 23.05/s, 43.1 ms |
| cpulow | Gold and Silver pinned 1401.6 (-37% Gold) | 26.60/s, 36.4 ms | 23.05/s, 43.6 ms | 23.46/s, 43.1 ms |
| gpu647 | GPU +10% | 27.27/s, 35.5 ms | 21.98/s, 47.5 ms | 22.08/s, 44.4 ms |
| gpu430 | GPU -27% | 25.32/s, 38.3 ms | 20.56/s, 50.0 ms | 20.30/s, 48.1 ms |
| ddr1296 | DDR -28% | **22.26/s, 45.4 ms** | **18.13/s, 61.5 ms** | **17.22/s, 62.5 ms** |

- CPU: no effect in either direction (cpulow equals base within run-to-run noise). The auto
  governor is not limiting and CPU speed is not the bottleneck at these loads.
- GPU core clock: -27% costs 4% (Home) to 10% (CC). +10% gives nothing measurable.
- DDR: -28% costs 15% (Home) and 20-24% (CC). The strongest lever by far.
- base and base2 bracket the round (first and last), so drift/thermal effects are small
  (TSENS 53-62 C throughout).

## GPU timeline (control-a, sampled window)

GPU job submit -> completion-observed intervals (completion polled every 50 us by waiters),
union per frame:

| Config | GPU busy per frame | GPU idle per frame |
| --- | ---: | ---: |
| base | 34.9 ms | 9.3 ms |
| gpu430 | 36.8 ms (+5%) | 11.9 ms |
| ddr1296 | 41.1 ms (+18%) | 14.1 ms |
| cpulow | 31.2 ms | 12.2 ms |

A Control Center frame is ~8 GPU jobs, nearly all touching the full-screen framebuffer
(surfaces 2/4). The CPU submits them within ~16 ms, the GPU then executes them back to back
for 30-50 ms, then sits idle ~10 ms until the next frame's first job (CoreAnimation waits
for each frame's GPU work before starting the next). GPU busy time scales with DDR, not with
the GPU clock: the GPU is waiting on memory, not computing.

Hardware counters (`ddr bw 4000 bg` during 4 s of motion, GPU 588 MHz, DDR 1804;
`research/bottleneck-20261028/bw-counters.txt`):

| Window | GPU busy | RAM-starved | VBIF traffic |
| --- | ---: | ---: | ---: |
| idle | 0 | 0 | 0 |
| home swipes (x2) | 418-421 Mcyc/s | 233-234 Mcyc/s (56%) | 5.3-5.4 GB/s |
| Control Center (x2) | 390-400 Mcyc/s | 258-260 Mcyc/s (65-66%) | 5.1-5.5 GB/s |

The windows include the gaps between gestures, so busy-in-motion is higher than 70%.
Over half of the GPU's busy cycles stall on DRAM.

## Frame pacing

Swap intervals in units of the 16.7 ms frame clock (fb-a):

| Phase | 1 period | 2 periods | 3 periods | 4-5 periods |
| --- | ---: | ---: | ---: | ---: |
| home-b | 0 | 228 | 59 | 0 |
| control-a | 0 | 119 | 84 | 18 |
| control-b | 2 | 114 | 90 | 12 |

No frame completes inside one period. Small clock changes therefore only move frames
across the 33.3 ms boundary, which is why the sensitivity table shows steps rather than
proportional changes. `sweetfb_hz=30` in the boot-args does not apply here: with
`sweetfb_sync=1` every swap (994 of 994) took the immediate-present path in `AppleCLCD::swap`.

## What follows

- Reduce GPU bytes per frame. This is the existing task 24 (fewer batches, then GMEM for the
  big ones, [PERF-TASK23-25-GPU-TRAFFIC.md](PERF-TASK23-25-GPU-TRAFFIC.md)) and task 25
  (render nearer 1080x2160 instead of 1125x2436, ~20% of pixel work).
- Task 5 (Mesa CPU per draw) and CPU DVFS/clock work will not raise frame rate now: halving
  CPU frequency changed nothing. CPU work matters again only after GPU time per frame drops
  well below 33 ms, and the CPU-side gap (~10 ms/frame of GPU idle) comes next.
- Raising DDR above 1804 is the clock-only route. This run did not test it; it is outside the
  validated range.
- To go from ~27 to a steady 30 (Home), shave a few ms off the slow frames; 60 fps needs
  the whole serialized frame (CPU gap + GPU) under 16.7 ms, about a 3x cut in GPU time.

## Not established

- Per-batch/per-draw GPU cost on today's build (needs a temporary boot with
  `SWEETCA_GPUPROF=1/2` in sweetenv; the 2026-10-25 breakdown in
  [PERF-GPU-TIME-20261025.md](PERF-GPU-TIME-20261025.md) ran at the same GPU/DDR clocks).
- Displayed FPS and touch-to-photon (framebench limits unchanged).
- home-a again had no swap arrivals (known framebench issue); Home numbers use home-b.
- `ddr state` shows `bimc_gfx 28 MHz`. GCC debug mux 0x0ac is `gcc_bimc_gfx_clk`, which
  is a branch clock. The reading is probably a divided measurement (28 x 32 = 902 = BIMC),
  not a real 28 MHz GPU memory port. Unverified.

## Reproduce

```powershell
python tools/g2/sensround.py research/<new-dir> base:auto cpulow:gold=1401600,silver=1401600 gpu430:gpu=430 ddr1296:ddr=1296 --kernel xnu/out-jasmine-j0108/kernel.development.sweet --lib xnu/out-mesa-diag/libsweetca.dylib --lock <free lock path>
```

Raw data (ignored): `research/bottleneck-20261028/` (fb-a, sens/*, sens.log, *.clocks.json,
bw-counters.txt, precheck, shot0.*). Pre-check: trustd/accessoryupdater idle (ReportCrash
~265 ms/s was busy at the start, outside the render path). Battery 39% charging at start.
