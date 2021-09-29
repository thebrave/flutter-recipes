# Copyright 2020 The Chromium Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

from recipe_engine.recipe_api import Property

DEPS = [
    'flutter/devicelab_osx_sdk',
    'flutter/flutter_deps',
    'flutter/logs_util',
    'flutter/os_utils',
    'flutter/osx_sdk',
    'flutter/repo_util',
    'flutter/retry',
    'flutter/test_utils',
    'recipe_engine/buildbucket',
    'recipe_engine/cas',
    'recipe_engine/context',
    'recipe_engine/file',
    'recipe_engine/path',
    'recipe_engine/platform',
    'recipe_engine/properties',
    'recipe_engine/raw_io',
    'recipe_engine/runtime',
    'recipe_engine/service_account',
    'recipe_engine/step',
    'recipe_engine/swarming',
]

# Fifteen minutes
MAX_TIMEOUT_SECS = 30 * 60


def RunSteps(api):
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
  env, env_prefixes = api.repo_util.flutter_environment(flutter_path)
  api.logs_util.initialize_logs_collection(env)
  with api.step.nest('Dependencies'):
    api.flutter_deps.flutter_engine(env, env_prefixes)
    deps = api.properties.get('dependencies', [])
    # TODO: If deps contains dart_sdk and we are running a local engine,
    # we don't want to fetch it with cipd, so don't fetch it with required_deps
    api.flutter_deps.required_deps(env, env_prefixes, deps)
    api.flutter_deps.vpython(env, env_prefixes, 'latest')
  devicelab_path = flutter_path.join('dev', 'devicelab')
  git_branch = api.buildbucket.gitiles_commit.ref.replace('refs/heads/', '')
  # Create tmp file to store results in
  results_path = api.path.mkdtemp(prefix='results').join('results')
  # Run test
  runner_params = [
      '-t', task_name, '--results-file', results_path, '--luci-builder',
      api.properties.get('buildername')
  ]
  if 'LOCAL_ENGINE' in env:
    runner_params.extend(['--local-engine', env['LOCAL_ENGINE']])
  # LUCI git checkouts end up in a detached HEAD state, so branch must
  # be passed from gitiles -> test runner -> Cocoon.
  if git_branch:
    # git_branch is set only when the build was triggered by buildbucket.
    runner_params.extend(['--git-branch', git_branch])
  test_status = ''
  with api.context(env=env, env_prefixes=env_prefixes, cwd=devicelab_path):
    api.retry.step(
        'flutter doctor',
        ['flutter', 'doctor'],
        max_attempts=3,
        timeout=300,
    )
    api.step('pub get', ['pub', 'get'], infra_step=True)
    dep_list = {d['dependency']: d.get('version') for d in deps}
    if dep_list.has_key('xcode'):
      api.os_utils.clean_derived_data()
      if str(api.swarming.bot_id).startswith('flutter-devicelab'):
        with api.devicelab_osx_sdk('ios'):
          test_status = mac_test(
              api, env, env_prefixes, flutter_path, task_name, runner_params
          )
      else:
        with api.osx_sdk('ios'):
          test_status = mac_test(
              api, env, env_prefixes, flutter_path, task_name, runner_params
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
              timeout_secs=MAX_TIMEOUT_SECS
          )
        finally:
          api.logs_util.upload_logs(task_name)
          # This is to clean up leaked processes.
          api.os_utils.kill_processes()
        if test_status == 'flaky':
          check_flaky(api)
  with api.context(env=env, env_prefixes=env_prefixes, cwd=devicelab_path):
    uploadResults(
        api, results_path, test_status == 'flaky', git_branch,
        api.properties.get('buildername')
    )
    uploadMetricsToCas(api, results_path)


def mac_test(api, env, env_prefixes, flutter_path, task_name, runner_params):
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
          timeout_secs=MAX_TIMEOUT_SECS
      )
    finally:
      api.logs_util.upload_logs(task_name)
      # This is to clean up leaked processes.
      api.os_utils.kill_processes()
    if test_status == 'flaky':
      check_flaky(api)
  return test_status


def check_flaky(api):
  if api.platform.is_win:
    api.step(
        'check flaky',
        ['powershell.exe', 'echo "test run is flaky"'],
        infra_step=True,
    )
  else:
    api.step(
        'check flaky',
        ['echo', 'test run is flaky'],
        infra_step=True,
    )


def shouldNotUpdate(api, builder_name, git_branch):
  """Check if a post submit builder should update results to cocoon.

  Test results will be sent to cocoon only when test is post-submit, when test
  runs in prod pool, and when test is from master branch.
  """
  supported_branches = ['master']
  if api.runtime.is_experimental or api.properties.get(
      'git_url') or 'staging' in builder_name or git_branch not in supported_branches:
    return True
  else:
    return False


def uploadResults(
    api,
    results_path,
    is_test_flaky,
    git_branch,
    builder_name,
    test_status='Succeeded'
):
  """Upload DeviceLab test results to Cocoon.

  luci-auth only gurantees a service account token life of 3 minutes. To work
  around this limitation, results uploading is separate from the the test run.

  Only post-submit tests upload results to Cocoon. If `upload_metrics: true`, generated
  test metrics will be uploaded to Cocoon. Otherwise, only test flaky status will be
  updated to Cocoon.
  """
  if shouldNotUpdate(api, builder_name, git_branch):
    return
  runner_params = ['--test-flaky', is_test_flaky]
  if not api.properties.get('upload_metrics'):
    runner_params.extend([
        '--git-branch', git_branch, '--luci-builder', builder_name,
        '--test-status', test_status
    ])
  else:
    runner_params.extend(['--results-file', results_path])
  with api.step.nest('Upload metrics'):
    service_account = api.service_account.default()
    access_token = service_account.get_access_token()
    access_token_path = api.path.mkstemp()
    api.file.write_text(
        "write token", access_token_path, access_token, include_log=False
    )
    runner_params.extend(['--service-account-token-file', access_token_path])
    upload_command = ['dart', 'bin/test_runner.dart', 'upload-metrics']
    upload_command.extend(runner_params)
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
      api.properties(buildername='Linux abc', task_name='abc'),
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
      api.platform.name('linux'),
      api.runtime(is_experimental=True),
  )
  yield api.test(
      "xcode-devicelab",
      api.properties(
          buildername='Mac abc',
          task_name='abc',
          dependencies=[{'dependency': 'xcode'}]
      ), api.repo_util.flutter_environment_data(checkout_dir=checkout_path),
      api.buildbucket.ci_build(
          git_ref='refs/heads/master',
      ),
      api.step_data(
          'run abc',
          stdout=api.raw_io.output_text('#flaky\nthis is a flaky\nflaky: true'),
          retcode=0
      ), api.swarming.properties(bot_id='flutter-devicelab-mac-1')
  )
  yield api.test(
      "xcode-chromium-mac",
      api.properties(
          buildername='Mac abc',
          task_name='abc',
          dependencies=[{'dependency': 'xcode'}]
      ),
      api.buildbucket.ci_build(
          git_ref='refs/heads/master',
      ),
      api.repo_util.flutter_environment_data(checkout_dir=checkout_path),
  )
  yield api.test(
      "post-submit",
      api.properties(
          buildername='Windows abc', task_name='abc', upload_metrics=True
      ),
      api.repo_util.flutter_environment_data(checkout_dir=checkout_path),
      api.step_data(
          'run abc',
          stdout=api.raw_io.output_text('#flaky\nthis is a flaky\nflaky: true'),
          retcode=0
      ),
      api.buildbucket.ci_build(
          git_ref='refs/heads/master',
      ),
      api.platform.name('win'),
  )
  yield api.test(
      "upload-metrics-mac",
      api.properties(
          buildername='Mac abc',
          dependencies=[{'dependency': 'xcode'}],
          task_name='abc',
          upload_metrics=True,
          upload_metrics_to_cas=True,
      ), api.repo_util.flutter_environment_data(checkout_dir=checkout_path),
      api.buildbucket.ci_build(
          git_ref='refs/heads/master',
      )
  )
  yield api.test(
      "local-engine",
      api.properties(
          buildername='Linux abc',
          task_name='abc',
          local_engine_cas_hash='isolatehashlocalengine/22',
          local_engine='host-release'
      ), api.repo_util.flutter_environment_data(checkout_dir=checkout_path),
      api.buildbucket.ci_build(
          project='test',
          git_repo='git.example.com/test/repo',
          git_ref='refs/heads/master',
      )
  )
