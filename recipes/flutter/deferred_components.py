# Copyright 2020 The Chromium Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

# TODO(garyq): This Android AVD based test is currently implemented as a separate recipe
# to validate stability of AVD in pre and post submit. Move this into the general recipe
# once validated, stable, and no longer under heavy development.

from contextlib import contextmanager
import re

from PB.recipes.flutter.engine.engine import InputProperties
from PB.recipes.flutter.engine.engine import EnvProperties

DEPS = [
    'flutter/android_virtual_device',
    'flutter/flutter_deps',
    'flutter/os_utils',
    'flutter/repo_util',
    'recipe_engine/cipd',
    'recipe_engine/context',
    'recipe_engine/defer',
    'recipe_engine/file',
    'recipe_engine/path',
    'recipe_engine/properties',
    'recipe_engine/raw_io',
    'recipe_engine/step',
]

# Builder dependencies requried:
#  - android_sdk
#  - android_avd
#  - curl

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

  with api.android_virtual_device(env=env, env_prefixes=env_prefixes):
    bundletool_dir = cache_root.join('bundletool')
    bundletool_jar = bundletool_dir.join('bundletool.jar')
    with api.context(env=env, env_prefixes=env_prefixes, cwd=checkout_path):
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
                'download dependencies',
                ['flutter', 'update-packages', '-v'],
                infra_step=True,
            )
        )
        deferred.append(
            api.defer(
                api.cipd.ensure,
                bundletool_dir,
                api.cipd.EnsureFile().add_package(
                    'flutter/android/bundletool',
                    '0xeDa85nRhdQfi3iN2dK8PPluwI73z9San_Afuj3CfgC'
                )
            )
        )
        api.defer.collect(deferred)

    test_dir = checkout_path.join(
        'dev', 'integration_tests', 'deferred_components_test'
    )
    with api.context(env=env, env_prefixes=env_prefixes, cwd=test_dir):
      deferred = []
      # These assets are not allowed to be checked into the repo,
      # so they are downloaded separately here.
      deferred.append(
          api.defer(
              api.step, 'download assets script', ['./download_assets.sh']
          )
      )
      deferred.append(
          api.defer(
              api.step,
              'Deferred components release tests',
              ['./run_release_test.sh',
               str(bundletool_jar), env['ADB_PATH']],
              timeout=700,
          )
      )
      api.defer.collect(deferred)

    # This is to clean up leaked processes.
    api.os_utils.kill_processes()
    # Collect memory/cpu/process after task execution.
    api.os_utils.collect_os_info()


def GenTests(api):
  checkout_path = api.path['start_dir'].join('flutter sdk')
  avd_api_version = '31'
  yield api.test(
      'flutter_release_clean_exit',
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
      'flutter_release_zombie_process',
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
