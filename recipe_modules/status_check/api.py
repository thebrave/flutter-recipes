# Copyright 2018 The Fuchsia Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

# This is only here because test_api.py can't stand alone.

from recipe_engine import recipe_api


class StatusCheckApi(recipe_api.RecipeApi):
  pass
