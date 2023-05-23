# Copyright 2023 The Chromium Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

import datetime
from recipe_engine import recipe_api

DEFAULT_TTL_SECS = 60 * 60 * 2  # 2 hours.
INFRA_BUCKET_NAME = 'flutter_archives_v2'


class CacheApi(recipe_api.RecipeApi):
  """Cache manager API.

  This API can be use to create caches on CAS, save metadata on GCS
  and mount caches within recipes. This is required to add caches
  support to subbuilds using generic builders.
  """

  def _metadata(self, cache_name):
    cloud_path = self._cache_path(cache_name)
    result = self.m.step(
        '%s exists' % cache_name, [
            'python3',
            self.m.depot_tools.gsutil_py_path,
            'stat',
            cloud_path,
        ],
        ok_ret='all'
    )
    # A return value of 0 means the file ALREADY exists on cloud storage
    return result.exc_result.retcode == 0

  def requires_refresh(self, cache_name):
    """Calculates if the cache needs to be refreshed.

    Args:
      cache_name (str): The name of the cache.
      ttl_seconds (int): Seconds from last update that the cache is still valid.
    """
    if not self._metadata(cache_name):
      return True
    cloud_path = self._cache_path(cache_name)
    result = self.m.gsutil.cat(cloud_path, stdout=self.m.json.output()).stdout
    last_cache = result.get('last_cache_ts_micro_seconds', 0)
    cache_ttl = result.get('cache_ttl_microseconds', 0)
    ms_since_epoch_now = 1684900396429444 if self._test_data.enabled else int(
        datetime.datetime.utcnow().timestamp() * 1e6
    )
    return (last_cache + cache_ttl) < ms_since_epoch_now

  def _cache_path(self, cache_name):
    platform = self.m.platform.name
    return 'gs://%s/caches/%s-%s.json' % (
        INFRA_BUCKET_NAME, cache_name, platform
    )

  def write(self, cache_name, paths, ttl_secs):
    cache_metadata = {}
    ms_since_epoch_now = 1684900396429444 if self._test_data.enabled else int(
        datetime.datetime.utcnow().timestamp() * 1e6
    )
    cache_metadata['last_cache_ts_micro_seconds'] = ms_since_epoch_now
    cache_metadata['cache_ttl_microseconds'] = int(ttl_secs * 1e6)
    cache_metadata['hashes'] = {}

    for path in paths:
      name = self.m.path.basename(path)
      hash_value = self.m.cas.archive('Archive %s' % name, path)
      cache_metadata['hashes'][name] = hash_value
    platform = self.m.platform.name
    local_cache_path = self.m.path['cleanup'].join(
        '%s-%s.json' % (cache_name, platform)
    )
    self.m.file.write_json(
        'Write cache metadata', local_cache_path, cache_metadata
    )
    metadata_gs_path = self._cache_path(cache_name)
    # Max age in seconds to cache the file.
    headers = {'Cache-Control': 'max-age=60'}
    self.m.archives.upload_artifact(
        local_cache_path, metadata_gs_path, metadata=headers
    )

  def mount_cache(self, cache_name, cache_root=None):
    cache_root = cache_root or self.m.path['CACHE']
    cloud_path = self._cache_path(cache_name)
    metadata = self.m.gsutil.cat(cloud_path, stdout=self.m.json.output()).stdout
    for k, v in metadata['hashes'].items():
      self.m.cas.download('Mounting %s with hash %s' % (k, v), v, cache_root)
