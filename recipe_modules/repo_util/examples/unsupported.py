# Copyright 2020 The Chromium Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

PYTHON_VERSION_COMPATIBILITY = 'PY2+3'

DEPS = [
    'flutter/repo_util',
    'recipe_engine/path',
]


def RunSteps(api):
  repo_dir = api.path['start_dir'].join('unsupported_repo')
  api.repo_util.checkout('unsupported_repo', repo_dir)


def GenTests(api):
  yield api.test(
      'unsupported',
      api.expect_exception('ValueError'),
  )
