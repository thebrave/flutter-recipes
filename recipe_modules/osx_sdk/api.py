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



class OSXSDKApi(recipe_api.RecipeApi):
  """API for using OS X SDK distributed via CIPD."""

  def __init__(self, sdk_properties, *args, **kwargs):
    super(OSXSDKApi, self).__init__(*args, **kwargs)
    self._sdk_properties = sdk_properties
    self._sdk_version = None
    self._runtime_versions = None
    self._tool_pkg = 'infra/tools/mac_toolchain/${platform}'
    self._tool_ver = 'latest'

  def initialize(self):
    """Initializes xcode, and ios versions.

    Versions are usually passed as recipe properties but if not then defaults
    are used.
    """
    if not self.m.platform.is_mac:
      return

    if 'toolchain_ver' in self._sdk_properties:
      self._tool_ver = self._sdk_properties['toolchain_ver'].lower()

    if 'runtime_versions' in self._sdk_properties:
      self._runtime_versions = self._sdk_properties['runtime_versions']

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
            # Cache for mac_toolchain tool and XCode.app
            name: "osx_sdk"
            path: "osx_sdk"
          },
          {
            # Runtime version
            name: xcode_runtime_ios-14-0,
            path: xcode_runtime_ios-14-0
          }
        ]

    If you have builders which e.g. use a non-current SDK, you can give them
    a uniqely named cache:

        caches: {
          # Cache for N-1 version mac_toolchain tool and XCode.app
          name: "osx_sdk_old"
          path: "osx_sdk"
        }

    If you use multiple runtimes you'll need to provide a cache for each of
    the runtimes.

        caches: [
          {
            # Cache for mac_toolchain tool and XCode.app
            name: "osx_sdk"
            path: "osx_sdk"
          },
          {
            # Runtime version
            name: xcode_runtime_ios-14-0,
            path: xcode_runtime_ios-14-0
          },
          {
            # Runtime version
            name: xcode_runtime_ios-13-0,
            path: xcode_runtime_ios-13-0
          }

        ]

    Similarly, if you have mac and iOS builders you may want to distinguish the
    cache name by adding '_ios' to it. However, if you're sharing the same bots
    for both mac and iOS, consider having a single cache and just always
    fetching the iOS version. This will lead to lower overall disk utilization
    and should help to reduce cache thrashing.

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
        app = self._ensure_sdk(kind)
        self.m.step('select XCode', ['sudo', 'xcode-select', '--switch', app])
        self.m.step('list simulators', ['xcrun', 'simctl', 'list'])
      yield
    finally:
      with self.m.context(infra_steps=True):
        self.m.step('reset XCode', ['sudo', 'xcode-select', '--reset'])

  def _ensure_sdk(self, kind):
    """Ensures the mac_toolchain tool and OS X SDK packages are installed.

    Returns Path to the installed sdk app bundle."""
    cache_dir = self.m.path['cache'].join('osx_sdk')

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
        ],
    )
    if self._runtime_versions:
      for version in self._runtime_versions:
        runtime_cache_dir = self.m.path['cache'].join('xcode_runtime_%s' % version.lower())
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
        runtime_name = 'iOS %s.simruntime' % version.lower().replace('ios-', '').replace('-', '.')
        source = runtime_cache_dir.join(runtime_name)
        dest = sdk_app.join(*_RUNTIMESPATH).join(runtime_name)
        self.m.file.rmglob('Removing stale %s' % runtime_name, sdk_app.join(*_RUNTIMESPATH), runtime_name)
        self.m.file.symlink('Moving %s to final dest' % version.lower(), source, dest)
    return sdk_app
