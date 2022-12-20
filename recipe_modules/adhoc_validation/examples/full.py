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
  validation = api.properties.get('validation', 'docs')
  env, env_prefixes = api.repo_util.flutter_environment(
      api.path['start_dir'].join('flutter sdk')
  )
  with api.context(env=env, env_prefixes=env_prefixes):
    api.adhoc_validation.run('Docs', validation, {}, {})


def GenTests(api):
  checkout_path = api.path['start_dir'].join('flutter sdk')
  yield api.test(
      'win', api.platform.name('win'),
      api.repo_util.flutter_environment_data(checkout_path)
  )
  yield api.test(
      'linux', api.platform.name('linux'),
      api.properties(firebase_project='myproject', git_branch='main'),
      api.repo_util.flutter_environment_data(checkout_path)
  )
  yield api.test(
      'mac', api.platform.name('mac'),
      api.properties(dependencies=[{"dependency": "xcode"}]),
      api.repo_util.flutter_environment_data(checkout_path)
  )
  yield api.test(
      'mac_nodeps', api.platform.name('mac'),
      api.repo_util.flutter_environment_data(checkout_path)
  )
  yield api.test(
      'invalid_validation', api.properties(validation='invalid'),
      api.expect_exception('AssertionError'),
      api.repo_util.flutter_environment_data(checkout_path)
  )
  yield api.test(
      'docs', api.platform.name('linux'),
      api.properties(firebase_project='myproject',
                     git_branch=''),
      api.repo_util.flutter_environment_data(checkout_path),
      api.step_data(
          'Docs.Identify branches.git branch',
          stdout=api.raw_io.output_text('branch1\nbranch2\nflutter-3.2-candidate.5')
      ),
      api.buildbucket.ci_build(
          project='flutter',
          bucket='flutter',
          git_repo='https://flutter.googlesource.com/mirrors/flutter',
          git_ref='refs/heads/stable',
          revision='abcd' * 10,
          build_number=123,
      ),
  )
