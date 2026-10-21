# Shared-cache analysis helpers (G2 step A)

blacktop `ipsw` 3.1.739 runs out of memory (15 GB WSL) on whole-cache commands (`dyld stubs`, `dyld a2s`-heavy
`disass --vaddr`, `macho --stubs`). These scripts read the cache files directly instead: `dsc.py` maps a VM
address to its subcache file and follows stub islands (`adrp/add/br`, `adrp/ldr/br`).

They run in WSL (`python3`, plus `c++filt` for names) and expect the inputs below in `~/ios-work/gl/out2`
(QuartzCore disassembly in `~/ios-work/gl/out/qc.s`). With `I=~/ios-work/tools/ipsw-3.1.739/x/ipsw` and
`D=~/ios-work/gl/dsc/dyld_shared_cache_arm64`:

```
$I dyld macho $D QuartzCore --symbols --no-color > qc-symbols.txt      # also --strings, --objc --objc-refs
$I dyld macho $D OpenGLES --symbols --no-color > gles-symbols.txt
$I dyld disass $D --image OpenGLES -q --no-color > gles.s               # GLEngine -> gle.s, /usr/lib/dyld -> dyld.s
$I dyld disass $D --image AppleMetalGLRenderer -q --no-color > amglr.s  # symbols -> amglr-syms.txt
```

| Script | Does |
| --- | --- |
| `show.py ADDR [N]` | QuartzCore disassembly with call targets named (QuartzCore functions, objc stubs as `msgSend$sel`, other images' exports) and adrp+add strings |
| `gshow.py ADDR [N]` / `gshow.py x STR...` | same for another image (`ASM=`, `SYMS=` pick the files; default OpenGLES); `x` lists functions that reference the strings |
| `xref.py ADDR\|STRING...` | QuartzCore code that branches to or materialises an address or string |
| `qcimports.py` | which images QuartzCore calls through stub islands, per image |
| `eaglcallers.py` | QuartzCore functions that send EAGL selectors |
| `glimap.py` | GLI dispatch offset -> GL name, from OpenGLES's exported `gl*` thunks |
| `glidisp.py`, `glidisp2.py` | GLI dispatch entries QuartzCore calls (register tracking from `GLESContext+0x7f8`, and a `ldr fn,[b,#off]; ldr x0,[b]; blr fn` pattern scan); result in `jasmine/ca-gles-calls-ios16.txt` |
| `tbl.py ADDR N` | decode a table of function pointers (AppleMetalGLRenderer names) |

No Apple data is kept here; the dumps stay in WSL.
