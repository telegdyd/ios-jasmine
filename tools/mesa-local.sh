#!/bin/bash
# The mesa and ios-tools jobs of .github/workflows/xnu.yml, run on a Mac (the build VM, see
# tools/vm-mesa.sh, which syncs mesa/, ios/ and tools/ there and calls this).
#   tools/mesa-local.sh mesa     Mesa 26.2.5 + mesa/patches -> ~/topaz-mesa/out-mesa (= mesa-ios artifact)
#   tools/mesa-local.sh ios      ios/*.c, ios/lib/*.c       -> ~/topaz-mesa/out-ios  (= ios-tools artifact)
# Same compiler flags, meson options, ninja targets and ad-hoc signatures as the workflow.
# TASK24_CONTROLS=1 adds the workflow's Task 24 control (gltest without patch0008); SOURCE
# names the checkout for its provenance file (the workflow writes $GITHUB_SHA there).
# Work tree: ~/topaz-mesa. mesa-26.2.5 is the pristine clone, stage gets it plus our patches,
# mesa-src/build is the persistent meson build dir. stage is copied into mesa-src by content
# (rsync -c), so only files whose patched text changed get a new mtime and ninja rebuilds
# just what depends on them. Python 3.13, bison 3.8 and the meson venv come from
# tools/vm-mesa-setup.sh (Sonoma's 3.9 and 2.3 are too old for Mesa 26).
set -euo pipefail
TREE=$(cd "$(dirname "$0")/.." && pwd)
ROOT=$HOME/topaz-mesa
mode=${1:?usage: mesa-local.sh mesa|ios}
OUT=$ROOT/out-$mode
cd "$TREE"
rm -rf "$OUT"
mkdir -p "$OUT"
SDK=$(xcrun --sdk iphoneos --show-sdk-path)

case $mode in
ios)
	for src in ios/*.c; do
		name=$(basename "$src" .c)
		xcrun --sdk iphoneos clang -arch arm64 -mios-version-min=16.0 -isysroot "$SDK" -O2 -Wall -Werror -o "$OUT/$name" "$src"
		codesign -f -s - --entitlements ios/entitlements.plist "$OUT/$name"
		codesign -dv "$OUT/$name" 2>&1 | head -3
	done
	for src in ios/lib/*.c; do
		name=$(basename "$src" .c)
		xcrun --sdk iphoneos clang -arch arm64 -mios-version-min=16.0 -isysroot "$SDK" -O2 -Wall -Werror \
			-dynamiclib -install_name "/usr/local/bin/$name.dylib" -o "$OUT/$name.dylib" "$src"
		codesign -f -s - "$OUT/$name.dylib"
	done
	;;
mesa)
	export PATH="$ROOT/venv/bin:$ROOT/tools/bin:$PATH"
	test -x "$ROOT/venv/bin/meson" -a -x "$ROOT/tools/bin/bison" || { echo "no Mesa toolchain: ssh mac sh -s < tools/vm-mesa-setup.sh" >&2; exit 1; }
	test -d "$ROOT/mesa-26.2.5" || git clone -q --depth 1 --branch mesa-26.2.5 https://gitlab.freedesktop.org/mesa/mesa.git "$ROOT/mesa-26.2.5"
	rsync -a --delete --exclude=/.git "$ROOT/mesa-26.2.5/" "$ROOT/stage/"
	(cd "$ROOT/stage" && for p in "$TREE"/mesa/patches/*.patch; do git apply --verbose "$p"; done) > "$ROOT/patch.log" 2>&1 ||
		{ cat "$ROOT/patch.log"; exit 1; }
	grep -c '^Applied patch' "$ROOT/patch.log" | sed 's/$/ patch files applied cleanly/'
	mkdir -p "$ROOT/mesa-src"
	rsync -rlpc --delete --exclude=/build "$ROOT/stage/" "$ROOT/mesa-src/"
	cd "$ROOT/mesa-src"
	opts="--cross-file $TREE/mesa/ios-arm64.ini -Dbuildtype=release -Dplatforms= -Dgallium-drivers=freedreno -Dvulkan-drivers= -Dfreedreno-kmds=msm
		-Dglx=disabled -Degl=disabled -Dgbm=disabled -Dopengl=false -Dgles1=disabled -Dgles2=enabled
		-Dllvm=disabled -Dzstd=disabled -Dxmlconfig=disabled -Dexpat=disabled -Dvalgrind=disabled
		-Dlibunwind=disabled -Dbuild-tests=false -Dshader-cache=disabled -Dperfetto=false
		-Dvideo-codecs= -Dspirv-tools=disabled -Dallow-fallback-for=libdrm"
	# configure once; again only when the options or the cross file change (ninja itself
	# re-runs meson when a meson.build changes)
	stamp="$opts $(shasum -a 256 < "$TREE/mesa/ios-arm64.ini")"
	if [ ! -f build/build.ninja ] || [ "$(cat build/.topaz-setup 2>/dev/null)" != "$stamp" ]; then
		# shellcheck disable=SC2086
		meson setup $([ -f build/build.ninja ] && echo --reconfigure) build $opts > "$ROOT/setup.log" 2>&1 ||
			{ tail -40 "$ROOT/setup.log"; tail -80 build/meson-logs/meson-log.txt 2>/dev/null; exit 1; }
		printf '%s' "$stamp" > build/.topaz-setup
	fi
	ninja -C build -k 0 src/gallium/drivers/freedreno/sweetgpu_fdtest src/gallium/frontends/sweetgl/sweetgpu_gltest src/gallium/frontends/sweetgl/libsweetca.dylib > "$ROOT/build.log" 2>&1 || true
	grep -E -A12 "^FAILED|error:|Undefined symbols" "$ROOT/build.log" | grep -v "warning:" | head -300 || true
	tail -15 "$ROOT/build.log"
	test -f build/src/gallium/drivers/freedreno/sweetgpu_fdtest
	test -f build/src/gallium/frontends/sweetgl/sweetgpu_gltest
	test -f build/src/gallium/frontends/sweetgl/libsweetca.dylib
	cp build/src/gallium/drivers/freedreno/sweetgpu_fdtest "$OUT/"
	codesign -f -s - --entitlements "$TREE/ios/entitlements.plist" "$OUT/sweetgpu_fdtest"
	cp build/src/gallium/frontends/sweetgl/sweetgpu_gltest "$OUT/"
	codesign -f -s - --entitlements "$TREE/ios/entitlements.plist" "$OUT/sweetgpu_gltest"
	# libsweetca (EAGL on sweetgl for CoreAnimation) and its test; the test is Objective-C, so clang builds it here
	cp build/src/gallium/frontends/sweetgl/libsweetca.dylib "$OUT/"
	codesign -f -s - "$OUT/libsweetca.dylib"
	cd "$TREE"
	xcrun --sdk iphoneos clang -arch arm64 -mios-version-min=16.0 -fobjc-arc -O1 -Wno-deprecated-declarations \
		mesa/darwin/sweetgl/sweetca_test.m -o "$OUT/sweetca_test" \
		-framework Foundation -framework QuartzCore -framework CoreGraphics -framework IOSurface -framework OpenGLES \
		-L"$OUT" -lsweetca
	codesign -f -s - --entitlements ios/entitlements.plist "$OUT/sweetca_test"
	# screenshot through the render server (G2 step 3)
	xcrun --sdk iphoneos clang -arch arm64 -mios-version-min=16.0 -O1 mesa/darwin/sweetgl/sweet_shot.m -o "$OUT/sweet_shot" -framework Foundation -framework IOSurface
	codesign -f -s - --entitlements ios/entitlements.plist "$OUT/sweet_shot"
	if [ "${TASK24_CONTROLS:-0}" = 1 ]; then
		# the next build's rsync puts patch0008 back (by content), so this only costs a rebuild of its files
		cd "$ROOT/mesa-src"
		git apply --reverse --check "$TREE/mesa/patches/0008-freedreno-a5xx-sysmem-barrier-experiment.patch"
		git apply --reverse "$TREE/mesa/patches/0008-freedreno-a5xx-sysmem-barrier-experiment.patch"
		ninja -C build src/gallium/frontends/sweetgl/sweetgpu_gltest > "$ROOT/task24-control-build.log" 2>&1 || {
			tail -100 "$ROOT/task24-control-build.log"
			exit 1
		}
		cp build/src/gallium/frontends/sweetgl/sweetgpu_gltest "$OUT/sweetgpu_gltest-pre-sysbarrier"
		codesign -f -s - --entitlements "$TREE/ios/entitlements.plist" "$OUT/sweetgpu_gltest-pre-sysbarrier"
		{
			echo "source=${SOURCE:-unknown}"
			echo "control=all current patches except patch0008; identical diagnostic test source"
			(cd "$OUT" && shasum -a 256 sweetgpu_gltest sweetgpu_gltest-pre-sysbarrier)
		} > "$OUT/task24-control-provenance.txt"
	fi
	;;
*)
	echo "usage: mesa-local.sh mesa|ios" >&2
	exit 1
	;;
esac
ls -la "$OUT"
(cd "$OUT" && shasum -a 256 *) > "$ROOT/out-$mode.sha256"
