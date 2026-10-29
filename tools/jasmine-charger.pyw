#!/usr/bin/env python3
"""Mi A2 (jasmine) charger: one-window Windows app.

Finds the phone in iOS (USB Ethernet command port), fastboot or the Linux charging
shell, moves it into the fast charging shell (shim/out/charge-shell.img, see
tools/charge-shell/) and shows the charge state; "Boot iOS" sends it back. Under iOS
(j0114+ kernels) the battery comes from the command port's `batt` line.

Run with pythonw (no console): the desktop shortcut "Mi A2 Charger" does that.
Every phone action takes the shared phone lock first (PHONE_LOCK, same file as
tools/g2/flash-slotb.sh) so other sessions' tests are never interrupted.
"""
import base64
import glob
import hashlib
import os
import pathlib
import queue
import re
import shutil
import socket
import subprocess
import threading
import time
import tkinter as tk
from tkinter import ttk

REPO = pathlib.Path(__file__).resolve().parent.parent
IMAGE = REPO / 'shim' / 'out' / 'charge-shell.img'
REBOOT_BL = REPO / 'shim' / 'out' / 'reboot-bootloader'
LOCK = pathlib.Path(os.environ.get('PHONE_LOCK', 'C:/Users/teleg/AppData/Local/Claude-Data/'
                    'claude_pzs8sxrjxfjjc/side-session-notes/'
                    'local_b57c5c9a-db18-434e-a448-e6d69fa0dddf/phone.lock'))
LOCK_TAG = f'jasmine-charger app pid {os.getpid()}'

SHELL_HOST = '172.16.42.1'          # pmOS initramfs telnet (USB NCM)
IOS_HOSTS = ('192.168.7.2', '169.254.7.2')
IOS_CMD_PORT = 5141                 # j0022 command port: "reboot" -> fastboot
NOWIN = getattr(subprocess, 'CREATE_NO_WINDOW', 0)
POLL_S = 3


def find_fastboot():
    exe = shutil.which('fastboot')
    if exe:
        return exe
    hits = glob.glob(os.path.expandvars(
        r'%LOCALAPPDATA%\Microsoft\WinGet\Packages\Google.PlatformTools*\platform-tools\fastboot.exe'))
    return hits[0] if hits else 'fastboot'


FASTBOOT = find_fastboot()


def fastboot(*args, timeout=30):
    try:
        p = subprocess.run([FASTBOOT, *args], capture_output=True, text=True,
                           timeout=timeout, creationflags=NOWIN)
        return p.returncode, (p.stdout + p.stderr).strip()
    except (OSError, subprocess.TimeoutExpired) as e:
        return -1, str(e)


def fastboot_present():
    rc, out = fastboot('devices', timeout=10)
    return rc == 0 and 'fastboot' in out


def fastboot_var(name):
    rc, out = fastboot('getvar', name, timeout=10)
    for line in out.splitlines():
        if line.startswith(name + ':'):
            return line.split(':', 1)[1].strip()
    return None


# --- Linux shell over telnet (same protocol as tools/pmos-shell.py) ---------------
IAC, DONT, DO, WONT, WILL, SB, SE = 255, 254, 253, 252, 251, 250, 240
END = '__PMOS_SHELL_DONE__'


def _strip_telnet(sock, data):
    out, i = bytearray(), 0
    while i < len(data):
        b = data[i]
        if b != IAC or i + 1 >= len(data):
            out.append(b)
            i += 1
            continue
        cmd = data[i + 1]
        if cmd in (DO, DONT, WILL, WONT) and i + 2 < len(data):
            if cmd == DO:
                sock.sendall(bytes([IAC, WONT, data[i + 2]]))
            elif cmd == WILL:
                sock.sendall(bytes([IAC, DONT, data[i + 2]]))
            i += 3
        elif cmd == SB:
            j = data.find(bytes([IAC, SE]), i)
            i = len(data) if j < 0 else j + 2
        elif cmd == IAC:
            out.append(IAC)
            i += 2
        else:
            i += 2
    return bytes(out)


def shell(command, timeout=15):
    with socket.create_connection((SHELL_HOST, 23), timeout=timeout) as sock:
        sock.sendall(b'stty -echo 2>/dev/null\n')
        half = len(END) // 2

        def mark(n):
            return f"printf '%s%s{n}\\n' '{END[:half]}' '{END[half:]}'"

        sock.sendall(f'{mark(0)}; {command}; echo; {mark(1)}\n'.encode())
        buf = b''
        while f'{END}1'.encode() not in buf:
            chunk = sock.recv(1 << 16)
            if not chunk:
                break
            buf += _strip_telnet(sock, chunk)
    text = buf.split(f'{END}0'.encode(), 1)[-1].split(f'{END}1'.encode(), 1)[0]
    return text.replace(b'\r\n', b'\n').decode(errors='replace').strip()


def port_open(host, port, timeout=0.6):
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


def ios_up():
    """Ping only: the command port treats every connection as a command line."""
    for host in IOS_HOSTS:
        p = subprocess.run(['ping', '-n', '1', '-w', '600', host], capture_output=True,
                           creationflags=NOWIN)
        if p.returncode == 0 and b'TTL=' in p.stdout:
            return True
    return False


def ios_command(line):
    for host in IOS_HOSTS:
        try:
            with socket.create_connection((host, IOS_CMD_PORT), timeout=3) as s:
                s.sendall(line.encode() + b'\n')
                s.settimeout(5)
                out = b''
                try:  # the kernel closes the connection after its reply
                    while len(out) < 4096:
                        chunk = s.recv(4096)
                        if not chunk:
                            break
                        out += chunk
                except socket.timeout:
                    pass
                return out.decode(errors='replace').strip() or '(no answer)'
        except OSError:
            continue
    return None


# j0114 sweet_ddrgov.c: "batt: %d mV %d mA, %d.%d C, soc %d%%, online %d charging %d full %d; display %s, ..."
BATT_RE = re.compile(r'batt: (-?\d+) mV (-?\d+) mA, (-?\d+\.\d) C, soc (\d+)%, '
                     r'online (\d) charging (\d) full (\d); display (\w+)')


def ios_batt():
    """The kernel's fuel-gauge line, or None (no answer, or a kernel before j0114)."""
    m = BATT_RE.search(ios_command('batt') or '')
    if not m:
        return None
    mv, ma, temp, soc, online, charging, full, display = m.groups()
    return {'mv': int(mv), 'ma': int(ma), 'temp': temp, 'soc': soc, 'online': online == '1',
            'charging': charging == '1', 'full': full == '1', 'display': display}


STATS_CMD = (
    'cd /sys/class/power_supply; '
    'for k in pm660-charger/status pm660-charger/usb_type pm660-charger/current_max '
    'pm660-charger/constant_charge_voltage pm660-charger/voltage_now pm660-charger/current_now '
    'qcom-battery/voltage_now qcom-battery/current_now qcom-battery/capacity qcom-battery/temp; '
    'do echo "$k=$(cat $k 2>/dev/null)"; done; '
    '[ -e /init.pmos ] && echo fast=1; '
    'echo wled=$(grep ^d846: /sys/kernel/debug/regmap/0-03/registers 2>/dev/null | cut -d" " -f2); '
    # kernel/0006 logs every detection; keep the last two (an SDP re-run and its result)
    'dmesg | grep -E "qcom-smbx.*(charger type|APSD:)" | tail -2 | '
    'sed -e "s/^\\[ *\\([0-9]*\\)\\.[0-9]*\\] .*charger@1000: /detect=\\1 s: /"'
)


def read_stats():
    out = {'detect': []}
    for line in shell(STATS_CMD).splitlines():
        if line.startswith('detect='):
            out['detect'].append(line[7:].strip())
        elif '=' in line:
            k, v = line.split('=', 1)
            out[k.removeprefix('qcom-battery/')] = v.strip()
    return out


# --- phone lock ------------------------------------------------------------------
def lock_holder():
    try:
        return LOCK.read_text(errors='replace').strip() or '(empty lock file)'
    except OSError:
        return None


def take_lock():
    try:
        LOCK.parent.mkdir(parents=True, exist_ok=True)
        fd = os.open(LOCK, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    except FileExistsError:
        return False
    with os.fdopen(fd, 'w', newline='\n') as f:
        f.write(f'{LOCK_TAG} {time.strftime("%H:%M:%S")}\n')
    return True


def release_lock():
    h = lock_holder()
    if h and h.startswith(LOCK_TAG):
        try:
            LOCK.unlink()
        except OSError:
            pass


# --- app -------------------------------------------------------------------------
class App:
    def __init__(self, root):
        self.root = root
        self.q = queue.Queue()
        self.busy = False
        self.state = 'unknown'
        self.fast = False
        root.title('Mi A2 Charger')
        root.resizable(False, False)
        root.protocol('WM_DELETE_WINDOW', self.close)

        frm = ttk.Frame(root, padding=14)
        frm.grid()
        self.state_var = tk.StringVar(value='Looking for the phone...')
        ttk.Label(frm, textvariable=self.state_var, font=('Segoe UI', 12, 'bold')).grid(
            row=0, column=0, columnspan=2, sticky='w')

        big = ('Segoe UI', 22)
        self.volt = tk.StringVar(value='-')
        self.amps = tk.StringVar(value='-')
        self.pct = tk.StringVar(value='-')
        for i, (name, var) in enumerate((('Battery', self.volt), ('Current', self.amps),
                                         ('Gauge', self.pct))):
            ttk.Label(frm, text=name, foreground='#666').grid(row=1, column=i, sticky='w',
                                                              padx=(0, 22), pady=(10, 0))
            ttk.Label(frm, textvariable=var, font=big).grid(row=2, column=i, sticky='w',
                                                            padx=(0, 22))
        self.detail = tk.StringVar(value='')
        ttk.Label(frm, textvariable=self.detail, foreground='#444', justify='left').grid(
            row=3, column=0, columnspan=3, sticky='w', pady=(8, 0))

        btns = ttk.Frame(frm)
        btns.grid(row=4, column=0, columnspan=3, sticky='w', pady=(12, 0))
        self.b_charge = ttk.Button(btns, text='Charging shell', command=self.to_shell)
        self.b_charge.grid(row=0, column=0, padx=(0, 8))
        self.b_ios = ttk.Button(btns, text='Boot iOS', command=self.to_ios)
        self.b_ios.grid(row=0, column=1)

        self.msg = tk.StringVar(value='')
        ttk.Label(frm, textvariable=self.msg, foreground='#a05000', wraplength=420,
                  justify='left').grid(row=5, column=0, columnspan=3, sticky='w', pady=(10, 0))

        self.update_buttons()
        threading.Thread(target=self.poller, daemon=True).start()
        root.after(200, self.pump)

    # UI thread
    def pump(self):
        try:
            while True:
                kind, val = self.q.get_nowait()
                if kind == 'state':
                    self.show_state(*val)
                elif kind == 'msg':
                    self.msg.set(val)
                elif kind == 'busy':
                    self.busy = val
                    self.update_buttons()
        except queue.Empty:
            pass
        self.root.after(200, self.pump)

    def show_state(self, state, info):
        self.state = state
        self.fast = state == 'shell' and info.get('fast') == '1'
        holder = lock_holder()
        lock_txt = f'\nPhone lock: {holder}' if holder and not holder.startswith(LOCK_TAG) else ''
        if state == 'shell':
            s = info
            try:
                v = int(s.get('voltage_now', '')) / 1e6
                self.volt.set(f'{v:.3f} V')
            except ValueError:
                self.volt.set('-')
            try:
                a = int(s.get('current_now', '')) / 1e6
                self.amps.set(f'{a:+.2f} A')
            except ValueError:
                self.amps.set('-')
            self.pct.set(f"{s.get('capacity', '-')} %")
            cv = s.get('pm660-charger/constant_charge_voltage', '')
            lines = [f"Charger: {s.get('pm660-charger/status', '?')}"
                     + (f", limit {int(cv) / 1e6:.3f} V" if cv.isdigit() else '')]
            usb = s.get('pm660-charger/usb_type', '')
            port = usb[usb.find('[') + 1:usb.find(']')] if '[' in usb else usb
            imax = s.get('pm660-charger/current_max', '')
            vin = s.get('pm660-charger/voltage_now', '')
            iin = s.get('pm660-charger/current_now', '')
            inp = f'Input: {port or "?"}'
            if imax.isdigit():
                inp += f', max {int(imax) / 1e6:.2f} A'
            if vin.isdigit() and iin.isdigit():
                inp += f', {int(vin) / 1e6:.2f} V / {int(iin) / 1e6:.2f} A'
            lines.append(inp)
            for d in s.get('detect', []):
                lines.append(f'Detect at {d}')
            t = s.get('temp', '')
            if t.lstrip('-').isdigit():
                lines.append(f'Battery temp: {int(t) / 10:.1f} °C')
            wled = s.get('wled')
            lines.append('Screen: ' + ('off' if wled == '00' else 'backlight ON' if wled else '?'))
            if s.get('fast') != '1':
                lines.append('Old pmOS shell: "Charging shell" swaps in the fast one.')
            self.state_var.set('Charging shell' + (' (fast)' if s.get('fast') == '1' else ''))
            self.detail.set('\n'.join(lines) + lock_txt)
        elif state == 'ios' and info.get('batt'):
            b = info['batt']
            self.volt.set(f"{b['mv'] / 1000:.3f} V")
            self.amps.set(f"{b['ma'] / 1000:+.2f} A")
            self.pct.set(f"{b['soc']} %")
            chg = ('Full' if b['full'] else 'Charging' if b['charging'] else
                   'Not charging' if b['online'] else 'Unplugged')
            lines = [f'Charger: {chg}' + (' (net discharge)' if b['online'] and b['ma'] < 0 else ''),
                     f"Battery temp: {b['temp']} °C",
                     f"Screen: {b['display']}",
                     "Gauge = iOS fuel-gauge SOC (the Linux shell's capacity can differ)."]
            self.state_var.set('iOS running')
            self.detail.set('\n'.join(lines) + lock_txt)
        else:
            self.volt.set(info.get('volt', '-') if isinstance(info, dict) else '-')
            self.amps.set('-')
            self.pct.set('-')
            label = {'ios': 'iOS running', 'fastboot': 'Fastboot',
                     'none': 'No phone on USB'}.get(state, state)
            self.state_var.set(label)
            ios_txt = ('Phone in use: battery not read.' if info.get('skipped') else
                       'No battery readout (kernel before j0114, or no answer).')
            extra = {'ios': ios_txt,
                     'fastboot': f"Slot {info.get('slot', '?')}" if isinstance(info, dict) else '',
                     'none': 'Off or hung: hold Power + Volume Down for fastboot.'}.get(state, '')
            self.detail.set(extra + lock_txt)
        self.update_buttons()

    def update_buttons(self):
        free = not self.busy
        self.b_charge.state(['!disabled'] if free and self.state in ('ios', 'fastboot', 'shell')
                            and not self.fast else ['disabled'])
        self.b_ios.state(['!disabled'] if free and self.state in ('shell', 'fastboot')
                         else ['disabled'])

    def close(self):
        release_lock()
        self.root.destroy()

    # background
    def detect(self):
        if port_open(SHELL_HOST, 23):
            try:
                return 'shell', read_stats()
            except OSError:
                pass
        if fastboot_present():
            info = {}
            if not self.busy and lock_holder() is None:
                v = fastboot_var('battery-voltage')
                info['volt'] = f'{int(v) / 1000:.3f} V' if v and v.isdigit() else '-'
                info['slot'] = fastboot_var('current-slot') or '?'
            return 'fastboot', info
        if ios_up():
            # the command port is shared with other sessions' tests: only read it when free
            if self.busy or lock_holder() is not None:
                return 'ios', {'skipped': True}
            return 'ios', {'batt': ios_batt()}
        return 'none', {}

    def poller(self):
        while True:
            if not self.busy:
                try:
                    self.q.put(('state', self.detect()))
                except Exception as e:  # keep polling whatever happens
                    self.q.put(('msg', f'poll error: {e}'))
            time.sleep(POLL_S)

    def run_action(self, fn):
        holder = lock_holder()
        if holder is not None:
            self.msg.set(f'Phone is in use (lock: {holder}). Try again when it is free.')
            return
        if not take_lock():
            self.msg.set('Phone lock was just taken by someone else.')
            return
        self.q.put(('busy', True))

        def work():
            try:
                fn()
            except Exception as e:
                self.q.put(('msg', f'Error: {e}'))
            finally:
                release_lock()
                self.q.put(('busy', False))
        threading.Thread(target=work, daemon=True).start()

    def say(self, text):
        self.q.put(('msg', f'{time.strftime("%H:%M:%S")}  {text}'))

    def wait_for(self, test, secs, what):
        t0 = time.time()
        while time.time() - t0 < secs:
            if test():
                return True
            time.sleep(1.5)
        return False

    def shell_to_fastboot(self):
        self.say('Shell -> fastboot...')
        cmd = ('B=/sbin/reboot-bootloader; [ -x $B ] || B=/tmp/reboot-bootloader; '
               '[ -x $B ] && { setsid sh -c "sleep 1; $B" </dev/null >/dev/null 2>&1 & echo ok; }')
        if 'ok' not in shell(cmd):
            self.push_reboot_bootloader()
            shell('setsid sh -c "sleep 1; /tmp/reboot-bootloader" </dev/null >/dev/null 2>&1 &')

    def push_reboot_bootloader(self):
        self.say('Old shell: copying reboot-bootloader...')
        data = REBOOT_BL.read_bytes()
        text = base64.b64encode(data).decode()
        # one telnet session; short lines so the tty line limit never bites
        lines = ['rm -f /tmp/rb.b64'] + [f'echo {text[i:i + 3000]} >> /tmp/rb.b64'
                                         for i in range(0, len(text), 3000)]
        lines.append('base64 -d /tmp/rb.b64 > /tmp/reboot-bootloader && '
                     'chmod +x /tmp/reboot-bootloader && sha256sum /tmp/reboot-bootloader')
        out = shell('\n'.join(lines), timeout=180)
        if hashlib.sha256(data).hexdigest() not in out:
            raise RuntimeError('reboot-bootloader copy failed checksum')

    def to_shell(self):
        def go():
            st = self.state
            if st == 'ios':
                self.say('iOS -> fastboot (command port reboot)...')
                if ios_command('reboot') is None:
                    raise RuntimeError('iOS command port did not answer')
            elif st == 'shell':
                self.shell_to_fastboot()
            if st != 'fastboot':
                if not self.wait_for(fastboot_present, 90, 'fastboot'):
                    self.say('No fastboot yet; the phone may have powered off. '
                             'Hold Power + Volume Down, waiting up to 10 min...')
                    if not self.wait_for(fastboot_present, 600, 'fastboot'):
                        raise RuntimeError('fastboot never appeared')
            self.say('Booting the charging shell...')
            rc, out = fastboot('boot', str(IMAGE), timeout=60)
            if rc != 0:
                raise RuntimeError(f'fastboot boot failed: {out[-200:]}')
            if not self.wait_for(lambda: port_open(SHELL_HOST, 23), 90, 'shell'):
                raise RuntimeError('charging shell did not come up on 172.16.42.1')
            time.sleep(3)
            self.say('Charging shell is up.')
        self.run_action(go)

    def to_ios(self):
        def go():
            if self.state == 'shell':
                self.shell_to_fastboot()
                if not self.wait_for(fastboot_present, 90, 'fastboot'):
                    raise RuntimeError('fastboot did not appear after the shell reboot')
            slot = fastboot_var('current-slot')
            if slot != 'b':
                raise RuntimeError(f'active slot is {slot!r}, not b (iOS): not rebooting')
            self.say('Fastboot -> iOS (slot b)...')
            fastboot('reboot', timeout=20)
            if self.wait_for(ios_up, 120, 'iOS'):
                self.say('iOS is up.')
            else:
                self.say('iOS has not answered on USB yet (it may still be booting).')
        self.run_action(go)


def main():
    root = tk.Tk()
    try:
        root.tk.call('tk', 'scaling', 1.25)
    except tk.TclError:
        pass
    App(root)
    root.mainloop()


if __name__ == '__main__':
    main()
