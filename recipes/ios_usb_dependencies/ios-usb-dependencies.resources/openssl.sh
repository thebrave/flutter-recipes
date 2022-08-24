#!/usr/bin/env bash

set -exo pipefail

if [ -z "$3" ]; then
  echo -e "Usage: libplist.sh \$SRC_DIR \$INSTALL_DIR \$OUTPUT_DIR " 1>&2
  exit 1
fi

set -u

SRC_DIR="$1"
INSTALL_DIR="$2"
OUTPUT_DIR="$3"
REMOTE_URL="https://flutter.googlesource.com/third_party/openssl"

git clone "$REMOTE_URL" "$SRC_DIR"
cd "$SRC_DIR"
git rev-parse HEAD > "commit_sha.txt"

"$SRC_DIR"/configure --prefix="$INSTALL_DIR" --openssldir="$INSTALL_DIR/openssl" \
  no-ssl2 no-ssl3 no-zlib shared enable-cms darwin64-x86_64-cc enable-ec_nistp_64_gcc_128

make depend
make
make install MANDIR="$INSTALL_DIR/openssl/man" MANSUFFIX=ssl

cp ./LICENSE.txt "$INSTALL_DIR"/lib/libssl.3.dylib \
  "$INSTALL_DIR"/lib/libcrypto.3.dylib "$OUTPUT_DIR"
