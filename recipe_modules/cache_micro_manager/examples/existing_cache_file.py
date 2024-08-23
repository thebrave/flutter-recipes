DEPS = [
  'flutter/cache_micro_manager',
  'recipe_engine/file',
  'recipe_engine/json',
  'recipe_engine/path',
  'recipe_engine/raw_io',
  'recipe_engine/step',
  'recipe_engine/properties',
]


from recipe_engine.post_process import MustRun

from datetime import datetime
from datetime import timedelta
from unittest.mock import Mock


def RunSteps(api):
  cache_target_dir = api.path.cache_dir.join('osx_sdk')

  fake_dirdep_1_path = cache_target_dir.join('fake_dep_package_1')
  fake_filedep_1_path = cache_target_dir.join('fake_dep_file_1')
  fake_filedep_2_path = cache_target_dir.join('fake_dep_file_2')

  fake_expired_file = cache_target_dir.join('fake_expired_file')

  cache_file_name = cache_target_dir.join('.osx_sdk_cache_metadata.json')

  api.path.mock_add_directory(fake_dirdep_1_path)
  api.path.mock_add_file(fake_filedep_1_path)
  api.path.mock_add_file(fake_filedep_2_path)

  api.path.mock_add_file(cache_file_name)
  api.path.mock_add_file(fake_expired_file)

  deps_list = ['fake_dep_package_1', 'fake_dep_file_1', 'new_dep_5']

  api.cache_micro_manager.today = Mock(return_value=datetime(2023, 12, 15, 13, 43, 21, 621929))

  api.step('run cache micro manager', api.cache_micro_manager.run(cache_target_dir, deps_list))

def ComputeJsonFileData() -> str:
  '''Compute relative test data to "today" for the datetimes used in testing.
  '''
  datetime_now = datetime(2023, 12, 15, 13, 43, 21, 621929)
  datetime_removal_delta = timedelta(days=30)

  fake_dep_file_1_updated = datetime.strftime(datetime_now, "%m/%d/%Y, %H:%M:%S")
  fake_dep_file_1_removal = datetime.strftime(datetime_now + datetime_removal_delta, "%m/%d/%Y, %H:%M:%S")

  fake_dep_package_1_updated = datetime.strftime(datetime_now, "%m/%d/%Y, %H:%M:%S")
  fake_dep_package_1_removal = datetime.strftime(datetime_now + datetime_removal_delta, "%m/%d/%Y, %H:%M:%S")

  # TODO remove this code when the old time types have been updated.
  fake_dep_package_old_time_delta = datetime_now - timedelta(days=60)
  fake_dep_package_old_time_updated = datetime.strftime(fake_dep_package_old_time_delta, "%m/%d/%Y")
  fake_dep_package_old_time_removal = datetime.strftime(fake_dep_package_old_time_delta + datetime_removal_delta, "%m/%d/%Y")

  fake_dep_package_2_time_and_delta = datetime_now - timedelta(days=365)
  fake_dep_package_2_updated = datetime.strftime(fake_dep_package_2_time_and_delta, "%m/%d/%Y, %H:%M:%S")
  fake_dep_package_2_removal = datetime.strftime(fake_dep_package_2_time_and_delta + datetime_removal_delta, "%m/%d/%Y, %H:%M:%S")

  fake_expired_file_time_and_delta = datetime_now - timedelta(days=380)
  fake_expired_file_updated = datetime.strftime(fake_expired_file_time_and_delta, "%m/%d/%Y, %H:%M:%S")
  fake_expired_file_removal = datetime.strftime(fake_expired_file_time_and_delta + datetime_removal_delta, "%m/%d/%Y, %H:%M:%S")

  dep_not_in_dir_time_and_delta = datetime_now - timedelta(days=720)
  dep_not_in_dir_updated = datetime.strftime(dep_not_in_dir_time_and_delta, "%m/%d/%Y, %H:%M:%S")
  dep_not_in_dir_removal = datetime.strftime(dep_not_in_dir_time_and_delta + datetime_removal_delta, "%m/%d/%Y, %H:%M:%S")

  return '''
        [
            {{
                \"name\": \"fake_dep_file_1\",
                \"updated_date\": \"{0}\",
                \"removal_date\": \"{1}\"
            }},
            {{
                \"name\": \"fake_dep_package_1\",
                \"updated_date\": \"{2}\",
                \"removal_date\": \"{3}\"
            }},
            {{
                \"name\": \"fake_dep_package_2\",
                \"updated_date\": \"{4}\",
                \"removal_date\": \"{5}\"
            }},
            {{
                \"name\": \"fake_expired_file\",
                \"updated_date\": \"{6}\",
                \"removal_date\": \"{7}\"
            }},
            {{
                \"name\": \"dep_not_in_dir\",
                \"updated_date\": \"{8}\",
                \"removal_date\": \"{9}\"
            }},
            {{
                \"name\": \"fake_dep_package_old_time\",
                \"updated_date\": \"{10}\",
                \"removal_date\": \"{11}\"
            }}
        ]
        '''.format(
          fake_dep_file_1_updated,
          fake_dep_file_1_removal,
          fake_dep_package_1_updated,
          fake_dep_package_1_removal,
          fake_dep_package_2_updated,
          fake_dep_package_2_removal,
          fake_expired_file_updated,
          fake_expired_file_removal,
          dep_not_in_dir_updated,
          dep_not_in_dir_removal,
          fake_dep_package_old_time_updated,
          fake_dep_package_old_time_removal,
        )


def GenTests(api):
  yield (
    api.test(
      'cache_metadata_exists_is_created',
      api.step_data(
        "Running Cache Micro Manager on [CACHE]/osx_sdk..Reading metadata file [CACHE]/osx_sdk/.osx_sdk_cache_metadata.json.Reading [CACHE]/osx_sdk/.osx_sdk_cache_metadata.json",
        api.file.read_text(
        ComputeJsonFileData())
      ),
      api.step_data(
        'Running Cache Micro Manager on [CACHE]/osx_sdk..Reading cache directory [CACHE]/osx_sdk',
        api.file.listdir(['fake_dep_file_1', 'fake_dep_package_1', 'fake_dep_package_old_time', 'fake_dep_package_2', 'fake_expired_file', 'new_dep_5', '.osx_sdk_cache_metadata.json'])
      ),
      api.post_check(
        MustRun,
        'Running Cache Micro Manager on [CACHE]/osx_sdk..Writing cache metadata file.'
      )
    )
  )
