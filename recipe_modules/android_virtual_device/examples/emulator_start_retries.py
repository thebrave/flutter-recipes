# Copyright 2020 The Chromium Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

DEPS = [
    'flutter/android_virtual_device', 'recipe_engine/path',
    'recipe_engine/raw_io', 'recipe_engine/step', 'recipe_engine/properties'
]


def RunSteps(api):
  env = {
      'USE_EMULATOR': api.properties.get('use_emulator', False),
      'AVD_CIPD_VERSION': 'TESTVERSIONSTR'
  }
  env_prefixes = {}

  with api.android_virtual_device(env=env, env_prefixes=env_prefixes,
                                  version='android_31_google_apis_x64.textpb'):
    api.step('Do something', ['echo', 'hello'])


def GenTests(api):
  avd_api_version = 'android_31_google_apis_x64.textpb'

  yield api.test(
      'setup_avd_fails',
      api.properties(use_emulator="true", fake_data='fake data'),
      api.step_data(
          'start avd.Start Android emulator (%s)' % avd_api_version,
          stdout=api.raw_io.output_text(
              'android_' + avd_api_version +
              '_google_apis_x86|emulator-5554 started (pid: 17687)'
          )
      ),
      api.step_data(
          'start avd.Start Android emulator (%s) (2)' % avd_api_version,
          stdout=api.raw_io.output_text(
              'android_' + avd_api_version +
              '_google_apis_x86|emulator-5554 started (pid: 17687)'
          )
      ),
      api.step_data(
          'start avd.Start Android emulator (%s) (3)' % avd_api_version,
          stdout=api.raw_io.output_text(
              'android_' + avd_api_version +
              '_google_apis_x86|emulator-5554 started (pid: 17687)'
          )
      ),
      api.step_data('start avd.avd setup.avd_setup.sh', retcode=1),
      api.step_data('start avd.avd setup (2).avd_setup.sh', retcode=1),
      api.step_data('start avd.avd setup (3).avd_setup.sh', retcode=1),
      status='INFRA_FAILURE'
  )
  yield api.test(
      'setup_avd_pass_on_retry',
      api.properties(use_emulator="true", fake_data='fake data'),
      api.step_data(
          'start avd.Start Android emulator (%s)' % avd_api_version,
          stdout=api.raw_io.output_text(
              'android_' + avd_api_version +
              '_google_apis_x86|emulator-5554 started (pid: 17687)'
          )
      ),
      api.step_data(
          'start avd.Start Android emulator (%s) (2)' % avd_api_version,
          stdout=api.raw_io.output_text(
              'android_' + avd_api_version +
              '_google_apis_x86|emulator-5554 started (pid: 17687)'
          )
      ),
      api.step_data('start avd.avd setup.avd_setup.sh', retcode=1),
      status='SUCCESS'
  )
