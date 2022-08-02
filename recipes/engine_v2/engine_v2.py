# Copyright 2021 The Chromium Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

# Orchestrator recipe that coordinates dependencies and build/test execution
# of sub-builds.
#
# This recipe is the main entry point for every builder(e.g. Windows Host
# Engine, Mac iOS Engine, etc). Once here this recipe will read the builder
# configuration from <engine_checkout>/ci/builders/<builder_name>, spawn
# subbuilds to compile/archive using engine_v2/builder.py wait for dependencies
# to be ready and then spawn subbuilds to run expensive tests using
# engine_v2/tester.py.

from contextlib import contextmanager

from PB.recipes.flutter.engine.engine import InputProperties
from PB.recipes.flutter.engine.engine import EnvProperties

from PB.go.chromium.org.luci.buildbucket.proto import build as build_pb2
from PB.go.chromium.org.luci.buildbucket.proto \
  import builds_service as builds_service_pb2
from google.protobuf import struct_pb2

PYTHON_VERSION_COMPATIBILITY = 'PY3'

DEPS = [
    'depot_tools/gsutil',
    'flutter/display_util',
    'flutter/repo_util',
    'flutter/osx_sdk',
    'flutter/shard_util_v2',
    'recipe_engine/buildbucket',
    'recipe_engine/file',
    'recipe_engine/json',
    'recipe_engine/path',
    'recipe_engine/platform',
    'recipe_engine/properties',
    'recipe_engine/step',
]

PROPERTIES = InputProperties
ENV_PROPERTIES = EnvProperties


def RunSteps(api, properties, env_properties):
  config_name = api.properties.get('config_name')
  # Checkout engine repository only.
  checkout_path = api.path['start_dir'].join('engine')
  api.repo_util.checkout(
      'engine',
      checkout_path=checkout_path,
      url=api.properties.get('git_url'),
      ref=api.properties.get('git_ref')
  )
  # Read builds configuration from repository under test.
  config_path = checkout_path.join('ci', 'builders', '%s.json' % config_name)
  builds = api.properties.get('builds')
  if builds is None:
    builds = api.json.read(
        'Read build config file',
        config_path,
        step_test_data=lambda: api.json.test_api.output({})
    ).json.output.get('builds', [])
  with api.step.nest('launch builds') as presentation:
    tasks = api.shard_util_v2.schedule_builds(builds, presentation)
  with api.step.nest('collect builds') as presentation:
    build_results = api.shard_util_v2.collect(tasks, presentation)

  api.display_util.display_builds(
      step_name='display builds',
      builds=[b.build_proto for b in build_results.values()],
      raise_on_failure=True,
  )

  # Run tests
  tests = api.properties.get('tests')
  if tests is None:
    tests = api.json.read(
        'Read build config file',
        config_path,
        step_test_data=lambda: api.json.test_api.output({})
    ).json.output.get('tests', [])
  with api.step.nest('launch tests') as presentation:
    tasks = api.shard_util_v2.schedule_tests(tests, build_results, presentation)
  with api.step.nest('collect tests') as presentation:
    test_results = api.shard_util_v2.collect(tasks, presentation)

  api.display_util.display_builds(
      step_name='display tests',
      builds=[b.build_proto for b in test_results.values()],
      raise_on_failure=True,
  )


  # Global generators
  generators = api.properties.get('generators')
  if generators is None:
    generators = api.json.read(
        'Read build config file',
        config_path,
        step_test_data=lambda: api.json.test_api.output({})
    ).json.output.get('generators', [])
  if generators:
    # Generators require a full engine checkout.
    full_engine_checkout = api.path['cache'].join('builder')
    api.file.ensure_directory('Ensure full engine checkout folder', full_engine_checkout)
    clobber = api.properties.get('clobber', True)
    gclient_vars = api.shard_util_v2.unfreeze_dict(api.properties.get('gclient_variables', {}))
    env, env_prefixes = api.repo_util.engine_environment(full_engine_checkout)
    api.repo_util.engine_checkout(
        full_engine_checkout, env, env_prefixes, clobber,
        custom_vars=gclient_vars
    )
    # Download sub-builds
    out_builds_path = full_engine_checkout.join('src', 'out')
    api.file.rmtree('Clobber build download folder', out_builds_path)
    api.shard_util_v2.download_full_builds(build_results, out_builds_path)
    with api.step.nest('Global generators') as presentation:
      if 'tasks' in generators: 
        for generator_task in generators['tasks']:
          # Generators must run from inside flutter folder.
          # If platform is mac we need to run the generator from an xcode context.
          if api.platform.is_mac:
            with api.osx_sdk('ios'):
              _run_global_generator(api, generator_task, full_engine_checkout)
          else:
            _run_global_generator(api, generator_task, full_engine_checkout)
    api.file.listdir('Final List checkout', full_engine_checkout.join('src', 'out'), recursive=True)
  # Global archives
  archives = api.properties.get('archives')
  if archives is None:
    archives = api.json.read(
        'Read build config file',
        config_path,
        step_test_data=lambda: api.json.test_api.output({})
    ).json.output.get('archives', [])
  # Global archives are stored in out folder from full_engine_checkout inside release, debug or profile
  # depending of the runtime mode. So far we are uploading files only.
  bucket = 'flutter_archives_v2'
  for archive in archives:
    source = full_engine_checkout.join('src', archive.get('source'))
    commit = api.repo_util.get_commit(full_engine_checkout.join('src', 'flutter'))
    artifact_path = 'flutter_infra_release/flutter/%s/%s' % (commit, archive.get('destination'))
    api.gsutil.upload(
        source=source,
        bucket=bucket,
        dest=artifact_path,
        args=['-r'],
        name=archive.get('name'),
    )


def _run_global_generator(api, generator_task, full_engine_checkout):
  cmd = []
  api.file.listdir('List checkout', full_engine_checkout.join('src', 'out'), recursive=True)
  script = generator_task.get('script')
  full_path_script = full_engine_checkout.join('src', script)
  cmd.append(full_path_script)
  cmd.extend(generator_task.get('parameters', []))
  api.step(generator_task.get('name'), cmd)


def GenTests(api):
  try_subbuild1 = api.shard_util_v2.try_build_message(
      build_id=8945511751514863186,
      builder="builder-subbuild1",
      output_props={"test_orchestration_inputs_hash": "abc"},
      status="SUCCESS",
  )
  builds = [{
      "name": "ios_debug", "gn": ["--ios"],
      "ninja": {"config": "ios_debug", "targets": []},
      "generators": [{"name": "generator1", "script": "script1.sh"}]
  }]
  generators = {
          "tasks":
              [
                  {
                    "language": "python",
                    "name": "Debug-FlutterMacOS.framework",
                    "parameters": [
                        "--variant",
                        "host_profile",
                        "--type",
                        "engine",
                        "--engine-capture-core-dump"
                    ],
                    "script": "flutter/sky/tools/create_macos_framework.py",
                    "type": "local"
                  }
              ]
  }
  archives = [
      {
          'source': '/a/b/c.txt',
          'destination': 'bucket/c.txt',
          'name': 'c.txt'

      }
  ]


  yield api.test(
      'basic_mac',
      api.platform.name('mac'),
      api.properties(builds=builds, tests=[], generators=generators, archives=archives, environment='Staging'),
      api.buildbucket.try_build(
          project='proj',
          builder='try-builder',
          git_repo='https://flutter.googlesource.com/mirrors/engine',
          revision='a' * 40,
          build_number=123,
      ),
      api.shard_util_v2.child_build_steps(
          builds=[try_subbuild1],
          launch_step="launch builds",
          collect_step="collect builds",
      ),
  )

  yield api.test(
      'basic_linux',
      api.platform.name('linux'),
      api.properties(builds=builds, tests=[], generators=generators, environment='Staging'),
      api.buildbucket.try_build(
          project='proj',
          builder='try-builder',
          git_repo='https://flutter.googlesource.com/mirrors/engine',
          revision='a' * 40,
          build_number=123,
      ),
      api.shard_util_v2.child_build_steps(
          builds=[try_subbuild1],
          launch_step="launch builds",
          collect_step="collect builds",
      ),
  )

  yield api.test(
      'config_from_file',
      api.properties(environment='Staging'),
      api.buildbucket.try_build(
          project='proj',
          builder='try-builder',
          git_repo='https://github.com/repo/a',
          revision='a' * 40,
          build_number=123,
      ),
      api.shard_util_v2.child_build_steps(
          builds=[try_subbuild1],
          launch_step="launch builds",
          collect_step="collect builds",
      ),
      api.step_data(
          'Read build config file',
          api.json.output({'builds': builds})),
      api.step_data(
          'Read build config file (2)',
          api.json.output({'builds': builds})),
  )
