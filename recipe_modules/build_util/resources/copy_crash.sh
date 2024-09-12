#!/bin/bash
# Copyright 2024 The Flutter Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

# TIP: A manual test of this script is available as copy_crash_test.sh:
# $ ./copy_crash_test.sh

# Helper script to copy mobileprovisioning profile to
# bot's default location.
set -e

# The first argument is the destination directory to copy any crash files to.
destination=$1

# Crash files are stored in this directory.
# See https://github.com/flutter/flutter/issues/154308#issuecomment-2318512303.
origin="$HOME/Library/Logs/DiagnosticReports"

crash_files=( "$origin"/*.crash )

# Check if at least 1 matching file is found.
for file in "${crash_files[@]}"; do
  if [ -f "$file" ]; then
    cp -v "$file" "$destination"
    break
  fi
  echo "No crash files found."
  exit 0
done

echo "Crash files copied successfully"
