# Installed Metal performance, 2026-11-01

Two fresh standard framebench runs on the settled installed j0126 boot, after the
Control Center derivative fix. **CPU texture uploads are the first target; GPU
memory stalls are a second, independent limit.** This investigation measured
opportunities; it did not install a renderer optimization or establish a speedup.

## Configuration and evidence

- Installed `/usr/local/bin/libbgair.dylib` read back SHA256
  `1a8aa7b67142bd858feccd5a7c8277b923ec73f60ba9b85ddbf7aad9a3206f46`;
  `libbgmtl.dylib`
  `d816ccec0c066d620b9815070c5d618c74afa5d98288ae0a3c9a2292d7324b3d`.
  These match the clean ccfix runtime. Kernel symbols:
  `xnu/out-jasmine-pride16/kernel.development.sweet`, SHA256
  `d429ac52e24339fec9a449a0af359bd4b6b0e309d597b20650d6d4c64681df92`.
- Environment read back before and after, byte-identical:
  `CA_DISABLE_FRAMEBUFFER_COMPRESSION=1` only. Async replay remains off.
- GPU 588 MHz, DDR 1804 MHz; CPU governor unchanged. First baseline started at
  17:22 local time. Baseline TSENS started around 50–54 C and ended at 54–57 C.
- Ignored evidence: `research/metal-perf-20261101/`, including `baseline1/`,
  `baseline2/`, matching dylibs, `baseline{1,2}-bbcpu.txt`,
  `baseline2-framecrit.txt`, `counters/`, and both netlogs.
- Baseline1 sampled A and B phases: 34,182 events, 65,536 samples, **13,707
  dropped CPU records**, zero dropped events. Its late control-b CPU window is
  incomplete and must not support CPU conclusions. Baseline2 used normal A-only
  sampling: 30,716 events, 42,797 samples, 11,467 stacks, **zero losses**.
  Use baseline2 for the main CPU estimates. Both captures completed.

## Repeatability

These are swap arrivals during commanded motion, not physically validated display
FPS. A/B here denotes workload phases, not a renderer comparison.

| Phase | Baseline1 updates/s | Baseline2 updates/s | Baseline2 median / p95 interval, ms |
| --- | ---: | ---: | ---: |
| Home A | 35.85 | 36.24 | 27.24 / 32.13 |
| Home B | 36.19 | 36.20 | 27.20 / 32.65 |
| Control Center A | 30.88 | 30.82 | 30.48 / 42.70 |
| Control Center B | 32.35 | 31.37 | 29.26 / 44.15 |
| Spotlight repeat | 27.46 | 25.47 | 30.90 / 38.28 |

No Home-A stall in these runs. Control Center had isolated 170–200 ms gaps;
Spotlight also had long gesture-boundary gaps. The short repeated samples do not
establish their cause. Earlier GL/Metal numbers used other runtime/workload state;
they are historical context, not a controlled regression comparison to ccfix.

## CPU: roughly half the render thread is the Metal replay

Symbolized stacks identify this hot path:

`BGMTLCommandBuffer bgReplayFrom:` → `BGMTLTexture rwaTextureSampled` →
`rwaTexture` → `rwa_texture_write` → `u_default_texture_subdata` →
`util_copy_box` → `memmove`.

Baseline2, primary render thread only, each phase sampled for four seconds:

| Work, inclusive unless marked | Home A, estimated ms | CC A, estimated ms | Share of thread CPU, Home / CC |
| --- | ---: | ---: | ---: |
| Thread total | 3404 | 3374 | 100% / 100% |
| `bgReplayFrom:` | 1680 | 1704 | 49.4% / 50.5% |
| CPU texture write | 812 | 562 | 23.9% / 16.7% |
| `util_copy_box` subtree | 736 | 516 | 21.6% / 15.3% |
| `fd5_emit_state` | 230 | 378 | 6.8% / 11.2% |
| `batch_draw_tracking` | 140 | 202 | 4.1% / 6.0% |
| `flush_submit_list` | 88 | 172 | 2.6% / 5.1% |
| `bg_log` | 102 | 68 | 3.0% / 2.0% |
| Command buffer deallocation | 68 | 72 | 2.0% / 2.1% |

Rows overlap: do not sum them. Baseline1 independently shows the same large copy
path (878 / 568 estimated ms in `rwa_texture_write` in Home A / CC A).

The 0.5 ms grid in framecrit estimates, for 138 Home and 106 CC sampled intervals:

| Per update | Home A, ms | CC A, ms |
| --- | ---: | ---: |
| Interval mean | 27.76 | 33.18 |
| Render thread on CPU | 24.94 | 28.54 |
| User CPU beneath our Metal libraries | 13.15 | 14.70 |
| CoreAnimation and other user CPU outside our libraries | 7.97 | 10.00 |
| GPU outstanding, upper bound | 21.23 | 20.86 |
| Render runnable without a core | 0.01 | 0.04 |

These are grid/sample estimates, not exact instruction timings. GPU outstanding
includes submission/queue/observation delay and overlaps CPU. On the sampled-frame
denominator the texture-write cost is roughly **5–6 ms per update**; this is an
opportunity bound, not a prediction that all of it can be removed.

The live log repeatedly rejects sampled IOSurfaces with pixel format 500. The
primary thread's `bg_log` stacks and kernel `fbcon_transmit_data` show a real
diagnostic cost even with tracing off. The meaning of this private format and the
correct fallback are **not established** here. Do not guess a format mapping.

## GPU: memory traffic matters even after CPU savings

Separate counter-only Home and CC workloads, no CPU samples. Temporarily set
`gpu pc off` so GX counter state survives the window, then restore `gpu pc on` in
`finally` and read back. HW clock gating and all clock selections remained unchanged.
The requested 12-second bandwidth windows were **clamped by the kernel to 10 s**;
use the actual ten-second result and corresponding event window.

| Whole-GPU measurement | Home | CC |
| --- | ---: | ---: |
| Busy Mcycles/s | 409 | 326 |
| Busy fraction at 588 MHz | 69.6% | 55.4% |
| RAM-starved Mcycles/s | 215 | 168 |
| Starved / busy counter ratio | 52.6% | 51.5% |
| VBIF million AXI beats/s | 161 | 133 |
| Swap arrivals in approximate matching 10 s | 341 | 281 |
| Whole-GPU busy ms / swap, approximate | 20.4 | 19.7 |

The phase marker precedes the counter command slightly; these are approximate
alignments. Counters include every GPU client (including wallpaper), not just
backboardd, and the bandwidth sampler itself occupies a CPU thread. This separate
workload was slower and hotter than the baselines (ending TSENS max 61.1 C).
Do not treat its swap rates as a performance A/B. Do not interpret RAM-starved
cycles as automatically removable time. The printed CPU BWMON `mon cnt` bandwidth
is implausible and is not used; retain the GPU counter measurements above.

## What to optimize next

1. **Identify the repeatedly uploaded textures and eliminate safe copies.** Start
   at `rwaTexture`'s `_linSrc` / `_ncBytes` branches. Capture dimensions, format,
   byte count, source identity and upload count with bounded aggregate diagnostics.
   The stack above passes through `rwaTexture`, rather than `copySurfaceLocked`.
   Investigate direct buffer-backed linear sampling or a valid producer dirty
   generation. Arbitrary caller memory can change between commits: simply skipping
   refreshes is incorrect. The identity of the largest textures is still unknown.
2. **Deduplicate repeated format-rejection diagnostics**, retaining the first
   diagnostic and a suppressed-count summary. Separately determine whether the
   unsupported format forces a more expensive texture path. This is smaller than
   uploads but directly measured and comparatively contained.
3. **Reduce batch state/resource overhead.** CC spends another 11% of render CPU
   under state emission and 6% under resource tracking. Existing per-draw state
   caching is already active. Measure render-target/batch switches and duplicated
   resource references before changing Gallium dependencies or synchronization.
4. **Measure GPU traffic per pass/client.** Whole-GPU counters show enough GPU work
   to exceed a 16.7 ms budget too. Look for full-screen copies, blur intermediates,
   and sysmem traffic; evaluate eligible GMEM passes with pixel correctness gates.
   This run does not establish which pass or wallpaper accounts for that traffic.
5. **Revisit asynchronous replay only after ticket safety.** The earlier r26 gain
   remains a lead, not a new validated result. Do not restore it blindly: the old
   stale-ticket / boot-time fallback failure is still documented in
   `METAL-SPEED-IDEAS.md`. Current render runnable time is tiny; scheduler contention
   is not the leading CPU target in these samples.

## Tool correction and final state

Framebench previously attributed user stacks under libbgair/libbgmtl to their
QuartzCore caller. It now records `render-Metal-CPU` and ranks that work explicitly.
Framecrit accepts multiple renderer libraries so both halves of Metal are resolved.
Regression tests cover both Metal libraries above a QuartzCore caller and a pure
QuartzCore stack, plus ranking. Fixed stale test argument fixtures for `sample_b`.
All **34 framebench tests pass**. Regenerated both offline reports; framecrit ran
successfully on the loss-free capture with both installed libraries.

No build or CI run was needed; the local macOS VM connection succeeds. No reboot,
flash, runtime replacement or partition change. Both baseline captures show zero
latch timeout fallbacks and zero presentation-ticket wait errors (1667 and 1619
waits); no DROP/CANCEL/ABORT events. Low free RAM (~20–23 MiB) had zero page-waiter
snapshots; the second backboardd footprint was stable (-0.3 MiB). No leak conclusion
from these short runs. Final bench/profiler idle, own lock released, GPU collapse
mode 1 / HWCG on restored and read back, compositor env unchanged. No new physical
panel correctness check was requested or inferred from the counters.
