# CPU voltage path: SAW4 wide requests work on both clusters

2026-10-27. The old software-voltage blocker has a demonstrated fix: **SAW4
software requests must select the 16-bit payload width**. Small raise/restore
tests changed PMIC target and valid-voltage registers on both CPU supplies,
without changing PLLs, APM or MEM-ACC. This does not yet validate higher clocks,
full voltage ranges, a governor, thermal caps or an installed default.

## Evidence and root cause

The earlier driver used an eight-bit voltage-data mask. Its requests could
change the target's lower byte without committing the full PMIC voltage.
The SDM660 [SAW4 register header](https://github.com/David112x/android-firmware-qti-sdm660/blob/b5e5bb9ed6c92442fd502b3e726d7c8024dc0763/boot_images/QcomPkg/Sdm660Pkg/Library/HALclkLib/HALavsHWIOSAW4.h)
defines these fields:

| Register/field | Offset or mask |
| --- | --- |
| SAW4 VCTL | base +0x900 |
| VCTL request SIZE | bit20,0x100000 |
| VCTL address index | bits18:16,0x70000 |
| VCTL PMIC data | bits15:0,0xffff |
| SPM_PMIC_DATA_3 | base +0x4c; same SIZE/address/data fields |
| PMIC_STS data / state |0xffff /0x30000 |
| SAW ID PMIC_DATA_WIDTH capability | bit8 |

Both SAW IDs read0x2020016f, including the wide-data capability bit. Wide
software requests at address-index0 use `0x100000 | millivolts`, with a paired
PMIC_DATA_3 update preserving unrelated bits. A bounded poll checks idle and
the full sixteen-bit returned data, then PMIC target/valid/enable/mode are
read independently after100ms. No AVS loop, port remapping or APM switch was
needed for these small voltage updates. SPM_PMIC_DATA_n contains command
delay/index/data fields; do not reinterpret its low byte as a port-address map.

For reference, a later [Linux SPM implementation](https://android.googlesource.com/kernel/msm/+/android-msm-bluecross-4.9-pie-qpr1/drivers/soc/qcom/msm-spm.c)
also documents a separate upper-byte-port approach for other configurations.
That is not the approach tested here, and this phone's DT assigns port1 to
phase control. The direct SDM660 SIZE field avoids guessing that mapping.

## Hardware results

Temporary diagnostic kernel40b6e3d, CI40414145643 PASS, SHA256
`9cbfef7aee241bfbd9ca488e03766339cba408cfea169580dce2360de2b570c8`.
Source/symbol gates, four checker-init scenarios, twelve neutral-RPM scenarios
and integration guards passed; only four expected upstream patch skips.
Four Gold CPUs online, Silver parked. Gold1747.2MHz, Silver PLL1382.4MHz,
GPU588MHz, DDR1804MHz throughout. CPU frequencies were never raised.

| Test | Observed target and valid voltage | Result |
| --- | --- | --- |
| Neutral RPM S1/S2/S3 |872/868/868mV unchanged; all ACK | Request handling works; scaling not proven |
| RPM S1 request872→876→872 | Stayed872 throughout, despite ACK | No demonstrated voltage control on this path |
| SAW16 S1 neutral872 |872mV | PASS |
| SAW16 S1 raise/restore,02:54:39 |872→876→872mV | PASS; Gold supplies unchanged |
| SAW16 Gold neutral868 | Both S2/S3 at868mV | PASS |
| SAW16 Gold raise/restore,02:58:22 | Both S2/S3:868→872→868mV | PASS; S1 unchanged |

Gold's four pinned workers each passed20 deterministic runs while its supplies
were raised, and again after restoration. PLL/RCG, APM and MEM-ACC stayed at
baseline; modes/enables/limits stayed unchanged. Transaction replies took about
0.42–0.48ms including command/readback output; this is not an isolated voltage
settling-time measurement. PMIC valid status is digital evidence, not an
independent physical rail measurement. Silver was not executing during its step.

The failed RPM step was restored to the872mV vote before reboot. Following the
SAW tests, supplies were restored to S1872/S2-S3868mV. Production library readback
matches its pre-test SHA256
`14e32aea4121e9c8a357da8f5e6322fe572a85f1c22e496990af0e687cb19261`.
Final clean reboot returned to fastboot
at03:04:04; the phone was parked in r109,86%,34C,charging with backlight0 and
slot_b. Own lock released; exact charging and cleanup records are in root NOTES.md.

## Next gate

### Serialized diagnostic backend (j0103)

Source commit00866db adds a kernel helper behind `sweetcpuvolt=1`. `cpuvolt 0`
reports Gold status; `cpuvolt 1` reports Silver. Supplying a third argument
requests one of the demonstrated levels: Gold868/872mV or Silver872/876mV.
Image packaging requires `--cpu-voltage-probe`, strips an inherited opt-in by
default, and rejects a kernel without the helper marker before writing images.

One mutex covers both clusters' preflight, request, delayed readback and rollback.
Preflight requires the exact boot PLL/RCG, disabled OSM, observed APM/array state,
wide-data capability and matching PMIC type/mode/enable. Gold checks both S2/S3.
A request requires full sixteen-bit SAW status within2ms and matching PMIC
target/valid after100ms. A failed transaction attempts the prior verified level;
unverified rollback latches a fault until reboot. Status distinguishes the last
request from live-revalidated voltage. The100ms observation is deliberately
diagnostic, not a production settling-time measurement.

Raises additionally require all14 TSENS readings valid and below70C, matching
the prior test gate; restoration is still possible with failed/hot sensors.
This does not establish production thermal policy or sensor freshness. The
[requested thermal test switch](PERF-TASK2-DVFS.md) belongs to the governor's
normal caps; emergency protection stays independent.

Actual-header host tests pass the gate, paired-rail, ordering, timeout, PMIC
mismatch, rollback and sticky-fault cases. Removing SIZE bit20 is caught by the
test. An old kernel is rejected by image opt-in. ARM CI40437789398/bcdc037 PASS,
kernel SHA256 `1ba0349f842523a80094e06667db90edc0d0e64f98e9e3df535e42111b465f1b`.
All source/symbol/behavior/integration gates pass; four expected upstream skips.
Temporary default4 boot refused both clusters' voltage requests with enable0
and unchanged rails. Opted-in4 and8 boots each passed three raise/restore cycles
per cluster and all pinned checker runs (six raised checks plus initial/final,
20runs/core/check). Eight-core startup100runs/core also passed. Silver executed
during the eight-core ramps. Bounds refusals, paired Gold readback, requested/
verified reporting and restoration to S1872/S2-S3868mV passed. Clock/array
readings stayed unchanged. Raw register commands bypass the helper's mutex
and checks; do not run them alongside helper transactions. No PLL/APM/MEM-ACC
transition has been added by this patch.

### Array transition audit

Rechecked the historical OSM source against LineageOS lineage-19.1 pinned at
`2e69f2ae550dcfbde1ffb6daa11492762b122191`; file SHA256 still matches the
recorded914e8d9f... reference. `qcom,osm-no-tz` is absent in this phone's DT, so
the source skips reading the omitted MEM-ACC address/value properties and
expects TrustZone to initialize them. Their absence is not a DT error. The
newer lineage-20 SDM660-specific driver at
`49688d8750f2fca28271f936cfcfec5d97c0d7a4` retains that distinction. Do not infer
CPU array register addresses from the generic sequencer's table slots or from
the GPU MEM-ACC regulator. The previously observed0x179d1368..370 zeros remain
an observation, not established CPU array programming instructions.

The stock OSM constants specify APM control0 for MX and bit1 for APC, status
mask0x1f with low mode0/3, with this DT's Silver control/status0x179d0004/0xc
and Gold0x179d0010/0x18. The generic CPR regulator describes reaching the872mV
crossover before changing supplies. Actual acknowledgement, protected-write
access and array ordering on this boot path remain unvalidated. No APM write
was attempted during the source audit.

### Live APM and upper-voltage experiments, 03:37 onward

On the opted-in eight-core boot, Gold was raised868→872mV before selecting APC.
Its control0x179d0010 accepted bit1; status0x179d0018 read0x1f000003, matching
the documented low-five-bit mode3. All8x20 checker runs passed while selected.
Control/status then returned0, followed by restored Gold868mV. Silver at its
existing872mV also accepted APC: control0x179d0004=2, status0x179d000c=0xff000303
(low-five-bit mode3); all8x20 passed; control/status restored0. No clock or
MEM-ACC write. These prove the crossover supply switch at existing clocks,
not high-frequency array timing. The first Gold host parser incorrectly
expected an unmasked status string, skipped its checker, and restored correctly;
the corrected masked-status repetition above includes the required checker.

A separate Gold range test, with APC selected at872mV, verified both S2/S3
target/valid at each4mV step through948mV. Sampled all-core checks passed at880,
896,912,928 and944mV. At948mV the hottest of14 TSENS readings was70.2C
(raw8; Gold raw4..7 maximum69.6C), tripping the conservative global70C
diagnostic cutoff before the top-level checker. Restoration872→MX→868 passed;
all eight pinned workers then passed. **The complete range test is rejected by
its thermal gate, despite successful top-voltage readback.** No frequency was
increased. This is not a matched power comparison or a production thermal
threshold. Raw evidence: range-gold-* and apm-{gold,gold2,silver}-* in ignored
research/cpu-dvfs/; no dump is committed.

Silver subsequently verified target/valid872→900mV in4mV steps with APC selected,
all8x20 checks at880/896/900mV and after restoration, peak TSENS61.8C, and restored
MX/872mV with unchanged clocks/array state. **The preceding stricter cooldown
gate failed:** it required three readings below58C within180s and observed
57.6–62.8C but no qualifying sequence. A PowerShell command list continued to
the range script despite that nonzero exit. The range script itself enforced
valid sensors below70C, PMIC verification and ordered restoration throughout.
Treat this as warm electrical evidence, not the planned cooled-run acceptance.
The corrected orchestration uses Python `subprocess.run(..., check=True)` for
each dependent stage. Raw and reviewed results are both retained; do not rewrite
the original PASS output as evidence that the cooldown gate passed.

The default boot's first checker measured26–27ms/Gold run at unchanged PLL/RCG;
settled opted-in4/8 tests measured~14.3ms Gold and~26.1ms Silver, matching earlier
captures. Startup contention is a possible explanation, not established by that
single sample. PrintedMHz remains a calibrated timing proxy. No frequency or
performance improvement is claimed by these voltage/APM tests.

Final eight-core shutdown returned to actual fastboot at03:45:52.834 local;
RootUnmount+3188ms reported0 wrapped surfaces/0 GPU imports/0 pins, followed by
system unmount+3190ms. Temporary r109 parking boot succeeded. Fresh charging
readback:92%,34C,+757812uA,4287098uV,online1/Charging/Good,backlight0,slot_b.
Own shared phone lock released after verification; no collector remained.
No partition flash, production-library edit or higher-frequency default.

Extend the serialized backend beyond its demonstrated two-level window only
after the relevant gates pass. Keep software-visible requested/actual states
distinct. Validate target-OPP bounds, rollback, PLL lock/mux transitions and
MEM-ACC sequencing before enabling higher clocks. Integrate the demonstrated
APM crossover with ordered rollback and bounded acknowledgement. Then add
load policy and independent thermal caps together. The former APM explanation
for an uncommitted small voltage request is no longer needed; APM ordering at
higher operating points is still untested and must not be skipped.

Ignored evidence: `research/cpu-dvfs/`, including `probe4.txt`, `saw16.txt`,
`neutral-s{1,2,3}-*`, `s1-step-*`, `saw16-s1-*`, `saw16-gold-*`, CI logs,
manifests and pinned firmware references. Header SHA256
`8c778b3a7fcb3fdf4b49671bbea8fe9a367df9112d50938296e19d3ddf4ceb15`;
HALavs.c SHA256 `0f7d0b04d5c50a8ce63ded329aa79a7852faf48ab89dc1e3c1b072f1dd740b5a`.
Register facts were used; firmware source stays ignored.
