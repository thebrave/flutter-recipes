# Copyright 2021 The Chromium Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

import copy

from PB.go.chromium.org.luci.buildbucket.proto import common as common_pb2
from PB.go.chromium.org.luci.led.job import job as job_pb2

from recipe_engine.post_process import (
    MustRun,
    StepCommandContains,
)

DEPS = [
    'flutter/monorepo',
    'flutter/shard_util',
    'fuchsia/buildbucket_util',
    'recipe_engine/buildbucket',
    'recipe_engine/led',
    'recipe_engine/path',
    'recipe_engine/platform',
    'recipe_engine/properties',
    'recipe_engine/step',
]


def RunSteps(api):
  build_configs = api.properties.get('builds', [])
  test_configs = api.properties.get('tests', [])
  props = api.shard_util.pre_process_properties({
      'properties': {
          '$flutter/osx_sdk':
              '{"cleanup_cache": true, "sdk_version": "14a5294e"}',
          'validation':
              'docs'
      }
  })
  assert isinstance(props['properties']['$flutter/osx_sdk'], dict)
  assert props['properties']['validation'] == 'docs'
  with api.step.nest("launch builds") as presentation:
    reqs = api.shard_util.schedule_builds(
        build_configs,
        presentation,
        branch=api.properties.get('git_ref', 'main'),
    )
  with api.step.nest("collect builds") as presentation:
    builds = api.shard_util.collect(reqs)
    for build in builds.values():
      if build.build_proto.status != common_pb2.SUCCESS:
        raise api.step.StepFailure("build %s failed" % build.build_id)
    api.shard_util.archive_full_build(
        api.path.start_dir / 'out/host_debug', 'host_debug'
    )
    api.shard_util.download_full_builds(builds, api.path.cleanup_dir / 'out')
  with api.step.nest("launch builds") as presentation:
    reqs = api.shard_util.schedule_tests(test_configs, builds, presentation)
  api.shard_util.get_base_bucket_name()


def GenTests(api):
  try_subbuild1 = api.shard_util.try_build_message(
      build_id=8945511751514863186,
      builder='ios_debug',
      input_props={'task_name': 'mytask'},
      output_props={
          'cas_output_hash': {
              'web_tests': 'abc', 'ios_debug': 'bcd', 'full_build': '123'
          }
      },
      status='SUCCESS',
  )
  try_subbuild2 = api.shard_util.try_build_message(
      build_id=8945511751514863187,
      builder='builder-subbuild2',
      output_props={
          'cas_output_hash': {'web_tests': 'abc', 'ios_debug': 'bcd'}
      },
      status='SUCCESS',
  )
  try_failure = api.shard_util.try_build_message(
      build_id=8945511751514863187,
      builder='builder-subbuild2',
      output_props={
          'cas_output_hash': {'web_tests': 'abc', 'ios_debug': 'bcd'}
      },
      status='FAILURE',
  )

  led_try_subbuild1 = api.shard_util.try_build_message(
      build_id=87654321,
      builder='ios_debug',
      input_props={'task_name': 'mytask'},
      output_props={
          'cas_output_hash': {
              'web_tests': 'abc', 'ios_debug': 'bcd', 'full_build': '123'
          }
      },
      status='SUCCESS',
  )

  props = {
      'builds': [{
          'name': 'ios_debug', 'gn': [], 'ninja': ['ios_debug'],
          'dimensions': {'cpu': 'arm64'},
          'drone_dimensions': ['dimension1=abc', 'os=Linux']
      }],
      'tests': [{
          'name': 'felt_test', 'dependencies': ['ios_debug'],
          'scripts': ['out/script.sh'], 'parameters': ['test']
      }],
      'environment': 'Staging',
      'dependencies': [{'dependency': 'android_sdk'},
                       {'dependency': 'chrome_and_driver'}],
      '$recipe_engine/led': {
          'led_run_id':
              'flutter/led/abc_google.com/b9861e3db1034eee460599837221ab468e03bc43f9fd05684a08157fd646abfc',
          'rbe_cas_input': {
              'cas_instance':
                  'projects/chromium-swarm/instances/default_instance',
              'digest': {
                  'hash':
                      '146d56311043bb141309968d570e23d05a108d13ce2e20b5aeb40a9b95629b3e',
                  'size_bytes':
                      91
              }
          }
      },
  }
  props_bb = {
      'task_name': 'mytask', 'builds': [{
          'name': 'ios_debug', 'gn': ['--ios'], 'dimensions': {'cpu': 'arm64'},
          'ninja': {'config': 'ios_debug', 'targets': []},
          'drone_dimensions': ['dimension1=abc', 'os=Windows-10'],
          'generators': [{'name': 'generator1', 'script': 'script1.sh'}]
      }], 'tests': [{
          'name': 'felt_test', 'dependencies': ['ios_debug'],
          'scripts': ['out/script.sh'], 'parameters': ['test']
      }], 'dependencies': [{'dependency': 'android_sdk'},
                           {'dependency': 'chrome_and_driver'}],
      'environment': 'Staging'
  }

  presubmit_props = copy.deepcopy(props)
  presubmit_props['git_url'] = 'http://abc'
  presubmit_props['git_ref'] = 'refs/123/main'

  job = job_pb2.Definition()
  build = api.buildbucket.ci_build_message(build_id=87654321, on_backend=True)
  job.buildbucket.bbagent_args.build.CopyFrom(build)
  yield api.test(
      'presubmit_led', api.properties(**presubmit_props),
      api.platform.name('linux'),
      api.buildbucket.ci_build(
          project='proj',
          builder='try-builder',
          git_repo='https://github.com/repo/a',
          revision='a' * 40,
          build_number=123
      ), api.led.mock_get_builder(
          job,
          project='proj',
          bucket='ci',
      ),
      api.shard_util.child_led_steps(
          subbuilds=[led_try_subbuild1],
          collect_step='collect builds',
      )
  )
  presubmit_props_bb = copy.deepcopy(props_bb)
  presubmit_props_bb['git_url'] = 'http://abc'
  presubmit_props_bb['git_ref'] = 'refs/123/main'
  presubmit_props_bb['no_goma'] = 'true'

  yield (
      api.buildbucket_util.test('presubmit_bb', tryjob=False, status='FAILURE')
      + api.properties(**presubmit_props_bb) + api.platform.name('linux') +
      api.shard_util.child_build_steps(
          subbuilds=[try_failure],
          launch_step='launch builds.schedule',
          collect_step='collect builds',
      )
  )

  yield (
      api.buildbucket_util
      .test('presubmit_bb_release', tryjob=False, status='FAILURE') +
      api.properties(
          **({
              **presubmit_props_bb, 'git_ref': 'flutter-1.0-candidate.1'
          })
      ) + api.platform.name('linux') + api.shard_util.child_build_steps(
          subbuilds=[try_failure],
          launch_step='launch builds.schedule',
          collect_step='collect builds',
      )
  )

  presubmit_props_bb_with_custom_timeout = copy.deepcopy(props_bb)
  presubmit_props_bb_with_custom_timeout['builds'][0]['timeout'] = 10
  yield (
      api.buildbucket_util.
      test('presubmit_bb_with_custom_timeout', tryjob=False, status='FAILURE') +
      api.properties(**presubmit_props_bb_with_custom_timeout) +
      api.platform.name('linux') + api.shard_util.child_build_steps(
          subbuilds=[try_failure],
          launch_step='launch builds.schedule',
          collect_step='collect builds',
      )
  )

  yield api.test(
      'presubmit_led_subbuilds', api.properties(**props),
      api.platform.name('linux'),
      api.buildbucket.ci_build(
          project='proj',
          builder='try-builder',
          git_repo='https://github.com/repo/a',
          revision='a' * 40,
          build_number=123
      ), api.led.mock_get_builder(
          job,
          project='proj',
          bucket='ci',
      ),
      api.shard_util.child_led_steps(
          subbuilds=[led_try_subbuild1],
          collect_step='collect builds',
      )
  )

  yield api.test(
      'monorepo_bb_subbuilds', api.properties(**props_bb),
      api.platform.name('linux'), api.monorepo.ci_build(),
      api.shard_util.child_build_steps(
          subbuilds=[try_subbuild1],
          launch_step='launch builds.schedule',
          collect_step='collect builds',
      )
  )

  yield api.test(
      'monorepo_try_bb_subbuilds', api.properties(**props_bb),
      api.platform.name('linux'), api.monorepo.try_build(),
      api.shard_util.child_build_steps(
          subbuilds=[try_subbuild1],
          launch_step='launch builds.schedule',
          collect_step='collect builds',
      )
  )

  yield api.test(
      'monorepo_led_subbuilds',
      api.properties(**props),
      api.platform.name('linux'),
      api.monorepo.ci_build(),
      api.shard_util.child_led_steps(
          subbuilds=[led_try_subbuild1],
          collect_step='collect builds',
      ),
      api.led.mock_get_builder(job, project='dart', bucket='ci.sandbox'),
  )

  yield api.test(
      'monorepo_try_led_subbuilds',
      api.properties(**props),
      api.platform.name('linux'),
      api.monorepo.try_build(),
      api.shard_util.child_led_steps(
          subbuilds=[led_try_subbuild1],
          collect_step='collect builds',
      ),
      api.led.mock_get_builder(job, project='dart', bucket='try.monorepo'),
      api.post_process(MustRun, 'launch builds.led edit-cr-cl'),
      api.post_process(
          StepCommandContains, 'launch builds.led get-builder', [
              'led', 'get-builder', '-real-build',
              'dart/try.monorepo/flutter-linux-ios_debug-try'
          ]
      ),
  )

  yield api.test(
      'monorepo_try_led_without_builder_id',
      api.properties(**props),
      api.platform.name('linux'),
      api.monorepo.try_build(build_id=0),
      api.expect_exception('AssertionError'),
  )
