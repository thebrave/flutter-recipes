# Copyright 2020 The Chromium Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

import os
from contextlib import contextmanager
from recipe_engine import recipe_api

from PB.go.chromium.org.luci.buildbucket.proto import common as common_pb2

TIMEOUT_PROPERTY = 'ios_debug_symbol_doctor_timeout_seconds'
TCC_AUTOMATION_DB = 'TCC.db'
TCC_AUTOMATION_BACKUP_DB = 'TCC.db.backup'


class OsUtilsApi(recipe_api.RecipeApi):
  """Operating system utilities."""

  def initialize(self):
    self._mock_is_symlink = None
    if self._test_data.enabled:
      self._mock_is_symlink = self._test_data.get('is_symlink', True)

  def _kill_win(self, name, exe_name):
    """Kills all the windows processes with a given name.

    Args:
      name(str): The name of the step.
      exe_name(str): The name of the windows executable.
    """
    self.m.step(
        name,
        ['taskkill', '/f', '/im', exe_name, '/t'],
        ok_ret='any',
    )

  def replace_magic_envs(self, command, env):
    """Replaces allowed listed env variables by its value."""
    MAGIC_ENV_DICT = {
        '${FLUTTER_LOGS_DIR}': 'FLUTTER_LOGS_DIR',
        '${LUCI_WORKDIR}': 'LUCI_WORKDIR',
        '${LUCI_CLEANUP}': 'LUCI_CLEANUP',
        '${REVISION}': 'REVISION',
    }
    result = []
    for part in command:
      if part in MAGIC_ENV_DICT:
        result.append(env[MAGIC_ENV_DICT[part]])
      else:
        result.append(part)
    return result

  def is_symlink(self, path):
    """Returns if a path points to a symlink or not."""
    is_symlink = os.path.islink(self.m.path.abspath(path))
    return is_symlink if self._mock_is_symlink is None else self._mock_is_symlink

  def symlink(self, source, dest):
    """Creates a symbolic link.

    Creates a symbolic link in mac platforms.
    """
    if self.m.platform.is_mac:
      self.m.step(
          'Link %s to %s' % (dest, source),
          ['ln', '-s', source, dest],
          infra_step=True,
      )

  def clean_derived_data(self):
    """Cleans the derived data folder in mac builders.

    Derived data caches fail very frequently when different version of mac/ios
    sdks are used in the same bot. To prevent those failures we will start
    deleting the folder before every task.
    """
    derived_data_path = self.m.path.home_dir.join(
        'Library', 'Developer', 'Xcode', 'DerivedData'
    )
    if self.m.platform.is_mac:
      self.m.step(
          'Delete mac deriveddata',
          ['rm', '-rf', derived_data_path],
          infra_step=True,
      )

  def collect_os_info(self):
    """Collects meminfo, cpu, processes for mac"""
    if self.m.platform.is_mac:
      self.m.step(
          'OS info',
          cmd=['top', '-l', '3', '-o', 'mem'],
          infra_step=True,
      )
      # These are temporary steps to collect xattr info for triage purpose.
      # See issue: https://github.com/flutter/flutter/issues/68322#issuecomment-740264251
      self.m.step(
          'python3 xattr info',
          cmd=['xattr', '/opt/s/w/ir/cipd_bin_packages/python3'],
          ok_ret='any',
          infra_step=True,
      )
      self.m.step(
          'git xattr info',
          cmd=['xattr', '/opt/s/w/ir/cipd_bin_packages/git'],
          ok_ret='any',
          infra_step=True,
      )
    elif self.m.platform.is_linux:
      self.m.step(
          'OS info',
          cmd=['top', '-b', '-n', '3', '-o', '%MEM'],
          infra_step=True,
      )

  def kill_simulators(self):
    """Kills any open simulators.

    This is to ensure builds use xcode from a clean state.
    """
    if self.m.platform.is_mac:
      self.m.step(
          'kill dart', [
              'killall', '-9', '-v',
              'com.apple.CoreSimulator.CoreSimulatorDevice'
          ],
          ok_ret='any',
          infra_step=True
      )

  def kill_processes(self):
    """Kills processes.

    Windows uses exclusive file locking.  On LUCI, if these processes remain
    they will cause the build to fail because the builder won't be able to
    clean up.

    Linux and Mac have leaking processes after task executions, potentially
    causing the build to fail if without clean up.

    This might fail if there's not actually a process running, which is
    fine.

    If it actually fails to kill the task, the job will just fail anyway.
    """
    with self.m.step.nest('Killing Processes') as presentation:
      if self.m.platform.is_win:
        self._kill_win('stop gradle daemon', 'java.exe')
        self._kill_win('stop dart', 'dart.exe')
        self._kill_win('stop adb', 'adb.exe')
        self._kill_win('stop flutter_tester', 'flutter_tester.exe')
      elif self.m.platform.is_mac:
        self.m.step(
            'kill dart', ['killall', '-9', '-v', 'dart'],
            ok_ret='any',
            infra_step=True
        )
        self.m.step(
            'kill flutter', ['killall', '-9', '-v', 'flutter'],
            ok_ret='any',
            infra_step=True
        )
        self.m.step(
            'kill Chrome', ['killall', '-9', '-v', 'Chrome'],
            ok_ret='any',
            infra_step=True
        )
        self.m.step(
            'kill Safari', ['killall', '-9', '-v', 'Safari'],
            ok_ret='any',
            infra_step=True
        )
        self.m.step(
            'kill java', ['killall', '-9', '-v', 'java'],
            ok_ret='any',
            infra_step=True
        )
        self.m.step(
            'kill adb', ['killall', '-9', '-v', 'adb'],
            ok_ret='any',
            infra_step=True
        )
        self.m.step(
            'kill Xcode', ['killall', '-9', '-v', 'Xcode'],
            ok_ret='any',
            infra_step=True
        )
        self.m.step(
            'kill QuickTime', ['killall', '-9', '-v', 'QuickTime Player'],
            ok_ret='any',
            infra_step=True
        )
      else:
        self.m.step(
            'kill chrome', ['pkill', '-e', 'chrome'],
            ok_ret='any',
            infra_step=True
        )
        self.m.step(
            'kill dart', ['pkill', '-e', 'dart'], ok_ret='any', infra_step=True
        )
        self.m.step(
            'kill flutter', ['pkill', '-e', 'flutter'],
            ok_ret='any',
            infra_step=True
        )
        self.m.step(
            'kill java', ['pkill', '-e', 'java'], ok_ret='any', infra_step=True
        )
        self.m.step(
            'kill adb', ['pkill', '-e', 'adb'], ok_ret='any', infra_step=True
        )
      # Ensure we always pass this step as killing non existing processes
      # may create errors.
      presentation.status = 'SUCCESS'

  @contextmanager
  def make_temp_directory(self, label):
    """Makes a temporary directory that is automatically deleted.

    Args:
      label:
        (str) Part of the step name that removes the directory after is used.
    """
    temp_dir = self.m.path.mkdtemp('tmp')
    try:
      yield temp_dir
    finally:
      self.m.file.rmtree('temp dir for %s' % label, temp_dir)

  def shutdown_simulators(self):
    """It stops simulators if task is running on a devicelab bot."""
    if self.is_devicelab() and self.is_ios() and self.m.platform.is_mac:
      with self.m.step.nest('Shutdown simulators'):
        self.m.step(
            'Shutdown simulators',
            ['sudo', 'xcrun', 'simctl', 'shutdown', 'all']
        )
        self.m.step(
            'Erase simulators', ['sudo', 'xcrun', 'simctl', 'erase', 'all']
        )

  def enable_long_paths(self):
    """Enables long path support in Windows."""

    if not self.m.platform.is_win:
      # noop for non windows platforms.
      return
    with self.m.step.nest('Enable long path support'):
      resource_name = self.resource('long_paths.ps1')
      self.m.step(
          'Run long path support script',
          ['powershell.exe', resource_name],
      )

  def _get_initial_timeout(self):
    return self.m.properties.get(
        # This is not set by the builder config, but can be provided via LED
        TIMEOUT_PROPERTY,
        120,  # 2 minutes
    )

  def ios_debug_symbol_doctor(self, diagnose_first=True):
    """Call the ios_debug_symbol_doctor entrypoint of the Device Doctor.

    Args:
      diagnose_first:
        (bool) Whether diagnosis will be run initially before attempting to recover.
    """
    if not self.is_devicelab() or not self.m.platform.is_mac or not self.is_ios(
    ):
      # if no iPhone is attached, we don't need to recover ios debug symbols
      return
    with self.m.step.nest('ios_debug_symbol_doctor'):
      cocoon_path = self._checkout_cocoon()
      entrypoint = cocoon_path.join(
          'cipd_packages',
          'device_doctor',
          'bin',
          'ios_debug_symbol_doctor.dart',
      )

      timeout = self._get_initial_timeout()
      # Since we double the timeout on each retry, the last retry will have a
      # timeout of 16 minutes
      retry_count = 4
      with self.m.context(cwd=cocoon_path.join('cipd_packages',
                                               'device_doctor'),
                          infra_steps=True):
        self.m.step(
            'pub get device_doctor',
            ['dart', 'pub', 'get'],
        )
        if diagnose_first:
          clean_results = self._diagnose_debug_symbols(
              entrypoint, timeout, cocoon_path
          )
          if clean_results:
            # It doesn't appear debug symbols need to be sync'd, we are finished
            return
        for _ in range(retry_count):
          self._recover_debug_symbols(entrypoint, timeout, cocoon_path)
          result = self._diagnose_debug_symbols(
              entrypoint, timeout, cocoon_path
          )
          if result:
            # attached devices don't have errors
            return
          # Try for twice as long next time
          timeout *= 2

        message = '''
The ios_debug_symbol_doctor is detecting phones attached with errors and failed
to recover this bot with a timeout of %s seconds.

See https://github.com/flutter/flutter/issues/103511 for more context.
''' % timeout
        # raise purple
        self.m.step.empty(
            'Recovery failed after %s attempts' % retry_count,
            status=self.m.step.INFRA_FAILURE,
            step_text=message,
        )

  def prepare_ios_device(self):
    """Prepare iOS device for running tests.

    If the device is a CoreDevice (physical iOS 17+ devices), wait for the
    device to show as connected.

    Dismisses iOS and macOS dialogs to avoid problems.

    Args:
      flutter_path(Path): A path to the checkout of the flutter sdk repository.
    """
    if self.is_devicelab() and self.is_ios() and self.m.platform.is_mac:
      with self.m.step.nest('Prepare iOS device'):
        device_id = self.m.step(
            'Find device id', ['idevice_id', '-l'],
            stdout=self.m.raw_io.output_text()
        ).stdout.rstrip()

        is_core_device = self._is_core_device(device_id)

        cocoon_path = self._checkout_cocoon()

        if is_core_device:
          with self.m.step.nest('Wait for device to connect'
                               ) as wait_connect_step:
            try:
              self._is_core_device_connected(device_id)
            except self.m.step.InfraFailure:
              infra_dialog_project_path = self._infra_dialog_directory_path(
                  cocoon_path
              ).join('infra-dialog.xcodeproj')
              self.m.step(
                  'Open infra-dialog in Xcode',
                  ['open', infra_dialog_project_path],
              )
              # Open device in QuickTime to try to establish a connection.
              self._open_quick_time(device_id)

              # Wait up to ~5 minutes for device to connect.
              try:
                self.m.retry.basic_wrap(
                    lambda timeout: self._is_core_device_connected(
                        device_id,
                        timeout=timeout,
                    ),
                    step_name='Wait for device to connect',
                    sleep=10.0,
                    backoff_factor=2,
                    max_attempts=6
                )
              except self.m.step.InfraFailure:
                # If step fails, continue to "Run app to dismiss dialogs" step.
                # That step should also fail.
                wait_connect_step.status = self.m.step.INFRA_FAILURE
              finally:
                self._list_core_devices()
                self.m.step(
                    'Kill Xcode',
                    ['killall', '-9', '-v', 'Xcode'],
                    ok_ret='any',
                )

        with self.m.step.nest('Dismiss iOS dialogs'):
          resource_name = self.resource('dismiss_dialogs.sh')
          self.m.step(
              'Set execute permission',
              ['chmod', '755', resource_name],
              infra_step=True,
          )
          with self.m.context(
              cwd=self._infra_dialog_directory_path(cocoon_path),
              infra_steps=True,
          ):
            cmd = [resource_name, device_id]
            try:
              self.m.step('Run app to dismiss dialogs', cmd)
            finally:
              self._list_core_devices()
              self.m.step(
                  'Kill QuickTime',
                  ['killall', '-9', '-v', 'QuickTime Player'],
                  ok_ret='any',
              )
        with self.m.step.nest('Dismiss Xcode automation dialogs'):
          with self.m.context(infra_steps=True):
            builder_name = self.m.properties.get('buildername')
            self.m.step.empty("Get buildername", step_text=builder_name)

            # Only required for CoreDevices (physical iOS 17+ devices) or
            # "xcode_debug" tests. Builders with 'xcode_debug' in the name
            # force tests the workflow that requires this permission.
            if is_core_device or 'xcode_debug' in builder_name:
              self._dismiss_automation_dialog('Xcode', 'com.apple.dt.Xcode')

  def _infra_dialog_directory_path(self, cocoon_path):
    return cocoon_path.join(
        'cipd_packages', 'device_doctor', 'tool', 'infra-dialog'
    )

  def _open_quick_time(self, device_id):
    """Gives permissions to automate QuickTime. Then opens QuickTime with
    screen and audio to set to `device_id`.

    Opening QuickTime and switching the "Screen" to the device may help the
    device connect.

    Args:
      device_id(string): A string of the selected device's UDID.
    """
    with self.m.step.nest('Trigger device connect with QuickTime'):
      with self.m.context(infra_steps=True):
        with self.m.step.nest('Dismiss QuickTime automation dialogs'):
          self._dismiss_automation_dialog(
              'QuickTime Player', 'com.apple.QuickTimePlayerX'
          )
        self.m.step(
            'Open QuickTime',
            ['open', '-a', 'QuickTime Player'],
        )
        self.m.step(
            'Set Audio Device in QuickTime',
            [
                'defaults', 'write', 'com.apple.QuickTimePlayerX',
                'MGDeviceRecordingDocumentViewControllerAudioDeviceSelectionUniqueID',
                device_id
            ],
        )
        self.m.step(
            'Set Video Device in QuickTime',
            [
                'defaults', 'write', 'com.apple.QuickTimePlayerX',
                'MGDeviceRecordingDocumentViewControllerVideoDeviceSelectionUniqueID',
                device_id
            ],
        )
        self.m.step(
            'View defaults in QuickTime',
            ['defaults', 'read', 'com.apple.QuickTimePlayerX'],
        )

        self._apple_script_command(
            'Open QuickTime Recording',
            'QuickTime Player',
            ['new movie recording'],
            timeout=30,
        )
        # For some reason, the first time you open a QuickTime recording, the
        # device will not be selected. Close the window and try again. The
        # second time should work.
        self._apple_script_command(
            'Close QuickTime Recording',
            'QuickTime Player',
            ['close its front window'],
            timeout=30,
        )
        self._apple_script_command(
            'Open QuickTime Recording',
            'QuickTime Player',
            ['new movie recording'],
            timeout=30,
        )

  def _apple_script_command(
      self,
      title,
      app_name,
      commands,
      timeout=2,
      raise_on_failure=False,
  ):
    """Run an AppleScript command.

    Args:
      title(string): A string of step's title.
      app_name(string): The name of the app to tell the commands to.
      commands(list): A list of strings of commands to tell the app to do.
      timeout (int or float): How many seconds to wait before timing out the step.
      raise_on_failure (bool): Raise InfraFailure or StepFailure on failure.
    """

    apple_script_to_run = []
    for command in commands:
      apple_script_to_run.append('-e')
      apple_script_to_run.append(command)
    self.m.step(
        title,
        [
            'osascript',
            '-e',
            'tell app "%s"' % app_name,
            *apple_script_to_run,
            '-e',
            'end tell',
        ],
        raise_on_failure=raise_on_failure,
        ok_ret=(0,) if raise_on_failure else 'any',
        timeout=timeout,
    )

  def _list_core_devices(self):
    """Get list of CoreDevices.
    Allow any return code and ignore failure since this command will only
    work with Xcode 15 and therefore may not work for all machines.
    """
    device_list = self.m.step(
        'List CoreDevices',
        [
            'xcrun',
            'devicectl',
            'list',
            'devices',
            '-v',
        ],
        raise_on_failure=False,
        ok_ret='any',
        stdout=self.m.raw_io.output_text(add_output_log=True),
    ).stdout.rstrip()

    return device_list

  def _is_core_device(self, device_id):
    """Check if device is a CoreDevice (physical iOS 17+ devices).

    Only CoreDevices appear in `devicectl list devices` command.

    Args:
      device_id(string): A string of the selected device's UDID.
    """
    device_list = self._list_core_devices()

    if device_id in device_list:
      return True
    return False

  # pylint: disable=unused-argument
  def _is_core_device_connected(self, device_id, timeout=None):
    """Use `devicectl` command to determine if device is connected via cable.
    Only accept if `transportType` is wired in case other devices are paired
    but not connected via cable (aka connected wirelessly).

    Args:
      device_id(string): A string of the selected device's UDID.

    Throws an InfraFailure if device is not connected.
    """
    device_list = self.m.step(
        'Find wired CoreDevices',
        [
            'xcrun',
            'devicectl',
            'list',
            'devices',
            '--filter',
            "connectionProperties.transportType CONTAINS 'wired'",
            '-v',
        ],
        stdout=self.m.raw_io.output_text(add_output_log=True),
    ).stdout.rstrip()

    if device_id not in device_list:
      raise self.m.step.InfraFailure('Device not connected.')

  def _dismiss_automation_dialog(self, app_name, app_identifer):
    """Dismiss automation permission dialog and update permission db.

    Args:
      app_name(string): Name of the application to get permission for.
      app_identifer(string): Bundle id of the application.
    """

    tcc_directory_path, db_path, backup_db_path = self._get_tcc_path()

    # Ensure db exists
    files = self.m.step(
        'Find TCC directory',
        ['ls', tcc_directory_path],
        stdout=self.m.raw_io.output_text(add_output_log=True),
    ).stdout.rstrip()

    if TCC_AUTOMATION_DB not in files:
      self.m.step.empty(
          'Failed to find TCC.db',
          status=self.m.step.INFRA_FAILURE,
      )

    # Print contents of db for potential debugging purposes.
    self._query_automation_db_step_with_retry(db_path)

    # Create backup db if there isn't one.
    # If there is already a backup, it's most likely that a previous run did
    # not complete correctly and did not get reset, so don't overwrite the backup.
    if TCC_AUTOMATION_BACKUP_DB not in files:
      self.m.step(
          'Create backup db',
          ['cp', db_path, backup_db_path],
      )

    self.m.retry.basic_wrap(
        lambda timeout: self._create_tcc_entry(
            db_path,
            app_name,
            app_identifer,
            timeout=timeout,
        ),
        step_name='Wait to add entry in TCC db',
        sleep=2.0,
        backoff_factor=2,
        max_attempts=3,
        timeout=2,
    )

    # Update TCC.db. If fails, try up to 3 times. It may fail if the db is locked.
    self.m.retry.basic_wrap(
        lambda timeout: self._update_automation_permission_db(
            db_path,
            app_identifer,
            timeout=timeout,
        ),
        step_name='Wait to update TCC db',
        sleep=2.0,
        backoff_factor=2,
        max_attempts=3
    )

    # Print contents of db for potential debugging purposes.
    self._query_automation_db_step_with_retry(db_path)

    # Try and trigger automation. If fails or times out, permission was
    # not successfully granted.
    self._trigger_and_dismiss_automation_permission(
        app_name,
        timeout=5 * 60,
        raise_on_failure=True,
    )

    # The app was opened by Applescript, so kill it.
    self.m.step(
        'Kill %s' % app_name,
        ['killall', '-9', '-v', app_name],
        ok_ret='any',
    )

  def _dismiss_automation_permission(self):
    """Kill the automation dialog. After killing the dialog, an entry for
    the client requesting control of app should automatically be added to the db.
    """

    self.m.step(
        'Dismiss dialog',
        ['killall', '-9', '-v', 'UserNotificationCenter'],
        ok_ret='any',
    )

  def _trigger_and_dismiss_automation_permission(
      self, app_name, timeout=2, raise_on_failure=False
  ):
    """Trigger automation dialog to appear and then kill the dialog.

    Args:
      app_name(string): Name of the application to get permission for.
      timeout (int or float): How many seconds to wait before timing out the
              "Trigger dialog" step.
      raise_on_failure (bool): Raise InfraFailure or StepFailure on failure.
    """

    # Run an arbitrary AppleScript command to trigger permissions dialog.
    # The AppleScript counts how many windows of the app are open.
    # The script will hang if permission has not been given, so timeout after
    # a few seconds.
    try:
      self._apple_script_command(
          'Trigger dialog',
          app_name,
          ['launch', 'count window'],
          timeout,
          raise_on_failure,
      )
    finally:
      self._dismiss_automation_permission()

  def _create_tcc_entry(self, db_path, app_name, app_identifer, timeout=2):
    """Trigger automation dialog to appear and then kill the dialog.
    Killing the dialog will add an entry for the permission to the TCC.db.
    Raises an error if dialog fails to add entry to db.

    Args:
      app_name(string): Name of the application to get permission for.
      app_identifer(string): Bundle id of the application.
      db_path(string): A string of the path to the sqlite database.
    """

    self._trigger_and_dismiss_automation_permission(app_name, timeout=timeout)

    if app_identifer not in self._query_automation_db_step_with_retry(db_path):
      raise self.m.step.InfraFailure(
          '%s entry not found in TCC.db' % app_identifer
      )

  def _get_tcc_path(self):
    """Constructs paths to the TCC directory, TCC db, and TCC backup db.

    Returns:
        A tuple of strings representing the paths to the TCC directory, TCC db, and TCC backup db.
    """
    home_path = 'Users/fakeuser' if self._test_data.enabled else os.environ.get(
        'HOME'
    )
    tcc_directory_path = os.path.join(
        str(home_path), 'Library/Application Support/com.apple.TCC'
    )
    db_path = os.path.join(tcc_directory_path, TCC_AUTOMATION_DB)
    backup_db_path = os.path.join(tcc_directory_path, TCC_AUTOMATION_BACKUP_DB)
    return tcc_directory_path, db_path, backup_db_path

  # pylint: disable=unused-argument
  def _update_automation_permission_db(
      self, db_path, app_identifer, timeout=None
  ):
    self.m.step(
        'Update db',
        [
            'sqlite3', db_path,
            "UPDATE access SET auth_value = 2, auth_reason = 3, flags = NULL WHERE service = 'kTCCServiceAppleEvents' AND indirect_object_identifier = '%s'"
            % app_identifer
        ],
    )

  def _query_automation_db_step_with_retry(self, db_path):
    """Queries the TCC database with 3 retries. Sometimes if the database is
    locked, query will fail. So wait and try again.

    Args:
      db_path(string): A string of the path to the sqlite database.

    Returns:
      A string of the query's output.
    """

    return self.m.retry.basic_wrap(
        lambda timeout: self._query_automation_db_step(
            db_path,
            timeout=timeout,
        ),
        step_name='Wait to query TCC db',
        sleep=2.0,
        backoff_factor=1,
        max_attempts=3
    )

  # pylint: disable=unused-argument
  def _query_automation_db_step(self, db_path, timeout=None):
    """Queries the TCC database.

    Args:
      db_path(string): A string of the path to the sqlite database.

    Returns:
      A string of the query's output.
    """
    query_results = self.m.step(
        'Query TCC db',
        [
            'sqlite3', db_path,
            'SELECT service, client, client_type, auth_value, auth_reason, indirect_object_identifier_type, indirect_object_identifier, flags, last_modified FROM access WHERE service = "kTCCServiceAppleEvents"'
        ],
        stdout=self.m.raw_io.output_text(add_output_log=True),
    )

    return query_results.stdout.rstrip()

  def _checkout_cocoon(self):
    """Checkout cocoon at HEAD to the cache and return the path."""
    cocoon_path = self.m.path.cache_dir.join('cocoon')
    self.m.repo_util.checkout('cocoon', cocoon_path, ref='refs/heads/main')
    return cocoon_path

  def _diagnose_debug_symbols(self, entrypoint, timeout, cocoon_path):
    """Diagnose if attached phones have errors with debug symbols.

    If there are errors, a recovery will be attempted. This function is intended
    to be called in a retry loop until it returns True, or until a max retry
    count is reached.

    Returns a boolean for whether or not the initial diagnose succeeded.
    """
    try:
      self.m.step(
          'diagnose',
          ['dart', entrypoint, 'diagnose'],
      )
      return True
    except self.m.step.StepFailure as e:
      return False

  def _recover_debug_symbols(self, entrypoint, timeout, cocoon_path):
    self.m.step(
        'recover with %s second timeout' % timeout,
        [
            'dart',
            entrypoint,
            'recover',
            '--cocoon-root',
            cocoon_path,
            '--timeout',
            timeout,
        ],
    )

  def is_devicelab(self):
    return str(self.m.swarming.bot_id).startswith('flutter-devicelab') or str(
        self.m.swarming.bot_id
    ).startswith('flutter-win')

  def is_ios(self):
    device_os = self.m.properties.get('device_os', '')
    return device_os.lower().startswith('ios-')

  def is_vs_installed(self, version=None):
    if not self.m.platform.is_win:
      return False

    vswhere_path = self.m.path.join(
        os.environ.get('PROGRAMFILES(X86)'),
        'Microsoft Visual Studio',
        'Installer',
        'vswhere.exe',
    )

    # Return mocked result for testing.
    vswhereexists = self._test_data.get(
        'vswhereexists', True
    ) if self._test_data.enabled else self.m.path.exists(vswhere_path)

    # Return False if vswhere does not exist.
    if not vswhereexists:
      return False

    result = self.m.step(
        'Detect installation',
        [vswhere_path, '-legacy', '-prerelease', '-format', 'json'],
        stdout=self.m.json.output()
    )

    # If no version is provided any vs_build installed version is ok.
    if not version:
      return len(result.stdout) > 0

    # If version is provided we look for that specific version in the installations.
    for installation in result.stdout:
      if installation.get('catalog', {}).get('productLineVersion') == version:
        return True

    return False
