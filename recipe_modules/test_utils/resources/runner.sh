#!/bin/bash

# Helper script to run tests saving the output to a file.
set -e

args=( "$@" )
"${args[@]}" 2>&1 | tee $LOGS_FILE
