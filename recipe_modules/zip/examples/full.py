# Copyright 2014 The Chromium Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

DEPS = [
    'flutter/zip',
    'recipe_engine/context',
    'recipe_engine/file',
    'recipe_engine/path',
    'recipe_engine/platform',
    'recipe_engine/step',
    'recipe_engine/json',
]


def RunSteps(api):
  # Prepare files.
  temp = api.path.mkdtemp('zip-example')
  api.step('touch a', ['touch', temp / 'a'])
  api.step('touch b', ['touch', temp / 'b'])
  api.file.ensure_directory('mkdirs', temp / 'sub/dir')
  api.step('touch c', ['touch', temp / 'sub/dir/c'])

  # Build zip using 'zip.directory'.
  api.zip.directory('zipping', temp, temp / 'output.zip')

  # Build a zip using ZipPackage api.
  package = api.zip.make_package(temp, temp / 'more.zip')
  package.add_file(package.root / 'a')
  package.add_file(package.root / 'b')
  package.add_directory(package.root / 'sub')
  package.zip('zipping more')

  # Coverage for 'output' property.
  api.step('report', ['echo', package.output])

  # Unzip the package.
  api.zip.unzip('unzipping', temp / 'output.zip', temp / 'output', quiet=True)
  # List unzipped content.
  with api.context(cwd=temp / 'output'):
    api.step('listing', ['find'])

  # Retrieve zip file names list.
  expected_namelist = ['/a/b/c.txt']
  namelist = api.zip.namelist('namelist', temp / 'output.zip')
  assert namelist == expected_namelist

  # Clean up.
  api.file.rmtree('cleanup', temp)


def GenTests(api):
  for platform in ('linux', 'win', 'mac'):
    yield api.test(
        platform, api.platform.name(platform),
        api.zip.namelist('namelist', ['/a/b/c.txt'])
    )
