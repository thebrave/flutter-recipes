#!/bin/bash

# Copyright 2022 The Chromium Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.
#
# Script to generate and upload flutter docs.

set -e

dart ./dev/bots/post_process_docs.dart
