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

Implement the serialized per-cluster backend with these confirmed sixteen-bit
requests and full-width status checks. Keep software-visible requested/actual
states distinct. Validate target-OPP bounds, rollback, PLL lock/mux transitions,
APM crossover and MEM-ACC sequencing before enabling higher clocks. Then add
load policy and independent thermal caps together. The former APM explanation
for an uncommitted small voltage request is no longer needed; APM ordering at
higher operating points is still untested and must not be skipped.

Ignored evidence: `research/cpu-dvfs/`, including `probe4.txt`, `saw16.txt`,
`neutral-s{1,2,3}-*`, `s1-step-*`, `saw16-s1-*`, `saw16-gold-*`, CI logs,
manifests and pinned firmware references. Header SHA256
`8c778b3a7fcb3fdf4b49671bbea8fe9a367df9112d50938296e19d3ddf4ceb15`;
HALavs.c SHA256 `0f7d0b04d5c50a8ce63ded329aa79a7852faf48ab89dc1e3c1b072f1dd740b5a`.
Register facts were used; firmware source stays ignored.
