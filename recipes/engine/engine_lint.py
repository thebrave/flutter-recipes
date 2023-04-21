# Copyright 2016 The Chromium Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

from contextlib import contextmanager

from PB.recipes.flutter.engine.engine_lint import InputProperties
from PB.recipes.flutter.engine.engine_lint import EnvProperties

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
    'recipe_engine/buildbucket',
    'recipe_engine/context',
    'recipe_engine/file',
    'recipe_engine/path',
    'recipe_engine/platform',
    'recipe_engine/properties',
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


def Lint(api, config, shardId=None, shardVariants=""):
  checkout = GetCheckoutPath(api)
  with api.context(cwd=checkout):
    lint_cmd = checkout.join('flutter', 'ci', 'lint.sh')
    cmd = [lint_cmd, '--variant', config]
    if api.properties.get('lint_all', True):
      cmd += ['--lint-all']
    if api.properties.get('lint_head', False):
      cmd += ['--lint-head']
    if shardId != None:
      cmd += ['--shard-id=%d' % shardId, '--shard-variants=%s' % shardVariants]
    api.step(api.test_utils.test_step_name('lint %s' % config), cmd)


def DoLints(api):
  if api.platform.is_linux:
    RunGN(api, '--android', '--android-cpu', 'arm64', '--no-lto')
    RunGN(api, '--runtime-mode', 'debug', '--prebuilt-dart-sdk', '--no-lto')
    if api.properties.get('lint_android', True):
      Build(api, 'android_debug_arm64')
      Lint(api, 'android_debug_arm64', shardId=0, shardVariants="host_debug")

    if api.properties.get('lint_host', True):
      # We have to build before linting because source files #include header
      # files that are generated during the build.
      Build(api, 'host_debug')
      Lint(api, 'host_debug', shardId=1, shardVariants="android_debug_arm64")

  elif api.platform.is_mac:
    with api.osx_sdk('ios'):
      cpu = api.properties.get('cpu', 'x86')
      ios_command = ['--ios', '--runtime-mode', 'debug', '--simulator', '--no-lto']
      host_command = ['--runtime-mode', 'debug', '--prebuilt-dart-sdk', '--no-lto']
      if (cpu == 'arm64'):
        ios_command += ['--force-mac-arm64']
        host_command += ['--force-mac-arm64']
      RunGN(api, *ios_command)
      RunGN(api, *host_command)
      if api.properties.get('lint_ios', True):
        Build(api, 'ios_debug_sim')
        Lint(api, 'ios_debug_sim', shardId=0, shardVariants="host_debug")

      if api.properties.get('lint_host', True):
        # We have to build before linting because source files #include header
        # files that are generated during the build.
        Build(api, 'host_debug')
        Lint(api, 'host_debug', shardId=1, shardVariants="ios_debug_sim")


def RunSteps(api, properties, env_properties):
  # Collect memory/cpu/process before task execution.
  api.os_utils.collect_os_info()

  cache_root = api.path['cache'].join('builder')
  checkout = GetCheckoutPath(api)

  api.file.ensure_directory('Ensure checkout cache', cache_root)
  dart_bin = checkout.join(
      'third_party', 'dart', 'tools', 'sdks', 'dart-sdk', 'bin'
  )

  android_home = checkout.join('third_party', 'android_tools', 'sdk')

  env = {
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
    for lint_set in ('all', 'head', 'branch'):
      for lint_target in ('host', 'ios', 'android'):
        if lint_target == 'ios' and platform == 'linux':
          continue
        if lint_target == 'android' and platform == 'mac':
          continue
        test = api.test(
            '%s %s %s' % (
                platform, lint_target, lint_set,
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
                    lint_all=lint_set == 'all',
                    lint_head=lint_set == 'head',
                    lint_host=lint_target == 'host',
                    lint_android=lint_target == 'android',
                    lint_ios=lint_target == 'ios',
                ),
            ),
            api.properties.environ(
                EnvProperties(SWARMING_TASK_ID='deadbeef')
            ),
        )
        yield test

  for lint_target in ('host', 'ios'):
    for cpu in ('arm64', 'x86'):
      yield api.test(
          '%s arch %s' % (
              lint_target, cpu,
          ),
          api.platform('mac', 64),
          api.runtime(is_experimental=False),
          api.properties(
                cpu='%s' % cpu,
                goma_jobs='1024',
                lint_all=False,
                lint_head=False,
                lint_host=lint_target == 'host',
                lint_android=False,
                lint_ios=lint_target == 'ios',
          ),
      )

