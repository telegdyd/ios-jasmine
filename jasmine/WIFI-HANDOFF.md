# Wi-Fi on jasmine: handoff (2026-10-24, 19:30)

Status: **the modem boots and runs under iOS, GLINK/QRTR and the host services work, and the WLAN
firmware reaches FW_READY + mission mode. Blocker: the modem's own watchdog kills it ~101 s after
start (`dog_hb.c:266: Task starvation: diag`).** The radio itself (copy engines, HTC, WMI, scan) and
the iOS glue are not started yet. Details of every round are in `jasmine/WIFI.md`; this file is the
summary plus what is left.

## Where things are

| What | Where |
|---|---|
| Patches | `xnu/patches/j0080*.patch` (j0080 .. j0080t), branch `wifi` of telegdyd/ios-jasmine, worktree `ios-jasmine-wifi/` |
| XNU source | WSL `~/xnu-wifi`, branch `wifi`, HEAD `6137680` = j0080t (one commit per patch; `git format-patch -1 --stdout` > the patch file) |
| Main code | `iokit/Kernel/arm/TopazModem.cpp` (topaz's modem/Wi-Fi stack, made per board by `board_setup()` / `soc.jasmine`) |
| Other touched files | `bsd/dev/sweet_rpm.c` (per-client rail votes, `sweet_rpm_kvp`), `osfmk/arm64/sleh.c` (SError details in the panic line), `osfmk/arm64/sweet_osm.c` (MSS regs on the command port) |
| Test scripts | `ios-jasmine/research/wifi/` (gitignored): `modem-round.sh`, `linux-modem-life.sh`, `nura-extract.sh`, `nura-journal.sh`, `fatls.py`, `rd32.c` |
| References | `research/wifi/linux/` (mainline q6v5_mss, glink, gcc-sdm660 ...), `msm44/`, `diag/` (linux-msm diag-router sources), `jasmine.dts`, `r109-mods/` |
| Nura rootfs (Linux reference) | WSL `~/nura-root/root.img` (sparse, unpacked from `backup/nura-full-20261020/userdata-p2-root.e2i.gz`), read with `/sbin/debugfs -R "dump|ls|cat ..."`; journal copies in `~/nura-root/journal/` |
| Logs | `ios-jasmine/logs/netlog-j80*-{modem1,nowlan,qdssoff}.txt` |

### Build and test loop
- Build: commit in `~/xnu-wifi`, export the patch, push `wifi`, then
  `gh workflow run xnu.yml -R telegdyd/ios-jasmine --ref wifi -f topaz_4k=1` (~5 min).
  **`xnu.yml` has `cancel-in-progress`: never dispatch while a build runs, the running one is cancelled.**
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

Working sequence (j0080t log): MBA booted, metadata + MPSS authenticated, READY + HANDOVER at ~114 ms, GLINK
IPCRTR + glink_ssr up, 40-42 QRTR services, rmtfs (modemst1/2, fsg, fsc), tftp (mcfg, wlanmdsp), pd-mapper,
WLFW at ~840 ms: chip 140, fw WLAN.HL.1.0.1.c2-00811, board data `image/bdwlan.bin`, FW_READY 2.3 s, mission ok.

## The blocker: `dog_hb.c:266: Task starvation: diag, ping: 4`

- Deterministic: 100.95-101.4 s after the modem start in every round without the WLFW handshake; 13-17 s when
  the WLAN firmware waits on the host (stuck handshake or mission mode with no copy engines).
- The modem sends nothing on GLINK after the mcfg tftp exchange at ~8.6 s (j0080o trace). `ping: 4` = the diag
  task missed 4 watchdog pings, i.e. it is stuck almost from boot.
- **Ruled out, one round each**: WCN3990 power (j0080l), the WLAN PD (j0080q `modem_nowlan=1`), the SMP2P
  `master-kernel` entry (j0080r), the RPM qdss vote (dropped live after handover), pd-mapper answers (j0080s),
  `glink_ssr` (j0080t).
- Linux r109 shell (no rmtfs/tftp/diag) is **not** a reference: its modem dies every 40 s ("fatal error without
  message").
- **Lead**: Nura (real Linux on this phone, weeks of uptime with Wi-Fi) ran `diag-router`. Its journal has
  `[modem] mask: ... DIAG-ID (0x1eef7)` and a modem control packet 28 on every one of 17 modem boots, and no
  diag starvation ever. So under Linux the modem **opens `DIAG_CNTL`/`DIAG` itself**; under our kernel it never
  does, in any round. Finding out why is the next step.

## Next tasks, in order

1. **Phone recovery first**: after the j80t round (19:25) the reboot froze the phone (no fastboot, no command
   port). Power + Volume down for ~10 s, then park: `fastboot boot shim/out/nura-r109-boot_a.img`.
2. **Why the modem does not open DIAG.** Best tool: a real Linux reference on the phone. Boot the r109 shell
   (`research/wifi/linux-modem-life.sh` does the module + firmware part), add `rmtfs`, `tqftpserv`, `diag-router`
   and their libraries (`libqrtr.so.1`, `libudev.so.1`, musl) dumped from `~/nura-root/root.img`, check whether
   r109 has the in-kernel pd-mapper (Nura had no pd-mapper binary), start the modem and watch
   `/sys/bus/rpmsg/devices` for when `DIAG*` appear and what was there before. Compare with our j0080o trace.
   Things Linux does that we still do not: kernel `qcom_sysmon` (QMI SSCTL 0x2b client, plus `sys_mon` if the
   modem has it), QRTR name-service behaviour (lookups, DEL_CLIENT/BYE), PDR clients registering with the modem's
   servreg-notifier (0x42) for `avs/audio` and `wlan/fw`, the GLINK interrupt (we poll), Linux's GLINK intent
   defaults. Nura journal timestamps of `[modem] mask` vs "remote processor ... is now up" would show what it waits for.
3. **Safe modem stop before reboot** (the freezes after a modem crash: j0080p, j0080t). Port `q6v5_stop`:
   set the `master-kernel` stop bit (SMP2P), wait for stop-ack (`slave-kernel` bit 3), then halt the AXI ports,
   assert `mss_restart`, clocks off, reclaim memory, and call it from the reboot path. j0080q's reclaim straight
   after a crash took an SError after the modem port failed to halt: do the stop handshake first.
4. **Radio bring-up** once the modem stays up: run with `wifi=1`. Unknowns: whether the anoc2 SMMU
   (0x16c0000, SID 0x1a00 mask 1) takes our identity context bank (the log says "OK" or "NOT as written"; it may
   be hypervisor-owned), then CE start, HTC, WMI READY and the passive scan (topaz code, polled). A WLAN firmware
   in mission mode without CE is also what preceded the first freeze.
5. **ath10k TxBF-on-disassoc fix** (Nura `kernel/0005`): do not reset the TxBF vdev param after the peer is gone,
   or the HL.1.0 firmware asserts on disassociation.
6. **iOS glue**: `topaz_sta_init()` (en0 + Apple80211 for wifid) is skipped on jasmine in `topaz_modem_init()`;
   enable it once scans work.
7. **Done means on the phone**: make it default (no boot args) and flash slot b with the user's OK; drop the
   diagnostics (j0080o trace, step logs) or put them behind a boot arg.
