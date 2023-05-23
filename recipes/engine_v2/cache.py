# Copyright 2023 The Chromium Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

from PB.recipes.flutter.engine.engine import InputProperties
from PB.recipes.flutter.engine.engine import EnvProperties

DEPS = [
    'flutter/cache',
    'flutter/repo_util',
    'recipe_engine/path',
    'recipe_engine/properties',
    'recipe_engine/file',
    'recipe_engine/json',
]

PROPERTIES = InputProperties
ENV_PROPERTIES = EnvProperties


def RunSteps(api, properties, env_properties):
  # Sets the engine environment and checkouts the source code.
  checkout = api.path['cache'].join('builder', 'src')
  api.file.rmtree('Clobber build output', checkout.join('out'))
  builder_root = api.path['cache'].join('builder')
  api.file.ensure_directory('Ensure checkout cache', builder_root)
  env, env_prefixes = api.repo_util.engine_environment(builder_root)
  # Engine path is used inconsistently across the engine repo. We'll start
  # with [cache]/builder and will adjust it to start using it consistently.
  env['ENGINE_PATH'] = api.path['cache'].join('builder')
  cache_root = api.properties.get('cache_root', 'CACHE')
  cache_ttl = api.properties.get('cache_ttl', 3600 * 4)
  cache_name = api.properties.get('cache_name')
  if api.cache.requires_refresh(cache_name):
    api.repo_util.engine_checkout(builder_root, env, env_prefixes)
    paths = [
        api.path[cache_root].join(p)
        for p in api.properties.get('cache_paths', [])
    ]
    api.cache.write(cache_name, paths, cache_ttl)


def GenTests(api):
  yield api.test(
      'basic',
      api.properties(cache_root='cache', cache_paths=['builder', 'git']),
      api.step_data(
          'gsutil cat',
          stdout=api.json.output({}),
      )
  )
