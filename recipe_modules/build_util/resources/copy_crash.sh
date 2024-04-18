#!/bin/bash

# Helper script to copy mobileprovisioning profile to
# bot's default location.
set -e

destination=$1
origin="$HOME/Library/Logs/DiagnosticReports/"
if [ -f "$origin"/llvm_*.crash ]; then
  cp "$origin"/llvm_*.crash "$destination"/.
fi