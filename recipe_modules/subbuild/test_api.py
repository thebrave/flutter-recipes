# Copyright 2020 The Fuchsia Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

from recipe_engine import recipe_test_api
from PB.go.chromium.org.luci.buildbucket.proto import (
    builds_service as builds_service_pb2,
)
from PB.go.chromium.org.luci.led.job import job as job_pb2


class SubbuildTestApi(recipe_test_api.RecipeTestApi):

  def ci_build_message(
      self, builder, input_props=None, output_props=None, **kwargs
  ):
    """Generates a CI Buildbucket Build message.

        Args:
          builder (str): The builder name.
          input_props (Dict): Input properties to set on the build.
          output_props (Dict): Output properties to set on the build.
          kwargs: Forwarded to BuildbucketApi.ci_build_message.

        See BuildBucketTestApi.ci_build_message for full parameter documentation.
        """
    project = kwargs.pop("project", "fuchsia")
    msg = self.m.buildbucket.ci_build_message(
        builder=builder, project=project, **kwargs
    )
    msg.infra.backend.task.id.id = "abc123"
    msg.input.properties.update(input_props if input_props else {})
    msg.output.properties.update(output_props if output_props else {})
    return msg

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
    return msg

  def child_build_steps(
      self,
      builds,
      launch_step="build",
      collect_step="build",
      collect_attempt=1
  ):
    """Generates step data to schedule and collect from child builds.

        Args:
          builds (list(build_pb2.Build)): The builds to schedule and collect from.
        """
    responses = []
    for build in builds:
      responses.append(
          dict(schedule_build=dict(id=build.id, builder=build.builder))
      )
    mock_schedule_data = self.m.buildbucket.simulated_schedule_output(
        step_name=f"{launch_step}.schedule",
        batch_response=builds_service_pb2.BatchResponse(responses=responses),
    )

    index = "" if collect_attempt <= 1 else (f" ({collect_attempt})")
    mock_collect_data = self.m.buildbucket.simulated_collect_output(
        step_name=f"{collect_step}.collect{index}",
        builds=builds,
    )
    return mock_schedule_data + mock_collect_data

  def child_led_steps(
      self,
      builds,
      collect_step="build",
      launch_step="build",
      collect_attempt=1
  ):
    """Generates step data to schedule and collect from child builds.

        Args:
          builds (list(build_pb2.Build)): The builds to schedule and collect from.
        """
    del launch_step
    responses = []
    step_data = []
    for build in builds:
      responses.append(
          dict(schedule_build=dict(id=build.id, builder=build.builder))
      )
      jd = job_pb2.Definition()
      jd.buildbucket.bbagent_args.build.CopyFrom(build)
      step_data.append(
          self.m.led.mock_get_builder(
              jd,
              build.builder.project,
              build.builder.bucket,
              build.builder.builder,
          )
      )

    index = "" if collect_attempt <= 1 else (f" ({collect_attempt})")
    ret = self.m.buildbucket.simulated_collect_output(
        step_name=f"{collect_step}.collect{index}",
        builds=builds,
    )
    for s in step_data:
      ret += s
    return ret
