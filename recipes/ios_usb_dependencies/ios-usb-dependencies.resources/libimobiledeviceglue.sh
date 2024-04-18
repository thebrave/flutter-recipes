#!/usr/bin/env bash
# Copyright 2024 The Flutter Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

set -exo pipefail

if [ -z "$3" ]; then
  echo -e "Usage: libplist.sh \$SRC_DIR \$REVISION \$OUTPUT_DIR " 1>&2
  exit 1
fi

set -u

SRC_DIR="$1"
INSTALL_DIR="$2"
OUTPUT_DIR="$3"
REMOTE_URL="https://github.com/libimobiledevice/libimobiledevice-glue.git"

git clone "$REMOTE_URL" "$SRC_DIR"
cd "$SRC_DIR"
git rev-parse HEAD > "commit_sha.txt"

./autogen.sh

"$SRC_DIR"/configure --prefix="$INSTALL_DIR"

make install

cp "$INSTALL_DIR"/lib/libimobiledevice-glue-1.0.0.dylib "$OUTPUT_DIR"
