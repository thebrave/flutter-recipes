# Copyright 2020 The Chromium Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

from PB.recipe_modules.recipe_engine.swarming import properties
from recipe_engine.post_process import DoesNotRun, Filter, StatusFailure

DEPS = [
    'flutter/os_utils',
    'recipe_engine/assertions',
    'recipe_engine/platform',
    'recipe_engine/properties',
    'recipe_engine/raw_io',
]


def RunSteps(api):
  api.os_utils.ios_debug_symbol_doctor()
  api.os_utils.kill_processes()
  api.os_utils.collect_os_info()

  with api.os_utils.make_temp_directory('Create temp directory') as temp_dir:
    file = temp_dir.join('artifacts.zip')
  api.os_utils.clean_derived_data()
  api.os_utils.shutdown_simulators()
  api.os_utils.enable_long_paths()
  api.os_utils.prepare_ios_device()
  api.os_utils.is_symlink('/a/b/c/simlink')
  api.os_utils.symlink('/a/file', '/a/b/c/simlink')
  api.os_utils.kill_simulators()

  command = ['cat', '${FLUTTER_LOGS_DIR}']
  env = {'FLUTTER_LOGS_DIR': '/a/b/c'}
  new_command = api.os_utils.replace_magic_envs(command, env)
  api.assertions.assertEqual(new_command, ['cat', '/a/b/c'])


def GenTests(api):
  # For coverage.
  api.os_utils.is_symlink(True)

  xcode_dismiss_dialog_find_db_step = api.step_data(
      'Prepare iOS device.Dismiss Xcode automation dialogs.Find TCC directory',
      stdout=api.raw_io.output_text('TCC.db'),
  )
  xcode_dismiss_dialog_query_db_step = api.step_data(
      'Prepare iOS device.Dismiss Xcode automation dialogs.Query TCC db (2)',
      stdout=api.raw_io.output_text(
          'service|client|client_type|auth_value|auth_reason|auth_version|com.apple.dt.Xcode|flags|last_modified'
      ),
  )
  yield api.test(
      'basic',
      api.platform('win', 64),
  )
  yield api.test(
      'mac',
      api.platform('mac', 64),
  )
  yield api.test(
      'ios_debug_symbol_doctor_fails_then_succeeds',
      api.step_data('ios_debug_symbol_doctor.diagnose', retcode=1),
      xcode_dismiss_dialog_find_db_step,
      xcode_dismiss_dialog_query_db_step,
      api.platform('mac', 64),
      api.properties(device_os='iOS-16'),
      api.properties.environ(
          properties.EnvProperties(SWARMING_BOT_ID='flutter-devicelab-mac-1')
      ),
  )
  yield api.test(
      'ios_debug_symbol_doctor_fails_four_times',
      api.step_data('ios_debug_symbol_doctor.diagnose', retcode=1),
      api.step_data('ios_debug_symbol_doctor.diagnose (2)', retcode=1),
      api.step_data('ios_debug_symbol_doctor.diagnose (3)', retcode=1),
      api.step_data('ios_debug_symbol_doctor.diagnose (4)', retcode=1),
      api.step_data('ios_debug_symbol_doctor.diagnose (5)', retcode=1),
      api.platform('mac', 64),
      api.properties(device_os='iOS-16'),
      api.properties.environ(
          properties.EnvProperties(SWARMING_BOT_ID='flutter-devicelab-mac-1')
      ),
      status='INFRA_FAILURE'
  )
  yield api.test(
      'linux_linux',
      api.platform('linux', 64),
  )
  yield api.test(
      'with_failures', api.platform('win', 64),
      api.step_data("Killing Processes.stop dart", retcode=1)
  )
  yield api.test(
      'clean_derived_data',
      api.platform('mac', 64),
      xcode_dismiss_dialog_find_db_step,
      xcode_dismiss_dialog_query_db_step,
      api.properties(device_os='iOS-16'),
      api.properties.environ(
          properties.EnvProperties(SWARMING_BOT_ID='flutter-devicelab-mac-1')
      ),
  )
  yield api.test(
      'dimiss_dialog_xcode_automation_fails_find_db',
      api.step_data(
          'Prepare iOS device.Dismiss Xcode automation dialogs.Find TCC directory',
          stdout=api.raw_io.output_text(''),
      ),
      api.platform('mac', 64),
      api.properties(device_os='iOS-16'),
      api.properties.environ(
          properties.EnvProperties(SWARMING_BOT_ID='flutter-devicelab-mac-1')
      ),
      status='INFRA_FAILURE'
  )
  yield api.test(
      'dimiss_dialog_xcode_automation_fails_update_db',
      xcode_dismiss_dialog_find_db_step,
      api.platform('mac', 64),
      api.properties(device_os='iOS-16'),
      api.properties.environ(
          properties.EnvProperties(SWARMING_BOT_ID='flutter-devicelab-mac-1')
      ),
      status='INFRA_FAILURE'
  )
  yield api.test(
      'dimiss_dialog_xcode_automation_skip_if_not_core_device',
      api.step_data(
          'Prepare iOS device.Find device id',
          stdout=api.raw_io.output_text('123456789'),
      ),
      api.platform('mac', 64),
      api.properties(
          buildername='Mac flutter_gallery_ios__start_up', device_os='iOS-16'
      ),
      api.properties.environ(
          properties.EnvProperties(SWARMING_BOT_ID='flutter-devicelab-mac-1')
      ),
  )
  yield api.test(
      'fail_to_prepare_device',
      api.platform('mac', 64),
      api.properties(
          buildername='Mac flutter_gallery_ios__start_up', device_os='iOS-17'
      ),
      api.properties.environ(
          properties.EnvProperties(SWARMING_BOT_ID='flutter-devicelab-mac-1')
      ),
      api.step_data(
          'Prepare iOS device.Find device id',
          stdout=api.raw_io.output_text('123456789'),
      ),
      api.step_data(
          'Prepare iOS device.List CoreDevices',
          stdout=api.raw_io.output_text('123456789'),
      ),
      api.step_data(
          'Prepare iOS device.Wait for device to connect.Trigger device connect with QuickTime.Dismiss QuickTime automation dialogs.Find TCC directory',
          stdout=api.raw_io.output_text('TCC.db'),
      ),
      api.step_data(
          'Prepare iOS device.Wait for device to connect.Trigger device connect with QuickTime.Dismiss QuickTime automation dialogs.Query TCC db (2)',
          stdout=api.raw_io.output_text(
              'service|client|client_type|auth_value|auth_reason|auth_version|com.apple.QuickTimePlayerX|flags|last_modified'
          ),
      ),
      api.step_data(
          'Prepare iOS device.Dismiss iOS dialogs.Run app to dismiss dialogs',
          retcode=1,
      ),
      status='INFRA_FAILURE'
  )
