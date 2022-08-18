# Copyright 2020 The Chromium Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

DEPS = [
    'flutter/flutter_deps',
    'flutter/repo_util',
    'flutter/yaml',
    'recipe_engine/context',
    'recipe_engine/file',
    'recipe_engine/json',
    'recipe_engine/path',
    'recipe_engine/properties',
    'recipe_engine/step',
]


def RunSteps(api):
  """Recipe to run flutter package tests."""
  packages_checkout_path = api.path['start_dir'].join('packages')
  flutter_checkout_path = api.path['start_dir'].join('flutter')
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
      version_file = packages_checkout_path.join('.ci', version_file_name)
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
  with api.step.nest('Dependencies'):
    deps = api.properties.get('dependencies', [])
    api.flutter_deps.required_deps(env, env_prefixes, deps)

  with api.context(env=env, env_prefixes=env_prefixes,
                   cwd=flutter_checkout_path):
    with api.step.nest('prepare environment'):
      api.step(
          'flutter config --enable-windows-desktop',
          ['flutter', 'config', '--enable-windows-desktop'],
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
  tests_yaml_path = packages_checkout_path.join(
      '.ci', 'targets', api.properties.get('target_file', 'tests.yaml')
  )
  result = api.yaml.read('read yaml', tests_yaml_path, api.json.output())
  with api.context(env=env, env_prefixes=env_prefixes,
                   cwd=packages_checkout_path):
    with api.step.nest('Run package tests'):
      for task in result.json.output['tasks']:
        script_path = packages_checkout_path.join(task['script'])
        api.step(task['name'], cmd=['bash', script_path])


def GenTests(api):
  flutter_path = api.path['start_dir'].join('flutter')
  tasks_dict = {'tasks': [{'name': 'one', 'script': 'myscript'}]}
  yield api.test(
      'master_channel', api.repo_util.flutter_environment_data(flutter_path),
      api.properties(
          channel='master',
          version_file='flutter_master.version',
      ),
      api.step_data('read yaml.parse', api.json.output(tasks_dict))
  )
  yield api.test(
      'stable_channel', api.repo_util.flutter_environment_data(flutter_path),
      api.properties(
          channel='stable',
      ),
      api.step_data('read yaml.parse', api.json.output(tasks_dict))
  )
