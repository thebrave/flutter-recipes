# Copyright 2016 The Chromium Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

from contextlib import contextmanager

from PB.recipes.flutter.engine.engine_lint import InputProperties
from PB.recipes.flutter.engine.engine_lint import EnvProperties

PYTHON_VERSION_COMPATIBILITY = 'PY3'

DEPS = [
    'depot_tools/depot_tools',
    'depot_tools/gclient',
    'flutter/build_util',
    'flutter/flutter_deps',
    'flutter/logs_util',
    'flutter/os_utils',
    'flutter/osx_sdk',
    'flutter/repo_util',
    'flutter/retry',
    'flutter/test_utils',
    'fuchsia/goma',
    'recipe_engine/buildbucket',
    'recipe_engine/context',
    'recipe_engine/file',
    'recipe_engine/path',
    'recipe_engine/platform',
    'recipe_engine/properties',
    'recipe_engine/python',
    'recipe_engine/runtime',
    'recipe_engine/step',
]

GIT_REPO = 'https://flutter.googlesource.com/mirrors/engine'

PROPERTIES = InputProperties
ENV_PROPERTIES = EnvProperties


def GetCheckoutPath(api):
  return api.path['cache'].join('builder', 'src')


def RunGN(api, *args):
  checkout = GetCheckoutPath(api)
  api.build_util.run_gn(args, checkout)


def Build(api, config, *targets):
  checkout = GetCheckoutPath(api)
  api.build_util.build(config, checkout, targets)


@contextmanager
def InstallGems(api):
  gem_dir = api.path['start_dir'].join('gems')
  api.file.ensure_directory('mkdir gems', gem_dir)

  with api.context(cwd=gem_dir):
    api.step(
        'install jazzy', [
            'gem', 'install', 'jazzy:' + api.properties['jazzy_version'],
            '--install-dir', '.'
        ]
    )
  with api.context(env={"GEM_HOME": gem_dir},
                   env_prefixes={'PATH': [gem_dir.join('bin')]}):
    yield


def Lint(api, config):
  checkout = GetCheckoutPath(api)
  with api.context(cwd=checkout):
    lint_cmd = checkout.join('flutter', 'ci', 'lint.sh')
    api.step(
        api.test_utils.test_step_name('lint %s' % config),
        [lint_cmd, '--lint-all', '--variant', config],
    )


def DoLints(api):
  if api.platform.is_linux:
    RunGN(api, '--runtime-mode', 'debug', '--prebuilt-dart-sdk', '--no-lto')
    Lint(api, 'host_debug')

    debug_variants = [
        ('arm', 'android_debug', 'android-arm', True, 'armeabi_v7a'),
        ('arm64', 'android_debug_arm64', 'android-arm64', False, 'arm64_v8a'),
        ('x86', 'android_debug_x86', 'android-x86', False, 'x86'),
        ('x64', 'android_debug_x64', 'android-x64', False, 'x86_64'),
    ]
    for android_cpu, out_dir, artifact_dir, run_tests, abi in debug_variants:
      RunGN(api, '--android', '--android-cpu=%s' % android_cpu, '--no-lto')
      Lint(api, out_dir)

  if api.platform.is_mac:
    with api.osx_sdk('ios'):
      RunGN(api, '--runtime-mode', 'debug', '--prebuilt-dart-sdk', '--no-lto')
      # We have to build for mac before linting because source files #incude
      # header files that are generated during the build.
      Build(api, 'host_debug')
      Lint(api, 'host_debug')
      with InstallGems(api):
        RunGN(
            api, '--ios', '--runtime-mode', 'debug', '--simulator', '--no-lto',
        )
        Lint(api, 'ios_debug_sim')


def RunSteps(api, properties, env_properties):
  # Collect memory/cpu/process before task execution.
  api.os_utils.collect_os_info()

  cache_root = api.path['cache'].join('builder')
  checkout = GetCheckoutPath(api)

  api.file.ensure_directory('Ensure checkout cache', cache_root)
  api.goma.ensure()
  dart_bin = checkout.join(
      'third_party', 'dart', 'tools', 'sdks', 'dart-sdk', 'bin'
  )

  android_home = checkout.join('third_party', 'android_tools', 'sdk')

  env = {
    'GOMA_DIR': api.goma.goma_dir,
    'ANDROID_HOME': str(android_home),
    'FLUTTER_PREBUILT_DART_SDK': 'True',
  }
  env_prefixes = {'PATH': [dart_bin]}

  api.logs_util.initialize_logs_collection(env)

  # Add certificates and print the ones required for pub.
  api.flutter_deps.certs(env, env_prefixes)
  api.os_utils.print_pub_certs()

  # Enable long path support on Windows.
  api.os_utils.enable_long_paths()

  api.repo_util.engine_checkout(cache_root, env, env_prefixes)

  # Delete derived data on mac. This is a noop for other platforms.
  api.os_utils.clean_derived_data()

  # Various scripts we run assume access to depot_tools on path for `ninja`.
  with api.context(cwd=cache_root, env=env,
                   env_prefixes=env_prefixes), api.depot_tools.on_path():

    api.gclient.runhooks()

    try:
      DoLints(api)
    finally:
      api.logs_util.upload_logs('engine')
      # This is to clean up leaked processes.
      api.os_utils.kill_processes()

  # Collect memory/cpu/process after task execution.
  api.os_utils.collect_os_info()


# pylint: disable=line-too-long
# See https://chromium.googlesource.com/infra/luci/recipes-py/+/refs/heads/master/doc/user_guide.md
# The tests in here make sure that every line of code is used and does not fail.
# pylint: enable=line-too-long
def GenTests(api):
  for platform in ('mac', 'linux'):
    test = api.test(
        '%s' % (
            platform,
        ),
        api.platform(platform, 64),
        api.buildbucket.ci_build(
            builder='%s Engine Lint' % platform.capitalize(),
            git_repo=GIT_REPO,
            project='flutter',
        ),
        api.runtime(is_experimental=False),
        api.properties(
            InputProperties(
                goma_jobs='1024',
            ),
        ),
        api.properties.environ(
            EnvProperties(SWARMING_TASK_ID='deadbeef')
        ),
    )
    if platform == 'mac':
      test += (
          api.properties(
              InputProperties(
                  jazzy_version='0.8.4',
              )
          )
      )
    yield test
