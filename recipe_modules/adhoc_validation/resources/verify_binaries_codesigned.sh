#!/bin/bash

# Validate verify binaries are codesigned.

set -e

./dev/conductor/bin/conductor codesign --verify
