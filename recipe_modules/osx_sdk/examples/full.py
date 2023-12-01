# Copyright 2018 The Chromium Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

DEPS = [
    'flutter/os_utils',
    'flutter/osx_sdk',
    'flutter/retry',
    'recipe_engine/file',
    'recipe_engine/json',
    'recipe_engine/path',
    'recipe_engine/platform',
    'recipe_engine/properties',
    'recipe_engine/raw_io',
    'recipe_engine/step',
]


def RunSteps(api):
  with api.osx_sdk('mac'):
    api.step('gn', ['gn', 'gen', 'out/Release'])
    api.step('ninja', ['ninja', '-C', 'out/Release'])
  with api.osx_sdk('mac', devicelab=True):
    api.step('gn', ['gn', 'gen', 'out/Release'])
    api.step('ninja', ['ninja', '-C', 'out/Release'])
  api.osx_sdk.reset_xcode()


def GenTests(api):
  for platform in ('linux', 'mac', 'win'):
    yield (api.test(platform) + api.platform.name(platform))

  yield api.test(
      'explicit_version', api.platform.name('mac'),
      api.properties(
          **{
              '$flutter/osx_sdk': {
                  'sdk_version': 'deadbeef', 'toolchain_ver_intel': '123abc',
                  'cleanup_cache': True
              }
          }
      )
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
                  'sdk_version': 'deadbeef', 'toolchain_ver_intel': '123abc',
                  'runtime_versions': ['ios-13-0', 'ios-14-0']
              }
          }
      ),
      api.step_data(
          'list runtimes',
          stdout=api.raw_io.output_text(
              '== Runtimes ==\n' +
              'iOS 13.0 - com.apple.CoreSimulator.SimRuntime.iOS-13-0\n' +
              'iOS 14.0 - com.apple.CoreSimulator.SimRuntime.iOS-14-0'
          )
      ),
      api.os_utils.is_symlink(False),
  )

  yield api.test(
      'no_runtime_version',
      api.platform.name('mac'),
      api.properties(
          **{
              '$flutter/osx_sdk': {
                  'sdk_version': 'deadbeef',
                  'toolchain_ver_intel': '123abc',
              }
          }
      ),
      api.os_utils.is_symlink(False),
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

  yield api.test(
      'explicit_package_source', api.platform.name('mac'),
      api.properties(
          **{
              '$flutter/osx_sdk': {
                  'sdk_version': 'deadbeef',
                  'toolchain_ver_intel': '123abc',
                  'xcode_cipd_package_source': 'some/package',
                  'cleanup_cache': True,
              }
          }
      )
  )

  yield api.test(
      'explicit_invalid_runtime_version_with_mac_13',
      api.platform.name('mac'),
      api.platform.mac_release('13.5.1'),
      api.properties(
          **{
              '$flutter/osx_sdk': {
                  'sdk_version': 'deadbeef', 'toolchain_ver_intel': '123abc',
                  'runtime_versions': ['ios-16-4', 'ios-16-2']
              }
          }
      ),
      status='INFRA_FAILURE'
  )

  yield api.test(
      'mac_13_explicit_runtime_version_already_mounted',
      api.platform.name('mac'),
      api.platform.mac_release('13.5.1'),
      api.properties(
          **{
              '$flutter/osx_sdk': {
                  'sdk_version': 'deadbeef', 'toolchain_ver_intel': '123abc',
                  'runtime_versions': ['ios-16-4_14e300c']
              }
          }
      ),
      api.step_data(
          'install runtimes.list runtimes',
          stdout=api.raw_io.output_text(
              '== Runtimes ==\n' +
              'iOS 16.4 (16.4 - 20E247) - com.apple.CoreSimulator.SimRuntime.iOS-16-4'
          )
      ),
      api.step_data(
          'install runtimes.cipd describe ios-16-4_14e300c.cipd describe infra_internal/ios/xcode/ios_runtime_dmg',
          retcode=1
      ),
      api.step_data(
          'install runtimes.cipd describe ios-16-4_14e300c.cipd describe infra_internal/ios/xcode/ios_runtime_dmg (2)',
          api.json.output({
              'result': {
                  'pin': {'package': 'xxx', 'instance_id': 'xxx'},
                  'registered_by':
                      'xxx',
                  'registered_ts':
                      'xxx',
                  'tags': [
                      {
                          'tag': 'ios_runtime_build:20e247',
                          'registered_by': 'xxx', 'registered_ts': 'xxx'
                      },
                      {
                          'tag': 'ios_runtime_version:ios-16-4',
                          'registered_by': 'xxx', 'registered_ts': 'xxx'
                      },
                  ],
              }
          }),
      ),
      api.step_data(
          'list runtimes',
          stdout=api.raw_io.output_text(
              '== Runtimes ==\n' +
              'iOS 16.4 (16.4 - 20E247) - com.apple.CoreSimulator.SimRuntime.iOS-16-4'
          )
      ),
  )

  yield api.test(
      'mac_13_explicit_runtime_version_not_mounted',
      api.platform.name('mac'),
      api.platform.mac_release('13.5.1'),
      api.properties(
          **{
              '$flutter/osx_sdk': {
                  'sdk_version': 'deadbeef', 'toolchain_ver_intel': '123abc',
                  'runtime_versions': ['ios-16-4_14e300c']
              }
          }
      ),
      api.step_data(
          'install runtimes.list runtimes',
          stdout=api.raw_io.output_text('== Runtimes ==\n')
      ),
      api.step_data(
          'install runtimes.cipd describe ios-16-4_14e300c.cipd describe infra_internal/ios/xcode/ios_runtime_dmg',
          retcode=1
      ),
      api.step_data(
          'install runtimes.cipd describe ios-16-4_14e300c.cipd describe infra_internal/ios/xcode/ios_runtime_dmg (2)',
          api.json.output({
              'result': {
                  'pin': {'package': 'xxx', 'instance_id': 'xxx'},
                  'registered_by':
                      'xxx',
                  'registered_ts':
                      'xxx',
                  'tags': [
                      {
                          'tag': 'ios_runtime_build:20e247',
                          'registered_by': 'xxx', 'registered_ts': 'xxx'
                      },
                      {
                          'tag': 'ios_runtime_version:ios-16-4',
                          'registered_by': 'xxx', 'registered_ts': 'xxx'
                      },
                  ],
              }
          }),
      ),
      api.step_data(
          'list runtimes',
          stdout=api.raw_io.output_text(
              '== Runtimes ==\n' +
              'iOS 16.4 (16.4 - 20E247) - com.apple.CoreSimulator.SimRuntime.iOS-16-4'
          )
      ),
  )

  yield api.test(
      'mac_13_explicit_runtime_version_build_verion_failure',
      api.platform.name('mac'),
      api.platform.mac_release('13.5.1'),
      api.properties(
          **{
              '$flutter/osx_sdk': {
                  'sdk_version': 'deadbeef', 'toolchain_ver_intel': '123abc',
                  'runtime_versions': ['ios-16-4_14e300c']
              }
          }
      ),
      api.step_data(
          'install runtimes.list runtimes',
          stdout=api.raw_io.output_text('== Runtimes ==\n')
      ),
      api.step_data(
          'install runtimes.cipd describe ios-16-4_14e300c.cipd describe infra_internal/ios/xcode/ios_runtime_dmg',
          retcode=1
      ),
      api.step_data(
          'install runtimes.cipd describe ios-16-4_14e300c.cipd describe infra_internal/ios/xcode/ios_runtime_dmg (2)',
          api.json.output({
              'result': {
                  'pin': {'package': 'xxx', 'instance_id': 'xxx'},
                  'registered_by':
                      'xxx',
                  'registered_ts':
                      'xxx',
                  'tags': [{
                      'tag': 'ios_runtime_build_invalid_tag',
                      'registered_by': 'xxx', 'registered_ts': 'xxx'
                  }],
              }
          }),
      ),
      status='INFRA_FAILURE'
  )

  yield api.test(
      'mac_13_explicit_runtime_version_clean',
      api.platform.name('mac'),
      api.platform.mac_release('13.5.1'),
      api.properties(
          **{
              '$flutter/osx_sdk': {
                  'sdk_version': 'deadbeef',
                  'toolchain_ver_intel': '123abc',
                  'runtime_versions': ['ios-16-4_14e300c'],
                  'cleanup_cache': True,
              }
          }
      ),
      api.step_data(
          'Cleaning up runtimes cache.Cleaning up mounted simulator runtimes',
          stdout=api.raw_io.output_text('No matching images found to delete'),
          stderr=api.raw_io.output_text('No matching images found to delete')
      ),
      api.step_data(
          'Cleaning up runtimes cache.list runtimes',
          stdout=api.raw_io.output_text(
              '== Runtimes ==\n' +
              'iOS 16.4 (16.2 - 20E247) - com.apple.CoreSimulator.SimRuntime.iOS-16-4\n'
              +
              'iOS 16.2 (16.2 - 20C52) - com.apple.CoreSimulator.SimRuntime.iOS-16-2'
          )
      ),
      api.step_data(
          'install runtimes.cipd describe ios-16-4_14e300c.cipd describe infra_internal/ios/xcode/ios_runtime_dmg',
          api.json.output({
              'result': {
                  'pin': {'package': 'xxx', 'instance_id': 'xxx'},
                  'registered_by':
                      'xxx',
                  'registered_ts':
                      'xxx',
                  'tags': [
                      {
                          'tag': 'ios_runtime_build:20e247',
                          'registered_by': 'xxx', 'registered_ts': 'xxx'
                      },
                      {
                          'tag': 'ios_runtime_version:ios-16-4',
                          'registered_by': 'xxx', 'registered_ts': 'xxx'
                      },
                  ],
              }
          }),
      ),
      api.step_data(
          'list runtimes',
          stdout=api.raw_io.output_text(
              '== Runtimes ==\n' +
              'iOS 16.4 (16.4 - 20E247) - com.apple.CoreSimulator.SimRuntime.iOS-16-4'
          )
      ),
  )

  yield api.test(
      'failed_to_delete_runtimes_err_in_stdout',
      api.platform.name('mac'),
      api.platform.mac_release('13.5.1'),
      api.properties(
          **{
              '$flutter/osx_sdk': {
                  'sdk_version': 'deadbeef',
                  'toolchain_ver_intel': '123abc',
                  'runtime_versions': ['ios-16-4_14e300c', 'ios-16-2_14c18'],
                  'cleanup_cache': True,
              }
          }
      ),
      api.step_data(
          'Cleaning up runtimes cache.Cleaning up mounted simulator runtimes',
          stdout=api.raw_io.output_text('Some error')
      ),
      status='INFRA_FAILURE'
  )
  yield api.test(
      'failed_to_delete_runtimes_err_in_stderr',
      api.platform.name('mac'),
      api.platform.mac_release('13.5.1'),
      api.properties(
          **{
              '$flutter/osx_sdk': {
                  'sdk_version': 'deadbeef',
                  'toolchain_ver_intel': '123abc',
                  'runtime_versions': ['ios-16-4_14e300c', 'ios-16-2_14c18'],
                  'cleanup_cache': True,
              }
          }
      ),
      api.step_data(
          'Cleaning up runtimes cache.Cleaning up mounted simulator runtimes',
          stderr=api.raw_io.output_text('Some error')
      ),
      status='INFRA_FAILURE'
  )
  yield api.test(
      'mac_13_cleanup_no_runtimes',
      api.platform.name('mac'),
      api.platform.mac_release('13.5.1'),
      api.properties(
          **{
              '$flutter/osx_sdk': {
                  'sdk_version': 'deadbeef',
                  'toolchain_ver_intel': '123abc',
                  'cleanup_cache': True,
              }
          }
      ),
  )

  yield api.test(
      'mac_13_arm_host',
      api.platform.name('mac'),
      api.platform.mac_release('13.5.1'),
      api.platform.arch('arm'),
      api.properties(
          **{
              '$flutter/osx_sdk': {
                  'sdk_version': 'deadbeef',
                  'toolchain_ver_arm': 'ARM_toolchain_verison',
              }
          }
      ),
  )

  yield api.test(
      'mac_13_x86_host',
      api.platform.name('mac'),
      api.platform.mac_release('13.5.1'),
      api.platform.arch('intel'),
      api.properties(
          **{
              '$flutter/osx_sdk': {
                  'sdk_version': 'deadbeef',
                  'toolchain_ver_intel': 'INTEL_toolchain_version',
              }
          }
      ),
  )

  yield api.test(
      'xcode_install_fails_passes_on_retry',
      api.platform.name('mac'),
      api.platform.mac_release('13.5.1'),
      api.properties(**{'$flutter/osx_sdk': {'sdk_version': 'deadbeef',}}),
      api.path.exists(sdk_app_path),
      api.step_data(
          'install xcode.verify xcode [CACHE]/osx_sdk/xcode_deadbeef/XCode.app.check xcode version',
          retcode=1
      ),
      api.step_data('install xcode.install xcode from cipd', retcode=1),
  )
