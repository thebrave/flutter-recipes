# Copyright 2020 The Fuchsia Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

import attr

from recipe_engine import recipe_api
from recipe_engine.config_types import Path

SDK_GCS_BUCKET = 'fuchsia'


@attr.s
class ImageFilePaths(object):
  """Required files from fuchsia image to start FEMU."""

  # Recipe API, required
  _api = attr.ib(type=recipe_api.RecipeApi)

  # Files from fuchsia image
  build_args = attr.ib(type=Path, default=None)
  kernel_file = attr.ib(type=Path, default=None)
  system_fvm = attr.ib(type=Path, default=None)
  zircona = attr.ib(type=Path, default=None)

  def _exists(self, p):
    return p and self._api.path.exists(p)

  def _exist(self):
    return all([
        self._exists(self.build_args),
        self._exists(self.kernel_file),
        self._exists(self.system_fvm),
        self._exists(self.zircona),
    ])

  def _report_missing(self):
    result = []
    if not self._exists(self.build_args):
      result.append(self.build_args)
    if not self._exists(self.kernel_file):
      result.append(self.kernel_file)
    if not self._exists(self.system_fvm):
      result.append(self.system_fvm)
    if not self._exists(self.zircona):
      result.append(self.zircona)
    return result


@attr.s
class PackageFilePaths(object):
  # Recipe API, required
  _api = attr.ib(type=recipe_api.RecipeApi, init=True)

  # Files from fuchsia packages
  tar_file = attr.ib(type=Path, default=None)
  amber_files = attr.ib(type=Path, default=None)
  pm = attr.ib(type=Path, default=None)

  def _exists(self, p):
    return p and self._api.path.exists(p)

  def _exist(self):
    return all([
        self._exists(self.tar_file),
        self._exists(self.amber_files),
        self._exists(self.pm),
    ])

  def _report_missing(self):
    result = []
    if not self._exists(self.tar_file):
      result.append(self.tar_file)
    if not self._exists(self.amber_files):
      result.append(self.amber_files)
    if not self._exists(self.pm):
      result.append(self.pm)
    return result


class SDKApi(recipe_api.RecipeApi):
  """Downloads Fuchsia SDK files required to start FEMU."""

  def __init__(self, *args, **kwargs):
    super(SDKApi, self).__init__(*args, **kwargs)
    self._image_paths = ImageFilePaths(api=self.m)
    self._package_paths = PackageFilePaths(api=self.m)
    self._sdk_path = None
    self._version = None

  def _fetch_sdk(self):
    """Downloads Fuchsia SDK from GCS and untar."""
    with self.m.step.nest('ensure sdk'):
      with self.m.context(infra_steps=True):
        # Ensure cache path has the correct permission
        cache_path = self.m.buildbucket.builder_cache_path.join(
            self.version, 'fuchsia_sdk', self.platform_name
        )
        self.m.file.ensure_directory('init fuchsia_sdk cache', cache_path)
        if not self.m.file.listdir(name='check sdk cache content',
                                   source=cache_path, test_data=()):
          # Copy GN image to temp directory
          sdk_file = 'gn.tar.gz'
          local_tmp_root = self.m.path.mkdtemp('fuchsia_sdk_tmp')
          self.m.gsutil.download(
              src_bucket=SDK_GCS_BUCKET,
              src=self.m.path.join(
                  'development',
                  self.version,
                  'sdk',
                  self.sdk_platform_name,
                  sdk_file,
              ),
              dest=local_tmp_root,
          )
          # Extract sdk
          self.m.tar.extract(
              step_name='extract sdk gz',
              path=self.m.path.join(local_tmp_root, sdk_file),
              directory=cache_path,
          )

        # Save cache path
        self._sdk_path = cache_path

  def _fetch_image(self):
    """Downloads Fuchsia image from GCS. Untar and store the required paths for FEMU."""
    with self.m.step.nest('ensure image'):
      with self.m.context(infra_steps=True):
        image_to_download = self._select_image_to_download()
        # Ensure cache path has the correct permission
        cache_path = self.m.buildbucket.builder_cache_path.join(
            self.version, 'fuchsia_image', self.platform_name
        )
        self.m.file.ensure_directory('init fuchsia_image cache', cache_path)

        if not self.m.file.listdir(name='check image cache content',
                                   source=cache_path, test_data=()):
          # Copy image to temp directory
          local_tmp_path = self.m.path.mkdtemp('fuchsia_image_tmp')
          self.m.gsutil.download(
              src_bucket=SDK_GCS_BUCKET,
              src=self.m.path.join(
                  'development', self.version, 'images', image_to_download
              ),
              dest=local_tmp_path,
          )

          # Extract image
          self.m.tar.extract(
              step_name='extract image tgz',
              path=self.m.path.join(local_tmp_path, image_to_download),
              directory=cache_path,
          )
        # Assemble files required for FEMU
        for p in self.m.file.listdir(
            name='set image files',
            source=cache_path,
            test_data=(
                'buildargs.gn',
                'qemu-kernel.kernel',
                'zircon-a.zbi',
                'zircon-r.zbi',
                'storage-sparse.blk',
                'storage-full.blk',
            ),
        ):
          base = self.m.path.basename(p)
          if base == 'buildargs.gn':
            self._image_paths.build_args = p
          elif base == 'qemu-kernel.kernel':
            self._image_paths.kernel_file = p
          elif base == 'storage-full.blk':
            self._image_paths.system_fvm = p
          elif base == 'zircon-a.zbi':
            self._image_paths.zircona = p

  def _fetch_packages(self):
    with self.m.step.nest('ensure packages'):
      with self.m.context(infra_steps=True):
        package_to_download = self._select_package_to_download()
        # Ensure cache path has the correct permission
        cache_path = self.m.buildbucket.builder_cache_path.join(
            self.version, 'fuchsia_packages', self.platform_name
        )
        self.m.file.ensure_directory('init fuchsia_packages cache', cache_path)

        if not self.m.file.listdir(name='check packages cache content',
                                   source=cache_path, test_data=()):
          # Copy packages to cache directory.
          # TODO(yuanzhi) Copy to tmp. We need to keep this in cache because fuchsia_ctl
          # used by the flutter team expects packages as .tar.gz input. However, we should
          # use fuchsia device controller (FDC) that comes with VDL for FEMU based testing
          # eventually.
          self.m.gsutil.download(
              src_bucket=SDK_GCS_BUCKET,
              src=self.m.path.join(
                  'development', self.version, 'packages', package_to_download
              ),
              dest=cache_path,
          )

          # Extract package, this will produce the following subdirectories:
          # |cache_path|
          #   |__ amber-files
          #      |__ keys
          #      |__ repository
          #   |__ pm
          self.m.tar.extract(
              step_name='extract package tar.gz',
              path=self.m.path.join(cache_path, package_to_download),
              directory=cache_path,
          )
        self._package_paths.tar_file = cache_path.join(package_to_download)
        self._package_paths.amber_files = cache_path.join('amber-files')
        self._package_paths.pm = cache_path.join('pm')

  def authorize_zbi(
      self,
      ssh_key_path,
      zbi_input_path,
      zbi_output_path=None,
      zbi_tool_path=None
  ):
    """Use zbi tool to extend BootFS with SSH authorization key.

    Arguments:
      ssh_key_path: path to public ssh key file.
      zbi_input_path: path to zircon-a.zbi file.
      zbi_output_path: (optional) output path to store extended zbi image file.
        if None, we will replace zircon file specified in zbi_input_path
      zbi_tool_path: (optional) path to the zbi binary tool.
        if None, we will fetch the zbi tool from fuchsia sdk in GCS.
    """
    zbi_path = None
    if zbi_tool_path:
      zbi_path = zbi_tool_path
    if not zbi_path:
      zbi_path = self.m.path.join(self.sdk_path, 'tools', 'zbi')
    if not zbi_output_path:
      zbi_output_path = zbi_input_path

    self.m.step(
        "authorize zbi",
        [
            zbi_path,
            "--output",
            self.m.raw_io.output_text(leak_to=zbi_output_path),
            zbi_input_path,
            "--entry",
            "%s=%s" % ('data/ssh/authorized_keys', ssh_key_path),
        ],
    )

  def _select_package_to_download(self):
    """Maps platform parameters to Package names."""
    return 'qemu-{arch}.tar.gz'.format(arch=self._select_arch())

  def _select_image_to_download(self):
    """Maps platform parameters to Image names."""
    return 'qemu-{arch}.tgz'.format(arch=self._select_arch())

  def _select_arch(self):
    """Maps platform parameters to SDK names."""
    if self.m.platform.arch == 'arm' and self.m.platform.bits == 64:
      return 'arm64'
    elif self.m.platform.arch == 'intel' and self.m.platform.bits == 64:
      return 'x64'
    raise self.m.step.StepFailure(
        'Cannot find supported tools. arch %s, bit %s' %
        (self.m.platform.arch, self.m.platform.bits)
    )

  @property
  def sdk_platform_name(self):
    """Derives the sdk package platform name, resembles the CIPD platform name."""
    name = ''
    if self.m.platform.is_linux:
      name = 'linux-amd64'
    elif self.m.platform.is_mac:
      name = 'mac-amd64'
    return name

  @property
  def platform_name(self):
    return '%s_%s_%s' % (
        self.m.platform.name,
        self.m.platform.arch,
        self.m.platform.bits,
    )

  @property
  def version(self):
    return self._version

  @version.setter
  def version(self, value):
    self._version = value

  @property
  def image_paths(self):
    """Downloads and unpacks Fuchsia image files from GCS.

    Raises:
      StepFailure: When cannot find image files matching host architecture.
      StepFailure: When image files do not exist after download and unpack from GCS.
    """
    assert self.version
    self._fetch_image()
    if not self._image_paths._exist():
      missing = self._image_paths._report_missing()
      ex = self.m.step.StepFailure(
          'Image paths do not exist. {missing_paths}'.format(
              missing_paths=missing
          )
      )
      ex.missing_paths = missing
      raise ex
    return self._image_paths

  @property
  def package_paths(self):
    """Downloads and unpacks Fuchsia package files from GCS.

    Raises:
      StepFailure: When cannot find package files matching host architecture.
      StepFailure: When package files do not exist after download and unpack from GCS.
    """
    assert self.version
    self._fetch_packages()
    if not self._package_paths._exist():
      missing = self._package_paths._report_missing()
      ex = self.m.step.StepFailure(
          'Package paths do not exist. {missing_paths}'.format(
              missing_paths=missing
          )
      )
      ex.missing_paths = missing
      raise ex
    return self._package_paths

  @property
  def sdk_path(self):
    """Downloads and unpacks Fuchsia sdk files from GCS.

    Raises:
      StepFailure: When cannot find sdk files matching host architecture.
    """
    assert self.version
    self._fetch_sdk()
    return self._sdk_path
