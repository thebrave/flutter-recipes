# Copyright 2014 The Chromium Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

from recipe_engine import recipe_api


class ZipApi(recipe_api.RecipeApi):
  """Provides steps to zip and unzip files."""

  def make_package(self, root, output):
    """Returns ZipPackage object that can be used to compress a set of files.

    Usage:
      pkg = api.zip.make_package(root, output)
      pkg.add_file(root.join('file'))
      pkg.add_directory(root.join('directory'))
      yield pkg.zip('zipping step')

    Args:
      root: a directory that would become root of a package, all files added to
          an archive will have archive paths relative to this directory.
      output: path to a zip file to create.

    Returns:
      ZipPackage object.
    """
    return ZipPackage(self.m, root, output)

  def directory(self, step_name, directory, output):
    """Step to compress a single directory.

    Args:
      step_name: display name of the step.
      directory: path to a directory to compress, it would become the root of
          an archive, i.e. |directory|/file.txt would be named 'file.txt' in
          the archive.
      output: path to a zip file to create.
    """
    pkg = self.make_package(directory, output)
    pkg.add_directory(directory)
    pkg.zip(step_name)

  def namelist(self, step_name, zip_file):
    """Step to get the name list of |zip_file|.

    Args:
      step_name: display name of a step.
      zip_file: path to a zip file to get its namelist, should exist.
    """
    script_input = {
        'zip_file': str(zip_file),
    }
    names_step = self.m.step(
        step_name,
        ['python3', self.resource('namelist.py')],
        stdin=self.m.json.input(script_input),
        stdout=self.m.json.output(),
    )
    return names_step.stdout or []

  def unzip(self, step_name, zip_file, output, quiet=False):
    """Step to uncompress |zip_file| into |output| directory.

    Zip package will be unpacked to |output| so that root of an archive is in
    |output|, i.e. archive.zip/file.txt will become |output|/file.txt.

    Step will FAIL if |output| already exists.

    Args:
      step_name: display name of a step.
      zip_file: path to a zip file to uncompress, should exist.
      output: path to a directory to unpack to, it should NOT exist.
      quiet (bool): If True, print terse output instead of the name
          of each unzipped file.
    """
    # TODO(vadimsh): Use 7zip on Windows if available?
    script_input = {
        'output': str(output),
        'zip_file': str(zip_file),
        'quiet': quiet,
    }
    self.m.step(
        step_name, ['python3', self.resource('unzip.py')],
        stdin=self.m.json.input(script_input)
    )


class ZipPackage(object):
  """Used to gather a list of files to zip."""

  def __init__(self, api, root, output):
    self._api = api
    self._root = root
    self._output = output
    self._entries = []

  @property
  def root(self):
    return self._root

  @property
  def output(self):
    return self._output

  def add_file(self, path, archive_name=None):
    """Stages single file to be added to the package.

    Args:
      path: absolute path to a file, should be in |root| subdirectory.
      archive_name: name of the file in the archive, if non-None
    """
    assert self._root.is_parent_of(path), path
    self._entries.append({
        'type': 'file', 'path': str(path), 'archive_name': archive_name
    })

  def add_directory(self, path):
    """Stages a directory with all its content to be added to the package.

    Args:
      path: absolute path to a directory, should be in |root| subdirectory.
    """
    # TODO(vadimsh): Implement 'exclude' filter.
    assert self._root.is_parent_of(path) or path == self._root, path
    self._entries.append({
        'type': 'dir',
        'path': str(path),
    })

  def zip(self, step_name):
    """Step to zip all staged files."""
    script_input = {
        'entries': self._entries,
        'output': str(self._output),
        'root': str(self._root),
    }
    step_result = self._api.step(
        step_name, ['python3', self._api.zip.resource('zip.py')],
        stdin=self._api.json.input(script_input)
    )
    self._api.path.mock_add_paths(self._output)
    return step_result
