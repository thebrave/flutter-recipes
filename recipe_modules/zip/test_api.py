# Copyright 2023 The Chromium Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

import json

from recipe_engine import recipe_test_api


class ZipTestApi(recipe_test_api.RecipeTestApi):  # pragma: no cover
  """Test api for zip module."""

  def namelist(self, name, output):
    """Generated namelist step data for testing.

    Args:
      name: The name of the step to generate step data for.
      output: A list of strings representing the names of files
        inside the zip file.
    """
    return self.override_step_data(
        name, stdout=self.m.json.output(output), retcode=0
    )
