# Copyright 2020 The Chromium Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

from recipe_engine import recipe_test_api


class RepoUtilTestApi(recipe_test_api.RecipeTestApi):

  def flutter_environment_data(self, checkout_dir=''):
    """Provides flutter environment data for tests."""
    checkout_path = checkout_dir or self.m.path.checkout_dir
    dart_bin = checkout_path / 'bin/cache/dart-sdk/bin'
    flutter_bin = checkout_path / 'bin'
    return self.m.path.exists(dart_bin, flutter_bin)

  def flutter_environment_path(self, checkout_dir=''):
    """Provides flutter environment data for tests."""
    checkout_path = checkout_dir or self.m.path.checkout_dir
    dart_bin = checkout_path / 'bin/cache/dart-sdk/bin'
    flutter_bin = checkout_path / 'bin'
    return [dart_bin, flutter_bin]