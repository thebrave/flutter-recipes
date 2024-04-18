#!/bin/bash
# Copyright 2020 The Chromium Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.
#
# Script to ensure the avd is set up for testing.
#
# Usage: ./avd_setup.sh <path-to-adb-executable>

set -x

function print_device_list() {
    local adb=${1}
    local devices_output=$(${adb} devices)
    echo ""
    echo "${devices_output}"
    echo ""
}

# path to the adb executable
adb=${1}

which ${adb}
if [[ $? -eq 1 ]]; then
    echo "Unable to locate adb on path."
fi

print_device_list "${adb}"