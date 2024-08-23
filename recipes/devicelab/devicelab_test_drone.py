# Copyright 2020 The Chromium Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

from recipe_engine.recipe_api import Property

PYTHON_VERSION_COMPATIBILITY = 'PY3'

DEPS = [
    'depot_tools/gsutil',
    'flutter/flutter_deps',
    'flutter/logs_util',
    'flutter/os_utils',
    'flutter/osx_sdk',
    'flutter/repo_util',
    'flutter/retry',
    'flutter/shard_util',
    'flutter/test_utils',
    'flutter/token_util',
    'fuchsia/git',
    'recipe_engine/buildbucket',
    'recipe_engine/cas',
    'recipe_engine/context',
    'recipe_engine/json',
    'recipe_engine/path',
    'recipe_engine/platform',
    'recipe_engine/properties',
    'recipe_engine/raw_io',
    'recipe_engine/runtime',
    'recipe_engine/step',
    'recipe_engine/swarming',
]

# Fifteen minutes
MAX_TIMEOUT_SECS = 30 * 60
# GCS bucket for flutter devicelab build app artifacts.
DEVICELAB_BUCKET = 'flutter_devicelab'


def RunSteps(api):
  # Collect memory/cpu/process before task execution.
  api.os_utils.collect_os_info()

  # If on macOS, reset Xcode in case a previous build failed to do so.
  api.osx_sdk.reset_xcode()

  task_name = api.properties.get("task_name")
  if not task_name:
    raise ValueError('A task_name property is required')

  # Artifact needs pre-built before running the test.
  artifact = api.properties.get('artifact', None)
  if not artifact:
    raise ValueError('An artifact property is required')

  flutter_path = api.path.mkdtemp().join('flutter sdk')
  api.repo_util.checkout(
      'flutter',
      flutter_path,
      api.properties.get('git_url'),
      api.properties.get('git_ref'),
  )
  with api.context(cwd=flutter_path):
    commit_time = api.git(
        'git commit time',
        'log',
        '--pretty=format:%ct',
        '-n',
        '1',
        stdout=api.raw_io.output_text()
    ).stdout.rstrip()
  env, env_prefixes = api.repo_util.flutter_environment(flutter_path)
  api.logs_util.initialize_logs_collection(env)
  with api.step.nest('Dependencies'):
    api.flutter_deps.flutter_engine(env, env_prefixes)
    deps = api.properties.get('dependencies', [])
    # TODO: If deps contains dart_sdk and we are running a local engine,
    # we don't want to fetch it with cipd, so don't fetch it with required_deps
    api.flutter_deps.required_deps(env, env_prefixes, deps)

  target_tags = api.properties.get('tags', [])
  device_tags = api.test_utils.collect_benchmark_tags(
      env, env_prefixes, target_tags
  )
  benchmark_tags = api.json.dumps(device_tags)

  devicelab_path = flutter_path.join('dev', 'devicelab')
  git_branch = api.properties.get('git_branch')
  # Create tmp file to store results in
  results_path = api.path.mkdtemp(prefix='results').join('results')
  # Run test
  parent_builder = api.properties.get('parent_builder')
  # Quote builder name if running on windows.
  parent_builder = f'\"{parent_builder}\"' if api.platform.is_win else parent_builder
  runner_params = [
      '-t', task_name, '--results-file', results_path, '--luci-builder',
      parent_builder
  ]
  # Downloads artifact
  artifact_destination_dir = api.path.mkdtemp()
  download_artifact(api, artifact, artifact_destination_dir)
  # Test taskArgs
  artifact_path = artifact_destination_dir.join(artifact)
  runner_params.extend([
      '--task-args', 'test', '--task-args',
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
  test_status = ''
  with api.context(env=env, env_prefixes=env_prefixes, cwd=devicelab_path):
    api.retry.run_flutter_doctor()
    api.step('dart pub get', ['dart', 'pub', 'get'], infra_step=True)
    if not api.properties.get('$flutter/osx_sdk'):
      with api.context(env=env, env_prefixes=env_prefixes):
        run_test(api, task_name, runner_params)
    else:
      api.os_utils.clean_derived_data()
      if str(api.swarming.bot_id).startswith('flutter-devicelab'):
        with api.osx_sdk('ios', devicelab=True):
          with api.context(env=env, env_prefixes=env_prefixes):
            # Next steps get executed only if running in mac.
            api.os_utils.prepare_ios_device()
            api.os_utils.shutdown_simulators()
            api.os_utils.ios_debug_symbol_doctor()
            run_test(api, task_name, runner_params)

  with api.context(env=env, env_prefixes=env_prefixes, cwd=devicelab_path):
    uploadResults(
        api, env, env_prefixes, results_path, test_status == 'flaky',
        git_branch, parent_builder, commit_time, task_name, benchmark_tags
    )
    uploadMetricsToCas(api, results_path)


def run_test(api, task_name, runner_params):
  '''Run the devicelab test.'''
  api.retry.run_flutter_doctor()
  test_runner_command = ['dart', 'bin/test_runner.dart', 'test']
  test_runner_command.extend(runner_params)
  test_status = ''
  try:
    test_status = api.test_utils.run_test(
        'run %s' % task_name,
        test_runner_command,
        timeout_secs=MAX_TIMEOUT_SECS
    )
  finally:
    debug_after_failure(api, task_name)


def download_artifact(api, artifact, artifact_destination_dir):
  '''Download pre-build artifact.'''
  commit_sha = api.repo_util.get_env_ref()
  artifact_gcs_dir = 'flutter/%s/%s' % (
      api.shard_util.get_base_bucket_name(), commit_sha
  )
  artifact_gcs_path = '%s/%s' % (artifact_gcs_dir, artifact)
  api.gsutil.download(
      DEVICELAB_BUCKET,
      artifact_gcs_path,
      artifact_destination_dir,
      args=['-r'],
      name="download artifact"
  )


def debug_after_failure(api, task_name):
  """Upload logs and collect OS debug info."""
  api.logs_util.upload_logs(task_name)
  # This is to clean up leaked processes.
  api.os_utils.kill_processes()
  # Collect memory/cpu/process after task execution.
  api.os_utils.collect_os_info()


def shouldNotUpdate(api, git_branch):
  """Check if a post submit builder should update results to cocoon/skia perf.

  Test results will be sent to cocoon/skia perf only when test is post-submit and test is from
  supported branches.
  """
  supported_branches = ['master']
  if api.runtime.is_experimental or api.properties.get(
      'git_url') or git_branch not in supported_branches:
    return True
  else:
    return False


def uploadResults(
    api,
    env,
    env_prefixes,
    results_path,
    is_test_flaky,
    git_branch,
    builder_name,
    commit_time,
    task_name,
    benchmark_tags,
    test_status='Succeeded',
):
  """Upload DeviceLab test results to Cocoon/skia perf.

  luci-auth only gurantees a service account token life of 3 minutes. To work
  around this limitation, results uploading is separate from the the test run.

  Only post-submit tests upload results to Cocoon/skia perf.

  If `upload_metrics: true`, generated test metrics will be uploaded to skia perf
  for both prod and staging tests.

  Otherwise, test status will be updated in Cocoon for tests running in prod pool,
  and staging tests without `upload_metrics: true` will not be updated.

  Args:
    env(dict): Current environment variables.
    env_prefixes(dict):  Current environment prefixes variables.
    results_path(str): Path to test results.
    is_test_flaky(bool): Flaky flag for the test running step.
    git_branch(str): Branch the test runs against.
    builder_name(str): The builder name that is being run on.
    commit_time(str): The commit time in UNIX timestamp.
    task_name(str): The task name of the current test.
    benchmark_tags(str): Json dumped str of benchmark tags, which includes host and device info.
    test_status(str): The status of the test running step.
  """
  if shouldNotUpdate(api, git_branch):
    return
  bucket = api.shard_util.get_base_bucket_name()
  runner_params = ['--test-flaky', is_test_flaky, '--builder-bucket', bucket]
  if api.properties.get('upload_metrics'):
    runner_params.extend([
        '--results-file', results_path, '--commit-time', commit_time,
        '--task-name', task_name, '--benchmark-tags', benchmark_tags
    ])
  else:
    # For builders without `upload_metrics: true`
    #  - prod ones need to update test status, to be reflected on go/flutter-build
    #  - staging ones do not need to as we are not tracking staging tests in cocoon datastore.
    if bucket == 'staging':
      return
    else:
      runner_params.extend([
          '--git-branch', git_branch, '--luci-builder', builder_name,
          '--test-status', test_status
      ])

  with api.step.nest('Upload metrics'):
    with api.token_util.metric_center_token(env, env_prefixes):
      runner_params.extend([
          '--service-account-token-file',
          api.token_util.cocoon_token()
      ])
      upload_command = ['dart', 'bin/test_runner.dart', 'upload-metrics']
      upload_command.extend(runner_params)
      with api.context(env=env, env_prefixes=env_prefixes):
        api.step('upload results', upload_command, infra_step=True)


def uploadMetricsToCas(api, results_path):
  """Upload DeviceLab test performance metrics to CAS.

  The hash of the CAS (content-addressed storage) upload is added as an
  output property to the build.
  """
  if not api.properties.get('upload_metrics_to_cas'):
    return
  cas_hash = api.cas.archive(
      'Upload metrics to CAS', api.path.dirname(results_path), results_path
  )
  api.step.active_result.presentation.properties['results_cas_hash'] = cas_hash


def GenTests(api):
  checkout_path = api.path.cleanup_dir.join('tmp_tmp_1', 'flutter sdk')
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
      "artifact-exists",
      api.properties(
          buildername='Linux abc',
          task_name='abc',
          git_branch='master',
          artifact='def',
          fake_data='fake data',
          git_ref='refs/pull/1/head',
          parent_builder='ghi',
      ),
      api.repo_util.flutter_environment_data(checkout_dir=checkout_path),
  )
  yield api.test(
      "basic",
      api.properties(
          buildername='Linux abc',
          task_name='abc',
          git_branch='master',
          fake_data='#flaky\nthis is a flaky\nflaky: true',
          artifact='def',
          upload_metrics=True,
          upload_metrics_to_cas=True,
          parent_builder='ghi',
      ),
      api.repo_util.flutter_environment_data(checkout_dir=checkout_path),
      api.buildbucket.ci_build(
          project='test',
          git_repo='git.example.com/test/repo',
      ),
  )
  yield api.test(
      "experimental",
      api.properties(
          buildername='Linux abc',
          task_name='abc',
          git_branch='master',
          artifact='def',
          fake_data='#flaky\nthis is a flaky\nflaky: true',
          parent_builder='ghi',
      ),
      api.repo_util.flutter_environment_data(checkout_dir=checkout_path),
      api.buildbucket.ci_build(
          project='test',
          git_repo='git.example.com/test/repo',
      ),
      api.runtime(is_experimental=True),
  )
  yield api.test(
      "no-upload-metrics-linux-staging",
      api.properties(
          buildername='Linux abc',
          task_name='abc',
          fake_data='fake data',
          artifact='def',
          upload_metrics_to_cas=True,
          git_branch='master',
          parent_builder='ghi',
      ), api.repo_util.flutter_environment_data(checkout_dir=checkout_path),
      api.buildbucket.ci_build(
          git_ref='refs/heads/master',
          bucket='staging',
      )
  )
  yield api.test(
      "local-engine",
      api.properties(
          buildername='Linux abc',
          task_name='abc',
          local_engine_cas_hash='isolatehashlocalengine/22',
          local_engine='android-release',
          local_engine_host='host-release',
          git_branch='master',
          fake_data='fake data',
          artifact='def',
          parent_builder='ghi',
      ), api.repo_util.flutter_environment_data(checkout_dir=checkout_path),
      api.buildbucket.ci_build(
          project='test',
          git_repo='git.example.com/test/repo',
          git_ref='refs/heads/master',
      )
  )
  yield api.test(
      "mac",
      api.properties(
          buildername='Mac_ios abc',
          task_name='abc',
          tags=['ios'],
          git_branch='master',
          **{'$flutter/osx_sdk': {'sdk_version': 'deadbeef',}},
          artifact='def',
          fake_data='#flaky\nthis is a flaky\nflaky: true',
          parent_builder='ghi'
      ), api.repo_util.flutter_environment_data(checkout_dir=checkout_path),
      api.platform.name('mac'),
      api.buildbucket.ci_build(git_ref='refs/heads/master',),
      api.swarming.properties(bot_id='flutter-devicelab-mac-1'),
      api.step_data(
          'Find device type',
          stdout=api.raw_io.output_text('iPhone8,1'),
      )
  )
