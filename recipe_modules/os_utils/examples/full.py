# Copyright 2020 The Chromium Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

from PB.recipe_modules.recipe_engine.swarming import properties
from recipe_engine.post_process import DoesNotRun, Filter, StatusFailure

DEPS = [
    'flutter/os_utils',
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
  api.os_utils.dismiss_dialogs()
  api.os_utils.reset_automation_dialogs()
  api.os_utils.print_pub_certs()
  api.os_utils.is_symlink('/a/b/c/simlink')
  api.os_utils.symlink('/a/file', '/a/b/c/simlink')
  api.os_utils.kill_simulators()


def GenTests(api):
  # For coverage.
  api.os_utils.is_symlink(True)

  xcode_dismiss_dialog_find_db_step = api.step_data(
      'Dismiss dialogs.Dismiss Xcode automation dialogs.Find TCC directory',
      stdout=api.raw_io.output_text('TCC.db'),
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
      api.platform('mac', 64),
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
      'clean_derived_data', api.platform('mac', 64),
      xcode_dismiss_dialog_find_db_step,
      api.properties.environ(
          properties.EnvProperties(SWARMING_BOT_ID='flutter-devicelab-mac-1')
      )
  )
  yield api.test(
      'dimiss_dialog_xcode_automation_fails_find_db',
      api.step_data(
          'Dismiss dialogs.Dismiss Xcode automation dialogs.Find TCC directory',
          stdout=api.raw_io.output_text(''),
      ),
      api.platform('mac', 64),
      api.properties.environ(
          properties.EnvProperties(SWARMING_BOT_ID='flutter-devicelab-mac-1')
      ),
      status='INFRA_FAILURE'
  )
  yield api.test(
      'reset_dialog_xcode_automation_fails_find_db',
      xcode_dismiss_dialog_find_db_step,
      api.step_data(
          'Reset Xcode automation dialogs.Find TCC directory',
          stdout=api.raw_io.output_text('TCC.db.backup'),
      ),
      api.platform('mac', 64),
      api.properties.environ(
          properties.EnvProperties(SWARMING_BOT_ID='flutter-devicelab-mac-1')
      ),
  )
  yield api.test(
      'dimiss_dialog_xcode_automation_skip_if_not_core_device',
      api.step_data(
          'Dismiss dialogs.Dismiss iOS dialogs.Find device id',
          stdout=api.raw_io.output_text('123456789'),
      ),
      api.step_data(
          'Dismiss dialogs.Dismiss Xcode automation dialogs.Find wired CoreDevices',
          stdout=api.raw_io.output_text('No devices found.'),
      ),
      api.platform('mac', 64),
      api.properties(buildername='Mac flutter_gallery_ios__start_up',),
      api.properties.environ(
          properties.EnvProperties(SWARMING_BOT_ID='flutter-devicelab-mac-1')
      ),
  )
