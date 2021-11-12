# Copyright 2016 The Chromium Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Recipe to run framework tests with local builds."""

from contextlib import contextmanager

from PB.recipes.flutter.engine import InputProperties
from PB.recipes.flutter.engine import EnvProperties

from PB.go.chromium.org.luci.buildbucket.proto import build as build_pb2
from google.protobuf import struct_pb2

PYTHON_VERSION_COMPATIBILITY = 'PY2+3'

DEPS = [
    'flutter/build_util',
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
  env = {
    'FLUTTER_PREBUILT_DART_SDK': 'True',
  }
  env_prefixes = {}

  # Checkout Engine.
  api.repo_util.engine_checkout(cache_root, env, env_prefixes)

  # Build engine host unopt.
  with api.step.nest('Build host_debug_unopt'):
    api.build_util.run_gn(['--unoptimized', '--full-dart-sdk', '--prebuilt-dart-sdk'], checkout)
    api.build_util.build('host_debug_unopt', checkout, [])

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
              'bin/flutter', 'update-packages',
              '--local-engine=%s' % str(build_dir)
          ]
      )
      api.step(
          'Framework analyze', [
              'bin/flutter', 'analyze', '--flutter-repo',
              '--local-engine=%s' % str(build_dir)
          ]
      )
  # Run framework packages test
  with api.step.nest('Framework test'):
    with api.context(env=env, env_prefixes=env_prefixes,
                     cwd=flutter_checkout_path.join('packages', 'flutter')):
      api.step(
          api.test_utils.test_step_name('Framework test'), [
              str(flutter_checkout_path.join('bin', 'flutter')), 'test',
              '--null-assertions', '--sound-null-safety',
              '--local-engine=%s' % str(build_dir)
          ]
      )


def GenTests(api):
  yield api.test('basic', api.properties(goma_jobs="100"))
