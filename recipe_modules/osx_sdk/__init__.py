# Copyright 2018 The Chromium Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

DEPS = [
    'flutter/os_utils',
    'flutter/retry',
    'flutter/cache_micro_manager',
    'recipe_engine/cipd',
    'recipe_engine/context',
    'recipe_engine/file',
    'recipe_engine/path',
    'recipe_engine/platform',
    'recipe_engine/raw_io',
    'recipe_engine/step',
    'recipe_engine/version',
    'recipe_engine/uuid',
]

from recipe_engine.recipe_api import Property
from recipe_engine.config import ConfigGroup, Single, List

PROPERTIES = {
    '$flutter/osx_sdk': Property(
    help='Properties specifically for the infra osx_sdk module.',
    param_name='sdk_properties',
    kind=ConfigGroup(  # pylint: disable=line-too-long
      # XCode build version number. Internally maps to an XCode build id like
      # '9c40b'. See
      #
      # https://chrome-infra-packages.appspot.com/p/flutter_internal/ios/xcode/mac/+/
      #
      # For an up to date list of the latest SDK builds.
      sdk_version=Single(str),
      # Runtime version to be installed along the xcode version.
      runtime_versions=List(str),

      # The CIPD toolchain tool package and version
      toolchain_pkg=Single(str),
      toolchain_ver_arm=Single(str),
      toolchain_ver_intel=Single(str),
      # Cleanup caches
      cleanup_cache=Single(bool),

      # Location of the Xcode CIPD package
      xcode_cipd_package_source=Single(str),
    ), default={},
    )
}
