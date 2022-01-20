#!/bin/bash

# Validate verify binaries are codesigned.

set -e

# Checking out master here is ok even though this test runs on release branches
# because the checkout is used only to download the conductor tool but the validation
# is run on the binaries for the commit passed as property to the builder.
git fetch origin master:master

# Run the actual validation.
./dev/conductor/bin/conductor codesign --verify
