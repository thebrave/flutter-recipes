# Copyright 2017 The Fuchsia Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

from recipe_engine import recipe_api

TAR_VERSION = 'git_revision:6462ccda48c8f33dce4c80c2f1533263277d4da9'


class TarApi(recipe_api.RecipeApi):
  """Provides steps to tar and untar files."""

  COMPRESSION_OPTS = ["gzip", "bzip2", "xz", "lzma"]

  def __init__(self, *args, **kwargs):
    super().__init__(*args, **kwargs)
    self._tool_path = None

  def __call__(self, step_name, cmd):
    full_cmd = [self._bsdtar_path] + list(cmd)
    return self.m.step(step_name, full_cmd)

  @property
  def _bsdtar_path(self):
    """Ensures that bsdtar is installed."""
    if not self._tool_path:
      self._tool_path = self.m.cipd.ensure_tool(
          'fuchsia/tools/bsdtar/${platform}', TAR_VERSION
      )
    return self._tool_path

  def create(self, path, compression=None):
    """Returns TarArchive object that can be used to compress a set of files.

        Args:
          path: path of the archive file to be created.
          compression: str, one of COMPRESSION_OPTS or None to disable compression.
        """
    assert not compression or compression in TarApi.COMPRESSION_OPTS, (
        "compression must be one of %s",
        TarApi.COMPRESSION_OPTS,
    )
    return TarArchive(self.m, path, compression)

  def extract(self, step_name, path, directory=None, strip_components=None):
    """Uncompress |archive| file.

        Args:
          step_name: name of the step.
          path: absolute path to archive file.
          directory: directory to extract the archive in.
          strip_components: strip number of leading components from file names.
        """
    # We use long-form options whenever possible, but for options with
    # arguments, we have to use the short form. The recipe engine tests require
    # objects which might be placeholders (in this case |path|) to be their own
    # argument, and the version of tar we're using doesn't support
    # '--long-opt arg'. It only supports '--long-opt=arg' or short-form like
    # '-s arg'.
    cmd = [
        "--extract",
        "--verbose",
        "-f",
        path,
    ]
    if directory:
      cmd.extend(["-C", directory])
    if strip_components:
      cmd.extend(["--strip-components", str(int(strip_components))])
    return self(step_name, cmd)


class TarArchive:
  """Used to gather a list of files to tar."""

  def __init__(self, api, path, compression):
    self._api = api
    self._path = path
    self._compression = compression
    self._entries = {}

  @property
  def path(self):
    return self._path

  def add(self, path, directory=None):
    """Stages single file to be added to the package.

        Args:
          path: absolute path to a file, should be a child of |directory|.
          directory: ancestor directory of |path|. The name of the file
              inside the archive will not include |directory|. Defaults to $CWD.
        """
    if not directory:
      directory = self._api.context.cwd
    assert directory in path.parents, \
        "directory must be a parent of path. directory: %s.%s, path: %s.%s" % (
            directory.base,
            directory.pieces,
            path.base,
            path.pieces,
        )

    self._entries.setdefault(str(directory), []).append(str(path))

  def tar(self, step_name):
    """Step to tar all staged files."""
    cmd = ["--create", "-f", self._path]
    if self._compression:
      cmd.append("--%s" % self._compression)
    for directory in sorted(self._entries):
      cmd.extend(["-C", directory] + [
          self._api.path.relpath(p, directory) for p in self._entries[directory]
      ])

    step_result = self._api.tar(step_name, cmd)
    self._api.path.mock_add_paths(self._path)
    return step_result
