# Copyright 2020 The Chromium Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

DEPS = [
    'flutter/repo_util',
    'flutter/flutter_deps',
    'recipe_engine/context',
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
  # This is required by `flutter upgrade`
  env['FLUTTER_GIT_URL'
     ] = 'https://chromium.googlesource.com/external/github.com/flutter/flutter'
  with api.step.nest('Dependencies'):
    deps = api.properties.get('dependencies', [])
    api.flutter_deps.required_deps(env, env_prefixes, deps)

  with api.context(env=env, env_prefixes=env_prefixes,
                   cwd=flutter_checkout_path):
    with api.step.nest('prepare environment'):
      config_flag = '--enable-windows-uwp-desktop' if api.properties.get(
          'uwp'
      ) else '--enable-windows-desktop'
      api.step(
          'flutter config %s' % config_flag,
          ['flutter', 'config', config_flag],
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
      api.step(
          'pub global activate flutter_plugin_tools',
          ['pub', 'global', 'activate', 'flutter_plugin_tools'],
          infra_step=True,
      )
  with api.context(env=env, env_prefixes=env_prefixes,
                   cwd=plugins_checkout_path):
    with api.step.nest('Run plugin tests'):
      build_drive_flag = '--winuwp' if api.properties.get(
          'uwp'
      ) else '--windows'
      api.step(
          'build examples',
          ['bash', 'script/tool_runner.sh', 'build-examples', build_drive_flag]
      )
      api.step(
          'drive examples',
          ['bash', 'script/tool_runner.sh', 'drive-examples', build_drive_flag]
      )


def GenTests(api):
  yield api.test('basic', api.repo_util.flutter_environment_data())
