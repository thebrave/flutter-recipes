# Copyright 2020 The Chromium Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

DEPS = [
    'android_virtual_device',
    'recipe_engine/context',
    'recipe_engine/path',
    'recipe_engine/properties',
    'recipe_engine/raw_io',
    'recipe_engine/step',
]

def RunSteps(api):
  env = {}
  env_prefixes = {}
  avd_root = api.path['cache'].join('builder', 'avd')
  api.android_virtual_device.download(
      avd_root=avd_root,
      env=env,
      env_prefixes=env_prefixes,
      version='31'
  )
  api.android_virtual_device.start(
      env=env,
      env_prefixes=env_prefixes,
  )
  api.android_virtual_device.setup(
      env=env,
      env_prefixes=env_prefixes,
  )
  api.android_virtual_device.kill()


def GenTests(api):
  avd_api_version = '31'
  yield api.test(
    'demo',
    api.step_data(
        'start avd.Start Android emulator (API level %s)' % avd_api_version,
        stdout=api.raw_io.output_text(
            'android_' + avd_api_version + '_google_apis_x86|emulator-5554 started (pid: 17687)'
        )
    ),
  )
  yield api.test(
    'demo zombie processes',
    api.step_data(
        'start avd.Start Android emulator (API level %s)' % avd_api_version,
        stdout=api.raw_io.output_text(
            'android_' + avd_api_version + '_google_apis_x86|emulator-5554 started (pid: 17687)'
        )
    ),
    api.step_data(
          'kill and cleanup avd.list processes',
          stdout=api.raw_io.output_text(
              '12345 qemu-system blah'
          )
      ),
  )
