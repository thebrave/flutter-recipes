# Copyright 2020 The Chromium Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

from contextlib import contextmanager
import re

from PB.recipes.flutter.engine import InputProperties
from PB.recipes.flutter.engine import EnvProperties

DEPS = [
    'depot_tools/depot_tools',
    'flutter/os_utils',
    'flutter/repo_util',
    'flutter/flutter_deps',
    'recipe_engine/context',
    'recipe_engine/path',
    'recipe_engine/platform',
    'recipe_engine/properties',
    'recipe_engine/cipd',
    'recipe_engine/file',
    'recipe_engine/python',
    'recipe_engine/raw_io',
    'recipe_engine/step',
]

PROPERTIES = InputProperties
ENV_PROPERTIES = EnvProperties

def KillZombieEmulatorProcesses(api):
  # Kill zombie processes left over by QEMU on the host.
  step_result = api.step('list processes', ['ps', '-axww'], stdout=api.raw_io.output())
  zombieList = ['pm serve', 'qemu-system']
  killCommand = ['kill', '-9']
  for line in step_result.get_result().stdout.splitlines():
    # Check if current process has zombie process substring.
    if any(zombie in line for zombie in zombieList):
      killCommand.append(line.split(None, 1)[0])
  if len(killCommand) > 2:
    api.step('Kill zombie processes', killCommand)

def RunSteps(api, properties, env_properties):
  # Collect memory/cpu/process before task execution.
  api.os_utils.collect_os_info()
  api.os_utils.print_pub_certs()

  cache_root = api.path['cache'].join('builder')

  api.file.ensure_directory('Ensure root cache', cache_root)

  checkout_path = api.path['start_dir'].join('flutter sdk')
  with api.step.nest('checkout source code'):
    api.repo_util.checkout(
        'flutter',
        checkout_path=checkout_path,
        url=api.properties.get('git_url'),
        ref=api.properties.get('git_ref'),
    )

  env, env_prefixes = api.repo_util.flutter_environment(checkout_path)
  api.flutter_deps.required_deps(
      env, env_prefixes, api.properties.get('dependencies', [{'dependency': 'android_sdk'}])
  )
  with api.context(env=env, env_prefixes=env_prefixes, cwd=cache_root), api.depot_tools.on_path():
    avd_cache_dir = cache_root.join('avd')
    api.file.ensure_directory('Ensure avd cache', avd_cache_dir)
    # Download and install AVD
    api.cipd.ensure(
        avd_cache_dir,
        api.cipd.EnsureFile().add_package(
            'chromium/tools/android/avd/linux-amd64',
            'p-1EgH-og45NbJT5ld4bBmvhayUxyb5Wm0oedSBwXOsC'
        )
    )

    avd_script_path = avd_cache_dir.join(
        'src', 'tools', 'android', 'avd', 'avd.py'
    )
    avd_config = avd_cache_dir.join(
        'src', 'tools', 'android', 'avd', 'proto', 'generic_android31.textpb'
    )

    adb_script_path = avd_cache_dir.join(
        'src', 'third_party', 'android_sdk', 'public', 'platform-tools', 'adb'
    )

    emulator_pid = ''
    with api.context(env=env, env_prefixes=env_prefixes, cwd=avd_cache_dir):
      with api.step.nest('start avd'):
        api.python(
            'Install Android emulator (API level 31)', avd_script_path,
            ['install', '--avd-config', avd_config]
        )
        output = api.python(
            'Start Android emulator (API level 31)',
            avd_script_path,
            ['start', '--no-read-only', '--writable-system', '--avd-config', avd_config],
            stdout=api.raw_io.output()
        ).stdout
        m = re.match('.*pid: (\d+)\)', output)
        emulator_pid = m.group(1)

        api.step(
            'adb kill-server',
            [str(adb_script_path), 'kill-server'],
        )
        api.step(
            'adb start-server',
            [str(adb_script_path), 'start-server'],
        )
        # Wait for avd to initialize
        api.step(
            'adb wait-for-device',
            [str(adb_script_path), 'wait-for-device'],
        )
        # Wait for avd to reach home screen
        api.step(
            'adb wait until booted completed',
            [
              str(adb_script_path),
              '-s',
              'emulator-5554',
              'shell',
              'while [[ -z $(getprop sys.boot_completed) ]]; do sleep 1; done;'
            ],
        )
        api.step(
            'adb devices',
            [str(adb_script_path), 'devices'],
        )
        # unlock avd
        api.step(
            'adb shell input keyevent 82',
            [str(adb_script_path), 'shell', 'input', 'keyevent', '82'],
        )
        # Ensure developer mode is enabled
        api.step(
            'adb shell settings put global development_settings_enabled 1',
            [str(adb_script_path), 'shell', 'settings', 'put', 'global', 'development_settings_enabled', '1'],
        )

    with api.context(env=env, env_prefixes=env_prefixes, cwd=checkout_path):
      with api.step.nest('prepare environment'), api.step.defer_results():
        # This prevents junk analytics from being sent due to testing
        api.step(
            'flutter config --no-analytics',
            ['flutter', 'config', '--no-analytics'],
        )
        api.step(
            'flutter doctor',
            ['flutter', 'doctor'],
        )
        api.step(
            'flutter devices',
            ['flutter', 'devices', '--device-timeout=40', '--verbose'],
        )
        api.step(
            'download dependencies',
            ['flutter', 'update-packages'],
            infra_step=True,
        )
    views_test_dir = checkout_path.join('dev', 'integration_tests', 'android_views')
    with api.context(env=env, env_prefixes=env_prefixes, cwd=views_test_dir):
      api.step(
          'Android Views Integration Tests',
          [
            'flutter',
            'drive',
            '--browser-name=android-chrome',
            '--android-emulator',
            '--no-start-paused',
            '--purge-persistent-cache',
            '--device-timeout=30'
          ],
          timeout=700,
      )

  with api.step.nest('cleanup'), api.step.defer_results():
    api.step('Kill emulator cleanup', ['kill', '-9', emulator_pid])
    KillZombieEmulatorProcesses(api)
    # This is to clean up leaked processes.
    api.os_utils.kill_processes()
    # Collect memory/cpu/process after task execution.
    api.os_utils.collect_os_info()


def GenTests(api):
  checkout_path = api.path['start_dir'].join('flutter sdk')
  yield api.test(
      'flutter_drive_clean_exit',
      api.repo_util.flutter_environment_data(checkout_dir=checkout_path),
      api.step_data(
          'start avd.Start Android emulator (API level 31)',
          stdout=api.raw_io.output_text(
              'android_31_google_apis_x86|emulator-5554 started (pid: 17687)'
          )
      ),
  )
  yield api.test(
      'flutter_drive_zombie_process',
      api.repo_util.flutter_environment_data(checkout_dir=checkout_path),
      api.step_data(
          'start avd.Start Android emulator (API level 31)',
          stdout=api.raw_io.output_text(
              'android_31_google_apis_x86|emulator-5554 started (pid: 17687)'
          )
      ),
      api.step_data(
          'cleanup.list processes',
          stdout=api.raw_io.output_text(
              '12345 qemu-system blah'
          )
      ),
  )
