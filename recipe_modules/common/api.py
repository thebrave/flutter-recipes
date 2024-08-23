# Copyright 2021 The Chromium Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

import re

from recipe_engine import recipe_api


class CommonApi(recipe_api.RecipeApi):
  """Functions that are shared across multiple modules.

  Recipe modules cannot have circular dependencies, so code that will be
  called from multiple modules should be lifted here.

  This module should NOT depend on any other Flutter maintained modules
  (instead, the necessary behavior should be lifted to this module).
  """

  def is_release_candidate_branch(self, branch):
    """Returns true when the provided git branch name is that of a release
    candidate."""
    match = re.match(r'flutter-\d+\.\d+-candidate\.\d+', branch)
    return match is not None

  def branch_ref_to_branch_name(self, ref):
    """Transforms a git ref like "refs/heads/branch_name" to a branch name
    like "branch_name".
    """
    return ref.replace('refs/heads/', '')
