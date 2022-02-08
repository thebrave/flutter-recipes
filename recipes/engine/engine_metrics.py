# Copyright 2020 The Chromium Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

from PB.recipes.flutter.engine.engine import InputProperties
from PB.recipes.flutter.engine.engine import EnvProperties

PYTHON_VERSION_COMPATIBILITY = 'PY3'

DEPS = [
    'depot_tools/depot_tools',
    'flutter/build_util',
    'flutter/os_utils',
    'flutter/repo_util',
    'flutter/token_util',
    'recipe_engine/context',
    'recipe_engine/path',
    'recipe_engine/properties',
    'recipe_engine/step',
]
PROPERTIES = InputProperties
ENV_PROPERTIES = EnvProperties


def RunSteps(api, properties, env_properties):
  # Collect memory/cpu/process after task execution.
  api.os_utils.collect_os_info()

  checkout_path = api.path['cache'].join('builder', 'src')
  cache_root = api.path['cache'].join('builder')
  dart_bin = checkout_path.join(
      'third_party', 'dart', 'tools', 'sdks', 'dart-sdk', 'bin'
  )
  android_home = checkout_path.join('third_party', 'android_tools', 'sdk')
  env = {
      'ANDROID_HOME': str(android_home),
      'FLUTTER_PREBUILT_DART_SDK': 'True',
  }
  env_prefixes = {'PATH': [dart_bin]}
  api.repo_util.engine_checkout(cache_root, env, env_prefixes)
  with api.depot_tools.on_path(), api.context(env=env,
                                              env_prefixes=env_prefixes):
    api.build_util.run_gn(['--runtime-mode', 'release', '--prebuilt-dart-sdk'],
                          checkout_path)
    api.build_util.build('host_release', checkout_path, [])

  host_release_path = checkout_path.join('out', 'host_release')
  script_path = checkout_path.join(
      'flutter', 'testing', 'benchmark', 'generate_metrics.sh'
  )
  with api.context(env=env, env_prefixes=env_prefixes,
                   cwd=host_release_path), api.step.defer_results():
    api.step('Generate metrics', ['bash', script_path])
    # This is to clean up leaked processes.
    api.os_utils.kill_processes()
    # Collect memory/cpu/process after task execution.
    api.os_utils.collect_os_info()

  benchmark_path = checkout_path.join('flutter', 'testing', 'benchmark')
  script_path = checkout_path.join(
      'flutter', 'testing', 'benchmark', 'upload_metrics.sh'
  )

  env['TOKEN_PATH'] = api.token_util.metric_center_token()
  env['GCP_PROJECT'] = 'flutter-cirrus'
  with api.context(env=env, env_prefixes=env_prefixes, cwd=benchmark_path):
    if properties.upload_metrics:
      api.step('Upload metrics', ['bash', script_path])
    else:
      api.step('Upload metrics', ['bash', script_path, '--no-upload'])


def GenTests(api):
  for upload_metrics in [True, False]:
    test_name = 'basic_upload_metrics_%s' % upload_metrics
    yield api.test(
        test_name,
        api.properties(
            InputProperties(
                goma_jobs='200',
                no_lto=True,
                upload_metrics=upload_metrics,
            )
        )
    )
