# Copyright 2021 The Fuchsia Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.
from google.protobuf import json_format

from recipe_engine import recipe_test_api
from PB.go.chromium.org.luci.buildbucket.proto import (
    builds_service as builds_service_pb2,
)
from PB.go.chromium.org.luci.led.job import job as job_pb2
from RECIPE_MODULES.flutter.shard_util_v2.api import SubbuildResult


class ShardUtilTestApi(recipe_test_api.RecipeTestApi):
  
  def try_build_message(
      self, builder, input_props=None, output_props=None, **kwargs
  ):
    """Generates a try Buildbucket Build message.

    Args:
      builder (str): The builder name.
      input_props (Dict): Input properties to set on the build.
      output_props (Dict): Output properties to set on the build.
      kwargs: Forwarded to BuildbucketApi.try_build_message.

    See BuildBucketTestApi.try_build_message for full parameter documentation.
    """
    project = kwargs.pop("project", "fuchsia")
    msg = self.m.buildbucket.try_build_message(
        builder=builder, project=project, **kwargs
    )
    msg.infra.swarming.task_id = "abc123"
    msg.input.properties.update(input_props if input_props else {})
    msg.output.properties.update(output_props if output_props else {})
    subbuild = SubbuildResult(
        builder=msg.builder.builder,
        build_id=msg.id,
        build_name=builder,
        build_proto= msg)
    return subbuild

  def child_build_steps(
      self, subbuilds, launch_step="build", collect_step="build"
  ):
    """Generates step data to schedule and collect from child builds.

    Args:
      builds (list(build_pb2.Build)): The builds to schedule and collect from.
    """
    responses = []
    for subbuild in subbuilds:
      responses.append(
          dict(schedule_build=dict(id=subbuild.build_id, builder=subbuild.build_proto.builder))
      )
    mock_schedule_data = self.m.buildbucket.simulated_schedule_output(
        step_name="%s.schedule" % launch_step,
        batch_response=builds_service_pb2.BatchResponse(responses=responses),
    )

    mock_collect_data = self.m.buildbucket.simulated_collect_output(
        step_name="%s.collect" % collect_step,
        builds=[b.build_proto for b in subbuilds],
    )
    return mock_schedule_data + mock_collect_data

  def child_led_steps(self, subbuilds, collect_step="build"):
    """Generates step data to schedule and collect from child builds.

    Args:
      builds (list(build_pb2.Build)): The builds to schedule and collect from.
    """
    step_data = []
    task_results = []
    i = 0
    for subbuild in subbuilds:
      i += 1
      suffix = ""
      if i > 1:
        suffix = " (%d)" % i

      task_id = "fake-task-id-%d" % (i,)

      # led launch mock will take ....infra.swarming.task_id as this
      # build's launched swarming ID.
      jd = job_pb2.Definition()
      jd.buildbucket.bbagent_args.build.CopyFrom(subbuild.build_proto)
      jd.buildbucket.bbagent_args.build.infra.swarming.task_id = task_id
      step_data.append(
          self.m.led.mock_get_builder(
              jd,
              subbuild.build_proto.builder.project,
              subbuild.build_proto.builder.bucket,
              subbuild.build_proto.builder.builder,
          )
      )
      task_results.append(
          self.m.swarming.task_result(id=task_id, name=subbuild.build_name)
      )
      step_data.append(
          self.step_data(
              "%s.read build.proto.json%s" % (collect_step, suffix),
              self.m.file.read_proto(subbuild.build_proto),
          )
      )
    ret = self.step_data(
        "%s.collect" % collect_step, self.m.swarming.collect(task_results)
    )
    for s in step_data:
      ret += s
    return ret
