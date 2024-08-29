#!/bin/bash
# Copyright 2024 The Flutter Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

# Helper script to copy mobileprovisioning profile to
# bot's default location.
set -e

# The first argument is the destination directory to copy any crash files to.
destination=$1

# Crash files are stored in this directory.
# See https://github.com/flutter/flutter/issues/154308#issuecomment-2318512303.
origin="$HOME/Library/Logs/DiagnosticReports/"

crash_files=( "$origin"/*.crash )
if [ ${#crash_files[@]} -gt 0 ]; then
  cp "${crash_files[@]}" "$destination"/.
  echo "Crash files copied successfully."
else
  echo "No crash files found."
fi
