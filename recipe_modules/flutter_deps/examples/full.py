# Copyright 2020 The Chromium Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

import contextlib
from recipe_engine.post_process import DoesNotRun, Filter, StatusFailure
from recipe_engine.recipe_api import Property

DEPS = [
    'flutter/flutter_deps',
    'flutter/repo_util',
    'recipe_engine/assertions',
    'recipe_engine/buildbucket',
    'recipe_engine/context',
    'recipe_engine/file',
    'recipe_engine/json',
    'recipe_engine/path',
    'recipe_engine/platform',
    'recipe_engine/properties',
    'recipe_engine/swarming',
]


def RunSteps(api):
  env = {}
  env_prefixes = {}
  api.flutter_deps.open_jdk(env, env_prefixes, 'v1')
  api.assertions.assertTrue(env.get('JAVA_HOME'))
  api.flutter_deps.arm_tools(env, env_prefixes, 'v1')
  api.assertions.assertTrue(env.get('ARM_TOOLS'))

  api.flutter_deps.goldctl(env, env_prefixes, 'v2')
  # Skip the following lines when goldctl is purposedly skipped.
  if not api.properties.get('gold_noop'):
    api.assertions.assertTrue(env.get('GOLDCTL'))

  api.flutter_deps.android_virtual_device(
      env, env_prefixes, "android_31_google_apis_x64.textpb"
  )
  api.assertions.assertTrue(env.get('EMULATOR_VERSION'))
  api.assertions.assertTrue(env.get('USE_EMULATOR'))
  api.flutter_deps.avd_cipd_version(env, env_prefixes, "AVDCIPDVERSION")
  api.assertions.assertTrue(env.get('AVD_CIPD_VERSION'))
  env_prefixes = {}
  env = {}
  api.flutter_deps.chrome_and_driver(env, env_prefixes, 'v3')
  api.assertions.assertTrue(env.get('CHROME_NO_SANDBOX'))
  api.assertions.assertTrue(env.get('CHROME_EXECUTABLE'))
  api.flutter_deps.firefox(env, env_prefixes, 'v3')
  api.assertions.assertTrue(env.get('FIREFOX_EXECUTABLE'))
  api.assertions.assertEqual(
      env_prefixes.get('PATH'), [
          api.path.cache_dir / 'chrome/chrome',
          api.path.cache_dir / 'chrome/drivers', api.path.cache_dir / 'firefox'
      ]
  )
  api.flutter_deps.go_sdk(env, env_prefixes, 'v4')
  api.flutter_deps.dashing(env, env_prefixes, 'v5')
  deps = api.properties.get("dependencies", [])
  api.flutter_deps.required_deps(env, env_prefixes, deps)
  with api.assertions.assertRaises(ValueError):
    api.flutter_deps.required_deps(
        env, env_prefixes, [{'dependency': 'does_not_exist'}]
    )
  with api.assertions.assertRaises(ValueError):
    api.flutter_deps.required_deps(
        env, env_prefixes, [{'dependency': 'xcode'}, {'dependency': 'xcode'}]
    )
  api.flutter_deps.android_sdk(env, env_prefixes, '')
  api.flutter_deps.android_sdk(env, env_prefixes, 'version:29.0')
  api.flutter_deps.gradle_cache(env, env_prefixes, '')
  api.flutter_deps.flutter_engine(env, env_prefixes)
  api.flutter_deps.firebase(env, env_prefixes)
  api.flutter_deps.cmake(
      env, env_prefixes, version='build_id:8787856497187628321'
  )
  api.flutter_deps.codesign(env, env_prefixes, 'latest')
  api.flutter_deps.cosign(env, env_prefixes)
  api.flutter_deps.ninja(env, env_prefixes)
  api.flutter_deps.clang(env, env_prefixes)
  api.flutter_deps.apple_signing(env, env_prefixes)
  api.flutter_deps.curl(env, env_prefixes, '')
  api.flutter_deps.doxygen(env, env_prefixes, '')
  api.flutter_deps.dart_sdk(env, env_prefixes, '')
  api.flutter_deps.certs(env, env_prefixes, '')
  api.flutter_deps.vs_build(env, env_prefixes, 'version:vs2019')
  api.flutter_deps.ruby(env, env_prefixes, '')
  api.flutter_deps.ktlint(env, env_prefixes)
  api.flutter_deps.android_virtual_device(env, env_prefixes, '34')
  api.flutter_deps.swift_format(env, env_prefixes, '')

  with contextlib.ExitStack() as exit_stack:
    api.flutter_deps.enter_contexts(exit_stack, ['osx_sdk'], env, env_prefixes)
    api.flutter_deps.enter_contexts(
        exit_stack, ['osx_sdk_devicelab', 'depot_tools_on_path'], env,
        env_prefixes
    )
  if api.platform.is_linux:
    api.flutter_deps.gh_cli(env, env_prefixes, 'latest')

  # Gems dependency requires to run from a flutter_environment.
  checkout_path = api.path.start_dir / 'flutter sdk'
  env, env_prefixes = api.repo_util.flutter_environment(checkout_path)


def GenTests(api):
  checkout_path = api.path.start_dir / 'flutter sdk'
  yield api.test(
      'basic',
      api.repo_util.flutter_environment_data(checkout_path),
  )
  yield api.test(
      'linux',
      api.platform('linux', 64),
      api.repo_util.flutter_environment_data(checkout_path),
  )
  yield api.test(
      'mac',
      api.platform('mac', 64),
      api.properties(
          dependencies=[{
              "dependency": "xcode"
          }, {
              'dependency': 'chrome_and_driver'
          }]
      ),
      api.swarming.properties(bot_id='flutter-devicelab-mac-1'),
      api.path.exists(
          (
              api.path.cache_dir /
              'osx_sdk/XCode.app/Contents/Developer/Toolchains/XcodeDefault.xctoolchain/usr/lib/swift'
          ),
          (
              api.path.cache_dir /
              'osx_sdk/XCode.app/Contents/Developer/Toolchains/XcodeDefault.xctoolchain/usr/lib/swift-5.0'
          ),
      ),
      api.repo_util.flutter_environment_data(checkout_path),
  )

  # Tests the old vanilla chromium version dependency
  yield api.test(
      'mac_old',
      api.platform('mac', 64),
      api.properties(
          dependencies=[{
              "dependency": "xcode"
          }, {
              'dependency': 'chrome_and_driver',
              'version': 'version:117.0'
          }]
      ),
      api.swarming.properties(bot_id='flutter-devicelab-mac-1'),
      api.path.exists(
          (
              api.path.cache_dir /
              'osx_sdk/XCode.app/Contents/Developer/Toolchains/XcodeDefault.xctoolchain/usr/lib/swift'
          ),
          (
              api.path.cache_dir /
              'osx_sdk/XCode.app/Contents/Developer/Toolchains/XcodeDefault.xctoolchain/usr/lib/swift-5.0'
          ),
      ),
      api.repo_util.flutter_environment_data(checkout_path),
  )
  yield api.test(
      'local_engine_cas',
      api.properties(
          local_engine_cas_hash='abceqwe/7',
          local_engine='android-release',
          local_engine_host='host-release',
      ),
      api.repo_util.flutter_environment_data(checkout_path),
  )
  yield api.test(
      'local_web_sdk_cas',
      api.properties(
          local_web_sdk_cas_hash='abceqwe/7', local_web_sdk='wasm-release'
      ),
      api.repo_util.flutter_environment_data(checkout_path),
  )
  yield api.test(
      'goldTryjob',
      api.properties(gold_tryjob=True, git_ref='refs/pull/1/head'),
      api.repo_util.flutter_environment_data(checkout_path),
  )
  yield api.test(
      'noop_golds_official_builds',
      api.buildbucket.ci_build(
          project='dart-internal',
          bucket='flutter',
          git_repo='https://dart.googlesource.com/monorepo',
          git_ref='refs/heads/main'
      ),
      api.repo_util.flutter_environment_data(checkout_path),
      api.properties(gold_noop=True),
  )
  yield api.test(
      'windows_vs_not_installed',
      api.properties(gold_tryjob=True, git_ref='refs/pull/1/head'),
      api.repo_util.flutter_environment_data(checkout_path),
      api.platform.name('win'),
      api.step_data(
          'VSBuild.List logs', api.file.listdir(['log1.txt', 'log2.txt'])
      ),
      api.step_data('VSBuild.Detect installation', stdout=api.json.output([])),
  )
  yield api.test(
      'windows_vs_installed',
      api.properties(gold_tryjob=True, git_ref='refs/pull/1/head'),
      api.repo_util.flutter_environment_data(checkout_path),
      api.platform.name('win'),
      api.step_data(
          'VSBuild.Detect installation',
          stdout=api.json.output([{'catalog': {'productLineVersion': '2019'}}])
      ),
  )
