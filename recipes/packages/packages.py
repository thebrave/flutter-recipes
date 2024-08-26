# Copyright 2020 The Chromium Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

from contextlib import ExitStack

DEPS = [
    'flutter/android_virtual_device',
    'flutter/flutter_deps',
    'flutter/logs_util',
    'flutter/os_utils',
    'flutter/osx_sdk',
    'flutter/repo_util',
    'flutter/yaml',
    'recipe_engine/context',
    'recipe_engine/file',
    'recipe_engine/json',
    'recipe_engine/path',
    'recipe_engine/properties',
    'recipe_engine/step',
    'recipe_engine/runtime',
    'recipe_engine/raw_io',
]


def RunSteps(api):
  """Recipe to run flutter package tests."""
  # Collect memory/cpu/process before task execution.
  api.os_utils.collect_os_info()

  # If on macOS, reset Xcode in case a previous build failed to do so.
  api.osx_sdk.reset_xcode()

  packages_checkout_path = api.path.start_dir / 'packages'
  flutter_checkout_path = api.path.start_dir / 'flutter'
  channel = api.properties.get('channel')
  version_file_name = api.properties.get('version_file', '')
  with api.step.nest('checkout source code'):
    api.repo_util.checkout(
        'packages',
        checkout_path=packages_checkout_path,
        url=api.properties.get('git_url'),
        ref=api.properties.get('git_ref')
    )
    # Check out the specified version of Flutter.
    flutter_ref = 'refs/heads/%s' % channel
    # When specified, use a pinned version instead of latest.
    if version_file_name:
      version_file = packages_checkout_path / '.ci' / version_file_name
      flutter_ref = api.file.read_text(
          'read pinned version', version_file, flutter_ref
      ).strip()
    api.repo_util.checkout(
        'flutter',
        checkout_path=flutter_checkout_path,
        ref=flutter_ref,
        url='https://github.com/flutter/flutter',
    )

  env, env_prefixes = api.repo_util.flutter_environment(flutter_checkout_path)

  # Join labels with ',' and do no perform any char escaping.
  env['PR_OVERRIDE_LABELS'] = ','.join(api.properties.get('overrides', ''))

  env['USE_EMULATOR'] = False
  with api.step.nest('Dependencies'):
    deps = api.properties.get('dependencies', [])
    api.flutter_deps.required_deps(env, env_prefixes, deps)
    dep_list = {d['dependency']: d.get('version') for d in deps}
    # If the emulator dependency is present then we assume it is wanted for testing.
    if 'android_virtual_device' in dep_list.keys():
      env['USE_EMULATOR'] = True
      env['EMULATOR_VERSION'] = dep_list.get('android_virtual_device')
    if 'avd_cipd_version' in dep_list.keys():
      env['AVD_CIPD_VERSION'] = dep_list.get('avd_cipd_version')

  with api.context(env=env, env_prefixes=env_prefixes,
                   cwd=flutter_checkout_path):
    with api.step.nest('prepare environment'):
      api.step('flutter doctor', ['flutter', 'doctor', '-v'])
      # Fail fast on dependencies problem.
      timeout_secs = 300
      api.step(
          'download dependencies', ['flutter', 'update-packages', '-v'],
          infra_step=True,
          timeout=timeout_secs
      )
  tests_yaml_path = (
      packages_checkout_path / '.ci/targets' /
      api.properties.get('target_file', 'tests.yaml')
  )
  result = api.yaml.read('read yaml', tests_yaml_path, api.json.output())
  with api.context(env=env, env_prefixes=env_prefixes,
                   cwd=packages_checkout_path):
    with api.step.nest('Run package tests'):
      if api.properties.get('$flutter/osx_sdk'):
        with api.osx_sdk('ios'):
          with api.context(env=env, env_prefixes=env_prefixes):
            run_test(api, result, packages_checkout_path, env, env_prefixes)
      else:
        with ExitStack() as stack:
          if env['USE_EMULATOR']:
            stack.enter_context(
                api.android_virtual_device(
                    env=env,
                    env_prefixes=env_prefixes,
                    version=env['EMULATOR_VERSION']
                )
            )
          run_test(api, result, packages_checkout_path, env, env_prefixes)

  # This is to clean up leaked processes.
  api.os_utils.kill_processes()
  # Collect memory/cpu/process after task execution.
  api.os_utils.collect_os_info()


def run_test(api, result, packages_checkout_path, env, env_prefixes):
  """Run tests sequentially following the script"""
  failed_tasks = []
  for task in result.json.output['tasks']:
    script_path = packages_checkout_path / task['script']
    cmd = ['bash', script_path]
    if 'args' in task:
      args = task['args']
      cmd.extend(args)
    api.logs_util.initialize_logs_collection(env)

    # Flag showing whether the task should always run regardless of previous failures.
    always_run_task = task['always'] if 'always' in task else False
    # Flag showing whether the task should be considered and infra failure or test failure.
    is_infra_step = task['infra_step'] if 'infra_step' in task else False
    with api.context(env=env, env_prefixes=env_prefixes):
      # Runs the task in two scenarios:
      #   1) all earlier tasks pass
      #   2) there are earlier task failures, but the current task is marked as `always: True`.
      #   Note that infra tasks fail and do not run the rest of the tasks including `always`.
      if not failed_tasks or always_run_task:
        step = api.step(
            task['name'],
            cmd,
            raise_on_failure=is_infra_step,
            infra_step=is_infra_step
        )
        if step.retcode != 0:
          failed_tasks.append(task['name'])
    api.logs_util.upload_logs(task['name'])
  if failed_tasks:
    raise api.step.StepFailure('Tasks failed: %s' % ','.join(failed_tasks))


def GenTests(api):
  flutter_path = api.path.start_dir / 'flutter'
  tasks_dict = {
      'tasks': [{
          'name': 'one',
          'script': 'myscript',
          'args': ['arg1', 'arg2']
      }]
  }
  yield api.test(
      'master_channel', api.repo_util.flutter_environment_data(flutter_path),
      api.properties(
          channel='master',
          version_file='flutter_master.version',
      ), api.step_data('read yaml.parse', api.json.output(tasks_dict))
  )
  yield api.test(
      'stable_channel', api.repo_util.flutter_environment_data(flutter_path),
      api.properties(channel='stable',),
      api.step_data('read yaml.parse', api.json.output(tasks_dict))
  )
  yield api.test(
      'mac', api.repo_util.flutter_environment_data(flutter_path),
      api.properties(
          channel='master',
          version_file='flutter_master.version',
          **{'$flutter/osx_sdk': {'sdk_version': 'deadbeef',}},
      ), api.step_data('read yaml.parse', api.json.output(tasks_dict))
  )
  checkout_path = api.path.cleanup_dir / 'tmp_tmp_1/flutter sdk'
  yield api.test(
      "emulator-test", api.repo_util.flutter_environment_data(flutter_path),
      api.properties(
          channel='master',
          version_file='flutter_master.version',
          git_branch='master',
          dependencies=[{
              "dependency": "android_virtual_device",
              "version": "android_31_google_apis_x64.textpb"
          }, {
              "dependency": "avd_cipd_version",
              "version": "AVDCIPDVERSION"
          }],
      ), api.step_data('read yaml.parse', api.json.output(tasks_dict)),
      api.properties(fake_data='fake data'),
      api.step_data(
          'Run package tests.start avd.Start Android emulator (android_31_google_apis_x64.textpb)',
          stdout=api.raw_io.output_text(
              'android_31_google_apis_x86|emulator-5554 started (pid: 17687)'
          )
      ), api.runtime(is_experimental=True)
  )
  multiple_tasks_dict = {
      'tasks': [{'name': 'one', 'script': 'myscript', 'args': ['arg1', 'arg2']},
                {
                    'name': 'two', 'script': 'myscript',
                    'args': ['arg1', 'arg2'], 'always': True
                }]
  }
  yield api.test(
      'multiple_tests_with_always',
      api.repo_util.flutter_environment_data(flutter_path),
      api.properties(
          channel='master',
          version_file='flutter_master.version',
      ),
      api.step_data('read yaml.parse', api.json.output(multiple_tasks_dict)),
      api.step_data('Run package tests.one', retcode=1),
      status='FAILURE'
  )
