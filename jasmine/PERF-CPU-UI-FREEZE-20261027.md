# CPU scaling and UI freeze investigation

The earlier screen freeze was reproduced without a synthetic stress sweep or
user interaction. After fixing released-surface pixel retention, eight-core
stock-OPP memory checks and automatic scaling pass, and the user confirms the
physical UI is responsive while swiping. A separate Wallpaper-gallery trial is
currently being observed; its physical result is pending.

## Fixed-kernel validation

CI40520184930/ba35bbc passes actual ARM compilation, the new memory and surface
lifetime tests, and existing integration/source/symbol guards. Kernel SHA256:
`156b9ebf43cf605dd752993bfb7f3c10e52e01b2a4ab902aab663966906a540a`.

Device testing used kernel50ea09c/SHA256
`80a07f5bb50013de237ff9c2f9a9b0a422e1cd4b0d65e5a70a814801ca13fea7`.
Its ARM build succeeded, but an overly narrow new CI regex rejected its `S`
code symbol. Remaining guards and the lifetime regression passed locally
against its exact packaged source. The corrected CI artifact's `__TEXT_EXEC`,
`__DATA_CONST` and `__DATA` segments are byte-identical to this tested artifact;
whole-file hashes differ. No failed compile was booted.

The new checker passed on four CPUs, then33 checks on eight CPUs: boot state,
all Gold7/Silver8 stock OPPs up/down, joint maxima and restored boot. Each check
used1MiB per pinned CPU and four patterns, with readers crossing clusters.
Every CPU reported its correct binding and zero memory errors. Ordered boot
restore passed; transition failures/faults remained zero. This is bounded
CPU/cache/RAM evidence, not an exhaustive hardware memory qualification.

The fixed-clock control and subsequent automatic run each captured24 snapshots
over about4.5minutes on the same boot. Under auto, wired memory stayed272.7–
279.9MiB and requested surface backing61.9–66.1MiB; no page waiters or GPU
allocation failures occurred. Both300MHz floors and both stock ceilings were
observed. The user explicitly confirmed physical responsiveness while swiping.
Old/new baseline wired totals alone are not a matched saving measurement:
the earlier run also allocated the larger legacy profiler buffer.

The user then requested a Wallpaper trial. Dense2s monitoring observed backing
rise to184.2MiB and fall to about72MiB rather than accumulating past1.5GiB.
Physical gallery acceptance is still pending. A green-CI temporary auto-on
eight-core image is prepared under ignored `dvfs-ready-images/`; no flash or
persistent boot/default change has been performed.

## Controlled reproduction

Temporary kernel2550347/CI40444015228, eight CPUs, manual mode, normal boot
clocks: the user confirmed physical touch responsive. Six observations over
about four minutes showed wired memory settling around470MiB, flattening
compression/pageout activity and low kernel CPU use. No CPU transitions ran.

Automatic scaling was then enabled on that same boot. The user reported a
frozen screen again and explicitly said they did nothing during the interval.
By the first subsequent observation, wired memory had risen to about1.55GiB.
Later kernel memory snapshots show:

| Counter | Before auto | Under pressure |
| --- | ---: | ---: |
| Wired bytes | 506,937,344 | 1,756,545,024 |
| Surface objects | 169 | 627 |
| Surface requested backing bytes | 276,397,704 | 1,709,990,656 |
| GPU BO mapped bytes | 114,393,088 | 261,390,336 |
| GPU pool actual bytes | 98,959,360 | 140,902,400 |

These counters overlap and must not be added. Process footprints were small
and heavily compressed. Profiles showed VM compression/pageout and eMMC write
busy-polling; the GPU had completed all submitted jobs at the observed snapshots.
No DVFS failure or fault was reported.

Ordered restore succeeded: automatic mode off, Gold1747.2MHz/868mV,
Silver1382.4MHz/872mV, both APMs at MX. Gold37/Silver680 changes had occurred.
Userland memory/process queries subsequently timed out despite kernel command
responses. A clean reboot reached actual fastboot at14:54:12 local; the accepted
four-core baseline restored physical touch, explicitly confirmed by the user.
Its six idle observations stayed stable around452MiB wired after startup.

This establishes a stronger temporal relationship with auto enable, not a
proven electrical cause. It does not implicate user wallpaper interaction.

The persisted AegirPoster report captured at14:46:10 shows SIGABRT in an
Objective-C exception path through NSArray insertion and the renderer's
uniform-buffer creation. The first16 exception frames exactly match a report
from2026-10-24, before this DVFS implementation. Auto was enabled at14:45:35.
Thus this renderer abort predates the new governor; this does not establish
whether it triggered the surface growth or why auto enable coincided with it.
Raw crash reports remain ignored and contain device identifiers.

## Concrete retention defect and fix

`IOSurfaceRootUserClient::trapRelease` cached up to256 released views per client
in `fZombies` to preserve their16KiB state mappings. Each cached
`SweetSurfaceRef` also retained the entire `SweetSurface`, including its pixel
backing, until eviction. Existing allocation counters count those objects until
their actual destruction, including objects no longer in the live ID table.

j0106 drops the view's surface retain after unmapping its data and dropping its
table user, preserving the independent state mapping. `IOMemoryMap` retains its
descriptor in `setMemoryDescriptor`; surviving clients, GPU imports and Mach
ports retain their own surface references. The state-page cache bound remains256.
This fixes demonstrated unnecessary retention; phone freeze recovery is pending.

The regression test compiles the actual release method. Old source fails its
immediate-pixel-release assertion; fixed source passes state-page retention,
cache eviction, repeated release counts and independent live-client cases.

## Additional diagnostics and next validation

j0105 adds `checkmem`:1MiB per CPU, all-zero/all-one/address-derived/complement
patterns, with pinned writers and readers offset by half the CPU count to cross
clusters on eight CPUs. All allocations are released after started workers
finish. Concurrent host tests pass on4/8 CPUs, including injected corruption,
incorrect binding, allocation/thread-start failure and cleanup.

`surfaces` groups live ID-table backing by creator PID/name. Creators are not
necessarily current holders; removed-table objects are not counted by this
diagnostic. Use framebench lifetime allocation totals alongside it.

Published milestones: diagnosticsf52ccce/sourcef74baa6; retention fix50ea09c/
sourced5f8701; CI guard correctionba35bbc. Diagnostic-only CI40516338522 was
cancelled. CI40517147150 compiled successfully but failed the symbol regex;
CI40520184930 is green. Next finish Wallpaper acceptance and validate a clean
auto-on boot. No governor, voltage or default-core policy changed here.

Ignored artifacts and scripts remain under `research/cpu-dvfs/`: `ui-idle8*`,
`ui-auto8*`, `ui-fixed4*`, `ui-recovery4c*` and the exact CI logs/manifests.
