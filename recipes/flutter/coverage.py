# Copyright 2022 The Chromium Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

DEPS = [
    'depot_tools/gsutil',
    'flutter/flutter_deps',
    'flutter/repo_util',
    'recipe_engine/context',
    'recipe_engine/defer',
    'recipe_engine/path',
    'recipe_engine/properties',
    'recipe_engine/step',
]


def RunSteps(api):
  """Recipe to collect coverage used by the flutter tool."""
  checkout_path = api.path['start_dir'].join('flutter sdk')
  with api.step.nest('checkout source code'):
    api.repo_util.checkout(
        'flutter',
        checkout_path=checkout_path,
        url=api.properties.get('git_url'),
        ref=api.properties.get('git_ref')
    )

  env, env_prefixes = api.repo_util.flutter_environment(checkout_path)
  api.flutter_deps.required_deps(
      env, env_prefixes, api.properties.get('dependencies', [])
  )

  packages_path = checkout_path.join('packages', 'flutter')
  with api.context(env=env, env_prefixes=env_prefixes, cwd=packages_path):
    with api.step.nest('prepare environment'):
      deferred = []
      deferred.append(
          api.defer(api.step, 'flutter doctor',['flutter', 'doctor'])
      )
      deferred.append(
          api.defer(
              api.step,
              'download dependencies',
              ['flutter', 'update-packages', '-v'],
              infra_step=True,
          )
      )
      api.defer.collect(deferred)

    api.step(
        'flutter coverage',
        ['flutter', 'test', '--coverage', '-j', '1'],
    )
    lcov_path = packages_path.join('coverage', 'lcov.info')
    api.gsutil.upload(
        bucket='flutter_infra_release',
        source=lcov_path,
        dest='flutter/coverage/lcov.info',
        link_name='lcov.info',
        multithreaded=True,
        name='upload lcov.info',
        unauthenticated_url=True
    )


def GenTests(api):
  yield api.test('coverage', api.repo_util.flutter_environment_data())
