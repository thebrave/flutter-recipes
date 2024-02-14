# Copyright 2016 The Chromium Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Recipe to run framework tests with local builds."""

from contextlib import contextmanager

from PB.recipes.flutter.engine.engine import InputProperties
from PB.recipes.flutter.engine.engine import EnvProperties

from PB.go.chromium.org.luci.buildbucket.proto import build as build_pb2
from google.protobuf import struct_pb2

DEPS = [
    'flutter/build_util',
    'flutter/logs_util',
    'flutter/rbe',
    'flutter/repo_util',
    'flutter/test_utils',
    'recipe_engine/context',
    'recipe_engine/file',
    'recipe_engine/path',
    'recipe_engine/properties',
    'recipe_engine/step',
]

PROPERTIES = InputProperties
ENV_PROPERTIES = EnvProperties


def RunSteps(api, properties, env_properties):
  checkout_base = api.path['cache'].join('builder')
  checkout = api.path['cache'].join('builder', 'src')
  api.file.rmtree('Clobber build output', checkout.join('out'))
  cache_root = api.path['cache'].join('builder')
  api.file.ensure_directory('Ensure checkout cache', cache_root)
  env, env_prefixes = api.repo_util.engine_environment(cache_root)
  env['FLUTTER_PREBUILT_DART_SDK'] = 'True'
  env_prefixes = {}

  # Checkout Engine.
  api.repo_util.engine_checkout(cache_root, env, env_prefixes)
  api.logs_util.initialize_logs_collection(env)

  # Build engine host unopt.
  with api.step.nest('Build host_debug_unopt'):
    gn = ['--unoptimized', '--prebuilt-dart-sdk', '--rbe', '--no-goma']
    rbe_working_path = api.path.mkdtemp(prefix="rbe")
    api.rbe.prepare_rbe_gn(rbe_working_path, gn)
    api.build_util.run_gn(gn, checkout)
    try:
      api.build_util.build('host_debug_unopt', checkout, [], env, rbe_working_path)
    finally:
      api.logs_util.upload_logs('builder', type='engine')

  # Checkout framework and analyze.
  flutter_checkout_path = api.path['cache'].join('flutter')
  # Checkout flutter at master.
  api.repo_util.checkout(
      'flutter', checkout_path=flutter_checkout_path, ref='refs/heads/master'
  )
  build_dir = checkout.join('out', 'host_debug_unopt')
  with api.step.nest('Framework analyze'):
    with api.context(env=env, env_prefixes=env_prefixes,
                     cwd=flutter_checkout_path):
      api.file.rmtree(
          'Delete framework engine cache',
          flutter_checkout_path.join('bin', 'cache', 'pkg', 'sky_engine')
      )
      api.file.ensure_directory(
          'Ensure framework engine cache',
          flutter_checkout_path.join('bin', 'cache', 'pkg')
      )
      api.step(
          'Update packages', [
              'bin/flutter',
              'update-packages',
              '-v',
              '--local-engine=%s' % str(build_dir),
              '--local-engine-host=host_debug_unopt',
          ]
      )
      api.step(
          'Framework analyze', [
              'bin/flutter',
              'analyze',
              '--flutter-repo',
              '--local-engine=%s' % str(build_dir),
              '--local-engine-host=host_debug_unopt',
          ]
      )
  # Run framework packages test
  with api.step.nest('Framework test'):
    env['GOLDCTL'] = None
    with api.context(env=env, env_prefixes=env_prefixes,
                     cwd=flutter_checkout_path.join('packages', 'flutter')):
      api.step(
          api.test_utils.test_step_name('Framework test'), [
              str(flutter_checkout_path.join('bin', 'flutter')),
              'test',
              '--local-engine=%s' % str(build_dir),
              '--local-engine-host=host_debug_unopt',
              '-j',
              '8',
              '-x',
              'reduced-test-set'
          ]
      )


def GenTests(api):
  yield api.test('basic', api.properties(goma_jobs="100"))
  yield api.test('no_goma', api.properties(goma_jobs="100", no_goma=True))
