# Copyright 2020 The Chromium Authors. All rights reserved.

# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Recipe for engine repository tests."""

import contextlib
import copy

from recipe_engine import recipe_api

from PB.recipes.flutter.engine.engine import InputProperties
from PB.recipes.flutter.engine.engine import EnvProperties

DEPS = [
    'depot_tools/depot_tools',
    'flutter/build_util',
    'flutter/display_util',
    'flutter/flutter_deps',
    'flutter/os_utils',
    'flutter/repo_util',
    'flutter/shard_util_v2',
    'flutter/test_utils',
    'fuchsia/cas_util',
    'recipe_engine/buildbucket',
    'recipe_engine/context',
    'recipe_engine/file',
    'recipe_engine/json',
    'recipe_engine/path',
    'recipe_engine/platform',
    'recipe_engine/properties',
    'recipe_engine/runtime',
    'recipe_engine/step',
]


PROPERTIES = InputProperties
ENV_PROPERTIES = EnvProperties

def GetCheckoutPath(api):
  return api.path['cache'].join('builder', 'src')


def CleanUpProcesses(api):
  # This is to clean up leaked processes.
  api.os_utils.kill_processes()
  # Collect memory/cpu/process after task execution.
  api.os_utils.collect_os_info()


def RunSteps(api, properties, env_properties):
  """Steps to checkout flutter engine and execute web tests."""
  # Collect memory/cpu/process before task execution.
  api.os_utils.collect_os_info()
  cache_root = api.path['cache'].join('builder')
  checkout = GetCheckoutPath(api)

  if properties.clobber:
    api.file.rmtree('Clobber cache', cache_root)
  api.file.rmtree('Clobber build output', checkout.join('out'))

  api.file.ensure_directory('Ensure checkout cache', cache_root)
  env, env_prefixes = api.repo_util.engine_environment(cache_root)
  env['ENGINE_PATH'] = cache_root
  api.flutter_deps.certs(env, env_prefixes)

  # Enable long path support on Windows.
  api.os_utils.enable_long_paths()

  # Checkout source code and build
  api.repo_util.engine_checkout(cache_root, env, env_prefixes)

  # Ensure required deps are installed
  api.flutter_deps.required_deps(
      env, env_prefixes, api.properties.get('dependencies', [])
  )

  with api.context(cwd=cache_root, env=env,
                    env_prefixes=env_prefixes), api.depot_tools.on_path():
    felt_name = 'felt.bat' if api.platform.is_win else 'felt'
    felt_cmd = [
        checkout.join('flutter', 'lib', 'web_ui', 'dev', felt_name)
    ]

    cas_hash = ''
    builds = []
    if api.platform.is_linux:
      api.build_util.run_gn(['--build-canvaskit', '--web', '--runtime-mode=release', '--no-goma'],
                            checkout)
      api.build_util.build('wasm_release', checkout, [])
      wasm_cas_hash = api.shard_util_v2.archive_full_build(
              checkout.join('out', 'wasm_release'),
              'wasm_release')
      targets = generate_targets(api, cas_hash, wasm_cas_hash)

    # Update dart packages and run tests.
    felt_licenses = copy.deepcopy(felt_cmd)
    felt_licenses.append('check-licenses')
    api.step('felt licenses', felt_licenses)
    if api.platform.is_linux:
      web_engine_analysis = copy.deepcopy(felt_cmd)
      web_engine_analysis.append('analyze')
      api.step('web engine analysis', web_engine_analysis)
      with api.step.nest('launch builds') as presentation:
        tasks = api.shard_util_v2.schedule(targets, presentation)
      with api.step.nest('collect builds') as presentation:
        build_results = api.shard_util_v2.collect(tasks, presentation)
      api.display_util.display_subbuilds(
          step_name='display builds',
          subbuilds=build_results,
          raise_on_failure=True,
      )
      CleanUpProcesses(api)
    elif api.platform.is_mac:
      with recipe_api.defer_results():
        felt_test = copy.deepcopy(felt_cmd)
        felt_test.append('test')
        felt_test.append('--require-skia-gold')
        felt_test.append('--browser=safari')
        api.step(
            api.test_utils.test_step_name('Run tests on macOS Safari'), felt_test
        )
        CleanUpProcesses(api)
    else:
      felt_test = copy.deepcopy(felt_cmd)
      felt_test.append('test')
      api.step(api.test_utils.test_step_name('felt test chrome'), felt_test)
      CleanUpProcesses(api)


def generate_targets(api, cas_hash, wasm_cas_hash):
  """Schedules one subbuild per subshard."""
  targets = []

  inherited_dependencies = [
      api.shard_util_v2.unfreeze_dict(d)
      for d in api.properties.get('dependencies', [])
  ]
  drone_props = {
      'local_engine_cas_hash': cas_hash,
      'inherited_dependencies': inherited_dependencies,
      'wasm_release_cas_hash': wasm_cas_hash,
  }

  # For running Chrome Unit tests:
  properties = copy.deepcopy(drone_props)
  properties['command_name'] = 'chrome-unit-linux'
  properties['name'] = properties['command_name']
  # These are the felt commands which will be used.
  properties['command_args'] = ['test', '--browser=chrome', '--require-skia-gold']
  properties['recipe'] = 'engine/web_engine_drone'
  targets.append(properties)

  # For running Chrome Unit tests with CanvasKit
  properties = copy.deepcopy(drone_props)
  properties['command_name'] = 'chrome-unit-linux-canvaskit'
  properties['name'] = properties['command_name']
  # These are the felt commands which will be used.
  properties['command_args'] = [
      'test', '--browser=chrome', '--require-skia-gold',
      '--use-local-canvaskit'
  ]
  properties['recipe'] = 'engine/web_engine_drone'
  targets.append(properties)

  # For running Chrome Unit tests compiled to wasm:
  properties = copy.deepcopy(drone_props)
  properties['command_name'] = 'chrome-unit-linux-wasm'
  properties['name'] = properties['command_name']
  # These are the felt commands which will be used.
  properties['command_args'] = [
      'test', '--browser=chrome', '--require-skia-gold',
      '--wasm'
  ]
  properties['recipe'] = 'engine/web_engine_drone'
  targets.append(properties)

  # For running Firefox Unit tests:
  properties = copy.deepcopy(drone_props)
  properties['command_name'] = 'firefox-unit-linux'
  properties['name'] = properties['command_name']
  # These are the felt commands which will be used.
  properties['command_args'] = ['test', '--browser=firefox']
  properties['recipe'] = 'engine/web_engine_drone'
  targets.append(properties)
  return targets


def GenTests(api):
  yield api.test(
     'basic',
     api.properties(clobber=True),
     api.buildbucket.try_build(
          project='proj',
          builder='try-builder',
          bucket='try',
          git_repo='https://flutter.googlesource.com/mirrors/engine',
          revision='a' * 40,
          build_number=123,
     ),
  )
  yield api.test(
     'mac-post-submit',
     api.properties(goma_jobs='200', gclient_variables={'download_emsdk': True}),
     api.platform('mac', 64),
     api.runtime(is_experimental=False),
     api.buildbucket.try_build(
          project='proj',
          builder='try-builder',
          bucket='try',
          git_repo='https://flutter.googlesource.com/mirrors/engine',
          revision='a' * 40,
          build_number=123,
     ),
  )
  yield api.test(
     'windows-post-submit',
     api.properties(
        gclient_variables={'download_emsdk': True}
     ),
     api.platform('win', 64),
     api.runtime(is_experimental=False),
     api.buildbucket.ci_build(
          project='flutter',
          bucket='prod',
          git_repo='https://flutter.googlesource.com/mirrors/engine',
          git_ref='refs/heads/main'
     ),
  )

