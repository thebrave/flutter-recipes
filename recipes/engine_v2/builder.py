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
import copy

from contextlib import contextmanager

from google.protobuf import struct_pb2
from PB.recipes.flutter.engine.engine import InputProperties
from PB.recipes.flutter.engine.engine import EnvProperties
from PB.go.chromium.org.luci.buildbucket.proto import build as build_pb2

DEPS = [
    'depot_tools/gsutil',
    'flutter/archives',
    'flutter/build_util',
    'flutter/flutter_bcid',
    'flutter/flutter_deps',
    'flutter/monorepo',
    'flutter/os_utils',
    'flutter/osx_sdk',
    'flutter/repo_util',
    'flutter/retry',
    'flutter/shard_util_v2',
    'flutter/test_utils',
    'fuchsia/cas_util',
    'recipe_engine/bcid_reporter',
    'recipe_engine/buildbucket',
    'recipe_engine/context',
    'recipe_engine/file',
    'recipe_engine/path',
    'recipe_engine/platform',
    'recipe_engine/properties',
    'recipe_engine/raw_io',
    'recipe_engine/step',
]

PROPERTIES = InputProperties
ENV_PROPERTIES = EnvProperties
ANDROID_ARTIFACTS_BUCKET = 'download.flutter.io'


def Build(api, checkout, env, env_prefixes, outputs):
  """Builds a flavor identified as a set of gn and ninja configs."""
  ninja_tool = {
      "ninja": api.build_util.build,
  }
  deps = api.properties.get('dependencies', [])
  api.flutter_deps.required_deps(env, env_prefixes, deps)
  build = api.properties.get('build')
  api.flutter_bcid.report_stage('compile')
  api.build_util.run_gn(build.get('gn'), checkout)
  ninja = build.get('ninja')
  ninja_tool[ninja.get('tool', 'ninja')
            ](ninja.get('config'), checkout, ninja.get('targets'))
  # Archive full build. This is inneficient but necessary for global generators.
  full_build_hash = api.shard_util_v2.archive_full_build(
          checkout.join('out', build.get('name')), build.get('name'))
  outputs['full_build'] = full_build_hash
  generator_tasks = build.get('generators', {}).get('tasks', [])
  pub_dirs = build.get('generators', {}).get('pub_dirs', [])
  archives = build.get('archives', [])
  # Get only local tests.
  tests = [t for t in build.get('tests', []) if t.get('type') == 'local']
  with api.context(env=env, env_prefixes=env_prefixes,
                   cwd=checkout.join('flutter')):
    # Run pub on all of the pub_dirs.
    for pub in pub_dirs:
      pub_dir = api.path.abs_to_path(
          api.path.dirname(
              checkout.join(pub))
      )
      with api.context(env=env, env_prefixes=env_prefixes,
                       cwd=pub_dir):
        api.step('dart pub get', ['dart', 'pub', 'get'])
    for generator_task in generator_tasks:
      # Generators must run from inside flutter folder.
      cmd = []
      for script in generator_task.get('scripts'):
        full_path_script = checkout.join(script)
        cmd.append(full_path_script)
      cmd.extend(generator_task.get('parameters', []))
      api.step(generator_task.get('name'), cmd)
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
      #api.step(test.get('name'), command)
      step_name = api.test_utils.test_step_name(test.get('name'))

      def run_test():
        return api.step(step_name, command)

      # Rerun test step 3 times by default if failing.
      # TODO(keyonghan): notify tree gardener for test failures/flakes:
      # https://github.com/flutter/flutter/issues/89308
      api.retry.wrap(run_test, step_name=test.get('name'))

    api.flutter_bcid.report_stage('upload')
    for archive_config in archives:
      outputs[archive_config['name']] = Archive(api, checkout, archive_config)
    api.flutter_bcid.report_stage('upload-complete')


def Archive(api, checkout,  archive_config):
  paths = api.archives.engine_v2_gcs_paths(checkout, archive_config)
  for path in paths:
    api.archives.upload_artifact(path.local, path.remote)
    api.flutter_bcid.upload_provenance(
        path.local,
        path.remote
    )

def RunSteps(api, properties, env_properties):
  api.flutter_bcid.report_stage('start')
  checkout = api.path['cache'].join('builder', 'src')
  api.file.rmtree('Clobber build output', checkout.join('out'))
  cache_root = api.path['cache'].join('builder')
  api.file.ensure_directory('Ensure checkout cache', cache_root)

  # Enable long path support on Windows.
  api.os_utils.enable_long_paths()
  env, env_prefixes = api.repo_util.engine_environment(api.path['cache'].join('builder'))

  # Engine path is used inconsistently across the engine repo. We'll start
  # with [cache]/builder and will adjust it to start using it consistently.
  env['ENGINE_PATH'] = api.path['cache'].join('builder')

  # Pass gclient_variables to checkout.

  api.flutter_bcid.report_stage('fetch')
  if api.monorepo.is_monorepo_ci_build or api.monorepo.is_monorepo_try_build:
    api.repo_util.monorepo_checkout(cache_root, env, env_prefixes)
    checkout = api.path['cache'].join('builder', 'engine', 'src')
  else:
    api.repo_util.engine_checkout(cache_root, env, env_prefixes)
  outputs = {}
  if api.platform.is_mac:
    with api.osx_sdk('ios'):
      Build(api, checkout, env, env_prefixes, outputs)
  else:
    Build(api, checkout, env, env_prefixes, outputs)
  output_props = api.step('Set output properties', None)
  output_props.presentation.properties['cas_output_hash'] = outputs


def GenTests(api):
  build = {
      "archives": [
                {
                    "name": "android_jit_release_x86",
                    "type": "gcs",
                    "base_path": "out/android_jit_release_x86/zip_archives/",
                    "include_paths": [
                        "out/android_jit_release_x86/zip_archives/android-x86-jit-release/artifacts.zip",
                        "out/android_jit_release_x86/zip_archives/download.flutter.io"
                    ]
                }
      ],
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
  yield api.test(
      'basic',
      api.properties(build=build, no_goma=True),
      api.buildbucket.ci_build(
          project='flutter',
          bucket='prod',
          builder='linux-host',
          git_repo='https://flutter.googlesource.com/mirrors/engine',
          git_ref='refs/heads/main',
          revision='abcd' * 10,
          build_number=123,
      ),
  )
  yield api.test(
      'mac',
      api.properties(build=build, no_goma=True),
      api.platform('mac', 64),
      api.buildbucket.ci_build(
          project='flutter',
          bucket='prod',
          builder='mac-host',
          git_repo='https://flutter.googlesource.com/mirrors/engine',
          git_ref='refs/heads/main',
          revision='abcd' * 10,
          build_number=123,
      ),
  )
  yield api.test(
      'monorepo',
      api.properties(build=build, no_goma=True),
      api.monorepo.ci_build(),
  )
  yield api.test(
      'monorepo_tryjob',
      api.properties(build=build, no_goma=True),
      api.monorepo.try_build(),
  )

  build_custom = dict(build)
  build_custom["gclient_variables"] = {"example_custom_var": True}
  build_custom["tests"] = []
  yield api.test(
      'dart-internal-flutter', api.properties(build=build, no_goma=True),
      api.buildbucket.ci_build(
          project='dart-internal',
          bucket='flutter',
          git_repo='https://flutter.googlesource.com/mirrors/engine',
          git_ref='refs/heads/main',
      ),
  )
