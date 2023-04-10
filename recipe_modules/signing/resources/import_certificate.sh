#!/bin/bash

# Helper script to import a flutter p12 identity.
# Note: do not enable -x to display expanded values of the variables, as this will leak the passwords.
set -e

RAW_PASSWORD=$(cat $FLUTTER_P12_PASSWORD)
# Only filepath with a .p12 suffix will be recognized
mv $FLUTTER_P12 $P12_SUFFIX_FILEPATH
/usr/bin/security import $P12_SUFFIX_FILEPATH -k build.keychain -P $RAW_PASSWORD -T $CODESIGN_PATH -T /usr/bin/codesign