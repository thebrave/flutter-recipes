#!/bin/bash
# Copyright 2024 The Flutter Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

# Helper script to copy mobileprovisioning profile to
# bot's default location.
set -e

mobileprovision_profile=$1
destination="$HOME/Library/MobileDevice/Provisioning Profiles"
uuid=$(/usr/libexec/PlistBuddy -c 'Print UUID' /dev/stdin <<< $(security cms -D -i "$mobileprovision_profile"))
mkdir -p "$destination"
if [ ! -f "$destination"/"$uuid".mobileprovision ]; then
  cp "$mobileprovision_profile" "$destination"/"$uuid".mobileprovision
fi