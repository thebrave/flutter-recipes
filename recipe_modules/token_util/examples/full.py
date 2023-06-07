# Copyright 2020 The Chromium Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

from recipe_engine.recipe_api import Property

DEPS = [
    'flutter/token_util',
]


def RunSteps(api):
  with api.token_util.metric_center_token({}, {}):
    pass
  api.token_util.cocoon_token()


def GenTests(api):
  yield api.test('basic')
