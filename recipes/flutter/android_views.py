# Copyright 2020 The Chromium Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

# TODO(garyq): This Android AVD based test is currently implemented as a separate recipe
# to validate stability of AVD in pre and post submit. Move this into the general recipe
# once validated, stable, and no longer under heavy development.

from PB.recipes.flutter.engine.engine import InputProperties
from PB.recipes.flutter.engine.engine import EnvProperties

DEPS = [
    'flutter/android_virtual_device',
    'flutter/flutter_deps',
    'flutter/os_utils',
    'flutter/repo_util',
    'flutter/retry',
    'recipe_engine/context',
    'recipe_engine/defer',
    'recipe_engine/file',
    'recipe_engine/path',
    'recipe_engine/properties',
    'recipe_engine/raw_io',
    'recipe_engine/step',
]

PROPERTIES = InputProperties
ENV_PROPERTIES = EnvProperties


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
      env, env_prefixes, api.properties.get('dependencies', [])
  )

  deps = api.properties.get('dependencies', [])
  dep_list = {d['dependency']: d.get('version') for d in deps}
  # If the emulator dependency is present then we assume it is wanted for testing.
  if 'android_virtual_device' in dep_list.keys():
    env['USE_EMULATOR'] = True
    env['EMULATOR_VERSION'] = dep_list.get('android_virtual_device')

  with api.android_virtual_device(env=env, env_prefixes=env_prefixes, version=env['EMULATOR_VERSION']):
    with api.context(env=env, env_prefixes=env_prefixes, cwd=checkout_path):
      views_test_dir = checkout_path.join(
        'dev', 'integration_tests', 'android_views'
      )
      with api.step.nest('prepare environment'):
        deferred = []
        # This prevents junk analytics from being sent due to testing
        deferred.append(
            api.defer(
                api.step,
                'flutter config --no-analytics',
                ['flutter', 'config', '--no-analytics'],
            )
        )
        deferred.append(
            api.defer(
                api.step,
                'flutter doctor',
                ['flutter', 'doctor'],
            )
        )
        deferred.append(
            api.defer(
                api.step,
                'flutter devices',
                ['flutter', 'devices', '--device-timeout=40', '--verbose'],
            )
        )
        deferred.append(
            api.defer(
                api.step,
                'download flutter dependencies',
                ['flutter', 'update-packages', '-v'],
                infra_step=True,
            )
        )
        api.defer.collect(deferred)

      # Create gradlew file
      with api.context(env=env, env_prefixes=env_prefixes, cwd=views_test_dir):
        api.step(
            'configure android project',
            ['flutter', 'build', 'apk', '--config-only'],
            infra_step=True,
        )
      # Any gradle command downloads gradle if not already present in the cache.
      # ./gradlew dependencies downloads any gradle defined dependencies to the cache.
      # https://docs.gradle.org/current/userguide/viewing_debugging_dependencies.html
      # Downloading gradle and downloading dependencies are a common source of flakes
      # and moving those to an infra step that can be retried shifts the blame
      # individual tests to the infra itself.
      android_path = views_test_dir.join('android')
      with api.context(env=env, env_prefixes=env_prefixes, cwd=android_path):
        api.retry.step(
            'download android dependencies',
            ['./gradlew', '-q', 'dependencies'],
            max_attempts=2,
            infra_step=True,
        )
    with api.context(env=env, env_prefixes=env_prefixes, cwd=views_test_dir):
      api.step(
          'Android Views Integration Tests',
          [
              'flutter', 'drive', '--browser-name=android-chrome',
              '--android-emulator', '--no-start-paused',
              '--purge-persistent-cache', '--device-timeout=30'
          ],
          timeout=700,
      )

  # This is to clean up leaked processes.
  api.os_utils.kill_processes()
  # Collect memory/cpu/process after task execution.
  api.os_utils.collect_os_info()


def GenTests(api):
  checkout_path = api.path['start_dir'].join('flutter sdk')
  avd_api_version = '31'
  yield api.test(
      'flutter_drive_clean_exit',
      api.properties(
          dependencies=[{'dependency': 'android_sdk'}, {
              'dependency': 'android_virtual_device', 'version': '31'
          }, {'dependency': 'curl'}]
      ),
      api.repo_util.flutter_environment_data(checkout_dir=checkout_path),
      api.step_data(
          'start avd.Start Android emulator (API level %s)' % avd_api_version,
          stdout=api.raw_io.output_text(
              'android_' + avd_api_version +
              '_google_apis_x86|emulator-5554 started (pid: 17687)'
          )
      ),
  )
  yield api.test(
      'flutter_drive_zombie_process',
      api.properties(
          dependencies=[{'dependency': 'android_sdk'}, {
              'dependency': 'android_virtual_device', 'version': '31'
          }, {'dependency': 'curl'}]
      ),
      api.repo_util.flutter_environment_data(checkout_dir=checkout_path),
      api.step_data(
          'start avd.Start Android emulator (API level %s)' % avd_api_version,
          stdout=api.raw_io.output_text(
              'android_' + avd_api_version +
              '_google_apis_x86|emulator-5554 started (pid: 17687)'
          )
      ),
      api.step_data(
          'kill and cleanup avd.list processes',
          stdout=api.raw_io.output_text('12345 qemu-system blah')
      ),
  )
