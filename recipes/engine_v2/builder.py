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
import contextlib
import copy
import re

DEPS = [
    'depot_tools/depot_tools',
    'flutter/archives',
    'flutter/build_util',
    'flutter/flutter_bcid',
    'flutter/flutter_deps',
    'flutter/logs_util',
    'flutter/monorepo',
    'flutter/os_utils',
    'flutter/osx_sdk',
    'flutter/rbe',
    'flutter/repo_util',
    'flutter/retry',
    'flutter/shard_util',
    'flutter/signing',
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
    'recipe_engine/time',
]

ANDROID_ARTIFACTS_BUCKET = 'download.flutter.io'

# Relative paths used to mock paths for testing.
MOCK_JAR_PATH = (
    'io/flutter/x86_debug/'
    '1.0.0-0005149dca9b248663adcde4bdd7c6c915a76584/'
    'x86_debug-1.0.0-0005149dca9b248663adcde4bdd7c6c915a76584.jar'
)
MOCK_POM_PATH = (
    'io/flutter/x86_debug/'
    '1.0.0-0005149dca9b248663adcde4bdd7c6c915a76584/'
    'x86_debug-1.0.0-0005149dca9b248663adcde4bdd7c6c915a76584.pom'
)

# Used for mock paths
DIRECTORY = 'DIRECTORY'

# Default timeout for tests running as part of the build.
DEFAULT_TEST_TIMEOUT_SECS = 30 * 60


def run_generators(api, pub_dirs, generator_tasks, checkout, env, env_prefixes):
  """Runs sub-builds generators."""
  # Run pub on all of the pub_dirs.
  for pub in pub_dirs:
    pub_dir = api.path.abs_to_path(api.path.dirname(checkout / pub))
    with api.context(env=env, env_prefixes=env_prefixes, cwd=pub_dir):
      api.step('dart pub get', ['dart', 'pub', 'get'])
  for generator_task in generator_tasks:
    # Generators must run from inside flutter folder.
    cmd = []
    for script in generator_task.get('scripts'):
      full_path_script = checkout / script
      cmd.append(full_path_script)
    cmd.extend(generator_task.get('parameters', []))
    api.step(generator_task.get('name'), cmd)


def _should_run_test(api, test):
  """Whether the current test should run on this branch.

  The current test should run when the `test_if` matches the test branch, for both presubmit
  and postsubmit.
  """
  # Presubmit builds have git_ref property, whereas `api.buildbucket.gitiles_commit.ref` is None:
  #  1) Main branch
  #    * git_ref: "refs/pull/51183/head"
  #    * git_branch: "main"
  #  2) Release branch
  #    * git_ref: "refs/pull/144592/head"
  #    * git_branch: "flutter-3.20-candidate.17"
  if api.properties.get('git_ref', None):
    branch = api.properties.get('git_branch')
  else:
    # Postsubmit builds do not have git_ref property, but have `api.buildbucket.gitiles_commit.ref` defined:
    #  1) Main branch
    #    * api.buildbucket.gitiles_commit.ref: "refs/heads/main"
    #  2) Release branch
    #    * api.buildbucket.gitiles_commit.ref: "refs/heads/flutter-3.20-candidate.17"
    branch = api.buildbucket.gitiles_commit.ref
  test_if = test.get('test_if', '')
  regex = re.compile(f'.*{test_if}')
  return regex.match(branch)


def run_tests(api, tests, checkout, env, env_prefixes):
  """Runs sub-build tests."""
  # Run local tests in the builder to optimize resource usage.
  for test in tests:
    if not _should_run_test(api, test):
      continue
    # Copy and expand env, env_prefixes. This is required to
    # add configuration env variables.
    test_deps = test.get('test_dependencies', [])
    api.flutter_deps.required_deps(env, env_prefixes, test_deps)
    tmp_env = copy.deepcopy(env)
    tmp_env.update(test.get('env', {}))
    # Run tests within a exitStack context
    with contextlib.ExitStack() as exit_stack:
      api.flutter_deps.enter_contexts(
          exit_stack, test.get('contexts', []), tmp_env, env_prefixes
      )
      command = [test.get('language')] if test.get('language') else []
      # Ideally local tests should be completely hermetic and in theory we can run
      # them in parallel using futures. I haven't found a flutter engine
      # configuration with more than one local test but once we find it we
      # should run the list of tests using parallelism.
      # TODO(godofredoc): Optimize to run multiple local tests in parallel.
      command.append(checkout / test.get('script'))
      command.extend(test.get('parameters', []))
      step_name = api.test_utils.test_step_name(test.get('name'))
      test_timeout_secs = test.get(
          'test_timeout_secs', DEFAULT_TEST_TIMEOUT_SECS
      )

      # pylint: disable=cell-var-from-loop
      def run_test():
        # Replace MAGIC_ENVS
        updated_command = api.os_utils.replace_magic_envs(command, tmp_env)
        return api.step(step_name, updated_command, timeout=test_timeout_secs)

      # Rerun test step 3 times by default if failing.
      # TODO(keyonghan): notify tree gardener for test failures/flakes:
      # https://github.com/flutter/flutter/issues/89308
      api.logs_util.initialize_logs_collection(tmp_env)
      try:
        # Run within another context to make the logs env variable available to
        # test scripts.
        with api.context(env=tmp_env, env_prefixes=env_prefixes):
          api.retry.wrap(
              run_test,
              max_attempts=test.get('max_attempts', 3),
              step_name=step_name
          )
      finally:
        api.logs_util.upload_logs(test.get('name'))


def Build(api, checkout, env, env_prefixes, outputs, build):
  """Builds a flavor identified as a set of gn and ninja configs."""
  # Mock data for tests. This is required for the archive api to expand the directory to full path
  # of files.
  api.path.mock_add_directory(
      api.path.cache_dir /
      'builder/src/out/android_jit_release_x86/zip_archives/download.flutter.io'
  )

  ninja_tool = {
      "ninja": api.build_util.build,
  }
  deps = build.get('dependencies', [])
  api.flutter_deps.required_deps(env, env_prefixes, deps)
  api.flutter_bcid.report_stage('compile')
  gn = build.get('gn')

  # If prod apply prod gn overrides.
  if api.flutter_bcid.is_prod_build():
    gn = build.get('postsubmit_overrides', {}).get('gn', gn)

  if gn:
    with api.context(env=env, env_prefixes=env_prefixes):
      gn = list(gn)
      if api.flutter_bcid.is_official_build():
        # Goma/RBE is not supported for official builds.
        gn.append('--no-goma')
        gn.append('--no-rbe')
      if api.monorepo.is_monorepo_ci_build:
        version = env['REVISION']
        gn.append(f'--gn-args=engine_version="{version}"')
      if api.monorepo.is_monorepo_try_build:
        version = api.monorepo.build_identifier
        gn.append(f'--gn-args=engine_version="{version}"')
      rbe_working_path = api.path.mkdtemp(prefix="rbe")
      if '--rbe' in gn:
        api.rbe.prepare_rbe_gn(rbe_working_path, gn)
      api.build_util.run_gn(gn, checkout)
      ninja = build.get('ninja')
      ninja_tool[ninja.get('tool', 'ninja')](
          ninja.get('config'),
          checkout,
          ninja.get('targets', []),
          env,
          rbe_working_path=rbe_working_path
      )
  generator_tasks = build.get('generators', {}).get('tasks', [])
  pub_dirs = build.get('generators', {}).get('pub_dirs', [])
  archives = build.get('archives', [])
  # Get only local tests.
  tests = build.get('tests', [])
  with api.context(env=env, env_prefixes=env_prefixes,
                   cwd=checkout / 'flutter'), api.depot_tools.on_path():
    run_generators(api, pub_dirs, generator_tasks, checkout, env, env_prefixes)
    run_tests(api, tests, checkout, env, env_prefixes)
    api.flutter_bcid.report_stage('upload')
    for archive_config in archives:
      outputs[archive_config['name']] = Archive(api, checkout, archive_config)
    api.flutter_bcid.report_stage('upload-complete')
    # Allow time for the provenance to upload so it can be validated
    api.time.sleep(60)
    for archive_config in archives:
      if api.flutter_bcid.is_official_build():
        Verify(api, checkout, archive_config)
  # Archive full build. This is inefficient but necessary for global generators.
  if build.get('cas_archive', True):
    full_build_hash = api.shard_util.archive_full_build(
        checkout / 'out' / build.get('name'), build.get('name')
    )
    outputs['full_build'] = full_build_hash


def Archive(api, checkout, archive_config):
  paths = api.archives.engine_v2_gcs_paths(checkout, archive_config)
  # Sign artifacts if running on mac and a release candidate branch.
  is_release_branch = api.repo_util.is_release_candidate_branch(
      checkout / 'flutter'
  )
  if api.platform.is_mac and is_release_branch:
    signing_paths = [
        path.local
        for path in paths
        if api.signing.requires_signing(path.local)
    ]
    api.signing.code_sign(signing_paths)
  for path in paths:
    api.archives.upload_artifact(path.local, path.remote)
    api.flutter_bcid.upload_provenance(path.local, path.remote)


def Verify(api, checkout, archive_config):
  """Verifies a set of artifacts through BCID using artifact provenance."""

  paths = api.archives.engine_v2_gcs_paths(checkout, archive_config)

  for path in paths:
    gcs_path = path.remote
    gcs_path_without_prefix = str.lstrip(gcs_path, 'gs://')
    file = api.path.basename(gcs_path)
    bucket = gcs_path_without_prefix.split('/', maxsplit=1)[0]
    gcs_path_without_bucket = '/'.join(gcs_path_without_prefix.split('/')[1:])

    api.flutter_bcid.download_and_verify_provenance(
        file, bucket, gcs_path_without_bucket
    )


def RunSteps(api):
  # Collect memory/cpu/process before task execution.
  api.os_utils.collect_os_info()

  # If on macOS, reset Xcode in case a previous build failed to do so.
  api.osx_sdk.reset_xcode()

  api.flutter_bcid.report_stage('start')

  if api.repo_util.is_fusion() or api.monorepo.is_monorepo_ci_build or api.monorepo.is_monorepo_try_build:
    checkout = api.path.cache_dir / 'builder/engine/src'
  else:
    checkout = api.path.cache_dir / 'builder/src'
  api.file.rmtree('Clobber build output', checkout / 'out')

  cache_root = api.path.cache_dir / 'builder'
  api.file.ensure_directory('Ensure checkout cache', cache_root)

  with api.os_utils.make_temp_directory('standalone_repo') as temp_checkout:
    build = api.repo_util.get_build(temp_checkout)
  gclient_variables = build.get('gclient_variables', {})

  # Enable long path support on Windows.
  api.os_utils.enable_long_paths()

  api.flutter_bcid.report_stage('fetch')
  if api.monorepo.is_monorepo_ci_build or api.monorepo.is_monorepo_try_build:
    env, env_prefixes = api.repo_util.monorepo_environment(
        api.path.cache_dir / 'builder'
    )
    api.repo_util.monorepo_checkout(cache_root, env, env_prefixes)
  else:
    env, env_prefixes = api.repo_util.engine_environment(
        api.path.cache_dir / 'builder'
    )
    api.repo_util.engine_checkout(
        cache_root, env, env_prefixes, gclient_variables=gclient_variables
    )
  outputs = {}
  api.logs_util.initialize_logs_collection(env)
  try:
    with api.osx_sdk('ios'):
      Build(api, checkout, env, env_prefixes, outputs, build)
  finally:
    api.logs_util.upload_logs('builder', type='engine')
  output_props = api.step('Set output properties', None)
  output_props.presentation.properties['cas_output_hash'] = outputs

  # This is to clean up leaked processes.
  api.os_utils.kill_processes()
  # Collect memory/cpu/process after task execution.
  api.os_utils.collect_os_info()


def GenTests(api):
  build = {
      "archives": [{
          "name":
              "android_jit_release_x86",
          "type":
              "gcs",
          "realm":
              "production",
          "base_path":
              "out/android_jit_release_x86/zip_archives/",
          "include_paths": [
              "out/android_jit_release_x86/zip_archives/android-x86-jit-release/artifacts.zip",
              "out/android_jit_release_x86/zip_archives/download.flutter.io"
          ]
      }],
      "gn": ["--ios", "--rbe"],
      "name":
          "flutter/build",
      "ninja": {
          "config": "ios_debug",
          "targets": []
      },
      "generators": {
          "pub_dirs": ["dev"],
          "tasks": [{
              "name": "generator1",
              "scripts": ["script1.sh", "dev/felt.dart"],
              "parameters": ["--argument1"]
          }]
      },
      "tests": [{
          "name": "mytest",
          "script": "myscript.sh",
          "parameters": ["param1", "param2", '${FLUTTER_LOGS_DIR}'],
          "type": "local",
          "contexts": ["metric_center_token"]
      }]
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
      'config_file',
      api.properties(no_goma=True, config_name='abc'),
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
      'mac_main',
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
      'mac_release_candidate',
      api.properties(build=build, no_goma=True),
      api.platform('mac', 64),
      api.buildbucket.ci_build(
          project='flutter',
          bucket='prod',
          builder='mac-host',
          git_repo='https://flutter.googlesource.com/mirrors/engine',
          git_ref='refs/heads/flutter-3.17-candidate.0',
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
      api.properties(
          build=build, no_goma=True, try_build_identifier='81123491'
      ),
      api.monorepo.try_build(),
  )

  fake_bcid_response_success = '''
  {
    "allowed": true,
    "verificationSummary": "This artifact is definitely legitimate!"
  }
  '''
  build_custom = dict(build)
  build_custom["gclient_variables"] = {"example_custom_var": True}
  build_custom["tests"] = []
  artifacts_location = 'artifacts.zip'
  jar_location = 'x86_debug-1.0.0-0005149dca9b248663adcde4bdd7c6c915a76584.jar'
  pom_location = 'x86_debug-1.0.0-0005149dca9b248663adcde4bdd7c6c915a76584.pom'
  yield api.test(
      'dart-internal-flutter-success',
      api.properties(build=build, no_goma=True),
      api.buildbucket.ci_build(
          project='dart-internal',
          bucket='flutter',
          git_repo='https://flutter.googlesource.com/mirrors/engine',
          git_ref='refs/heads/main',
      ),
      api.step_data(
          'Verify {0} provenance.verify {0} provenance'
          .format(artifacts_location),
          stdout=api.raw_io.output_text(fake_bcid_response_success)
      ),
      api.step_data(
          'Verify {0} provenance.verify {0} provenance'.format(jar_location),
          stdout=api.raw_io.output_text(fake_bcid_response_success)
      ),
      api.step_data(
          'Verify {0} provenance.verify {0} provenance'.format(pom_location),
          stdout=api.raw_io.output_text(fake_bcid_response_success)
      ),
  )
  test_if_build = {
      "name":
          "flutter/build",
      "tests": [{
          "name": "mytest",
          "script": "myscript.sh",
          "parameters": ["param1", "param2", '${FLUTTER_LOGS_DIR}'],
          "type": "local",
          "contexts": ["metric_center_token"],
          "test_if": "main"
      }]
  }
  yield api.test(
      'test_if_skip_postsubmit',
      api.properties(build=test_if_build, no_goma=True),
      api.buildbucket.ci_build(
          project='flutter',
          bucket='prod',
          builder='linux-host',
          git_repo='https://flutter.googlesource.com/mirrors/engine',
          git_ref='refs/heads/flutter-3.17-candidate.0',
          revision='abcd' * 10,
          build_number=123,
      ),
  )
  yield api.test(
      'test_if_not_skip_postsubmit',
      api.properties(build=test_if_build, no_goma=True),
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
      'test_if_not_skip_presubmit',
      api.properties(
          build=test_if_build,
          no_goma=True,
          git_ref="refs/pull/51183/head",
          git_branch="main"
      ),
      api.buildbucket.ci_build(
          project='flutter',
          bucket='prod',
          builder='linux-host',
          git_repo='https://flutter.googlesource.com/mirrors/engine',
          revision='abcd' * 10,
          build_number=123,
      ),
  )
  yield api.test(
      'test_if_skip_presubmit',
      api.properties(
          build=test_if_build,
          no_goma=True,
          git_ref="refs/pull/51183/head",
          git_branch="flutter-3.17-candidate.0"
      ),
      api.buildbucket.ci_build(
          project='flutter',
          bucket='prod',
          builder='linux-host',
          git_repo='https://flutter.googlesource.com/mirrors/engine',
          revision='abcd' * 10,
          build_number=123,
      ),
  )
