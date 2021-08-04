# Copyright 2021 The Chromium Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

DRONE_TIMEOUT_SECS = 3600 * 3  # 3 hours.

import attr

from google.protobuf import json_format
from recipe_engine import recipe_api
from PB.go.chromium.org.luci.buildbucket.proto import common as common_pb2
from PB.go.chromium.org.luci.buildbucket.proto import build as build_pb2

# Builder names use full platform name instead of short names. We need to
# map short names to full platform names to be able to identify the drone
# used to run the subshards.
PLATFORM_TO_NAME = {'win': 'Windows', 'linux': 'Linux', 'mac': 'Mac'}


@attr.s
class SubbuildResult(object):
    """Subbuild result metadata."""

    builder = attr.ib(type=str)
    build_id = attr.ib(type=str)
    url = attr.ib(type=str, default=None)
    build_proto = attr.ib(type=build_pb2.Build, default=None)


class ShardUtilApi(recipe_api.RecipeApi):
  """Utilities to shard tasks."""

  def schedule(self, builds):
    """Schedules one subbuild per build."""
    # Dependencies get here as a frozen dict we need to force them back
    # to list of dicts.
    results = {}
    for build in builds:
      task_name = build.get('name')
      drone_properties = self.m.properties.thaw()
      drone_properties['build'] = build
      # Copy parent bot dimensions.
      drone_dimensions = build.get('drone_dimensions', [])
      task_dimensions = {}
      task_dimensions = []
      for d in drone_dimensions:
        k, v = d.split('=')
        task_dimensions.append(common_pb2.RequestedDimension(key=k, value=v))
      platform_name = PLATFORM_TO_NAME.get(self.m.platform.name)

      # Override recipe.
      drone_properties['recipe'] = 'engine_v2/builder'

      if self.m.led.launched_by_led:
        # If coming from led Launch sub-build using led.
        builder_name='%s Engine Drone' % platform_name
        parent = self.m.buildbucket.build.builder
        led_data = self.m.led(
            "get-builder",
            "luci.%s.%s:%s" % (parent.project, parent.bucket, builder_name),
        )
        edit_args = []
        for k, v in drone_properties.items():
          edit_args.extend(["-p", "%s=%s" % (k, self.m.json.dumps(v))])
        # led reduces the priority of tasks by 10 from their values in
        # buildbucket which we do not want.
        # TODO(crbug.com/1138533) Add an option to led to handle this.
        led_data.result.buildbucket.bbagent_args.build.infra.swarming.priority -= 10
        led_data = led_data.then("edit", *edit_args)
        led_data = led_data.then("edit", "-name", task_name)
        led_data = led_data.then("edit", "-r", 'engine_v2/builder')
        led_data = self.m.led.inject_input_recipes(led_data)
        launch_res = led_data.then("launch", "-modernize")
        task_id = launch_res.launch_result.task_id
        build_url = "https://ci.chromium.org/swarming/task/%s?server=%s" % (
            task_id,
            launch_res.launch_result.swarming_hostname,
        )
        results[task_name] = SubbuildResult(
                builder=task_name, build_id=task_id, url=build_url
        )
    return results

  def collect(self, task_ids, presentation):
    """Waits for a list of builds to complete.

    Args:
      task_ids((list(str|TaskRequestMetadata)): The tasks metadata used to
        wait for completion.
      presentation(StepPresentation): Used to add logs and logs to UI.

    Returns: A list of SubBuildResult, one per task.
    """
    swarming_results = self.m.swarming.collect(
        "collect", task_ids, output_dir=self.m.path["cleanup"]
    )
    builds = {}
    for result in swarming_results:
      task_id = result.id
      # Led launch ensures this file is present in the task root dir.
      build_proto_path = result.output_dir.join("build.proto.json")
      build_proto_json = self.m.file.read_text(
          "read build.proto.json", build_proto_path
      )
      build_proto = build_pb2.Build()
      log_name = '%s-build.proto.json' % result.id
      presentation.logs[log_name] = build_proto_json.splitlines()
      json_format.Parse(build_proto_json, build_proto)
      builds[task_id] = SubbuildResult(
         builder=build_proto.builder.builder,
         build_id=task_id,
         build_proto=build_proto,
      )
    return builds
