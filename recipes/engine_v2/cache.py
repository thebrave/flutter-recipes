# Copyright 2023 The Chromium Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

DEPS = [
    'flutter/cache', 'flutter/repo_util', 'recipe_engine/path',
    'recipe_engine/properties', 'recipe_engine/file', 'recipe_engine/json',
    'recipe_engine/step'
]


def RunSteps(api):
  # Sets the engine environment and checkouts the source code.
  checkout = api.path.cache_dir / 'builder/src'
  api.file.rmtree('Clobber build output', checkout / 'out')
  builder_root = api.path.cache_dir / 'builder'
  api.file.ensure_directory('Ensure checkout cache', builder_root)
  env, env_prefixes = api.repo_util.engine_environment(builder_root)
  # Engine path is used inconsistently across the engine repo. We'll start
  # with [cache]/builder and will adjust it to start using it consistently.
  env['ENGINE_PATH'] = api.path.cache_dir / 'builder'
  cache_ttl = api.properties.get('cache_ttl', 3600 * 4)
  cache_name = api.properties.get('cache_name')

  if api.cache.requires_refresh(cache_name):
    api.repo_util.engine_checkout(builder_root, env, env_prefixes)
    paths = [
        api.path.cache_dir / p for p in api.properties.get('cache_paths', [])
    ]

    api.path.mock_add_directory(api.path.cache_dir / 'builder/fake')
    ignore_paths = [
        api.path.cache_dir / p
        for p in api.properties.get('ignore_cache_paths', [])
    ]

    for p in ignore_paths:
      if api.path.exists(p):
        api.file.rmtree(f'Removing path {p} from archive', p)

    api.cache.write(cache_name, paths, cache_ttl)


def GenTests(api):
  yield api.test(
      'basic',
      api.properties(cache_root='cache', cache_paths=['builder', 'git'], ignore_cache_paths=['builder/fake']),
      api.step_data(
          'gsutil cat',
          stdout=api.json.output({}),
      )
  )
