# Copyright 2016 The Chromium Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

from contextlib import contextmanager

from PB.recipes.flutter.engine_unopt import InputProperties
from PB.recipes.flutter.engine_unopt import EnvProperties

DEPS = [
    'depot_tools/depot_tools',
    'depot_tools/gclient',
    'flutter/build_util',
    'flutter/flutter_deps',
    'flutter/os_utils',
    'flutter/osx_sdk',
    'flutter/repo_util',
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

GIT_REPO = (
   'https://chromium.googlesource.com/external/github.com/flutter/engine'
)

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


def RunTests(api, out_dir, android_out_dir=None, ios_out_dir=None, types='all'):
  script_path = GetCheckoutPath(api).join('flutter', 'testing', 'run_tests.py')
  # TODO(godofredoc): use .vpython from engine when file are available.
  venv_path = api.depot_tools.root.join('.vpython')
  args = ['--variant', out_dir, '--type', types]
  if android_out_dir:
    args.extend(['--android-variant', android_out_dir])
  if ios_out_dir:
    args.extend(['--ios-variant', ios_out_dir])
  api.python('Host Tests for %s' % out_dir, script_path, args, venv=venv_path)


def AnalyzeDartUI(api):
  RunGN(api, '--unoptimized', '--prebuilt-dart-sdk')
  Build(api, 'host_debug_unopt', 'sky_engine')

  checkout = GetCheckoutPath(api)
  with api.context(cwd=checkout):
    api.step('analyze dart_ui', ['/bin/bash', 'flutter/ci/analyze.sh'])


def FormatAndDartTest(api):
  checkout = GetCheckoutPath(api)
  with api.context(cwd=checkout.join('flutter')):
    format_cmd = checkout.join('flutter', 'ci', 'format.sh')
    api.step('format and dart test', [format_cmd])


def Lint(api):
  checkout = GetCheckoutPath(api)
  with api.context(cwd=checkout):
    lint_cmd = checkout.join('flutter', 'ci', 'lint.sh')
    api.step('lint test', [lint_cmd])


def LintAndroidHost(api):
  android_lint_path = GetCheckoutPath(api
                                     ).join('flutter', 'tools', 'android_lint')
  with api.step.nest('android lint'):
    with api.context(cwd=android_lint_path):
      api.step('dart bin/main.dart', ['dart', 'bin/main.dart'])


def CheckLicenses(api):
  checkout = GetCheckoutPath(api)
  with api.context(cwd=checkout):
    licenses_cmd = checkout.join('flutter', 'ci', 'licenses.sh')
    api.step('licenses check', [licenses_cmd])


def BuildLinuxAndroid(api, swarming_task_id):
  # Build Android Unopt and run tests
  RunGN(api, '--android', '--unoptimized')
  Build(api, 'android_debug_unopt', 'flutter/shell/platform/android:robolectric_tests')
  RunTests(
      api,
      'android_debug_unopt',
      android_out_dir='android_debug_unopt',
      types='java'
  )


def BuildLinux(api):
  RunGN(api, '--runtime-mode', 'debug', '--unoptimized', '--prebuilt-dart-sdk')
  Build(api, 'host_debug_unopt')
  RunTests(api, 'host_debug_unopt', types='dart,engine')


def TestObservatory(api):
  checkout = GetCheckoutPath(api)
  flutter_tester_path = checkout.join('out/host_debug_unopt/flutter_tester')
  empty_main_path = \
      checkout.join('flutter/shell/testing/observatory/empty_main.dart')
  test_path = checkout.join('flutter/shell/testing/observatory/test.dart')
  test_cmd = ['dart', test_path, flutter_tester_path, empty_main_path]
  with api.context(cwd=checkout):
    api.step('test observatory and service protocol', test_cmd)


@contextmanager
def SetupXcode(api):
  # See cr-buildbucket.cfg for how the version is passed in.
  # https://github.com/flutter/infra/blob/35f51ea4bfc91966b41d988f6028e34449aa4279/config/generated/flutter/luci/cr-buildbucket.cfg#L7176-L7203
  with api.osx_sdk('ios'):
    yield


def BuildMac(api):
  RunGN(api, '--runtime-mode', 'debug', '--unoptimized', '--no-lto', '--prebuilt-dart-sdk')
  Build(api, 'host_debug_unopt')
  RunTests(api, 'host_debug_unopt', types='dart,engine')


def RunIosIntegrationTests(api):
  test_dir = GetCheckoutPath(api).join('flutter', 'testing')
  scenario_app_tests = test_dir.join('scenario_app')

  with api.context(cwd=scenario_app_tests):
    api.step(
        'Scenario App Integration Tests',
        ['./build_and_run_ios_tests.sh', 'ios_debug_sim']
    )


def BuildIOS(api):
  # Simulator doesn't use bitcode.
  # Simulator binary is needed in all runtime modes.
  RunGN(api, '--ios', '--runtime-mode', 'debug', '--simulator', '--no-lto')
  Build(api, 'ios_debug_sim')

  # We need to build host_debug_unopt for testing
  RunGN(api, '--unoptimized', '--prebuilt-dart-sdk')
  Build(api, 'host_debug_unopt')
  Build(api, 'ios_debug_sim', 'ios_test_flutter')

  RunTests(api, 'ios_debug_sim', ios_out_dir='ios_debug_sim', types='objc')
  RunIosIntegrationTests(api)


def BuildWindows(api):
  RunGN(api, '--runtime-mode', 'debug', '--unoptimized', '--prebuilt-dart-sdk')
  Build(api, 'host_debug_unopt')
  RunTests(api, 'host_debug_unopt', types='engine')


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


def RunSteps(api, properties, env_properties):
  # Collect memory/cpu/process before task execution.
  api.os_utils.collect_os_info()

  cache_root = api.path['cache'].join('builder')
  checkout = GetCheckoutPath(api)

  api.file.rmtree('Clobber build output', checkout.join('out'))

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

    # Checks before building the engine. Only run on Linux.
    if api.platform.is_linux:
      FormatAndDartTest(api)
      Lint(api)
      AnalyzeDartUI(api)
      CheckLicenses(api)
      BuildLinux(api)
      TestObservatory(api)
      LintAndroidHost(api)
      BuildLinuxAndroid(api, env_properties.SWARMING_TASK_ID)

    if api.platform.is_mac:
      with SetupXcode(api):
        BuildMac(api)
        with InstallGems(api):
          BuildIOS(api)

    if api.platform.is_win:
      BuildWindows(api)

  # This is to clean up leaked processes.
  api.os_utils.kill_processes()
  # Collect memory/cpu/process after task execution.
  api.os_utils.collect_os_info()


# pylint: disable=line-too-long
# See https://chromium.googlesource.com/infra/luci/recipes-py/+/refs/heads/master/doc/user_guide.md
# The tests in here make sure that every line of code is used and does not fail.
# pylint: enable=line-too-long
def GenTests(api):
  for platform in ('mac', 'linux', 'win'):
    for no_lto in (True, False):
      test = api.test(
          '%s%s' % (platform, '' if no_lto else '_lto'),
          api.platform(platform, 64),
          api.buildbucket.ci_build(
              builder='%s Engine' % platform.capitalize(),
              git_repo=GIT_REPO,
              project='flutter',
          ),
          api.runtime(is_experimental=False),
          api.properties(
              InputProperties(
                  goma_jobs='1024',
                  no_lto=no_lto,
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
