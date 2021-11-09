# Copyright 2020 The Chromium Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

from recipe_engine.post_process import DropExpectation

PYTHON_VERSION_COMPATIBILITY = 'PY2+3'

DEPS = [
    'flutter/bucket_util',
    'flutter/zip',
    'recipe_engine/buildbucket',
    'recipe_engine/path',
    'recipe_engine/properties',
    'recipe_engine/runtime',
]


def RunSteps(api):
  api.bucket_util.upload_folder(
      'Upload test.zip', # dir_label
      'src', # parent_directory
      'build', # folder_name
      'test1.zip') # zip_name

  api.bucket_util.upload_folder_and_files(
      'Upload test.zip', # dir_label
      'src', # parent_directory
      'build', # folder_name
      'test2.zip',  # zip_name
      file_paths=['a.txt'])

  api.bucket_util.upload_folder_and_files(
      'Upload test.zip', # dir_label
      'src', # parent_directory
      'build', # folder_name
      'test3.zip', # zip_name
      platform='parent_directory',
      file_paths=['a.txt'])

  # Prepare files.
  temp = api.path.mkdtemp('bucketutil-example')

  local_zip = temp.join('output.zip')
  package = api.zip.make_package(temp, local_zip)

  # Add files to zip package.
  api.bucket_util.add_files(package, ['a', 'b'])
  api.bucket_util.add_directories(package, ['sub'])
  package.zip('zipping')

  api.bucket_util.safe_upload(
      local_zip, # local_path
      "foo", # remote_path
      skip_on_duplicate=True)

  if api.properties.get('try_bad_file', False):
    api.bucket_util.safe_upload(
        temp.join('A_file_that_does_not_exist'), # local_path
        'bar', # remote_path
        skip_on_duplicate=True,
        add_mock=False)


def GenTests(api):
  yield api.test(
      'basic',
      api.properties(
          upload_packages=False,
      ),
  )
  yield api.test(
      'basic with fail',
      api.properties(
          upload_packages=False,
          try_bad_file=True,
      ),
      api.expect_exception('AssertionError'), # the non-existent file
      # Expectation file would contain a brittle stack trace.
      # TODO: Re-enable the expectation file after Python 2 support is no longer
      # required.
      api.post_process(DropExpectation),
  )
  yield api.test(
      'upload_packages',
      api.properties(
          upload_packages=True,
      ),
      # These ids are UUIDs derivated from a fixed seed.
      # To get new ids, just run the test and use the ids generated
      # by the uuid module.
      api.step_data(
          'Ensure flutter/00000000-0000-0000-0000-000000001337/test1.zip '
          'does not already exist on cloud storage',
          retcode=1,
      ),
      api.step_data(
          'Ensure flutter/00000000-0000-0000-0000-00000000133a/test2.zip '
          'does not already exist on cloud storage',
          retcode=1,
      ),
      api.step_data(
          'Ensure '
          'flutter/00000000-0000-0000-0000-00000000133d/parent_directory/test3.zip '
          'does not already exist on cloud storage',
          retcode=1,
      ),
  )
  yield api.test(
      'upload_packages_if_commit_is_present',
      api.properties(
          upload_packages=True,
      ),
      api.buildbucket.ci_build(
          git_repo='github.com/flutter/engine',
          revision='8b3cd40a25a512033cc8c0797e41de9ecfc2432c'),
      api.step_data(
          'Ensure flutter/8b3cd40a25a512033cc8c0797e41de9ecfc2432c/test1.zip '
          'does not already exist on cloud storage',
          retcode=1,
      ),
      api.step_data(
          'Ensure flutter/8b3cd40a25a512033cc8c0797e41de9ecfc2432c/test2.zip '
          'does not already exist on cloud storage',
          retcode=1,
      ),
      api.step_data(
          'Ensure '
          'flutter/8b3cd40a25a512033cc8c0797e41de9ecfc2432c/parent_directory/test3.zip '
          'does not already exist on cloud storage',
          retcode=1,
      ),
  )
  yield api.test(
      'upload_packages_tiggers_exception_and_package_exists',
      api.properties(
          upload_packages=True,
      ),
      api.expect_exception('AssertionError'),
      # Expectation file would contain a brittle stack trace.
      # TODO: Re-enable the expectation file after Python 2 support is no longer
      # required.
      api.post_process(DropExpectation),
  )
  yield api.test(
      'upload_packages_experimental_runtime',
      api.runtime(is_experimental=True),
      api.properties(
          upload_packages=True,
      ),
  )
