# Copyright 2020 The Chromium Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

from PB.recipe_modules.recipe_engine.swarming import properties
from recipe_engine.post_process import DoesNotRun, Filter, StatusFailure

PYTHON_VERSION_COMPATIBILITY = 'PY3'

DEPS = [
    'flutter/test_utils',
    'recipe_engine/platform',
    'recipe_engine/properties',
    'recipe_engine/raw_io',
]


def RunSteps(api):
  api.test_utils.run_test('mytest', ['ls', '-la'])
  api.test_utils.is_devicelab_bot()
  api.test_utils.test_step_name('test')
  api.test_utils.flaky_step('test step')
  env = {}
  env_prefixes = {}
  target_tags = api.properties.get("tags")
  api.test_utils.collect_benchmark_tags(env, env_prefixes, target_tags)


def GenTests(api):
  yield api.test(
      'passing',
      api.step_data(
          'mytest',
          stdout=api.raw_io.output_text('#success\nthis is a success'),
      ),
      api.platform.name('win'),
      api.properties(tags=['hostonly']),
  )
  yield api.test(
      'passing-mac',
      api.step_data(
          'mytest',
          stdout=api.raw_io.output_text('#success\nthis is a success'),
      ),
      api.platform.name('mac'),
      api.properties(tags=['ios']),
      api.step_data(
          'Find device type',
          stdout=api.raw_io.output_text('iPhone8,1'),
      ),
      api.step_data(
          'Find device version',
          stdout=api.raw_io.output_text('14'),
      ),
  )
  yield api.test(
      'flaky',
      api.step_data(
          'mytest',
          stdout=api.raw_io.output_text('#flaky\nthis is a flaky\nflaky: true'),
      ),
      api.properties(tags=['hostonly', 'android']),
      api.platform.name('linux'),
      api.step_data(
          'Find debian version',
          stdout=api.raw_io.output_text('10'),
      ),
  )
  yield api.test(
      'failing',
      api.step_data(
          'mytest',
          stdout=api.raw_io.output_text('#failure\nthis is a failure'),
          retcode=1
      )
  )
  very_long_string = "xyz\n" * 1500
  yield api.test(
      'long_stdout',
      api.step_data(
          'mytest', stdout=api.raw_io.output_text(very_long_string), retcode=1
      )
  )
