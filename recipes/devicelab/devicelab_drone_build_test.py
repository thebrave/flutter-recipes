# Copyright 2020 The Chromium Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

PYTHON_VERSION_COMPATIBILITY = 'PY3'

DEPS = [
    'depot_tools/gsutil',
    'flutter/devicelab_osx_sdk',
    'flutter/display_util',
    'flutter/flutter_deps',
    'flutter/logs_util',
    'flutter/os_utils',
    'flutter/osx_sdk',
    'flutter/repo_util',
    'flutter/retry',
    'flutter/shard_util',
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

  api.os_utils.print_pub_certs()
  task_name = api.properties.get("task_name")
  if not task_name:
    raise ValueError('A task_name property is required')

  commit_sha = api.repo_util.get_env_commit()
  artifact = api.properties.get('artifact', None)
  if not artifact:
    raise ValueError('An artifact property is required')
  artifact_gcs_dir = 'flutter/%s' % commit_sha
  artifact_gcs_path = '%s/%s' % (artifact_gcs_dir, artifact)
  artifact_exist = check_artifact_exist(
      api, 'gs://%s/%s' % (DEVICELAB_BUCKET, artifact_gcs_path)
  )
  # Run build step.
  if not artifact_exist:
    build(api, task_name, artifact, artifact_gcs_dir)

  # Run test step.
  builds = test(
      api, task_name, api.properties.get('dependencies', []), artifact
  )
  builds = api.shard_util.collect_builds(builds)
  api.display_util.display_builds(
      step_name='display builds',
      builds=builds,
      raise_on_failure=True,
  )


def test(api, task_name, deps, artifact):
  '''Run devicelab test assuming build artifact is available.'''
  git_branch = api.properties.get('git_branch')
  reqs = []
  # These are dependencies specified in the yaml file. We want to pass them down
  # to test so they also install these dependencies.
  test_props = {
      'dependencies': [api.shard_util_v2.unfreeze_dict(dep) for dep in deps],
      'task_name': task_name,
      'artifact': artifact,
  }

  req = api.buildbucket.schedule_request(
      swarming_parent_run_id=api.swarming.task_id,
      builder='Linux Devicelab Test Drone',
      properties=test_props,
      priority=25,
      exe_cipd_version=api.properties.get(
          'exe_cipd_version', 'refs/heads/%s' % git_branch
      )
  )
  reqs.append(req)
  return api.buildbucket.schedule(reqs)


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
  # LUCI git checkouts end up in a detached HEAD state, so branch must
  # be passed from gitiles -> test runner -> Cocoon.
  if git_branch and api.properties.get('git_url') is None:
    # git_branch is set only when the build was triggered on post-submit.
    runner_params.extend(['--git-branch', git_branch])
  with api.context(env=env, env_prefixes=env_prefixes, cwd=devicelab_path):
    api.repo_util.run_flutter_doctor()
    api.step('dart pub get', ['dart', 'pub', 'get'], infra_step=True)
    dep_list = {d['dependency']: d.get('version') for d in deps}
    if 'xcode' not in dep_list:
      with api.context(env=env, env_prefixes=env_prefixes):
        api.repo_util.run_flutter_doctor()
        test_runner_command = ['dart', 'bin/test_runner.dart', 'test']
        test_runner_command.extend(runner_params)
        try:
          api.test_utils.run_test(
              'build %s' % task_name,
              test_runner_command,
              timeout_secs=MAX_TIMEOUT_SECS
          )
          api.gsutil.upload(
              bucket='flutter_devicelab',
              source=artifact_dir,
              dest=artifact_gcs_dir,
              link_name='artifacts',
              args=['-r'],
              multithreaded=True,
              name='upload artifacts',
              unauthenticated_url=True
          )
        finally:
          debug_after_failure(api, task_name)


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
      "no-artifact-name",
      api.properties(
          buildername='Linux abc', task_name='abc', git_ref='refs/pull/1/head'
      ),
      api.expect_exception('ValueError'),
  )
  yield api.test(
      "artifact exists",
      api.properties(
          buildername='Linux abc',
          task_name='abc',
          git_branch='master',
          artifact='def',
          git_ref='refs/pull/1/head'
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
          task_name='abc',
          artifact='def',
          local_engine_cas_hash='isolatehashlocalengine/22',
          local_engine='host-release',
          git_branch='master',
      ), api.repo_util.flutter_environment_data(checkout_dir=checkout_path),
      api.buildbucket.ci_build(
          project='test',
          git_repo='git.example.com/test/repo',
          git_ref='refs/heads/master',
      )
  )
