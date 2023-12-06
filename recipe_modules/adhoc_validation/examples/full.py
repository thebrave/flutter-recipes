# Copyright 2020 The Chromium Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

from recipe_engine.post_process import DoesNotRun, Filter, StatusFailure

DEPS = [
    'flutter/adhoc_validation',
    'flutter/repo_util',
    'recipe_engine/buildbucket',
    'recipe_engine/context',
    'recipe_engine/path',
    'recipe_engine/platform',
    'recipe_engine/properties',
    'recipe_engine/raw_io',
    'recipe_engine/runtime',
]


def RunSteps(api):
  validation = api.properties.get('validation', 'verify_binaries_codesigned')
  env, env_prefixes = api.repo_util.flutter_environment(
      api.path['start_dir'].join('flutter sdk')
  )
  with api.context(env=env, env_prefixes=env_prefixes):
    api.adhoc_validation.run('verify_binaries_codesigned', validation, {}, {})


def GenTests(api):
  checkout_path = api.path['start_dir'].join('flutter sdk')
  yield api.test(
      'mac', api.platform.name('mac'),
      api.properties(**{'$flutter/osx_sdk': {'sdk_version': 'deadbeef',}},),
      api.repo_util.flutter_environment_data(checkout_path)
  )
  yield api.test(
      'invalid_validation', api.properties(validation='invalid'),
      api.expect_exception('AssertionError'),
      api.repo_util.flutter_environment_data(checkout_path)
  )
