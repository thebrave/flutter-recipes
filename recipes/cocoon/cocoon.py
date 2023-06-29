# Copyright 2019 The Chromium Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Recipe for cocoon repository tests."""

DEPS = [
    'flutter/os_utils',
    'flutter/repo_util',
    'flutter/yaml',
    'recipe_engine/context',
    'recipe_engine/json',
    'recipe_engine/path',
    'recipe_engine/properties',
    'recipe_engine/runtime',
    'recipe_engine/step',
]


def RunSteps(api):
  """Steps to checkout cocoon, dependencies and execute tests."""
  # Collect memory/cpu/process before task execution.
  api.os_utils.collect_os_info()
  start_path = api.path['start_dir']
  cocoon_path = start_path.join('cocoon')
  flutter_path = start_path.join('flutter')

  api.repo_util.checkout(
      'cocoon',
      cocoon_path,
      url=api.properties.get('git_url'),
      ref=api.properties.get('git_ref') or 'refs/heads/main'
  )

  # Checkout flutter/flutter at head.
  flutter_git_ref = 'refs/heads/stable'
  api.repo_util.checkout(
      'flutter',
      flutter_path,
      ref=flutter_git_ref,
      url='https://github.com/flutter/flutter',
      override_sha=True
  )

  # Read yaml file
  tests_yaml_path = start_path.join('cocoon', 'tests.yaml')
  result = api.yaml.read('read yaml', tests_yaml_path, api.json.output())
  env, env_prefixes = api.repo_util.flutter_environment(flutter_path)
  # The context adds dart-sdk tools to PATH and sets PUB_CACHE.
  with api.context(env=env, env_prefixes=env_prefixes, cwd=start_path):
    api.step('flutter doctor', cmd=['flutter', 'doctor'])
    prepare_script_path = cocoon_path.join(
        'test_utilities', 'bin', 'prepare_environment.sh'
    )
    api.step(
        'prepare environment',
        cmd=['bash', prepare_script_path],
        infra_step=True,
    )
    for task in result.json.output['tasks']:
      script_path = cocoon_path.join(task['script'])
      test_folder = cocoon_path.join(task['task'])
      api.step(task['task'], cmd=['bash', script_path, test_folder])
  # This is to clean up leaked processes.
  api.os_utils.kill_processes()
  # Collect memory/cpu/process after task execution.
  api.os_utils.collect_os_info()

def GenTests(api):
  tasks_dict = {'tasks': [{'task': 'one', 'script': 'myscript'}]}
  yield api.test(
      'pull_request', api.runtime(is_experimental=True),
      api.properties(
          git_url='https://github.com/flutter/cocoon',
          git_ref='refs/pull/1/head'
      ),
      api.repo_util.flutter_environment_data(
          api.path['start_dir'].join('flutter')
      ), api.step_data('read yaml.parse', api.json.output(tasks_dict))
  )
