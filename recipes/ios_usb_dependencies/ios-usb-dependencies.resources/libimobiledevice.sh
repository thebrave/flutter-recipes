#!/usr/bin/env bash
# Copyright 2024 The Flutter Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

set -exo pipefail

if [ -z "$3" ]; then
  echo -e "Usage: libplist.sh \$SRC_DIR \$INSTALL_DIR \$OUTPUT_DIR " 1>&2
  exit 1
fi

set -u

SRC_DIR="$1"
INSTALL_DIR="$2"
OUTPUT_DIR="$3"
REMOTE_URL="https://flutter.googlesource.com/third_party/libimobiledevice"

git clone "$REMOTE_URL" "$SRC_DIR"
cd "$SRC_DIR"
git rev-parse HEAD > "commit_sha.txt"

./autogen.sh

"$SRC_DIR"/configure -disable-dependency-tracking --disable-silent-rules \
  --prefix="$INSTALL_DIR" --without-cython --enable-debug-code

make install

cp ./COPYING ./COPYING.LESSER "$INSTALL_DIR"/lib/libimobiledevice-1.0.6.dylib \
  "$INSTALL_DIR"/bin/idevicescreenshot "$INSTALL_DIR"/bin/idevicesyslog "$OUTPUT_DIR"
