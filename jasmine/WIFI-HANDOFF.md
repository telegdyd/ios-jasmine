# Wi-Fi on jasmine: handoff (2026-10-25, 02:45)

Status: **Wi-Fi works under iOS: joined, DHCP address, internet (round j86-wlan, 23:35, user-confirmed).**
wifid scans (networks in Settings), joins WPA2 (TelekNet, keys in ~50 ms, it rejoins by itself on boot),
configd runs DHCP on en0, traffic both ways. The factory MAC comes from persist. Still test images only
(`wifi=1` boot arg, nothing flashed). The USB link runs on 192.168.7.0/24 (j0088/j0089: the phone hands
the PC 192.168.7.1 over DHCP) and **survives Wi-Fi** (j89c, 01:02). **Leaving while joined works** (j0092,
round j92 at 01:57): Forget + rejoin in Settings, and the reboot while joined runs a clean Wi-Fi off
(wlan_mode off ok, stop-ack); before j0092 every leave while joined crashed the WLAN firmware.
Details of every round are in `jasmine/WIFI.md`; this file is the summary plus what is left.

## Where things are

| What | Where |
|---|---|
| Patches | `xnu/patches/j0080*.patch` (j0080 .. j0080z), `j0081-*.patch`, branch `wifi` of telegdyd/ios-jasmine, worktree `ios-jasmine-wifi/` |
| XNU source | WSL `~/xnu-wifi`, branch `wifi`, HEAD = j0081 (one commit per patch; `git format-patch -1 --stdout` > the patch file) |
| Main code | `iokit/Kernel/arm/TopazModem.cpp` (topaz's modem/Wi-Fi stack, made per board by `board_setup()` / `soc.jasmine`) |
| Other touched files | `bsd/dev/sweet_rpm.c` (per-client rail votes, `sweet_rpm_kvp`), `osfmk/arm64/sleh.c` (SError details in the panic line), `osfmk/arm64/sweet_osm.c` (MSS regs on the command port) |
| Test scripts | `ios-jasmine/research/wifi/` (gitignored): `modem-round.sh`, `linux-modem-life.sh`, `nura-extract.sh`, `nura-journal.sh`, `fatls.py`, `rd32.c` |
| References | `research/wifi/linux/` (mainline q6v5_mss, glink, gcc-sdm660 ..., `ath10k/` and `mac80211/mlme.c` from v6.12), `msm44/`, `diag/` (linux-msm diag-router sources), `jasmine.dts`, `r109-mods/` |
| Nura rootfs (Linux reference) | WSL `~/nura-root/root.img` (sparse, unpacked from `backup/nura-full-20261020/userdata-p2-root.e2i.gz`), read with `/sbin/debugfs -R "dump|ls|cat ..."`; journal copies in `~/nura-root/journal/` |
| Logs | `ios-jasmine/logs/netlog-j80*-{modem1,nowlan,qdssoff}.txt` |

### Build and test loop
- Build: commit in `~/xnu-wifi`, export the patch, push `wifi`, then
  `gh workflow run xnu.yml -R telegdyd/ios-jasmine --ref wifi -f topaz_4k=1` (~5 min).
  **`xnu.yml` has `cancel-in-progress`: never dispatch while a build runs, the running one is cancelled.**
  **Patches apply in glob order and a failing one is skipped with only a warning**: name new ones so they sort
  last (`j0081`, `j0082`, ... not `j0080aa`) and grep the build log for `Skipping patch` (4 blacktop patches
  for other macOS versions are always skipped).
- Image: `wsl env GPUDBG=0 VARIANT=<v> AMP=1 CPUS=4 EXTRA_ARGS="gpudelay=1 gpupause=0 sweetfb_sync=1 sweetenv=backboardd:DYLD_INSERT_LIBRARIES=/usr/local/bin/libsweetca.dylib sweetcmd=1 sweetosm=1 modem=1 modem_delay=45 [modem_nowlan=1] [wifi=1] [wlfw=0]" bash tools/g2/mkimg.sh <tag>` after `gh run download <run> -n xnu-kernel -D xnu/out-jasmine-<tag>`.
- Round: `bash research/wifi/modem-round.sh shim/out/shim-boot-<tag>-<v>.img logs/netlog-<tag>-<v>.txt 300`
  (takes the phone lock, moves the phone from the r109 charging shell to fastboot, `fastboot boot`s the test image,
  logs N s, then parks it back on the r109 charging shell; skips the round under 10% battery). Test images only:
  nothing is flashed, slot b (plain iOS) is unchanged.
- Boot args: `modem=1` (on), `modem_delay=45` (start after the USB log is up), `modem_nowlan=1` (tftp refuses
  `wlanmdsp.mbn`: no WLAN PD), `wlfw=0` (no WLFW handshake), `wifi=1` (radio path: SMMU + CE + HTC/WMI, untested
  on jasmine), `modem_pblwait`, `modem_stop`, `modem_pulse`, `modem_rpmclk=0` (diagnostics).
- Live RPM experiments without a build: `python tools/sweet-cmd.py "rpm as TYPE ID KEY VALUE"` (needs `sweetcmd=1`).
- Phone rules: take `phone.lock` for any phone command; park on the r109 charging shell
  (`fastboot boot shim/out/nura-r109-boot_a.img`) whenever it is not needed; watch the battery level each round
  (no temperature limit); flashing needs the user's OK.

## Done (all on branch `wifi`)

| Patch | What |
|---|---|
| j0080..h | MBA boot port of Linux `qcom_q6v5_mss.c` sdm660 (FAT16 firmware reader, clocks, cx/mx proxy votes, QDSP6 v62 power-up, RMB handshake, hyp assign), SError details, diagnostics |
| j0080i | **the boot fix**: no QDSP6SS read after STOP_CORE (the "QDSP6 started" log line caused the SError) |
| j0080j | **GLINK fix**: SMEM cached-list search (the modem's FIFO item 480 is cached) |
| j0080k | no WLFW handshake with the chip unpowered |
| j0080l | WCN3990 LDOs (pm660 L5/L9/L6/L19 via RPM `ldoa`) |
| j0080m | WLFW with the jasmine quirks (`host_cap` u8, msa_ready as MSA_READY), `wlfw=0` |
| j0080n | `wifi=1` allowed on jasmine (anoc2 SMMU identity bank, CE after mission); SHADOW_PA per board |
| j0080o | GLINK/qrtr traffic trace after 3 s (250 lines) |
| j0080p | BDF end-segment CRC rejection not fatal (as ath10k) -> FW_READY + mission |
| j0080q | `modem_nowlan=1` (its FATAL-stop part was reverted in j0080r: SError) |
| j0080r | AP SMP2P item has `master-kernel` (jasmine DT) instead of topaz's `ipa` |
| j0080s | pd-mapper answers built from jasmine's six `.jsn` files (no `tms/pdr_enabled`, ADSP 74 / CDSP 76) |
| j0080t | multi-channel GLINK: `glink_ssr` opened back; `DIAG_CNTL`/`DIAG`/`DIAG_CMD` handled with a minimal diag-router (never exercised: the modem did not open them) |
| j0080u | **the diag fix**: diag over QRTR as diag-router `peripheral-qrtr.c`: we publish service 4097 (0x1001), instance-in-version 0 CNTL / 2 DATA / 4 DCI on ports 0x4005-7; the modem's diag connects at ~230 ms and publishes its CMD server 1001:1 (port 0x1c) and 1001:3 |
| j0080v | diag FEATURE_MASK with `mask_len` 3 (modem mask 0x1eef7) answered; DIAG_ID "msm/modem/root_pd" -> 2 |
| j0080w | one `modem alive` line a minute (slave-kernel, glink rx, diag cntl) |
| j0080x | `topaz_modem_stop`: q6v5_stop (SMP2P stop + stop-ack, port halts, mss_restart) on reboot and panic reset; j81: stop-ack after 207 ms, parked fine |
| j0080y | step lines in `smmu_identity`; anoc2 SMMU on the command port (`r 0x16c0000`) |
| j0080z | WCN3990 rails before the SMMU setup; the `rpm` command takes short keys (`KHz`, `uv`) |
| j0081 | **no global TLB sync after the WLAN stream setup on jasmine** (it never returned; Linux does none there) |
| j0082 | **factory MAC** from persist `/wlan_mac.bin` (read-only ext4 root-dir lookup over sweet_ufs); fixed address as fallback |
| j0083 | en0 + Apple80211 (`topaz_sta_init`) on jasmine with `wifi=1` |
| j0084 | data path diagnostics after a join: `wifi data:` every 10 s, the first 12 frames each way (drop or gate before default) |
| j0085 | Wi-Fi off before the modem stop (superseded by j0086: its WLAN_MODE OFF asserted the firmware in wlan_vdev.c) |
| j0086 | Wi-Fi off in ath10k order (teardown, VDEV_STOPPED, VDEV_DELETE, WLAN_MODE OFF); no mss_restart under an unhalted modem port |
| j0087 | scoped routes for ue0 (192.168.7/24, 169.254/16); the 5140/5141/5142 listeners bound to ue0 (also: not reachable from Wi-Fi) |
| j0088 | DHCP server on ue0: the PC's USB adapter gets 192.168.7.1/24 (no router, no DNS) instead of a 169.254 address |
| j0089 | scoped host route 255.255.255.255 on ue0 (the DHCP answers failed with ENETUNREACH without it) |
| j0090 | the leave as a step machine (`S_LEAVE`, `w_leave_poll`) with waits; no scan/join during it; STOP_SCAN before wlan off |
| j0091 | the leave stops a running scan first; a log line per leave step; no wlan off wait on a FATAL modem |
| j0093 | **status bar bars**: Apple80211 LQM event 39 every 5 s while joined (layout from IO80211 `_dispatchlqmChangedEvent`), live RSSI (joined AP's beacons + `rx_ppdu_start.rssi_comb`), NOISE (17) answered -95 dBm; j93 (02:38): bars white (user) |
| j0094 | modem stop without mss_restart: the modem AXI port never halts on sdm660 (Linux: "port failed halt" on every stop), the board reset takes the MSS |
| j0095 | one LQM event with the link-up event (j93: bars gray ~15 s after the join until the first 5 s tick); built (run 40147609435), not yet on the phone |
| j0092 | **the leave fix**: mac80211's order (`ieee80211_set_disassoc`): deauth, tx drain, PEER_DELETE until HTT unmap + PEER_DELETE_RESP, then VDEV_DOWN, VDEV_STOP until VDEV_STOPPED (VDEV_DOWN with the peer still there asserted in wlan_vdev.c) |
| tools (branch `jasmine`, 8fda077) | `mkadt.py --wlan`: the `/arm-io/wlan` node launchd needs to start wifid; `mkimg.sh` passes it when EXTRA_ARGS has `wifi=1` |
| phone rootfs (23:19) | configd's default network configuration written to `/private/var/preferences/SystemConfiguration/preferences.plist` (Set "Automatic", service "Wi-Fi" on en0, DHCP + IPv6 automatic); configd never made it because it starts before en0 exists |

Working sequence (j0080t log): MBA booted, metadata + MPSS authenticated, READY + HANDOVER at ~114 ms, GLINK
IPCRTR + glink_ssr up, 40-42 QRTR services, rmtfs (modemst1/2, fsg, fsc), tftp (mcfg, wlanmdsp), pd-mapper,
WLFW at ~840 ms: chip 140, fw WLAN.HL.1.0.1.c2-00811, board data `image/bdwlan.bin`, FW_READY 2.3 s, mission ok.

## Solved 2026-10-24 20:00-20:30: the diag starvation (j0080u/v)

The modem's diag does **not** use GLINK channels on this firmware: it is a QRTR client ("diag over sockets").
Nura's journal shows diag-router `Connecting CMD socket to 0:28` (node 0 = modem, port 28 = 0x1c) and the
`SOCKETS` feature bit. diag-router publishes service 4097 with the diag instance in the version byte (modem base 0:
CNTL 0, CMD 1 (looked up, the modem's server), DATA 2, DCI 4); the modem's diag waits for those servers and
starves without them. Rounds (all `modem_nowlan=1`, logs `logs/netlog-j80{u,v,w}-nowlan.txt`):
- j80u (20:05): modem connects to our CNTL at 228 ms, 35 CNTL messages; the feature mask was dropped (7-byte
  packet, we wanted 8). **No FATAL line** (j80t: `slave-kernel 00000007 FATAL` at 100.95 s); log ran ~200 s
  past the modem start. (The trace's last line sits at ~101 s only because the 250-line cap ran out.)
- j80v (20:20): full handshake (mask 0x1eef7, ours 0xa053, DIAG_ID), no FATAL, same ~200 s.
- **j80w (20:34-20:44): confirmed.** `modem alive: slave-kernel 00000006` at every minute from t=60000 to
  t=480000 (the last before the log ended), no FATAL. glink rx stops growing at 280 msgs after ~2 min (an idle
  modem is quiet); diag cntl 34. Reboot afterwards parked fine (as after j80u/v).

## Findings worth knowing (2026-10-24 evening)

- **Diag protocol over QRTR** (diag-router `router/peripheral-qrtr.c`, now in
  `research/wifi/diag/peripheral-qrtr.c`): service 4097, and the "instance" field is `instance << 8 | version`
  with the diag instance passed as the *version* (so the raw field is 0/2/4 for modem CNTL/DATA/DCI). Bases:
  modem 0, lpass 64, wcnss 128, sensors 192, cdsp 256. Replies go to the source address of the modem's
  first CNTL message (here 0:0x1b). DATA/DCI are dropped (RESUME_TX still sent by the generic path).
- The modem's FEATURE_MASK has `mask_len` 3 (7 payload bytes); diag-router reads 4 bytes regardless, which is
  why it "works" there. Control packets 12 (NUM_PRESETS) and 28 are ignored by diag-router too. We send
  feature mask, an all-disabled msg mask, diag mode v1, buffering mode v1; diag-router also sends log/event
  masks (`diag_cntl_send_masks`); add them only if something asks.
- **Reading round logs**: the GLINK/qrtr trace stops after 250 lines, so its last line is *not* the modem's death.
  A crash always shows `slave-kernel 00000007 FATAL` + `modem crash reason: ...`; the `modem alive` line
  (j0080w) gives the lifetime. The `t=` counter in `modem_watch` counts `IOSleep(1)` loop iterations, so it
  runs slower than wall time (the old 100.95 s FATAL used the same counter, comparisons hold).
- **Nura journal**, the best Linux reference: in WSL
  `journalctl --file='~/nura-root/journal/*.journal*' -o short-monotonic --no-pager | grep ...` (ordered, with
  boot-relative times). diag-router lines: `Connecting CMD socket to 0:28`, `[modem] mask: ... (0x1eef7)`,
  `unsupported control packet: 28`. The modem is up at ~42.4 s and its diag talks 250 ms later.
- Nura's rootfs (`~/nura-root/root.img`, debugfs) has `rmtfs`, `tqftpserv`, `diag-router` in /usr/bin and
  their systemd units; no pd-mapper binary (kernel 6.19.10 does it in-kernel), no udev rules for rpmsg.
- Tooling gotchas: `wsl bash -c '... | grep -E "a|b" ...'` from Git Bash mangles the quoting (empty output);
  write the script to a file and run `wsl bash /mnt/c/...`. In `~/xnu-wifi` git has no identity: commit with
  `git -c user.name=telegdyd -c user.email=telegdyd93@gmail.com commit ...`.
- 19:45: after the user's hard reset the phone was in fastboot, but `fastboot boot` of the r109 shell gave no
  USB device at all for ~13 min (no USB network, no fastboot); at ~20:04 it was back in fastboot and every
  later round and park worked. Cause unknown; if it repeats, wait or ask for another Power + Volume down.
- Battery: 73% at 20:46, charging fine in the r109 shell (~0.7 A).

## The old blocker (solved): `dog_hb.c:266: Task starvation: diag, ping: 4`

- Deterministic: 100.95-101.4 s after the modem start in every round without the WLFW handshake; 13-17 s when
  the WLAN firmware waits on the host (stuck handshake or mission mode with no copy engines).
- The modem sends nothing on GLINK after the mcfg tftp exchange at ~8.6 s (j0080o trace). `ping: 4` = the diag
  task missed 4 watchdog pings, i.e. it is stuck almost from boot.
- **Ruled out, one round each**: WCN3990 power (j0080l), the WLAN PD (j0080q `modem_nowlan=1`), the SMP2P
  `master-kernel` entry (j0080r), the RPM qdss vote (dropped live after handover), pd-mapper answers (j0080s),
  `glink_ssr` (j0080t).
- Linux r109 shell (no rmtfs/tftp/diag) is **not** a reference: its modem dies every 40 s ("fatal error without
  message").
- The earlier lead ("under Linux the modem opens `DIAG_CNTL`/`DIAG` itself") was wrong: under Linux the diag
  traffic is QRTR, not GLINK channels. j0080t's GLINK diag code stays for other firmware but is unused here.
- Still not done and not needed so far (things Linux does that we do not): kernel `qcom_sysmon` (SSCTL 0x2b
  client), QRTR lookups/DEL_CLIENT/BYE handling in our name service, PDR clients for the servreg-notifier (0x42),
  the GLINK interrupt (we poll). Look here first if a later step stalls.

## Next tasks, in order

1. (Done 2026-10-25 02:00, j0090-j0092: the leave while joined. Peer before vdev, as mac80211; see WIFI.md
   j90-j92. Also done: the USB link with Wi-Fi joined, j0087-j0089.) Not tried yet: the AP ending the link
   (deauth from the AP, peer kickout) and a failed join (wrong password), which run the same leave.
2. **Reboot while joined hangs, about 3 in 5** (j83, j85, j93 hung; j89c, j92 fine; unjoined never).
   The modem port part is settled (j0094): the port never halts on sdm660 and Linux logs `port failed
   halt` on every stop too, so no mss_restart. But j93 hung **without** mss_restart, so the reset was not the
   cause. The hang is after `launchd quiesce complete` and before `vfs_unmountall(nonsystem) start`
   (reboot_kernel: rest of proc_shutdown, audit_shutdown, sync(), IOSystemShutdownNotification RootUnmount),
   and the USB log dies within seconds (whole system frozen?). Next: log lines around each of those
   steps (and per IOService shutdown handler), then joined reboot rounds (each hang = the user's button reset).
   Blocks task 8: a default image would hang on about half the reboots while joined.
3. (Done 02:40, j0093/j0095: gray Wi-Fi icon.) The bars come from Apple80211 event 39 (LQM), see WIFI.md.
   j0095 (bars right at the join) is built but not yet tested.
4. **No auto-join** (user, 00:00): wifid does not rejoin TelekNet on boot; every join was a tap in Settings
   (the j85 note said otherwise, corrected). Look at how wifid stores known networks (com.apple.wifi.plist in
   /private/var/preferences/SystemConfiguration, the keychain for the password, which needs our AKS/securityd
   shims) and which Apple80211 requests or events it waits for before an auto-join (e.g. the refused 383/386,
   link events, a scan with the network's name).
5. **configd's default configuration on a fresh rootfs**: the live write (23:19) fixed this phone. For other
   installs either put the same `preferences.plist` into the rootfs setup (`tools/sweet-root-tweaks.py` or the
   install script), or make en0 exist before configd starts. Both versions are kept in
   `ios-jasmine/research/wifi/` (gitignored): `configd-preferences-wifi.plist` (written, binary plist) and
   `configd-preferences-orig.plist` (before: only System/HostNames + ComputerName "iPhone").
6. Other Apple80211 requests wifid gets REFUSED for: PHY_MODE (14), RATE (8), MCS (57), PROTMODE (6), POWERSAVE (5),
   INT_MIT (18), COUNTRY_CODE (51 get/set), 383, 386, 353, 346, 419, 422, HOST_AP_MODE (25). Answer the ones that
   matter for the UI (rate, phy mode) once task 2 is done.
7. Cosmetic: en0's link is named `wcn3988` (topaz's chip) and the ADT node says `jasmine,wcn3990`; name it per board.
8. **Done means on the phone**: make Wi-Fi the default (no `wifi=1`, ADT wlan node always on jasmine), drop or gate
   the diagnostics (j0080o trace, j0080y SMMU step lines, j0084 frame lines), build, and flash slot b **with the
   user's OK**. Only after task 2 is solid: a reboot hang on the default image would need a button reset every time.
