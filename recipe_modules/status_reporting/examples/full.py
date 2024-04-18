# Copyright 2020 The Chromium Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

from recipe_engine.post_process import DoesNotRun, Filter, StatusFailure

from PB.go.chromium.org.luci.buildbucket.proto import build as build_pb2
from PB.go.chromium.org.luci.buildbucket.proto import builder_common as builder_pb2
from RECIPE_MODULES.flutter.shard_util.api import SubbuildResult

DEPS = ['flutter/status_reporting']


def RunSteps(api):
  build = build_pb2.Build(
      builder=builder_pb2
      .BuilderID(project='flutter', bucket='try', builder='mybuild')
  )
  result = SubbuildResult(
      builder='mybuild',
      build_id=123,
      build_name='build_name',
      url='https://123',
      build_proto=build
  )
  api.status_reporting.publish_builds(subbuilds={'mybuild': result})
  api.status_reporting.publish_builds(
      subbuilds={'mybuild': result}, topic='custom/pubsub/url'
  )
  api.status_reporting.publish_builds(
      subbuilds={'mybuild': result},
      topic='custom/pubsub/url',
      only_publish_build_id=True
  )


def GenTests(api):
  yield api.test('basic')
