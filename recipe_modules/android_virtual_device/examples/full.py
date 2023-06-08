# Copyright 2020 The Chromium Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

DEPS = [
    'flutter/android_virtual_device', 'recipe_engine/path',
    'recipe_engine/raw_io', 'recipe_engine/step', 'recipe_engine/properties'
]


def RunSteps(api):
  env = {'USE_EMULATOR': api.properties.get('use_emulator', False)}
  env_prefixes = {}
  avd_root = api.path['cache'].join('builder', 'avd')
  api.android_virtual_device.download(
      avd_root=avd_root, env=env, env_prefixes=env_prefixes, version='31'
  )
  with api.android_virtual_device(env=env, env_prefixes=env_prefixes,
                                  version="31"):
    api.step('Do something', ['echo', 'hello'])


def GenTests(api):
  avd_api_version = '31'

  yield api.test(
      'emulator started',
      api.properties(use_emulator="true"),
      api.step_data(
          'start avd.Start Android emulator (API level %s)' % avd_api_version,
          stdout=api.raw_io.output_text(
              'android_' + avd_api_version +
              '_google_apis_x86|emulator-5554 started (pid: 17687)'
          )
      ),
  )

  yield api.test(
      'emulator started and stopped, processes killed',
      api.properties(use_emulator="true"),
      api.step_data(
          'start avd.Start Android emulator (API level %s)' % avd_api_version,
          stdout=api.raw_io.output_text(
              'android_' + avd_api_version +
              '_google_apis_x86|emulator-5554 started (pid: 17687)'
          )
      ),
      api.step_data(
          'kill and cleanup avd.list processes',
          stdout=api.raw_io.output_text('12345 qemu-system blah')
      ),
  )
