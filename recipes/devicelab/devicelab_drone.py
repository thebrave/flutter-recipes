# Copyright 2020 The Chromium Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

from recipe_engine.recipe_api import Property


PYTHON_VERSION_COMPATIBILITY = 'PY3'

DEPS = [
    'flutter/devicelab_osx_sdk',
    'flutter/flutter_deps',
    'flutter/logs_util',
    'flutter/os_utils',
    'flutter/osx_sdk',
    'flutter/repo_util',
    'flutter/retry',
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

# Any builder in this list will have logs suppressed.
SUPPRESS_LOG_BUILDER_LIST = ['Linux abc']

def RunSteps(api):
  # Collect memory/cpu/process before task execution.
  api.os_utils.collect_os_info()

  task_name = api.properties.get("task_name")
  if not task_name:
    raise ValueError('A task_name property is required')

  api.os_utils.print_pub_certs()

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

  builder_name = api.properties.get('buildername')
  suppress_log = builder_name in SUPPRESS_LOG_BUILDER_LIST

  if not suppress_log:
    api.logs_util.initialize_logs_collection(env)
  with api.step.nest('Dependencies'):
    api.flutter_deps.flutter_engine(env, env_prefixes)
    deps = api.properties.get('dependencies', [])
    # TODO: If deps contains dart_sdk and we are running a local engine,
    # we don't want to fetch it with cipd, so don't fetch it with required_deps
    api.flutter_deps.required_deps(env, env_prefixes, deps)
    api.flutter_deps.vpython(env, env_prefixes, 'latest')

  target_tags = api.properties.get('tags', [])
  device_tags = api.test_utils.collect_benchmark_tags(env, env_prefixes, target_tags)
  benchmark_tags = api.json.dumps(device_tags)

  devicelab_path = flutter_path.join('dev', 'devicelab')
  git_branch = api.properties.get('git_branch')
  # Create tmp file to store results in
  results_path = api.path.mkdtemp(prefix='results').join('results')
  # Run test
  runner_params = [
      '-t', task_name, '--results-file', results_path, '--luci-builder',
      builder_name
  ]
  if 'LOCAL_ENGINE' in env:
    runner_params.extend(['--local-engine', env['LOCAL_ENGINE']])
  # LUCI git checkouts end up in a detached HEAD state, so branch must
  # be passed from gitiles -> test runner -> Cocoon.
  if git_branch and api.properties.get('git_url') is None:
    # git_branch is set only when the build was triggered on post-submit.
    runner_params.extend(['--git-branch', git_branch])
  test_status = ''
  with api.context(env=env, env_prefixes=env_prefixes, cwd=devicelab_path):
    api.retry.step(
        'flutter doctor',
        ['flutter', 'doctor'],
        max_attempts=3,
        timeout=300,
    )
    api.step('dart pub get', ['dart', 'pub', 'get'], infra_step=True)
    dep_list = {d['dependency']: d.get('version') for d in deps}
    if 'xcode' in dep_list:
      api.os_utils.clean_derived_data()
      if str(api.swarming.bot_id).startswith('flutter-devicelab'):
        with api.devicelab_osx_sdk('ios'):
          test_status = mac_test(
              api, env, env_prefixes, flutter_path, task_name, runner_params, suppress_log
          )
      else:
        with api.osx_sdk('ios'):
          test_status = mac_test(
              api, env, env_prefixes, flutter_path, task_name, runner_params, suppress_log
          )
    else:
      with api.context(env=env, env_prefixes=env_prefixes):
        api.retry.step(
            'flutter doctor',
            ['flutter', 'doctor', '--verbose'],
            max_attempts=3,
            timeout=300,
        )
        test_runner_command = ['dart', 'bin/test_runner.dart', 'test']
        test_runner_command.extend(runner_params)
        try:
          test_status = api.test_utils.run_test(
              'run %s' % task_name,
              test_runner_command,
              timeout_secs=MAX_TIMEOUT_SECS,
              suppress_log=suppress_log,
          )
        finally:
          if not suppress_log:
            debug_after_failure(api, task_name)
        if test_status == 'flaky':
          api.test_utils.flaky_step('run %s' % task_name)
  with api.context(env=env, env_prefixes=env_prefixes, cwd=devicelab_path):
    uploadResults(
        api, env, env_prefixes, results_path, test_status == 'flaky',
        git_branch, api.properties.get('buildername'), commit_time, task_name,
        benchmark_tags, suppress_log=suppress_log
    )
    uploadMetricsToCas(api, results_path)


def debug_after_failure(api, task_name):
  """Upload logs and collect OS debug info."""
  api.logs_util.upload_logs(task_name)
  # This is to clean up leaked processes.
  api.os_utils.kill_processes()
  # Collect memory/cpu/process after task execution.
  api.os_utils.collect_os_info()


def mac_test(api, env, env_prefixes, flutter_path, task_name, runner_params, suppress_log):
  """Runs a devicelab mac test."""
  api.flutter_deps.gems(
      env, env_prefixes, flutter_path.join('dev', 'ci', 'mac')
  )
  api.retry.step(
      'flutter doctor', ['flutter', 'doctor', '--verbose'],
      max_attempts=3,
      timeout=300
  )
  api.os_utils.dismiss_dialogs()
  api.os_utils.shutdown_simulators()
  with api.context(env=env, env_prefixes=env_prefixes):
    resource_name = api.resource('runner.sh')
    api.step('Set execute permission', ['chmod', '755', resource_name])
    test_runner_command = [resource_name]
    test_runner_command.extend(runner_params)
    try:
      test_status = api.test_utils.run_test(
          'run %s' % task_name,
          test_runner_command,
          timeout_secs=MAX_TIMEOUT_SECS,
          suppress_log=suppress_log,
      )
    finally:
      debug_after_failure(api, task_name)
    if test_status == 'flaky':
      api.test_utils.flaky_step('run %s' % task_name)
  return test_status


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
    suppress_log=False,
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
    suppress_log(bool): Flag whether test logs are suppressed.
  """
  if shouldNotUpdate(api, git_branch):
    return
  bucket = api.buildbucket.build.builder.bucket
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
    env['TOKEN_PATH'] = api.token_util.metric_center_token()
    env['GCP_PROJECT'] = 'flutter-infra'
    runner_params.extend([
        '--service-account-token-file',
        api.token_util.cocoon_token()
    ])
    upload_command = ['dart', 'bin/test_runner.dart', 'upload-metrics']
    upload_command.extend(runner_params)
    with api.context(env=env, env_prefixes=env_prefixes):
      if suppress_log:
        api.step(
            'upload results',
            upload_command,
            infra_step=True,
            stdout=api.raw_io.output_text(),
            stderr=api.raw_io.output_text(),
        )
      else:
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
  checkout_path = api.path['cleanup'].join('tmp_tmp_1', 'flutter sdk')
  yield api.test(
      "no-task-name",
      api.expect_exception('ValueError'),
  )
  yield api.test(
      "basic",
      api.properties(buildername='Linux abc', task_name='abc', git_branch='master'),
      api.repo_util.flutter_environment_data(checkout_dir=checkout_path),
      api.step_data(
          'run abc',
          stdout=api.raw_io.output_text('#flaky\nthis is a flaky\nflaky: true'),
          retcode=0
      ),
      api.buildbucket.ci_build(
          project='test',
          git_repo='git.example.com/test/repo',
      ),
      api.runtime(is_experimental=True),
  )
  yield api.test(
      "xcode-devicelab",
      api.properties(
          buildername='Mac_ios abc',
          task_name='abc',
          tags=['ios'],
          dependencies=[{'dependency': 'xcode'}],
          git_branch='master',
      ), api.repo_util.flutter_environment_data(checkout_dir=checkout_path),
      api.buildbucket.ci_build(git_ref='refs/heads/master',),
      api.step_data(
          'run abc',
          stdout=api.raw_io.output_text('#flaky\nthis is a flaky\nflaky: true'),
          retcode=0
      ), api.swarming.properties(bot_id='flutter-devicelab-mac-1'),
      api.step_data(
          'Find device type',
          stdout=api.raw_io.output_text('iPhone8,1'),
      )
  )
  yield api.test(
      "xcode-chromium-mac",
      api.properties(
          buildername='Mac_ios abc',
          task_name='abc',
          tags=['ios'],
          dependencies=[{'dependency': 'xcode'}],
          git_branch='master',
      ),
      api.buildbucket.ci_build(git_ref='refs/heads/master',),
      api.repo_util.flutter_environment_data(checkout_dir=checkout_path),
      api.platform.name('mac'),
      api.step_data(
          'Find device type',
          stdout=api.raw_io.output_text('iPhone8,1'),
      ),
  )
  yield api.test(
      "post-submit",
      api.properties(
          buildername='Windows abc', task_name='abc', upload_metrics=True,
          git_branch='master',
      ),
      api.repo_util.flutter_environment_data(checkout_dir=checkout_path),
      api.step_data(
          'run abc',
          stdout=api.raw_io.output_text('#flaky\nthis is a flaky\nflaky: true'),
          retcode=0
      ),
      api.buildbucket.ci_build(git_ref='refs/heads/master',),
  )
  yield api.test(
      "upload-metrics-mac",
      api.properties(
          buildername='Mac_ios abc',
          dependencies=[{'dependency': 'xcode'}],
          tags=['ios'],
          task_name='abc',
          upload_metrics=True,
          upload_metrics_to_cas=True,
          git_branch='master',
      ), api.repo_util.flutter_environment_data(checkout_dir=checkout_path),
      api.platform.name('mac'),
      api.step_data(
          'Find device type',
          stdout=api.raw_io.output_text('iPhone8,1'),
      ), api.buildbucket.ci_build(git_ref='refs/heads/master',)
  )
  yield api.test(
      "no-upload-metrics-linux-staging",
      api.properties(
          buildername='Linux abc',
          task_name='abc',
          upload_metrics_to_cas=True,
          git_branch='master',
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
          local_engine='host-release',
          git_branch='master',
      ), api.repo_util.flutter_environment_data(checkout_dir=checkout_path),
      api.buildbucket.ci_build(
          project='test',
          git_repo='git.example.com/test/repo',
          git_ref='refs/heads/master',
      )
  )
