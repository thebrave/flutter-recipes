# Copyright 2020 The Fuchsia Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

from recipe_engine import recipe_api

from RECIPE_MODULES.fuchsia.utils import cached_property

VDL_CIPD_PREFIX = 'fuchsia/vdl/${platform}'
DEFAULT_VDL_VERSION_TAG = 'latest'
# Fuchsia provides back-tagging for certain packages when they are rolled
# into the Fuchsia tree. This `integration` ref will always point at what
# is currently used by Fuchsia @ HEAD. It would be better to export this
# in the SDK so it is coupled to the SDK version but that is not done.
DEFAULT_AEMU_VERSION_TAG = 'integration'

_DEVICE_SPEC_TEMPLATE = """
device_spec {{
  horizontal_resolution: {horizontal_resolution}
  vertical_resolution: {vertical_resolution}
  vm_heap: {vm_heap}
  ram: {ram}
  cache: {cache}
  screen_density: {screen_density}
}}
"""


class VDLApi(recipe_api.RecipeApi):
  """Fetches VDL and AEMU to start FEMU."""

  def __init__(self, *args, **kwargs):
    super(VDLApi, self).__init__(*args, **kwargs)
    self._aemu_version_tag = DEFAULT_AEMU_VERSION_TAG
    self._vdl_version_tag = DEFAULT_VDL_VERSION_TAG
    self._device_proto_path = None

  @cached_property
  def vdl_path(self):
    """Fetches and installs VDL from CIPD."""
    with self.m.step.nest('ensure vdl'):
      with self.m.context(infra_steps=True):
        ensure_file = self.m.cipd.EnsureFile()
        ensure_file.add_package(VDL_CIPD_PREFIX, self._vdl_version_tag)
        cache_path = self.m.buildbucket.builder_cache_path.join('vdl')
        self.m.cipd.ensure(root=cache_path, ensure_file=ensure_file)
        return cache_path.join('device_launcher')

  @cached_property
  def aemu_dir(self):
    """Fetches and installs AEMU from CIPD."""
    with self.m.step.nest('ensure aemu'):
      with self.m.context(infra_steps=True):
        ensure_file = self.m.cipd.EnsureFile()
        ensure_file.add_package(
            'fuchsia/third_party/android/aemu/release/${platform}', self._aemu_version_tag
        )
        cache_path = self.m.buildbucket.builder_cache_path.join('aemu')
        self.m.cipd.ensure(root=cache_path, ensure_file=ensure_file)
        return cache_path

  def create_device_proto(
      self,
      horizontal_resolution=480,
      vertical_resolution=800,
      vm_heap=192,
      ram=4096,
      cache=32,
      screen_density=240,
  ):
    """Generates virtual device textproto file used by VDL to configure AEMU."""
    device_spec_cache = self.m.buildbucket.builder_cache_path.join(
        'device_spec'
    )
    self.m.file.ensure_directory(
        'init device spec cache at ', device_spec_cache
    )
    device_spec_location = device_spec_cache.join('virtual_device.textproto')
    self.m.file.write_text(
        name='generate %s' % device_spec_location,
        dest=device_spec_location,
        text_data=_DEVICE_SPEC_TEMPLATE.format(
            horizontal_resolution=horizontal_resolution,
            vertical_resolution=vertical_resolution,
            vm_heap=vm_heap,
            ram=ram,
            cache=cache,
            screen_density=screen_density,
        ),
    )
    self._device_proto_path = device_spec_location
    return device_spec_location

  def set_aemu_cipd_tag(self, tag):
    """Changes the default aemu cipd package tag.

    Must be called before calling `aemu_dir`.
    """
    self._aemu_version_tag = tag

  def set_vdl_cipd_tag(self, tag):
    """Changes the default vdl cipd package tag.

    Must be called before calling `vdl_path`.
    """
    self._vdl_version_tag = tag

  def get_image_paths(self, sdk_version):
    """Downloads and unpacks fuchsia image from GCS.

    Args:
      sdk_version: Fuchsia sdk version to fetch.
    Raises:
      StepFailure: When cannot find image files matching host architecture.
      StepFailure: When image files do not exist after download and unpack from GCS.
    """
    self.m.sdk.version = sdk_version
    return self.m.sdk.image_paths

  def get_package_paths(self, sdk_version):
    """Downloads and unpacks fuchsia packages from GCS.

    Args:
      sdk_version: Fuchsia sdk version to fetch.
    Raises:
      StepFailure: When cannot find package files matching host architecture.
      StepFailure: When package files do not exist after download and unpack from GCS.
    """
    self.m.sdk.version = sdk_version
    return self.m.sdk.package_paths

  def gen_ssh_files(self):
    """Generate ssh private-public key pairs.

    Raises:
      StepFailure: When ssh key paths do not contain valid files.
    """
    return self.m.ssh.ssh_paths

  def assemble_femu_startup_files(
      self,
      sdk_version,
      vdl_tag=None,
      aemu_tag=None,
      create_links=True,
      extra_files={},
  ):
    """
    Assembles all required files to start FEMU.

    Args:
      sdk_version: Fuchsia sdk version to fetch.
      vdl_tag: Changes the default vdl cipd package tag.
      aemu_tag: Changes the default aemu cipd package tag.
      create_links: True will create symlinks. False will not.
        If set to false, user has to call symlink_tree.create_links().
      extra_files: A dictionary to add additional files to root dir.
        key: Source of the file, must be type Path.
        value: Relative path to root_dir.
        Example: {
          [CACHE]/builder/fileOld.txt : "fileNew.txt"
        }
        This will add a new link from fileOld.txt to root_dir/fileNew.txt
        in the symlink_tree.
    Raises:
      StepFailure: When ssh key paths do not contain valid files.
      StepFailure: When cannot find package files matching host architecture.
      StepFailure: When cannot find image files matching host architecture.
      StepFailure: When package files do not exist after download and unpack from GCS.
      StepFailure: When image files do not exist after download and unpack from GCS.
    """
    root_dir = self.m.path.mkdtemp('vdl_runfiles_')
    symlink_tree = self.m.file.symlink_tree(root=root_dir)

    def add(src, name_rel_to_root):
      symlink_tree.register_link(
          target=src,
          linkname=symlink_tree.root.join(name_rel_to_root),
      )

    def add_vdl_files():
      if vdl_tag:
        self.set_vdl_cipd_tag(tag=vdl_tag)
      if aemu_tag:
        self.set_aemu_cipd_tag(tag=aemu_tag)
      add(self.vdl_path, 'device_launcher')
      add(self.aemu_dir, 'aemu')
      add(self.create_device_proto(), 'virtual_device.textproto')

    def add_package_files():
      fuchsia_packages = self.get_package_paths(sdk_version=sdk_version)
      add(fuchsia_packages.pm, self.m.path.basename(fuchsia_packages.pm))
      add(fuchsia_packages.tar_file, 'package_archive')
      add(
          fuchsia_packages.amber_files,
          self.m.path.basename(fuchsia_packages.amber_files),
      )

    def add_image_files():
      ssh_files = self.gen_ssh_files()
      add(ssh_files.id_public, self.m.path.basename(ssh_files.id_public))
      add(ssh_files.id_private, self.m.path.basename(ssh_files.id_private))

      fuchsia_images = self.get_image_paths(sdk_version=sdk_version)
      add(fuchsia_images.build_args, 'qemu_buildargs')
      add(fuchsia_images.kernel_file, 'qemu_kernel')
      add(fuchsia_images.system_fvm, 'qemu_fvm')
      add(self.m.sdk.sdk_path.join('tools', 'far'), 'far')
      add(self.m.sdk.sdk_path.join('tools', 'fvm'), 'fvm')

      # Provision and add zircon-a
      authorized_zircona = self.m.buildbucket.builder_cache_path.join(
          'zircon-authorized.zbi'
      )
      self.m.sdk.authorize_zbi(
          ssh_key_path=ssh_files.id_public,
          zbi_input_path=fuchsia_images.zircona,
          zbi_output_path=authorized_zircona,
      )
      add(authorized_zircona, 'qemu_zircona-ed25519')

      # Generate and add ssh_config
      ssh_config = self.m.buildbucket.builder_cache_path.join('ssh_config')
      self.m.ssh.generate_ssh_config(
          private_key_path=self.m.path.basename(ssh_files.id_private),
          dest=ssh_config,
      )
      add(ssh_config, 'ssh_config')

    def add_extra_files():
      for src in extra_files:
        add(src, extra_files[src])

    add_vdl_files()
    add_image_files()
    add_package_files()
    add_extra_files()

    if create_links:
      symlink_tree.create_links('create tree of vdl runfiles')

    return root_dir, symlink_tree
