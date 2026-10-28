# Task 16 mode 2 on the current kernel (2026-10-28)

The pipelined presentation from task 16 ([plan](PERF-TASK16-PLAN.md)) ported onto the current
kernel and measured against the same kernel with it off. Motivation: the
[bottleneck report](PERF-BOTTLENECK-20261028.md) showed the GPU idle ~9-12 ms per frame while
CoreAnimation records the next frame (mode 0 waits for each frame's GPU work in `glFinish`).
Since Home's GPU work fell to ~27 ms/frame, that bubble is what pushes frames past 33 ms.

## Port

- Kernel: the four `t16-build1` commits (j0100 present queue, j0100b, j0100c, j0101 render
  tickets; written on j0099) cherry-picked without conflicts onto the j0108 series and exported
  as `xnu/patches/j0109-jasmine-present-queue.patch`, `j0109b-...swapend-never-fails`,
  `j0109c-...present-sleep-on-time`, `j0110-jasmine-render-tickets.patch` (commit fb9e470).
  Everything is gated by `sweetfb_sleep=1 sweetfb_queue=1 sweetgpu_tickets=1`; without them
  the kernel behaves as before. CI now checks that both patches are in the built source.
- CI 40609825244 failed only in the host test `tools/cpuclk/surface-release-test.py`
  (j0106's harness compiles the real `trapRelease`, which now ends a view's write
  reservations). Harness updated and extended (commit after fb9e470). CI **40611111142 PASS**,
  kernel SHA256 `02b946d9ff3be77d77ba3757844839122a70fc148ed3c0d4aafcc901b24c6e61`
  (`xnu/out-jasmine-j0110/`).
- Mesa: no change. Mode 2 (`SWEETCA_PIPELINE=2`) has been in libsweetca since de632aa; the
  production library 4780fbaa was used as installed.

## A/B (same kernel, same library, consecutive temporary boots)

Images (args = installed boot_b minus `abmark=b`): `shim/out/shim-boot-j0110-m0.img`
(SHA256 40b81fab...) and `shim/out/shim-boot-j0110-m2.img` (a91cb73d..., adds the three
boot-args and `SWEETCA_PIPELINE=2` in sweetenv). `tools/g2/abround.py`: boot, unlock, 150 s
settle, one standard framebench capture. CPU auto, GPU 588, DDR 1804 on both (read back).

| Phase | Mode 0 rate, median / p95 ms | Mode 2 rate, median / p95 ms | Rate change |
| --- | ---: | ---: | ---: |
| Home B | 27.12/s, 35.5 / 47.3 | **33.06/s, 29.2 / 42.8** | **+22%** |
| Control A | 21.70/s, 45.9 / 62.1 | 23.18/s, 40.8 / 67.2 | +7% |
| Control B | 22.01/s, 46.0 / 62.9 | 22.95/s, 40.5 / 62.3 | +4% |
| Spotlight repeat | 20.35/s, 45.0 / 55.2 | 25.59/s, 34.8 / 53.1 | +26% |

Mode 0 on j0110 equals the installed j0108 kernel (Home B 26.3-27.1/s, CC 22.0-22.7/s earlier
the same night): the port is inert when off.

Frame intervals in 16.7 ms periods (1 / 2 / 3 / 4+):

| Phase | Mode 0 | Mode 2 |
| --- | --- | --- |
| Home B | 0 / 243 / 50 / 1 | **69** / 278 / 17 / 1 |
| Control B | 2 / 109 / 85 / 21 | 1 / 133 / 76 / 18 |

Health on the mode-2 boot (`logs/netlog-j0110-m2.txt`, `research/ab/j0110-m2/`): mode 2 stayed
on (no `ticket/submit error` / fallback lines); 1239 BEGIN = 1239 SEAL, 1150 admitted = 1150
flipped, 0 cancels/aborts, guard attempts 911 with 0 rejected, 0 ticket-wait errors; queue
high-water 1. No GPU write waits for the panel (they become the 1.8-3.0 s of SwapWait
sleeping per phase). No SMMU fault or panic (only the usual boot-time lines). Screen dumps
`research/ab/j0110-m2/shot.{2,4,8}.png`: home screen correct; CA now cycles three surfaces.

## Installed (2026-10-28 02:50)

User OK, battery 32%. boot_b = `research/t16port/j0110-mode2-slotb.img` (SHA256 9096026c..., the m2 args plus
`abmark=b`). Backup of the previous boot_b and both GPT copies first; exact readback, boot_a and GPT checks PASS
(only boot_b's slot attributes changed). Normal boot: mode 2 on (tickets 1212/1211/0 aborts, no errors), slot marked
successful, home screen correct. Rollback: `fastboot flash boot_b research/t16port/install-backup/boot_b-before.img`.

## Still open

- The user's look at motion on the phone (Oct 25 mode 2 "looks right"; not re-checked today).
- Control Center A p95 got worse (62 -> 67 ms); B unchanged. One capture each; not significant.
- A longer session (task 14 freeze history): only ~10 minutes of mode 2 so far today.
