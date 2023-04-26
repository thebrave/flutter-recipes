# Copyright 2020 The Chromium Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Recipe for framework tests running with web-engine repository tests."""

import contextlib
import copy

from recipe_engine import recipe_api

from PB.recipes.flutter.engine.engine import InputProperties
from PB.recipes.flutter.engine.engine import EnvProperties

DEPS = [
    'depot_tools/depot_tools',
    'depot_tools/gclient',
    'flutter/build_util',
    'flutter/display_util',
    'flutter/flutter_deps',
    'flutter/os_utils',
    'flutter/repo_util',
    'flutter/shard_util_v2',
    'fuchsia/cas_util',
    'flutter/goma',
    'recipe_engine/buildbucket',
    'recipe_engine/context',
    'recipe_engine/file',
    'recipe_engine/path',
    'recipe_engine/platform',
    'recipe_engine/properties',
    'recipe_engine/step',
    'recipe_engine/swarming',
]

PROPERTIES = InputProperties
ENV_PROPERTIES = EnvProperties
DRONE_TIMEOUT_SECS = 3600 * 3  # 3 hours.


def Archive(api, target):
  checkout = GetCheckoutPath(api)
  build_dir = checkout.join('out', target)
  cas_dir = api.path.mkdtemp('cas-directory')
  cas_out = cas_dir.join('out', target)
  api.file.copytree('Copy wasm_release', build_dir, cas_out)
  source_dir = checkout.join('flutter')
  cas_source = cas_dir.join('flutter')
  api.file.copytree('Copy source', source_dir, cas_source)
  return api.cas_util.upload(cas_dir, step_name='Archive Flutter Web SDK CAS')


def GetCheckoutPath(api):
  return api.path['cache'].join('builder', 'src')


def RunSteps(api, properties, env_properties):
  """Steps to checkout flutter engine and execute web tests."""
  # Collect memory/cpu/process before task execution.
  api.os_utils.collect_os_info()
  cache_root = api.path['cache'].join('builder')
  checkout = GetCheckoutPath(api)

  if properties.clobber:
    api.file.rmtree('Clobber cache', cache_root)
  api.file.rmtree('Clobber build output', checkout.join('out'))

  api.file.ensure_directory('Ensure checkout cache', cache_root)
  env, env_prefixes = api.repo_util.engine_environment(cache_root)
  env['ENGINE_PATH'] = cache_root
  api.repo_util.engine_checkout(cache_root, env, env_prefixes)
  with api.context(cwd=cache_root, env=env,
                   env_prefixes=env_prefixes), api.depot_tools.on_path():

    api.gclient.runhooks()

    target_name = 'wasm_release'
    gn_flags = ['--web', '--runtime-mode=release']

    api.build_util.run_gn(gn_flags, checkout)
    api.build_util.build(target_name, checkout, [])

    # Archive build directory into CAS.
    cas_hash = Archive(api, target_name)
    ref = api.properties.get('git_branch', '')
    ref = ref if ref.startswith('flutter-') else 'master'
    ref = 'refs/heads/%s' % ref
    url = 'https://github.com/flutter/flutter'

    # Checkout flutter to run the web integration tests with the local engine.
    flutter_checkout_path = api.path['cache'].join('flutter')
    api.repo_util.checkout(
        'flutter', checkout_path=flutter_checkout_path, url=url, ref=ref
    )

    # Create new enviromenent variables for Framework.
    # Note that the `dart binary` location is not the same for Framework and the
    # engine.
    f_env, f_env_prefix = api.repo_util.flutter_environment(flutter_checkout_path)
    f_env['FLUTTER_CLONE_REPO_PATH'] = flutter_checkout_path

    deps = api.properties.get('dependencies', [])
    api.flutter_deps.required_deps(f_env, f_env_prefix, deps)
    with api.context(cwd=cache_root, env=f_env, env_prefixes=f_env_prefix):
      configure_script = checkout.join(
          'flutter',
          'tools',
          'configure_framework_commit.sh',
      )
      api.step(
          'configure framework commit',
          [configure_script],
          infra_step=True,
      )
      commit_no_file = flutter_checkout_path.join('flutter_ref.txt',)
      ref = api.file.read_text(
          'read commit no', commit_no_file, 'b6efc758213fdfffee1234465'
      )
      assert (len(ref) > 0)
    # The SHA of the youngest commit older than the engine in the framework
    # side is kept in `ref`.
    targets = generate_targets(api, cas_hash, ref.strip(), url, deps)
    with api.step.nest('launch builds') as presentation:
       tasks = api.shard_util_v2.schedule(targets, presentation)
    with api.step.nest('collect builds') as presentation:
       build_results = api.shard_util_v2.collect(tasks)
    api.display_util.display_subbuilds(
      step_name='display builds',
      subbuilds=build_results,
      raise_on_failure=True,
    )


def generate_targets(api, cas_hash, ref, url, deps):
  """Schedules one subbuild per subshard."""
  targets = []

  shard = api.properties.get('shard')
  for subshard in api.properties.get('subshards'):
    task_name = '%s-%s' % (shard, subshard)
    drone_props = {
        'subshard': subshard,
        'shard': shard,
        'dependencies': [api.shard_util_v2.unfreeze_dict(dep) for dep in deps],
        'task_name': task_name,
        'local_web_sdk_cas_hash': cas_hash,
    }
    drone_props['git_url'] = url
    drone_props['git_ref'] = ref
    targets.append(
        {
            'name': task_name,
            'properties': drone_props,
            'recipe': 'flutter/flutter_drone',
            'drone_dimensions': api.properties.get('drone_dimensions', []),
        }
    )
  return targets


def GenTests(api):
  yield api.test(
      'linux-pre-submit',
      api.repo_util.flutter_environment_data(api.path['cache'].join('flutter')),
      api.properties(
          dependencies=[{'dependency': 'chrome_and_driver', 'version': 'version:96.2'}],
          shard='web_tests',
          subshards=['0', '1_last'],
          goma_jobs='200',
          git_url='https://mygitrepo',
          git_ref='refs/pull/1/head',
          git_branch='main',
          clobber=True,
          task_name='abc'
      ),
      api.platform('linux', 64),
      api.buildbucket.try_build(
          project='flutter',
          bucket='try',
          git_repo='https://flutter.googlesource.com/mirrors/engine',
          git_ref='refs/heads/main'
      ),
  )
