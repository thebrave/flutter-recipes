# Copyright 2020 The Chromium Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.
import re
from contextlib import contextmanager
from recipe_engine import recipe_api

RERUN_ATTEMPTS = 3


class AndroidVirtualDeviceApi(recipe_api.RecipeApi):
  """Installs and manages an Android AVD.
  """

  def __init__(self, *args, **kwargs):
    super(AndroidVirtualDeviceApi, self).__init__(*args, **kwargs)
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
    self.avd_root = self.m.path.cache_dir / 'avd'
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
      self.start(env, env_prefixes, version)
      yield
    finally:
      self.kill()
      self.uninstall(env, env_prefixes, version=version)
      self.show_devices(env, env_prefixes, "after emulator uninstall")

  def download(self, env, env_prefixes):
    """Installs the android avd emulator package.

    Args:
      env(dict): Current environment variables.
      env_prefixes(dict):  Current environment prefixes variables.
      avd_root(Path): The root path to install the AVD package.
    """
    cipd_version = env.get('AVD_CIPD_VERSION', None)
    if cipd_version is None:
      raise self.m.step.InfraFailure(
        'avd_cipd_version must be set in .ci.yaml target if depending on'
        'android_virtual_device'
      )
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

      adb_root = (
          self.avd_root / 'src/third_party/android_sdk/public/platform-tools'
      )
      self.adb_path = adb_root / 'adb'
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
        avd_config = (
            self.avd_root / 'src/tools/android/avd/proto' /
            f'android_{version}_google_apis_x64.textpb'
        )
      else:
        avd_config = (
            self.avd_root /
            f'src/tools/android/avd/proto/generic_android{version}.textpb'
        )
    else:
      avd_config = self.avd_root / f'src/tools/android/avd/proto{version}'

    return avd_config

  def start(self, env, env_prefixes, version):
    """Starts an android avd emulator.

    Args:
      env(dict): Current environment variables.
      env_prefixes(dict):  Current environment prefixes variables.
      version(string): The android API version of the emulator as a string.
    """
    with self.m.step.nest('start avd'):
      with self.m.context(env=env, env_prefixes=env_prefixes,
                          cwd=self.avd_root), self.m.depot_tools.on_path():
        avd_script_path = self.avd_root / 'src/tools/android/avd/avd.py'

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
          self.m.step(
              'Start Android emulator (%s)' % version,
              [
                  'xvfb-run',
                  'vpython3',
                  avd_script_path,
                  'start',
                  '--no-read-only',
                  '--wipe-data',
                  '--debug-tags',
                  'all',
                  '--avd-config',
                  avd_config
              ],
              stdout=self.m.raw_io.output_text(add_output_log=True),
              infra_step=True,
          )
          self._setup(env, env_prefixes)

        self.m.retry.wrap(_start, max_attempts=3)

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
        avd_script_path = self.avd_root / 'src/tools/android/avd/avd.py'

        avd_config = self._get_config_version(version=version)

        self.m.step(
            'Uninstall Android emulator (%s)' % version, [
                'vpython3', avd_script_path, 'uninstall', '--avd-config',
                avd_config
            ],
            stdout=self.m.raw_io.output_text(add_output_log=True)
        )

  def kill(self):
    """Kills the emulator and cleans up any zombie QEMU processes.
    """
    assert self.m.platform.is_linux
    with self.m.step.nest('kill and cleanup avd'):
      self.m.step('List processes before cleaning up', ['ps', 'aux'])
      # Accepting any return code because when the emulator dies the pid is no longer
      # available causing an exception.
      self.m.step(
          'Kill emulator cleanup', ['pkill', '-9', '-e', '-f', 'emulator'],
          ok_ret='any'
      )
      self.m.step('List processes after cleaning up', ['ps', 'aux'])
