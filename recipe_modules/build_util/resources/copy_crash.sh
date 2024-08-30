#!/bin/bash
# Copyright 2024 The Flutter Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

# Helper script to copy mobileprovisioning profile to
# bot's default location.
set -e

destination=$1
origin="$HOME/Library/Logs/DiagnosticReports/"
if [ -f "$origin"/llvm_*.crash ]; then
  cp "$origin"/llvm_*.crash "$destination"/.
fi