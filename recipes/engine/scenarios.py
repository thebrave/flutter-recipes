# Copyright 2020 The Chromium Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

import re

from PB.recipes.flutter.engine.engine import InputProperties
from PB.recipes.flutter.engine.engine import EnvProperties

DEPS = [
    'depot_tools/depot_tools',
    'flutter/android_virtual_device',
    'flutter/build_util',
    'flutter/flutter_deps',
    'flutter/os_utils',
    'flutter/repo_util',
    'recipe_engine/buildbucket',
    'recipe_engine/context',
    'recipe_engine/file',
    'recipe_engine/path',
    'recipe_engine/properties',
    'recipe_engine/raw_io',
    'recipe_engine/step',
]

PROPERTIES = InputProperties
ENV_PROPERTIES = EnvProperties


def GetCheckoutPath(api):
  return api.path['cache'].join('builder', 'src')


def RunAndroidUnitTests(api, env, env_prefixes):
  """Runs the unit tests for the Android embedder on a x64 Android Emulator."""
  engine_checkout = GetCheckoutPath(api)
  test_dir = engine_checkout.join('flutter', 'testing')
  exe_path = engine_checkout.join(
      'out', 'android_debug_x64', 'flutter_shell_native_unittests'
  )
  with api.context(cwd=test_dir, env=env, env_prefixes=env_prefixes):
    result = api.step(
        'Android Unit Tests', [
            './run_tests.py', '--android-variant', 'android_debug_x64',
            '--type', 'android', '--adb-path', env['ADB_PATH']
        ]
    )


def RunAndroidScenarioTests(api, env, env_prefixes):
  """Runs the scenario test app on a x64 Android emulator.

  See details at
  https://chromium.googlesource.com/chromium/src/+/HEAD/docs/android_emulator.md#using-your-own-emulator-image
  """
  engine_checkout = GetCheckoutPath(api)

  test_dir = engine_checkout.join('flutter', 'testing')
  scenario_app_tests = test_dir.join('scenario_app')

  # Proxies `python` since vpython cannot resolve spec files outside of the jar
  # file containing the python scripts.
  gradle_home_bin_dir = scenario_app_tests.join('android', 'gradle-home', 'bin')
  with api.context(cwd=scenario_app_tests,
                   env_prefixes={'PATH': [gradle_home_bin_dir]
                                }), api.step.defer_results():

    result = api.step(
        'Scenario App Integration Tests',
        ['./run_android_tests.sh', 'android_debug_x64'],
    )


def RunSteps(api, properties, env_properties):
  # Collect memory/cpu/process after task execution.
  api.os_utils.collect_os_info()

  cache_root = api.path['cache'].join('builder')
  checkout = GetCheckoutPath(api)

  api.file.rmtree('Clobber build output', checkout.join('out'))
  api.file.ensure_directory('Ensure checkout cache', cache_root)

  env, env_prefixes = api.repo_util.engine_environment(cache_root)
  api.flutter_deps.required_deps(
      env, env_prefixes, api.properties.get('dependencies', [])
  )

  api.repo_util.engine_checkout(cache_root, env, env_prefixes)
  with api.android_virtual_device(env=env, env_prefixes=env_prefixes):

    with api.context(cwd=cache_root, env=env,
                     env_prefixes=env_prefixes), api.depot_tools.on_path():
      gn_cmd = ['--android', '--android-cpu=x64', '--no-lto']
      api.build_util.run_gn(gn_cmd, checkout)
      api.build_util.build(
          'android_debug_x64', checkout,
          ['scenario_app', 'flutter_shell_native_unittests']
      )
      RunAndroidUnitTests(api, env, env_prefixes)
      RunAndroidScenarioTests(api, env, env_prefixes)

  with api.step.defer_results():
    # This is to clean up leaked processes.
    api.os_utils.kill_processes()
    # Collect memory/cpu/process after task execution.
    api.os_utils.collect_os_info()


def GenTests(api):
  scenario_failures = GetCheckoutPath(api).join(
      'flutter', 'testing', 'scenario_app', 'build', 'reports', 'diff_failures'
  )
  avd_api_version = '31'
  yield api.test(
      'without_failure_upload',
      api.properties(
          dependencies=[
              {'dependency': 'android_virtual_device', 'version': '31'},
          ]
      ),
      api.buildbucket.ci_build(
          builder='Linux Engine',
          git_repo='https://flutter.googlesource.com/mirrors/engine',
          project='flutter',
          revision='abcd1234',
      ),
      api.properties(InputProperties(goma_jobs='1024',),),
      api.step_data(
          'start avd.Start Android emulator (API level %s)' % avd_api_version,
          stdout=api.raw_io.output_text(
              'android_' + avd_api_version +
              '_google_apis_x86|emulator-5554 started (pid: 17687)'
          )
      ),
  )
