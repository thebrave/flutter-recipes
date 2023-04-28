# Copyright 2019 The Fuchsia Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

# Must keep this file or else recipe engine complains that StatusApi has no
# test coverage.

DEPS = [
    "flutter/status_check",
]


def RunSteps(api):
  del api  # Unused.


def GenTests(api):
  yield api.status_check.test("basic", status="success")
