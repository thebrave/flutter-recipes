# Copyright 2020 The Chromium Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

import os
from contextlib import contextmanager
from recipe_engine import recipe_api

from PB.go.chromium.org.luci.buildbucket.proto import common as common_pb2

TIMEOUT_PROPERTY = 'ios_debug_symbol_doctor_timeout_seconds'
XCODE_AUTOMATION_DB = 'TCC.db'
XCODE_AUTOMATION_BACKUP_DB = 'TCC.db.backup'


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

  def print_pub_certs(self):
    """Prints pub.dev certificates."""
    cmd = (
        'gci -Recurse cert: |Where-Object {$_.Subject -like "*GTS CA 1D4*"'
        ' -or $_.FriendlyName -like "GlobalSign Root CA - R1" -or $_.Subject'
        ' -like "*GTS Root R1*"}'
    )
    if self.m.platform.is_win:
      self.m.step(
          'Print pub.dev certs',
          ['powershell.exe', cmd],
          infra_step=True,
      )

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
    derived_data_path = self.m.path['home'].join(
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
          'kill dart',
          ['killall', '-9', 'com.apple.CoreSimulator.CoreSimulatorDevice'],
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
            'kill dart', ['killall', '-9', 'dart'],
            ok_ret='any',
            infra_step=True
        )
        self.m.step(
            'kill flutter', ['killall', '-9', 'flutter'],
            ok_ret='any',
            infra_step=True
        )
        self.m.step(
            'kill Chrome', ['killall', '-9', 'Chrome'],
            ok_ret='any',
            infra_step=True
        )
        self.m.step(
            'kill Safari', ['killall', '-9', 'Safari'],
            ok_ret='any',
            infra_step=True
        )
        self.m.step(
            'kill Safari', ['killall', '-9', 'java'],
            ok_ret='any',
            infra_step=True
        )
        self.m.step(
            'kill Safari', ['killall', '-9', 'adb'],
            ok_ret='any',
            infra_step=True
        )
        self.m.step(
            'kill Xcode', ['killall', '-9', 'Xcode'],
            ok_ret='any',
            infra_step=True
        )
      else:
        self.m.step(
            'kill chrome', ['pkill', 'chrome'], ok_ret='any', infra_step=True
        )
        self.m.step(
            'kill dart', ['pkill', 'dart'], ok_ret='any', infra_step=True
        )
        self.m.step(
            'kill flutter', ['pkill', 'flutter'], ok_ret='any', infra_step=True
        )
        self.m.step(
            'kill java', ['pkill', 'java'], ok_ret='any', infra_step=True
        )
        self.m.step('kill adb', ['pkill', 'adb'], ok_ret='any', infra_step=True)
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
    if self._is_devicelab() and self.m.platform.is_mac:
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
    if not self._is_devicelab() or not self.m.platform.is_mac:
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

  def dismiss_dialogs(self):
    """Dismisses iOS and macOS dialogs to avoid problems.

    Args:
      flutter_path(Path): A path to the checkout of the flutter sdk repository.
    """
    if str(self.m.swarming.bot_id
          ).startswith('flutter-devicelab') and self.m.platform.is_mac:
      with self.m.step.nest('Dismiss dialogs'):
        with self.m.step.nest('Dismiss iOS dialogs'):
          cocoon_path = self._checkout_cocoon()
          resource_name = self.resource('dismiss_dialogs.sh')
          self.m.step(
              'Set execute permission',
              ['chmod', '755', resource_name],
              infra_step=True,
          )
          with self.m.context(
              cwd=cocoon_path.join('cipd_packages', 'device_doctor', 'tool',
                                   'infra-dialog'),
              infra_steps=True,
          ):
            device_id = self.m.step(
                'Find device id', ['idevice_id', '-l'],
                stdout=self.m.raw_io.output_text()
            ).stdout.rstrip()
            cmd = [resource_name, device_id]
            self.m.step('Run app to dismiss dialogs', cmd)
        with self.m.step.nest('Dismiss Xcode automation dialogs'):
          self._dismiss_xcode_automation_dialogs(device_id)

  def _dismiss_xcode_automation_dialogs(self, device_id):
    """Dismiss Xcode automation permission dialog and update permission db.

    Only required for CoreDevices (physical iOS 17+ devices) or "xcode_debug" tests.

    Args:
      device_id(string): A string of the selected device's UDID.
    """

    # Get list of wired CoreDevices.
    # Allow any return code and ignore failure since this command will only
    # work with Xcode 15 and therefore may not work for all machines.
    self.m.step(
        'List CoreDevices',
        [
            'xcrun',
            'devicectl',
            'list',
            'devices',
            '-v',
        ],
        infra_step=True,
        raise_on_failure=False,
        ok_ret='any',
    )

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
        stdout=self.m.raw_io.output_text(),
        infra_step=True,
        raise_on_failure=False,
        ok_ret='any',
    ).stdout.rstrip()

    builder_name = self.m.properties.get('buildername')

    self.m.step.empty("Get buildername", step_text=builder_name)

    # Skip the rest of this step if the device is not a CoreDevice and the
    # builder name doesn't contain 'xcode_debug'.
    # Builders with 'xcode_debug' in the name force tests the workflow that
    # requires this permission.
    if device_id not in device_list and 'xcode_debug' not in builder_name:
      return

    tcc_directory_path, db_path, backup_db_path = self._get_tcc_path()

    # Ensure db exists
    self.m.step(
        'List TCC directory',
        ['ls', tcc_directory_path],
        infra_step=True,
    )

    files = self.m.step(
        'Find TCC directory',
        ['ls', tcc_directory_path],
        stdout=self.m.raw_io.output_text(),
        infra_step=True,
    ).stdout.rstrip()

    if XCODE_AUTOMATION_DB not in files:
      self.m.step.empty(
          'Failed to find TCC.db',
          status=self.m.step.INFRA_FAILURE,
      )

    # Print contents of db for potential debugging purposes.
    self._query_automation_db_step(db_path)

    # Create backup db if there isn't one.
    # If there is already a backup, it's most likely that a previous run did
    # not complete correctly and did not get reset, so don't overwrite the backup.
    if XCODE_AUTOMATION_BACKUP_DB not in files:
      self.m.step(
          'Create backup db',
          ['cp', db_path, backup_db_path],
          infra_step=True,
      )

    # Run an arbitrary AppleScript Xcode command to trigger permissions dialog.
    # The AppleScript counts how many Xcode windows are open.
    # The script will hang if permission has not been given, so timeout after
    # a few seconds.
    self.m.step(
        'Trigger dialog',
        [
            'osascript',
            '-e',
            'tell app "Xcode"',
            '-e',
            'launch',
            '-e',
            'count window',
            '-e',
            'end tell',
        ],
        infra_step=True,
        raise_on_failure=False,
        ok_ret='any',
        timeout=2,
    )

    # Kill the dialog. After killing the dialog, an entry for the app requesting
    # control of Xcode should automatically be added to the db.
    self.m.step(
        'Dismiss dialog',
        ['killall', '-9', 'UserNotificationCenter'],
        infra_step=True,
        ok_ret='any',
    )

    # Print contents of db for potential debugging purposes.
    self._query_automation_db_step(db_path)

    # Update the db to make it think permission was given.
    self.m.step(
        'Update db',
        [
            'sqlite3', db_path,
            "UPDATE access SET auth_value = 2, auth_reason = 3, flags = NULL WHERE service = 'kTCCServiceAppleEvents' AND indirect_object_identifier = 'com.apple.dt.Xcode'"
        ],
        infra_step=True,
    )

    # Print contents of db for potential debugging purposes.
    self._query_automation_db_step(db_path)

    # Xcode was opened by Applescript, so kill it.
    self.m.step(
        'Kill Xcode',
        ['killall', '-9', 'Xcode'],
        infra_step=True,
        ok_ret='any',
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
    db_path = os.path.join(tcc_directory_path, XCODE_AUTOMATION_DB)
    backup_db_path = os.path.join(
        tcc_directory_path, XCODE_AUTOMATION_BACKUP_DB
    )
    return tcc_directory_path, db_path, backup_db_path

  def _query_automation_db_step(self, db_path):
    """Queries the TCC database.

    Args:
      db_path(string): A string of the path to the sqlite database.
    """
    self.m.step(
        'Query TCC db',
        [
            'sqlite3', db_path,
            'SELECT service, client, client_type, auth_value, auth_reason, indirect_object_identifier_type, indirect_object_identifier, flags, last_modified FROM access WHERE service = "kTCCServiceAppleEvents"'
        ],
        infra_step=True,
    )

  def reset_automation_dialogs(self):
    """Reset Xcode Automation permissions."""
    if str(self.m.swarming.bot_id
          ).startswith('flutter-devicelab') and self.m.platform.is_mac:
      with self.m.step.nest('Reset Xcode automation dialogs'):
        tcc_directory_path, db_path, backup_db_path = self._get_tcc_path()

        files = self.m.step(
            'Find TCC directory',
            ['ls', tcc_directory_path],
            stdout=self.m.raw_io.output_text(),
            infra_step=True,
            raise_on_failure=False,
            ok_ret='any',
        ).stdout.rstrip()

        if XCODE_AUTOMATION_BACKUP_DB not in files:
          return

        self.m.step(
            'Restore from backup db',
            ['cp', backup_db_path, db_path],
        )
        self.m.step(
            'Remove backup',
            ['rm', backup_db_path],
        )

        # Print contents of db for potential debugging purposes.
        self._query_automation_db_step(db_path)

  def _checkout_cocoon(self):
    """Checkout cocoon at HEAD to the cache and return the path."""
    cocoon_path = self.m.path['cache'].join('cocoon')
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

  def _is_devicelab(self):
    return str(self.m.swarming.bot_id).startswith('flutter-devicelab')
