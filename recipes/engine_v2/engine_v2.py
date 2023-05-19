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
from google.protobuf import struct_pb2

from PB.recipes.flutter.engine.engine import InputProperties
from PB.recipes.flutter.engine.engine import EnvProperties

from PB.go.chromium.org.luci.buildbucket.proto import build as build_pb2
from PB.go.chromium.org.luci.buildbucket.proto \
  import builds_service as builds_service_pb2

from RECIPE_MODULES.flutter.flutter_bcid.api import BcidStage

DEPS = [
    'depot_tools/depot_tools',
    'flutter/archives',
    'flutter/signing',
    'flutter/display_util',
    'flutter/flutter_bcid',
    'flutter/flutter_deps',
    'flutter/monorepo',
    'flutter/pubsub',
    'flutter/repo_util',
    'flutter/osx_sdk',
    'flutter/shard_util_v2',
    'recipe_engine/buildbucket',
    'recipe_engine/context',
    'recipe_engine/file',
    'recipe_engine/json',
    'recipe_engine/path',
    'recipe_engine/platform',
    'recipe_engine/properties',
    'recipe_engine/raw_io',
    'recipe_engine/runtime',
    'recipe_engine/step',
]

PROPERTIES = InputProperties
ENV_PROPERTIES = EnvProperties
BUILD_RESULT_PUBSUB_ENDPOINT = 'projects/flutter-dashboard/topics/dart-internal-build-results'


def RunSteps(api, properties, env_properties):
  api.flutter_bcid.report_stage(BcidStage.START.value)
  config_name = api.properties.get('config_name')
  builds = api.properties.get('builds')
  tests = api.properties.get('tests')
  generators = api.properties.get('generators')
  archives = api.properties.get('archives')
  checkout_path = None
  if config_name:
    # Read builds configuration from repository under test.
    if api.monorepo.is_monorepo_ci_build or api.monorepo.is_monorepo_try_build:
      project = 'monorepo'
    else:
      project = 'engine'

    # Only check out the repository, not dependencies.
    api.flutter_bcid.report_stage(BcidStage.FETCH.value)
    checkout_path = api.path['start_dir'].join(project)
    api.repo_util.checkout(
        project,
        checkout_path=checkout_path,
        url=api.properties.get('git_url'),
        ref=api.properties.get('git_ref')
    )
    config_path = checkout_path.join('ci', 'builders', '%s.json' % config_name)
    config = api.file.read_json(
        'Read build config file', config_path, test_data={}
    )
    if builds is None:
      builds = config.get('builds')
    if tests is None:
      tests = config.get('tests')
    if generators is None:
      generators = config.get('generators')
    if archives is None:
      archives = config.get('archives')
  if builds is None:
    builds = []
  if tests is None:
    tests = []
  if generators is None:
    generators = []
  if archives is None:
    archives = []

  current_branch = 'main'
  if checkout_path and api.repo_util.is_release_candidate_branch(checkout_path):
    current_branch = api.repo_util.release_candidate_branch(checkout_path)

  # Execute subbuilds
  with api.step.nest('launch builds') as presentation:
    tasks = api.shard_util_v2.schedule_builds(
        builds, presentation, branch=current_branch
    )
  with api.step.nest('collect builds') as presentation:
    build_results = api.shard_util_v2.collect(tasks)

  api.display_util.display_subbuilds(
      step_name='display builds',
      subbuilds=build_results,
      raise_on_failure=True,
  )

  # Global generators
  if generators or archives or (
      checkout_path and
      api.repo_util.is_release_candidate_branch(checkout_path)):
    # Generators, archives and codesign require a full engine checkout.
    full_engine_checkout = api.path['cache'].join('builder')
    api.file.ensure_directory(
        'Ensure full engine checkout folder', full_engine_checkout
    )
    if api.monorepo.is_monorepo_ci_build or api.monorepo.is_monorepo_try_build:
      env, env_prefixes = api.repo_util.monorepo_environment(
          full_engine_checkout
      )
      api.repo_util.monorepo_checkout(full_engine_checkout, env, env_prefixes)
      full_engine_checkout = full_engine_checkout.join('engine')
    else:
      env, env_prefixes = api.repo_util.engine_environment(full_engine_checkout)
      api.repo_util.engine_checkout(full_engine_checkout, env, env_prefixes)
      # The checkouts are using cache which may have some old artifacts in the out
      # directory. We are cleaning out the folder to ensure we start from an empty
      # out folder.
      api.file.rmtree(
          'Clobber build output', full_engine_checkout.join('src', 'out')
      )

  if generators:
    # Download sub-builds
    out_builds_path = full_engine_checkout.join('src', 'out')
    api.file.rmtree('Clobber build download folder', out_builds_path)
    api.shard_util_v2.download_full_builds(build_results, out_builds_path)
    with api.step.nest('Global generators') as presentation:
      if 'tasks' in generators:
        api.flutter_bcid.report_stage(BcidStage.COMPILE.value)
        if api.platform.is_mac:
          with api.osx_sdk('ios'):
            _run_global_generators(
                api, generators, full_engine_checkout, env, env_prefixes
            )
            _archive(api, archives, full_engine_checkout)
        else:
          _run_global_generators(
              api, generators, full_engine_checkout, env, env_prefixes
          )
          _archive(api, archives, full_engine_checkout)

  # Run tests
  if not api.flutter_bcid.is_official_build():
    with api.step.nest('launch tests') as presentation:
      tasks = api.shard_util_v2.schedule_tests(
          tests, build_results, presentation
      )

    with api.step.nest('collect tests') as presentation:
      test_results = api.shard_util_v2.collect(tasks)

    api.display_util.display_subbuilds(
        step_name='display tests',
        subbuilds=test_results,
        raise_on_failure=True,
    )

  not_experimental = not api.runtime.is_experimental and api.buildbucket.build.id != 0
  prod_build = api.flutter_bcid.is_prod_build()
  if not_experimental and prod_build:
    api.pubsub.publish_message(
        BUILD_RESULT_PUBSUB_ENDPOINT, api.buildbucket.build.id
    )


def _archive(api, archives, full_engine_checkout):
  """Proces global archives.

  Args:
    api: Object point to all the imported modules of this build.
    archives: List of global archive configurations.
    full_engine_path: Path to a gclient engine checkout.
  """
  if not archives:
    return

  api.flutter_bcid.report_stage(BcidStage.UPLOAD.value)
  # Global archives are stored in out folder from full_engine_checkout inside
  # release, debug or profile depending on the runtime mode.
  # So far we are uploading files only.
  files_to_archive = api.archives.global_generator_paths(
      full_engine_checkout.join('src'), archives
  )

  # Sign artifacts if running in mac.
  is_release_candidate = api.repo_util.is_release_candidate_branch(
      full_engine_checkout.join('src', 'flutter')
  )
  signing_paths = [
      path.local
      for path in files_to_archive
      if api.signing.requires_signing(path.local)
  ]
  if api.platform.is_mac and is_release_candidate:
    signing_paths = [
        path.local
        for path in files_to_archive
        if api.signing.requires_signing(path.local)
    ]
    api.signing.code_sign(signing_paths)
  for archive in files_to_archive:
    api.archives.upload_artifact(archive.local, archive.remote)
    api.flutter_bcid.upload_provenance(archive.local, archive.remote)
  api.flutter_bcid.report_stage(BcidStage.UPLOAD_COMPLETE.value)


def _run_global_generators(
    api, generators, full_engine_checkout, env, env_prefixes
):
  """Runs global generator tasks.

  Args:
    generators: list(dict) global generator configurations used to run scripts
        over subbuild outputs to generate artifacts.
    full_engine_checkout: (Path) the checkout directory.
    env: (dict) a dictionary with environment variables to set.
    env_prefixes: (dict) a dictionary with lists of values associated to env
        variables with priority based on the order.
  """
  # Install dependencies. If this is running from within an xcode context it will use
  # xcode's ruby.
  deps = api.properties.get('dependencies', [])
  api.flutter_deps.required_deps(env, env_prefixes, deps)
  for generator_task in generators['tasks']:
    # Generators must run from inside flutter folder.
    # If platform is mac we need to run the generator from an xcode context.
    with api.context(env=env, env_prefixes=env_prefixes,
                     cwd=full_engine_checkout), api.depot_tools.on_path():
      cmd = [generator_task.get('language')
            ] if generator_task.get('language') else []
      api.file.listdir(
          'List checkout',
          full_engine_checkout.join('src', 'out'),
          recursive=True
      )
      script = generator_task.get('script')
      full_path_script = full_engine_checkout.join('src', script)
      cmd.append(full_path_script)
      cmd.extend(generator_task.get('parameters', []))
      # Run within an engine context to make dart available.
      with api.context(env=env, env_prefixes=env_prefixes):
        api.step(generator_task.get('name'), cmd)


def GenTests(api):
  try_subbuild1 = api.shard_util_v2.try_build_message(
      build_id=8945511751514863186,
      builder="builder-subbuild1",
      output_props={"test_orchestration_inputs_hash": "abc"},
      status="SUCCESS",
  )
  builds = [{
      "archives": [{
          "base_path": "out/host_debug/zip_archives/", "type": "gcs",
          "include_paths": [
              "out/host_debug/zip_archives/darwin-x64/artifacts.zip",
              "out/host_debug/zip_archives/darwin-x64/FlutterEmbedder.framework.zip",
              "out/host_debug/zip_archives/dart-sdk-darwin-x64.zip",
              "out/host_debug/zip_archives/flutter-web-sdk-darwin-x64.zip"
          ], "name": "host_debug"
      }], "name": "ios_debug", "gn": ["--ios"],
      "ninja": {"config": "ios_debug", "targets": []},
      "generators": [{"name": "generator1", "script": "script1.sh"}],
      "drone_dimensions": ['os=Linux']
  }]
  generators = {
      "tasks": [{
          "language": "python3", "name": "Debug-FlutterMacOS.framework",
          "parameters": [
              "--variant", "host_profile", "--type", "engine",
              "--engine-capture-core-dump"
          ], "script": "flutter/sky/tools/create_macos_framework.py",
          "type": "local"
      }]
  }
  archives = [{
      'source': '/a/b/c.txt', 'destination': 'bucket/c.txt', 'name': 'c.txt'
  }]

  yield api.test(
      'basic_mac', api.platform.name('mac'),
      api.properties(
          builds=builds,
          tests=[],
          generators=generators,
          archives=archives,
      ),
      api.buildbucket.ci_build(
          project='flutter',
          bucket='prod',
          builder='prod-builder',
          git_repo='https://flutter.googlesource.com/mirrors/engine',
          git_ref='refs/heads/main',
          revision='a' * 40,
          build_number=123,
      ),
      api.shard_util_v2.child_build_steps(
          subbuilds=[try_subbuild1],
          launch_step="launch builds.schedule",
          collect_step="collect builds",
      ),
      api.step_data(
          'Global generators.git rev-parse',
          stdout=api.raw_io
          .output_text('12345abcde12345abcde12345abcde12345abcde\n')
      )
  )

  yield api.test(
      'basic_linux',
      api.platform.name('linux'),
      api.properties(
          builds=builds, generators=generators, environment='Staging'
      ),
      api.buildbucket.try_build(
          project='proj',
          builder='try-builder',
          git_repo='https://flutter.googlesource.com/mirrors/engine',
          revision='a' * 40,
          build_number=123,
      ),
      api.shard_util_v2.child_build_steps(
          subbuilds=[try_subbuild1],
          launch_step="launch builds.schedule",
          collect_step="collect builds",
      ),
  )

  yield api.test(
      'config_from_file',
      api.properties(config_name='config_name', environment='Staging'),
      api.buildbucket.try_build(
          project='proj',
          builder='try-builder',
          git_repo='https://flutter.googlesource.com/mirrors/engine',
          revision='a' * 40,
          build_number=123,
      ),
      api.shard_util_v2.child_build_steps(
          subbuilds=[try_subbuild1],
          launch_step="launch builds.schedule",
          collect_step="collect builds",
      ),
      api.step_data(
          'Read build config file',
          api.file.read_json({'builds': builds, 'archives': archives})
      ),
  )

  yield api.test(
      'overridden_config_from_file',
      api.properties(
          config_name='overridden_config_name', archives=[], generators=[]
      ),
      api.buildbucket.try_build(
          project='proj',
          builder='try-builder',
          git_repo='https://flutter.googlesource.com/mirrors/engine',
          revision='a' * 40,
          build_number=123,
      ),
      api.step_data(
          'Read build config file', api.file.read_json({'archives': archives})
      ),
  )

  yield api.test(
      'monorepo_try',
      api.platform.name('linux'),
      api.properties(builds=builds, builder_name_suffix='-try'),
      api.monorepo.try_build(),
      api.shard_util_v2.child_build_steps(
          subbuilds=[try_subbuild1],
          launch_step="launch builds.schedule",
          collect_step="collect builds",
      ),
  )

  yield api.test(
      'monorepo_config_file',
      api.platform.name('linux'),
      api.properties(config_name='config_name'),
      api.monorepo.ci_build(),
      api.shard_util_v2.child_build_steps(
          subbuilds=[try_subbuild1],
          launch_step="launch builds.schedule",
          collect_step="collect builds",
      ),
      api.step_data(
          'Read build config file', api.file.read_json({'builds': builds})
      ),
      api.step_data(
          'Identify branches.git branch',
          stdout=api.raw_io
          .output_text('branch1\nbranch2\nflutter-3.2-candidate.5')
      ),
  )

  yield api.test(
      'codesign_release_branch',
      api.platform.name('mac'),
      api.properties(config_name='config_name', environment='Staging'),
      api.buildbucket.try_build(
          project='proj',
          builder='try-builder',
          git_repo='https://flutter.googlesource.com/mirrors/engine',
          revision='a' * 40,
          build_number=123,
      ),
      api.shard_util_v2.child_build_steps(
          subbuilds=[try_subbuild1],
          launch_step="launch builds.schedule",
          collect_step="collect builds",
      ),
      api.step_data(
          'Read build config file',
          api.file.read_json({
              'builds': builds, 'archives': archives, 'generators': generators
          })
      ),
      api.step_data(
          'Identify branches.git rev-parse',
          stdout=api.raw_io
          .output_text('12345abcde12345abcde12345abcde12345abcde\n')
      ),
      api.step_data(
          'Identify branches.git branch',
          stdout=api.raw_io
          .output_text('branch1\nbranch2\nflutter-3.2-candidate.5')
      ),
      api.step_data(
          'Identify branches (2).git branch',
          stdout=api.raw_io
          .output_text('branch1\nbranch2\nflutter-3.2-candidate.5')
      ),
      api.step_data(
          'Global generators.Identify branches.git branch',
          stdout=api.raw_io
          .output_text('branch1\nbranch2\nflutter-3.2-candidate.5')
      ),
  )

  tests = [{
      "name":
          "framework_tests libraries", "shard":
              "framework_tests", "subshard":
                  "libraries", "test_dependencies": [{
                      "dependency": "android_sdk", "version": "version:33v6"
                  }]
  }]

  subtest1 = api.shard_util_v2.try_build_message(
      build_id=8945511751514863187,
      builder="subtest1",
      output_props={"test_orchestration_inputs_hash": "abc"},
      status="SUCCESS",
  )

  yield api.test(
      'monorepo_config_file_tests',
      api.platform.name('linux'),
      api.properties(config_name='config_name'),
      api.monorepo.ci_build(),
      api.shard_util_v2.child_build_steps(
          subbuilds=[try_subbuild1],
          launch_step="launch builds.schedule",
          collect_step="collect builds",
      ),
      api.shard_util_v2.child_build_steps(
          subbuilds=[subtest1],
          launch_step="launch tests.schedule",
          collect_step="collect tests",
      ),
      api.step_data(
          'Read build config file',
          api.file.read_json({
              'builds': builds, 'tests': tests, 'generators': generators,
              'archives': archives
          })
      ),
      api.step_data(
          'Identify branches.git branch',
          stdout=api.raw_io
          .output_text('branch1\nbranch2\nflutter-3.2-candidate.5')
      ),
  )
