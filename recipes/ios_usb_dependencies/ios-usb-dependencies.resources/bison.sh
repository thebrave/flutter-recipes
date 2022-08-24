#!/usr/bin/env bash

set -exo pipefail

if [ -z "$2" ]; then
  echo -e "Usage: libplist.sh \$SRC_DIR \$INSTALL_DIR \$OUTPUT_DIR " 1>&2
  exit 1
fi

set -u

SRC_DIR="$1"
INSTALL_DIR="$2"

curl http://mirror.us-midwest-1.nexcess.net/gnu/bison/bison-3.8.tar.gz --output "$SRC_DIR"/bison-3.8.tar.gz
tar -xzvf "$SRC_DIR"/bison-3.8.tar.gz -C "$SRC_DIR"
cd "$SRC_DIR"/bison-3.8

"$SRC_DIR"/bison-3.8/configure --prefix="$INSTALL_DIR"

make install
