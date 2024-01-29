# Copyright 2018 The Chromium Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""The `osx_sdk` module provides safe functions to access a semi-hermetic
XCode installation.

Available only to Google-run bots."""

from contextlib import contextmanager

from recipe_engine import recipe_api

# Rationalized from https://en.wikipedia.org/wiki/Xcode.
#
# Maps from OS version to the maximum supported version of Xcode for that OS.
#
# Keep this sorted by OS version.
_DEFAULT_VERSION_MAP = [('10.12.6', '9c40b'), ('10.13.2', '9f2000'),
                        ('10.13.6', '10b61'), ('10.14.3', '10g8'),
                        ('10.14.4', '11b52'), ('10.15.4', '12a7209')]

_RUNTIMESPATH = [
    'Contents', 'Developer', 'Platforms', 'iPhoneOS.platform', 'Library',
    'Developer', 'CoreSimulator', 'Profiles', 'Runtimes'
]

# This CIPD source contains Xcode and iOS runtimes create and maintained by the
# Flutter team.
_FLUTTER_XCODE_CIPD = 'flutter_internal/ios/xcode'

# This CIPD source contains Xcode and iOS runtimes created and maintained by the
# Chrome team.
_INFRA_XCODE_CIPD = 'infra_internal/ios/xcode'


class OSXSDKApi(recipe_api.RecipeApi):
  """API for using OS X SDK distributed via CIPD."""

  def __init__(self, sdk_properties, *args, **kwargs):
    super(OSXSDKApi, self).__init__(*args, **kwargs)
    self._sdk_properties = sdk_properties
    self._sdk_version = None
    self._runtime_versions = None
    self._tool_pkg = 'infra/tools/mac_toolchain/${platform}'
    self._tool_ver = 'latest'
    self._cleanup_cache = False
    self.macos_13_or_later = False
    self._xcode_cipd_package_source = None

  def initialize(self):
    """Initializes xcode, and ios versions.

    Versions are usually passed as recipe properties but if not then defaults
    are used.
    """
    if not self.m.platform.is_mac:
      return

    if 'cleanup_cache' in self._sdk_properties:
      self._cleanup_cache = self._sdk_properties['cleanup_cache']

    if 'arm' in self.m.platform.arch and 'toolchain_ver_arm' in self._sdk_properties:
      self._tool_ver = self._sdk_properties['toolchain_ver_arm']
    elif 'intel' in self.m.platform.arch and 'toolchain_ver_intel' in self._sdk_properties:
      self._tool_ver = self._sdk_properties['toolchain_ver_intel']

    if 'runtime_versions' in self._sdk_properties:
      # Sorts the runtime versions to make xcode cache path deterministic, without
      # being affected by how user orders the runtime versions.
      runtime_versions = self._sdk_properties['runtime_versions']
      runtime_versions.sort(reverse=True)
      self._runtime_versions = runtime_versions

    current_os = self.m.platform.mac_release
    if 'sdk_version' in self._sdk_properties:
      self._sdk_version = self._sdk_properties['sdk_version'].lower()
    else:
      for target_os, xcode in reversed(_DEFAULT_VERSION_MAP):
        if current_os >= self.m.version.parse(target_os):
          self._sdk_version = xcode
          break
      else:
        self._sdk_version = _DEFAULT_VERSION_MAP[0][-1]

    self.macos_13_or_later = current_os >= self.m.version.parse('13.0.0')

    if 'xcode_cipd_package_source' in self._sdk_properties:
      self._xcode_cipd_package_source = self._sdk_properties[
          'xcode_cipd_package_source']
    else:
      # TODO(vashworth): Once all bots are on macOS 13, we can remove this
      # check and always default to _INFRA_XCODE_CIPD.
      if self.macos_13_or_later:
        # Starting with macOS 13, Xcode packages that have been altered are
        # considered "damaged" and will not be usable. Since Xcode CIPD packages
        # from flutter_internal have been altered up to Xcode 15 beta 6 (15a5219j),
        # use infra_internal Xcode CIPD packages as the default on macOS 13.
        self._xcode_cipd_package_source = _INFRA_XCODE_CIPD
      else:
        self._xcode_cipd_package_source = _FLUTTER_XCODE_CIPD

  @contextmanager
  def __call__(self, kind, devicelab=False):
    """Sets up the XCode SDK environment.

    Is a no-op on non-mac platforms.

    This will deploy the helper tool and the XCode.app bundle at
    `[START_DIR]/cache/osx_sdk`.

    To avoid machines rebuilding these on every run, set up a named cache in
    your cr-buildbucket.cfg file like:

        caches: [
          {
            name: "flutter_xcode"
            path: "osx_sdk"
          }
        ]

    The Xcode app will be installed under:
        osx_sdk/xcode_<xcode-version>

    If any iOS runtime is needed, the corresponding path will be:
        osx_sdk/xcode_<xcode-version>_runtime_<runtime-version>

    These cached packages will be shared across builds/bots.

    Usage:
      with api.osx_sdk('mac'):
        # sdk with mac build bits

      with api.osx_sdk('ios'):
        # sdk with mac+iOS build bits

    Args:
      kind ('mac'|'ios'): How the SDK should be configured. iOS includes the
        base XCode distribution, as well as the iOS simulators (which can be
        quite large).
      devicelab (bool): whether this is a devicelab tasks. The xcode for devicelab
        is installed in a fixed location `/opt/flutter/xcode`.

    Raises:
        StepFailure or InfraFailure.
    """
    assert kind in ('mac', 'ios'), 'Invalid kind %r' % (kind,)
    if not self.m.platform.is_mac:
      yield
      return

    try:
      with self.m.context(infra_steps=True):
        self._setup_osx_sdk(kind, devicelab)
        runtime_simulators = self.m.step(
            'list runtimes', ['xcrun', 'simctl', 'list', 'runtimes'],
            stdout=self.m.raw_io.output_text()
        ).stdout.splitlines()
        if self._missing_runtime(runtime_simulators[1:]):
          self._cleanup_cache = True
          self._setup_osx_sdk(kind, devicelab)
      yield
    finally:
      self.reset_xcode()

  def reset_xcode(self):
    '''Unset manually defined Xcode path for Xcode command line tools on macOS.'''
    if not self.m.platform.is_mac:
      return
    with self.m.context(infra_steps=True):
      self.m.step('reset XCode', ['sudo', 'xcode-select', '--reset'])

  def _missing_runtime(self, runtime_simulators):
    """Check if there is any missing runtime.

    If no explicit `_runtime_versions` is specified, we assume `runtime_simulators`
    at least has the default runtime and should not be empty.

    If there is explicit `_runtime_versions` defined, we need to check if the number
    of installed runtime matches the number of required.

    The runtime_simulators follows:
    [
      "iOS 16.2 (16.2 - 20C52) - com.apple.CoreSimulator.SimRuntime.iOS-16-2",
      "iOS 16.4 (16.4 - 20E247) - com.apple.CoreSimulator.SimRuntime.iOS-16-4"
    ]

    The property `_runtime_versions` follows:
    [
      "ios-16-4_14e300c",
      "ios-16-2_14c18"
    ]
    """
    if not self._runtime_versions:
      return not runtime_simulators
    return len(self._runtime_versions) != len(runtime_simulators)

  def _get_xcode_base_cache_path(self, devicelab: bool):
    """Returns the base cache path for xcode.

    Args:
      devicelab - Whether or not the machine this code is running is a devicelab
        machine.
    """
    if devicelab:
      return '/opt/flutter/xcode'
    return self.m.path['cache'].join('osx_sdk')

  def _setup_osx_sdk(self, kind, devicelab):
    app = None
    self._clean_xcode_cache(devicelab)
    # NOTE: cleaning of the cache on devicelab will happen via salt.
    if not devicelab:
      self._micro_manage_cache(devicelab=devicelab)
    app = self._ensure_sdk(kind, devicelab)
    self.m.os_utils.kill_simulators()
    self._select_xcode(app)
    self.m.step('list simulators', ['xcrun', 'simctl', 'list'])

  def _clean_xcode_cache(self, devicelab):
    """Cleans up cache when specified or polluted.

    Cleans up only corresponding versioned xcode instead of the whole `osx_sdk`.

    If on macOS 13 or later, deletes all mounted runtimes and deletes
    corresponding cached runtime dmgs.
    """
    if not self._cleanup_cache:
      return
    if devicelab or not self.macos_13_or_later:
      self.m.file.rmtree('Cleaning up Xcode cache', self._xcode_dir(devicelab))
    else:
      # Clean up with `file.rmtree` fails on macOS 13 non-devicelab bots with an
      # "Operation not permitted" error when deleting XCode.app/Contents/_CodeSignature.
      # Use `rm -rf` instead.
      self.m.step(
          'Cleaning up Xcode cache',
          ['rm', '-rf', self._xcode_dir(devicelab)]
      )

  def _ensure_mac_toolchain(self, tool_dir):
    ef = self.m.cipd.EnsureFile()
    ef.add_package(self._tool_pkg, self._tool_ver)
    self.m.cipd.ensure(tool_dir, ef)

  def _select_xcode(self, sdk_app):
    self.m.step('select xcode', ['sudo', 'xcode-select', '--switch', sdk_app])

  def _verify_xcode(self, sdk_app):
    """If Xcode is already downloaded, verify that it's not damaged.

    Args:
    sdk_app: (Path) Path to installed Xcode app bundle.
    """
    if not self.m.path.exists(sdk_app):
      return

    with self.m.step.nest('verify xcode %s' % sdk_app):
      version_check_failed = False
      try:
        self._select_xcode(sdk_app)

        # This step is expected to timeout if Xcode is damaged.
        self.m.step(
            'check xcode version',
            [
                'xcrun',
                'xcodebuild',
                '-version',
            ],
            timeout=60 * 5,  # 5 minutes
        )
      except self.m.step.StepFailure:
        version_check_failed = True
        raise
      finally:
        self.reset_xcode()
        self._dimiss_damaged_notification()

        if version_check_failed:
          self._diagnose_codesign_failure(sdk_app)

  def _diagnose_codesign_failure(self, sdk_app):
    """Check if Xcode verification may have failed due to code not matching
    original signed code. Used to help debug issues.
    """
    self.m.step(
        'verify codesign',
        [
            'codesign',
            '-vv',
            sdk_app,
        ],
        ok_ret='any',
    )

  def _dimiss_damaged_notification(self):
    """If Xcode is damaged, it may show a notification that can cause
    Xcode processes to hang until it's closed. Kill `CoreServicesUIAgent`
    to close it.
    """
    self.m.step(
        'dismiss damaged notification',
        ['killall', '-9', 'CoreServicesUIAgent'],
        ok_ret='any',
    )

  def _try_install_xcode(self, tool_dir, kind, app_dir, sdk_app, devicelab):
    """Installs xcode using mac_toolchain. If install fails, clear the cache and try again.

    Args:
      devicelab: (bool) Whether this is a devicelab tasks. Don't install
        explicit runtimes for devicelab tasks.
      app_dir: (Path) Path to Xcode cache directory.
      tool_dir: (Path) Path to mac_toolchain cache directory.
      sdk_app: (Path) Path to installed Xcode app bundle.
      kind ('mac'|'ios'): How the SDK should be configured.
    """
    with self.m.step.nest('install xcode'):
      try:
        self._install_xcode(tool_dir, kind, app_dir, sdk_app, devicelab)
      except self.m.step.StepFailure:
        self._install_xcode(tool_dir, kind, app_dir, sdk_app, devicelab, True)

  def _install_xcode(
      self, tool_dir, kind, app_dir, sdk_app, devicelab, retry=False
  ):
    """Installs xcode using mac_toolchain.

    Args:
      devicelab: (bool) Whether this is a devicelab tasks. Don't install
        explicit runtimes for devicelab tasks.
      app_dir: (Path) Path to Xcode cache directory.
      tool_dir: (Path) Path to mac_toolchain cache directory.
      sdk_app: (Path) Path to installed Xcode app bundle.
      kind ('mac'|'ios'): How the SDK should be configured.
      retry: (bool) Whether this is the second attempt to install Xcode.
    """

    install_path = sdk_app

    # On retry, install Xcode to a different path and later move it to the
    # original path. Although unproven, there is a theory that re-installing
    # Xcode to the same path as a previously damaged version may cause the new
    # version to also be considered damaged.
    if retry:
      uuid = self.m.uuid.random()
      install_path = self.m.path.join(app_dir, 'temp_%s_xcode.app' % uuid)

    try:
      # Verify that existing Xcode is not damaged. If it's damaged, the
      # 'install xcode from cipd' step may get stuck until it times out.
      self._verify_xcode(install_path)
    except self.m.step.StepFailure:
      self._cleanup_cache = True
      self._clean_xcode_cache(devicelab)

    try:
      self._ensure_mac_toolchain(tool_dir)
      if self.macos_13_or_later:
        # TODO(vashworth): Remove macOS 13 specific install steps once
        # https://github.com/flutter/flutter/issues/138238 is resolved.
        self.m.step('Show tool_dir cache', ['ls', '-al', tool_dir])
      self.m.step(
          'install xcode from cipd',
          [
              tool_dir.join('mac_toolchain'),
              'install',
              '-kind',
              kind,
              '-xcode-version',
              self._sdk_version,
              '-output-dir',
              install_path,
              '-cipd-package-prefix',
              self._xcode_cipd_package_source,
              '-with-runtime=%s' % (not bool(self._runtime_versions)),
              '-verbose',
          ],
          timeout=60 * 30  # 30 minutes
      )
      if retry:
        self.m.step(
            'move to final destination',
            [
                'mv',
                install_path,
                sdk_app,
            ],
        )
    except self.m.step.StepFailure:
      if self.macos_13_or_later:
        # TODO(vashworth): Remove macOS 13 specific install steps once
        # https://github.com/flutter/flutter/issues/138238 is resolved.
        self.m.step('Show tool_dir cache', ['ls', '-al', tool_dir])
        self.m.step('Show app_dir cache', ['ls', '-al', app_dir], ok_ret='any')
      self._dimiss_damaged_notification()
      self._diagnose_codesign_failure(sdk_app)
      self._cleanup_cache = True
      self._clean_xcode_cache(devicelab)
      self.m.step.empty(
          'Failed to install Xcode',
          status=self.m.step.INFRA_FAILURE,
      )
    finally:
      if retry:
        self.m.step(
            'clean temporary install path',
            [
                'rm',
                '-rf',
                install_path,
            ],
            ok_ret='any',
        )

  def _ensure_sdk(self, kind, devicelab):
    """Ensures the mac_toolchain tool and OSX SDK packages are installed.

    Returns Path to the installed sdk app bundle."""
    app_dir = self._xcode_dir(devicelab)
    tool_dir = self.m.path.mkdtemp().join('osx_sdk') if devicelab else app_dir
    sdk_app = self.m.path.join(app_dir, 'XCode.app')
    self._try_install_xcode(tool_dir, kind, app_dir, sdk_app, devicelab)

    self._cleanup_runtimes_cache(sdk_app)

    self._install_runtimes(devicelab, app_dir, tool_dir, sdk_app, kind)

    return sdk_app

  def _micro_manage_cache(self, devicelab: bool):
    """Tracks the age of packages in the target cache. If older than a
    specific date then delete them.

    Params:
      devicelab: (bool) tells the module which path we should be working with.
    """
    cache_path = self._get_xcode_base_cache_path(devicelab)
    app_dir = self._xcode_dir(devicelab)
    self.m.step("show app_dir", ['echo', app_dir])
    self._show_xcode_cache(cache_path)
    self.m.cache_micro_manager.run(cache_path, [app_dir])
    self._show_xcode_cache(cache_path)

  def _show_xcode_cache(self, cache_path):
    self.m.step(
        'Show xcode cache',
        ['ls', '-al', cache_path],
        ok_ret='any',
    )

  def _install_runtimes(self, devicelab, app_dir, tool_dir, sdk_app, kind):
    """Ensure runtimes are installed.

    For macOS lower than 13, this involves downloading the runtime and copying
    it into the Xcode app bundle.

    For macOS 13 and higher, this involved downloading the runtime dmg and
    running a `simctl` command to verify and mount it. This is required because
    copying files into Xcode on macOS 13 may damage it and prevent it from
    being usable.

    Args:
      devicelab: (bool) Whether this is a devicelab tasks. Don't install
        explicit runtimes for devicelab tasks.
      app_dir: (Path) Path to Xcode cache directory.
      tool_dir: (Path) Path to mac_toolchain cache directory.
      sdk_app: (Path) Path to installed Xcode app bundle.
      kind ('mac'|'ios'): How the SDK should be configured.
    """

    if not self._runtime_versions:
      # On macOS 13, when cleanup_cache is True, we first clear the Xcode cache,
      # install Xcode, and then clean up the runtimes cache. It happens in this
      # order because removing runtimes requires Xcode developer tools so Xcode
      # must be installed first. However, when no explicit runtimes are defined,
      # the runtime is also installed in the `_try_install_xcode` function. So after
      # cleaning the runtimes, the runtime that was installed may have been
      # removed. So re-call `_try_install_xcode` to reinstall the removed runtime.
      if self.macos_13_or_later and self._cleanup_cache:
        with self.m.step.nest('install runtimes'):
          self._try_install_xcode(tool_dir, kind, app_dir, sdk_app, devicelab)
      return

    if devicelab:
      return

    with self.m.step.nest('install runtimes'):
      if self.macos_13_or_later:
        self._select_xcode(sdk_app)
        runtime_simulators = self.m.step(
            'list runtimes', ['xcrun', 'simctl', 'list', 'runtimes'],
            stdout=self.m.raw_io.output_text(add_output_log=True)
        ).stdout.splitlines()

        for version in self._runtime_versions:
          runtime_version_parts = version.split('_')
          if len(runtime_version_parts) != 2:
            self.m.step.empty(
                'Invalid runtime version %s' % version,
                status=self.m.step.INFRA_FAILURE,
            )
          runtime_version = runtime_version_parts[0]
          xcode_version = runtime_version_parts[1]
          # we can assume devicelab False and build this with base path.
          runtime_dmg_cache_dir = self._runtime_dmg_dir_cache_path(version)

          self.m.step(
              'install xcode runtime %s' % version.lower(),
              [
                  app_dir.join('mac_toolchain'),
                  'install-runtime-dmg',
                  '-cipd-package-prefix',
                  self._xcode_cipd_package_source,
                  '-runtime-version',
                  runtime_version,
                  '-xcode-version',
                  xcode_version,
                  '-output-dir',
                  runtime_dmg_cache_dir,
              ],
          )
          downloaded_runtime_files = self.m.file.listdir(
              'list xcode runtime dmg %s' % version.lower(),
              runtime_dmg_cache_dir
          )

          # The runtime dmg may not be named consistently so search for the dmg file.
          runtime_dmg_path = None
          for file_path in downloaded_runtime_files:
            if '.dmg' in str(file_path):
              runtime_dmg_path = str(file_path)

          if runtime_dmg_path is None:
            self.m.step.empty(
                'Failed to find runtime dmg',
                status=self.m.step.INFRA_FAILURE,
            )

          # Skip adding the runtime if it's already mounted
          if not self._is_runtime_mounted(runtime_version, xcode_version,
                                          runtime_simulators):
            self.m.step(
                'verify and mount runtime %s' % version.lower(),
                [
                    'xcrun',
                    'simctl',
                    'runtime',
                    'add',
                    runtime_dmg_path,
                ],
            )

      else:
        # Skips runtime installation if it already exists. Otherwise,
        # installs each runtime version under `osx_sdk` for cache sharing,
        # and then copies over to the destination.

        self.m.file.ensure_directory(
            'Ensuring runtimes directory',
            self.m.path.join(sdk_app, *_RUNTIMESPATH)
        )
        for version in self._runtime_versions:
          runtime_name = 'iOS %s.simruntime' % version.lower(
          ).replace('ios-', '').replace('-', '.')
          dest = self.m.path.join(sdk_app, *_RUNTIMESPATH, runtime_name)
          if not self.m.path.exists(dest):
            cache_base_path = self._get_xcode_base_cache_path(False)
            runtime_cache_dir = cache_base_path.join(
                'xcode_runtime_%s' % version.lower()
            )
            self.m.step(
                'install xcode runtime %s' % version.lower(),
                [
                    app_dir.join('mac_toolchain'),
                    'install-runtime',
                    '-cipd-package-prefix',
                    _FLUTTER_XCODE_CIPD,
                    '-runtime-version',
                    version.lower(),
                    '-output-dir',
                    runtime_cache_dir,
                ],
            )
            # Move the runtimes
            path_with_version = runtime_cache_dir.join(runtime_name)
            # If the runtime was the default for xcode the cipd bundle contains a directory called iOS.simruntime otherwise
            # it contains a folder called "iOS <version>.simruntime".
            source = path_with_version if self.m.path.exists(
                path_with_version
            ) else runtime_cache_dir.join('iOS.simruntime')
            self.m.file.copytree(
                'Copy runtime to %s' % dest, source, dest, symlinks=True
            )

  def _xcode_dir(self, devicelab):
    """Returns the location of the xcode app in the cache dir.

    For a devicelab task, the path is prefixed at `/opt/flutter/xcode`.

    For a host only task without runtime, the path looks like
            xcode_<xcode-version>

    a host only task with runtimes, the path looks like
        xcode_<xcode-version>_runtime1_<runtime1-version>_..._runtimeN_<runtimeN-version>
    """

    xcode_cache_base_path = self._get_xcode_base_cache_path(devicelab)
    if devicelab:
      return f"{xcode_cache_base_path}/{self._sdk_version}"
    runtime_version = None
    sdk_version = f"xcode_{self._sdk_version}"
    if not self.macos_13_or_later and self._runtime_versions:
      runtime_version = "_".join(self._runtime_versions)
      sdk_version = f"{sdk_version}_runtime_{runtime_version}"
    return xcode_cache_base_path.join(sdk_version)

  def _runtime_dmg_dir_cache_path(self, version):
    cache_base_path = self._get_xcode_base_cache_path(False)
    # this method seems to be only used for non-devicelab cache path.
    return cache_base_path.join('xcode_runtime_dmg_%s' % version.lower())

  def _cleanup_runtimes_cache(self, sdk_app):
    """Deletes all mounted runtimes and deletes corresponding cached runtime dmgs.

    This is only used for macOS 13+ since runtimes are installed and mounted separately.
    """

    if not self._cleanup_cache or not self.macos_13_or_later:
      return

    with self.m.step.nest('Cleaning up runtimes cache'):
      self._select_xcode(sdk_app)

      simulator_cleanup_result = self.m.step(
          'Cleaning up mounted simulator runtimes',
          [
              'xcrun',
              'simctl',
              'runtime',
              'delete',
              'all',
          ],
          raise_on_failure=False,
          ok_ret='any',
          stdout=self.m.raw_io.output_text(add_output_log=True),
          stderr=self.m.raw_io.output_text(add_output_log=True),
      )

      simulator_cleanup_stdout = simulator_cleanup_result.stdout.rstrip()
      simulator_cleanup_stderr = simulator_cleanup_result.stderr.rstrip()
      if simulator_cleanup_stdout and 'No matching images found to delete' not in simulator_cleanup_stdout:
        self.m.step.empty(
            'Failed to delete runtimes',
            status=self.m.step.INFRA_FAILURE,
            step_text=simulator_cleanup_stdout,
        )
      if simulator_cleanup_stderr and 'No matching images found to delete' not in simulator_cleanup_stderr:
        self.m.step.empty(
            'Failed to delete runtimes',
            status=self.m.step.INFRA_FAILURE,
            step_text=simulator_cleanup_stderr,
        )

      # Determine how many runtimes can remain to consider them unmounted. For
      # Xcode versions 15 or greater, 0 are allowed to remain. Otherwise 1 is
      # allowed. This is because in older versions of Xcode, the runtime is
      # included in Xcode, which means it won't be unmounted.
      max_remaining_runtimes = 1
      xcode_version = self.m.step(
          'check xcode version',
          [
              'xcrun',
              'xcodebuild',
              '-version',
          ],
          stdout=self.m.raw_io.output_text(add_output_log=True),
      ).stdout.splitlines()
      if len(xcode_version) > 0:
        xcode_version = xcode_version[0].replace("Xcode", "").strip()
        parsed_xcode_version = self.m.version.parse(xcode_version)
        if parsed_xcode_version >= self.m.version.parse('15.0.0'):
          max_remaining_runtimes = 0

      # Wait up to ~5 minutes until runtimes are unmounted.
      self.m.retry.basic_wrap(
          lambda timeout: self._is_runtimes_unmounted(
              max_remaining_runtimes,
              timeout=timeout,
          ),
          step_name='Wait for runtimes to unmount',
          sleep=5.0,
          backoff_factor=2,
          max_attempts=7
      )

      if not self._runtime_versions:
        return

      for version in self._runtime_versions:
        runtime_dmg_cache_dir = self._runtime_dmg_dir_cache_path(version)

        self.m.file.rmtree(
            'Cleaning up runtime cache %s' % version.lower(),
            runtime_dmg_cache_dir
        )

  # pylint: disable=unused-argument
  def _is_runtimes_unmounted(self, max_remaining_runtimes, timeout=None):
    '''Check if more than one runtime is currently mounted. If more than one
    is mounted, raise a `StepFailure`.

    Args:
      max_remaining_runtimes: (int) How many runtimes are allowed to remain for
      it to be considered done unmounting.
    '''
    runtime_simulators = self.m.step(
        'list runtimes', ['xcrun', 'simctl', 'list', 'runtimes'],
        stdout=self.m.raw_io.output_text(add_output_log=True)
    ).stdout.splitlines()

    if len(runtime_simulators[1:]) > max_remaining_runtimes:
      raise self.m.step.StepFailure('Runtimes not unmounted yet')

  def _is_runtime_mounted(
      self, runtime_version, xcode_version, runtime_simulators
  ):
    """Determine if iOS runtime version is already mounted.

    Args:
      runtime_version: (string) The iOS version (e.g. "ios-16-4").
      xcode_version: (string) The Xcode version (e.g. "14e300c").
      runtime_simulators: (list) A list of strings of runtime versions.
    Returns:
      A boolean for whether or not the runtime is already mounted.
    """

    with self.m.step.nest('cipd describe %s_%s' %
                          (runtime_version, xcode_version)) as display_step:
      # First try to get the iOS runtime build version by the Xcode version
      ios_runtime_build_version = self._get_ios_runtime_build_version(
          runtime_version, xcode_version
      )

      # If unable to get from the Xcode version, try again by using the iOS runtime version
      if ios_runtime_build_version is None:
        ios_runtime_build_version = self._get_ios_runtime_build_version(
            runtime_version
        )

      if ios_runtime_build_version is None:
        self.m.step.empty(
            'Failed to get runtime build version',
            status=self.m.step.INFRA_FAILURE,
        )
      else:
        self.m.step.empty(
            'runtime build version', step_text=ios_runtime_build_version
        )
        display_step.presentation.status = self.m.step.SUCCESS

    # Check if runtime is already mounted
    for runtime in runtime_simulators:
      # Example runtime: `iOS 14.3 (14.3 - 18C61) - com.apple.CoreSimulator.SimRuntime.iOS-14-3`
      if ios_runtime_build_version.lower() in runtime.lower():
        return True

    return False

  def _get_ios_runtime_build_version(self, runtime_version, xcode_version=None):
    """Gets the iOS runtime build version from CIPD.

    If `xcode_version` is provided, it will use it to search for the CIPD package.
    If not provided, the `runtime_version` will be used. In both cases, it ensures
    the found package matches the `runtime_version`.

    Args:
      runtime_version: (string) An iOS version used to find and match the CIPD package (e.g. "ios-16-4")
      xcode_version: (string) A version of Xcode to use to find CIPD package (e.g. "14e300c").
    Returns:
      A string of the build version or None if unable to get the build version.
    """

    search_ref = runtime_version
    if xcode_version is not None:
      search_ref = xcode_version

    try:
      description = self.m.cipd.describe(
          '%s/ios_runtime_dmg' % self._xcode_cipd_package_source,
          search_ref,
      )
      runtime_tag = None
      build_tag = None
      for tag in description.tags:
        if 'ios_runtime_version' in tag.tag:
          runtime_tag = self._parse_cipd_description_tag(tag.tag)
        if 'ios_runtime_build' in tag.tag:
          build_tag = self._parse_cipd_description_tag(tag.tag)

      if runtime_tag == runtime_version:
        return build_tag

      self.m.step.empty(
          'mismatching runtimes',
          step_text='Found %s, expected %s' % (runtime_tag, runtime_version),
          status=self.m.step.INFRA_FAILURE,
      )

    except self.m.step.StepFailure:
      pass

    return None

  def _parse_cipd_description_tag(self, tag):
    """Parse a colon separated CIPD description tag.

    Args:
      tag: (string) A colon separated string describing a CIPD tag.
        (e.g "ios_runtime_build:21A5303d" or "ios_runtime_version:ios-17-0")
    Returns:
      A string of the value following the colon or None if unable to parse.
    """
    tag_parts = tag.split(':')
    if len(tag_parts) == 2:
      return tag_parts[1]
    return None
