# Copyright 2021 The Chromium Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

# Orchestrator recipe that coordinates dependencies and build/test execution
# of sub-builds.
#
# This recipe is the main entry point for every builder(e.g. Windows Host
# Engine, Mac iOS Engine, etc). Once here this recipe will read the builder
# configuration from <engine_checkout>/ci/builders/<builder_name>, spawn
# subbuilds to compile/archive using engine_v2/builder.py wait for dependencies
# to be ready and then spawn subbuilds to run expensive tests using
# engine_v2/tester.py.

from contextlib import contextmanager

from PB.recipes.flutter.engine import InputProperties
from PB.recipes.flutter.engine import EnvProperties

from PB.go.chromium.org.luci.buildbucket.proto import build as build_pb2
from google.protobuf import struct_pb2

DEPS = [
    'flutter/repo_util',
    'flutter/shard_util_v2',
    'recipe_engine/buildbucket',
    'recipe_engine/json',
    'recipe_engine/properties',
    'recipe_engine/path',
    'recipe_engine/step',
]

PROPERTIES = InputProperties
ENV_PROPERTIES = EnvProperties


def RunSteps(api, properties, env_properties):
  config_name = api.properties.get('config_name')
  # Checkout engine repository only.
  checkout_path = api.path['start_dir'].join('engine')
  api.repo_util.checkout(
      'engine',
      checkout_path=checkout_path,
      url=api.properties.get('git_url'),
      ref=api.properties.get('git_ref')
  )
  # Read builds configuration from repository under test.
  config_path = checkout_path.join('ci', 'builders', '%s.json' % config_name)
  builds = api.properties.get('builds')
  builds = builds or api.json.read(
      'Read build config file',
      config_path,
      step_test_data=lambda: api.json.test_api.output([])
  ).json.output
  with api.step.nest('launch builds') as presentation:
    tasks = api.shard_util_v2.schedule_builds(builds, presentation)
  with api.step.nest('collect builds') as presentation:
    api.shard_util_v2.collect(tasks, presentation)


def GenTests(api):
  try_subbuild1 = api.shard_util_v2.try_build_message(
      build_id=8945511751514863186,
      builder="builder-subbuild1",
      output_props={"test_orchestration_inputs_hash": "abc"},
      status="SUCCESS",
  )
  builds = [{
      "name": "ios_debug", "gn": ["--ios"],
      "ninja": {"config": "ios_debug", "targets": []},
      "generators": [{"name": "generator1", "script": "script1.sh"}]
  }]
  yield api.test(
      'basic', api.properties(builds=builds, environment='Staging'),
      api.buildbucket.try_build(
          project='proj',
          builder='try-builder',
          git_repo='https://github.com/repo/a',
          revision='a' * 40,
          build_number=123
      ),
      api.shard_util_v2.child_build_steps(
          builds=[try_subbuild1],
          launch_step="launch builds",
          collect_step="collect builds",
      )
  )
