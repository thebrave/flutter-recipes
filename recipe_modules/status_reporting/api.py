# Copyright 2022 The Chromium Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

from recipe_engine import recipe_api
from google.protobuf import json_format

from PB.go.chromium.org.luci.buildbucket.proto import common as common_pb2
from PB.go.chromium.org.luci.buildbucket.proto import build as build_pb2


class StatusReportingApi(recipe_api.RecipeApi):

  def build_to_json(self, build):
    """Encodes a shard_util_v2.SubbuildResult to a json string.

    Args:
      build(build.Build): The build to encode.

    Returns:
      A string with the Build message encoded as Json.
    """
    return json_format.MessageToJson(build)

  def publish_builds(
      self,
      subbuilds,
      topic='projects/flutter-dashboard/topics/luci-builds-prod',
      only_publish_build_id=False
  ):
    """Publish builds to a pubsub topic.

    Args:
      subbuilds(dict): A dictionary with the build name as key and a value
        of shard_util_v2.SubbuildResult as a value.
      topic(str): (optional) gcloud topic to publish message to.
      only_publish_build_id(bool): (optional) If True, only publish the build_id
        of the shard_util_v2.SubbuildResult instead of the entire build json.
    """
    with self.m.step.nest('Publish results') as presentation:
      for id_name, build in subbuilds.items():
        if only_publish_build_id is True:
          message = build.build_id
        else:
          message = self.build_to_json(build.build_proto)

        cmd = [
            'pubsub', 'topics', 'publish', topic,
            '--message=\'%s\'' % message
        ]
        self.m.gcloud(*cmd, infra_step=True)
