# Copyright 2020 The Chromium Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.
import re
from contextlib import contextmanager
from recipe_engine import recipe_api

# Supports 19 though API 34.
AVD_CIPD_IDENTIFIER = 'nNnmIzfGCF3wVB1sB14hKaU77TdoTFbq6uq_wXHM-WQC'

RERUN_ATTEMPTS = 3


class AndroidVirtualDeviceApi(recipe_api.RecipeApi):
  """Installs and manages an Android AVD.
  """

  def __init__(self, *args, **kwargs):
    super(AndroidVirtualDeviceApi, self).__init__(*args, **kwargs)
    self.emulator_pid = -1
    self.avd_root = None
    self.adb_path = None
    self._initialized = False

  def _initialize(self, env, env_prefixes):
    """Initilizes the android emulator environment if needed."""
    # TODO: Currently only Linux is supported but we will look to support
    # other platforms (mac, win) in the future.
    assert self.m.platform.is_linux
    if self._initialized:
      # Do not download artifacts just update envs.
      env['AVD_ROOT'] = self.avd_root
      env['ADB_PATH'] = self.adb_path
      return
    self.avd_root = self.m.path['cache'].join('avd')
    self.download(
        env=env,
        env_prefixes=env_prefixes,
    )
    self._initialized = True

  @contextmanager
  def __call__(
      self, env, env_prefixes, version='android_31_google_apis_x64.textpb'
  ):
    # check for emulator version in env
    self._initialize(env, env_prefixes)
    try:
      # Show devices before anything to see if anything is left over from a
      # previous run.
      self.show_devices(env, env_prefixes, "before emulator install/start")
      self.emulator_pid = self.start(env, env_prefixes, version)
      yield
    finally:
      self.kill(self.emulator_pid)
      self.uninstall(env, env_prefixes, version=version)
      self.show_devices(env, env_prefixes, "after emulator uninstall")

  def download(self, env, env_prefixes):
    """Installs the android avd emulator package.

    Args:
      env(dict): Current environment variables.
      env_prefixes(dict):  Current environment prefixes variables.
      avd_root(Path): The root path to install the AVD package.
    """
    cipd_version = env.get('AVD_CIPD_VERSION', AVD_CIPD_IDENTIFIER)
    with self.m.step.nest('download avd package'):
      with self.m.context(
          env=env, env_prefixes=env_prefixes), self.m.depot_tools.on_path():
        # Download and install AVD
        self.m.cipd.ensure(
            self.avd_root,
            self.m.cipd.EnsureFile().add_package(
                'chromium/tools/android/avd/linux-amd64', cipd_version
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

  def _get_config_version(self, version):
    """Get the config if given an integer version
    
    Args:
    """
    avd_config = None
    is_int_version = True
    try:
      int(version)
    except ValueError:
      is_int_version = False

    if is_int_version:
      if int(version) > 33:
        avd_config = self.avd_root.join(
            'src', 'tools', 'android', 'avd', 'proto',
            'android_%s_google_apis_x64.textpb' % version
        )
      else:
        avd_config = self.avd_root.join(
            'src', 'tools', 'android', 'avd', 'proto',
            'generic_android%s.textpb' % version
        )
    else:
      avd_config = self.avd_root.join(
          'src', 'tools', 'android', 'avd', 'proto', '%s' % version
      )

    return avd_config

  def start(self, env, env_prefixes, version):
    """Starts an android avd emulator.

    Args:
      env(dict): Current environment variables.
      env_prefixes(dict):  Current environment prefixes variables.
      version(string): The android API version of the emulator as a string.
    """
    self.emulator_pid = ''
    with self.m.step.nest('start avd'):
      with self.m.context(env=env, env_prefixes=env_prefixes,
                          cwd=self.avd_root), self.m.depot_tools.on_path():
        avd_script_path = self.avd_root.join(
            'src', 'tools', 'android', 'avd', 'avd.py'
        )

        avd_config = self._get_config_version(version=version)

        self.m.step(
            'Install Android emulator (%s)' % version, [
                'vpython3', avd_script_path, 'install', '--avd-config',
                avd_config
            ],
            stdout=self.m.raw_io.output_text(add_output_log=True)
        )

        def _start():
          # In case of retries we need to kill the previous emulator to ensure a fresh
          # start.
          self.kill()
          output = self.m.step(
              'Start Android emulator (%s)' % version,
              [
                  'xvfb-run', 'vpython3', avd_script_path, 'start',
                  '--no-read-only', '--wipe-data', '--writable-system',
                  '--debug-tags', 'all', '--avd-config', avd_config
              ],
              stdout=self.m.raw_io.output_text(add_output_log=True),
              infra_step=True,
          ).stdout

          m = re.search(r'.*pid: (\d+)\)', output)
          self.emulator_pid = m.group(1)
          env['EMULATOR_PID'] = self.emulator_pid
          self._setup(env, env_prefixes)

        self.m.retry.wrap(_start, max_attempts=3)

    return self.emulator_pid

  def _setup(self, env, env_prefixes):
    """Configures a running emulator and waits for it to reach the home screen.

    Args:
      env(dict): Current environment variables.
      env_prefixes(dict):  Current environment prefixes variables.
    """
    with self.m.step.nest('avd setup'):
      with self.m.context(env=env, env_prefixes=env_prefixes,
                          cwd=self.avd_root):
        # Only supported on linux. Do not run this on other platforms.
        resource_name = self.resource('avd_setup.sh')
        self.m.step(
            'Set execute permission',
            ['chmod', '755', resource_name],
            infra_step=True,
        )
        self.m.step(
            'avd_setup.sh', [resource_name, str(self.adb_path)],
            infra_step=True
        )

  def show_devices(self, env, env_prefixes, messsage):
    with self.m.step.nest('Show devices attached - {}'.format(messsage)):
      with self.m.context(env=env, env_prefixes=env_prefixes,
                          cwd=self.avd_root):
        # Only supported on linux. Do not run this on other platforms.
        resource_name = self.resource('adb_show_devices.sh')
        self.m.step(
            'Set execute permission',
            ['chmod', '755', resource_name],
            infra_step=True,
        )
        self.m.test_utils.run_test(
            'adb_show_devices.sh',
            [resource_name, str(self.adb_path)],
            infra_step=True
        )

  def uninstall(self, env, env_prefixes, version):
    """Uninstall all packages related to an android avd emulator.

    Args:
      env(dict): Current environment variables.
      env_prefixes(dict):  Current environment prefixes variables.
    """
    self.emulator_pid = ''
    with self.m.step.nest('uninstall avd'):
      with self.m.context(env=env, env_prefixes=env_prefixes,
                          cwd=self.avd_root), self.m.depot_tools.on_path():
        avd_script_path = self.avd_root.join(
            'src', 'tools', 'android', 'avd', 'avd.py'
        )

        avd_config = self._get_config_version(version=version)

        self.m.step(
            'Uninstall Android emulator (%s)' % version, [
                'vpython3', avd_script_path, 'uninstall', '--avd-config',
                avd_config
            ],
            stdout=self.m.raw_io.output_text(add_output_log=True)
        )

    env['EMULATOR_PID'] = self.emulator_pid
    return self.emulator_pid

  def kill(self, emulator_pid=None):
    """Kills the emulator and cleans up any zombie QEMU processes.

    Args:
      emulator_pid(string): The PID of the emulator process.
    """
    assert self.m.platform.is_linux
    with self.m.step.nest('kill and cleanup avd'):
      pid_to_kill = emulator_pid or self.emulator_pid
      if not pid_to_kill:
        # Noop if there is not emulator to kill.
        return
      # Accepting any return code because when the emulator dies the pid is no longer
      # available causing an exception.
      self.m.step(
          'Kill emulator cleanup', ['kill', '-9', pid_to_kill], ok_ret='any'
      )

      # Kill zombie processes left over by QEMU on the host.
      step_result = self.m.step(
          'list processes', ['ps', '-axww'],
          stdout=self.m.raw_io.output_text(add_output_log=True),
          stderr=self.m.raw_io.output_text(add_output_log=True)
      )
      zombieList = ['qemu-system']
      killCommand = ['kill', '-9']
      for line in step_result.stdout.splitlines():
        # Check if current process has zombie process substring.
        if any(zombie in line for zombie in zombieList):
          killCommand.append(line.split(None, 1)[0])
      if len(killCommand) > 2:
        self.m.step('Kill zombie processes', killCommand, ok_ret='any')
