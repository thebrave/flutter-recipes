# Copyright 2020 The Chromium Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.
#
# Recipe to run shard + subshard tests for the Flutter SDK repository.
# This recipe will run a single shard and will be used by flutter/flutter.py.

from contextlib import contextmanager
import re

from RECIPE_MODULES.flutter.flutter_bcid.api import BcidStage

DEPS = [
    'flutter/flutter_bcid',
    'flutter/flutter_deps',
    'flutter/logs_util',
    'flutter/os_utils',
    'flutter/osx_sdk',
    'flutter/repo_util',
    'flutter/retry',
    'flutter/test_utils',
    'flutter/token_util',
    'recipe_engine/context',
    'recipe_engine/path',
    'recipe_engine/properties',
    'recipe_engine/step',
    'recipe_engine/file',
]

# Default timeouts for framework tests.
HOSTONLY_TIMEOUT_SECS = 30 * 60
DEVICELAB_TIMEOUT_SECS = 10 * 60


def RunShard(api, env, env_prefixes, checkout_path):
  with api.context(env=env, env_prefixes=env_prefixes, cwd=checkout_path):
    cmd_list = [
        'dart', '--enable-asserts',
        checkout_path.join('dev', 'bots', 'test.dart')
    ]
    if env.get('LOCAL_WEB_SDK'):
      cmd_list.extend(['--local-web-sdk', env.get('LOCAL_WEB_SDK')])

    # Default timeout for tasks in either devicelab or hostonly.
    default_timeout_secs = DEVICELAB_TIMEOUT_SECS if api.test_utils.is_devicelab_bot(
    ) else HOSTONLY_TIMEOUT_SECS
    deps_timeout_secs = api.properties.get(
        'test_timeout_secs'
    ) or default_timeout_secs
    env['GCP_PROJECT'] = 'flutter-infra'
    with api.context(env=env, env_prefixes=env_prefixes):
      api.test_utils.run_test(
          'run test.dart for %s shard and subshard %s' %
          (api.properties.get('shard'), api.properties.get('subshard')),
          cmd_list,
          timeout_secs=deps_timeout_secs
      )
      api.logs_util.show_logs_stdout(checkout_path.join('error.log'))
      api.logs_util.upload_test_metrics(
          checkout_path.join('test_results.json'),
          '%s_%s' % (api.properties.get('shard'), api.properties.get('subshard'))
      )


def RunSteps(api):
  api.flutter_bcid.report_stage(BcidStage.START.value)
  # Collect memory/cpu/process before task execution.
  api.os_utils.collect_os_info()
  api.os_utils.print_pub_certs()

  checkout_path = api.path['start_dir'].join('flutter')
  api.flutter_bcid.report_stage(BcidStage.FETCH.value)
  api.repo_util.checkout(
      'flutter',
      checkout_path=checkout_path,
      url=api.properties.get('git_url'),
      ref=api.properties.get('git_ref')
  )

  env, env_prefixes = api.repo_util.flutter_environment(checkout_path)
  deps = api.properties.get('dependencies', [])
  api.flutter_deps.required_deps(env, env_prefixes, deps)
  # Add shard, subshard, and test scope.
  env['SHARD'] = api.properties.get('shard')
  env['SUBSHARD'] = api.properties.get('subshard')
  env['REDUCED_TEST_SET'] = api.properties.get('reduced_test_set', False)

  with api.context(env=env, env_prefixes=env_prefixes, cwd=checkout_path):
    # Dependencies timeout.
    deps_timeout_secs = 300
    api.retry.step(
        'download dependencies', ['flutter', 'update-packages', '-v'],
        max_attempts=2,
        infra_step=True
    )
    env['TOKEN_PATH'] = api.token_util.metric_center_token()
    # Load local engine information if available.
    api.flutter_deps.flutter_engine(env, env_prefixes)
    dep_list = [d['dependency'] for d in deps]
    if 'xcode' in dep_list:
      with api.osx_sdk('ios'), api.step.defer_results():
        api.flutter_deps.gems(
            env, env_prefixes, checkout_path.join('dev', 'ci', 'mac')
        )
        api.step(
            'flutter doctor',
            ['flutter', 'doctor', '-v'],
        )
        RunShard(api, env, env_prefixes, checkout_path)
        # This is to clean up leaked processes.
        api.os_utils.kill_processes()
        # Collect memory/cpu/process after task execution.
        api.os_utils.collect_os_info()
    else:
      with api.step.defer_results():
        api.step(
            'flutter doctor',
            ['flutter', 'doctor', '-v'],
        )
        RunShard(api, env, env_prefixes, checkout_path)
        # This is to clean up leaked processes.
        api.os_utils.kill_processes()
        # Collect memory/cpu/process after task execution.
        api.os_utils.collect_os_info()


def GenTests(api):
  for should_run_reduced in (True, False):
    yield api.test(
        'no_requirements%s' % ( '_reduced' if should_run_reduced else ''), api.repo_util.flutter_environment_data(),
        api.properties(reduced_test_set=should_run_reduced)
    )
    yield api.test(
        'android_sdk%s' % ( '_reduced' if should_run_reduced else ''), api.repo_util.flutter_environment_data(),
        api.properties(
            dependencies=[{'dependency': 'android_sdk'}],
            android_sdk=True,
            android_sdk_preview_license='abc',
            android_sdk_license='cde',
            reduced_test_set=should_run_reduced
        )
    )
    yield api.test(
        'web_engine%s' % ( '_reduced' if should_run_reduced else ''), api.repo_util.flutter_environment_data(),
        api.properties(
        local_web_sdk_cas_hash='abceqwe',
        reduced_test_set=should_run_reduced
        )
    )
    yield api.test(
        'xcode%s' % ( '_reduced' if should_run_reduced else ''), api.repo_util.flutter_environment_data(),
        api.properties(dependencies=[{'dependency': 'xcode'}], reduced_test_set=should_run_reduced)
    )
