# Copyright 2023 The Chromium Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Flutter Engine tester recipe.

Recipe to run engine scoped tests using prebuilts stored in CAS..


This recipe expects configurations with the following format:

  {
      "test_dependencies": [
          {
              "dependency": "chrome_and_driver", "version": "version:111.0"
          }
      ],
      "resolved_deps": [
          {
              "full_build": "f5b9de6cc9f4b05833aa128717d3112c133e2363e4303df9a1951540c79e72a3/87"
          },
          {`
              "full_build": "32b40edba8bfbf7729374eaa4aa44bf0d89c385f080f64b56c9fbce7172e4a71/84"
          }
      ],
      'tasks': [
          {
              'language': 'dart',
              'name': 'felt test: chrome-unit-linux',
              'parameters': [
                  'test',
                  '--browser=chrome',
                  '--require-skia-gold'
              ],
              'script': 'flutter/lib/web_ui/dev/felt'
          }
      ]
  }

test_dependnecies - is a list of dictionaries with third party dependencies required for the tests.
resolved_deps - is a list of dictionaries with CAS hashes pointing to full sub-build archives.
tasks - is a list of dictionaries with the scripts to run in this test sub-build.


This recipe will be called from the engine_v2/engine_v2 recipe using the shard_util_v2 module. The
test configuration is defined in the engine build configurations files as global tests. 
"""
import copy

from contextlib import contextmanager

from google.protobuf import struct_pb2
from PB.recipes.flutter.engine.engine import InputProperties
from PB.recipes.flutter.engine.engine import EnvProperties
from PB.go.chromium.org.luci.buildbucket.proto import build as build_pb2

DEPS = [
    'depot_tools/depot_tools',
    'flutter/flutter_deps',
    'flutter/logs_util',
    'flutter/repo_util',
    'flutter/retry',
    'flutter/test_utils',
    'recipe_engine/cas',
    'recipe_engine/context',
    'recipe_engine/file',
    'recipe_engine/path',
    'recipe_engine/properties',
    'recipe_engine/step',
]

PROPERTIES = InputProperties
ENV_PROPERTIES = EnvProperties


def run_tests(api, test, checkout, env, env_prefixes):
  """Runs sub-build tests."""
  # Install dependencies.
  deps = test.get('test_dependencies', [])
  api.flutter_deps.required_deps(env, env_prefixes, deps)

  out_path = checkout.join('out')
  # Download build dependencies.
  for dep in test.get('resolved_deps', []):
    out_hash = dep.get('full_build')
    api.cas.download(f'Download {out_hash}', out_hash, out_path)
  for task in test.get('tasks', []):
    command = [task.get('language')] if task.get('language') else []
    # Ideally local tests should be completely hermetic and in theory we can run
    # them in parallel using futures. I haven't found a flutter engine
    # configuration with more than one local test but once we find it we
    # should run the list of tests using parallelism.
    # TODO(godofredoc): Optimize to run multiple local tests in parallel.
    command.append(checkout.join(task.get('script')))
    command.extend(task.get('parameters', []))
    step_name = api.test_utils.test_step_name(task.get('name'))

    def run_test():
      return api.step(step_name, command)

    api.logs_util.initialize_logs_collection(env)
    try:
      # Run within another context to make the logs env variable available to
      # test scripts.
      with api.context(env=env, env_prefixes=env_prefixes):
        api.retry.wrap(run_test, step_name=task.get('name'))
    finally:
      api.logs_util.upload_logs(task.get('name'))


def Test(api, checkout, env, env_prefixes):
  """Runs a global test using prebuilts."""
  test = api.properties.get('build')
  with api.context(env=env, env_prefixes=env_prefixes,
                   cwd=checkout.join('flutter')), api.depot_tools.on_path():
    run_tests(api, test, checkout, env, env_prefixes)


def RunSteps(api, properties, env_properties):
  # Sets the engine environment and checkouts the source code.
  checkout = api.path['cache'].join('builder', 'src')
  api.file.rmtree('Clobber build output', checkout.join('out'))
  cache_root = api.path['cache'].join('builder')
  api.file.ensure_directory('Ensure checkout cache', cache_root)
  env, env_prefixes = api.repo_util.engine_environment(
      api.path['cache'].join('builder')
  )
  # Engine path is used inconsistently across the engine repo. We'll start
  # with [cache]/builder and will adjust it to start using it consistently.
  env['ENGINE_PATH'] = api.path['cache'].join('builder')
  api.repo_util.engine_checkout(cache_root, env, env_prefixes)
  Test(api, checkout, env, env_prefixes)


def GenTests(api):
  build = {
      "test_dependencies": [{
          "dependency": "chrome_and_driver", "version": "version:111.0"
      }], "resolved_deps": [{
          "full_build":
              "f5b9de6cc9f4b05833aa128717d3112c133e2363e4303df9a1951540c79e72a3/87"
      }, {
          "full_build":
              "32b40edba8bfbf7729374eaa4aa44bf0d89c385f080f64b56c9fbce7172e4a71/84"
      }], 'tasks': [{
          'language': 'dart', 'name': 'felt test: chrome-unit-linux',
          'parameters': ['test', '--browser=chrome', '--require-skia-gold'],
          'script': 'flutter/lib/web_ui/dev/felt'
      }]
  }
  yield api.test(
      'basic',
      api.properties(build=build),
  )
