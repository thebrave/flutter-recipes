#!/bin/bash

# Copyright 2020 The Chromium Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

set -e

# Customer testing require both master and the branch
# under test to be checkout out.
if [$GIT_BRANCH != 'master']
then
  git fetch origin master
  git checkout master
fi

git fetch origin $GIT_BRANCH:$GIT_BRANCH
git checkout $GIT_BRANCH
cd dev/customer_testing/
bash ci.sh
