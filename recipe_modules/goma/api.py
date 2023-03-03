# Copyright 2015 The Chromium Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

from contextlib import contextmanager

from recipe_engine import recipe_api


class GomaApi(recipe_api.RecipeApi):
    """GomaApi contains helper functions for using goma."""

    def __init__(self, props, *args, **kwargs):
        super().__init__(*args, **kwargs)

        self._is_local = bool(props.goma_dir)
        self._enable_arbitrary_toolchains = props.enable_arbitrary_toolchains
        self._goma_dir = props.goma_dir
        self._goma_log_dir = None
        self._jobs = props.jobs
        self._server = (
            props.server or "rbe-prod1.endpoints.fuchsia-infra-goma-prod.cloud.goog"
        )
        self._use_http2 = props.use_http2

        self._goma_context = None

        self._goma_started = False

        self._goma_ctl_env = {}
        self._http2_proxy_port = 8199
        self._http2_proxy_pid_file = None
        self._recommended_jobs = None
        self._jsonstatus = None

    @property
    def json_path(self):
        assert self._goma_dir
        return self.m.path.join(self._goma_dir, "jsonstatus")

    @property
    def jsonstatus(self):  # pragma: no cover
        return self._jsonstatus

    @property
    def jobs(self):
        """Returns number of jobs for parallel build using Goma.

        Uses value from property "$infra/goma:{\"jobs\": JOBS}" if
        configured (typically in cr-buildbucket.cfg), else defaults to
        `recommended_goma_jobs`.
        """
        return self._jobs or self.recommended_goma_jobs

    @property
    def recommended_goma_jobs(self):
        """Return the recommended number of jobs for parallel build using Goma.

        Prefer to use just `goma.jobs` and configure it through default builder
        properties in cr-buildbucket.cfg.

        This function caches the _recommended_jobs.
        """
        if self._recommended_jobs is None:
            # When goma is used, 10 * self.m.platform.cpu_count is basically good in
            # various situations according to our measurement. Build speed won't
            # be improved if -j is larger than that.
            #
            # For safety, we'd like to set the upper limit to 1000.
            self._recommended_jobs = min(10 * self.m.platform.cpu_count, 1000)

        return self._recommended_jobs

    @property
    def goma_ctl(self):
        return self.m.path.join(self._goma_dir, "goma_ctl.py")

    @property
    def goma_dir(self):
        assert self._goma_dir
        return self._goma_dir

    @property
    def _stats_path(self):
        assert self._goma_dir
        return self.m.path.join(self._goma_dir, "goma_stats.json")

    def set_path(self, path):
        self._goma_dir = path

    def ensure(self, canary=False):
        if self._is_local:
            return self._goma_dir

        with self.m.step.nest("ensure goma") as step_result:
            if canary:
                step_result.presentation.step_text = "using canary goma client"
                step_result.presentation.status = self.m.step.WARNING

            with self.m.context(infra_steps=True):
                pkgs = self.m.cipd.EnsureFile()
                ref = "integration"
                if canary:
                    ref = "candidate"
                pkgs.add_package("flutter/third_party/goma/client/${platform}", ref)
                self._goma_dir = self.m.path["cache"].join("goma", "client")

                self.m.cipd.ensure(self._goma_dir, pkgs)
                return self._goma_dir

    def _run_jsonstatus(self):
        with self.m.context(env=self._goma_ctl_env):
            jsonstatus_result = self.m.python3(
                "goma jsonstatus",
                [
                    self.goma_ctl,
                    "jsonstatus",
                    self.m.json.output(leak_to=self.json_path),
                ],
                step_test_data=lambda: self.m.json.test_api.output(
                    data={
                        "notice": [
                            {
                                "infra_status": {
                                    "ping_status_code": 200,
                                    "num_user_error": 0,
                                }
                            }
                        ]
                    }
                ),
            )

        self._jsonstatus = jsonstatus_result.json.output
        if self._jsonstatus is None:
            jsonstatus_result.presentation.status = self.m.step.WARNING

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
        self.m.step.active_result.presentation.logs["json.output"] = self.m.json.dumps(
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

    def start(self):
        """Start goma compiler_proxy.

        A user MUST execute ensure_goma beforehand. It is user's
        responsibility to handle failure of starting compiler_proxy.
        """
        assert self._goma_dir
        assert not self._goma_started

        with self.m.step.nest("setup goma") as nested_result:
            # Allow user to override from the command line.
            self._goma_ctl_env["GOMA_TMP_DIR"] = self.m.context.env.get(
                "GOMA_TMP_DIR", self.m.path["cleanup"].join("goma")
            )
            self._goma_ctl_env["GOMA_USE_LOCAL"] = False
            self._goma_log_dir = self.m.path["cleanup"]
            self._goma_ctl_env["GLOG_log_dir"] = self._goma_log_dir

            self._goma_ctl_env["GOMA_CACHE_DIR"] = self.m.path["cache"].join("goma")
            self._goma_ctl_env["GOMA_DEPS_CACHE_FILE"] = "goma_deps_cache"
            self._goma_ctl_env["GOMA_LOCAL_OUTPUT_CACHE_DIR"] = self.m.path[
                "cache"
            ].join("goma", "localoutputcache")
            self._goma_ctl_env["GOMA_STORE_LOCAL_RUN_OUTPUT"] = True

            if self._use_http2:
                self._http2_proxy_pid_file = self.m.path["tmp_base"].join(
                    "goma_http2_proxy.pid"
                )
                self.m.daemonizer.start(
                    self._http2_proxy_pid_file,
                    [
                        self._goma_dir.join("http_proxy"),
                        "-server-host",
                        self._server,
                        "-port",
                        self._http2_proxy_port,
                    ],
                )
                self._goma_ctl_env["GOMA_SERVER_HOST"] = "127.0.0.1"
                self._goma_ctl_env["GOMA_SERVER_PORT"] = str(self._http2_proxy_port)
                self._goma_ctl_env["GOMA_USE_SSL"] = "false"
            else:
                self._goma_ctl_env["GOMA_SERVER_HOST"] = self._server

            if self.m.platform.is_win:
                self._enable_arbitrary_toolchains = True
            if self._enable_arbitrary_toolchains:
                self._goma_ctl_env[
                    "GOMA_ARBITRARY_TOOLCHAIN_SUPPORT"
                ] = self._enable_arbitrary_toolchains

            self._goma_ctl_env["GOMA_DUMP_STATS_FILE"] = self._stats_path
            # The next power of 2 larger than the currently known largest
            # output (153565624) from the core.x64 profile build.
            self._goma_ctl_env["GOMA_MAX_SUM_OUTPUT_SIZE_IN_MB"] = 256

            goma_ctl_env = self._goma_ctl_env.copy()

            try:
                with self.m.context(env=goma_ctl_env):
                    self.m.python3(
                        "start goma",
                        [self.goma_ctl, "restart"],
                        infra_step=True,
                    )
                self._goma_started = True
            except self.m.step.InfraFailure as e:  # pragma: no cover
                with self.m.step.defer_results():
                    self._run_jsonstatus()
                    if self._use_http2:
                        self.m.daemonizer.stop(self._http2_proxy_pid_file)

                    with self.m.context(env=self._goma_ctl_env):
                        self.m.python3(
                            "stop goma (start failure)",
                            [self.goma_ctl, "stop"],
                        )
                nested_result.presentation.status = self.m.step.EXCEPTION
                raise e

    def stop(self):
        """Stop goma compiler_proxy.

        A user MUST execute start beforehand.
        It is user's responsibility to handle failure of stopping compiler_proxy.

        Raises:
            StepFailure if it fails to stop goma.
        """
        assert self._goma_dir
        assert self._goma_started

        with self.m.step.nest("teardown goma") as nested_result:
            try:
                with self.m.step.defer_results():
                    self._run_jsonstatus()
                    if self._use_http2:
                        self.m.daemonizer.stop(self._http2_proxy_pid_file)

                    with self.m.context(env=self._goma_ctl_env):
                        self.m.python3("goma stats", [self.goma_ctl, "stat"])
                        self.m.python3("stop goma", [self.goma_ctl, "stop"])
                self._goma_started = False

                if self._goma_log_dir:
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
                            nested_result.presentation.status = self.m.step.EXCEPTION
                # Upload stats to BigQuery
                self._upload_goma_stats()

            except self.m.step.StepFailure:
                nested_result.presentation.status = self.m.step.EXCEPTION
                raise

    @contextmanager
    def build_with_goma(self):
        """Make context wrapping goma start/stop.

        Raises:
            StepFailure or InfraFailure if it fails to build.
        """
        self.start()
        # Some environment needs to be set for both compiler_proxy and gomacc.
        # Push those variables used by both into context so the build can use
        # them.
        gomacc_env_vars = ["GOMA_TMP_DIR", "GOMA_USE_LOCAL"]
        gomacc_env = {
            k: v for (k, v) in self._goma_ctl_env.items() if k in gomacc_env_vars
        }

        with self.m.context(env=gomacc_env):
            try:
                yield
            finally:
                if not self.m.runtime.in_global_shutdown:
                    self.stop()
