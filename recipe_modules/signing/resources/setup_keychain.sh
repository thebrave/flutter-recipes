#!/bin/bash
# Copyright 2024 The Flutter Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

# Helper script to import a flutter p12 identity.
# Note: do not enable -x to display expanded values of the variables, as this will leak the passwords.
set -e

RAW_PASSWORD=$(cat $FLUTTER_P12_PASSWORD)
# Only filepath with a .p12 suffix will be recognized
mv $FLUTTER_P12 $P12_SUFFIX_FILEPATH

# Delete build.keychain if it exists, do no-op if not exist.
if /usr/bin/security delete-keychain build.keychain; then
  :
fi
# Create build.keychain.
/usr/bin/security create-keychain -p '' build.keychain

# Retrieve current list of keychains on the search list of current machine.
keychains=$(security list-keychains -d user)

keychainNames=();

for keychain in $keychains
do
  basename=$(basename "$keychain")
  keychainName=${basename::${#basename}-4}
  keychainNames+=("$keychainName")
done

echo "User keychains on this machine: ${keychainNames[@]}";

# Add keychain name to search list. (FML, took me 5 days to hunt this down)
/usr/bin/security -v list-keychains -s "${keychainNames[@]}" build.keychain

# Set build.keychain as default.
/usr/bin/security default-keychain -s build.keychain

# Unlock build.keychain to allow sign commands to use its certs.
/usr/bin/security unlock-keychain -p '' build.keychain

attempt=0
sleep_time=2
while [ $attempt -lt 3 ]; do
   /usr/bin/security import $P12_SUFFIX_FILEPATH -k build.keychain -P $RAW_PASSWORD -T $CODESIGN_PATH -T /usr/bin/codesign
   /usr/bin/security set-key-partition-list -S apple-tool:,apple:,codesign: -s -k '' build.keychain
   if /usr/bin/security find-identity -v build.keychain | grep 'FLUTTER.IO LLC'; then
     exit 0
   fi
   sleep $sleep_time
   attempt=$(( attempt + 1 ))
   sleep_time=$(( sleep_time * sleep_time ))
done
exit 1