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
REMOTE_URL="https://flutter.googlesource.com/third_party/libtasn1"

git clone "$REMOTE_URL" "$SRC_DIR"
cd "$SRC_DIR"
git rev-parse HEAD > "commit_sha.txt"

# If an autoconf script calls GTK_DOC_CHECK, newer versions of
# autoreconf (>autoconf-2.69) try to call `gtkdocize --copy`, which
# would require an extra dependency on `gtk-doc`, even if
# documentation is disabled at configure time.
sed -i '.bak' 's/AUTOPOINT=true LIBTOOLIZE=true/AUTOPOINT=true LIBTOOLIZE=true GTKDOCIZE=true/g' bootstrap

./bootstrap

"$SRC_DIR"/configure --disable-dependency-tracking --disable-silent-rules \
  --disable-doc --prefix="$INSTALL_DIR"

make install
