# Copyright 2020 The Fuchsia Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

from PB.recipe_modules.flutter.goma.properties import InputProperties

DEPS = [
    "fuchsia/bqupload",
    "fuchsia/daemonizer",
    "fuchsia/python3",
    "recipe_engine/buildbucket",
    "recipe_engine/cipd",
    "recipe_engine/context",
    "recipe_engine/file",
    "recipe_engine/json",
    "recipe_engine/path",
    "recipe_engine/platform",
    "recipe_engine/runtime",
    "recipe_engine/step",
    "recipe_engine/time",
]

PROPERTIES = InputProperties
