# Copyright 2020 The Chromium Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

DEPS = [
    'flutter/android_virtual_device', 'recipe_engine/path',
    'recipe_engine/raw_io', 'recipe_engine/step', 'recipe_engine/properties'
]


def RunSteps(api):
  should_set_avd_cipd_version = api.properties.get('should_set_avd_cipd_version', True)
  env = {
      'USE_EMULATOR': api.properties.get('use_emulator', False),
      'AVD_CIPD_VERSION': 'TESTVERSIONSTR' if should_set_avd_cipd_version else None
  }
  env_prefixes = {}

  with api.android_virtual_device(env=env, env_prefixes=env_prefixes,
                                  version='android_31_google_apis_x64.textpb'):
    api.step('Do something', ['echo', 'hello'])
  # Calling a second time to ensure we have coverage for duplicated initialization.
  with api.android_virtual_device(env=env, env_prefixes=env_prefixes,
                                  version='android_31_google_apis_x64.textpb'):
    api.step('Do something', ['echo', 'hello'])


def GenTests(api):
  avd_api_version = 'android_31_google_apis_x64.textpb'

  yield api.test(
      'emulator started',
      api.properties(use_emulator="true"),
      api.properties(fake_data='fake data'),
      api.properties(should_set_avd_cipd_version=True),
      api.step_data(
          'start avd.Start Android emulator (%s)' % avd_api_version,
          stdout=api.raw_io.output_text(
              'android_' + avd_api_version +
              '_google_apis_x86|emulator-5554 started (pid: 17687)'
          )
      ),
      api.step_data(
          'start avd (2).Start Android emulator (%s)' % avd_api_version,
          stdout=api.raw_io.output_text(
              'android_' + avd_api_version +
              '_google_apis_x86|emulator-5554 started (pid: 17687)'
          )
      ),
  )

  yield api.test(
      'emulator started and stopped, processes killed',
      api.properties(use_emulator="true"),
      api.properties(fake_data='fake data'),
      api.properties(should_set_avd_cipd_version=True),
      api.step_data(
          'start avd.Start Android emulator (%s)' % avd_api_version,
          stdout=api.raw_io.output_text(
              'android_' + avd_api_version +
              '_google_apis_x86|emulator-5554 started (pid: 17687)'
          )
      ),
      api.step_data(
          'start avd (2).Start Android emulator (%s)' % avd_api_version,
          stdout=api.raw_io.output_text(
              'android_' + avd_api_version +
              '_google_apis_x86|emulator-5554 started (pid: 17687)'
          )
      ),
  )

  yield api.test(
    'emulator is not started if AVD_CIPD_VERSION not defined',
    api.properties(use_emulator="true"),
    api.properties(fake_data='fake data'),
    api.properties(should_set_avd_cipd_version=False),
    api.expect_status('INFRA_FAILURE'),
  )
