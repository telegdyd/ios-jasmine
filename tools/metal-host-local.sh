#!/bin/bash
# jasmine: called by mesa-local.sh metal-host under vm-mesa.sh's shared lock.
# Builds native macOS compiler tools only; never creates a Gallium screen.
# Softpipe + GLES enable full NIR in Meson; no software screen is instantiated.
set -euo pipefail
TREE=$(cd "$(dirname "$0")/.." && pwd)
ROOT=$HOME/topaz-mesa
OUT=$ROOT/out-metal-host
export PATH="$ROOT/venv/bin:$ROOT/tools/bin:$PATH"
mkdir -p "$OUT"
cd "$ROOT/mesa-src"
meson setup $([ -f build-host/build.ninja ] && echo --reconfigure) build-host \
    -Dbuildtype=debugoptimized -Dplatforms= -Dgallium-drivers=softpipe -Dvulkan-drivers= \
    -Dtools=freedreno -Dfreedreno-kmds=msm -Dglx=disabled -Degl=disabled -Dgbm=disabled \
    -Dopengl=false -Dgles1=disabled -Dgles2=enabled -Dllvm=disabled -Dzstd=disabled \
    -Dxmlconfig=disabled -Dexpat=disabled -Dvalgrind=disabled -Dlibunwind=disabled \
    -Dbuild-tests=false -Dshader-cache=disabled -Dperfetto=false -Dvideo-codecs= \
    -Dspirv-tools=disabled -Dwrap_mode=nofallback > "$ROOT/metal-host-setup.log" 2>&1 || {
    tail -80 "$ROOT/metal-host-setup.log"; exit 1;
}
ninja -C build-host src/compiler/air/air2nir src/freedreno/air2ir3 > "$ROOT/metal-host-build.log" 2>&1 || {
    tail -100 "$ROOT/metal-host-build.log"; exit 1;
}
cp build-host/src/compiler/air/air2nir build-host/src/freedreno/air2ir3 "$OUT/"
cp "$ROOT/metal-host-build.log" "$OUT/build.log"
file "$OUT/air2nir" "$OUT/air2ir3" > "$OUT/platform.txt"
# Synthetic AIR is generated locally; it is not extracted Apple system content.
xcrun --sdk iphoneos metal -mios-version-min=16.0 -std=ios-metal2.4 -c \
    "$TREE/mesa/metal/test/jasmine_compile.metal" -o "$OUT/jasmine_compile.air"
xcrun --sdk iphoneos metallib "$OUT/jasmine_compile.air" -o "$OUT/jasmine_compile.metallib"
"$OUT/air2nir" --list "$OUT/jasmine_compile.metallib" > "$OUT/functions.txt"
for name in jasmine_add jasmine_u2f jasmine_negative jasmine_vertex jasmine_fragment jasmine_byte; do
    "$OUT/air2ir3" "$OUT/jasmine_compile.metallib" "$name" > "$OUT/$name.txt" 2>&1 || {
        cat "$OUT/$name.txt"; exit 1;
    }
done
# a5xx framebuffer fetch compiles through the runtime's attachment-texture lowering
"$OUT/air2ir3" "$OUT/jasmine_compile.metallib" jasmine_fetch > "$OUT/jasmine_fetch.txt" 2>&1 || {
    cat "$OUT/jasmine_fetch.txt"; exit 1;
}
grep -q 'attachment reads of targets 0x1 lowered' "$OUT/jasmine_fetch.txt"
printf 'PASS: seven a512 compile/assemble probes (byte store; framebuffer fetch via attachment-texture lowering)\n' > "$OUT/status.txt"
cat "$OUT/status.txt"
