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

  deps_list = ['fake_dep_package_1', 'fake_dep_file_1', 'new_dep_5']

  api.cache_micro_manager.today = Mock(return_value=datetime(2023, 12, 15, 13, 43, 21, 621929))

  api.step('run cache micro manager', api.cache_micro_manager.run('dne', deps_list))


def GenTests(api):
  yield (
    api.test(
      'cache_directory_does_not_exist',
      api.post_check(
        MustRun,
        'Running Cache Micro Manager on dne..Cache Micro Manager, cache directory exists check'
      )
    )
  )