# Wi-Fi integration: device acceptance, 2026-10-26

The agreed device gate passed on the repaired kernel **d42bfb4**, built by
[CI40398100808](https://github.com/telegdyd/ios-jasmine/actions/runs/40398100808).
AP-loss, wrong-password and second-known-network ordering were not exercised;
the user requested skipping spare-AP cases. No WPA3/roaming claim is made.

## Failure found and repaired

The initial combined kernel8405096 booted, auto-joined, loaded a web page and
passed GL7/7, but failed Settings Wi-Fi off/on recovery. Power-off posted
framework link-down/power-off without leaving the AP. The station power
callback was an unconditional success stub; firmware remained associated.

Patch `j0100b-jasmine-wifi-power-leave.patch` makes power-off call the existing
`topaz_wlan_leave()` sequence while keeping firmware loaded. Power-on preserves
the existing rejoin path. The actual callback was extracted for a host GCC
check of on/off dispatch and error propagation; the full kernel CI then passed.
All48 integration patches and source/linked-symbol/skip guards passed.

On the repaired device, power-off sent deauth, drained TX, deleted the peer,
stopped the vdev and reached idle (reported26ms). Power-on performed a fresh
successful join. USB command/file services remained available in both states.
A new HTTPS Google result page loaded after recovery; no production library
replacement was involved.

## Observed results

| Check | Result and evidence |
|---|---|
| Default startup, no modem/wifi/delay arguments | PASS on two repaired temporary boots; known home network joined without network selection |
| IPv4/DNS/browser internet | PASS: DHCP lease/router present; HTTP page on initial candidate, fresh HTTPS browser results after repaired off/on |
| USB coexistence | PASS: kernel command, file readback, sweetd `/bin/df`, and idle `bench stat` while Wi-Fi joined; command/file access also worked while Wi-Fi off |
| GPU/IOSurface control | PASS: production-matched seven-step GL control including nine sampler checks, IOSurface readback and texture import; repaired kernel83.9ms,exit0 |
| Normal UI | Home, Settings, browser, Control Center and Notification Center visually inspected; no persistent corruption observed |
| Settings off/on | PASS after repair: actual firmware leave followed by fresh association and working internet |
| Joined reboot1 | PASS: WLAN off250ms, stop-ack48ms, system unmount at+1130ms; actual fastboot return22:07:19 Budapest |
| Joined reboot2 | PASS: WLAN off245ms, stop-ack49ms, system unmount at+956ms; actual fastboot return22:13:16 |
| Reboot memory gate | Both repaired joined reboots: zero GPU imports/pins at RootUnmount, no shutdown watchdog dump/stall |
| Explicit off fallback | PASS: no modem/radio/wifid startup; USB command/file/sweetd and framebench available; lock-screen UI rendered; clean reboot/fastboot return22:18:39 |
| Runtime faults | No new runtime GPU/SMMU fault, modem FATAL or panic observed. Known startup self-test CB0 FSR0x400 remains, matching baseline |
| Cleanup | Test-name GL binary and screenshot files removed; production library before/after identical; own collectors ended and shared lock released |

Boot times, Budapest: repaired default1 **21:58:57**, default2 **22:10:53**,
off fallback **22:15:34**. The earlier failing-candidate reboot also completed
cleanly, but is not counted as one of the two repaired joined reboots.
Two successful reboots are a practical smoke test, not statistical proof that
an intermittent shutdown issue can never recur. GL timings are correctness-test
durations, not performance results.

The log analyzer now checks zero actual GPU wiring/pins, rather than requiring
zero live unwired wrappers. The earlier failing-candidate reboot had109 live
unwired wrappers, zero imports/pins and a clean reset. Nonzero import or pin
negative controls still reject. No shutdown expectation was bypassed.

## Provenance and local artifacts

Accepted kernel source: `d42bfb40f41e4859f9955db15c50406b5b1a181d`.
Kernel SHA256:
`4f9c55643af4913da5fda53556a3f835a2a705d1d07a6f4e4516509b1b184589`.

| Image | SHA256 |
|---|---|
| default | `9a16325f7223e8056a4e1d1aa8a0a76f42ca66fe9ca25b6677d7e03bebed8d44` |
| diagnostic (not needed on device) | `1c074e860c16903d8140235f9331d676a9556828722529f8d1ef71562c5f6871` |
| off | `a6f3db0ac9eb47bd342804f1e5b8ddef09247028e82d318528801afbdf4a9797` |

The original checkout's ignored `research/wifi-integration/ci-40398100808/`
contains CI metadata/log, kernel/SHA256SUMS and image manifest. Initial
ci-40358833912 images are superseded for acceptance by this repaired kit.

Raw evidence/scripts/screenshots are ignored under
`C:/Users/teleg/Documents/Code/Xiaomi A2/ios-jasmine/research/wifi-integration/device/`.
`evidence-hashes.json` records complete hashes. Principal logs:

| Log | SHA256 |
|---|---|
| fixed-boot1.txt | `7d737b3577d0942a34c674087be1be157aec4f4662001224ef10b11ca70545f0` |
| fixed-boot2.txt | `caa256d06912084c7fa8f3035bd1e271dbaa70a51dceed2ce7d18ba86b9849a4` |
| fixed-off.txt | `a9b34c647e6222d66b99c9cf4c2050ccb45aefe4939993a795d95e3906f9cbf7` |

The existing production-matched GL control came from Mesa CI40170072509,
sourcea9e95ec; test SHA256
`5bcc71b6613738fd379968a87964e15f8208af8e6fb4a7d4546239aaaaf5e6bc`.
Production library before/after SHA256:
`14e32aea4121e9c8a357da8f5e6322fe572a85f1c22e496990af0e687cb19261`.
Task24's experimental barrier test/library was not installed.

## Final phone state

Restored to r109 charging shell, backlight0, active slot_b. Final sample:
capacity78%, battery current+802245uA, voltage4163075uV, temperature34C;
chargeronline1/statusCharging/healthGood. Own lock released22:22:13 Budapest.
These are point measurements, not a charge-rate estimate.

Only temporary `fastboot boot` images were used. No partition flashing/GPT
change or production library replacement occurred. Source was merged directly
into jasmine at `168cdea`; installing an accepted image into slot b remains a
separate step requiring explicit confirmation.
