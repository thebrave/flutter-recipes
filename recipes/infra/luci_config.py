# Copyright 2021 The Flutter Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Recipe for testing LUCI configs."""

DEPS = [
    'fuchsia/git',
    'recipe_engine/buildbucket',
    'recipe_engine/context',
    'recipe_engine/path',
    'recipe_engine/step',
]


def RunSteps(api):
  start_path = api.path['start_dir']
  infra_path = start_path.join('infra')
  # Checkout flutter/infra
  bb_input = api.buildbucket.build.input
  if bb_input.gerrit_changes:
    api.git.checkout_cl(
        bb_input.gerrit_changes[0], infra_path, onto='refs/heads/main'
    )
  else:
    api.git.checkout(
        'https://flutter.googlesource.com/infra', ref='refs/heads/main'
    )
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
