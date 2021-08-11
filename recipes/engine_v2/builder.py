# Copyright 2021 The Chromium Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Flutter Engine builder recipe.

This recipe is used to build flavors of flutter engine identified by lists of
gn flags and ninja configs and targets.


The following are examples of valid configurations passed to builders using
this recipe in the builds property:

 {
    "gn" : [
       "--ios",
       "--runtime-mode",
       "debug",
       "--simulator",
       "--no-lto"
    ],
    "ninja": {
      "config": "ios_debug_sim",
      "targets": ["ios_test_flutter"]
    }
 }
"""

from contextlib import contextmanager

from google.protobuf import struct_pb2
from PB.recipes.flutter.engine import InputProperties
from PB.recipes.flutter.engine import EnvProperties
from PB.go.chromium.org.luci.buildbucket.proto import build as build_pb2

DEPS = [
    'flutter/build_util',
    'flutter/flutter_deps',
    'flutter/os_utils',
    'flutter/osx_sdk',
    'flutter/repo_util',
    'fuchsia/goma',
    'recipe_engine/context',
    'recipe_engine/file',
    'recipe_engine/path',
    'recipe_engine/platform',
    'recipe_engine/properties',
    'recipe_engine/step',
]

PROPERTIES = InputProperties
ENV_PROPERTIES = EnvProperties


def Build(api, checkout, env, env_prefixes):
  """Builds a flavor identified as a set of gn and ninja configs."""
  ninja_tool = {
      "ninja": api.build_util.build,
      "autoninja": api.build_util.build_autoninja,
  }
  deps = api.properties.get('dependencies', [])
  api.flutter_deps.required_deps(env, env_prefixes, deps)
  build = api.properties.get('build')
  api.build_util.run_gn(build.get('gn'), checkout)
  ninja = build.get('ninja')
  ninja_tool[ninja.get('tool', 'ninja')
            ](ninja.get('config'), checkout, ninja.get('targets'))
  generator_tasks = build.get('generators', {}).get('tasks', [])
  pub_dirs = build.get('generators', {}).get('pub_dirs', [])
  # Get only local tests.
  tests = [t for t in build.get('tests', []) if t.get('type') == 'local']
  with api.context(env=env, env_prefixes=env_prefixes,
                   cwd=checkout.join('flutter')):
    api.file.listdir('checkout files', checkout.join('out', 'host_debug_unopt', 'dart-sdk', 'bin'))
    # Run pub on all of the pub_dirs.
    for pub in pub_dirs:
      pub_dir = api.path.abs_to_path(
          api.path.dirname(
              checkout.join(pub))
      )
      with api.context(env=env, env_prefixes=env_prefixes,
                       cwd=pub_dir):
        api.step('pub get', ['pub', 'get'])
    for generator_task in generator_tasks:
      # Generators must run from inside flutter folder.
      cmd = []
      for script in generator_task.get('scripts'):
        full_path_script = checkout.join(script)
        cmd.append(full_path_script)
      cmd.extend(generator_task.get('parameters'))
      api.step(generator_task.get('name', []), cmd)
    # Run local tests in the builder to optimize resource usage.
    for test in tests:
      command = [test.get('language')] if test.get('language') else []
      # Ideally local tests should be completely hermetic and in theory we can run
      # them in parallel using futures. I haven't found a flutter engine
      # configuration with more than one local test but once we find it we
      # should run the list of tests using parallelism.
      # TODO(godofredoc): Optimize to run multiple local tests in parallel.
      command.append(checkout.join(test.get('script')))
      command.extend(test.get('parameters', []))
      api.step(test.get('name'), command)


def RunSteps(api, properties, env_properties):
  checkout = api.path['cache'].join('builder', 'src')
  api.file.rmtree('Clobber build output', checkout.join('out'))
  cache_root = api.path['cache'].join('builder')
  api.file.ensure_directory('Ensure checkout cache', cache_root)

  # Enable long path support on Windows.
  api.os_utils.enable_long_paths()
  env, env_prefixes = api.repo_util.engine_environment(checkout)

  # Engine path is used inconsistently across the engine repo. We'll start
  # with [cache]/builder and will adjust it to start using it consistently.
  env['ENGINE_PATH'] = api.path['cache'].join('builder')

  custom_vars = api.properties.get('gclient_custom_vars', {})
  api.repo_util.engine_checkout(
      cache_root, env, env_prefixes, custom_vars=custom_vars
  )
  if api.platform.is_mac:
    with api.osx_sdk('ios'):
      Build(api, checkout, env, env_prefixes)
  else:
    Build(api, checkout, env, env_prefixes)


def GenTests(api):
  build = {
      "gn": ["--ios"], "ninja": {"config": "ios_debug", "targets": []},
      "generators": {
          "pub_dirs": ["dev"],
          "tasks": [
              {
                  "name": "generator1",
                  "scripts": ["script1.sh", "dev/felt.dart"],
                  "parameters": ["--argument1"]
              }
          ]
      },
      "tests": [
          {
               "name": "mytest", "script": "myscript.sh",
               "parameters": ["param1", "param2"], "type": "local"
          }
      ]
  }
  yield api.test('basic', api.properties(build=build, goma_jobs="100"))
  yield api.test(
      'mac', api.properties(build=build, goma_jobs="100"),
      api.platform('mac', 64),
      api.path.exists(
          api.path['cache'].join('builder', 'src', 'dev'),
      )
  )
  build["gclient_custom_vars"] = {"example_custom_var": True}
  yield api.test(
      'basic_custom_vars', api.properties(build=build, goma_jobs="100")
  )
