# Copyright 2020 The Chromium Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

from recipe_engine.post_process import DoesNotRun, Filter, StatusFailure

DEPS = [
    'flutter/flutter_deps',
    'flutter/repo_util',
    'recipe_engine/assertions',
    'recipe_engine/context',
    'recipe_engine/path',
    'recipe_engine/platform',
    'recipe_engine/properties',
]


def RunSteps(api):
  env = {}
  env_prefixes = {}
  api.flutter_deps.open_jdk(env, env_prefixes, 'v1')
  api.assertions.assertTrue(env.get('JAVA_HOME'))
  api.flutter_deps.goldctl(env, env_prefixes, 'v2')
  api.assertions.assertTrue(env.get('GOLDCTL'))
  env_prefixes = {}
  env = {}
  api.flutter_deps.chrome_and_driver(env, env_prefixes, 'v3')
  api.assertions.assertTrue(env.get('CHROME_NO_SANDBOX'))
  api.assertions.assertTrue(env.get('CHROME_EXECUTABLE'))
  api.assertions.assertEqual(
      env_prefixes.get('PATH'), [
          api.path['cache'].join('chrome', 'chrome'),
          api.path['cache'].join('chrome', 'drivers')
      ]
  )
  api.flutter_deps.go_sdk(env, env_prefixes, 'v4')
  api.flutter_deps.dashing(env, env_prefixes, 'v5')
  api.flutter_deps.vpython(env, env_prefixes, 'v6')
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
  api.flutter_deps.cmake(env, env_prefixes)
  with api.assertions.assertRaises(ValueError):
    api.flutter_deps.codesign(env, env_prefixes)
  api.flutter_deps.codesign(env, env_prefixes, 'latest')
  api.flutter_deps.cosign(env, env_prefixes)
  api.flutter_deps.ninja(env, env_prefixes)
  api.flutter_deps.clang(env, env_prefixes)
  api.flutter_deps.apple_signing(env, env_prefixes)
  api.flutter_deps.curl(env, env_prefixes, '')
  api.flutter_deps.dart_sdk(env, env_prefixes, '')
  api.flutter_deps.certs(env, env_prefixes, '')
  api.flutter_deps.vs_build(env, env_prefixes, '')
  api.flutter_deps.jazzy(env, env_prefixes, '')
  if api.platform.is_linux:
    api.flutter_deps.android_virtual_device(env, env_prefixes, '31')
    api.flutter_deps.gh_cli(env, env_prefixes, 'latest')

  # Gems dependency requires to run from a flutter_environment.
  checkout_path = api.path['start_dir'].join('flutter\ sdk')
  env, env_prefixes = api.repo_util.flutter_environment(checkout_path)
  with api.context(env=env, env_prefixes=env_prefixes):
    gems_dir = api.path['start_dir'].join('dev', 'ci', 'mac')
    api.flutter_deps.gems(env, env_prefixes, gems_dir)


def GenTests(api):
  checkout_path = api.path['start_dir'].join('flutter\ sdk')
  avd_api_version = '31'
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
      'with-gems', api.properties(dependencies=[{"dependency": "gems"}]),
      api.repo_util.flutter_environment_data(checkout_path),
  )

  yield api.test(
      'with-arm64ruby', api.properties(dependencies=[{"dependency": "gems"}, {"dependency": "arm64ruby"}]),
      api.repo_util.flutter_environment_data(checkout_path),
  )

  yield api.test(
      'mac',
      api.platform('mac', 64),
      api.properties(
          dependencies=[{"dependency": "xcode"},
                        {'dependency': 'chrome_and_driver'}]
      ),
      api.path.exists(
          api.path['cache'].join(
              'osx_sdk/XCode.app/Contents/Developer/Toolchains/XcodeDefault.xctoolchain/usr/lib/swift'
          ),
          api.path['cache'].join(
              'osx_sdk/XCode.app/Contents/Developer/Toolchains/XcodeDefault.xctoolchain/usr/lib/swift-5.0'
          ),
      ),
  )
  yield api.test(
      'flutter_engine', api.properties(local_engine_cas_hash='abceqwe/7',),
      api.repo_util.flutter_environment_data(checkout_path),
  )
  yield api.test(
      'local_engine_cas', api.properties(local_engine_cas_hash='abceqwe/7',
                                         local_engine='host-release'),
      api.repo_util.flutter_environment_data(checkout_path),
  )
  yield api.test(
      'goldTryjob',
      api.properties(gold_tryjob=True, git_ref='refs/pull/1/head'),
      api.repo_util.flutter_environment_data(checkout_path),
  )
  yield api.test(
      'windows', api.properties(gold_tryjob=True, git_ref='refs/pull/1/head'),
      api.repo_util.flutter_environment_data(checkout_path),
      api.platform.name('win'),
  )
