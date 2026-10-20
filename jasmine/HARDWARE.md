# Mi A2 (jasmine) hardware facts for an XNU port

Read from the running Nura install on 2026-10-20 (sysfs, `/proc/iomem`, live device tree), all read-only.
Compared with the two existing ports. "Same" means the topaz code can be reused as is.

## CPU

| | Mi A2 (SDM660) | topaz (SM6225) | sweet (SM7150) |
| --- | --- | --- | --- |
| Silver | 4× Kryo 260 Silver, MIDR `0x51AF8014`, MPIDR `0x0`–`0x3` | **same MIDR** | 6× A55 |
| Gold | 4× Kryo 260 Gold, MIDR `0x51AF8002`, MPIDR `0x100`–`0x103` | Kryo 260 Gold, `0x100`–`0x103` | 2× A76 |
| ISA | ARMv8.0: `fp asimd evtstrm aes pmull sha1 sha2 crc32 cpuid`. No `atomics` (LSE), no `lrcpc`, no PAN | same | ARMv8.2 |
| 16K granule | Silver: no (`TGran16 = 0`, per topaz on the same MIDR). Gold: yes (per topaz). **Confirm in phase 1** | same | all cores |
| Boot CPU | Silver CPU0 (ABL) | same | A55 |
| PSCI | `arm,psci-1.0`, `smc`, CPU nodes `enable-method = psci` | same | same |
| cpufreq | None in Linux either; cores run at ABL's clocks. No cpufreq-hw block (topaz's `gold_cpufreq_max()` does not apply) | has cpufreq-hw | |

## Memory (4 GB model, `MemTotal` 3.67 GB)

`/proc/iomem` System RAM ranges:

```
80000000-855fffff   89500000-8abfffff   95000000-9d3fffff   9f7ff000-9f7fffff
a0000000-bfffbfff   c0000000-f5ffffff   f7c00000-fecfffff   ff700000-17e4bffff
```

Reserved (`no-map` unless noted): wlan-msa `0x85600000`+2M, qhee `0x85800000`+6M, `0x85e00000`+2M, smem `0x86000000`+2M,
`0x86200000`+51M, mpss `0x8ac00000`+126M, mba `0x94800000`+2M, adsp `0x92a00000`+30M, cdsp `0x94a00000`+6M,
splash `0x9d400000`+36M, venus `0x9f800000`+8M, ramoops `0xa0000000`+4M (Nura's, mappable), adsp-region `0xf6000000`+8M,
qseecom `0xf6800000`+20M, gpu `0xfed00000`+10M.

**XNU RAM window: `0x1_00000000`–`0x1_7e4c0000` (1.97 GiB), or from `0xff700000` (2.03 GiB).** This is the largest
contiguous range above every carve-out. sweet and topaz give XNU about 4 GiB; we get about 2 GiB, like an iPhone 8.
The jetsam limits for an iPhone X identity assume 3 GB, so expect memory-pressure kills earlier.
A 6 GB Mi A2 would have a bigger upper bank, so the shim should read `/memory` from the FDT (topaz roadmap item 8).

## Interrupts and timer

- GICv3: distributor `0x17a00000` (64K), redistributors `0x17b00000` (1M region, `redistributor-stride` property present).
- Arch timer 19.2 MHz (virtual timer PPI as on topaz). MMIO timer frame `0x17920000`.

## Display

- ABL continuous splash: `simple-framebuffer` at **`0x9d400000`**, 1080×2160 (`0x438`×`0x870`), stride 4320, `a8r8g8b8`, size `0x8e6200`.
- Panel: `nt36672_tianma_fhd_video` (from ABL's `mdss_mdp.panel=` cmdline): **DSI video mode**, so it keeps scanning the
  framebuffer with no refresh kick, the same as sweet and topaz. Other jasmine units may have a different panel vendor.
- MDSS at `0xc900000`. Aspect is 18:9; iPhone X is 19.5:9 (1125×2436), so the frame has to be scaled or cropped
  (topaz patch 0114 "iPhone X canvas with aligned crop" is the model).

## Storage (all new work: neither port has eMMC)

- eMMC: Hynix `HBG4a2`, 29820 MiB, 8-bit, **HS400 enhanced strobe** at 192 MHz as left by Linux.
- Controller: `qcom,sdm630-sdhci` / `qcom,sdhci-msm-v5` at **`0xc0c4000`** (hc), `0xc0c5000` (cqhci), `0xc0c8000` (ice).
  Standard SDHCI register set with ADMA2 (64-bit) support. Linux device is `mmcblk1`.
- Partitions that matter (512-byte LBAs):

| # | Name | Start LBA | Size | Used by Nura? |
| --- | --- | --- | --- | --- |
| p62 / p63 | boot_a / boot_b | 2097152 / 2228224 | 64 MiB each | boot_a: yes |
| p64 | cache | 2359296 | 256 MiB | no |
| **p65** | **system_a** | **2883584** | **3 GiB** | **no** (stock Android system) |
| **p66** | **system_b** | **9175040** | **3 GiB** | **no** |
| p67 | vendor_a | 15466496 | 2 GiB | **yes** (msm-firmware-loader mounts it read-only) |
| p68 | vendor_b | 19660800 | 2 GiB | no (copy of vendor_a) |
| p69 | userdata | 23855104 | 18.2 GiB | **yes** (Nura rootfs) |

  system_a + system_b are **contiguous: LBA 2883584–15466495, exactly 6 GiB**, and unused by Nura.
  That is the candidate iOS root window for a dual-boot setup (see PLAN.md).

## Input

- Touch: **Novatek NT36672A** (`novatek,nt36672a-ts`) at I²C address `0x01` on **BLSP1 QUP `0xc175000`**
  (`qcom,i2c-qup-v2.2.1`, the older BLSP QUP, *not* GENI like sweet/topaz). Reset = TLMM GPIO 66.
  The IRQ comes through `interrupts-extended` (read it when writing the driver). UniXNU has a Novatek driver
  (NT36532E) whose event-buffer parsing is the same family.
- Power key and volume down: PM660 PON (`pmic@0/pon@800`) over SPMI.
- Volume up: `gpio-keys`, PMIC GPIO 7 (phandle `0x41`, most likely PM660L), code 115.
- SPMI: `qcom,spmi-pmic-arb` at `0x800f000` (core), channels `0x8400000`, observer `0x9400000`, interrupts `0xa400000`,
  config `0x800a000`. This is PMIC arbiter **v3** (SDM660); sweet's key driver is for the v5 arbiter on SM7150, so
  the channel lookup has to be ported.

## Reset, RTC, power

- PS_HOLD restart block: `qcom,pshold` at **`0x10ac000`**. Writing 0 there resets the SoC; this is what panics should do.
- RTC: PM660 `rtc@6000` (Linux `rtc-pm8xxx`), so a real clock is easy (topaz has none yet).
- Fuel gauge `battery@4000` and charger `charger@1000` (PM660). We already know both in detail from the Nura work:
  float voltage, ICL, HC mode and the AICL/THERMREG quirks (`kernel/` patches).
- Watchdog: no APSS watchdog node in the mainline DT. Check in phase 1 whether ABL leaves one running.

## Boot image

- Nura's `boot.img`: Android boot header **v0**, kernel at `0x8000` offset, **gzip Image with appended DTB**.
  So jasmine's ABL accepts a v0 image and `fastboot boot` of one. The shim should be packed the same way
  (sweet uses v2, topaz needed v4 because its ABL dropped v0–v2 ramdisks; ABL behaviour is checked in phase 1).
- ABL cmdline injects `androidboot.*`, `mdss_mdp.panel=` and a dm-verity line; the shim ignores them.

## Radios (later)

- Wi-Fi: WCN3990 with the WLAN firmware on the modem DSP (`mpss@8ac00000`, `mba@94800000`, `wlan-msa-mem@85700000`).
  Same architecture as topaz's WCN3988: topaz patches 0113–0130 (modem PAS boot, GLINK/QRTR, pd-mapper/rmtfs, WLFW,
  HTT/WMI, WPA2) are the template. SDM660 uses **SMD/GLINK over SMEM** and has a different modem firmware layout,
  so it is a port, not a copy. Carry over the TxBF-on-disassociation firmware crash fix we needed in Linux (r109).
- GPU: Adreno 512 (a5xx). No one has an XNU driver for it. Out of scope.
