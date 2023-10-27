# Copyright 2015 The Chromium Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

from contextlib import contextmanager

from recipe_engine import recipe_api


class GomaApi(recipe_api.RecipeApi):
  """GomaApi contains helper functions for using goma."""

  def __init__(self, props, *args, **kwargs):
    super().__init__(*args, **kwargs)

    self._enable_arbitrary_toolchains = props.enable_arbitrary_toolchains
    self._goma_dir = props.goma_dir
    self._jobs = props.jobs
    self._server = (
        props.server or "rbe-prod1.endpoints.fuchsia-infra-goma-prod.cloud.goog"
    )
    self._goma_started = False
    self._goma_log_dir = None

  @contextmanager
  def __call__(self):
    """Make context wrapping goma start/stop."""
    # Some environment needs to be set for both compiler_proxy and gomacc.
    # Push those variables used by both into context so the build can use
    # them.
    with self.m.context(env={
        # Allow user to override from the command line.
        "GOMA_TMP_DIR": self.m.context.env.get(
            "GOMA_TMP_DIR", self.m.path["cleanup"].join("goma")),
        "GOMA_USE_LOCAL": False,
    }):
      with self.m.step.nest("setup goma"):
        self._start()
      try:
        yield
      finally:
        if not self.m.runtime.in_global_shutdown:
          with self.m.step.nest("teardown goma"):
            self._stop()

  @property
  def jobs(self):
    """Returns number of jobs for parallel build using Goma."""
    if self._jobs:
      return self._jobs
    # Based on measurements, anything beyond 10*cpu_count won't improve
    # build speed. For safety, set an upper limit of 1000.
    return min(10 * self.m.platform.cpu_count, 1000)

  @property
  def goma_dir(self):
    if not self._goma_dir:
      self._ensure()
    return self._goma_dir

  @property
  def _stats_path(self):
    return self.m.path.join(self.goma_dir, "goma_stats.json")

  def initialize(self):
    self._goma_log_dir = self.m.path["cleanup"]
    if self.m.platform.is_win:
      self._enable_arbitrary_toolchains = True

  def set_path(self, path):
    self._goma_dir = path

  def _ensure(self):
    if self._goma_dir:
      return

    with self.m.step.nest("ensure goma"), self.m.context(infra_steps=True):
      self._goma_dir = self.m.path["cache"].join("goma", "client")
      if self.m.platform.is_mac:
        # On mac always use x64 package.
        # TODO(godofredoc): Remove this workaround and unfork once fuchsia has an arm package.
        package_path = "fuchsia/third_party/goma/client/mac-amd64"
      else:
        package_path = "fuchsia/third_party/goma/client/${platform}"

      self.m.cipd.ensure(
          self._goma_dir,
          self.m.cipd.EnsureFile().add_package(package_path, "integration"),
      )

  def _goma_ctl(self, step_name, args, **kwargs):
    """Run a goma_ctl.py subcommand."""
    env = {
        "GLOG_log_dir":
            self._goma_log_dir,
        "GOMA_CACHE_DIR":
            self.m.path["cache"].join("goma"),
        "GOMA_DEPS_CACHE_FILE":
            "goma_deps_cache",
        "GOMA_LOCAL_OUTPUT_CACHE_DIR":
            self.m.path["cache"].join("goma", "localoutputcache"),
        "GOMA_STORE_LOCAL_RUN_OUTPUT":
            True,
        "GOMA_SERVER_HOST":
            self._server,
        "GOMA_DUMP_STATS_FILE":
            self._stats_path,
        # The next power of 2 larger than the currently known largest
        # output (153565624) from the core.x64 profile build.
        "GOMA_MAX_SUM_OUTPUT_SIZE_IN_MB":
            256,
    }
    if self._enable_arbitrary_toolchains:
      env["GOMA_ARBITRARY_TOOLCHAIN_SUPPORT"] = True

    with self.m.context(env=env, infra_steps=True):
      return self.m.python3(
          step_name,
          [self.m.path.join(self.goma_dir, "goma_ctl.py")] + list(args),
          **kwargs,
      )

  def _run_jsonstatus(self):
    step = self._goma_ctl(
        "goma jsonstatus",
        ["jsonstatus", self.m.json.output(add_json_log=True)],
        step_test_data=lambda: self.m.json.test_api.output({"foo": "bar"}),
    )
    if step.json.output is None:
      step.presentation.status = self.m.step.WARNING

  def _upload_goma_stats(self):
    stats = self.m.file.read_json(
        "read goma_stats.json",
        self._stats_path,
        test_data={},
        include_log=False,
    )
    if not (self.m.buildbucket.builder_name and self.m.buildbucket.build.id):
      # Skip the upload if it does not have build input information.
      return
    stats["build_info"] = {
        "build_id": self.m.buildbucket.build.id,
        "builder": self.m.buildbucket.builder_name,
        "time_stamp": str(self.m.time.utcnow()),
        "time_stamp_int": self.m.time.ms_since_epoch(),
    }
    self.m.step.active_result.presentation.logs["json.output"
                                               ] = self.m.json.dumps(
                                                   stats, indent=4
                                               ).splitlines()

    self.m.bqupload.insert(
        step_name="upload goma stats to bigquery",
        project="fuchsia-infra",
        dataset="artifacts",
        table="builds_beta_goma",
        rows=[stats],
        ok_ret="all",
    )

  def _start(self):
    """Start goma compiler proxy."""
    assert not self._goma_started

    self._ensure()

    try:
      self._goma_ctl("start goma", ["restart"])
      self._goma_started = True
    except self.m.step.StepFailure:  # pragma: no cover
      deferred = []
      deferred.append(self.m.defer(self._run_jsonstatus))
      deferred.append(self.m.defer(self._goma_ctl, "stop goma (start failure)", ["stop"]))
      self.m.defer.collect(deferred)
      raise

  def _stop(self):
    """Stop goma compiler proxy."""
    assert self._goma_started

    deferred = []
    deferred.append(self.m.defer(self._run_jsonstatus))
    deferred.append(self.m.defer(self._goma_ctl, "goma stats", ["stat"]))
    deferred.append(self.m.defer(self._goma_ctl, "stop goma", ["stop"]))
    self.m.defer.collect(deferred)

    self._goma_started = False

    compiler_proxy_warning_log_path = self._goma_log_dir.join(
        "compiler_proxy.WARNING"
    )
    # Not all builds use goma, so it might not exist.
    self.m.path.mock_add_paths(compiler_proxy_warning_log_path)
    if self.m.path.exists(compiler_proxy_warning_log_path):
      try:
        self.m.file.read_text(
            "read goma_client warning log",
            compiler_proxy_warning_log_path,
            test_data="test log",
        )
      except self.m.step.StepFailure:  # pragma: no cover
        # Ignore. Not a big deal.
        pass

    self._upload_goma_stats()
