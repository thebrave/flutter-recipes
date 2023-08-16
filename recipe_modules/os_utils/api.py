# Copyright 2020 The Chromium Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

import os
from contextlib import contextmanager
from recipe_engine import recipe_api

from PB.go.chromium.org.luci.buildbucket.proto import common as common_pb2

TIMEOUT_PROPERTY = 'ios_debug_symbol_doctor_timeout_seconds'


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
    """Dismisses iOS dialogs to avoid problems.

    Args:
      flutter_path(Path): A path to the checkout of the flutter sdk repository.
    """
    if str(self.m.swarming.bot_id
          ).startswith('flutter-devicelab') and self.m.platform.is_mac:
      with self.m.step.nest('Dismiss dialogs'):
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
