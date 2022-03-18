# Copyright 2020 The Chromium Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.
import re
from contextlib import contextmanager
from recipe_engine import recipe_api


class AndroidVirtualDeviceApi(recipe_api.RecipeApi):
  """Installs and manages an Android AVD.
  """

  def download(self, avd_root, env, env_prefixes, version=None):
    """Installs the android avd emulator package.

    Args:
      env(dict): Current environment variables.
      env_prefixes(dict):  Current environment prefixes variables.
      avd_root: The root path to install the AVD package.
    """
    assert self.m.platform.is_linux
    self.avd_root = avd_root
    self.version = version
    with self.m.step.nest('download avd package'):
      self.m.file.ensure_directory('Ensure avd cache', self.avd_root)
      with self.m.context(env=env, env_prefixes=env_prefixes, cwd=self.avd_root), self.m.depot_tools.on_path():
        # Download and install AVD
        self.m.cipd.ensure(
            self.avd_root,
            self.m.cipd.EnsureFile().add_package(
                'chromium/tools/android/avd/linux-amd64',
                'p-1EgH-og45NbJT5ld4bBmvhayUxyb5Wm0oedSBwXOsC'
            )
        )

      adb_root = self.avd_root.join(
          'src', 'third_party', 'android_sdk', 'public', 'platform-tools'
      )
      self.adb_path = adb_root.join('adb')
      paths = env_prefixes.get('PATH', [])
      paths.append(adb_root)
      env_prefixes['PATH'] = paths
    env['AVD_ROOT'] = self.avd_root
    env['ADB_PATH'] = self.adb_path

  def start(self, env, env_prefixes, version=None):
    """Starts an android avd emulator.

    Args:
      env(dict): Current environment variables.
      env_prefixes(dict):  Current environment prefixes variables.
      version(string): The android API version of the emulator as a string.
    """
    self.version = version or self.version or '31'
    self.emulator_pid = ''
    with self.m.step.nest('start avd'):
      with self.m.context(env=env, env_prefixes=env_prefixes, cwd=self.avd_root), self.m.depot_tools.on_path():
        avd_script_path = self.avd_root.join(
            'src', 'tools', 'android', 'avd', 'avd.py'
        )
        avd_config = self.avd_root.join(
            'src', 'tools', 'android', 'avd', 'proto', 'generic_android%s.textpb' % self.version
        )
        self.m.python(
            'Install Android emulator (API level %s)' % self.version, avd_script_path,
            ['install', '--avd-config', avd_config]
        )
        output = self.m.python(
            'Start Android emulator (API level %s)' % self.version,
            avd_script_path,
            ['start', '--no-read-only', '--writable-system', '--wipe-data', '--avd-config', avd_config],
            stdout=self.m.raw_io.output_text()
        ).stdout
        m = re.match('.*pid: (\d+)\)', output)
        self.emulator_pid = m.group(1)
    env['EMULATOR_PID'] = self.emulator_pid
    return self.emulator_pid

  def setup(self, env, env_prefixes):
    """Configures a running emulator and waits for it to reach the home screen.

    Args:
      env(dict): Current environment variables.
      env_prefixes(dict):  Current environment prefixes variables.
    """
    with self.m.step.nest('avd setup'):
      with self.m.context(env=env, env_prefixes=env_prefixes, cwd=self.avd_root):
        # Only supported on linux. Do not run this on other platforms.
        resource_name = self.resource('avd_setup.sh')
        self.m.step(
            'Set execute permission',
            ['chmod', '755', resource_name],
            infra_step=True,
        )
        self.m.test_utils.run_test('avd_setup.sh', [resource_name, str(self.adb_path)])

  def kill(self, emulator_pid=None):
    """Kills the emulator and cleans up any zombie QEMU processes.

    Args:
      emulator_pid(string): The PID of the emulator process.
    """
    assert self.m.platform.is_linux
    with self.m.step.nest('kill and cleanup avd'):
      pid_to_kill = emulator_pid or self.emulator_pid
      self.m.step('Kill emulator cleanup', ['kill', '-9', pid_to_kill])

      # Kill zombie processes left over by QEMU on the host.
      step_result = self.m.step('list processes',
          ['ps', '-axww'],
          stdout=self.m.raw_io.output_text(add_output_log=True),
          stderr=self.m.raw_io.output_text(add_output_log=True))
      zombieList = ['qemu-system']
      killCommand = ['kill', '-9']
      for line in step_result.stdout.splitlines():
        # Check if current process has zombie process substring.
        if any(zombie in line for zombie in zombieList):
          killCommand.append(line.split(None, 1)[0])
      if len(killCommand) > 2:
        self.m.step('Kill zombie processes', killCommand, ok_ret='any')
