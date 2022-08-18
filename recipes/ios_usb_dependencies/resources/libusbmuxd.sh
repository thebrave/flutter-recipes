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
REMOTE_URL="https://flutter.googlesource.com/third_party/libusbmuxd"

git clone "$REMOTE_URL" "$SRC_DIR"
cd "$SRC_DIR"
git rev-parse HEAD > "commit_sha.txt"

./autogen.sh

"$SRC_DIR"/configure -disable-dependency-tracking --disable-silent-rules \
  --prefix="$INSTALL_DIR"

make install

cp ./COPYING "$INSTALL_DIR"/lib/libusbmuxd-2.0.6.dylib \
  "$INSTALL_DIR"/bin/iproxy "$OUTPUT_DIR"
