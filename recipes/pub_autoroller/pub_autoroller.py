# Copyright 2016 The Chromium Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

DEPS = [
    'flutter/flutter_deps',
    'flutter/kms',
    'flutter/repo_util',
    'recipe_engine/context',
    'recipe_engine/path',
    'recipe_engine/platform',
    'recipe_engine/properties',
    'recipe_engine/step',
]


def RunSteps(api):
  assert api.platform.is_linux, 'This recipe should only be run once per commit, on Linux'
  checkout_path = api.path.start_dir.join('flutter')
  api.repo_util.checkout(
      'flutter',
      checkout_path=checkout_path,
      # If either of these are None, repo_util.checkout will fall back to sane
      # default
      url=api.properties.get('git_url'),
      ref=api.properties.get('git_ref'),
  )
  env, env_prefixes = api.repo_util.flutter_environment(checkout_path)
  api.flutter_deps.required_deps(
      env,
      env_prefixes,
      api.properties.get('dependencies', []),
  )
  conductor_dir = checkout_path.join('dev', 'conductor')
  with api.context(env=env, env_prefixes=env_prefixes, cwd=conductor_dir):
    roll_packages(api, conductor_dir)


def roll_packages(api, conductor_dir):
  token_file = conductor_dir.join('token.txt')
  api.kms.get_secret('pub-roller-github-token.encrypted', token_file)
  autoroll_script = conductor_dir.join(
      'bin',
      'packages_autoroller',
  )
  api.step(
      'run roll-packages script', [
          autoroll_script,
          '--token',
          token_file,
      ]
  )


def GenTests(api):
  yield api.test(
      'roll',
      api.repo_util.flutter_environment_data(),
  )
