# Copyright 2021 The Chromium Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

DRONE_TIMEOUT_SECS = 3600 * 3  # 3 hours.

import attr

from google.protobuf import json_format
from recipe_engine import recipe_api
from recipe_engine import engine_types
from PB.go.chromium.org.luci.buildbucket.proto import common as common_pb2
from PB.go.chromium.org.luci.buildbucket.proto import build as build_pb2
from RECIPE_MODULES.fuchsia.utils import pluralize
# Builder names use full platform name instead of short names. We need to
# map short names to full platform names to be able to identify the drone
# used to run the subshards.
PLATFORM_TO_NAME = {'win': 'Windows', 'linux': 'Linux', 'mac': 'Mac'}

# Internal properties that should be set for builds running on BuildBucket.
PROPERTIES_TO_REMOVE = [
    '$recipe_engine/buildbucket', '$recipe_engine/runtime.is_experimental',
    'buildername', '$recipe_engine/runtime', 'is_experimental'
]


@attr.s
class SubbuildResult(object):
  """Subbuild result metadata."""

  builder = attr.ib(type=str)
  build_id = attr.ib(type=str)
  url = attr.ib(type=str, default=None)
  build_proto = attr.ib(type=build_pb2.Build, default=None)


class ShardUtilApi(recipe_api.RecipeApi):
  """Utilities to shard tasks."""

  def unfreeze_dict(self, dictionary):
    """Creates a mutable dictionary out of a FrozenDict."""
    result = {}
    for k, v in dictionary.items():
      if isinstance(v, engine_types.FrozenDict):
        result[k] = self.unfreeze_dict(v)
      elif isinstance(v, (list, tuple)):
        result[k] = [
            self.unfreeze_dict(i)
            if isinstance(i, engine_types.FrozenDict) else i for i in v
        ]
      else:
        result[k] = v
    return result

  def schedule(self, builds, presentation):
    """Schedules one subbuild per build."""
    build_list = [self.unfreeze_dict(b) for b in builds]
    if self.m.led.launched_by_led:
      builds = self._schedule_with_led(build_list)
    else:
      builds = self._schedule_with_bb(build_list)
    return builds

  def _schedule_with_led(self, builds):
    """Schedules one subbuild per build."""
    # Dependencies get here as a frozen dict we need to force them back
    # to list of dicts.
    results = {}
    for build in builds:
      task_name = build.get('name')
      drone_properties = self.m.properties.thaw()
      drone_properties['build'] = build
      # Delete builds property if it exists.
      drone_properties.pop('builds', None)
      # Copy parent bot dimensions.
      drone_dimensions = build.get('drone_dimensions', [])
      task_dimensions = []
      platform_name = build.get('platform') or PLATFORM_TO_NAME.get(
          self.m.platform.name
      )
      for d in drone_dimensions:
        k, v = d.split('=')
        task_dimensions.append(common_pb2.RequestedDimension(key=k, value=v))

      # Override recipe.
      drone_properties['recipe'] = 'engine_v2/builder'

      if self.m.led.launched_by_led:
        # If coming from led Launch sub-build using led.
        builder_name = '%s Engine Drone' % platform_name
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
        for d in drone_dimensions:
          led_data = led_data.then("edit", "-d", d)
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

  def _schedule_with_bb(self, builds):
    """Schedules builds using builbbucket."""
    swarming_parent_run_id = self.m.swarming.task_id
    reqs = []
    for build in builds:
      task_name = build.get('name')
      drone_properties = self.m.properties.thaw()
      drone_properties['build'] = build
      # Copy parent bot dimensions.
      drone_dimensions = build.get('drone_dimensions', [])
      task_dimensions = []
      platform_name = build.get('platform') or PLATFORM_TO_NAME.get(
          self.m.platform.name
      )
      builder_name = '%s Engine Drone' % platform_name
      for d in drone_dimensions:
        k, v = d.split('=')
        task_dimensions.append(common_pb2.RequestedDimension(key=k, value=v))
      # Override recipe.
      drone_properties['recipe'] = 'engine_v2/builder'
      properties = {
          key: val
          for key, val in drone_properties.items()
          if key not in PROPERTIES_TO_REMOVE
      }
      req = self.m.buildbucket.schedule_request(
          swarming_parent_run_id=self.m.swarming.task_id,
          builder=builder_name,
          properties=properties,
          dimensions=task_dimensions or None,
          # Having main build and subbuilds with the same priority can lead
          # to a deadlock situation when there are limited resources. For example
          # if we have only 7 mac bots and we get more than 7 new build requests the
          # within minutes of each other then the 7 bots will be used by main tasks
          # and they will all timeout waiting for resources to run subbuilds.
          # Increasing priority won't fix the problem but will make the deadlock
          # situation less unlikely.
          # https://github.com/flutter/flutter/issues/59169.
          priority=25
      )
      reqs.append(req)
    scheduled_builds = self.m.buildbucket.schedule(reqs, step_name="schedule")
    results = {}
    for build in scheduled_builds:
      build_url = "https://ci.chromium.org/b/%s" % build.id
      results[build.id] = SubbuildResult(
          builder=build.builder.builder, build_id=build.id, url=build_url
      )
    return results

  def collect(self, build_ids, presentation):
    """Collects builds with the provided build_ids.

    Args:
      build_ids (list(str)): The list of build ids to collect results for.
      presentation (StepPresentation): The presentation to add logs to.

    Returns:
      A map from build IDs to the corresponding SubbuildResult.
    """
    if self.m.led.launched_by_led:
      builds = self._collect_from_led(build_ids, presentation)
    else:
      builds = self._collect_from_bb(build_ids)
    return builds

  def _collect_from_led(self, task_ids, presentation):
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

  def _collect_from_bb(self, build_ids):
    bb_fields = self.m.buildbucket.DEFAULT_FIELDS.union({
        "infra.swarming.task_id", "summary_markdown"
    })
    # As of 2019-11-18, timeout defaults to something too short.
    # We never want this step to time out. We'd rather the whole build time out.
    builds = self.m.buildbucket.collect_builds(
        [int(build_id) for build_id in build_ids],
        interval=20,  # Lower from default of 60 b/c we're impatient.
        timeout=24 * 60 * 60,
        step_name="collect",
        fields=bb_fields,
    )
    failed_builds = [
        b for b in builds.values() if b.status != common_pb2.SUCCESS
    ]
    if failed_builds:
      task_ids = [b.infra.swarming.task_id for b in failed_builds]
      # Make sure task IDs are non-empty.
      assert all(task_ids), task_ids

      # Wait for the underlying Swarming tasks to complete. The Swarming
      # task for a Buildbucket build can take significantly longer to
      # complete than the build itself due to post-processing outside the
      # scope of the build's recipe (e.g. cache pruning). If the parent
      # build and its Swarming task both complete before the subbuild's
      # Swarming task finishes post-processing, then the subbuild's
      # Swarming task will be killed by Swarming due to the parent being
      # complete.
      #
      # That is actually working as intended. However, it's confusing for
      # a subbuild to be marked as killed when the recipe actually exited
      # normally; "killed" usually only happens for CQ builds, when a
      # build is canceled by CQ because a new patchset of the triggering
      # CL is uploaded. So it's convenient to have dashboards and queries
      # ignore "killed" tasks. We use this workaround to ensure that
      # failed subbuilds with long post-processing steps have time to
      # complete and exit cleanly with a plain old "COMPLETED (FAILURE)"
      # status.
      #
      # We only do this if the subbuild failed as a latency optimization.
      # If all subbuilds passed, the parent will go on to do some more
      # steps using the results of the subbuilds, leaving time for the
      # subbuilds' tasks to complete asynchronously, so we don't want to
      # block here while the tasks complete.
      self.m.swarming.collect(
          "wait for %s to complete" % pluralize("task", task_ids), task_ids
      )
    for build_id, build in builds.iteritems():
      builds[build_id] = SubbuildResult(
          builder=build.builder.builder, build_id=build_id, build_proto=build
      )
    return builds
