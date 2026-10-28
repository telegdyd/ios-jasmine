#!/bin/sh
# One-time Mesa toolchain on the macOS build VM (runs there): ssh mac sh -s < tools/vm-mesa-setup.sh
# Mesa 26.2.5 wants Python >= 3.10 and bison >= 3 (glsl_parser.yy: parse.error); Sonoma has
# 3.9.6 and bison 2.3, and there is no Homebrew on Intel any more, so build them from upstream
# source into ~/topaz-mesa/tools (no sudo): OpenSSL (for pip's ssl), CPython, GNU bison. Then a
# venv with what xnu.yml pip-installs. System flex 2.6.4 is the same version Homebrew had.
# Idempotent: finished steps are skipped.
set -eu
OPENSSL=3.5.9 OPENSSL_SHA256=603f5602e2eef00d77fbd429d34dcd5822bb301757a1bc9cdb24c670f1eb859a
PYTHON=3.13.18
BISON=3.8.2
top=$HOME/topaz-mesa
pfx=$top/tools
src=$top/tools-src
mkdir -p "$pfx" "$src"
cd "$src"
j=$(sysctl -n hw.ncpu)

get() { # url file
	[ -f "$2" ] || { curl -fsSL -o "$2.part" "$1" && mv "$2.part" "$2"; }
}

if [ ! -f "$pfx/lib/libssl.a" ]; then
	get https://github.com/openssl/openssl/releases/download/openssl-$OPENSSL/openssl-$OPENSSL.tar.gz openssl-$OPENSSL.tar.gz
	echo "$OPENSSL_SHA256  openssl-$OPENSSL.tar.gz" | shasum -a 256 -c
	rm -rf openssl-$OPENSSL && tar xzf openssl-$OPENSSL.tar.gz
	(cd openssl-$OPENSSL && ./Configure darwin64-x86_64-cc no-shared no-tests --prefix="$pfx" --libdir=lib --openssldir="$pfx/ssl" &&
		make -j"$j" && make install_sw install_ssldirs) >openssl.log 2>&1 || { tail -30 openssl.log; exit 1; }
fi

if [ ! -x "$pfx/bin/python3.13" ]; then
	get https://www.python.org/ftp/python/$PYTHON/Python-$PYTHON.tar.xz Python-$PYTHON.tar.xz
	rm -rf Python-$PYTHON && tar xJf Python-$PYTHON.tar.xz
	(cd Python-$PYTHON && ./configure --prefix="$pfx" --with-openssl="$pfx" --without-ensurepip &&
		make -j"$j" && make install) >python.log 2>&1 || { tail -30 python.log; exit 1; }
	"$pfx/bin/python3.13" -c 'import ssl, ctypes, zlib; print(ssl.OPENSSL_VERSION)'
fi

if [ ! -x "$pfx/bin/bison" ]; then
	get https://ftp.gnu.org/gnu/bison/bison-$BISON.tar.xz bison-$BISON.tar.xz
	rm -rf bison-$BISON && tar xJf bison-$BISON.tar.xz
	(cd bison-$BISON && ./configure --prefix="$pfx" --disable-nls && make -j"$j" && make install) >bison.log 2>&1 || { tail -30 bison.log; exit 1; }
fi

# CA bundle for the built OpenSSL: the system one (Sonoma keeps the roots in /etc/ssl/cert.pem)
[ -e "$pfx/ssl/cert.pem" ] || ln -sf /etc/ssl/cert.pem "$pfx/ssl/cert.pem"

if [ ! -x "$top/venv/bin/meson" ]; then
	"$pfx/bin/python3.13" -m venv "$top/venv"
	"$top/venv/bin/pip" install -q meson ninja mako pyyaml packaging
fi
"$top/venv/bin/python" --version
"$top/venv/bin/meson" --version
"$pfx/bin/bison" --version | head -1
flex --version
