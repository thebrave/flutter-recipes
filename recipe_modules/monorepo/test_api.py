# Copyright 2022 The Chromium Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

from recipe_engine import recipe_test_api


class MonorepoTestApi(recipe_test_api.RecipeTestApi):

  def ci_build(self, git_ref='refs/heads/main'):
    """An example monorepo ci build"""
    return self.m.buildbucket.ci_build(
        project='dart',
        bucket='ci.sandbox',
        builder='monorepo_builder',
        git_repo='https://dart.googlesource.com/monorepo',
        git_ref=git_ref,
        revision='a' * 40,
        build_number=123,
    )

  def try_build(self, **kwargs):
    """An example monorepo try build"""
    return self.m.buildbucket.try_build(
        project='dart',
        bucket='ci.sandbox',
        builder='monorepo_builder_try',
        # Used to construct a Gerrit CL, not a Gitiles commit.
        git_repo='https://dart.googlesource.com/sdk',
        change_number=9425,
        patch_set=3,
        **kwargs
    )
