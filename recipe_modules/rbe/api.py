# Copyright 2021 The Fuchsia Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

from enum import Enum
from contextlib import contextmanager

from recipe_engine import recipe_api

RECLIENT_CXX_WRAPPER = "reclient-cxx-wrapper.sh"

# For builds using the goma input processor, sometimes the deps cache file is
# too big for the default setting.  So just set the max file size permitted to
# be large enough.
_DEPS_CACHE_MAX_MB = "512"


class RbeApi(recipe_api.RecipeApi):
  """RemoteExecutionApi contains helper functions for using remote execution
    services via re-client/re-proxy."""

  class AbsolutePathPolicy(Enum):
    """This controls how absolute paths are to be treated.

        The choice impacts how reproxy and rewrapper are invoked.

        Choices:
          REJECT: remote commands using local absolute paths will fail.
            rewrapper --canonicalize_working_dir=true.
              This allows cache sharing between different build output
              directories (under exec_root) at the same depth.
            reproxy: no InputPathAbsoluteRoot

          RELATIVIZE: rewrite commands using relative paths, using a wrapper.
            Relative paths are remote-execution friendly, while absolute paths
            will likely fail.  cmake builds are known to use absolute paths.
            Relativized commands are better for caching across build
            environments, but the wrapper script incurs some overhead.
            rewrapper --canonicalize_working_dir=true.
            reproxy: no InputPathAbsoluteRoot

          ALLOW: Force the remote environment to mimic local paths.
            This allows commands with absolute paths to work,
            at the expense of being able to cache across build environments.
            This option can help cmake builds work remotely.
            rewrapper --canonicalize_working_dir=false.
            reproxy: --platform InputPathAbsoluteRoot=exec_root
        """

    REJECT = 1
    RELATIVIZE = 2
    ALLOW = 3

  def __init__(self, props, *args, **kwargs):
    super().__init__(*args, **kwargs)

    self._reclient_path = None
    self._platform = props.platform
    self._instance = props.instance

    # Default: let commands that use absolute paths fail remote execution.
    # For best caching performance, restrict remote execution commands
    # to use only relative paths.
    self._absolute_path_policy = self.AbsolutePathPolicy.REJECT

    if not self._platform and self._test_data.enabled:
      self._platform = "fake_rbe_platform"
    if not self._instance and self._test_data.enabled:
      self._instance = "fake_rbe_instance"
    self._log_format = props.log_format or "reducedtext"
    self._started = False

  @contextmanager
  def __call__(
      self,
      reclient_path=None,
      config_path=None,
      working_path=None,
      absolute_path_policy=AbsolutePathPolicy.REJECT,
  ):
    """Make context wrapping reproxy start/stop.

        Args:
          reclient_path (Path): if set, use this Path to reclient tools,
            otherwise, automatically use the Path to a loaded CIPD package.
          config_path (Path): The config file within the checkout.
            In the case of a Fuchsia checkout, this should be set to the path
            referenced by $FUCHSIA_OUT_DIR/rbe_config.json as reported by
            `gn gen`.
          absolute_path_policy (AbsolutePathPolicy): See enum definition.

        Raises:
            StepFailure or InfraFailure if it fails to start/stop.
        """
    if reclient_path:
      self._reclient_path = reclient_path
    else:
      self._reclient_path = self._ensure_reclient_path

    assert self._reclient_path
    assert self._instance, "No RBE backend in builder properties."

    # Save current value of infra_step so we can reset it when we
    # yield back.
    is_infra_step = self.m.context.infra_step

    # Separate invocations of RBE tools should use unique paths to avoid
    # conflicts between log/metric files.
    working_dir = working_path

    saved_absolute_path_policy = self._absolute_path_policy
    self._absolute_path_policy = absolute_path_policy

    with self.m.context(env=self._environment(working_dir), infra_steps=True):
      try:
        self._start(config_path=config_path)
        with self.m.context(infra_steps=is_infra_step):
          yield
      finally:
        if not self.m.runtime.in_global_shutdown:
          self._stop(working_dir=working_dir, config_path=config_path)
        self._absolute_path_policy = saved_absolute_path_policy

  @property
  def _ensure_reclient_path(self):
    return self.m.ensure_tool(
        "reclient", self.resource("tool_manifest.json"), executable_path=""
    )

  @property
  def _bootstrap_path(self):
    assert self._reclient_path
    return self._reclient_path.join("bootstrap")

  def _environment(self, working_dir):
    cache_dir = self.m.path["cache"].join("rbe")
    deps_cache_dir = cache_dir.join("deps")
    self.m.file.ensure_directory("create rbe cache dir", deps_cache_dir)
    # Environment. The source of truth for remote execution configuration
    # is the Fuchsia tree (see $FUCHSIA_OUT_DIR/rbe_config.json). These
    # values are used to modify the configuration in Infrastructure when
    # appropriate. These should not be used to modify the behavior of the
    # build in a meaningful way.
    return {
        "RBE_service": "remotebuildexecution.googleapis.com:443",
        # TODO(fangism): sync docker image with that used in Fuchsia
        "RBE_platform": self._platform,
        # Override default instance. Infrastructure uses different RBE
        # backends for different environments.
        "RBE_instance": self._instance,
        # Set deps cache path.
        "RBE_enable_deps_cache": "true",
        "RBE_cache_dir": deps_cache_dir,
        "RBE_deps_cache_max_mb": _DEPS_CACHE_MAX_MB,
        # Set preferred log format for reproxy.
        "RBE_log_format": self._log_format,
        # Set log paths within the task working directory.
        "RBE_log_dir": working_dir,
        "RBE_output_dir": working_dir,
        "RBE_proxy_log_dir": working_dir,
        "RBE_server_address": f"unix://{working_dir.join('reproxy.sock')}",
        "RBE_socket_path": working_dir.join("reproxy.sock"),
        # Use GCE credentials by default. Infrastructure presents an
        # emulated GCE metadata server in all environments for uniformity.
        "RBE_use_application_default_credentials": "false",
        "RBE_use_gce_credentials": "true",
    }

  @property
  def _reproxy_path(self):
    assert self._reclient_path
    return self._reclient_path.join("reproxy")

  def _start(self, config_path):
    """Start reproxy."""
    assert not self._started

    with self.m.step.nest("setup remote execution"):
      cmd = [self._bootstrap_path, f"--re_proxy={self._reproxy_path}"]
      if config_path:
        cmd += [f"--cfg={config_path}"]
      self.m.step("start reproxy", cmd)
      self._started = True

  def _stop(self, working_dir, config_path):
    """Stop reproxy."""
    with self.m.step.nest("teardown remote execution"):
      cmd = [self._bootstrap_path, "--shutdown"]
      if config_path:
        cmd += [f"--cfg={config_path}"]
      try:
        self.m.step("stop reproxy", cmd)
        self._started = False
      finally:
        # reproxy/rewrapper/bootstrap record various log information in
        # a number of locations. At the time of this implementation,
        # the following log files are used:
        # 1. bootstrap.<INFO|WARNING|ERROR|FATAL> is standard logging
        # for `bootstrap`. Each log file includes more severe logging
        # levels, e.g. bootstrap.WARNING includes WARNING, ERROR & FATAL
        # log messages.
        # 2. rbe_metrics.txt is the text representation of a proto
        # message that describes metrics related to the rbe execution.
        # 3. reproxy.<INFO|WARNING|ERROR|FATAL> is standard logging for
        # `reproxy`. See notes in #1 for more details.
        # 4. reproxy_log.txt is the log file that records all info
        # about all actions that are processed through reproxy.
        # 5. reproxy_outerr.log is merged stderr/stdout of `reproxy`.
        # 6. rewrapper.<INFO|WARNING|ERROR|FATAL> is standard logging
        # for `rewrapper`. See notes in #1 for more details.
        # 7. reproxy-gomaip.<INFO|WARNING|ERROR|FATAL> is logging
        # for `gomaip` which is the input processor used by `reclient`
        # for finding dependencies of `clang` compile invocations.
        #
        # We extract the WARNING log messages for each portion of the
        # local rbe client as well as reproxy stdout/stderr and metrics
        # from the build by default. If further debugging is required,
        # you could increase the verbosity of log messages that we
        # retain in logdog or add the full reproxy_log.txt log file to
        # the list of outputs.
        diagnostic_outputs = [
            "bootstrap.WARNING",
            "rbe_metrics.txt",
            "reproxy.WARNING",
            "reproxy-gomaip.WARNING",
            "reproxy_outerr.log",
            "rewrapper.WARNING",
        ]

        for output in diagnostic_outputs:
          path = working_dir.join(output)
          # Not all builds use rbe, so it might not exist.
          self.m.path.mock_add_paths(path)
          if self.m.path.exists(path):
            # Read the log so it shows up in Milo for debugging.
            self.m.file.read_text(f"read {output}", path)

        # reproxy also produces a log file of all the actions which
        # it handles including more detailed debugging information
        # useful for debugging.
        rpl_ext = {
            "text": "rpl",
            "reducedtext": "rrpl",
        }[self._log_format]
        rpl_file_glob = f"*.{rpl_ext}"
        rpl_paths = self.m.file.glob_paths(
            name=f"find {rpl_ext} files",
            source=working_dir,
            pattern=rpl_file_glob,
            test_data=[
                f"reproxy_2021-10-16_22_52_23.{rpl_ext}",
            ],
        )

        # More than 1 rpl file is likely a bug but we can punt until
        # that breaks someone.
        for p in rpl_paths:
          self.m.path.mock_add_paths(p)
          # Not all builds use rbe, so it might not exist.
          if self.m.path.exists(p):
            # Read the log so it shows up in Milo for debugging.
            self.m.file.read_text(f"read {self.m.path.basename(p)}", p)
