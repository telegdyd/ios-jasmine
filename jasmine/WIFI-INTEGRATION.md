# Wi-Fi integration and device acceptance

Branch: `codex/wifi-integration`, based on jasmine `d34f5ca` plus wifi `daf1e6d`.
This document supersedes WIFI-HANDOFF task 8's preparation instructions.
It does not mark device acceptance complete or authorize partition flashing.

## Ready for the device session (2026-10-26)

**Combined kernel CI40358833912 passed. All three images are prepared and
verified. No phone access or device test has occurred.**

Use the original checkout's
`research/wifi-integration/ci-40358833912/images/manifest.json` for exact paths,
command lines and hashes. Images are `wifi-default.img`, `wifi-diagnostic.img`
and `wifi-off.img`, each17,403,904 bytes. Kernel SHA256:
`2c281ee61aec20187df365d1b07d6f2b121109ad5bc4e06458e93dabd38051be`.
The manifest and NOTES.md record all image hashes. CI checksum, plain arm64,
integration symbols, baseline shim/ADT preservation, payload roundtrips,
independent Android header digests and variant arguments pass.

Only device acceptance remains: default auto-join/internet/USB + GL control,
disconnect/failure recovery, two joined reboots, and the off fallback. Use a
WPA2 test AP/hotspot for recovery cases; WPA3 support is not claimed.
No new configuration write should be needed on this already configured phone.

## Prepared offline

- Both j0099 patches coexist. A real SweetGPU cleanup hunk conflict was fixed
  by reducing trailing context in the Wi-Fi patch; framebench accounting and
  wrapped-import accounting both remain. No behavioral workaround was removed.
- All 47 patches from j0080 through j0100 apply in CI filename order against
  the Wi-Fi source base (`~/xnu-wifi`, parent of `544ee9f`). Evidence stays in
  ignored `research/wifi-integration/patch-application.log`.
- j0100 defaults jasmine's radio and modem on, retaining the tested 45-second
  modem delay. `wifi=0` disables the radio and default modem startup;
  `modem=0` explicitly prevents modem startup. Topaz retains explicit opt-in.
- `wifi_diag=1` enables the late QRTR trace, packet notes and SMMU step reads.
  State transitions, faults and reboot diagnostics remain available by default.
  The short-frame diagnostic also checks bounds before reading its LLC bytes.
- Device-tree generation includes WLAN by default. `--no-wlan` supports the
  off fallback. `mkimg.sh` handles explicit `wifi=0`/`modem=0` and propagates a
  failed shim build instead of copying a stale image.
- `tools/check-wifi-integration.py` rejects any skipped repository patch in the
  build log and checks combined Wi-Fi/reboot/framebench source markers. CI also
  checks their linked symbols. A green wrapper alone is insufficient.
- `tools/wifi-root-config.py` provisions configd's en0 service on an offline
  mounted root, with an original-file backup and without replacing existing
  services or static addressing. Invoke directly or through
  `sudo python3 tools/sweet-root-tweaks.py MOUNTED_ROOT --wifi` for new installs.
  Do not run all root tweaks against the live phone just to add Wi-Fi.
  This phone already received configd's configuration during the Wi-Fi rounds;
  it should not need another rootfs write for the first test.

## Build and image kit

Workflow `xnu.yml`, `topaz_4k=1`. Runs `40353134781` and `40354341764` were
cancelled while queued; neither compiled. The first was superseded by a corrected
C++ symbol check; the second was blocked by the active macOS14 brownout.
Supported Intel-runner build: **40358833912**, source **8405096**. ARM run
40357619511 was cancelled while queued without compiling. The Intel build
passed in24m25s including the cold build and artifact steps. Do not equate CI
with device success.

GitHub's [macOS14 retirement notice](https://github.blog/changelog/2026-10-01-github-actions-macos-14-runner-image-retirement/)
lists the Oct26 14:00UTC–Oct27 00:00UTC brownout and Nov2 retirement. The kernel
job now uses `macos-15-intel`. Xcode16's IIG emits a different RPC layout, so
`tools/xnu-legacy-iig.py` preserves the exact Xcode15-generated headers and
implementations from successful Wi-Fi CI40159794543. A pinned manifest checks
1922 original source header/definition hashes, 34 output hashes and the IIG
preprocessor configuration before replay. The private SweetSurface header and
two unrelated HFS/libpthread SDK header copies are excluded; RPC headers and
all IIG definitions are checked. No kernel ABI change or generated Apple source
is committed. Each build refreshes this immutable seed as a 90-day artifact.
If the source/generation configuration changes, the replay deliberately fails.

The offline packager reuses `shim/out/shim-boot-j99-wlan.img`'s verified shim
and hardware ADT, replacing only the kernel and the specified boot options.
It checks plain arm64, integration symbols, boot-argument length and payload
round trips. Default/diagnostic ADTs must remain byte-identical to j99.
The off image removes only `/arm-io/wlan`. No GPU library is installed/replaced.

```powershell
python tools/g2/wifi-build-kit.py --run 40358833912 --expected-head 84050968075304307e93f16baeb7f507725e8d70 --baseline "C:/Users/teleg/Documents/Code/Xiaomi A2/ios-jasmine/shim/out/shim-boot-j99-wlan.img" --out "C:/Users/teleg/Documents/Code/Xiaomi A2/ios-jasmine/research/wifi-integration/ci-40358833912"
```

The downloader refuses queued, failed or mismatched builds and requires the CI integration-gate output before
packaging. `wifi-images.py` can also package a separately verified local kernel.
For an interrupted download, `--resume` requires saved metadata for the exact
same successful source/run and refuses to overwrite existing images. Build-job
log downloads retry with HTTP/2 disabled after an observed stream cancellation.

Images: `wifi-default.img` exercises defaults without modem/wifi/delay arguments;
`wifi-diagnostic.img` differs by `wifi_diag=1`; `wifi-off.img` uses
`modem=0 wifi=0` and omits the WLAN node. `manifest.json` records full hashes,
kernel/source/CI provenance and exact command lines. Nothing auto-boots.

## Device session when the user is home

Coordinate availability and take the shared phone lock for the entire session.
Use the established lock helper in `tools/g2/framebench.py` or the exact shared
`PHONE_LOCK`; never remove another owner's lock. Read NOTES.md first in case
another chat used the phone. Fresh charging-shell capacity must be at least
30%; the previous observation was 12% with net discharge. Defer if still low.
No unattended retry, flashing or destructive step is authorized by this runbook.

1. **Preflight and identity.** Verify image hashes against the manifest, save
   production `/usr/local/bin/libsweetca.dylib` hash and current slot, and check
   that the r109 parking image and ordinary slot-b fallback are present. Keep
   the existing production library. Stop other collectors. Use existing
   charging-shell reboot-to-fastboot procedure; never `fastboot getvar`.
2. **Default-on boot (about 2 minutes).** Temporary `fastboot boot` of
   `wifi-default.img`. Start the USB console collector immediately (port5140;
   allow 180s for connection). Unlock once if wifid needs protected preferences.
   Do not tap a network before observing whether it auto-joins. Expect the
   modem start after45s, radio ready, then known-network join. Verify Wi-Fi icon,
   a real en0 DHCP address/default route/DNS and a fresh internet page in Safari.
   Verify USB command **and file** services still respond while joined. Check
   Home, icons, wallpaper, dock, CC/NC and a swipe for GPU/IOSurface regressions.
   `bench stat` must respond; do not start a performance capture.
   Run the staged **production-matched seven-step GL control** once, bounded
   to20s: require all7 steps PASS, exit0, no new GPU/SMMU fault. It comes from
   CI40170072509 /a9e95ec, under the original checkout's ignored
   `research/wifi-integration/production-gl-control/`; test SHA256
   `5bcc71b6613738fd379968a87964e15f8208af8e6fb4a7d4546239aaaaf5e6bc`.
   Its companion library matches production14e32aea... exactly. Install only
   the test as `/usr/local/bin/sweetgpu_gltest-wifi-acceptance`, verify readback,
   run with no options, then remove that test file. Do not install its library.
   This exercises the kernel's GPU/IOSurface import path using the established
   control, without Task24's unrelated experimental eighth step.
3. **Disconnect/recovery (about 3–5 minutes).** Toggle Wi-Fi off/on in Settings;
   expect clean leave and auto-rejoin with working traffic. With a controllable
   test AP/hotspot, remove and restore the AP while joined, then verify recovery.
   On a spare test network attempt a wrong password, then the correct one;
   expect a bounded failure and successful recovery without firmware FATAL.
   Do not overwrite/forget the only known working network to stage this test.
   Verify USB remains reachable throughout. A second known network/preference
   ordering can be checked here if available; record unavailable cases explicitly.
4. **Joined reboot #1.** Start a separate reboot collector **before** sending
   `reboot`, retain150s so any watchdog dump is captured. Expect clean leave,
   `wlan_mode off ok err 0`, `(stop-ack)`, zero pinned wrapped imports/pins,
   RootUnmount followed promptly by system unmount, and actual fastboot return.
   Seeing system unmount alone does not prove reset succeeded. Power-off or a
   stall is a failed gate; retain logs, use buttons if needed, stop the rollout.
5. **Default-on repeat / joined reboot #2.** Boot the same default image again,
   verify auto-join and USB/internet, then repeat the joined reboot. This is a
   practical smoke test of the intermittent stall fix, not a statistical proof.
6. **Off fallback (about 1–2 minutes).** Temporary boot `wifi-off.img`. Verify UI,
   USB command/file access and framebench status with no modem/radio startup.
   Capture its clean reboot, then park in r109 with backlight off. Verify fresh
   charging state and production library hash matches preflight; release own lock.

If a functional case fails, stop and use the diagnostic image for **one specific
reproduction only after coordination**. Preserve source/image hashes and the
complete boot/reboot logs; do not keep rebooting on a depleted battery. A new
runtime GPU/SMMU fault, modem FATAL, freeze or failed reset stops the session.
The known production GPU startup self-test FSR0x400 is historical baseline;
do not silently classify a new fault as that baseline.

Useful existing commands (run only while owning the lock):

```powershell
python tools/sweet-netlog.py research/wifi-integration/device/boot1.txt --wait 180 --for 240
python tools/sweet-cmd.py help
python tools/sweet-cmd.py "bench stat"
python tools/sweet-sh.py /bin/df
# In a second terminal, start this BEFORE sending reboot:
python tools/sweet-netlog.py research/wifi-integration/device/reboot1.txt --wait 10 --for 150
python tools/sweet-cmd.py reboot
```

Create the output directory before starting collectors. `sweet-fs.py` supplies
the existing file service; use a read-only readback/hash for coexistence checks.
Inspect logs offline with:

```powershell
python tools/wifi-check-log.py research/wifi-integration/device/boot1.txt --phase boot
python tools/wifi-check-log.py research/wifi-integration/device/reboot1.txt --phase reboot
python tools/wifi-check-log.py research/wifi-integration/device/off.txt --phase off
```

The analyzer requires positive evidence and reports faults/stalls; it cannot
prove internet, visual correctness, USB coexistence or physical fastboot return.
Record every case PASS/FAIL/NOT RUN with exact log, image and build references.

## Merge and installation gate

After combined CI, artifact verification and the above device checks pass,
merge the integration branch into jasmine. A direct merge is sufficient; the
draft PR is an optional review aid. Keep the production Mesa library;
Task24's unrelated default-off experiment is not part of this test. Update the
handoff and PR with observed results. Installing the accepted kernel into slot b
is a separate destructive action requiring the user's explicit confirmation.
No partition layout change, rootfs reflash or modem/persist write is needed.
