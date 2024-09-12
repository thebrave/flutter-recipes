#!/bin/bash
# Copyright 2024 The Flutter Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

# On Mac OS, readlink -f doesn't work, so follow_links traverses the path one
# link at a time, and then cds into the link destination and find out where it
# ends up.
#
# The returned filesystem path must be a format usable by Dart's URI parser,
# since the Dart command line tool treats its argument as a file URI, not a
# filename. For instance, multiple consecutive slashes should be reduced to a
# single slash, since double-slashes indicate a URI "authority", and these are
# supposed to be filenames. There is an edge case where this will return
# multiple slashes: when the input resolves to the root directory. However, if
# that were the case, we wouldn't be running this shell, so we don't do anything
# about it.
#
# The function is enclosed in a subshell to avoid changing the working directory
# of the caller.
function follow_links() (
  cd -P "$(dirname -- "$1")"
  file="$PWD/$(basename -- "$1")"
  while [[ -L "$file" ]]; do
    cd -P "$(dirname -- "$file")"
    file="$(readlink -- "$file")"
    cd -P "$(dirname -- "$file")"
    file="$PWD/$(basename -- "$file")"
  done
  echo "$file"
)

PROG_NAME="$(follow_links "${BASH_SOURCE[0]}")"

# Find the ./copy_crash.sh script.
copy_crash_script="$(dirname "$PROG_NAME")/copy_crash.sh"

# Tests that `./copy_crash.sh`:
# 1. Prints "No crash files found" if no files are in "$HOME/Library/Logs/DiagnosticReports".
# 2. Copies all files in "$HOME/Library/Logs/DiagnosticReports" to the destination directory if there are any.

# Create a temporary directory to pretend to be a HOME directory.
temp_home=$(mktemp -d)

# Set a trap to delete the temporary directory when the script exits.
trap 'rm -rf $temp_home' EXIT

# Create a temporary directory to pretend to be the destination directory.
temp_destination=$(mktemp -d)

# Set a trap to delete the temporary directory when the script exits.
trap 'rm -rf $temp_destination' EXIT

# Run the script with the temporary directories and assert the output.
output=$(HOME=$temp_home $copy_crash_script $temp_destination)
expected_output="No crash files found."
if [ "$output" != "$expected_output" ]; then
  echo "[FAIL]: Expected output does not match actual output."
  echo "Expected output: $expected_output"
  echo "Actual output: $output"
  exit 1
fi
echo "[PASS]: No crash files found."

# Create the directory where crash files are stored.
mkdir -p $temp_home/Library/Logs/DiagnosticReports

# Create a temporary crash file.
temp_crash_file=$(mktemp $temp_home/Library/Logs/DiagnosticReports/crash.XXXXXX.crash)

# Run the script with the temporary directories and assert the output.
output=$(HOME=$temp_home $copy_crash_script $temp_destination)
expected_output="Crash files copied successfully."

# Check that the crash file was copied to the destination directory.
if [ ! -f $temp_destination/crash.XXXXXX.crash ]; then
  echo "[FAIL]: Crash file not found in destination directory."
  echo "Contents of destination directory:"
  ls -l $temp_destination
  echo "Output of the script:"
  echo $output
  exit 1
fi
echo "[PASS]: Crash file found in destination directory."
