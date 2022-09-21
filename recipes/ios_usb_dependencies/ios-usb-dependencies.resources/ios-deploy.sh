#!/usr/bin/env bash

set -exo pipefail

if [ -z "$3" ]; then
  echo -e "Usage: ios-deploy.sh \$SRC_DIR \$INSTALL_DIR \$OUTPUT_DIR " 1>&2
  exit 1
fi

set -u

SRC_DIR="$1"
OUTPUT_DIR="$3"
REMOTE_URL="https://flutter.googlesource.com/third_party/ios-deploy"

git clone "$REMOTE_URL" "$SRC_DIR"
cd "$SRC_DIR"
git rev-parse HEAD > "commit_sha.txt"

xcodebuild -configuration Release SYMROOT=build GCC_PREPROCESSOR_DEFINITIONS="NDEBUG=1 IOS_DEPLOY_FEATURE_DEVELOPER_MODE=YES"

cp LICENSE LICENSE2 ./build/Release/ios-deploy "$OUTPUT_DIR"
