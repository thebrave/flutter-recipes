#!/bin/bash
# Copyright 2024 The Flutter Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

# Helper script to run tests saving the output to a file.
set -e

args=( "$@" )
set -o pipefail
"${args[@]}" 2>&1 | tee $LOGS_FILE
