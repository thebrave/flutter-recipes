#!/bin/bash

# Copyright 2020 The Chromium Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.
#
# Script to ensure the avd is set up for testing.
#
# Usage: ./avd_setup.sh <path-to-adb-executable>

$1 kill-server
$1 start-server
$1 wait-for-device
# Wait for avd to reach home screen
$1 -s emulator-5554 shell 'while [[ -z $(getprop sys.boot_completed) ]]; do sleep 1; done;'
$1 devices
# Set the density DPI
$1 shell wm density 400
# unlock avd
$1 shell input keyevent 82
# Ensure developer mode is enabled
$1 shell settings put global development_settings_enabled 1
# Enable MTP file transfer
$1 shell svc usb setFunctions mtp
