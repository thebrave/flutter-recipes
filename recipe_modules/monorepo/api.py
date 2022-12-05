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
