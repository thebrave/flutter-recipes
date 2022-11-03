# Copyright 2021 The Chromium Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

import copy

from PB.go.chromium.org.luci.buildbucket.proto import common as common_pb2

DEPS = [
    'flutter/shard_util_v2',
    'fuchsia/buildbucket_util',
    'recipe_engine/buildbucket',
    'recipe_engine/path',
    'recipe_engine/platform',
    'recipe_engine/properties',
    'recipe_engine/step',
]


def RunSteps(api):
  build_configs = api.properties.get('builds', [])
  test_configs = api.properties.get('tests', [])
  with api.step.nest("launch builds") as presentation:
    reqs = api.shard_util_v2.schedule_builds(build_configs, presentation)
  with api.step.nest("collect builds") as presentation:
    builds = api.shard_util_v2.collect(reqs, presentation)
    for build in builds.values():
      if build.build_proto.status != common_pb2.SUCCESS:
        raise api.step.StepFailure("build %s failed" % build.build_id)
    api.shard_util_v2.archive_full_build(api.path['start_dir'].join('out', 'host_debug'), 'host_debug')
    api.shard_util_v2.download_full_builds(builds, api.path['cleanup'].join('out'))
  with api.step.nest("launch builds") as presentation:
    reqs = api.shard_util_v2.schedule_tests(test_configs, builds, presentation)


def GenTests(api):
  try_subbuild1 = api.shard_util_v2.try_build_message(
      build_id=8945511751514863186,
      builder="ios_debug",
      input_props={'task_name': 'mytask'},
      output_props={
          "cas_output_hash": {"web_tests": "abc", "ios_debug": "bcd", "full_build": "123"}
      },
      status="SUCCESS",
  )
  try_subbuild2 = api.shard_util_v2.try_build_message(
      build_id=8945511751514863187,
      builder="builder-subbuild2",
      output_props={
          "cas_output_hash": {"web_tests": "abc", "ios_debug": "bcd"}
      },
      status="SUCCESS",
  )
  try_failure = api.shard_util_v2.try_build_message(
      build_id=8945511751514863187,
      builder="builder-subbuild2",
      output_props={
          "cas_output_hash": {"web_tests": "abc", "ios_debug": "bcd"}
      },
      status="FAILURE",
  )

  props = {
      'builds': [{
          "name": "ios_debug", "gn": [], "ninja": ["ios_debug"],
          'drone_dimensions': ['dimension1=abc']
      }],
      'tests': [{
          "name": "felt_test", "dependencies": ["ios_debug"],
          "scripts": ["out/script.sh"], "parameters": ["test"]
      }],
      'environment': 'Staging',
      'dependencies': [{"dependency": "android_sdk"},
                       {"dependency": "chrome_and_driver"}],
      '$recipe_engine/led': {
          "led_run_id":
              "flutter/led/abc_google.com/b9861e3db1034eee460599837221ab468e03bc43f9fd05684a08157fd646abfc",
          "rbe_cas_input": {
              "cas_instance":
                  "projects/chromium-swarm/instances/default_instance",
              "digest": {
                  "hash":
                      "146d56311043bb141309968d570e23d05a108d13ce2e20b5aeb40a9b95629b3e",
                  "size_bytes":
                      91
              }
          }
      },
  }
  props_bb = {
      'task_name': 'mytask', 'builds': [{
          "name": "ios_debug", "gn": ["--ios"],
          "ninja": {"config": "ios_debug",
                    "targets": []}, 'drone_dimensions': ['dimension1=abc'],
          "generators": [{"name": "generator1", "script": "script1.sh"}]
      }], 'tests': [{
          "name": "felt_test", "dependencies": ["ios_debug"],
          "scripts": ["out/script.sh"], "parameters": ["test"]
      }], 'dependencies': [{"dependency": "android_sdk"},
                           {"dependency": "chrome_and_driver"}],
      'environment': 'Staging'
  }

  presubmit_props = copy.deepcopy(props)
  presubmit_props['git_url'] = 'http://abc'
  presubmit_props['git_ref'] = 'refs/123/master'
  presubmit_props['builds'][0]['drone_builder_name'] = 'custom drone builder'

  yield api.test(
      'presubmit_led', api.properties(**presubmit_props),
      api.platform.name('linux'),
      api.buildbucket.try_build(
          project='proj',
          builder='try-builder',
          git_repo='https://github.com/repo/a',
          revision='a' * 40,
          build_number=123
      ),
      api.shard_util_v2.child_led_steps(
          subbuilds=[try_subbuild1, try_subbuild2],
          collect_step="collect builds",
      )
  )

  presubmit_props_bb = copy.deepcopy(props_bb)
  presubmit_props_bb['git_url'] = 'http://abc'
  presubmit_props_bb['git_ref'] = 'refs/123/master'
  presubmit_props_bb['builds'][0]['drone_builder_name'] = 'custom drone builder'
  presubmit_props_bb['no_goma'] = 'true'

  yield (
      api.buildbucket_util.test("presubmit_bb", tryjob=True, status="failure") +
      api.properties(**presubmit_props_bb) + api.platform.name('linux') +
      api.shard_util_v2.child_build_steps(
          subbuilds=[try_failure],
          launch_step="launch builds",
          collect_step="collect builds",
      )
  )
