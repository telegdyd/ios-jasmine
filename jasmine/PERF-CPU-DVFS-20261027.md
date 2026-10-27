# Dual-cluster CPU DVFS: electrical tests pass; UI acceptance open

The opt-in eight-core controller reaches both stock ceilings and scales down
with demand. The physical iOS screen froze during acceptance, before user
interaction, so this is not yet an accepted daily-use configuration. Four-core
defaults remain unchanged. Work is paused with the phone in charging shell.

Implementation: repository commit `2550347`, source commit `736adf1` in the
isolated `~/xnu-cpu-dvfs` worktree. Successful CI run `40444015228`, job
`121990838172`; kernel SHA256
`bca76245a10547f39f1268e34f6b3dc164169776da64788ca7e72199396deffd`.
The preceding run `40442814374` failed compilation and was never booted.

## Controller and commands

Runtime fuse-derived tables support the validated speed-bin1/revision2 path;
other paths refuse initialization. No chip fuse dump is committed.

| Cluster | Frequency MHz / voltage mV |
| --- | --- |
| Gold | 300/692, 1113.6/692, 1401.6/748, 1747.2/828, 1958.4/880, 2150.4/928, 2208/948 |
| Silver | 300/612, 633.6/612, 902.4/648, 1113.6/696, 1401.6/780, 1536/816, 1747.2/876, 1843.2/900 |

Transitions select verified safe300MHz before SAW16 supply/APM changes, poll
independent PMIC target/valid readings and both Gold supplies, then program and
verify PLL lock/mux. Existing MEM-ACC settings are retained and checked. Ordered
rollback restores the old point; unverified rollback latches a fault until reboot.
Legacy voltage helper and controller share a mutex. Do not mix raw register
writes with controller operations.

Use `sweetdvfs=1 sweetdvfsauto=0` for manual mode or `sweetdvfsauto=1` for
automatic mode; initialization is delayed30s. Image packaging accepts
`--cpu-dvfs` and `--cpu-dvfs-auto` and rejects mixed legacy voltage/RPM probes.

```text
dvfs stat
dvfs auto 0
dvfs set 0 2208000
dvfs set 1 1843200
dvfs restore
dvfs auto 1
```

Cluster0 is Gold,1 Silver. Manual changes require auto off. Restore disables
auto and returns to boot points: Gold1747.2MHz/868mV/MX,
Silver1382.4MHz/872mV/MX. Status includes PLL/RCG-derived frequency, requested
frequency, rail validity, load, change/failure counters and fault. It is not an
independent effective-frequency measurement; checker ~MHz is a timing proxy.

The governor samples busiest-core utilization per cluster every20ms. Load>=65%
jumps to stock maximum; five samples below35% permit downscaling, with below10%
selecting300MHz and other low loads stepping down. Thermal throttling is
deferred per user direction; status reports `thermal=off`. The old diagnostic
voltage helper's70C cutoff does not gate this controller.

## Validation and limitations

Actual ARM compilation, actual-header host tests including the command handler,
fault injection/rollback and source/linked-marker CI guards pass. Runtime OPPs
match the independent stock-DT/fuse model using ignored local chip data.

On the new eight-core kernel, all Gold7 and Silver8 OPPs passed upward/downward
sweeps, ten min/max ramp cycles and sustained maximum checks:60 stress checker
commands, each8 cores x20 runs, zero errors. An extra restored-state check passed.
There were70 set requests and33 Gold/35 Silver actual changes; failures0/fault0,
with boot clocks/rails/APMs restored successfully.

The settled automatic run passed10 load checks and captured38 status records.
Each cluster reached300MHz and its stock maximum, with zero failures/faults;
the floors need not occur simultaneously. An earlier10s idle observation failed
to see Silver's floor while background work remained busy; that run is not PASS.

The physical screen nevertheless froze before the user touched it. A previous
four-core baseline restored physical touch. A frozen-run3s profile had4817
samples and no drops: heavy VM/compression/pageout and UFS-write polling, with
the governor a small share. Wallpaper processes were present without user
interaction. These are diagnostic leads, not proof of the cause. No RAM/VM/UI
fix was implemented. Next: fresh eight-core baseline without transition stress,
physical UI/VM comparison and RAM/coherency testing across OPPs.

All boots were temporary. Device dumps and build artifacts remain ignored under
`research/cpu-dvfs/`; manual/auto image manifests and CI logs are retained there.
Final parking readback: Linux6.19.10-sdm660/r109,99%,33.5C, charger online/Full,
health Good, backlight0, slot_b. Own phone lock released and collectors stopped.
