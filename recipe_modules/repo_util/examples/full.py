# Copyright 2020 The Chromium Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

PYTHON_VERSION_COMPATIBILITY = 'PY3'

DEPS = [
    'flutter/repo_util',
    'recipe_engine/context',
    'recipe_engine/path',
    'recipe_engine/properties',
    'recipe_engine/raw_io',
]


def RunSteps(api):
  flutter_checkout_path = api.path['start_dir'].join('flutter')
  api.repo_util.get_branch(flutter_checkout_path)
  api.repo_util.checkout('flutter', flutter_checkout_path, ref='refs/heads/master')
  api.repo_util.checkout('engine', api.path['start_dir'].join('engine'), ref='refs/heads/main')
  api.repo_util.checkout('cocoon', api.path['start_dir'].join('cocoon'), ref='refs/heads/main')
  api.repo_util.checkout('packages', api.path['start_dir'].join('packages'), ref='refs/heads/main')
  # we need an override because all of the previous step calls on checkout directly overrides the ref variable
  api.repo_util.checkout('flutter', flutter_checkout_path, ref= 'refs/heads/beta')

  env, env_paths = api.repo_util.engine_environment(flutter_checkout_path)
  env, env_paths = api.repo_util.flutter_environment(flutter_checkout_path)
  api.repo_util.in_release_and_main(flutter_checkout_path)
  api.repo_util.engine_checkout(api.path['start_dir'].join('engine'), {}, {})
  with api.context(env=env, env_prefixes=env_paths):
    api.repo_util.sdk_checkout_path()


def GenTests(api):
  yield (
      api.test(
          'basic',
          api.properties(git_branch='beta'),
          api.repo_util.flutter_environment_data(),
          api.step_data('Identify branches.git rev-parse', stdout=api.raw_io.output_text('abchash')),
          api.step_data('Identify branches.git branch', stdout=api.raw_io.output_text('branch1\nbranch2')),
          api.step_data('Identify branches (2).git branch', stdout=api.raw_io.output_text('branch1\nbranch2')),
          api.step_data('Identify branches (3).git branch', stdout=api.raw_io.output_text('branch1\nbranch2')))
  )
  yield api.test('failed_flutter_environment')
  yield (
      api.test(
          'first_bot_update_failed',
          api.properties(
              git_url='https://github.com/flutter/engine',
              git_ref='refs/pull/1/head'
          )
      ) +
      # Next line force a fail condition for the bot update
      # first execution.
      api.step_data("Checkout source code.bot_update", retcode=1) +
      api.repo_util.flutter_environment_data()
  )
