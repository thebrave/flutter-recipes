#!/usr/bin/env bash

set -exo pipefail

if [ -z "$3" ]; then
  echo -e "Usage: ios-deploy.sh \$SRC_DIR \$REVISION \$OUTPUT_DIR " 1>&2
  exit 1
fi

set -u

SRC_DIR="$1"
REVISION="$2"
OUTPUT_DIR="$3"
REMOTE_URL="https://flutter-mirrors.googlesource.com/ios-deploy"

git clone "$REMOTE_URL" "$SRC_DIR"
cd "$SRC_DIR"
git checkout "$REVISION"

xcodebuild -configuration Release SYMROOT=build -arch x86_64

xcodebuild test \
  -scheme ios-deploy-tests -configuration Release SYMROOT=build -arch x86_64

cp LICENSE LICENSE2 ./build/Release/ios-deploy "$OUTPUT_DIR"
