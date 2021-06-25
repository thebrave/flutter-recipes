# Copyright 2021 The Flutter Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Recipe for testing LUCI configs."""

DEPS = [
    'flutter/repo_util',
    'recipe_engine/cipd',
    'recipe_engine/context',
    'recipe_engine/file',
    'recipe_engine/path',
    'recipe_engine/platform',
    'recipe_engine/properties',
    'recipe_engine/step',
]


def RunSteps(api):
  start_path = api.path['start_dir']
  infra_path = start_path.join('infra')
  # Checkout flutter/infra
  api.repo_util.checkout(
      'infra',
      infra_path,
      url=api.properties.get('git_url'),
      ref=api.properties.get('git_ref')
  )
  # Validate LUCI config
  config_path = infra_path.join('config', 'main.star')
  api.step(
      'lucicfg validate',
      ['lucicfg', 'validate', '-fail-on-warnings', config_path],
  )


def GenTests(api):
  yield api.test(
      'basic', api.platform('linux', 64),
      api.properties(
          git_url='https://flutter.googlesource.com/flutter/infra',
          git_ref='abc'
      ), api.repo_util.flutter_environment_data()
  )
