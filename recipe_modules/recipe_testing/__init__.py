# Copyright 2022 The Chromium Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

DEPS = [
    "flutter/gerrit_util",
    "fuchsia/buildbucket_util",
    "fuchsia/gerrit",
    "fuchsia/git",
    "fuchsia/gitiles",
    "flutter/subbuild",
    "flutter/swarming_retry",
    "recipe_engine/buildbucket",
    "recipe_engine/context",
    "recipe_engine/file",
    "recipe_engine/json",
    "recipe_engine/led",
    "recipe_engine/luci_config",
    "recipe_engine/path",
    "recipe_engine/properties",
    "recipe_engine/raw_io",
    "recipe_engine/step",
    "recipe_engine/swarming",
    "recipe_engine/time",
]

from PB.recipe_modules.flutter.recipe_testing.properties import InputProperties

PROPERTIES = InputProperties
