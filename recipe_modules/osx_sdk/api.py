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
        'Contents',
        'Developer',
        'Platforms',
        'iPhoneOS.platform',
        'Library',
        'Developer',
        'CoreSimulator',
        'Profiles',
        'Runtimes'
        ]

_XCODE_CACHE_PATH = 'osx_sdk'


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

  def initialize(self):
    """Initializes xcode, and ios versions.

    Versions are usually passed as recipe properties but if not then defaults
    are used.
    """
    if not self.m.platform.is_mac:
      return

    if 'cleanup_cache' in self._sdk_properties:
      self._cleanup_cache = self._sdk_properties['cleanup_cache']

    if 'toolchain_ver' in self._sdk_properties:
      self._tool_ver = self._sdk_properties['toolchain_ver'].lower()

    if 'runtime_versions' in self._sdk_properties:
      # Sorts the runtime versions to make xcode cache path deterministic, without
      # being affected by how user orders the runtime versions.
      runtime_versions = self._sdk_properties['runtime_versions']
      runtime_versions.sort(reverse=True)
      self._runtime_versions = runtime_versions

    if 'sdk_version' in self._sdk_properties:
      self._sdk_version = self._sdk_properties['sdk_version'].lower()
    else:
      cur_os = self.m.platform.mac_release
      for target_os, xcode in reversed(_DEFAULT_VERSION_MAP):
        if cur_os >= self.m.version.parse(target_os):
          self._sdk_version = xcode
          break
      else:
        self._sdk_version = _DEFAULT_VERSION_MAP[0][-1]

  @contextmanager
  def __call__(self, kind):
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

    Raises:
        StepFailure or InfraFailure.
    """
    assert kind in ('mac', 'ios'), 'Invalid kind %r' % (kind,)
    if not self.m.platform.is_mac:
      yield
      return

    try:
      with self.m.context(infra_steps=True):
        self._clean_cache()
        app = self._ensure_sdk(kind)
        self.m.os_utils.kill_simulators()
        self.m.step('select XCode', ['sudo', 'xcode-select', '--switch', app])
        self.m.step('list simulators', ['xcrun', 'simctl', 'list'])
      yield
    finally:
      with self.m.context(infra_steps=True):
        self.m.step('reset XCode', ['sudo', 'xcode-select', '--reset'])

  def _clean_cache(self):
    """Cleans up cache when specified or polluted.

    Cleans up only corresponding versioned xcode instead of the whole `osx_sdk`.
    """
    if self._cleanup_cache or self._cache_polluted():
      self.m.file.rmtree('Cleaning up Xcode cache', self._cache_dir())

  def _ensure_sdk(self, kind):
    """Ensures the mac_toolchain tool and OSX SDK packages are installed.

    Returns Path to the installed sdk app bundle."""
    cache_dir = self._cache_dir()
    ef = self.m.cipd.EnsureFile()
    ef.add_package(self._tool_pkg, self._tool_ver)
    self.m.cipd.ensure(cache_dir, ef)

    sdk_app = cache_dir.join('XCode.app')
    self.m.step(
        'install xcode',
        [
            cache_dir.join('mac_toolchain'),
            'install',
            '-kind',
            kind,
            '-xcode-version',
            self._sdk_version,
            '-output-dir',
            sdk_app,
            '-cipd-package-prefix',
            'flutter_internal/ios/xcode',
            '-with-runtime=%s' % (not bool(self._runtime_versions))
        ],
    )
    # Skips runtime installation if it already exists. Otherwise,
    # installs each runtime version under `osx_sdk` for cache sharing,
    # and then copies over to the destination.
    if self._runtime_versions:
      self.m.file.ensure_directory('Ensuring runtimes directory', sdk_app.join(*_RUNTIMESPATH))
      for version in self._runtime_versions:
        runtime_name = 'iOS %s.simruntime' % version.lower().replace('ios-', '').replace('-', '.')
        dest = sdk_app.join(*_RUNTIMESPATH).join(runtime_name)
        if not self.m.path.exists(dest):
          runtime_cache_dir = self.m.path['cache'].join(_XCODE_CACHE_PATH).join(
              'xcode_runtime_%s' % version.lower()
          )
          self.m.step(
              'install xcode runtime %s' % version.lower(),
              [
                  cache_dir.join('mac_toolchain'),
                  'install-runtime',
                  '-cipd-package-prefix',
                  'flutter_internal/ios/xcode',
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
          source = path_with_version if self.m.path.exists(path_with_version) else runtime_cache_dir.join('iOS.simruntime')
          self.m.file.copytree('Copy runtime to %s' % dest, source, dest, symlinks=True)
    return sdk_app

  def _cache_polluted(self):
    """Checks if cache is polluted.

    CIPD ensures package whenever called, but just checks on some levels, like
    `.xcode_versions` and `.cipd`. It misses the case where the `xcode` and runtime
    are finished installing, but the files are not finished copying over to destination.

    The above case causes cache polluted where xcode is installed incompletely:
    the xcode path exists but no runtime exists.

    All installed xcode contains runtime, either the default one or the extra
    specified runtimes by tests.

    This is a workaround to detect incomplete xcode installation as cipd is not
    able to detect some incomplete installation cases and reinstall.
    """
    cache_polluted = False
    sdk_app_dir = self._cache_dir()
    if not self.m.path.exists(sdk_app_dir):
      self.m.step('xcode not installed', ['echo', sdk_app_dir])
      return cache_polluted
    if not self._runtime_exists():
      cache_polluted = True
      self.m.step('cache polluted due to missing runtime', ['echo', 'xcode is installed without runtime'])
    return cache_polluted

  def _cache_dir(self):
    """Returns xcode cache dir.

    For an xcode without runtime, the path looks like
        xcode_<xcode-version>

    For an xcode with runtimes, the path looks like
        xcode_<xcode-version>_runtime1_<runtime1-version>_..._runtimeN_<runtimeN-version>
    """
    runtime_version = None
    sdk_version = 'xcode_' + self._sdk_version
    if self._runtime_versions:
      runtime_version = "_".join(self._runtime_versions)
      sdk_version = sdk_version + '_runtime_' + runtime_version
    return self.m.path['cache'].join(_XCODE_CACHE_PATH).join(sdk_version)

  def _runtime_exists(self):
    """Checks runtime existence in the installed xcode.

    Checks `iOS.simruntime` for default runtime.
    Checks each specific runtime version for specified ones.
    """
    runtime_exists = True
    sdk_app_dir = self._cache_dir().join('XCode.app')
    if self._runtime_versions:
      for version in self._runtime_versions:
        runtime_name = 'iOS %s.simruntime' % version.lower().replace('ios-', '').replace('-', '.')
        runtime_path = sdk_app_dir.join(*_RUNTIMESPATH).join(runtime_name)
        if not self.m.path.exists(runtime_path):
          runtime_exists = False
          self.m.step('runtime: %s does not exist' % runtime_name, ['echo', runtime_path])
          break
    else:
      runtime_path = sdk_app_dir.join(*_RUNTIMESPATH).join('iOS.simruntime')
      if not self.m.path.exists(runtime_path):
        runtime_exists = False
        self.m.step('iOS.simruntime does not exists', ['echo', runtime_path])
    return runtime_exists
