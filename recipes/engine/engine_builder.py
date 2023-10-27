# Copyright 2016 The Chromium Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

from contextlib import contextmanager
import contextlib

from PB.recipes.flutter.engine.engine_builder import InputProperties, EngineBuild

DEPS = [
    'depot_tools/depot_tools',
    'flutter/goma',
    'flutter/os_utils',
    'flutter/osx_sdk',
    'flutter/repo_util',
    'flutter/shard_util_v2',
    'recipe_engine/buildbucket',
    'recipe_engine/cas',
    'recipe_engine/context',
    'recipe_engine/defer',
    'recipe_engine/file',
    'recipe_engine/path',
    'recipe_engine/platform',
    'recipe_engine/properties',
    'recipe_engine/step',
]

GIT_REPO = \
    'https://flutter.googlesource.com/mirrors/engine'

PROPERTIES = InputProperties


def Build(api, config, disable_goma, *targets):
  checkout = api.path['cache'].join('builder', 'src')
  build_dir = checkout.join('out/%s' % config)
  ninja_path = checkout.join('flutter', 'third_party', 'ninja', 'ninja')

  if not disable_goma:
    ninja_args = [ninja_path, '-C', build_dir]
    ninja_args.extend(targets)
    with api.goma():
      name = 'build %s' % ' '.join([config] + list(targets))
      api.step(name, ninja_args)
  else:
    ninja_args = [ninja_path, '-C', build_dir]
    ninja_args.extend(targets)
    api.step('build %s' % ' '.join([config] + list(targets)), ninja_args)


def RunGN(api, disable_goma, *args):
  checkout = api.path['cache'].join('builder', 'src')
  gn_cmd = ['python3', checkout.join('flutter/tools/gn')]
  gn_cmd.extend(args)
  if disable_goma:
    api.step('gn %s' % ' '.join(args), gn_cmd)
  else:
    # Run gn within a context.
    env = {'GOMA_DIR': api.goma.goma_dir}
    with api.context(env=env):
      api.step('gn %s' % ' '.join(args), gn_cmd)


def CasOutputs(api, output_files, output_dirs):
  out_dir = api.path['cache'].join('builder', 'src')
  dirs = output_files + output_dirs
  dirs = [api.path.abspath(d) for d in dirs]
  return api.cas.archive('CAS build outputs', out_dir, *dirs)


def RunSteps(api, properties):
  # Collect memory/cpu/process after task execution.
  api.os_utils.collect_os_info()
  cache_root = api.path['cache'].join('builder')
  api.file.rmtree('Clobber build output', cache_root.join('src', 'out'))
  api.repo_util.engine_checkout(cache_root, {}, {})
  with api.context(cwd=cache_root):
    android_home = cache_root.join('src', 'third_party', 'android_tools', 'sdk')
    env = {'ANDROID_HOME': str(android_home)}

    output_files = []
    output_dirs = []
    with api.osx_sdk('ios'), api.depot_tools.on_path(), api.context(env=env):
      deferred = []
      for build in properties.builds:
        with api.step.nest('build %s (%s)' %
                           (build.dir, ','.join(build.targets))):
          deferred.append(
              api.defer(RunGN, api, build.disable_goma, *build.gn_args)
          )
          deferred.append(
              api.defer(
                  Build, api, build.dir, build.disable_goma, *build.targets
              )
          )
          for output_file in build.output_files:
            output_files.append(
                cache_root.join('src', 'out', build.dir, output_file)
            )
          for output_dir in build.output_dirs:
            output_dirs.append(
                cache_root.join('src', 'out', build.dir, output_dir)
            )
      # This is to clean up leaked processes.
      deferred.append(api.defer(api.os_utils.kill_processes))
      # Collect memory/cpu/process after task execution.
      deferred.append(api.defer(api.os_utils.collect_os_info))
      api.defer.collect(deferred)

    cas_hash = CasOutputs(api, output_files, output_dirs)
    output_props = api.step('Set output properties', None)
    output_props.presentation.properties['cas_output_hash'] = cas_hash


def GenTests(api):
  yield api.test(
      'Schedule two builds one with goma and one without',
      api.platform('linux', 64),
      api.buildbucket.ci_build(
          builder='Linux Drone',
          git_repo=GIT_REPO,
          project='flutter',
      ),
      api.properties(
          InputProperties(
              mastername='client.flutter',
              builds=[
                  EngineBuild(
                      disable_goma=True,
                      gn_args=['--unoptimized', '--android'],
                      dir='android_debug_unopt',
                      output_files=['libflutter.so'],
                      output_dirs=['some_dir'],
                  ),
                  EngineBuild(
                      disable_goma=False,
                      gn_args=['--unoptimized'],
                      dir='host_debug_unopt',
                      output_files=['shell_unittests']
                  )
              ]
          )
      )
  )
