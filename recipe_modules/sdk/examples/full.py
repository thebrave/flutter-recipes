# Copyright 2020 The Fuchsia Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

PYTHON_VERSION_COMPATIBILITY = 'PY2+3'

DEPS = [
    'flutter/sdk',
    'fuchsia/status_check',
    'recipe_engine/file',
    'recipe_engine/path',
    'recipe_engine/platform',
]


def RunSteps(api):
  api.sdk._select_image_to_download()
  api.sdk._select_package_to_download()
  api.sdk.version = '0.20200101.0.1'
  api.sdk.image_paths
  api.sdk.package_paths

  api.sdk.authorize_zbi(
      ssh_key_path=api.path['cache'],
      zbi_input_path=api.sdk.image_paths.zircona
  )
  api.sdk.authorize_zbi(
      ssh_key_path=api.path['cache'],
      zbi_input_path=api.sdk.image_paths.zircona,
      zbi_output_path=api.path['cache'],
      zbi_tool_path=api.path['cache'],
  )


def GenTests(api):
  yield api.status_check.test('ensure_intel_sdk') + api.path.exists(
      api.path['cache']
      .join('builder/0.20200101.0.1/fuchsia_image/linux_intel_64/buildargs.gn'),
      api.path['cache'].join(
          'builder/0.20200101.0.1/fuchsia_image/linux_intel_64/qemu-kernel.kernel'
      ),
      api.path['cache'].join(
          'builder/0.20200101.0.1/fuchsia_image/linux_intel_64/storage-full.blk'
      ),
      api.path['cache']
      .join('builder/0.20200101.0.1/fuchsia_image/linux_intel_64/zircon-a.zbi'),
      api.path['cache']
      .join('builder/0.20200101.0.1/fuchsia_packages/linux_intel_64/pm'),
      api.path['cache'].join(
          'builder/0.20200101.0.1/fuchsia_packages/linux_intel_64/amber-files'
      ),
      api.path['cache'].join(
          'builder/0.20200101.0.1/fuchsia_packages/linux_intel_64/qemu-x64.tar.gz'
      ),
  ) + api.platform('linux', 64, 'intel')
  yield api.status_check.test('ensure_arm_sdk') + api.path.exists(
      api.path['cache']
      .join('builder/0.20200101.0.1/fuchsia_image/mac_arm_64/buildargs.gn'),
      api.path['cache'].join(
          'builder/0.20200101.0.1/fuchsia_image/mac_arm_64/qemu-kernel.kernel'
      ),
      api.path['cache']
      .join('builder/0.20200101.0.1/fuchsia_image/mac_arm_64/storage-full.blk'),
      api.path['cache']
      .join('builder/0.20200101.0.1/fuchsia_image/mac_arm_64/zircon-a.zbi'),
      api.path['cache']
      .join('builder/0.20200101.0.1/fuchsia_packages/mac_arm_64/pm'),
      api.path['cache']
      .join('builder/0.20200101.0.1/fuchsia_packages/mac_arm_64/amber-files'),
      api.path['cache'].join(
          'builder/0.20200101.0.1/fuchsia_packages/mac_arm_64/qemu-arm64.tar.gz'
      ),
  ) + api.platform('mac', 64, 'arm')
  yield api.status_check.test(
      'no_bit_match', status='failure'
  ) + api.platform('linux', 32)
  yield api.status_check.test('has_cache_sdk') + api.override_step_data(
      'ensure image.check image cache content',
      api.file.listdir([
          'buildargs.gn', 'qemu-kernel.kernel', 'storage-full.blk',
          'zircon-a.zbi'
      ]),
  ) + api.path.exists(
      api.path['cache']
      .join('builder/0.20200101.0.1/fuchsia_image/linux_intel_64/buildargs.gn'),
      api.path['cache'].join(
          'builder/0.20200101.0.1/fuchsia_image/linux_intel_64/qemu-kernel.kernel'
      ),
      api.path['cache'].join(
          'builder/0.20200101.0.1/fuchsia_image/linux_intel_64/storage-full.blk'
      ),
      api.path['cache']
      .join('builder/0.20200101.0.1/fuchsia_image/linux_intel_64/zircon-a.zbi'),
      api.path['cache']
      .join('builder/0.20200101.0.1/fuchsia_packages/linux_intel_64/pm'),
      api.path['cache'].join(
          'builder/0.20200101.0.1/fuchsia_packages/linux_intel_64/amber-files'
      ),
      api.path['cache'].join(
          'builder/0.20200101.0.1/fuchsia_packages/linux_intel_64/qemu-x64.tar.gz'
      ),
  )

  yield api.status_check.test(
      'missing_image_file', status='failure'
  ) + api.override_step_data(
      'ensure image.check image cache content',
      api.file.listdir([
          'buildargs.gn', 'qemu-kernel.kernel', 'storage-full.blk',
          'zircon-a.zbi'
      ]),
  ) + api.path.exists(
      api.path['cache']
      .join('builder/0.20200101.0.1/fuchsia_packages/linux_intel_64/pm'),
      api.path['cache'].join(
          'builder/0.20200101.0.1/fuchsia_packages/linux_intel_64/amber-files'
      ),
      api.path['cache'].join(
          'builder/0.20200101.0.1/fuchsia_packages/linux_intel_64/qemu-x64.tar.gz'
      ),
  )

  yield api.status_check.test(
      'missing_package_file', status='failure'
  ) + api.override_step_data(
      'ensure image.check image cache content',
      api.file.listdir([
          'buildargs.gn', 'qemu-kernel.kernel', 'storage-full.blk',
          'zircon-a.zbi'
      ]),
  ) + api.path.exists(
      api.path['cache']
      .join('builder/0.20200101.0.1/fuchsia_image/linux_intel_64/buildargs.gn'),
      api.path['cache'].join(
          'builder/0.20200101.0.1/fuchsia_image/linux_intel_64/qemu-kernel.kernel'
      ),
      api.path['cache'].join(
          'builder/0.20200101.0.1/fuchsia_image/linux_intel_64/storage-full.blk'
      ),
      api.path['cache']
      .join('builder/0.20200101.0.1/fuchsia_image/linux_intel_64/zircon-a.zbi'),
  )
