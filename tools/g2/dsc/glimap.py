# builds off2name: GLI macro-context offset -> [gl names], from OpenGLES exports (gles.s, gles-symbols.txt)
import collections as _c, re as _re, os as _os
_OUT = _os.path.expanduser('~/ios-work/gl/out2')
_gsym = {}
for _l in open(f'{_OUT}/gles-symbols.txt', errors='replace'):
    _m = _re.match(r'(0x[0-9a-f]+):\s+\(__TEXT,__text\)\s+external\s+(_gl\w+)', _l)
    if _m:
        _gsym[int(_m.group(1), 16)] = _m.group(2)[1:]
_lines, _order = {}, []
for _l in open(f'{_OUT}/gles.s'):
    _m = _re.match(r'^(0x[0-9a-f]+):\s+(?:[0-9a-f]{2} ){4}\s*(.*)$', _l)
    if _m:
        _a = int(_m.group(1), 16)
        _lines[_a] = _m.group(2).strip()
        _order.append(_a)
_idx = {a: i for i, a in enumerate(_order)}
off2name = _c.defaultdict(list)
for _a, _n in sorted(_gsym.items(), key=lambda x: x[1]):
    if _a not in _idx:
        continue
    _base = None
    for _j in range(_idx[_a], min(_idx[_a] + 24, len(_order))):
        _t = _lines[_order[_j]]
        _m = _re.match(r'ldr\s+(x\d+), \[(x\d+), #0xf0\]', _t)
        if _m:
            _base = _m.group(1)
            continue
        _m = _re.match(r'ldr\s+(x\d+), \[(x\d+), #(0x[0-9a-f]+)\]', _t)
        if _m and _base and _m.group(2) == _base and int(_m.group(3), 16) != 0x20:
            off2name[int(_m.group(3), 16) - 0x20].append(_n)
            break
