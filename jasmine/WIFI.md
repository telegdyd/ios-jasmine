# Wi-Fi on jasmine: step 1, the modem (MBA boot)

Branch `wifi` (worktree `ios-jasmine-wifi/`, XNU worktree WSL `~/xnu-wifi` branch `wifi` on `fde1ca9` = j0070).
Test images only: nothing flashed, slot b unchanged. Phone lock: the usual `phone.lock` (see `tools/g2/flash-slotb.sh`).

## What the patches do (j0080, j0080b-h, all boot-arg gated: `modem=1`)

- **j0080** TopazModem on jasmine: SoC addresses per board (`board_setup()`: SMEM 0x86000000, TCSR mutex 0x1f40000,
  APCS 0x17911000, GLINK bit 15, WLAN MSA 0x85700000, anoc2 SMMU 0x16c0000 SID 0x1a00, CE 0x18800000+0x240000,
  pool 0xA1000000); firmware found at run time in the modem partition's FAT16 (`fat_*`, replaces topaz's offset
  tables; modem_a == modem_b); rmtfs on the DT carveout 0x85e00000 (HLOS+MSA, read-only EFS as topaz);
  `modem_boot_mba()` = Linux `qcom_q6v5_mss.c` sdm660_mss (cx/mx TURBO proxy votes, GCC MSS clocks/reset, QDSP6 v62
  power-up, PBL/MBA RMB handshake, metadata + segments, hyp assign HLOS<->MSS_MSA); `sweet_rpm_level_client()`
  aggregates rail votes per AP client (GPU 0, modem 1). Wi-Fi radio and en0/wifid glue stay off on jasmine.
- j0080b step log, `modem_delay=S` (start after the USB log is up), `modem_stop=1`.
- j0080c RPM clock handoff + scaling on before the boot (`modem_rpmclk=0` skips), DDR voted back.
- j0080d/f SError details in the panic line (`printf` there panics: console I/O with interrupts off); `modem_pblwait=MS`.
- j0080e `gpll0_out_msscc` (GCC 0x5200c bit 2, msm-4.4 gpll0_mss_clk); RMB code start/length 0 before release.
- j0080g halt-port log, `modem_pulse=1`, TCSR halt/QDSP6SS/RMB open to the command port `r`/`w` (with `sweetosm=1`).
- j0080h MBA bytes in DRAM checked (uncached read-back + crc32).

## 2026-10-24 afternoon: the modem boots, GLINK and the QMI services come up

- **j0080i** (the SError): the "QDSP6 started" log line read QDSP6SS PWR_CTL/MEM_PWR_CTL/RESET after STOP_CORE
  was cleared, and the SError was taken in the next IOLog. Only RMB is read after the start now. MBA boots, metadata
  and all MPSS segments authenticate, READY + HANDOVER 114 ms after the start, proxy votes dropped.
- **j0080j**: the modem's GLINK TX FIFO (SMEM item 480) is in the partition's *cached* list, which our `smem_get`
  never searched (mainline `qcom_smem_get_private` does). With it: IPCRTR up, qrtr HELLO, 42 services, pd-mapper,
  tftp (modem_pr/mcfg, wlanmdsp.mbn), rmtfs (modemst1/2, fsg, fsc), WLFW 0x45 at ~840 ms: chip_id 140, fw
  WLAN.HL.1.0.1.c2-00811. host_cap is rejected (err 1, the `snoc-host-cap-8bit-quirk`), then "waiting MSA_READY ind"
  (the `no-msa-ready-indicator` quirk).
- The modem then goes FATAL: `dog_hb.c:266: Task starvation: diag, ping: 4` at 13 s with our WLFW handshake
  (WCN3990 unpowered), at 101 s without it (**j0080k**: no WLFW handshake on jasmine while the radio is off).
  Nothing happens on GLINK after 8.8 s. Next: does Linux's modem (r109 shell, no rmtfs/tftp/diag) live longer?
- WCN3990 power for the radio step (pm660 RPM LDOs): L5 0.8 V cx/mx, L9 1.8 V xo, L6 1.3 V rfa, L19 3.3 V ch0.
- Linux reference (r109 shell, 17:22): its modem crashes every **40 s** ("fatal error without message", 5 recoveries
  in 210 s): the shell has no rmtfs/tftp/pd-mapper, so it is no lifetime reference. Ours lived 101 s.
- **j0080l** WCN3990 LDOs on before the modem boot (`wcn_power_on`): all four on, still FATAL at 101.2 s (j0080k
  101.4 s): deterministic, not the chip power.
- **j0080m** WLFW handshake once the chip is powered (`wlfw=0` skips), jasmine quirks: host_cap `daemon_support` as
  a u8 (answer err 94 NOT_SUPPORTED, not fatal as in ath10k), the msa_ready response taken as MSA_READY.
  **j0080n** `wifi=1` allowed on jasmine (anoc2 SMMU identity bank, CE after mission; untested), SHADOW_PA per board.
  **j0080o** GLINK/qrtr trace after 3 s: nothing at all from the modem between 8.6 s (mcfg tftp) and the crash.
- j0080o round: handshake to the board data (`image/bdwlan.bin`, board_id ff, 19152 B); the end segment answered
  err 1 (firmware CRC check of the BDF; ath10k ignores it and the firmware uses its built-in BDF), we stopped, FATAL
  at 17 s. The earlier the WLAN PD stalls waiting for the host, the sooner the starvation (13 s / 17 s / 101 s).
  **j0080p** goes on to cal_report like ath10k.
- CI: `xnu.yml` has `cancel-in-progress`: a new dispatch on the branch cancels the running build.

## Result so far (2026-10-24 06:20-08:20): the PBL kills the MSS register bus

Every step works up to the core start: FAT index (429 files), MBA copy (DRAM crc = file crc), cx/mx votes, all MSS
clocks, both hyp assigns (ret 0), the whole QDSP6 power-up (BHS ack, memories 0x1fffffff, clamps off). Right after
STOP_CORE is cleared the **first AP read of RMB (or QDSP6SS) gets a bus error**: SError `esr 0xbf000002`, taken in
the next IOLog. With `modem_pblwait=3000` nothing happens for 3 s, then the first RMB read faults. After the start all
three MSS AXI halt ports read idle. TZ `tr` reads return 0 for everything (filtered, useless).

Ruled out: qdss/RPM clock scaling (j0080c), gpll0_msscc (j0080e), halted ports / reset pulse (j0080g), GPU and its
CX votes (GPU-off image), MBA content (j0080h).

## Linux reference (r109 shell, same phone, same firmware chain): boots fine

`fastboot boot shim/out/nura-r109-boot_a.img`, push `qmi_helpers qcom_sysmon qcom_q6v5 qcom_common qcom_pil_info
qrtr qcom_q6v5_mss` (.ko from the r109 apk, decompressed: `research/wifi/r109-mods/` in the main checkout; qcom_aoss and mdt_loader are already
loaded), `mount -t vfat -o ro /dev/disk/by-partlabel/modem_a /mnt/m`, firmware path `/mnt/m/image`, insmod, `echo
start > /sys/class/remoteproc/remoteproc0/state`: "MBA booted" ~80-110 ms, MPSS up 1.5 s.

- function_graph of `q6v5_load`/`q6v5_start` (`research/wifi/linux-trace/q6v5_start.trace`): same order as ours.
- kprobes in `q6v5_mba_load` (x19 = qproc; +0x460 after the assigns, +0xf04 PBL done, offsets from the r109 module):
  before the power-up Linux has **exactly our state** (RESET 7, GFMUX 0x100, PWR_CTL 0x700000, XO_CBCR 0x80000000,
  BHS 0, RMB all 0), the same assigns (mpss then mba, src HLOS -> MSA RW), and its first RMB poll right after
  STOP_CORE gets PBL 1 and MBA 2.
- Reading QDSP6SS registers from a kprobe right after the core start, or RMB+0x40 while the modem runs, crashed
  Linux too: those reads are fatal in Linux as well. Linux reads only RMB 0x04/0x0c during the boot.

Tools in `research/wifi/` (main checkout, gitignored): `modem-round.sh` (lock + fastboot boot + log; aborts if the
phone is unreachable), `fatls.py`, `rd32.c`, `mba_load.dis` (r109 module disassembly), `linux-trace/`.

## Next (not done)

The state and the sequence match Linux; the difference is in how XNU touches the hardware or what else runs. Ideas:
1. Our code reads QDSP6SS after STOP_CORE? It should not (only RMB); recheck every read between STOP_CORE and the
   PBL poll (the LOG lines), and the memory type `ml_io_map` gives (Device-nGnRnE vs Linux nGnRE).
2. Other XNU activity on the same buses during the boot (GCC debug-mux measurements, bwmon, profiler, TSENS):
   run the boot with them off.
3. Speculative AP access to the assigned regions (any XNU mapping of 0x8ac00000-0x92a00000 / 0x94800000) -> hyp/TZ
   reaction; check the early V=P blocks and every mapping.
4. Port the rest only after the MBA boots: WLFW quirks (`snoc-host-cap-8bit-quirk`, `no-msa-ready-indicator`),
   WLAN SMMU on anoc2 behind the hypervisor, TxBF-on-disassoc fix (kernel/0005).

## 2026-10-24 evening (j0080q-t), handoff

- j0080q `modem_nowlan=1`: no WLAN PD, FATAL still at 101.1 s. Its stop-on-FATAL took an SError (reverted in j0080r).
- j0080r `master-kernel` SMP2P entry: 101.1 s. qdss RPM vote dropped live after handover: 101.4 s.
- Nura journal (backup rootfs): diag-router talked to the modem over DIAG_CNTL on every boot; no diag starvation.
- j0080s pd-mapper from the jasmine jsn files; j0080t glink_ssr + DIAG channels: glink_ssr up, the modem still never
  opened DIAG, FATAL at 100.95 s; the reboot after the round froze the phone.
- Summary and next tasks: `jasmine/WIFI-HANDOFF.md`.

## 2026-10-24 20:00-20:45 (j0080u-w): diag starvation solved

- The modem's diag is a QRTR client (service 4097), not GLINK `DIAG*` channels. j0080u publishes the diag
  servers, j0080v answers its 3-byte feature mask, j0080w logs `modem alive` each minute. j80w: alive to t=480000,
  no FATAL. Details and findings: `jasmine/WIFI-HANDOFF.md`.

## 2026-10-24 20:49-21:30 (j0080x-y): WLAN PD back on, safe stop, wifi=1 hangs in the SMMU setup

- j80w-modem1 (20:50, `modem=1 modem_delay=45`, WLAN PD on): chip 140, BDF (end-segment CRC rejected, not
  fatal, as ath10k), FW_READY, **mission mode at 2.5 s, modem alive to t=180000** (end of the 300 s log), no
  FATAL. The 13-17 s deaths with the WLAN firmware waiting were the diag starvation too. Reboot and park fine.
- j0080x `topaz_modem_stop(panic)`: q6v5_stop on the reboot (command-port reboot, `haltRestart` restart/halt)
  and panic paths: master-kernel bit 0, wait for slave-kernel bit 3 (5 s, 200 ms on a panic), clear, halt
  q6/modem/nc ports, assert mss_restart. No handshake after a FATAL (as Linux for a crashed remote), no clock or
  memory steps. Not yet exercised on the phone (the j80x round never booted the modem, below).
- j80x-wifi (21:02, `wifi=1`): `smmu: sCR0 00200626 ID0 48017a06 ID1 40008015: 6 SMRs, 21 CBs, page 1000 x32`,
  then nothing more from the modem thread for 5 min; no panic, the rest of iOS ran, the command-port reboot
  worked. So one access in `smmu_identity` after the ID reads never completes. Not writeback addressing (the
  disassembly has plain `ldr/str [x, #imm]` only). Linux on Nura sees the same SMMU (6 groups, 21 CBs).
- j0080y: a log line after each step of `smmu_identity`, and 0x16c0000-0x1700000 on the command port (`r`).
- j80y-wifi (21:21): every step lands and reads back (CB4 SCTLR e0, S2CR0 4, SMR0 80011a00), then the
  **global TLB sync** (sTLBGSYNC 0x70 / sTLBGSTATUS 0x74) never returns. The rest of iOS keeps running.
- j80y-aggr (21:30, `modem_delay=90`): the live aggre2 NoC vote could not be sent (the `rpm` parser wanted
  4-char keys, `KHz` is 3: fixed in j0080z). It would not have mattered: aggre2 (downstream anoc2 SMMU clock
  `AGGR2_NOC_SMMU_CLK`) is in the RPM scaling handoff, and before scaling is on the RPM ignores AP rate votes
  (UFS and USB run over aggre2 anyway). Same sync hang; this time the phone went down by itself ~45 s later
  and came back in fastboot (watchdog reset, probably); parked fine.
- j0080z: WCN3990 rails before the SMMU setup. j80z-wifi (21:40): rails on, **sync still hangs**. Not power.
- j0080aa: no global sync on jasmine. Linux's `arm_smmu_write_sme` does none after SMR/S2CR writes; the global
  sync only follows TLB maintenance (none issued, the bank does not translate) or the SMMU reset. If the WLAN
  TBU itself is unreachable, CE DMA will show it (no HTC READY) without a CPU hang, since CE is polled in memory.
- The CI applies `xnu/patches/*.patch` in glob order and **skips a patch that fails with only a warning**
  (`Skipping patch ... already upstream, previously applied, or malformed`): `j0080aa` sorted after `j0080`
  and was skipped, so j80aa (21:53) ran the j0080z kernel (same hang). Renamed `j0081`. Check the build log
  for `Skipping patch` (4 blacktop patches for other macOS versions are always skipped, that is normal).
- **j81-wifi (22:06): Wi-Fi scans under iOS.** SMMU `WLAN identity ... CB4 SMR0 -> OK`, modem READY at 108 ms,
  FW_READY 2.5 s, mission, CE 12 rings, HTC READY (2 credits x 2184, 22 endpoints), HTT/WMI connected, WMI
  SERVICE_READY + INIT + READY (fw MAC 00:00:00:00:00:00: no MAC given yet), chan list 37, passive scan:
  scan 1 at 7.3 s 5 networks, scan 2 6 networks, every 15 s after.
  Modem alive to t=180000 with the radio running. **Safe stop on the reboot**: `stop: slave-kernel 0000000e
  after 207 ms (stop-ack)`, `modem ports halted, mss_restart held`; fastboot and park fine (80%, charging).
  `modem-round.sh` now also records the log across the reboot (`<log>-reboot.txt`).

## 2026-10-24 22:15-23:05 (j0082-j0085): factory MAC, en0 + wifid, first join

- j0082: the Wi-Fi MAC from the persist partition's `/wlan_mac.bin` (`Intf0MacAddress=<12 hex>\nEND`, as
  Android's cnss-daemon), read in the kernel with a read-only ext4 root-directory lookup over `sweet_ufs`
  (tested on the host against both persist backups, byte-exact). The fixed 02:54:4f:50:41:5a stays as the
  fallback. The firmware still reports 00:..:00 in WMI READY; the vdev is created with our address (as ath10k).
  Linux/Nura never used it: ath10k picked a random MAC and pmOS `bootmac` set a made-up 02:00:... one.
  **j82-wifi (22:35)**: `wifi: MAC 94:87:e0:**:**:** from persist/wlan_mac.bin`, scans as before, clean stop
  (206 ms), parked 80%. Only 3 automatic scans is by design (`scans < 3`); later scans are on request.
- The ath10k TxBF-on-disassoc fix (Nura `kernel/0005`) does not apply: our WMI code sends no vdev TxBF param.
- j0083: `topaz_sta_init()` (en0 + Apple80211) on jasmine when `wifi=1`. j83-wifi (22:43): en0 attached once
  WMI was ready, but **wifid never ran**: launchd starts it only when the ADT has a `wlan` node
  (`_LimitLoadToDeviceTree`), which `tools/mkadt.py` made only for topaz. Fixed on branch `jasmine`
  (8fda077): `mkadt.py --wlan`, passed by `mkimg.sh` when EXTRA_ARGS has `wifi=1` (other images unchanged).
- **j83-wlan (22:52): wifid scans, networks show in Settings (user saw them), and the first join works at
  the 802.11 level**: wifid ASSOCIATE (TelekNet, WPA2, passphrase) -> `join: TelekNet 2472 MHz WPA2`, auth
  status 0, assoc status 0 aid 7, 4-way handshake, `WPA2 keys installed (group key yes, idx 2)`,
  `joined TelekNet` in 56 ms; wifid reads CURRENT_NETWORK/SSID/BSSID fine after it, link stays up.
  **No IP address** (Settings spins, no address under the network's info): DHCP never completes; the data
  path after the keys has no log (counters existed, never printed) -> j0084.
  The **reboot afterwards hung**: modem stop-ack after 128 ms, then `mba: halt modem port: ack 0 idle 0`
  (every earlier reboot halted it), mss_restart asserted, launchd quiesced, then nothing; the round script
  gave up, the user's Power + Volume down brought fastboot back at ~23:00; parked 71%.
- j0084: data path diagnostics while joined: a `wifi data:` line every 10 s (tx queued/sent/done by
  completion status/drops, rx msdus/data/eapol/up/not up/no SNAP) and the first 12 frames each way
  (IPv4 UDP ports: DHCP is 68 <-> 67).
- j0085: Wi-Fi off before the modem stop, as Linux (ath10k leaves the AP and sends WLFW WLAN_MODE OFF, then
  remoteproc stops the modem): `topaz_modem_stop` (not on a panic) asks the modem thread for `w_teardown()`
  and WLAN_MODE OFF (mode 4), waits up to 1.5 s for the answer, then the stop handshake as before.
- **j85-wlan (23:13, 420 s)**: TelekNet joined again (keys in 51 ms; the user tapped it: wifid does not
  auto-join on boot, see the handoff). j0084's counters: rx works
  (478 frames up to en0: ARP, IGMP, SSDP/WS-Discovery multicast), but **`tx queued 0`**: iOS never sent a
  frame (redwood_net: `0 frames sent`). Cause: configd had **no network service at all** —
  `/private/var/preferences/SystemConfiguration/preferences.plist` held only the host names (no Sets, no
  NetworkServices, no CurrentSet), while `NetworkInterfaces.plist` already named en0 (IEEE80211, builtin,
  `IOPathMatch .../RedwoodWLANController/RedwoodWLAN`). configd starts ~45 s before en0 exists
  (`modem_delay`), so it never made the default configuration. Written live over sweet_netfs (23:19, the
  original kept in the session scratchpad): one Set "Automatic" (CurrentSet) with a "Wi-Fi" service for en0
  (Interface DeviceName en0 / Hardware AirPort / Type Ethernet, IPv4 DHCP, IPv6 Automatic, ServiceOrder).
  Read by configd on the next boot; not yet tested. No kill/launchctl/scutil on the phone to restart configd.
- j85 reboot: j0085 sent WLAN_MODE OFF 20 ms after the teardown; the WLAN firmware asserted at once
  (`err_qdi.c:459:EF:wlan_process:1:cmnos_thread.c:3285:Asserted in wlan_vdev.c`), modem FATAL, no
  answer, `halt modem port: ack 0 idle 0` again, hang; the user's reset at ~23:25, parked 67%.
- j0086: Wi-Fi off in ath10k's order, one step per poll with the firmware's time: teardown (vdev down, peer
  delete, vdev stop), wait for WMI VDEV_STOPPED (0x5002, 400 ms at most), VDEV_DELETE (0x5002, tag 0x57),
  200 ms, CE off, WLAN_MODE OFF; stop waits up to 2.5 s. And when a modem port does not halt, mss_restart is
  not asserted (the board reset follows anyway): the two hangs both came after an unhalted modem port.
- **j86-wlan (23:35): IP address and internet over Wi-Fi (user-confirmed in Settings and with a page).**
  configd read the written Set: right after the join (t=30.1 s) en0 sent IPv6 ND and a DHCP DISCOVER
  (`UDP 68 -> 67`); the address came. The user saw a **gray Wi-Fi icon** in the status bar. ~1 s after the
  DHCP exchange (t=33.7 s) the USB log stopped and the command port was gone at the end, while iOS stayed
  responsive (user): the USB link lost its path once en0 was configured (handoff task 1). The reboot test of
  j0086 did not run; the phone was left in iOS.
- j0087: scoped routes for ue0 (192.168.7/24, 169.254/16) and the 5140/5141/5142 listeners bound to ue0
  (IP_BOUND_IF, inherited by accepted connections; also keeps them off the Wi-Fi network).
  **j87-wlan (23:59)**: both scoped routes added (0), the user tapped TelekNet at ~00:02, joined, DHCP
  DISCOVERs out, and the USB log stopped at 00:02:06 again. From the PC, 169.254.7.2 did not even answer
  ARP (neighbour state Probe; the PC's adapter "ios-sweet Sweet iOS (USB Ethernet)" had 169.254.218.81).
  Cause, in XNU: `arp_lookup_route()` never scopes a 169.254 lookup ("don't constrain the lookup"), so IPv4
  link-local lives on one interface, the one holding the unscoped 169.254/16 route, which configd gives the
  primary interface (en0 once it has an address). Nothing scoped can keep a 169.254 USB link alive.
  The round's reboot could not reach the command port; the user's reset, parked 63%.
- j0088: a DHCP server on ue0 (UDP 67 bound to ue0) gives the PC 192.168.7.1/24 (no router, no DNS, lease
  7 days, NAK for other addresses); the tools already try 192.168.7.2 first. 169.254.7.2 stays as a fallback.
- j88-wlan (00:13): the PC's DHCP DISCOVERs reached the server, but every OFFER failed `sock_send` 51
  (ENETUNREACH: nothing routes 255.255.255.255 out of ue0); no join, the reboot worked (j0086 unjoined:
  vdev stopped + deleted, WLAN_MODE OFF ok in 225 ms, stop-ack 50 ms, then `halt modem port: ack 0 idle 0`
  and the new fallback left mss_restart alone), parked 68%.
- j0089: a ue0-scoped host route for 255.255.255.255. **j89-wlan (00:22) and j89b (00:29)**: the PC's USB
  adapter got **192.168.7.1/24 by DHCP** (offer + ack, send 0), the log connected over 192.168.7.2 and ran the
  whole 300 s, the reboot over the command port and the park worked (69%, 70%). No Wi-Fi join happened in
  either round, so the link with Wi-Fi up is still to be seen. The modem port never halts, Wi-Fi or not.
- **j89c-wlan (01:02, 360 s): the USB link survives Wi-Fi.** PC on 192.168.7.1 by DHCP, log over
  192.168.7.2; the user joined TelekNet at t=26 s; the log ran on (`wifi data` at 36/46/56 s: 1805 frames sent,
  all completed ok, 0 drops; 2720 received up to en0). Reboot over the command port while joined at 01:05:53:
  the j0086 teardown made the WLAN firmware assert at once (`Asserted in wlan_vdev.c`, modem FATAL),
  WLAN_MODE OFF unanswered (2.5 s), no stop handshake, modem port not halted -> mss_restart left alone ->
  the phone rebooted to fastboot normally; parked 84%. So j85's assert was the teardown while joined too.
