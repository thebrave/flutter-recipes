# Copyright 2022 The Chromium Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

# Module containing utility functions for building and testing
# monorepo checkouts combining Dart and Flutter

from recipe_engine import recipe_api


class MonorepoApi(recipe_api.RecipeApi):
  """Provides utilities to work with monorepo checkouts."""

  @property
  def is_monorepo_ci_build(self):
    commit = self.m.buildbucket.build.input.gitiles_commit
    return commit.project == 'monorepo'

  @property
  def is_monorepo_try_build(self):
    input = self.m.buildbucket.build.input
    return (
        not input.gitiles_commit.project and input.gerrit_changes and
        input.gerrit_changes[0].host == 'dart-review.googlesource.com' and
        input.gerrit_changes[0].project == 'sdk'
    )

  @property
  def try_build_identifier(self):
    """Creates a unique identifier to use as an upload path for artifacts.

    There is no commit hash usable for this, because a Gerrit try job
    patches the monorepo HEAD with an uncommitted patch from the Gerrit CL.
    The flutter framework's bin/internal/engine.version can be any string,
    and will be used to construct the download path for engine artifacts.

    Args:
      none

    Returns:
      The buildbucket id of the engine_v2/engine_v2 coordinator build.
"""
    buildbucket_id = self.m.buildbucket.build.id
    if buildbucket_id:
      self.m.step.empty('get buildbucket id', step_text=str(buildbucket_id))
    else:
      self.m.step.empty(
          'get buildbucket id',
          status='INFRA_FAILURE',
          step_text='Try job has no buildbucket id'
      )
    return str(buildbucket_id)
