# Copyright 2021 The Flutter Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Recipe for testing LUCI configs."""

PYTHON_VERSION_COMPATIBILITY = 'PY3'

DEPS = [
    'fuchsia/git',
    'fuchsia/git_checkout',
    'recipe_engine/buildbucket',
    'recipe_engine/context',
    'recipe_engine/path',
    'recipe_engine/step',
]


def RunSteps(api):
  start_path = api.path['start_dir']
  infra_path = start_path.join('infra')
  # Checkout flutter/infra
  api.git_checkout('https://flutter.googlesource.com/infra', path=infra_path)
  with api.context(cwd=infra_path):
    api.git('log', 'log', '--oneline', '-n', '10')
  # Validate LUCI config
  config_path = infra_path.join('config', 'main.star')
  api.step(
      'lucicfg validate',
      ['lucicfg', 'validate', '-fail-on-warnings', config_path],
  )


def GenTests(api):
  yield api.test('basic')
  yield api.test(
      'cq',
      api.buildbucket.try_build(
          git_repo='https://flutter.googlesource.com/recipes'
      )
  )
