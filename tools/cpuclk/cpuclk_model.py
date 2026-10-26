#!/usr/bin/env python3
"""
Offline model of both clusters' clock setup on SDM660 / Mi A2,
as the downstream msm-4.4 drivers compute it: speed bin, CPR fuse combo,
per-corner open-loop / floor / ceiling voltages, target quotients, the CPRh
per-corner register words, and the OSM LUT rows the kernel writes.

Inputs: the phone's own stock device tree (decompiled, ~/jasmine-dtb/stock/
dtb0.dts in WSL) and the QFPROM fuse rows (64-bit, fuse_base 0x784000 + 8*row)
as dumped by the j0039 probe (sweetosm=1, lines "SWEET OSM: fuse NN 0x...").

Source: LineageOS android_kernel_xiaomi_sdm660, branch lineage-19.1:
  K = drivers/regulator/cprh-kbss-regulator.c
  U = drivers/regulator/cpr3-util.c
  R = drivers/regulator/cpr3-regulator.c
  O = drivers/clk/qcom/clk-cpu-osm.c
"K:1094" = that file, line 1094. Only the paths the jasmine DT takes are
modelled (no aging, no core-count/temperature bands, no mem-acc threshold:
those DT properties are absent).

Usage:
  cpuclk_model.py DTS FUSES      FUSES: text with "NN 0xVALUE" per row, or a
                                 kernel log with "SWEET OSM: fuse NN 0x..."
  cpuclk_model.py DTS FUSES --cluster both   Gold + Silver (default: gold)
  cpuclk_model.py DTS --zero     synthetic CPR fuses 0, speed bin 1; NOT chip data
"""
import re
import sys
import argparse

STEP = 4000             # qcom,voltage-step (apc1), uV
BASE_VOLT = 400000      # qcom,voltage-base
CPR3_RO_COUNT = 16      # R header
FUSE_STEP = 10000       # K:527 CPRH_KBSS_FUSE_STEP_VOLT
FUSE_SIZE = 6           # K:528 CPRH_KBSS_VOLTAGE_FUSE_SIZE
QUOT_OFFSET_SCALE = 5   # K:529
DELTA_QUOT_STEP = 4     # R:318 CPRH_DELTA_QUOT_STEP_FACTOR
OSM_TABLE_SIZE = 40     # O:86
OSM_SEQ_MINUS_ONE = 0xff

# K:401 kbss_speed_bin_param, K:391 sdm660_cpr_fusing_rev_param
SPEED_BIN = [(38, 29, 31)]
FUSING_REV = [(71, 28, 30)]
# Performance cluster (id 1) rows of the sdm660 tables, fuse corners
# SVS, SVSPLUS, NOM, TURBO, TURBO_L2 (K:120)
RO_SEL = [[(68, 61, 63), (69, 0, 0)], [(69, 1, 4)], [(68, 57, 60)], [(68, 53, 56)], [(66, 14, 17)]]   # K:211
INIT_V = [[(69, 17, 22)], [(69, 23, 28)], [(69, 11, 16)], [(69, 5, 10)], [(70, 42, 47)]]              # K:261
TQUOT = [[(69, 53, 63), (70, 0, 0)], [(70, 1, 12)], [(69, 41, 52)], [(69, 29, 40)], [(70, 48, 59)]]   # K:311
QOFF = [[], [(70, 27, 33)], [(70, 20, 26)], [(70, 13, 19)], [(70, 60, 63), (71, 0, 2)]]              # K:361
REF_VOLT = [724000, 788000, 868000, 988000, 1068000]    # K:490 sdm660 perf
CORNER_NAME = ["SVS", "SVSPLUS", "NOM", "TURBO", "TURBO_L2"]

# K:203/253/303/353/482, SDM660 power cluster (apc0). CPR uses the shared
# speed-bin fuse; this stock DT also maps both OSM efuses to that same row.
CLUSTERS = {
    "gold": dict(node="cprh-ctrl@179c4000", osm="perfcl", names=CORNER_NAME,
                 ro=RO_SEL, init=INIT_V, quot=TQUOT, qoff=QOFF, ref=REF_VOLT),
    "silver": dict(node="cprh-ctrl@179c8000", osm="pwrcl",
                   names=["LowSVS", "SVS", "SVSPLUS", "NOM", "TURBO_L1"],
                   ro=[[(67, 12, 15)], [(67, 8, 11)], [(65, 56, 59)],
                       [(67, 4, 7)], [(67, 0, 3)]],
                   init=[[(67, 34, 39)], [(67, 28, 33)], [(71, 3, 8)],
                         [(67, 22, 27)], [(67, 16, 21)]],
                   quot=[[(68, 12, 23)], [(68, 0, 11)], [(71, 9, 20)],
                         [(67, 52, 63)], [(67, 40, 51)]],
                   qoff=[[], [(68, 38, 44)], [(71, 21, 27)],
                         [(68, 31, 37)], [(68, 24, 30)]],
                   ref=[644000, 724000, 788000, 868000, 1068000]),
}


def required_rows(cluster):
    config = CLUSTERS[cluster]
    segments = SPEED_BIN + FUSING_REV
    for key in ("ro", "init", "quot", "qoff"):
        segments += [part for corner in config[key] for part in corner]
    return {row for row, _, _ in segments}


def cround(n, d):
    """R:857 CPR3_ROUND = DIV_ROUND_UP(n, d) * d (C integer division, n >= 0 here)."""
    return -(-n // d) * d


def div_round_up(n, d):
    return -(-n // d)


def cdiv(a, b):
    """C integer division (truncates toward zero)."""
    q = abs(a) // abs(b)
    return q if (a >= 0) == (b > 0) else -q


def read_param(rows, segs):
    """U:203 cpr3_read_fuse_param: concatenate bit segments, first segment = LSBs."""
    val, total = 0, 0
    for row, lo, hi in segs:
        bits = hi - lo + 1
        if row not in rows:
            raise ValueError("missing fuse row %d; refusing to substitute zero" % row)
        val |= ((rows[row] >> lo) & ((1 << bits) - 1)) << total
        total += bits
    return val


def ol_fuse(ref, step, fuse, size):
    """U:252 cpr3_convert_open_loop_voltage_fuse: MSB = sign, rest = steps."""
    sign = -1 if fuse & (1 << (size - 1)) else 1
    return ref + sign * (fuse & ((1 << (size - 1)) - 1)) * step


def interpolate(x1, y1, x2, y2, x):
    """U:275 cpr3_interpolate (y2 when the inputs are not ordered)."""
    if x1 >= x2 or y1 > y2 or x1 > x or x > x2:
        return y2
    return y2 - ((x2 - x) * (y2 - y1)) // (x2 - x1)


def quot_adjustment(ro_scale, volt_adjust):
    """U:1559 cpr3_quot_adjustment: ro_scale [QUOT/V] * uV / 1e6, toward zero."""
    sign = (-1 if ro_scale < 0 else 1) * (-1 if volt_adjust < 0 else 1)
    return sign * ((abs(ro_scale) * abs(volt_adjust)) // 1000000)


# ---------------------------------------------------------------- DT parsing
def parse_dts_node(text, node_name):
    """Properties of the first node whose name line contains node_name: name -> list of u32 / True."""
    i = text.find(node_name + " {")
    if i < 0:
        raise SystemExit("node %s not found" % node_name)
    depth, j, props = 0, text.index("{", i), {}
    body_start = j + 1
    while True:
        c = text[j]
        if c == "{":
            depth += 1
        elif c == "}":
            depth -= 1
            if depth == 0:
                break
        j += 1
    body = text[body_start:j]
    for m in re.finditer(r"^\s*([\w,#.-]+)\s*(=\s*([^;]*))?;", body, re.M):
        name, val = m.group(1), m.group(3)
        if val is None:
            props.setdefault(name, True)
        elif val.strip().startswith("<"):
            nums = []
            for cell in re.findall(r"<([^>]*)>", val):
                nums += [int(x, 0) & 0xffffffff for x in cell.split()]
            props.setdefault(name, nums)
        else:
            props.setdefault(name, val.strip())
    return props


def s32(v):
    return v - (1 << 32) if v & 0x80000000 else v


# ---------------------------------------------------------------- CPRh (apc1)
class Corner:
    def __init__(self):
        self.freq = 0
        self.fc = 0
        self.floor = self.ceiling = self.open_loop = 0
        self.quot = [0] * CPR3_RO_COUNT
        self.use_open_loop = False


def cprh_model(dt, rows, log, cluster="gold"):
    config = CLUSTERS[cluster]
    missing = required_rows(cluster) - rows.keys()
    if missing:
        raise ValueError("%s: missing fuse rows %s" % (cluster, sorted(missing)))
    speed_bin = read_param(rows, SPEED_BIN)                        # K:916
    rev = read_param(rows, FUSING_REV)                             # K:706
    combo = rev + 8 * speed_bin                                    # K:763
    fuse = {k: [read_param(rows, p[i]) for i in range(5)]
            for k, p in ((key, config[key]) for key in ("init", "quot", "ro", "qoff"))}   # K:716-752
    log("speed bin %d, CPR fusing rev %d, fuse combo %d" % (speed_bin, rev, combo))
    for i in range(5):
        log("  fuse corner %-8s init %#04x  quot %4d  ro %2d  quot_offset %3d"
            % (config["names"][i], fuse["init"][i], fuse["quot"][i], fuse["ro"][i], fuse["qoff"][i]))

    # U:541 cpr3_parse_common_corner_data
    n_fc = dt["qcom,cpr-fuse-corners"][0]
    assert n_fc == 5
    combos = dt["qcom,cpr-fuse-combos"][0]
    bins = dt["qcom,cpr-speed-bins"][0]
    assert combo < combos and speed_bin < bins
    combo_corners = dt["qcom,cpr-corners"]
    if len(combo_corners) == 1:
        combo_corners = combo_corners * combos
    n = combo_corners[combo]
    combo_off, combo_sum = sum(combo_corners[:combo]), sum(combo_corners)
    sb_corners = dt["qcom,cpr-speed-bin-corners"]
    sb_off, sb_sum = sum(sb_corners[:speed_bin]), sum(sb_corners)
    assert sb_corners[speed_bin] == n, "speed-bin corners conflict"

    def corner_array(name):                                        # U:386
        v = dt[name]
        if len(v) == n:
            return v[:n]
        if len(v) == combo_sum:
            return v[combo_off:combo_off + n]
        if len(v) == sb_sum:
            return v[sb_off:sb_off + n]
        raise SystemExit("bad length for " + name)

    def array(name, tuple_size):                                   # U:311
        v = dt[name]
        if len(v) == tuple_size:
            return v[:tuple_size]
        if len(v) == tuple_size * combos:
            return v[tuple_size * combo:tuple_size * (combo + 1)]
        if len(v) == tuple_size * bins:
            return v[tuple_size * speed_bin:tuple_size * (speed_bin + 1)]
        raise SystemExit("bad length for " + name)

    c = [Corner() for _ in range(n)]
    for i, v in enumerate(corner_array("qcom,cpr-voltage-ceiling")):
        c[i].ceiling = cround(v, STEP)                             # U:701
    for i, v in enumerate(corner_array("qcom,cpr-voltage-floor")):
        c[i].floor = cround(v, STEP)                               # U:711
    for i, v in enumerate(corner_array("qcom,corner-frequencies")):
        c[i].freq = v                                              # U:741
    fmax = array("qcom,cpr-corner-fmax-map", n_fc)                 # U:762
    for i in range(n):                                             # U:786
        for j in range(n_fc):
            if i + 1 <= fmax[j]:
                c[i].fc = j
                break
        else:
            c[i].fc = n_fc - 1

    # K:1010 cprh_kbss_calculate_open_loop_voltages
    fv = [ol_fuse(config["ref"][i], FUSE_STEP, fuse["init"][i], FUSE_SIZE) for i in range(5)]   # K:1069
    log("fused open-loop: " + ", ".join("%s %d" % (config["names"][i], fv[i]) for i in range(5)))
    if "qcom,cpr-open-loop-voltage-fuse-adjustment" in dt:        # U:1436
        adj = [s32(x) for x in array("qcom,cpr-open-loop-voltage-fuse-adjustment", n_fc)]
        fv = [fv[i] + adj[i] for i in range(5)]
        log("  + DT open-loop fuse adjustment %s -> %s" % (adj, fv))
    for i in range(1, 5):                                          # K:1094
        if fv[i] < fv[i - 1]:
            fv[i] = fv[i - 1]
    fmax_corner = [0] * n_fc                                       # K:1112
    j = n_fc - 1
    for i in range(n - 1, -1, -1):
        if c[i].fc == j:
            fmax_corner[j] = i
            j -= 1
    assert j < 0, "invalid fuse corner mapping"
    if "qcom,allow-voltage-interpolation" in dt:
        for i in range(fmax_corner[0] + 1):                        # K:1129
            c[i].open_loop = fv[0]
        for i in range(1, n_fc):                                   # K:1133
            for k in range(fmax_corner[i - 1] + 1, fmax_corner[i] + 1):
                c[k].open_loop = interpolate(c[fmax_corner[i - 1]].freq, fv[i - 1],
                                             c[fmax_corner[i]].freq, fv[i], c[k].freq)
    else:
        for x in c:
            x.open_loop = fv[x.fc]
    assert "qcom,cpr-open-loop-voltage-adjustment" not in dt       # U:1483 (absent on jasmine)

    for x in c:                                                    # U:1278 cpr3_limit_open_loop_voltages
        v = cround(x.open_loop, STEP)
        x.open_loop = min(max(v, x.floor), x.ceiling)

    # U:2048 cprh_adjust_voltages_for_apm (controller node properties)
    thr = cround(dt["ctrl"]["qcom,apm-threshold-voltage"][0], STEP)
    hyst = cround(dt["ctrl"].get("qcom,apm-hysteresis-voltage", [0])[0], STEP)
    for i, x in enumerate(c):
        if thr <= x.floor or thr > x.ceiling:
            continue
        if x.open_loop >= thr:
            x.floor = max(x.floor, thr - hyst)
            x.open_loop = max(x.open_loop, x.floor)
        else:
            x.ceiling = thr - STEP
        log("  APM threshold %d changed corner %d" % (thr, i))
    assert "qcom,mem-acc-threshold-voltage" not in dt["ctrl"]     # U:2114 (absent)

    if "qcom,cpr-scaled-open-loop-voltage-as-ceiling" in dt:      # U:1309
        for x in c:
            x.ceiling = x.open_loop

    if "qcom,cpr-floor-to-ceiling-max-range" in dt:               # U:1334
        for x, r in zip(c, corner_array("qcom,cpr-floor-to-ceiling-max-range")):
            if s32(r) >= 0:
                x.floor = max(cround(x.ceiling - r, STEP), x.floor)
                x.open_loop = max(x.open_loop, x.floor)
    for i in range(1, n):                                          # U:1372
        if c[i].floor < c[i - 1].floor:
            c[i].floor = c[i - 1].floor
            c[i].open_loop = max(c[i].open_loop, c[i].floor)
            c[i].ceiling = max(c[i].ceiling, c[i].floor)

    # K:1596 cprh_kbss_calculate_target_quotients (speed bin 3 has no TURBO_L2)
    lowest, highest = 0, 3 if speed_bin == 3 else 4
    ro = fuse["ro"]
    ro_all = array("qcom,cpr-ro-scaling-factor", n_fc * CPR3_RO_COUNT)     # U:1661
    ro_scale = [ro_all[i * CPR3_RO_COUNT + ro[i]] for i in range(n_fc)]
    vaf = [s32(x) for x in array("qcom,cpr-closed-loop-voltage-fuse-adjustment", n_fc)] \
        if "qcom,cpr-closed-loop-voltage-fuse-adjustment" in dt else [0] * n_fc
    assert "qcom,cpr-closed-loop-voltage-adjustment" not in dt     # per-corner: absent
    log("RO scale per fuse corner %s, closed-loop fuse adjustment %s" % (ro_scale, vaf))
    assert "qcom,allow-quotient-interpolation" in dt
    qa = quot_adjustment(ro_scale[lowest], vaf[lowest])            # K:1726
    q = fuse["quot"][lowest] + qa
    qhigh, qlow = [0] * n_fc, [0] * n_fc
    qhigh[lowest] = qlow[lowest] = q
    for i in range(fmax_corner[lowest] + 1):                       # K:1734
        c[i].quot[ro[lowest]] = q
    for i in range(lowest + 1, n_fc):                              # K:1737
        qhigh[i] = fuse["quot"][i]
        qlow[i] = qhigh[i - 1] if ro[i] == ro[i - 1] else qhigh[i] - fuse["qoff"][i] * QUOT_OFFSET_SCALE
        qhigh[i] = max(qhigh[i], qlow[i])
    for i in range(1, n_fc):                                       # K:1754
        qhigh[i] += quot_adjustment(ro_scale[i], vaf[i])
        if ro[i] == ro[i - 1]:
            qlow[i] = qhigh[i - 1]
        else:
            qlow[i] += quot_adjustment(ro_scale[i], vaf[i - 1])
        qhigh[i] = max(qhigh[i], qlow[i])
    for i in range(1, n_fc):                                       # K:1780
        for k in range(fmax_corner[i - 1] + 1, fmax_corner[i] + 1):
            c[k].quot[ro[i]] = interpolate(c[fmax_corner[i - 1]].freq, qlow[i],
                                           c[fmax_corner[i]].freq, qhigh[i], c[k].freq)
    for i in range(1, n):                                          # K:1808
        r = ro[c[i].fc]
        if ro[c[i - 1].fc] == r and c[i].quot[r] < c[i - 1].quot[r]:
            c[i].quot[r] = c[i - 1].quot[r]
    del highest

    # K:1473 cprh_kbss_apm_crossover_as_corner: one extra corner at the APM crossover
    apm_x = dt["ctrl"].get("qcom,apm-crossover-voltage", [0])[0]
    if apm_x:
        x = Corner()
        x.floor = x.ceiling = x.open_loop = apm_x
        x.use_open_loop = True
        c.append(x)
    return dict(speed_bin=speed_bin, rev=rev, combo=combo, corners=c, ro=ro, fuse=fuse)


def cprh_corner_regs(c):
    """R:1057 base quotients (min per RO), R:1100 CPRH_REG_CORNER(i) words (0x3a00 + 4*i)."""
    base = [0] * CPR3_RO_COUNT
    for r in range(CPR3_RO_COUNT):
        qs = [x.quot[r] for x in c if x.quot[r]]
        base[r] = min(qs) if qs else 0
    words = []
    for x in c:
        r = next((k for k in range(CPR3_RO_COUNT) if x.quot[k]), None)
        if r is None:
            assert not x.freq
            r = 0
        olv = div_round_up(x.open_loop - BASE_VOLT, STEP)
        flv = div_round_up(x.floor - BASE_VOLT, STEP)
        dq = div_round_up(x.quot[r] - base[r], DELTA_QUOT_STEP) if x.freq else 0
        assert olv <= 255 and flv <= 255 and dq <= 511
        w = (olv & 0xff) | (flv & 0xff) << 8 | (dq & 0x1ff) << 16 | (r & 0xf) << 25
        if x.use_open_loop:
            w |= 1 << 29                                           # CPRH_CORNER_CPR_CL_DISABLE
        words.append(w)
    return base, words


# ---------------------------------------------------------------- OSM (perfcl)
def osm_model(osm, rows, corners, log, cluster="gold"):
    prefix = CLUSTERS[cluster]["osm"]
    # O:3138/3187/3205: without a named efuse resource use the bin-0 LUT.
    has_efuse = '"%s_efuse"' % prefix in osm["reg-names"]
    if has_efuse:
        resources = re.findall(r'"([^"]+)"', osm["reg-names"])
        index = resources.index(prefix + "_efuse") * 2
        if osm["reg"][index:index + 2] != [0x784130, 8]:
            raise ValueError("unsupported %s efuse mapping" % prefix)
    # O:229/231: both resources use bits 31:29 of their low 32-bit word.
    sb = read_param(rows, SPEED_BIN) if has_efuse else 0
    prop = "qcom,%s-speedbin%d-v0" % (prefix, sb)
    arr = osm[prop]
    assert len(arr) % 5 == 0
    nrows = len(arr) // 5
    log("OSM: %s speed bin %d -> %s, %d rows" % (prefix, sb, prop, nrows))
    table = []
    for j in range(OSM_TABLE_SIZE):                                # O:941 rows past the end repeat the last
        k = min(j, nrows - 1) * 5
        freq, fdata, ovr, spare, vc = arr[k:k + 5]
        table.append(dict(freq=freq, fdata=fdata, ovr=ovr, spare=spare, vc=vc - 1))
    n_corners = len(corners)                                       # regulator_count_voltages
    for e in table:                                                # O:1582: ceiling of corner vc+1, mV
        e["olv"] = corners[e["vc"]].ceiling // 1000
    # O:1598 clk_osm_resolve_crossover_corners (no perfcl mem-acc threshold in the DT)
    apm_thr = osm["qcom,apm-threshold-voltage"][0]
    assert "qcom,perfcl-apcs-mem-acc-threshold-voltage" not in osm
    apm_crossover_vc = n_corners - 1
    apm_threshold_vc, apm_pre = 0, 0
    for e in table:
        if corners[e["vc"]].ceiling >= apm_thr:
            apm_threshold_vc = e["vc"]
            apm_pre = apm_threshold_vc - 1 if apm_threshold_vc else OSM_SEQ_MINUS_ONE
            break
    if not apm_threshold_vc and apm_pre != OSM_SEQ_MINUS_ONE:
        apm_threshold_vc = OSM_TABLE_SIZE - 1
        apm_pre = apm_threshold_vc - 1
    # O:2001 clk_osm_program_mem_acc_regs, non-secure (TZ) path
    level_map, cur, j = [0, 0, 0], table[0]["spare"], 0
    for e in table[:nrows]:
        if cur == 3:
            break
        if e["spare"] != cur:
            level_map[j] = e["vc"] - 1
            j += 1
            cur = e["spare"]
    mem_thr = [level_map[0], level_map[0] + 1, level_map[1], level_map[1] + 1]
    l_lvl3 = None
    for e in table[:nrows]:
        if mem_thr[3] == e["vc"]:
            l_lvl3 = e["fdata"] & 0xff
    return dict(sb=sb, nrows=nrows, table=table, apm_threshold_vc=apm_threshold_vc, apm_pre_vc=apm_pre,
                apm_crossover_vc=apm_crossover_vc, mem_acc_vc=mem_thr, seq32_lval=l_lvl3)


def parse_fuses(path):
    rows = {}
    for line in open(path, encoding="utf-8", errors="replace"):
        m = re.search(r"SWEET OSM: fuse (\d+) (0x[0-9a-fA-F]+)", line) or \
            re.match(r"\s*(\d+)\s+(0x[0-9a-fA-F]+)\s*$", line)
        if m:
            row, value = int(m.group(1)), int(m.group(2), 16)
            if value >= 1 << 64:
                raise ValueError("fuse row %d exceeds 64 bits" % row)
            if row in rows and rows[row] != value:
                raise ValueError("conflicting values for fuse row %d" % row)
            rows[row] = value
    return rows


def report_cluster(text, rows, cluster):
    config = CLUSTERS[cluster]
    ctrl = parse_dts_node(text, config["node"])
    vreg = parse_dts_node(text[text.find(config["node"]):], "regulator")
    vreg["ctrl"] = ctrl
    osm = parse_dts_node(text, "qcom,clk-cpu-660@179c0000")
    m = cprh_model(vreg, rows, print, cluster)
    c = m["corners"]
    base, words = cprh_corner_regs(c)
    print("\nCPRh %s corners (uV); last = APM crossover corner" % ("apc1" if cluster == "gold" else "apc0"))
    print(" vc   freq MHz  fc   floor  open-loop  ceiling   RO  quot   CPRH_REG_CORNER")
    for i, x in enumerate(c):
        r = next((k for k in range(CPR3_RO_COUNT) if x.quot[k]), 0)
        print(" %2d  %8.1f  %2s  %7d  %7d  %7d   %2d  %4d   %#010x"
              % (i, x.freq / 1e6, x.fc if x.freq else "-", x.floor, x.open_loop, x.ceiling, r, x.quot[r], words[i]))
    print(" base target quotients per RO: %s" % base)
    o = osm_model(osm, rows, c, print, cluster)
    print("\nOSM %s LUT (rows %d..39 repeat row %d)" % (config["osm"], o["nrows"], o["nrows"] - 1))
    print(" idx  freq MHz  src div cores  L    vc  OLV mV  spare  FREQ_REG    VOLT_REG    OVERRIDE")
    for i, e in enumerate(o["table"][:o["nrows"]]):
        fd = e["fdata"]
        volt = (e["vc"] & 0x3f) << 16 | (e["olv"] & 0xfff)
        print(" %2d   %7.1f   %d   %d    %d   %#04x  %2d   %4d    %d     %#010x  %#010x  %#010x"
              % (i, e["freq"] / 1e6, fd >> 26 & 3, fd >> 24 & 3, fd >> 16 & 7, fd & 0xff, e["vc"], e["olv"],
                 e["spare"], fd, volt, e["ovr"]))
    print(" APM threshold vc %d (pre %d), APM crossover vc %d; MEM-ACC threshold vcs %s, SEQ_REG(32) L %#x"
          % (o["apm_threshold_vc"], o["apm_pre_vc"], o["apm_crossover_vc"], o["mem_acc_vc"], o["seq32_lval"] or 0))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("dts")
    parser.add_argument("fuses", nargs="?")
    parser.add_argument("--zero", action="store_true", help="synthetic sanity input, NOT chip data")
    parser.add_argument("--cluster", choices=("gold", "silver", "both"), default="gold")
    args = parser.parse_args()
    if bool(args.fuses) == args.zero:
        parser.error("provide exactly one of FUSES or --zero")
    clusters = ("gold", "silver") if args.cluster == "both" else (args.cluster,)
    text = open(args.dts, encoding="utf-8-sig").read()
    if args.zero:
        print("SYNTHETIC ZERO-FUSE SANITY RUN: not a voltage table for this chip")
        rows = {row: 0 for cluster in clusters for row in required_rows(cluster)}
        rows[38] = 0x88614230_3040008c
    else:
        rows = parse_fuses(args.fuses)
    # Validate all requested inputs before printing any candidate tables.
    for cluster in clusters:
        missing = required_rows(cluster) - rows.keys()
        if missing:
            raise ValueError("%s: missing fuse rows %s" % (cluster, sorted(missing)))
    for cluster in clusters:
        if args.cluster == "both":
            print("\n=== %s ===" % cluster.upper())
        report_cluster(text, rows, cluster)


if __name__ == "__main__":
    try:
        main()
    except (ValueError, KeyError) as exc:
        sys.exit("cpuclk model: %s" % exc)
