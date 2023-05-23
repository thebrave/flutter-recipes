# Copyright 2023 The Chromium Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

import datetime

DEPS = [
    'flutter/cache',
    'recipe_engine/assertions',
    'recipe_engine/json',
]


def RunSteps(api):
  result = api.cache.requires_refresh('builder')
  api.assertions.assertFalse(result)


def GenTests(api):
  metadata = {
      'last_cache_ts_micro_seconds':
          1684900396429444,
      'cache_ttl_microseconds':
          3600 * 60 * 60
  }
  yield api.test(
      'basic', api.step_data(
          'gsutil cat',
          stdout=api.json.output(metadata),
      )
  )
