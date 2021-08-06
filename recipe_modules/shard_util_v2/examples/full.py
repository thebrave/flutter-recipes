# Copyright 2021 The Chromium Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

import copy

from PB.recipe_modules.recipe_engine.led.properties import (
    InputProperties as LedInputProperties,
)
from recipe_engine.post_process import DoesNotRun, Filter, StatusFailure
from PB.go.chromium.org.luci.buildbucket.proto import common as common_pb2

DEPS = [
    'flutter/shard_util_v2',
    'fuchsia/buildbucket_util',
    'recipe_engine/buildbucket',
    'recipe_engine/properties',
    'recipe_engine/platform',
    'recipe_engine/step',
]


def RunSteps(api):
  build_configs = api.properties.get('builds', [])
  with api.step.nest("launch builds") as presentation:
    reqs = api.shard_util_v2.schedule(build_configs, presentation)
  with api.step.nest("collect builds") as presentation:
    builds = api.shard_util_v2.collect([
        build.build_id for build in reqs.values()
    ], presentation)
    for build in builds.itervalues():
      if build.build_proto.status != common_pb2.SUCCESS:
        raise api.step.StepFailure("build %s failed" % build.build_id)


def GenTests(api):
  try_subbuild1 = api.shard_util_v2.try_build_message(
      build_id=8945511751514863186,
      builder="builder-subbuild1",
      output_props={"test_orchestration_inputs_hash": "abc"},
      status="SUCCESS",
  )
  try_subbuild2 = api.shard_util_v2.try_build_message(
      build_id=8945511751514863187,
      builder="builder-subbuild2",
      output_props={"test_orchestration_inputs_hash": "abc"},
      status="SUCCESS",
  )
  try_failure = api.shard_util_v2.try_build_message(
      build_id=8945511751514863187,
      builder="builder-subbuild2",
      output_props={"test_orchestration_inputs_hash": "abc"},
      status="FAILURE",
  )

  props = {
      'builds': [{
          "name": "ios_debug", "gn": [], "ninja": ["ios_debug"],
          'drone_dimensions': ['dimension1=abc']
      }],
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
      'builds': [{
          "name": "ios_debug", "gn": ["--ios"],
          "ninja": {"config": "ios_debug",
                    "targets": []}, 'drone_dimensions': ['dimension1=abc'],
          "generators": [{"name": "generator1", "script": "script1.sh"}]
      }], 'dependencies': [{"dependency": "android_sdk"},
                           {"dependency": "chrome_and_driver"}]
  }

  presubmit_props = copy.deepcopy(props)
  presubmit_props['git_url'] = 'http://abc'
  presubmit_props['git_ref'] = 'refs/123/master'

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
          builds=[try_subbuild1, try_subbuild2],
          collect_step="collect builds",
      )
  )

  presubmit_props_bb = copy.deepcopy(props_bb)
  presubmit_props_bb['git_url'] = 'http://abc'
  presubmit_props_bb['git_ref'] = 'refs/123/master'

  yield (
      api.buildbucket_util.test("presubmit_bb", tryjob=True, status="failure") +
      api.properties(**presubmit_props_bb) + api.platform.name('linux') +
      api.shard_util_v2.child_build_steps(
          builds=[try_failure],
          launch_step="launch builds",
          collect_step="collect builds",
      )
  )
