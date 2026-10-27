# CPU scaling and UI freeze investigation

The screen freeze is reproducible without a synthetic stress sweep or user
interaction. A concrete IOSurface lifetime defect has also been fixed in source;
its effect on the phone remains to be validated.

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
sourced5f8701. Combined CI40517147150 is pending. Diagnostic-only CI40516338522
was cancelled in favor of that combined build; no j0105/j0106 phone boot yet.
Next: actual ARM build/guards, temporary4/8 boots, memory-integrity tests across
stock OPPs, then ordinary auto scaling with allocation monitoring and physical
UI confirmation. No governor, voltage or default-core policy changed here.

Ignored artifacts and scripts remain under `research/cpu-dvfs/`: `ui-idle8*`,
`ui-auto8*`, `ui-fixed4*`, `ui-recovery4c*` and the exact CI logs/manifests.
