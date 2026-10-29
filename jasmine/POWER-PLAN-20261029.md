# Battery drain plan (2026-10-29)

Rule from the user: **no performance trade-offs.** Nothing here lowers a clock under load; every item
saves power only while the hardware is idle, and every item is gated by a framebench before/after
comparison (no regression). DDR stays at 1804 MHz whenever there is work: the phone is DDR-bound
(PERF-BOTTLENECK-20261028.md).

## Starting point (observations)

- Installed boot_b = j0113. Boot-args include `sweetddr=1804 gpumhz=588 sweetdvfs=1 sweetdvfsauto=1
  sweetfb_hz=30` (logs/netlog-j0113d-wall.txt).
- Battery current from the PM660 fuel gauge, only logged at charger plug/unplug events (`SWEET CHG:`):
  screen off, unplugged: **-437 mA at 3.88 V (~1.7 W)**; screen on, idle: -448 to -580 mA; moving UI
  -757 to -893 mA. Single samples. Backlight off saves little: the platform floor dominates.
  ~440 mA = ~7 h standby on 3000 mAh.
- Screen-off CPU load (`SWEET CLPC: 10 s`): Gold ~2.6 s, Silver ~1.7 s of CPU per 10 s. Three
  kernel_task threads (tids 158, 174, 221) at ~3 % of a core each, always.
- DDR fixed at 1804 MHz and the RPM buses at their maximum (PERF-TASKS.md "Power and heat").
- GPU at 588 MHz (NOM CX), no idle power-down, no hardware clock gating; GX off exists in j0018 only
  for error/reset.
- CPU idle is WFI only; DVFS governor (j0104/j0107) is on.
- Display off on jasmine logs only `backlight off (WLED 0)` + `display off`; whether MDP/DSI keep
  scanning at 30 Hz is **not verified** (guess: they do).
- Wi-Fi not associated scans every ~11 s forever (36 scans in 400 s, `TopazModem: *** scan N done`).
- Touch polled at 100 Hz over I2C (j0006), keys every 20 ms (j0005), screen on or off.
- USB30_PRIM GDSC and the 7 USB clocks stay on (ABL leaves them on).

## Step 0: make it measurable

- Periodic fuel-gauge current/voltage log (e.g. every 30 s, averaged) and/or a command-port `batt` command.
- Fixed protocol: unplugged, screen off, 5 min; and screen on idle on Home, 5 min.
- framebench baseline (FRAMEBENCH.md) on the same build, to compare every item against.

## Ranked by estimated saving (screen off; estimates, not measurements)

1. **DDR and bus scaling, ~50-120 mA.** Governor on the j0064 counters (CPU bwmon4, GPU VBIF) that votes
   bimc and the RPM bus clocks. Full rate (1804) immediately on display/GPU activity, touch and GPU
   submit, so a frame never starts on a low rate; step down only after a real idle gap or with the
   display off. Model: Linux bw_hwmon + cpubw/gpubw votes, biased to full rate. Keep >=1296 rule in mind
   (RPM scaling on without a bimc vote costs 20-60 %, GPU.md).
2. **GPU idle power-down + hardware clock gating, ~40-100 mA.** Clock gating (no speed cost); GX
   collapse after a few ms idle and always with the display off, fast power-up so the first submit does
   not stall; release the CX vote while off. Optional GPU DVFS: 588 whenever busy.
3. **CPU power collapse (PSCI CPU_SUSPEND, core then cluster), ~30-80 mA.** Latency-aware state choice
   (deep state only when the expected idle covers its residency), so short idles stay in WFI.
4. **System sleep (XO shutdown / VDD min), ~50-100 mA more.** RPM sleep-set votes so the SoC reaches
   Android-like standby with the screen off. Depends on 1-3 and 5-8.
5. **Display pipeline off with the screen, ~15-40 mA.** Stop the MDP timing engine and DSI, panel sleep-in
   (DCS 0x28/0x10), clean resume. Also lets item 1 really idle.
6. **Wi-Fi, ~20-40 mA.** Firmware PNO / scan back-off while unassociated and the screen is off; screen-on
   behaviour unchanged. `modem=0` A/B shows whether MPSS spends power on a cellular search.
7. **Touch and keys interrupt-driven, ~10-25 mA.** Touch IRQ GPIO and PON interrupts instead of polling
   (lower touch latency too); touch IC sleep with the screen off. Removes wakeups that block item 3.
8. **USB controller off when unplugged, ~5-15 mA.** GDSC + clocks off, back on at PMIC VBUS detect;
   keep j0113's replug behaviour.
9. **Always-busy kernel threads, a few mA now, more after item 3.** Identify tids 158/174/221; several
   likely go with item 7.
