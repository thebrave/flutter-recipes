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

from datetime import datetime
from unittest.mock import Mock

_MOCK_TIME_NOW = Mock(
    return_value=datetime(2023, 12, 15, 13, 43, 21, 621929)
)  # 2023-12-15 13:43:21


def RunSteps(api):
  api.osx_sdk.now = _MOCK_TIME_NOW
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
      'skipped_xcode', api.platform.name('mac'),
      api.properties(**{'$flutter/osx_sdk': {
          'skip_xcode_install': True,
      }})
  )

  yield api.test(
      'explicit_version', api.platform.name('mac'),
      api.properties(
          **{
              '$flutter/osx_sdk': {
                  'sdk_version': 'deadbeef',
                  'toolchain_ver_intel': '123abc',
                  'cleanup_cache': True
              }
          }
      )
  )

  sdk_app_path = api.path.cache_dir / 'osx_sdk/xcode_deadbeef/XCode.app'

  yield api.test(
      'explicit_runtime_version',
      api.platform.name('mac'),
      api.step_data(
          "find macOS version",
          stdout=api.raw_io.output_text("10.15.6"),
      ),
      api.properties(
          **{
              '$flutter/osx_sdk': {
                  'sdk_version': 'deadbeef',
                  'toolchain_ver_intel': '123abc',
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
      api.step_data(
          "find macOS version",
          stdout=api.raw_io.output_text("10.15.6"),
      ),
  )

  yield api.test(
      'ancient_version',
      api.platform.name('mac'),
      api.step_data(
          "find macOS version",
          stdout=api.raw_io.output_text("10.1.0"),
      ),
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
      api.step_data(
          "find macOS version",
          stdout=api.raw_io.output_text("13.5.1"),
      ),
      api.properties(
          **{
              '$flutter/osx_sdk': {
                  'sdk_version': 'deadbeef',
                  'toolchain_ver_intel': '123abc',
                  'runtime_versions': ['ios-16-4', 'ios-16-2']
              }
          }
      ),
      status='INFRA_FAILURE'
  )

  yield api.test(
      'mac_13_explicit_runtime_version_already_mounted',
      api.platform.name('mac'),
      api.step_data(
          "find macOS version",
          stdout=api.raw_io.output_text("13.5.1"),
      ),
      api.properties(
          **{
              '$flutter/osx_sdk': {
                  'sdk_version': 'deadbeef',
                  'toolchain_ver_intel': '123abc',
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
          'install runtimes.list xcode runtime dmg ios-16-4_14e300c',
          stdout=api.raw_io.output_text(
              '[CACHE]/osx_sdk/xcode_runtime_dmg_ios-16-4_14e300c/.cipd\n' +
              '[CACHE]/osx_sdk/xcode_runtime_dmg_ios-16-4_14e300c/iOS_16-4.dmg'
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
                  'pin': {
                      'package': 'xxx',
                      'instance_id': 'xxx'
                  },
                  'registered_by':
                      'xxx',
                  'registered_ts':
                      'xxx',
                  'tags': [
                      {
                          'tag': 'ios_runtime_build:20e247',
                          'registered_by': 'xxx',
                          'registered_ts': 'xxx'
                      },
                      {
                          'tag': 'ios_runtime_version:ios-16-4',
                          'registered_by': 'xxx',
                          'registered_ts': 'xxx'
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
      api.step_data(
          "find macOS version",
          stdout=api.raw_io.output_text("13.5.1"),
      ),
      api.properties(
          **{
              '$flutter/osx_sdk': {
                  'sdk_version': 'deadbeef',
                  'toolchain_ver_intel': '123abc',
                  'runtime_versions': ['ios-16-4_14e300c']
              }
          }
      ),
      api.step_data(
          'install runtimes.list runtimes',
          stdout=api.raw_io.output_text('== Runtimes ==\n')
      ),
      api.step_data(
          'install runtimes.list xcode runtime dmg ios-16-4_14e300c',
          stdout=api.raw_io.output_text(
              '[CACHE]/osx_sdk/xcode_runtime_dmg_ios-16-4_14e300c/.cipd\n' +
              '[CACHE]/osx_sdk/xcode_runtime_dmg_ios-16-4_14e300c/iOS_16-4.dmg'
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
                  'pin': {
                      'package': 'xxx',
                      'instance_id': 'xxx'
                  },
                  'registered_by':
                      'xxx',
                  'registered_ts':
                      'xxx',
                  'tags': [
                      {
                          'tag': 'ios_runtime_build:20e247',
                          'registered_by': 'xxx',
                          'registered_ts': 'xxx'
                      },
                      {
                          'tag': 'ios_runtime_version:ios-16-4',
                          'registered_by': 'xxx',
                          'registered_ts': 'xxx'
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
      api.step_data(
          "find macOS version",
          stdout=api.raw_io.output_text("13.5.1"),
      ),
      api.properties(
          **{
              '$flutter/osx_sdk': {
                  'sdk_version': 'deadbeef',
                  'toolchain_ver_intel': '123abc',
                  'runtime_versions': ['ios-16-4_14e300c']
              }
          }
      ),
      api.step_data(
          'install runtimes.list runtimes',
          stdout=api.raw_io.output_text('== Runtimes ==\n')
      ),
      api.step_data(
          'install runtimes.list xcode runtime dmg ios-16-4_14e300c',
          stdout=api.raw_io.output_text(
              '[CACHE]/osx_sdk/xcode_runtime_dmg_ios-16-4_14e300c/.cipd\n' +
              '[CACHE]/osx_sdk/xcode_runtime_dmg_ios-16-4_14e300c/iOS_16-4.dmg'
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
                  'pin': {
                      'package': 'xxx',
                      'instance_id': 'xxx'
                  },
                  'registered_by':
                      'xxx',
                  'registered_ts':
                      'xxx',
                  'tags': [{
                      'tag': 'ios_runtime_build_invalid_tag',
                      'registered_by': 'xxx',
                      'registered_ts': 'xxx'
                  }],
              }
          }),
      ),
      status='INFRA_FAILURE'
  )

  yield api.test(
      'mac_13_explicit_runtime_version_fails_to_find_dmg',
      api.platform.name('mac'),
      api.step_data(
          "find macOS version",
          stdout=api.raw_io.output_text("13.5.1"),
      ),
      api.properties(
          **{
              '$flutter/osx_sdk': {
                  'sdk_version': 'deadbeef',
                  'toolchain_ver_intel': '123abc',
                  'runtime_versions': ['ios-16-4_14e300c']
              }
          }
      ),
      api.step_data(
          'install runtimes.list runtimes',
          stdout=api.raw_io.output_text('== Runtimes ==\n')
      ),
      api.step_data(
          'install runtimes.list xcode runtime dmg ios-16-4_14e300c',
          stdout=api.raw_io.output_text(
              '[CACHE]/osx_sdk/xcode_runtime_dmg_ios-16-4_14e300c/.cipd\n'
          )
      ),
      status='INFRA_FAILURE'
  )

  yield api.test(
      'mac_13_explicit_runtime_version_clean',
      api.platform.name('mac'),
      api.step_data(
          "find macOS version",
          stdout=api.raw_io.output_text("13.5.1"),
      ),
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
          'Cleaning up runtimes cache.check xcode version',
          stdout=api.raw_io
          .output_text('Xcode 15.0\n' + 'Build version 15C500b')
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
          'Cleaning up runtimes cache.list runtimes (2)',
          stdout=api.raw_io.output_text(
              '== Runtimes ==\n' +
              'iOS 16.4 (16.2 - 20E247) - com.apple.CoreSimulator.SimRuntime.iOS-16-4'
          )
      ),
      api.step_data(
          'install runtimes.list xcode runtime dmg ios-16-4_14e300c',
          stdout=api.raw_io.output_text(
              '[CACHE]/osx_sdk/xcode_runtime_dmg_ios-16-4_14e300c/.cipd\n' +
              '[CACHE]/osx_sdk/xcode_runtime_dmg_ios-16-4_14e300c/iOS_17_Simulator_Runtime.dmg'
          )
      ),
      api.step_data(
          'install runtimes.cipd describe ios-16-4_14e300c.cipd describe infra_internal/ios/xcode/ios_runtime_dmg',
          api.json.output({
              'result': {
                  'pin': {
                      'package': 'xxx',
                      'instance_id': 'xxx'
                  },
                  'registered_by':
                      'xxx',
                  'registered_ts':
                      'xxx',
                  'tags': [
                      {
                          'tag': 'ios_runtime_build:20e247',
                          'registered_by': 'xxx',
                          'registered_ts': 'xxx'
                      },
                      {
                          'tag': 'ios_runtime_version:ios-16-4',
                          'registered_by': 'xxx',
                          'registered_ts': 'xxx'
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
      api.step_data(
          "find macOS version",
          stdout=api.raw_io.output_text("13.5.1"),
      ),
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
      #api.platform.mac_release('13.5.1'),
      api.step_data(
          "find macOS version",
          stdout=api.raw_io.output_text("13.5.1"),
      ),
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
      api.step_data(
          "find macOS version",
          stdout=api.raw_io.output_text("13.5.1"),
      ),
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
      api.step_data(
          "find macOS version",
          stdout=api.raw_io.output_text("13.5.1"),
      ),
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
      api.step_data(
          "find macOS version",
          stdout=api.raw_io.output_text("13.5.1"),
      ),
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
      api.step_data(
          "find macOS version",
          stdout=api.raw_io.output_text("13.5.1"),
      ),
      api.properties(**{'$flutter/osx_sdk': {
          'sdk_version': 'deadbeef',
      }}),
      api.path.exists(sdk_app_path),
      api.step_data(
          'install xcode.verify xcode [CACHE]/osx_sdk/xcode_deadbeef/XCode.app.check xcode version',
          retcode=1
      ),
      api.step_data('install xcode.install xcode from cipd', retcode=1),
  )

  _MOCK_TIME_WITHIN_7_DAYS = "2023-12-13 13:43:21"
  _MOCK_TIME_WITHIN_1_DAY = "2023-12-15 00:00:00"
  _MOCK_TIME_LONGER_THAN_7_DAYS = "2023-12-01 13:43:21"

  yield api.test(
      'launch_services_unresponsive_mac_reset_within_a_day',
      api.platform.name('mac'),
      api.step_data(
          "find macOS version",
          stdout=api.raw_io.output_text("13.5.1"),
      ),
      api.properties(**{'$flutter/osx_sdk': {
          'sdk_version': 'deadbeef',
      }}),
      api.path.exists(
          (sdk_app_path),
          (api.path.cache_dir / 'osx_sdk/launch_services_reset_log.txt'),
      ),
      api.step_data(
          'verify launch services.Check if xcodebuild impacted by Launch Services',
          stdout=api.raw_io.output_text(
              'Timestamp               Ty Process[PID:TID]\n' +
              '2025-01-25 22:47:00.906 E  xcodebuild[11687:149bd] [com.apple.launchservices:default] LaunchServices: disconnect event interruption received for service com.apple.lsd.modifydb\n'
              +
              '2025-01-25 22:47:00.906 E  xcodebuild[11687:149c6] [com.apple.launchservices:default] LaunchServices: disconnect event interruption received for service com.apple.lsd.mapdb'
          )
      ),
      api.step_data(
          'verify launch services.Check if Launch Services db has been reset recently',
          api.file.read_text(
              text_content=(
                  _MOCK_TIME_LONGER_THAN_7_DAYS + '\n' + _MOCK_TIME_WITHIN_1_DAY
              )
          )
      ),
  )

  yield api.test(
      'launch_services_unresponsive_mac_reset_within_7_days',
      api.platform.name('mac'),
      api.step_data(
          "find macOS version",
          stdout=api.raw_io.output_text("13.5.1"),
      ),
      api.properties(**{'$flutter/osx_sdk': {
          'sdk_version': 'deadbeef',
      }}),
      api.path.exists(
          (sdk_app_path),
          (api.path.cache_dir / 'osx_sdk/launch_services_reset_log.txt'),
      ),
      api.step_data(
          'verify launch services.Check if xcodebuild impacted by Launch Services',
          stdout=api.raw_io.output_text(
              'Timestamp               Ty Process[PID:TID]\n' +
              '2025-01-25 22:47:00.906 E  xcodebuild[11687:149bd] [com.apple.launchservices:default] LaunchServices: disconnect event interruption received for service com.apple.lsd.modifydb\n'
              +
              '2025-01-25 22:47:00.906 E  xcodebuild[11687:149c6] [com.apple.launchservices:default] LaunchServices: disconnect event interruption received for service com.apple.lsd.mapdb'
          )
      ),
      api.step_data(
          'verify launch services.Check if Launch Services db has been reset recently',
          api.file.read_text(
              text_content=(
                  _MOCK_TIME_LONGER_THAN_7_DAYS + '\n' +
                  _MOCK_TIME_WITHIN_7_DAYS
              )
          )
      ),
  )

  yield api.test(
      'launch_services_unresponsive_mac_reset_longer_than_7_days',
      api.platform.name('mac'),
      api.step_data(
          "find macOS version",
          stdout=api.raw_io.output_text("13.5.1"),
      ),
      api.properties(**{'$flutter/osx_sdk': {
          'sdk_version': 'deadbeef',
      }}),
      api.path.exists(
          (sdk_app_path),
          (api.path.cache_dir / 'osx_sdk/launch_services_reset_log.txt'),
      ),
      api.step_data(
          'verify launch services.Check if xcodebuild impacted by Launch Services',
          stdout=api.raw_io.output_text(
              'Timestamp               Ty Process[PID:TID]\n' +
              '2025-01-25 22:47:00.906 E  xcodebuild[11687:149bd] [com.apple.launchservices:default] LaunchServices: disconnect event interruption received for service com.apple.lsd.modifydb\n'
              +
              '2025-01-25 22:47:00.906 E  xcodebuild[11687:149c6] [com.apple.launchservices:default] LaunchServices: disconnect event interruption received for service com.apple.lsd.mapdb'
          )
      ),
      api.step_data(
          'verify launch services.Check if Launch Services db has been reset recently',
          api.file.read_text(text_content=_MOCK_TIME_LONGER_THAN_7_DAYS)
      ),
  )

  yield api.test(
      'launch_services_unresponsive_mac_already_reset_invalid date',
      api.platform.name('mac'),
      api.step_data(
          "find macOS version",
          stdout=api.raw_io.output_text("13.5.1"),
      ),
      api.properties(**{'$flutter/osx_sdk': {
          'sdk_version': 'deadbeef',
      }}),
      api.path.exists(
          (sdk_app_path),
          (api.path.cache_dir / 'osx_sdk/launch_services_reset_log.txt'),
      ),
      api.step_data(
          'verify launch services.Check if xcodebuild impacted by Launch Services',
          stdout=api.raw_io.output_text(
              'Timestamp               Ty Process[PID:TID]\n' +
              '2025-01-25 22:47:00.906 E  xcodebuild[11687:149bd] [com.apple.launchservices:default] LaunchServices: disconnect event interruption received for service com.apple.lsd.modifydb\n'
              +
              '2025-01-25 22:47:00.906 E  xcodebuild[11687:149c6] [com.apple.launchservices:default] LaunchServices: disconnect event interruption received for service com.apple.lsd.mapdb'
          )
      ),
      api.step_data(
          'verify launch services.Check if Launch Services db has been reset recently',
          api.file.read_text(text_content='invalid date')
      ),
  )

  yield api.test(
      'kill_startup_assistant',
      api.platform.name('mac'),
      api.step_data(
          "find macOS version",
          stdout=api.raw_io.output_text("13.5.1"),
      ),
      api.properties(**{'$flutter/osx_sdk': {
          'sdk_version': 'deadbeef',
      }}),
      api.path.exists(
          (sdk_app_path),
          (api.path.cache_dir / 'osx_sdk/launch_services_reset_log.txt'),
      ),
      api.step_data(
          'check for Setup Assistant', stdout=api.raw_io.output_text('123')
      ),
  )
