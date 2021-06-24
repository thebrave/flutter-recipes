# Copyright 2021 The Fuchsia Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.
from google.protobuf import json_format

from recipe_engine import recipe_test_api
from PB.go.chromium.org.luci.buildbucket.proto import (
    builds_service as builds_service_pb2,
)
from PB.go.chromium.org.luci.led.job import job as job_pb2


class ShardUtilTestApi(recipe_test_api.RecipeTestApi):

  def try_build_message(
      self, builder, input_props=None, output_props=None, **kwargs):
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
    msg.input.properties.update(input_props if input_props else {})
    msg.output.properties.update(output_props if output_props else {})
    return msg

  def child_led_steps(self, builds, collect_step="build"):
    """Generates step data to schedule and collect from child builds.

    Args:
      builds (list(build_pb2.Build)): The builds to schedule and collect from.
    """
    step_data = []
    task_results = []
    i = 0
    for build in builds:
      i += 1
      suffix = ""
      if i > 1:
        suffix = " (%d)" % i

      task_id = "fake-task-id-%d" % (i,)

      # led launch mock will take ....infra.swarming.task_id as this
      # build's launched swarming ID.
      jd = job_pb2.Definition()
      jd.buildbucket.bbagent_args.build.CopyFrom(build)
      jd.buildbucket.bbagent_args.build.infra.swarming.task_id = task_id
      step_data.append(
          self.m.led.mock_get_builder(
              jd,
              build.builder.project,
              build.builder.bucket,
              build.builder.builder,
          )
      )
      task_results.append(
          self.m.swarming.task_result(id=task_id, name=build.builder.builder)
      )
      step_data.append(
          self.step_data(
              "%s.read build.proto.json%s" % (collect_step, suffix),
              self.m.file.read_text(json_format.MessageToJson(build)),
          )
      )
    ret = self.step_data(
        "%s.collect" % collect_step, self.m.swarming.collect(task_results)
    )
    for s in step_data:
      ret += s
    return ret
