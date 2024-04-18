# Copyright 2021 The Fuchsia Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.
from google.protobuf import json_format

from recipe_engine import recipe_test_api
from PB.go.chromium.org.luci.buildbucket.proto import (
    builds_service as builds_service_pb2,
)
from PB.go.chromium.org.luci.led.job import job as job_pb2
from RECIPE_MODULES.flutter.shard_util.api import SubbuildResult


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
    msg.infra.backend.task.id.id = "abc123"
    msg.input.properties.update(input_props if input_props else {})
    msg.output.properties.update(output_props if output_props else {})
    subbuild = SubbuildResult(
        builder=msg.builder.builder,
        build_id=msg.id,
        build_name=builder,
        build_proto=msg
    )
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
          dict(
              schedule_build=dict(
                  id=subbuild.build_id, builder=subbuild.build_proto.builder
              )
          )
      )
    mock_schedule_data = self.m.buildbucket.simulated_schedule_output(
        step_name="%s" % launch_step,
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
      subbuilds (list(build_pb2.Build)): The builds to schedule and collect from.
    """
    mock_collect_data = self.m.buildbucket.simulated_collect_output(
        step_name="%s.collect" % collect_step,
        builds=[b.build_proto for b in subbuilds],
    )
    return mock_collect_data
