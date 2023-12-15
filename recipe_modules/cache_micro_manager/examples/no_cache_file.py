DEPS = [
  'flutter/cache_micro_manager',
  'recipe_engine/file',
  'recipe_engine/path',
  'recipe_engine/raw_io',
  'recipe_engine/step',
  'recipe_engine/properties',
]

from recipe_engine.post_process import MustRun

from datetime import datetime
from unittest.mock import Mock

def RunSteps(api):
  cache_target_dir = api.path['cache'].join('osx_sdk')

  fake_dirdep_1_path = cache_target_dir.join('fake_dep_package_1')
  fake_filedep_1_path = cache_target_dir.join('fake_dep_file_1')
  fake_filedep_2_path = cache_target_dir.join('fake_dep_file_2')

  fake_expired_file = cache_target_dir.join('fake_expired_file')

  api.path.mock_add_directory(fake_dirdep_1_path)
  api.path.mock_add_file(fake_filedep_1_path)
  api.path.mock_add_file(fake_filedep_2_path)

  api.path.mock_add_file(fake_expired_file)

  deps_list = ['fake_dep_package_1', 'fake_dep_file_1', 'new_dep_5']

  api.cache_micro_manager.today = Mock(return_value=datetime(2023, 12, 15, 13, 43, 21, 621929))

  api.step('run cache micro manager', api.cache_micro_manager.run(cache_target_dir, deps_list))


def GenTests(api):
  yield (
    api.test(
      'cache_metadata_exists_is_created',
      api.step_data(
        'Running Cache Micro Manager on [CACHE]/osx_sdk..Reading cache directory [CACHE]/osx_sdk',
        api.file.listdir(['fake_dep_file_1', 'fake_dep_package_1', 'fake_dep_package_2', 'fake_expired_file', 'new_dep_5'])
      ),
      api.post_check(
        MustRun,
        'Running Cache Micro Manager on [CACHE]/osx_sdk..Writing cache metadata file.'
      )
    )
  )
