# Copyright 2021 The Chromium Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Flutter Engine tester recipe.

This recipe is used to run tests using prebuilt artifacts.
"""

from contextlib import contextmanager

from google.protobuf import struct_pb2
from PB.recipes.flutter.engine import InputProperties
from PB.recipes.flutter.engine import EnvProperties
from PB.go.chromium.org.luci.buildbucket.proto import build as build_pb2

DEPS = [
    'recipe_engine/properties',
]

PROPERTIES = InputProperties
ENV_PROPERTIES = EnvProperties


def test(api, test_config):
  """Runs an independent test task."""
  pass

def RunSteps(api, properties, env_properties):
  # Test configuration is passed as build property. This is to standardize
  # the use of BuildBucket and Led APIs in the orchestrator recipe which
  # triggers the subbuilds.
  test_config = api.properties.get('build')
  test(api, test_config)


def GenTests(api):
  yield api.test('basic_custom_vars')
