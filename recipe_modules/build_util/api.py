# Copyright 2020 The Chromium Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

import multiprocessing
import sys

from recipe_engine import recipe_api


class BuildUtilApi(recipe_api.RecipeApi):
  """Gn and Ninja wrapper functions."""

  def __init__(self, *args, **kwargs):
    super(BuildUtilApi, self).__init__(*args, **kwargs)
    self._initialized = None
    self.use_goma = True

  def _initialize(self):
    if self._initialized:
      return
    if self.use_goma:
      self.m.goma.ensure()
    self._initialized = True

  def run_gn(self, gn_args, checkout_path):
    """Run a gn command with the given arguments.

    Args:
      gn_args(list): A list of strings to be passed to the gn command.
      checkout_path(Path): A path object with the checkout location.
    """
    gn_cmd = ['python3', checkout_path.join('flutter/tools/gn')]
    self.use_goma = False if '--no-goma' in gn_args else True
    self._initialize()
    if self.m.properties.get('no_lto', False) and '--no-lto' not in gn_args:
      gn_args += ('--no-lto',)
    gn_cmd.extend(gn_args)
    env = {}
    if self.use_goma:
      self.m.goma.set_path(self.m.goma.goma_dir)
      env = {'GOMA_DIR': self.m.goma.goma_dir}
    with self.m.context(env=env):
      self.m.step('gn %s' % ' '.join(gn_args), gn_cmd)

  def _calculate_j_value(self):
    """Calculates concurrent jobs value for the current machine."""
    cores = multiprocessing.cpu_count()
    # Assume simultaneous multithreading and therefore half as many cores as
    # logical processors.
    cores //= 2
    default_core_multiplier = 80
    j_value = cores * default_core_multiplier
    if self.m.platform.is_win:
      # On windows, j value higher than 1000 does not improve build
      # performance.
      j_value = min(j_value, 1000)
    elif self.m.platform.is_mac:
      # On macOS, j value higher than 800 causes 'Too many open files' error
      # (crbug.com/936864).
      j_value = min(j_value, 800)
    return 200 if self._test_data.enabled else j_value

  def _build_goma(self, config, checkout_path, targets, tool):
    """Builds using ninja and goma.

    Args:
      config(str): A string with the configuration to build.
      checkout_path(Path): A path object with the checkout location.
      targets(list): A list of string with the ninja targets to build.
    """
    self._initialize()
    build_dir = checkout_path.join('out/%s' % config)
    goma_jobs = self.m.properties.get('goma_jobs') or self._calculate_j_value()
    ninja_args = [tool, '-j', goma_jobs, '-C', build_dir]
    ninja_args.extend(targets)
    self.m.goma.set_path(self.m.goma.goma_dir)
    env = {'GOMA_DIR': self.m.goma.goma_dir}
    with self.m.context(
        env=env), self.m.goma.build_with_goma(), self.m.depot_tools.on_path():
      name = 'build %s' % ' '.join([config] + list(targets))
      self.m.step(name, ninja_args)

  def _build_no_goma(self, config, checkout_path, targets, tool):
    """Builds using ninja without goma.

    Args:
      config(str): A string with the configuration to build.
      checkout_path(Path): A path object with the checkout location.
      targets(list): A list of string with the ninja targets to build.
    """
    self._initialize()
    build_dir = checkout_path.join('out/%s' % config)
    concurrent_jobs = self.m.properties.get('concurrent_jobs') or self._calculate_j_value()
    ninja_args = [tool, '-C', build_dir, '-j', concurrent_jobs]
    ninja_args.extend(targets)
    with self.m.depot_tools.on_path():
      name = 'build %s' % ' '.join([config] + list(targets))
      self.m.step(name, ninja_args)

  def build(self, config, checkout_path, targets):
    """Builds using ninja.

    Args:
      config(str): A string with the configuration to build.
      checkout_path(Path): A path object with the checkout location.
      targets(list): A list of string with the ninja targets to build.
    """
    ninja_path = checkout_path.join('flutter', 'third_party', 'ninja', 'ninja')
    if self.use_goma:
      self._build_goma(config, checkout_path, targets, ninja_path)
    else:
      self._build_no_goma(config, checkout_path, targets, ninja_path)
