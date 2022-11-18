# Copyright 2020 The Chromium Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Recipe for engine shards.

   web_engine.py will call these shards. It will build the Flutter Web Engine,
   and will archive it to the CAS server.

   These shards will be called with required dependencies, felt commands, and
   with a CAS digest of the Flutter Web Engine.
"""

import contextlib
import copy

from recipe_engine import recipe_api

from PB.recipes.flutter.engine.engine import InputProperties
from PB.recipes.flutter.engine.engine import EnvProperties

DEPS = [
    'depot_tools/depot_tools',
    'flutter/flutter_deps',
    'flutter/os_utils',
    'flutter/repo_util',
    'recipe_engine/cas',
    'recipe_engine/context',
    'recipe_engine/file',
    'recipe_engine/json',
    'recipe_engine/path',
    'recipe_engine/platform',
    'recipe_engine/properties',
    'recipe_engine/step',
]

GIT_REPO = 'https://flutter.googlesource.com/mirrors/engine'

PROPERTIES = InputProperties
ENV_PROPERTIES = EnvProperties


def GetCheckoutPath(api):
  """Path to checkout the flutter/engine repo."""
  return api.path['cache'].join('builder', 'src')


def RunSteps(api, properties, env_properties):
  """Steps to checkout flutter engine and execute web test shard.

  The test shard to run will be determined by `command_args` send as part of
  properties.
  """
  cache_root = api.path['cache'].join('builder')
  checkout = GetCheckoutPath(api)
  platform = api.platform.name.capitalize()
  if properties.clobber:
    api.file.rmtree('Clobber cache', cache_root)
  api.file.rmtree('Clobber build output: %s' % platform, checkout.join('out'))

  api.file.ensure_directory('Ensure checkout cache', cache_root)

  # Copy build properties.
  build = api.properties.get('build')
  env, env_prefixes = api.repo_util.engine_environment(cache_root)
  # Checkout source code and build
  api.repo_util.engine_checkout(cache_root, env, env_prefixes)

  # Ensure required deps are installed
  api.flutter_deps.required_deps(
      env, env_prefixes, build.get('inherited_dependencies', [])
  )

  with api.context(cwd=cache_root, env=env,
                   env_prefixes=env_prefixes), api.depot_tools.on_path():

    # Download local CanvasKit build.
    wasm_cas_hash = build.get('wasm_release_cas_hash')
    out_dir = checkout.join('out')
    api.cas.download('Download CanvasKit build from CAS', wasm_cas_hash, out_dir)

    command_args = build.get('command_args', ['test'])
    command_name = build.get('command_name', 'test')

    felt_name = 'felt.bat' if api.platform.is_win else 'felt'
    felt_cmd = [
         checkout.join('flutter', 'lib', 'web_ui', 'dev', felt_name)
    ]
    felt_cmd.extend(command_args)

    with api.context(cwd=cache_root, env=env,
                     env_prefixes=env_prefixes), api.depot_tools.on_path():
      with recipe_api.defer_results():
        api.step('felt test: %s' % command_name, felt_cmd)
        # This is to clean up leaked processes.
        api.os_utils.kill_processes()
        # Collect memory/cpu/process after task execution.
        api.os_utils.collect_os_info()


def GenTests(api):
  build = {
      'command_args': ['test', '--browser=chrome', '--require-skia-gold'],
      'command_name': 'chrome-unit-linux',
      'git_ref': 'refs/heads/master',
      'inherited_dependencies': [
          {'dependency': 'chrome_and_driver'},
          {'dependency': 'firefox'},
          {'dependency': 'goldctl'},
          {'dependency': 'open_jdk'},
          {'dependency': 'gradle_cache'}
      ],
      'name': 'chrome-unit-linux',
      'wasm_release_cas_hash': '7a4348cb77de16aac05401c635950c2a75566e3f268fd60e7113b0c70cd4fbcb/87',
      'web_dependencies': ['chrome']
  }
  yield api.test(
      'basic',
      api.properties(build=build, clobber=True),
  )
