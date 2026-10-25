# Framebench

`tools/g2/framebench.py` runs once against a running j0099-instrumented kernel.
It does not boot, reboot, flash, install anything, change clocks, disable plugins,
or park the phone. The operator must first reserve the phone. Current plugin and
wallpaper behavior is a new baseline; old task-5 results are not a fallback ranking.

## Standard run

From the repository root in Windows, with the phone unlocked and settled:

```powershell
python tools/g2/framebench.py run --out research/framebench/current --ui-ready --kernel xnu/out-jasmine-framebench99/kernel.development.sweet --lib xnu/out-mesa-t5active/mesa-ios/libsweetca.dylib
```

Use the actual installed library's matching symbol file; the example is the last
documented production library, not independent verification of what is installed.
The kernel version from `bench caps`, local symbol file hashes, before/after clock
state, temperatures and all command results are recorded. Windows delegates CPU
symbolication to the existing WSL `prof.py`/dyld-cache tools with a 40 s deadline.
Without matching symbols it still reports frame observations, process CPU counts
and memory, and explicitly lowers attribution confidence.

The standard schedule is roughly a minute of idle, first-observed/repeated
Spotlight, warmup, home swipes and Control Center pulls/dismissals. There are two
segments per main workload; only A segments sample CPU for four seconds. Motion
markers include a fixed animation-tail allowance, exclude intentional holds, and
are independent of CPU load and frame duration. Memory checkpoints run between
motion windows so transfer delays do not become synthetic animation stalls.

Maximum device activity is 90 s. Export has a separate 45 s default deadline
(`--export-timeout`, maximum 120 s); symbolication is separately bounded. Actual
runtime and bytes are reported. There is no automatic second workload or boot
if collection, transfer or analysis is incomplete. Output directories must be new.

## Settings-page freeze capture

Start before navigating to the affected page:

```powershell
python tools/g2/framebench.py run --out research/framebench/wallpaper --manual --seconds 45 --kernel xnu/out-jasmine-framebench99/kernel.development.sweet --lib xnu/out-mesa-t5active/mesa-ios/libsweetca.dylib
```

Manual mode injects **no touches or buttons**. It saves memory snapshots about
once per second and arms one-second CPU/all-thread census windows periodically,
including blocked kernel stacks. Targets are refreshed as Preferences/PosterBoard
start. The entire manual window is labelled as manual activity, including any
intentional pauses; do not compare its FPS proxies with steady home motion.

Both modes stop issuing input on connection loss/deadline or when free memory is
below 32 MiB while pages are wanted. A single bounded stop/export cleanup follows;
there is no recovery reboot or workload retry. Already saved host snapshots survive
a complete device freeze. The tool cannot retrieve uncopied kernel buffers from a
device whose command/network service has stopped. No Wallpaper UI is opened by
the standard schedule.

## Output and interpretation

- `report.md`: workload metrics, memory high-water marks, CPU categories and up to
  three evidence-ranked follow-ups. Pressure/allocation failure takes precedence
  over CPU optimization. Missing evidence produces an attribution task, not an
  automatic recommendation to continue task 5.
- `summary.json`: structured report, worst no-update intervals with stack IDs,
  GPU job/surface links, validity flags and exact manifest.
- `progress.jsonl`: incremental memory and command checkpoints, including process
  PID plus task unique ID to distinguish restarts/PID reuse.
- `events.bin`, `samples.bin`, `stacks.bin`, `profile.meta`: bounded binary capture
  and symbol mappings. GPU jobs are detailed only in sampled windows. CPU records
  reference interned stacks; no 48 MiB legacy sample buffer is allocated by bench.
- `manifest.json`: configuration, live kernel version, symbol file hashes, counts,
  dropped records, timings and failures. Library identity is operator supplied.

The kernel capture/metadata allocation is bounded to approximately 9.4 MiB and
retained for reuse. `bench caps` gives the exact byte budget and reports whether
an earlier legacy profiler buffer already exists. Event/sample/dictionary overflow
or contention is reported. GPU BO mapped bytes, surface requested bytes and actual
GPU-pool allocation are separate, overlapping measures. Do not add them to process
resident/footprint or wired totals. Allocation-failure accounting currently covers
SweetGPU buffer-new failures, not every kernel allocator. Short growth is not a
leak diagnosis. Process enumeration is capped at 256 and reports captured/total.

**Displayed FPS remains unavailable until on-phone validation.** j0058 retires a
swap either after observing CTL_FLUSH clear or after a 50 ms timeout; framebench
records these separately. It also records the physical interface frame/line
counters, but software timer ticks are not hardware refresh events. The first
device session must validate the observation signal/resolution. Until then the
report labels swap-arrival and CTL-clear rates as proxies and never displays them
as confirmed displayed FPS. Pure GPU execution time, physical touch-to-photon,
long-term leaks, cold boot and thermal behavior are outside this short capture.

Reanalyze saved captures without contacting the phone:

```powershell
python tools/g2/framebench.py report research/framebench/current --kernel xnu/out-jasmine-framebench99/kernel.development.sweet --lib xnu/out-mesa-t5active/mesa-ios/libsweetca.dylib
python -m unittest discover -s tools/g2 -p test_framebench.py -v
```

All capture output belongs under ignored `research/`, never in git. The shared
atomic phone lock is the existing project's default; `PHONE_LOCK` or `--lock`
can specify its current location. Occupancy/missing lock directory fails quickly.

## Kernel maintenance

`xnu/patches/j0099-jasmine-framebench.patch` adds the hooks and compact sink to
the existing profiler and a length-aware binary response to the USB command
service. It preserves synchronization, surface lifetime and clock settings.
The canonical include is `tools/g2/framebench_kernel.inc`; the checked transformer
`tools/g2/framebench-kernel.py ISOLATED_XNU_TREE` installs it and hooks onto the
j0070 or compatible later source. Never run it on an active shared kernel tree.
Export j0099 with `git format-patch` and verify compatibility before CI. No new
launchd jobs, userland installation or Mesa rebuild are required.
