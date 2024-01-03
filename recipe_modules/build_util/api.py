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
    self.use_goma = True
    self.use_rbe = False

  def run_gn(self, gn_args, checkout_path):
    """Run a gn command with the given arguments.

    Args:
      gn_args(list): A list of strings to be passed to the gn command.
      checkout_path(Path): A path object with the checkout location.
    """
    gn_cmd = ['python3', checkout_path.join('flutter/tools/gn')]
    self.use_goma = '--no-goma' not in gn_args
    self.use_rbe = '--rbe' in gn_args
    if self.m.properties.get('no_lto', False) and '--no-lto' not in gn_args:
      gn_args += ('--no-lto',)
    gn_cmd.extend(gn_args)
    if self.use_goma:
      env = {'GOMA_DIR': self.m.goma.goma_dir}
      # Some gn configurations expect depot_tools in path. e.g. vs_studio
      # tool_chain update script.
      with self.m.goma(), self.m.context(env=env), self.m.depot_tools.on_path():
        self.m.step('gn %s' % ' '.join(gn_args), gn_cmd)
    else:
      with self.m.depot_tools.on_path():
        self.m.step('gn %s' % ' '.join(gn_args), gn_cmd)

  def _calculate_j_value(self):
    """Calculates concurrent jobs value for the current machine."""
    cores = multiprocessing.cpu_count()

    # For non goma builds, set -j to the number of cores.
    if not self.use_goma:
      return 5 if self._test_data.enabled else cores

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

  def _build_rbe(self, config, checkout_path, targets, tool, rbe_working_path):
    """Builds using ninja and rbe.

    Args:
      config(str): A string with the configuration to build.
      checkout_path(Path): A path object with the checkout location.
      targets(list): A list of strings with the ninja targets to build.
      tool(path): Path to the ninja tool.
      rbe_working_path(path): Path to the rbe working directory.
    """
    assert rbe_working_path
    build_dir = checkout_path.join('out/%s' % config)
    rbe_jobs = self.m.properties.get('rbe_jobs') or self._calculate_j_value()
    ninja_args = [tool, '-j', rbe_jobs, '-C', build_dir]
    ninja_args.extend(targets)
    with self.m.rbe(working_path=rbe_working_path
                   ), self.m.depot_tools.on_path():
      name = 'build %s' % ' '.join([config] + list(targets))
      self.m.step(name, ninja_args)

  def _build_goma(self, config, checkout_path, targets, tool, env):
    """Builds using ninja and goma.

    Args:
      config(str): A string with the configuration to build.
      checkout_path(Path): A path object with the checkout location.
      targets(list): A list of strings with the ninja targets to build.
    """
    build_dir = checkout_path.join('out/%s' % config)
    goma_jobs = self.m.properties.get('goma_jobs') or self._calculate_j_value()
    ninja_args = [tool, '-j', goma_jobs, '-C', build_dir]
    ninja_args.extend(targets)
    with self.m.goma(), self.m.depot_tools.on_path():
      try:
        name = 'build %s' % ' '.join([config] + list(targets))
        self.m.step(name, ninja_args)
      except self.m.step.StepFailure:
        self._upload_crash_reproducer(env)
        raise

  def _build_no_goma(self, config, checkout_path, targets, tool, env):
    """Builds using ninja without goma.

    Args:
      config(str): A string with the configuration to build.
      checkout_path(Path): A path object with the checkout location.
      targets(list): A list of string with the ninja targets to build.
    """
    build_dir = checkout_path.join('out/%s' % config)
    concurrent_jobs = self.m.properties.get('concurrent_jobs'
                                           ) or self._calculate_j_value()
    ninja_args = [tool, '-C', build_dir, '-j', concurrent_jobs]
    ninja_args.extend(targets)
    with self.m.depot_tools.on_path():
      try:
        name = 'build %s' % ' '.join([config] + list(targets))
        self.m.step(name, ninja_args)
      except self.m.step.StepFailure:
        self._upload_crash_reproducer(env)
        raise

  def _upload_crash_reproducer(self, env):
    """Uploads crash reproducer files to GCS when clang crash happens."""
    clang_crash_diagnostics_dir = env['CLANG_CRASH_DIAGNOSTICS_DIR']
    flutter_logs_dir = env['FLUTTER_LOGS_DIR']
    with self.m.step.nest("upload crash reproducer"), self.m.context(
        infra_steps=True):
      reproducers = self.m.file.glob_paths(
          "find reproducers",
          clang_crash_diagnostics_dir,
          "*.sh",
          test_data=(clang_crash_diagnostics_dir.join("foo.sh"),),
      )
      for reproducer in reproducers:
        base = self.m.path.splitext(self.m.path.basename(reproducer))[0]
        files = self.m.file.glob_paths(
            f"find {base} files",
            clang_crash_diagnostics_dir,
            base + ".*",
            test_data=(clang_crash_diagnostics_dir.join("foo.sh"),),
        )
        for f in files:
          self.m.file.copy(
              'Copy crash reproduce file %s' % f, f, flutter_logs_dir
          )

  def build(self, config, checkout_path, targets, env, rbe_working_path=None):
    """Builds using ninja.

    Args:
      config(str): A string with the configuration to build.
      checkout_path(Path): A path object with the checkout location.
      targets(list): A list of string with the ninja targets to build.
      rbe_working_path(path): Path to rbe working directory.
    """
    ninja_path = checkout_path.join('flutter', 'third_party', 'ninja', 'ninja')
    if self.use_rbe:
      self._build_rbe(
          config, checkout_path, targets, ninja_path, rbe_working_path
      )
    else:
      if self.use_goma:
        self._build_goma(config, checkout_path, targets, ninja_path, env)
      else:
        self._build_no_goma(config, checkout_path, targets, ninja_path, env)
