# Copyright 2019 The Chromium Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

# Recipe to validate test ownership.
#
# Validates tests defined in `.ci.yaml` have corresponding ownership in `TESTOWNERS`.
# This supports only flutter/flutter repo for now, but can be easily extended to
# other repos in the future.
#
# The pre-submit `sha` and `repo` are needed for validation. Violated builders will
# be returned in stdout when ownership is missing.

DEPS = [
    'depot_tools/git',
    'flutter/repo_util',
    'recipe_engine/buildbucket',
    'recipe_engine/context',
    'recipe_engine/json',
    'recipe_engine/path',
    'recipe_engine/properties',
    'recipe_engine/raw_io',
    'recipe_engine/runtime',
    'recipe_engine/step',
]


def RunSteps(api):
  """Steps to checkout cocoon, dependencies and execute tests."""
  start_path = api.path['start_dir']
  cocoon_path = start_path.join('cocoon')
  flutter_path = start_path.join('flutter')

  repo = api.properties.get("git_repo")
  with api.step.nest('checkout source code'):
    # Checkout flutter/flutter at head.
    commit_sha = api.repo_util.checkout(
        repo,
        checkout_path=flutter_path,
        url=api.properties.get('git_url'),
        ref=api.properties.get('git_ref')
    )
    # Checkout latest version of flutter/cocoon.
    api.repo_util.checkout('cocoon', cocoon_path, ref='refs/heads/master')

  # The context adds dart-sdk tools to PATH and sets PUB_CACHE.
  env, env_prefixes = api.repo_util.flutter_environment(flutter_path)

  with api.context(env=env, env_prefixes=env_prefixes,
                   cwd=cocoon_path.join('app_dart')):
    api.step('flutter doctor', cmd=['flutter', 'doctor'])
    api.step('pub get', cmd=['pub', 'get'])
    validate_task_owernship_path = cocoon_path.join(
        'app_dart', 'bin', 'validate_task_ownership.dart'
    )
    api.step(
        'validate test ownership',
        cmd=[
            'dart',
            validate_task_owernship_path,
            repo,
            commit_sha,
        ],
    )


def GenTests(api):
  yield api.test(
      'basic',
      api.repo_util.flutter_environment_data(
          api.path['start_dir'].join('flutter')
      ),
      api.properties(
          git_ref='refs/pull/123/head',
          git_url='https://abc.com/flutter',
          git_repo='flutter',
      )
  )
