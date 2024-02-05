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

# Validate a single config is returning the desired value.
function validate_config() {
    local adb=${1}
    local config=${2}
    local exp_return_value=${3}

    local ready=1
    # Wait for avd to reach home screen
    echo "Checking ${config} is returning ${exp_return_value}."

    for((i=0; i<${WAIT_ITERS}; i++)); do
        out=$(${adb} -s emulator-5554 shell "getprop ${config}" | tr -d '[:space:]')
        if [[ "${out}" = "${exp_return_value}" ]]; then
            echo "${config} is ready."
            ready=0
            break
        else
            echo "Config ${config} is not ready."
            echo "output: ${out}"
            sleep 1
        fi
    done

    if [[ ${ready} -eq 1 ]]; then
        echo "${config} was not ready in time."
        return 1
    fi

    return 0
}

# Validate an array of configs is returning their desired values.
function validate_all_configs() {
    local adb=$1; shift
    local config_array=("$@")
    for config in "${config_array[@]}"; do
        validate_config "${adb}" "${config}" "1"
        if [[ $? -ne 0 ]]; then
            echo "Config ${config} not ready."
            exit 1
        fi
    done
}

function print_device_list() {
    local adb=${1}
    local devices_output=$(${adb} devices)
    echo ""
    echo "${devices_output}"
    echo ""
}

function wait-for-device() {
    local remaining_attempts=20
    until adb shell true
    do
      ((remaining_attempts--))
      if [[ remaining_attempts -le 0 ]]
      then
        echo "Emulator not found"
        exit 1
      fi
      echo "Waiting for emulator to be available. Remaining attempts: $remaining_attempts"
      sleep 10
    done
    echo "Emulator is now available"
}

# path to the adb executable
adb=${1}

which ${adb}
if [[ $? -eq 1 ]]; then
    echo "Unable to locate adb on path."
fi

# properties to validate
declare -a configs_to_validate=("sys.boot_completed" "dev.bootcomplete")
print_device_list "${adb}"
echo "Stopping adb server"
${adb} stop-server
sleep 5
# when you run any adb command and the server is not up it will start it.
echo "Starting adb server"
${adb} start-server
print_device_list "${adb}"
echo "Waiting for device"
wait-for-device

echo "Validating that emulator is booted."
validate_all_configs "${adb}" "${configs_to_validate[@]}"

# Set the density DPI
${adb} shell wm density 400
# unlock avd
${adb} shell input keyevent 82
# Ensure developer mode is enabled
${adb} shell settings put global development_settings_enabled 1

# Enable MTP file transfer
# depending on the version under test this is setFunctions or setFunction (no s)
${adb} shell svc usb setFunction mtp

print_device_list "${adb}"

echo "Validating that emulator is booted."
validate_all_configs "${adb}" "${configs_to_validate[@]}"

${adb} shell input keyevent 82

print_device_list "${adb}"

# clear exit signal for the LUCI ci.
echo "Emulator ready."
exit 0
