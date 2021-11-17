# Copyright 2020 The Fuchsia Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

PYTHON_VERSION_COMPATIBILITY = 'PY3'

DEPS = [
    'flutter/vdl',
    'fuchsia/status_check',
    'recipe_engine/path',
]


def RunSteps(api):
  api.vdl.assemble_femu_startup_files(
      sdk_version='0.20200101.0.1',
      vdl_tag='g3-revision:vdl_fuchsia_20200729_RC00',
      aemu_tag='git_revision:825431f5e4eb46770606ad91697974348d3706da',
      extra_files={
          api.path['cache'].join('file1'): 'foo',
          api.path['cache'].join('file2'): 'bar',
      },
  )


def GenTests(api):
  yield api.status_check.test('ensure_vdl') + api.path.exists(
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
      api.path['cache'].join('builder/ssh/id_ed25519.pub'),
      api.path['cache'].join('builder/ssh/id_ed25519'),
      api.path['cache'].join('builder/ssh/ssh_host_key.pub'),
      api.path['cache'].join('builder/ssh/ssh_host_key'),
      api.path['cache'].join('file1'),
      api.path['cache'].join('file2'),
  )

  yield api.status_check.test(
      'vdl_missing_image_files', status='failure'
  ) + api.path.exists(
      api.path['cache']
      .join('builder/0.20200101.0.1/fuchsia_packages/linux_intel_64/pm'),
      api.path['cache'].join(
          'builder/0.20200101.0.1/fuchsia_packages/linux_intel_64/amber-files'
      ),
      api.path['cache'].join(
          'builder/0.20200101.0.1/fuchsia_packages/linux_intel_64/qemu-x64.tar.gz'
      ),
      api.path['cache'].join('builder/ssh/id_ed25519.pub'),
      api.path['cache'].join('builder/ssh/id_ed25519'),
      api.path['cache'].join('builder/ssh/ssh_host_key.pub'),
  )
  yield api.status_check.test(
      'vdl_missing_package_files', status='failure'
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
      api.path['cache'].join('builder/ssh/id_ed25519.pub'),
      api.path['cache'].join('builder/ssh/id_ed25519'),
      api.path['cache'].join('builder/ssh/ssh_host_key.pub'),
  )
  yield api.status_check.test(
      'vdl_missing_ssh_files', status='failure'
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
