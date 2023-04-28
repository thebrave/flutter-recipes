# Copyright 2018 The Chromium Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

DEPS = [
    'flutter/os_utils',
    'flutter/osx_sdk',
    'recipe_engine/file',
    'recipe_engine/path',
    'recipe_engine/platform',
    'recipe_engine/properties',
    'recipe_engine/step',
]


def RunSteps(api):
  with api.osx_sdk('mac'):
    api.step('gn', ['gn', 'gen', 'out/Release'])
    api.step('ninja', ['ninja', '-C', 'out/Release'])


def GenTests(api):
  for platform in ('linux', 'mac', 'win'):
    yield (api.test(platform) + api.platform.name(platform))

  yield api.test(
      'explicit_version', api.platform.name('mac'),
      api.properties(
          **{
              '$flutter/osx_sdk': {
                  'sdk_version': 'deadbeef', 'toolchain_ver': '123abc',
                  'cleanup_cache': True
              }
          }
      )
  )

  runtime_path = api.path['cache'].join(
      'osx_sdk', 'xcode_deadbeef_runtime_ios-14-0_ios-13-0', 'XCode.app',
      'Contents', 'Developer', 'Platforms', 'iPhoneOS.platform', 'Library',
      'Developer', 'CoreSimulator', 'Profiles', 'Runtimes',
      'iOS 13.0.simruntime'
  )

  sdk_app_path = api.path['cache'].join(
      'osx_sdk', 'xcode_deadbeef', 'XCode.app'
  )

  yield api.test(
      'explicit_runtime_version',
      api.platform.name('mac'),
      api.properties(
          **{
              '$flutter/osx_sdk': {
                  'sdk_version': 'deadbeef', 'toolchain_ver': '123abc',
                  'runtime_versions': ['ios-13-0', 'ios-14-0']
              }
          }
      ),
      api.os_utils.is_symlink(False),
      api.path.exists(runtime_path),
  )

  runtime_path = api.path['cache'].join(
      'osx_sdk', 'xcode_deadbeef', 'XCode.app', 'Contents', 'Developer',
      'Platforms', 'iPhoneOS.platform', 'Library', 'Developer', 'CoreSimulator',
      'Profiles', 'Runtimes', 'iOS.simruntime'
  )

  yield api.test(
      'no_runtime_version',
      api.platform.name('mac'),
      api.properties(
          **{
              '$flutter/osx_sdk': {
                  'sdk_version': 'deadbeef',
                  'toolchain_ver': '123abc',
              }
          }
      ),
      api.os_utils.is_symlink(False),
      api.path.exists(runtime_path),
      api.path.exists(sdk_app_path),
  )

  yield api.test(
      'automatic_version',
      api.platform.name('mac'),
      api.platform.mac_release('10.15.6'),
  )

  yield api.test(
      'ancient_version',
      api.platform.name('mac'),
      api.platform.mac_release('10.1.0'),
  )
