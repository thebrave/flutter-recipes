# Copyright 2023 The Chromium Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

import contextlib
from recipe_engine.post_process import (Filter)

DEPS = [
    'flutter/signing',
    'flutter/zip',
    'recipe_engine/assertions',
    'recipe_engine/file',
    'recipe_engine/path',
    'recipe_engine/platform',
    'recipe_engine/properties',
    'recipe_engine/step',
]


@contextlib.contextmanager
def _create_zip(api, include_entitlements=False):
  with api.step.nest('Create test file'):
    directory = api.path.mkdtemp()
    api.file.write_text('write file', directory.join('content', 'myfile.txt'), 'myfile')
    if include_entitlements:
      api.file.write_text('write entitlements.txt', directory.join('content', 'entitlements.txt'), '')
      api.file.write_text('write without_entitlements.txt', directory.join('content', 'without_entitlements.txt'), '')
    api.zip.directory('create zip', directory.join('content'), directory.join('myzip.zip'))
    yield directory.join('myzip.zip')
    api.file.rmtree('Delete tmp folder', directory)

def RunSteps(api):
  expected_result = api.properties.get('expected_result')
  with _create_zip(api, expected_result) as zip_file_name:
    result = api.signing.requires_signing(zip_file_name)
    api.assertions.assertEqual(result, expected_result)


def GenTests(api):
  yield api.test(
     'non_mac',
     api.platform.name('linux'),
     api.properties(expected_result=False),
  )
  yield api.test(
     'mac_require_signing_entitlements',
     api.platform.name('mac'),
     api.properties(expected_result=True),
     api.zip.namelist('Create test file.namelist', ['myfile.txt', 'entitlements.txt'])
  )
  yield api.test(
     'mac_require_signing_without_entitlements',
     api.platform.name('mac'),
     api.properties(expected_result=True),
     api.zip.namelist('Create test file.namelist', ['myfile.txt', 'without_entitlements.txt'])
  )
  yield api.test(
     'mac_does_not_require_signing',
     api.platform.name('mac'),
     api.properties(expected_result=False),
  )
