# Copyright 2020 The Chromium Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

from recipe_engine.post_process import DoesNotRun, Filter, StatusFailure

DEPS = [
    'flutter/build_util',
    'recipe_engine/context',
    'recipe_engine/path',
    'recipe_engine/platform',
    'recipe_engine/properties',
]


def RunSteps(api):
  checkout = api.path['start_dir']
  env_prefixes = {}
  with api.context(env_prefixes=env_prefixes):
    api.build_util.run_gn([], checkout)
    api.build_util.build(
        'profile', checkout, ['mytarget'], {
            'CLANG_CRASH_DIAGNOSTICS_DIR': api.path['start_dir'],
            'FLUTTER_LOGS_DIR': api.path['start_dir']
        }
    )
  with api.context(env_prefixes=env_prefixes):
    api.build_util.run_gn(['--no-goma'], checkout)
    api.build_util.build(
        'release', checkout, ['mytarget'], {
            'CLANG_CRASH_DIAGNOSTICS_DIR': api.path['start_dir'],
            'FLUTTER_LOGS_DIR': api.path['start_dir']
        }
    )
  with api.context(env_prefixes=env_prefixes):
    api.build_util.run_gn(['--no-goma', '--rbe'], checkout)
    api.build_util.build(
        'release',
        checkout,
        ['mytarget'],
        {
            'CLANG_CRASH_DIAGNOSTICS_DIR': api.path['start_dir'],
            'FLUTTER_LOGS_DIR': api.path['start_dir']
        },
        rbe_working_path=api.path["cleanup"].join("rbe"),
    )


def GenTests(api):
  yield api.test('basic', api.properties(no_lto=True))
  yield api.test(
      'basic_crash',
      api.properties(no_lto=True),
      api.step_data(
          'build profile mytarget',
          retcode=1,
      ),
      api.path.exists(api.path['start_dir'].join('foo.sh')),
      status='FAILURE',
  )
  yield api.test(
      'win',
      api.properties(no_lto=True),
      api.platform('win', 64),
      api.step_data(
          'build release mytarget',
          retcode=1,
      ),
      status='FAILURE',
  )
  yield api.test('mac', api.properties(no_lto=True), api.platform('mac', 64))
