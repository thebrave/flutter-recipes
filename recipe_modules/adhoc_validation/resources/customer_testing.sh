#!/bin/bash

# Copyright 2020 The Chromium Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

set -e

# Customer testing require both master and the branch
# under test to be checkout out.

git fetch origin master
git checkout master
git checkout $REVISION
cd dev/customer_testing/
bash ci.sh
