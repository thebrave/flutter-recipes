# Copyright 2020 The Chromium Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.
#
# Recipe to run firebase lab tests.
# This recipe uses the standar flutter dependencies model and a single property
# task_name to identify the test to run.

from contextlib import contextmanager
import re

DEPS = [
    'depot_tools/gsutil',
    'flutter/flutter_deps',
    'flutter/repo_util',
    'flutter/retry',
    'fuchsia/gcloud',
    'recipe_engine/context',
    'recipe_engine/file',
    'recipe_engine/path',
    'recipe_engine/properties',
    'recipe_engine/step',
    'recipe_engine/swarming',
]


def RunSteps(api):
  checkout_path = api.path['start_dir'].join('flutter')
  gcs_bucket = 'flutter_firebase_testlab_staging'
  api.repo_util.checkout(
      'flutter',
      checkout_path=checkout_path,
      url=api.properties.get('git_url'),
      ref=api.properties.get('git_ref')
  )
  env, env_prefixes = api.repo_util.flutter_environment(checkout_path)
  deps = api.properties.get('dependencies', [])
  api.flutter_deps.required_deps(env, env_prefixes, deps)
  task_name = api.properties.get('task_name')

  default_physical_devices = [
      # Physical devices - use only highly available devices to avoid timeouts.
      # Pixel 3
      # Disable temporarily to unblock the rolls https://github.com/flutter/flutter/issues/118708
      #'--device',
      #'model=blueline,version=28',
      # Pixel 5
      '--device',
      'model=redfin,version=30',
      # Moto Z XT1650
      '--device',
      'model=griffin,version=24',
  ]

  default_virtual_devices = [
      # SDK 20 not available virtually or physically.
      '--device',
      'model=Nexus5,version=21',
      '--device',
      'model=Nexus5,version=22',
      '--device',
      'model=Nexus5,version=23',
      # SDK 24 is run on a physical griffin/Moto Z above.
      # TODO(flutter/flutter#123331): This device is flaking.
      # '--device',
      # 'model=Nexus6P,version=25',
      '--device',
      'model=Nexus6P,version=26',
      '--device',
      'model=Nexus6P,version=27',
      # SDK 28 is run on a physical blueline/Pixel 3 above.
      '--device',
      'model=NexusLowRes,version=29',
      # SDK 30 is run on a physical redfin/Pixel 5 above.
  ]

  physical_devices = default_physical_devices if api.properties.get(
      'physical_devices'
  ) is None else api.properties.get('physical_devices')
  virtual_devices = default_virtual_devices if api.properties.get(
      'virtual_devices'
  ) is None else api.properties.get('virtual_devices')

  test_configurations = (
      (
          'Build appbundle', [
              'flutter', 'build', 'appbundle', '--target-platform',
              'android-arm,android-arm64'
          ], 'build/app/outputs/bundle/release/app-release.aab',
          list(physical_devices)
      ),
      (
          'Build apk', [
              'flutter', 'build', 'apk', '--debug', '--target-platform',
              'android-x86'
          ], 'build/app/outputs/flutter-apk/app-debug.apk',
          list(virtual_devices)
      ),
  )

  with api.context(env=env, env_prefixes=env_prefixes, cwd=checkout_path):
    api.step('flutter doctor', ['flutter', 'doctor', '-v'])
    api.step(
        'download dependencies',
        ['flutter', 'update-packages', '-v'],
        infra_step=True,
    )

  test_path = checkout_path.join('dev', 'integration_tests', task_name)
  with api.step.nest('test_execution') as presentation:
    with api.context(env=env, env_prefixes=env_prefixes, cwd=test_path):
      task_id = api.swarming.task_id
      api.gcloud(
          '--quiet',
          'config',
          'set',
          'project',
          'flutter-infra-staging',
          infra_step=True,
      )
      for step_name, build_command, binary, devices in test_configurations:
        # Skip running gcloud command if no devices were provided.
        if not devices:
          continue
        api.step(step_name, build_command)
        firebase_cmd = [
            'firebase', 'test', 'android', 'run', '--type', 'robo', '--app',
            binary, '--timeout', '2m',
            '--results-bucket=gs://%s' % gcs_bucket,
            '--results-dir=%s/%s' % (task_name, task_id)
        ] + devices

        # See https://firebase.google.com/docs/test-lab/android/command-line#script_exit_codes
        # If the firebase command fails with 1, it's likely an HTTP issue that
        # will resolve on a retry. If it fails on 15 or 20, it's explicitly
        # an infra failure on the FTL side, so we should just retry.
        def run_firebase():
          return api.gcloud(*firebase_cmd)

        # Sometimes, infra failures on the FTL side are persistent. We should
        # allow CI to pass in that case rather than block the tree.
        infra_failure_codes = (1, 15, 20)
        try:
          api.retry.wrap(
              run_firebase, max_attempts=3, retriable_codes=infra_failure_codes
          )
        except api.step.StepFailure:
          if api.step.active_result.retcode in infra_failure_codes:
            # FTL is having some infra outage. Don't block the tree. Still
            # check logs for pieces that may have passed.
            pass
          else:
            raise

      logcat_path = '%s/%s/*/logcat' % (task_name, task_id)
      tmp_logcat = api.path['cleanup'].join('logcat')
      api.gsutil.download(gcs_bucket, logcat_path, api.path['cleanup'])
      content = api.file.read_text('read', tmp_logcat)
      presentation.logs['logcat'] = content
      api.step('analyze_logcat', ['grep', 'E/flutter', tmp_logcat], ok_ret=(1,))


def GenTests(api):
  yield api.test(
      'basic',
      api.repo_util.flutter_environment_data(),
      api.properties(task_name='the_task'),
      # A return code of 1 from grep means not error messages were
      # found in logcat and the only acceptable return code.
      api.step_data('test_execution.analyze_logcat', retcode=1),
  )
  yield api.test(
      'empty_devices',
      api.repo_util.flutter_environment_data(),
      api.properties(task_name='the_task', virtual_devices=[]),
      # A return code of 1 from grep means not error messages were
      # found in logcat and the only acceptable return code.
      api.step_data('test_execution.analyze_logcat', retcode=1),
  )
  yield api.test(
      'succeed_on_infra_failure',
      api.repo_util.flutter_environment_data(),
      api.step_data('test_execution.gcloud firebase', retcode=15),
      api.step_data('test_execution.gcloud firebase (2)', retcode=15),
      api.step_data('test_execution.gcloud firebase (3)', retcode=15),
      status='FAILURE'
  )
  yield api.test(
      'failure 10',
      api.repo_util.flutter_environment_data(),
      api.step_data('test_execution.gcloud firebase', retcode=10),
      status='FAILURE'
  )
