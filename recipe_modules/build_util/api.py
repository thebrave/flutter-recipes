# Copyright 2020 The Chromium Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

import multiprocessing

from recipe_engine import recipe_api

# The default latency (seconds) to collect RBE logs.
COLLECT_RBE_LOGS_LATENCY_SECS = 1800


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
    gn_cmd = ['python3', checkout_path / 'flutter/tools/gn']
    self.use_goma = '--no-goma' not in gn_args
    self.use_rbe = '--no-rbe' not in gn_args
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

    # For non goma/rbe builds, set -j to the number of cores.
    if not self.use_goma and not self.use_rbe:
      return 5 if self._test_data.enabled else cores

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

  def _build_rbe(
      self, config, checkout_path, targets, tool, rbe_working_path, env
  ):
    """Builds using ninja and rbe.

    Args:
      config(str): A string with the configuration to build.
      checkout_path(Path): A path object with the checkout location.
      targets(list): A list of strings with the ninja targets to build.
      tool(path): Path to the ninja tool.
      rbe_working_path(path): Path to the rbe working directory.
    """
    assert rbe_working_path
    build_dir = checkout_path / f'out/{config}'
    rbe_jobs = self._calculate_j_value()
    ninja_args = [tool, '-j', rbe_jobs, '-C', build_dir]
    ninja_args.extend(targets)
    with self.m.rbe(
        working_path=rbe_working_path,
        collect_rbe_logs_latency=self.m.properties.get(
            'collect_rbe_logs_latency',
            COLLECT_RBE_LOGS_LATENCY_SECS)), self.m.depot_tools.on_path():
      try:
        name = 'build %s' % ' '.join([config] + list(targets))
        self.m.step(name, ninja_args)
      except self.m.step.StepFailure:
        self._upload_crash_reproducer(env)
        raise

  def _build_goma(self, config, checkout_path, targets, tool, env):
    """Builds using ninja and goma.

    Args:
      config(str): A string with the configuration to build.
      checkout_path(Path): A path object with the checkout location.
      targets(list): A list of strings with the ninja targets to build.
    """
    build_dir = checkout_path / f'out/{config}'
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

  def _build_no_goma_rbe(self, config, checkout_path, targets, tool, env):
    """Builds using ninja without goma/rbe.

    Args:
      config(str): A string with the configuration to build.
      checkout_path(Path): A path object with the checkout location.
      targets(list): A list of string with the ninja targets to build.
    """
    build_dir = checkout_path / f'out/{config}'
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
          test_data=(clang_crash_diagnostics_dir / "foo.sh",),
      )
      for reproducer in reproducers:
        base = self.m.path.splitext(self.m.path.basename(reproducer))[0]
        files = self.m.file.glob_paths(
            f"find {base} files",
            clang_crash_diagnostics_dir,
            base + ".*",
            test_data=(clang_crash_diagnostics_dir / "foo.sh",),
        )
        for f in files:
          self.m.file.copy(
              'Copy crash reproduce file %s' % f, f, flutter_logs_dir
          )
    # Copy the llvm_<YYYY-MM-DD-HHMMSS>_<hostname>.crash file to log dir.
    copy_script = self.resource('copy_crash.sh')
    self.m.step('Set execute permission', ['chmod', '755', copy_script])
    self.m.step('copy crash file', [copy_script, flutter_logs_dir])

  def build(self, config, checkout_path, targets, env, rbe_working_path=None):
    """Builds using ninja.

    Args:
      config(str): A string with the configuration to build.
      checkout_path(Path): A path object with the checkout location.
      targets(list): A list of string with the ninja targets to build.
      rbe_working_path(path): Path to rbe working directory.
    """
    ninja_exe = 'ninja.exe' if self.m.platform.is_win else 'ninja'
    ninja_path = checkout_path / 'flutter/third_party/ninja' / ninja_exe
    if not self.m.path.exists(ninja_path):
      ninja_path = self.m.path.dirname(self.m.path.dirname(checkout_path)) / 'third_party/ninja' / ninja_exe

    if self.use_goma:
      self._build_goma(config, checkout_path, targets, ninja_path, env)
    else:
      if self.use_rbe:
        self._build_rbe(
            config, checkout_path, targets, ninja_path, rbe_working_path, env
        )
      else:
        self._build_no_goma_rbe(config, checkout_path, targets, ninja_path, env)
