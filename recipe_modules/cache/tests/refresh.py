# Copyright 2023 The Chromium Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

DEPS = [
    'flutter/cache',
    'recipe_engine/assertions',
    'recipe_engine/json',
    'recipe_engine/path',
]


def RunSteps(api):
  result = api.cache.requires_refresh('builder')
  api.assertions.assertTrue(result)
  paths = [
      api.path.cache_dir.join('builder'),
      api.path.cache_dir.join('git'),
  ]
  api.cache.write('builder', paths, 60)
  api.cache.mount_cache('builder', api.path.cache_dir)
  api.cache.should_force_mount(api.path.cache_dir.join('builder'))


def GenTests(api):
  metadata = {'hashes': {'builder': 'hash1', 'git': 'hash2'}}
  yield api.test(
      'basic', api.step_data(
          'gsutil cat',
          stdout=api.json.output({}),
      ),
      api.step_data(
          'Mount caches.gsutil cat',
          stdout=api.json.output(metadata),
      )
  )
  yield api.test(
      'no_cache_file',
      api.step_data('builder exists', stdout=api.json.output({}), retcode=1),
      api.step_data(
          'Mount caches.gsutil cat',
          stdout=api.json.output(metadata),
      )
  )
