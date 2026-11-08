"""POCO X3 Pro (vayu) for tools/jasmine-charger.pyw: what the phone's charger chip says, read under iOS.

Everything here is READ ONLY. The phone's iOS (ios-vayu) answers through sweetd (TCP 5143, the token in
ios-vayu/userland/sweetd.token) with sysctls:
  kern.hakios.battery_*   the battery driver's fuel-gauge numbers (current > 0 while charging)
  kern.hakios.charger_regs / fg_regs   whole register blocks of the PM8150B (ios-vayu drivers/power/
                          hakios.battery.c, from kernel 67518d8b on): "BBBB:" + 256 registers as hex per line
A kernel without the register sysctls still gives the battery numbers; the charger then comes from nothing.

Register meanings: Xiaomi's vayu kernel (MiCode/Xiaomi_Kernel_OpenSource, vayu-r-oss) smb5-reg.h for the
addresses and bits, qpnp-smb5.c smb5_pm8150b_params for the scales (FCC/ICL 50 mA a step, float voltage
3600 mV + 10 mV a step) and smb5_irqs for the order of each block's interrupt bits (INT_RT_STS, offset 0x10).
"""
import os
import pathlib
import socket

VAYU_REPO = pathlib.Path(os.environ.get('VAYU_REPO', r'C:\Users\teleg\Documents\Code\Poco X3 Pro\ios-vayu'))
TOKEN = VAYU_REPO / 'userland' / 'sweetd.token'
HOSTS = ('169.254.7.2', '192.168.7.2')
PORT = 5143
END = b'__SWEETD_END__'

BATTERY_SYSCTLS = ('battery_soc', 'battery_voltage_mv', 'battery_current_ma', 'battery_temperature_c',
                   'battery_present', 'battery_charger_present', 'battery_charging', 'battery_soc_estimated',
                   'battery_charger_action', 'battery_full_uah', 'battery_design_uah', 'battery_cycles')


# --- sweetd ----------------------------------------------------------------------------------------
def sweetd(args, timeout=8):
    """Run a sweetd built-in or program; its output, or None when no vayu sweetd answers."""
    try:
        token = TOKEN.read_text().strip()
    except OSError:
        return None
    for host in HOSTS:
        try:
            s = socket.create_connection((host, PORT), timeout=1.5)
        except OSError:
            continue
        with s:
            s.settimeout(timeout)
            s.sendall(f'RUN {token} {timeout} {len(args)}\n'.encode() + b''.join(a.encode() + b'\n' for a in args))
            buf = b''
            try:
                while True:
                    chunk = s.recv(65536)
                    if not chunk:
                        break
                    buf += chunk
            except socket.timeout:
                pass
        cut = buf.rfind(b'\n' + END)
        return (buf[:cut] if cut >= 0 else buf).decode(errors='replace')
    return None


def read_all():
    """One poll: {'sysctl': {...}, 'charger': {addr: byte}, 'fg': {...}}, or None (not a vayu)."""
    names = [f'kern.hakios.{n}' for n in BATTERY_SYSCTLS] + ['kern.hakios.charger_regs', 'kern.hakios.fg_regs',
                                                              'kern.boottime', 'kern.version']
    out = sweetd(['sysctl', *names])
    if out is None or 'kern.hakios.battery_soc:' not in out:
        return None
    data = {'sysctl': {}, 'regs': {}, 'raw': {}}
    current = None
    for line in out.splitlines():
        if line.startswith('kern.') and ': ' in line:
            key, val = line.split(': ', 1)
            current = key
            if key in ('kern.hakios.charger_regs', 'kern.hakios.fg_regs'):
                line = val
            else:
                data['sysctl'][key.removeprefix('kern.hakios.')] = val.strip()
                continue
        if current in ('kern.hakios.charger_regs', 'kern.hakios.fg_regs') and len(line) > 5 and line[4] == ':':
            base = int(line[:4], 16)
            hexes = line[5:].strip()
            data['raw'][base] = hexes
            for i in range(min(256, len(hexes) // 2)):
                pair = hexes[2 * i:2 * i + 2]
                if pair != '--':
                    data['regs'][base + i] = int(pair, 16)
    return data


# --- decoding --------------------------------------------------------------------------------------
CHG_STATES = ['inhibited', 'trickle', 'pre-charge', 'full-on (fast)', 'taper (topping off)',
              'terminated (full)', 'paused', 'disabled']
APSD_BITS = [(0, 'SDP: plain USB port (500 mA)'), (1, 'OCP: other charging port'),
             (2, 'CDP: PC charging port (1.5 A)'), (3, 'DCP: wall charger'),
             (4, 'float: data pins not connected'), (5, 'QC 2.0 charger'), (6, 'QC 3.0 charger')]
APSD_SHORT = {0: 'Plain USB port (SDP)', 1: 'Other charging port (OCP)', 2: 'PC charging port (CDP)',
              3: 'Wall charger (DCP)', 4: 'Data pins floating (float)', 5: 'Quick Charge 2.0', 6: 'Quick Charge 3.0'}
APSD_LIMIT = {0: 500, 1: 1500, 2: 1500, 3: 1500, 4: 500, 5: 3000, 6: 3000}
IRQS = {
    0x1010: ['chgr-error', 'chg-state-change', 'step-chg-state-change', 'step-chg-soc-update-fail',
             'step-chg-soc-update-req', 'fg-fvcal-qualified', 'vph-alarm', 'vph-drop-prechg'],
    0x1110: ['otg-fail', 'otg-oc-disable-sw', 'otg-oc-hiccup', 'bsm-active', 'high-duty-cycle',
             'input-current-limiting', 'concurrent-mode-disable', 'switcher-power-ok'],
    0x1210: ['bat-temp', 'all-chnl-conv-done', 'bat-ov', 'bat-low', 'bat-therm-or-id-missing',
             'bat-terminal-missing', 'buck-oc', 'vph-ov'],
    0x1310: ['usbin-collapse', 'usbin-vashdn', 'usbin-uv', 'usbin-ov', 'usbin-plugin', 'usbin-revi-change',
             'usbin-src-change', 'usbin-icl-change'],
    0x1410: ['(bit 0)', 'dcin-vashdn', 'dcin-uv', 'dcin-ov', 'dcin-plugin', 'dcin-revi', 'dcin-pon', 'dcin-en'],
    0x1510: ['typec-or-rid-detect-change', 'typec-vpd-detect', 'typec-cc-state-change', 'typec-vconn-oc',
             'typec-vbus-change', 'typec-attach-detach', 'typec-legacy-cable-detect', 'typec-try-snk-src-detect'],
    0x1610: ['wdog-snarl', 'wdog-bark', 'aicl-fail', 'aicl-done', 'smb-en', 'imp-trigger', 'temp-change',
             'temp-change-smb'],
}
BLOCK_NAMES = {0x1000: 'CHGR (charger)', 0x1100: 'DCDC (buck, input limits)', 0x1200: 'BATIF (battery interface)',
               0x1300: 'USBIN (USB input, detection)', 0x1400: 'DCIN (wireless/DC input)', 0x1500: 'TYPEC (USB-C)',
               0x1600: 'MISC (temps, watchdog, AICL)', 0x4000: 'FG BATT_SOC', 0x4100: 'FG BATT_INFO',
               0x4200: 'FG RRADC'}


def bits(v, table):
    return [name for b, name in table if v is not None and v >> b & 1]


def bitnames(v, names):
    return [names[b] for b in range(8) if v is not None and v >> b & 1]


def ma50(v):
    return None if v is None else v * 50


def decode(d):
    """The poll as {'summary': [...], 'warnings': [...], 'verdict': str, 'sections': [(title, [lines])]}."""
    r = d['regs'].get
    sc = d['sysctl']
    have = bool(d['regs'])
    res = {'have_regs': have, 'summary': [], 'warnings': [], 'verdict': '', 'sections': []}

    def num(key):
        try:
            return int(sc.get(key, ''))
        except ValueError:
            return None

    res['mv'], res['ma'], res['soc'], res['temp'] = (num('battery_voltage_mv'), num('battery_current_ma'),
                                                     num('battery_soc'), num('battery_temperature_c'))
    plugged = num('battery_charger_present')
    charging = num('battery_charging')

    if not have:
        res['summary'].append('Charger registers: not in this kernel (needs kern.hakios.charger_regs, kernel 67518d8b+).')
        res['summary'].append('Charger: ' + ('charging' if charging else 'plugged, not charging' if plugged
                                             else 'unplugged'))
        res['sections'].append(('Battery driver', [f'{k} = {v}' for k, v in sc.items()]))
        return res

    st1, st2, st7 = r(0x1006), r(0x1007), r(0x100D)
    apsd_sts, apsd, qc = r(0x1307), r(0x1308), r(0x1309)
    icl_set, icl_max, icl_now, aicl_icl = ma50(r(0x1370)), ma50(r(0x1106)), ma50(r(0x1107)), ma50(r(0x1108))
    fcc = ma50(r(0x1061))
    fv = None if r(0x1070) is None else 3600 + 10 * r(0x1070)
    aicl, ppath = r(0x110A), r(0x110B)
    snk, typec_misc, legacy = r(0x1506), r(0x150B), r(0x150D)
    usbin_rt = r(0x1310)
    in_plug = usbin_rt is not None and usbin_rt >> 4 & 1

    # --- the important part --------------------------------------------------------------------
    state = CHG_STATES[st1 & 7] if st1 is not None else '?'
    res['summary'].append(f'Charger state: {state}' + ('' if in_plug else '  (no USB power in)'))
    kinds = [APSD_SHORT[b] for b in range(7) if apsd is not None and apsd >> b & 1]
    if in_plug:
        res['summary'].append('Plugged into: ' + (', '.join(kinds) if kinds else
                                                  'not detected yet' if apsd == 0 else f'? ({apsd:#x})'))
        rp = ('3.0 A' if snk is not None and snk & 0x02 else '1.5 A' if snk is not None and snk & 0x04 else
              'default USB (0.5/0.9 A)' if snk is not None and snk & 0x08 else 'nothing (no Rp)')
        res['summary'].append(f'USB-C pins advertise: {rp}')
        res['summary'].append(f'Input limit: {icl_set} mA set, {icl_max} mA allowed, {icl_now} mA in use'
                              f' (AICL settled at {aicl_icl} mA)')
    res['summary'].append(f'Battery limits: charge current {fcc} mA, full at {fv} mV')

    # the verdict: what holds the input back
    limit = min(x for x in (icl_set, icl_max, icl_now) if x is not None) if in_plug else None
    if not in_plug:
        res['verdict'] = 'No USB power coming in.'
    elif ppath is not None and ppath & 0x40:
        res['verdict'] = 'USB input is SUSPENDED: the chip takes nothing from the cable.'
    elif apsd is not None and apsd & 0x11 and limit is not None and limit <= 500:
        typec_a = 3000 if snk and snk & 0x02 else 1500 if snk and snk & 0x04 else None
        res['verdict'] = ('Stuck at 500 mA (2-2.5 W) because the data-pin check (BC1.2) found a '
                          + ('plain USB port' if apsd & 1 else 'floating data line') + '.'
                          + (f' The USB-C pins say {typec_a / 1000:.1f} A is allowed, so the port itself could do more:'
                             ' the D+/D- detection is what failed (cable/meter data wires, or the port\'s data pins).'
                             if typec_a else ''))
    elif aicl_icl is not None and icl_max is not None and aicl_icl < icl_max - 50:
        res['verdict'] = (f'Input current is being cut by AICL to {aicl_icl} mA (allowed {icl_max} mA): '
                          'the input voltage sags under load (weak charger, long/thin cable, or meter resistance).')
    elif st1 is not None and (st1 & 7) in (0, 6, 7) and in_plug:
        res['verdict'] = f'Charging is {state} (not the cable): see Temps & protections.'
    elif limit is not None:
        res['verdict'] = f'Input allowed up to {limit} mA ({limit * 5 / 1000:.1f} W at 5 V). No obvious limiter.'

    w = res['warnings']
    if in_plug and st1 is not None and (st1 & 7) in (0, 6, 7):
        en = r(0x1042)
        w.append(f'charging is {state} although USB power is in'
                 + (' (CHARGING_ENABLE_CMD is off)' if en is not None and not en & 1 else '')
                 + ': the battery is only fed if the phone uses less than the input')
    if typec_misc is not None and typec_misc & 0x80:
        w.append('USB-C port reports WATER/moisture detected')
    if typec_misc is not None and typec_misc & 0x10:
        w.append('USB-C VBUS error')
    if usbin_rt is not None:
        for b, txt in ((0, 'USB input collapsed (voltage dropped under load)'), (2, 'USB input under-voltage'),
                       (3, 'USB input over-voltage'), (1, 'USB input VASHDN (voltage too low to run)')):
            if usbin_rt >> b & 1:
                w.append(txt)
    if st2 is not None and st2 & 0x02:
        w.append('Battery over-voltage error')
    if st7 is not None:
        for b, txt in ((5, 'battery warm: JEITA soft limit (charging reduced)'),
                       (4, 'battery cool: JEITA soft limit (charging reduced)'),
                       (3, 'battery TOO HOT: charging stopped'), (2, 'battery TOO COLD: charging stopped')):
            if st7 >> b & 1:
                w.append(txt)
    trs = r(0x1606)
    if trs is not None and trs & 0x40:
        w.append('thermal regulation active (charger reducing current for heat)')
    for reg, what in ((0x1607, 'charger die'), (0x1608, 'skin'), (0x1609, 'USB connector'), (0x160A, 'SMB')):
        v = r(reg)
        if v is not None and v & 0x0E:
            w.append(f'{what} temperature over its limit ({", ".join(n for b, n in ((3, "shutdown"), (2, "reset"), (1, "upper bound")) if v >> b & 1)})')
    if aicl is not None and aicl & 0x40:
        w.append('soft input current limit active (AICL)')
    if r(0x1610) is not None and r(0x1610) & 0x04:
        w.append('AICL failed')
    if legacy is not None and legacy & 0x01:
        w.append('non-compliant legacy cable detected')

    # --- details --------------------------------------------------------------------------------
    def hx(a):
        v = r(a)
        return '--' if v is None else f'{v:#04x}'

    sec = res['sections']
    sec.append(('Charger', [
        f'BATTERY_CHARGER_STATUS_1 {hx(0x1006)}: {state}' + ''.join(f', bit {b}' for b in range(3, 8) if st1 is not None and st1 >> b & 1),
        f'STATUS_2 {hx(0x1007)}' + (' (battery OV)' if st2 is not None and st2 & 2 else ''),
        f'STATUS_5 {hx(0x100B)}: ' + ', '.join(bits(r(0x100B), [(0, 'full-on enabled'), (1, 'pre-charge enabled'), (2, 'trickle enabled')]) or ['-']),
        f'STATUS_7 {hx(0x100D)}: ' + ', '.join(bits(st7, [(5, 'hot soft'), (4, 'cold soft'), (3, 'too hot'), (2, 'too cold'), (1, 'too hot (AFP)'), (0, 'too cold (AFP)')]) or ['temps ok']),
        f'CHARGING_ENABLE_CMD {hx(0x1042)}, PAUSE_CMD {hx(0x1043)}, CHGR_CFG2 {hx(0x1051)}',
        f'Fast charge current (FCC) {hx(0x1061)} = {fcc} mA',
        f'Float voltage (FV) {hx(0x1070)} = {fv} mV',
        f'Inhibit threshold {hx(0x1072)}, recharge SOC {hx(0x107D)}',
        f'JEITA enable {hx(0x1090)}, safety timer {hx(0x10A2)}',
        'CHGR interrupts now: ' + (', '.join(bitnames(r(0x1010), IRQS[0x1010])) or 'none'),
    ]))
    sec.append(('Input & detection', [
        'USBIN interrupts now: ' + (', '.join(bitnames(usbin_rt, IRQS[0x1310])) or 'none'),
        f'APSD status {hx(0x1307)}: ' + (', '.join(bits(apsd_sts, [(0, 'detection done'), (1, 'QC charger'), (2, 'QC auth done'), (3, 'VADP change done'), (4, 'enumeration done'), (5, 'slow plug-in timeout'), (6, 'HVDCP check timeout'), (7, 'bit7')])) or '-'),
        f'APSD result {hx(0x1308)}: ' + (', '.join(bits(apsd, APSD_BITS)) or 'nothing'),
        f'QC voltage {hx(0x1309)}: ' + (', '.join(bits(qc, [(0, '5 V'), (1, '9 V'), (2, '12 V')])) or '-'),
        f'USB input current limit set {hx(0x1370)} = {icl_set} mA',
        f'ICL max {hx(0x1106)} = {icl_max} mA, ICL in use {hx(0x1107)} = {icl_now} mA, AICL result {hx(0x1108)} = {aicl_icl} mA',
        f'AICL status {hx(0x110A)}: ' + (', '.join(bits(aicl, [(0, 'done'), (6, 'soft limit')])) or '-'),
        f'Power path {hx(0x110B)}: ' + (', '.join(bits(ppath, [(0, 'valid input'), (3, 'using DCIN'), (4, 'using USBIN'), (6, 'USBIN SUSPENDED')])) or '-'),
        f'USBIN suspend cmd {hx(0x1340)}, ICL override cmd {hx(0x1342)}, HVDCP cmd {hx(0x1343)}',
        f'Adapter allow {hx(0x1360)}, options 1 {hx(0x1362)}: ' + (', '.join(bits(r(0x1362), [(2, 'HVDCP enabled'), (3, 'BC1.2 detect'), (5, 'HVDCP autonomous'), (6, 'HVDCP auth')])) or '-'),
        f'Options 2 {hx(0x1363)}: ' + (', '.join(bits(r(0x1363), [(0, 'float -> SDP'), (1, 'suspend on float'), (2, 'no charging on float'), (5, 'DCD timeout')])) or '-'),
        f'Load cfg {hx(0x1365)}, ICL options {hx(0x1366)}: ' + (', '.join(bits(r(0x1366), [(0, 'high-current mode'), (1, 'USB51 500 mA'), (2, 'USB 3.0')])) or '-'),
        f'AICL options {hx(0x1380)}: ' + (', '.join(bits(r(0x1380), [(2, 'AICL on'), (3, 'AICL ADC'), (4, 'periodic rerun'), (7, 'suspend on collapse')])) or '-'),
        f'Type-C cfg {hx(0x1358)}' + (' (BC1.2 starts on CC)' if r(0x1358) is not None and r(0x1358) & 0x80 else ''),
        'DCIN interrupts now: ' + (', '.join(bitnames(r(0x1410), IRQS[0x1410])) or 'none'),
    ]))
    sec.append(('USB-C', [
        'TYPEC interrupts now: ' + (', '.join(bitnames(r(0x1510), IRQS[0x1510])) or 'none'),
        f'Sink status {hx(0x1506)}: ' + (', '.join(bits(snk, [(0, 'Rp short'), (1, 'Rp 3.0 A'), (2, 'Rp 1.5 A'), (3, 'Rp default'), (4, 'debug acc. 3 A'), (5, 'debug acc. 1.5 A'), (6, 'debug acc. 500 mA')])) or 'no source'),
        f'Source status {hx(0x1508)}, state machine {hx(0x1509)}' + (' (attached)' if r(0x1509) is not None and r(0x1509) & 0x20 else ''),
        f'Misc status {hx(0x150B)}: ' + (', '.join(bits(typec_misc, [(0, 'CC attached'), (1, 'CC2 orientation'), (3, 'debounce done'), (4, 'VBUS error'), (6, 'source mode'), (7, 'WATER detected')])) or '-'),
        f'Legacy cable {hx(0x150D)}: ' + (', '.join(bits(legacy, [(0, 'non-compliant legacy'), (1, 'legacy')])) or 'no'),
        f'Micro-USB status {hx(0x150F)}, mode cfg {hx(0x1544)}, VCONN {hx(0x1546)}, Rp we source {hx(0x1552)}',
    ]))
    sec.append(('Temps & protections', [
        'BATIF interrupts now: ' + (', '.join(bitnames(r(0x1210), IRQS[0x1210])) or 'none'),
        'DCDC interrupts now: ' + (', '.join(bitnames(r(0x1110), IRQS[0x1110])) or 'none'),
        'MISC interrupts now: ' + (', '.join(bitnames(r(0x1610), IRQS[0x1610])) or 'none'),
        f'Temp range {hx(0x1606)}: ' + (', '.join(bits(trs, [(0, 'thermal regulation off'), (1, 'below range'), (2, 'within range'), (3, 'above range'), (4, 'alert'), (5, 'TLIM'), (6, 'REGULATING')])) or '-'),
        *(f'{name} temp {hx(a)}: ' + (', '.join(bits(r(a), [(0, 'lower bound'), (1, 'upper bound'), (2, 'reset'), (3, 'shutdown')])) or 'ok')
          for a, name in ((0x1607, 'Die'), (0x1608, 'Skin'), (0x1609, 'Connector'), (0x160A, 'SMB'))),
        f'Watchdog cfg {hx(0x1651)}, snarl/bark/bite {hx(0x1653)}, AICL rerun time {hx(0x1661)}, thermreg src {hx(0x1670)}',
        f'Ship mode {hx(0x1240)}, ADC channels {hx(0x1282)}',
        f'OTG cmd {hx(0x1140)}, OTG limit {hx(0x1152)}',
    ]))
    fg = [f'{k} = {v}' for k, v in sc.items() if k.startswith('battery_')]
    fg.append('FG interrupts now: BATT_SOC ' + hx(0x4010) + ', BATT_INFO ' + hx(0x4110) + ', RRADC ' + hx(0x4210))
    fg.append(f'Monotonic SOC raw {hx(0x4009)} ({(r(0x4009) or 0) * 100 // 255} %)')
    res['sections'].append(('Battery & gauge', fg))
    raw = []
    for base in sorted(d['raw']):
        raw.append(f'{base:04x}  {BLOCK_NAMES.get(base, "")}')
        h = d['raw'][base]
        for row in range(16):
            cells = [h[2 * (row * 16 + c):2 * (row * 16 + c) + 2] for c in range(16)]
            if any(c not in ('00', '--') for c in cells):
                raw.append(f'  {base + row * 16:04x}: ' + ' '.join(cells))
    sec.append(('Raw registers', raw))
    return res
