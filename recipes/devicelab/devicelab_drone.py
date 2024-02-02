# Copyright 2020 The Chromium Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

import contextlib
from RECIPE_MODULES.flutter.flutter_bcid.api import BcidStage

DEPS = [
    'flutter/android_virtual_device',
    'flutter/flutter_bcid',
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

MAX_DEFAULT_TIMEOUT_SECS = 30 * 60


def _runner_command(api, env, runner_params):
  if api.platform.is_mac:
    resource_name = api.resource('runner.sh')
    api.step('Set execute permission', ['chmod', '755', resource_name])
    test_runner_command = [resource_name]
    test_runner_command.extend(runner_params)
  else:
    test_runner_command = ['xvfb-run'] if api.properties.get('xvfb') else []
    test_runner_command.extend(['dart', 'bin/test_runner.dart', 'test'])
    test_runner_command.extend(runner_params)

  if 'USE_EMULATOR' in env and env['USE_EMULATOR']:
    # use-emulator is a flag for the test_runner.
    test_runner_command.extend(['--use-emulator'])

  return test_runner_command


def RunSteps(api):
  api.flutter_bcid.report_stage(BcidStage.START.value)
  # Collect memory/cpu/process before task execution.
  api.os_utils.collect_os_info()

  # If on macOS, reset Xcode in case a previous build failed to do so.
  api.osx_sdk.reset_xcode()

  task_name = api.properties.get("task_name")
  if not task_name:
    raise ValueError('A task_name property is required')

  api.os_utils.print_pub_certs()

  api.flutter_bcid.report_stage(BcidStage.FETCH.value)
  flutter_path = api.path.mkdtemp().join('flutter sdk')
  api.repo_util.checkout(
      'flutter',
      flutter_path,
      api.properties.get('git_url'),
      api.properties.get('git_ref'),
  )

  test_timeout_secs = api.properties.get(
      'test_timeout_secs', MAX_DEFAULT_TIMEOUT_SECS
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
  env['USE_EMULATOR'] = False
  api.logs_util.initialize_logs_collection(env)
  with api.step.nest('Dependencies'):
    api.flutter_deps.flutter_engine(env, env_prefixes)
    # TODO: If deps contains dart_sdk and we are running a local engine,
    # we don't want to fetch it with cipd, so don't fetch it with required_deps
    api.flutter_deps.required_deps(
        env, env_prefixes, api.properties.get('dependencies', [])
    )

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
  runner_params = [
      '-t', task_name, '--results-file', results_path, '--luci-builder',
      builder_name
  ]
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
    api.retry.step(
        'flutter doctor',
        ['flutter', 'doctor'],
        max_attempts=3,
        timeout=300,
    )
    api.step(
        'dart pub get',
        ['dart', 'pub', 'get'],
        infra_step=True,
        timeout=10 * 60,  # 10 minutes
    )

    with contextlib.ExitStack() as exit_stack:
      api.flutter_deps.enter_contexts(
          exit_stack, api.properties.get('contexts', []), env, env_prefixes
      )
      api.os_utils.clean_derived_data()
      api.retry.step(
          'flutter doctor',
          ['flutter', 'doctor', '--verbose'],
          max_attempts=3,
          timeout=300,
      )
      # Next steps get executed only if running in mac.
      api.os_utils.prepare_ios_device()
      api.os_utils.shutdown_simulators()
      api.os_utils.ios_debug_symbol_doctor()

      test_runner_command = _runner_command(api, env, runner_params)
      try:
        test_status = api.test_utils.run_test(
            'run %s' % task_name,
            test_runner_command,
            timeout_secs=test_timeout_secs,
        )
      finally:
        debug_after_failure(api, task_name)

      if test_status == 'flaky':
        api.test_utils.flaky_step('run %s' % task_name)

  with api.context(env=env, env_prefixes=env_prefixes, cwd=devicelab_path):

    def _retryUpload():
      api.step(
          'Upload results',
          uploadResults(
              api,
              env,
              env_prefixes,
              results_path,
              test_status == 'flaky',
              git_branch,
              api.properties.get('buildername'),
              commit_time,
              task_name,
              benchmark_tags,
          )
      )

    api.retry.wrap(_retryUpload, step_name='Retryable upload metrics')
    uploadMetricsToCas(api, results_path)


def debug_after_failure(api, task_name):
  """Upload logs and collect OS debug info."""
  api.logs_util.upload_logs(task_name)
  # This is to clean up leaked processes.
  api.os_utils.kill_processes()
  # This is to reset permission dialogs.
  api.os_utils.reset_automation_dialogs()
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
  checkout_path = api.path['cleanup'].join('tmp_tmp_1', 'flutter sdk')
  avd_version = "android_31_google_apis_x64.textpb"
  avd_cipd_version = "AVDCIPDVERSION"
  yield api.test(
      "no-task-name",
      api.expect_exception('ValueError'),
  )
  yield api.test(
      "basic",
      api.properties(
          buildername='Linux abc',
          task_name='abc',
          git_branch='master',
          openpay=True,
      ),
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
      "emulator-test",
      api.properties(
          buildername='Linux abc',
          task_name='abc',
          git_branch='master',
          dependencies=[{
              "dependency": "android_virtual_device", "version": avd_version
          }, {"dependency": "avd_cipd_version", "version": avd_cipd_version}],
          contexts=["android_virtual_device"]
      ), api.repo_util.flutter_environment_data(checkout_dir=checkout_path),
      api.step_data(
          'run abc',
          stdout=api.raw_io.output_text('#flaky\nthis is a flaky\nflaky: true'),
          retcode=0
      ),
      api.step_data(
          f'start avd.Start Android emulator ({avd_version})',
          stdout=api.raw_io.output_text(
              'android_31_google_apis_x86|emulator-5554 started (pid: 17687)'
          )
      ), api.runtime(is_experimental=True)
  )
  yield api.test(
      "xcode-devicelab",
      api.properties(
          buildername='Mac_ios abc',
          task_name='abc',
          tags=['ios'],
          device_os='iOS-16',
          git_branch='master',
          **{'$flutter/osx_sdk': {'sdk_version': 'deadbeef',}}
      ),
      api.repo_util.flutter_environment_data(checkout_dir=checkout_path),
      api.platform.name('mac'),
      api.buildbucket.ci_build(git_ref='refs/heads/master',),
      api.step_data(
          'run abc',
          stdout=api.raw_io.output_text('#flaky\nthis is a flaky\nflaky: true'),
          retcode=0
      ),
      api.swarming.properties(bot_id='flutter-devicelab-mac-1'),
      api.step_data(
          'Find device type',
          stdout=api.raw_io.output_text('iPhone8,1'),
      ),
      api.step_data(
          'Prepare iOS device.Dismiss Xcode automation dialogs.Find TCC directory',
          stdout=api.raw_io.output_text('TCC.db'),
      ),
      api.step_data(
          'Prepare iOS device.Dismiss Xcode automation dialogs.Query TCC db (2)',
          stdout=api.raw_io.output_text(
              'service|client|client_type|auth_value|auth_reason|auth_version|com.apple.dt.Xcode|flags|last_modified'
          ),
      ),
  )
  yield api.test(
      "xcode-devicelab-timeout",
      api.properties(
          buildername='Mac_ios abc',
          task_name='abc',
          tags=['ios'],
          device_os='iOS-16',
          test_timeout_secs=1,
          git_branch='master',
          **{'$flutter/osx_sdk': {'sdk_version': 'deadbeef',}}
      ),
      api.repo_util.flutter_environment_data(checkout_dir=checkout_path),
      api.platform.name('mac'),
      api.buildbucket.ci_build(git_ref='refs/heads/master',),
      api.step_data(
          'Find device type',
          stdout=api.raw_io.output_text('iPhone8,1'),
      ),
      api.step_data(
          'run abc',
          times_out_after=2,
          had_timeout=True,
      ),
      api.step_data(
          'Prepare iOS device.Dismiss Xcode automation dialogs.Find TCC directory',
          stdout=api.raw_io.output_text('TCC.db'),
      ),
      api.step_data(
          'Prepare iOS device.Dismiss Xcode automation dialogs.Query TCC db (2)',
          stdout=api.raw_io.output_text(
              'service|client|client_type|auth_value|auth_reason|auth_version|com.apple.dt.Xcode|flags|last_modified'
          ),
      ),
      api.swarming.properties(bot_id='flutter-devicelab-mac-1'),
      status='FAILURE',
  )
  yield api.test(
      "xcode-chromium-mac",
      api.properties(
          buildername='Mac_ios abc',
          task_name='abc',
          tags=['ios'],
          device_os='iOS-16',
          **{'$flutter/osx_sdk': {'sdk_version': 'deadbeef',}},
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
          buildername='Windows abc',
          task_name='abc',
          upload_metrics=True,
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
          **{'$flutter/osx_sdk': {'sdk_version': 'deadbeef',}},
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
      "linux-xvfb",
      api.properties(
          buildername='Linux xvfb',
          task_name='abc',
          upload_metrics_to_cas=True,
          git_branch='master',
          xvfb=1,
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
      ), api.repo_util.flutter_environment_data(checkout_dir=checkout_path),
      api.buildbucket.ci_build(
          project='test',
          git_repo='git.example.com/test/repo',
          git_ref='refs/heads/master',
      )
  )
  yield api.test(
      "upload-metrics-mac-with-failures",
      api.properties(
          buildername='Mac_ios abc',
          **{'$flutter/osx_sdk': {'sdk_version': 'deadbeef',}},
          tags=['ios'],
          task_name='abc',
          upload_metrics=True,
          upload_metrics_to_cas=True,
          git_branch='master',
      ), api.repo_util.flutter_environment_data(checkout_dir=checkout_path),
      api.platform.name('mac'),
      api.step_data(
          'Upload metrics.upload results',
          retcode=1,
      ),
      api.step_data(
          'Find device type',
          stdout=api.raw_io.output_text('iPhone8,1'),
      ), api.buildbucket.ci_build(git_ref='refs/heads/master',)
  )
