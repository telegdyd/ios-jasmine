#!/bin/bash
# Linux host build of the patched Mesa tree: a quick compile check for the
# darwin-independent parts (frontend, tests) before the iOS build on CI
set -e
cd ~/ios-work
[ -x venv/bin/meson ] || { python3 -m venv venv && venv/bin/pip install -q meson ninja mako pyyaml packaging; }
export PATH=~/ios-work/venv/bin:$PATH
cd mesa
if [ ! -f build-host/build.ninja ]; then
	meson setup build-host -Dbuildtype=debug \
		-Dplatforms= -Dgallium-drivers=freedreno -Dvulkan-drivers= -Dfreedreno-kmds=msm \
		-Dglx=disabled -Degl=disabled -Dgbm=disabled -Dopengl=false -Dgles1=disabled -Dgles2=enabled \
		-Dllvm=disabled -Dzstd=disabled -Dxmlconfig=disabled -Dexpat=disabled -Dvalgrind=disabled \
		-Dlibunwind=disabled -Dbuild-tests=false -Dshader-cache=disabled -Dperfetto=false \
		-Dvideo-codecs= -Dspirv-tools=disabled -Dallow-fallback-for=libdrm 2>&1 | tail -40
fi
ninja -C build-host "$@" 2>&1 | tail -60
