# Copyright 2020 The Chromium Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

PYTHON_VERSION_COMPATIBILITY = 'PY3'

DEPS = [
    'depot_tools/gsutil',
    'flutter/display_util',
    'flutter/flutter_deps',
    'flutter/logs_util',
    'flutter/os_utils',
    'flutter/osx_sdk',
    'flutter/repo_util',
    'flutter/retry',
    'flutter/shard_util_v2',
    'flutter/test_utils',
    'flutter/token_util',
    'fuchsia/git',
    'recipe_engine/buildbucket',
    'recipe_engine/cas',
    'recipe_engine/context',
    'recipe_engine/file',
    'recipe_engine/json',
    'recipe_engine/path',
    'recipe_engine/platform',
    'recipe_engine/properties',
    'recipe_engine/raw_io',
    'recipe_engine/runtime',
    'recipe_engine/step',
    'recipe_engine/swarming',
]

# Thirty minutes
MAX_TIMEOUT_SECS = 30 * 60
# GCS bucket for flutter devicelab build app artifacts.
DEVICELAB_BUCKET = 'flutter_devicelab'


def check_artifact_exist(api, url):
  '''Checks if the build artifact already exists in the bucket.'''
  artifacts_exist = None
  step_result = api.gsutil.list(
      url, stdout=api.raw_io.output_text(), ok_ret='any'
  ).stdout.rstrip()
  if step_result:
    artifacts_exist = True
  else:
    artifacts_exist = False
  return artifacts_exist


def RunSteps(api):
  # Collect memory/cpu/process before task execution.
  api.os_utils.collect_os_info()

  # If on macOS, reset Xcode in case a previous build failed to do so.
  api.osx_sdk.reset_xcode()

  api.os_utils.print_pub_certs()
  task_name = api.properties.get("task_name")
  if not task_name:
    raise ValueError('A task_name property is required')

  commit_sha = api.repo_util.get_env_ref()
  artifact = api.properties.get('artifact', task_name)
  bucket = api.buildbucket.build.builder.bucket
  artifact_gcs_dir = 'flutter/%s/%s' % (bucket, commit_sha)
  artifact_gcs_path = '%s/%s' % (artifact_gcs_dir, artifact)
  artifact_exist = check_artifact_exist(
      api, 'gs://%s/%s' % (DEVICELAB_BUCKET, artifact_gcs_path)
  )
  # Run build step.
  if not artifact_exist:
    build(api, task_name, artifact, artifact_gcs_path)

  # Run test step.
  targets = test(
      api, task_name, api.properties.get('dependencies', []), artifact
  )
  with api.step.nest('launch builds') as presentation:
    tasks = api.shard_util_v2.schedule(targets, presentation)
  with api.step.nest('collect builds') as presentation:
    build_results = api.shard_util_v2.collect(tasks)
    api.display_util.display_subbuilds(
        step_name='display builds',
        subbuilds=build_results,
        raise_on_failure=True,
    )


def test(api, task_name, deps, artifact):
  '''Run devicelab test assuming build artifact is available.'''
  reqs = []
  # Updates tuple to buildbucket API supported list.
  tags = [tag for tag in api.properties.get('tags', [])]
  # These are dependencies specified in the yaml file. We want to pass them down
  # to test so they also install these dependencies.
  test_props = {
      'dependencies': [api.shard_util_v2.unfreeze_dict(dep) for dep in deps],
      'task_name':
          task_name,
      'parent_builder':
          api.properties.get('buildername'),
      'artifact':
          artifact,
      'git_branch':
          api.properties.get('git_branch'),
      'tags':
          tags,
      '$flutter/osx_sdk':
          api.shard_util_v2.unfreeze_dict(
              api.properties.get('$flutter/osx_sdk', {})
          ),
  }
  reqs.append({
      'name': task_name, 'properties': test_props,
      'drone_dimensions': api.properties.get('drone_dimensions', []),
      'recipe': 'devicelab/devicelab_test_drone'
  })
  return reqs


def build(api, task_name, artifact, artifact_gcs_dir):
  '''Run devicelab build to collect the artifact.'''
  flutter_path = api.path.mkdtemp().join('flutter sdk')
  api.repo_util.checkout(
      'flutter',
      flutter_path,
      api.properties.get('git_url'),
      api.properties.get('git_ref'),
  )

  env, env_prefixes = api.repo_util.flutter_environment(flutter_path)
  with api.step.nest('Dependencies'):
    api.flutter_deps.flutter_engine(env, env_prefixes)
    deps = api.properties.get('dependencies', [])
    # TODO: If deps contains dart_sdk and we are running a local engine,
    # we don't want to fetch it with cipd, so don't fetch it with required_deps
    api.flutter_deps.required_deps(env, env_prefixes, deps)

  devicelab_path = flutter_path.join('dev', 'devicelab')
  git_branch = api.properties.get('git_branch')

  # Run test
  runner_params = [
      '-t', task_name, '--luci-builder',
      api.properties.get('buildername')
  ]
  # Build taskArgs

  artifact_dir = api.path.mkdtemp()
  api.file.ensure_directory('mkdir %s' % artifact, artifact_dir.join(artifact))
  artifact_path = artifact_dir.join(artifact)
  runner_params.extend([
      '--task-args', 'build', '--task-args',
      'application-binary-path=%s' % artifact_path
  ])
  if 'LOCAL_ENGINE' in env:
    runner_params.extend(['--local-engine', env['LOCAL_ENGINE']])
  if 'LOCAL_ENGINE_HOST' in env:
    runner_params.extend(['--local-engine-host', env['LOCAL_ENGINE_HOST']])
  # LUCI git checkouts end up in a detached HEAD state, so branch must
  # be passed from gitiles -> test runner -> Cocoon.
  if git_branch and api.properties.get('git_url') is None:
    # git_branch is set only when the build was triggered on post-submit.
    runner_params.extend(['--git-branch', git_branch])
  with api.context(env=env, env_prefixes=env_prefixes, cwd=devicelab_path):
    api.retry.run_flutter_doctor()
    api.step('dart pub get', ['dart', 'pub', 'get'], infra_step=True)
    deps = api.properties.get('dependencies', [])
    with api.context(env=env, env_prefixes=env_prefixes):
      api.step('dart pub get', ['dart', 'pub', 'get'], infra_step=True)
      if api.properties.get('$flutter/osx_sdk'):
        with api.osx_sdk('ios'):
          with api.context(env=env, env_prefixes=env_prefixes):
            test_runner_command = ['dart', 'bin/test_runner.dart', 'test']
            test_runner_command.extend(runner_params)
            try:
              api.test_utils.run_test(
                  'build %s' % task_name,
                  test_runner_command,
                  timeout_secs=MAX_TIMEOUT_SECS
              )
            finally:
              debug_after_failure(api, task_name)
      else:
        test_runner_command = ['dart', 'bin/test_runner.dart', 'test']
        test_runner_command.extend(runner_params)
        try:
          api.test_utils.run_test(
              'build %s' % task_name,
              test_runner_command,
              timeout_secs=MAX_TIMEOUT_SECS
          )
        finally:
          debug_after_failure(api, task_name)
      api.gsutil.upload(
          bucket='flutter_devicelab',
          source='%s/*' % artifact_dir,
          dest=artifact_gcs_dir,
          link_name='artifacts',
          args=['-r'],
          multithreaded=True,
          name='upload artifacts',
          unauthenticated_url=True
      )


def debug_after_failure(api, task_name):
  """Collect OS debug info."""
  api.os_utils.kill_processes()
  # Collect memory/cpu/process after task execution.
  api.os_utils.collect_os_info()


def GenTests(api):
  checkout_path = api.path['cleanup'].join('tmp_tmp_1', 'flutter sdk')
  yield api.test(
      "no-task-name",
      api.expect_exception('ValueError'),
  )
  yield api.test(
      "artifact exists",
      api.properties(
          buildername='Linux abc',
          drone_dimensions=['os=Linux'],
          task_name='abc',
          git_branch='master',
          fake_data='fake data',
          artifact='def',
          git_ref='refs/pull/1/head',
          git_url='test/repo'
      ),
      api.repo_util.flutter_environment_data(checkout_dir=checkout_path),
      api.step_data(
          'gsutil list',
          stdout=api.raw_io
          .output_text('gs://flutter_devicelab/flutter/refs/pull/1/head/def')
      ),
  )
  yield api.test(
      "artifact does not exist",
      api.properties(
          buildername='Linux abc',
          drone_dimensions=['os=Linux'],
          fake_data='fake data',
          task_name='abc',
          git_branch='master',
          artifact='def',
          git_ref='refs/pull/1/head'
      ),
      api.repo_util.flutter_environment_data(checkout_dir=checkout_path),
      api.buildbucket.ci_build(
          project='test',
          git_repo='git.example.com/test/repo',
      ),
  )
  yield api.test(
      "local-engine",
      api.properties(
          buildername='Linux abc',
          drone_dimensions=['os=Linux'],
          task_name='abc',
          rtifact='def',
          local_engine_cas_hash='isolatehashlocalengine/22',
          local_engine='android-release',
          local_engine_host='host-release',
          git_branch='master',
          fake_data='fake data',
      ), api.repo_util.flutter_environment_data(checkout_dir=checkout_path),
      api.buildbucket.ci_build(
          project='test',
          git_repo='git.example.com/test/repo',
          git_ref='refs/heads/master',
      )
  )
  yield api.test(
      "xcode-mac",
      api.properties(
          buildername='Mac_ios abc',
          drone_dimensions=['os=Mac'],
          task_name='abc',
          tags=['ios'],
          git_branch='master',
          fake_data='fake data',
          **{'$flutter/osx_sdk': {'sdk_version': 'deadbeef',}}
      ), api.repo_util.flutter_environment_data(checkout_dir=checkout_path),
      api.platform.name('mac'),
      api.buildbucket.ci_build(git_ref='refs/heads/master',)
  )
