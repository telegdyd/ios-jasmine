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
