#!/bin/bash

# Copyright 2020 The Chromium Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.
#
# Script to ensure the avd is set up for testing.
#
# Usage: ./avd_setup.sh <path-to-adb-executable>

set -x

# Monitor but it appears the device is always ready within a couple seconds.
readonly WAIT_ITERS=60

function wait_for_device_ready() {
    local adb=${1}

    local ready=1
    # Wait for avd to reach home screen
    for((i=0; i<${WAIT_ITERS}; i++)); do
        out=$(${adb} -s emulator-5554 shell 'getprop sys.boot_completed' | tr -d '[:space:]')
        if [[ "${out}" = "1" ]]; then
            echo "Device is ready."
            ready=0
            break
        else
            echo "Device is not ready."
            echo "output: ${out}"
            sleep 1
        fi
    done

    if [[ ${ready} -eq 1 ]]; then
        echo "Device was not ready in time."
        exit 1
    fi
}

# path to the adb executable
adb=${1}

which ${adb}
if [[ $? -eq 1 ]]; then
    echo "Unable to locate adb on path."
fi

# when you run any adb command and the server is not up it will start it.
${adb} start-server
${adb} devices
${adb} wait-for-device
wait_for_device_ready ${adb}
${adb} devices
# Set the density DPI
${adb} shell wm density 400
# unlock avd
${adb} shell input keyevent 82
# Ensure developer mode is enabled
${adb} shell settings put global development_settings_enabled 1
# Enable MTP file transfer
${adb} shell svc usb setFunctions mtp
# Wait for device to boot and unlock device's screen.
wait_for_device_ready ${adb}
${adb} shell input keyevent 82

# clear exit signal for the LUCI ci.
echo "Emulator ready."
exit 0