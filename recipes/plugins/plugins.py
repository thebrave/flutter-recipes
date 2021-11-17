# Copyright 2020 The Chromium Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

PYTHON_VERSION_COMPATIBILITY = 'PY3'

DEPS = [
    'flutter/flutter_deps',
    'flutter/repo_util',
    'flutter/yaml',
    'recipe_engine/context',
    'recipe_engine/json',
    'recipe_engine/path',
    'recipe_engine/properties',
    'recipe_engine/step',
]


def RunSteps(api):
  """Recipe to run flutter plugin tests."""
  plugins_checkout_path = api.path['start_dir'].join('plugins')
  flutter_checkout_path = api.path['start_dir'].join('flutter')
  channel = api.properties.get('channel', 'master')
  with api.step.nest('checkout source code'):
    # Check out flutter ToT from master.
    api.repo_util.checkout(
        'flutter',
        checkout_path=flutter_checkout_path,
        ref='refs/heads/%s' % channel,
    )
    api.repo_util.checkout(
        'plugins',
        checkout_path=plugins_checkout_path,
        url=api.properties.get('git_url'),
        ref=api.properties.get('git_ref')
    )
  env, env_prefixes = api.repo_util.flutter_environment(flutter_checkout_path)
  with api.step.nest('Dependencies'):
    deps = api.properties.get('dependencies', [])
    api.flutter_deps.required_deps(env, env_prefixes, deps)

  with api.context(env=env, env_prefixes=env_prefixes,
                   cwd=flutter_checkout_path):
    with api.step.nest('prepare environment'):
      config_flag = '--enable-windows-uwp-desktop' if api.properties.get(
          'uwp'
      ) else ''
      api.step(
          'flutter config --enable-windows-desktop',
          ['flutter', 'config', '--enable-windows-desktop'],
          infra_step=True,
      )
      api.step(
          'flutter config --enable-windows-uwp-desktop',
          ['flutter', 'config', '--enable-windows-uwp-desktop'],
          infra_step=True,
      )
      api.step('flutter doctor', ['flutter', 'doctor', '-v'])
      # Fail fast on dependencies problem.
      timeout_secs = 300
      api.step(
          'download dependencies', ['flutter', 'update-packages'],
          infra_step=True,
          timeout=timeout_secs
      )
  tests_yaml_path = plugins_checkout_path.join(
      '.ci', 'targets', api.properties.get('target_file', 'tests.yaml')
  )
  result = api.yaml.read('read yaml', tests_yaml_path, api.json.output())
  with api.context(env=env, env_prefixes=env_prefixes,
                   cwd=plugins_checkout_path):
    with api.step.nest('Run plugin tests'):
      for task in result.json.output['tasks']:
        script_path = plugins_checkout_path.join(task['script'])
        api.step(task['name'], cmd=['bash', script_path])


def GenTests(api):
  tasks_dict = {'tasks': [{'name': 'one', 'script': 'myscript'}]}
  yield api.test(
      'basic', api.repo_util.flutter_environment_data(),
      api.step_data('read yaml.parse', api.json.output(tasks_dict))
  )
