# Copyright 2022 The Chromium Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

# Orchestrator recipe that runs subbuilds required to release engine.
#
# This recipe reads <engine_checkout>/.ci_yaml, and for every target
# marked with release_build: true, and spawens a subbuild.

import re
from contextlib import contextmanager

from PB.recipes.flutter.release.release import InputProperties
from PB.recipes.flutter.release.release import EnvProperties

from RECIPE_MODULES.flutter.repo_util.api import REPOS

from google.protobuf import struct_pb2

DEPS = [
    'flutter/yaml',
    'flutter/display_util',
    'flutter/repo_util',
    'flutter/shard_util_v2',
    'recipe_engine/buildbucket',
    'recipe_engine/json',
    'recipe_engine/path',
    'recipe_engine/platform',
    'recipe_engine/properties',
    'recipe_engine/raw_io',
    'recipe_engine/step',
]

PROPERTIES = InputProperties
ENV_PROPERTIES = EnvProperties

RELEASE_CHANNELS = ('refs/heads/beta', 'refs/heads/stable')


def ShouldRun(api, git_ref, target, release_branch):
  """Validates if a target should run based on platform, channel and repo."""
  # Enabled for current branch
  enabled_branches = target.get('enabled_branches', [])
  if enabled_branches:
    for r in enabled_branches:
      # Enabled branches is a list of regex
      if re.match(r, release_branch):
        break
    else:
      # Current branch didn't match any of the enabled branches.
      return False

  release_build = target.get('properties', {}).get('release_build', False)
  for_this_platform = target['name'].lower().startswith(api.platform.name)
  # Postsubmit for engine and flutter repositories.
  if (release_build and for_this_platform and
      (git_ref not in RELEASE_CHANNELS)):
    return True
  # Packaging for the flutter repository.
  if (target.get('scheduler') == 'release' and for_this_platform and
      (git_ref in RELEASE_CHANNELS) and
      git_ref.replace('refs/heads/', '') in target.get('enabled_branches', [])):
    return True
  return False


def RunSteps(api, properties, env_properties):
  repository = api.properties.get(
      'git_repo'
  ) or api.buildbucket.gitiles_commit.project
  repository_parts = repository.split('/')
  checkout_path = api.path['start_dir'].join(*repository_parts)
  git_ref = api.properties.get('git_ref') or api.buildbucket.gitiles_commit.ref
  git_url = api.properties.get('git_url') or REPOS[repository]
  api.repo_util.checkout(
      repository, checkout_path=checkout_path, url=git_url, ref=git_ref
  )

  ci_yaml_path = checkout_path.join('.ci.yaml')
  ci_yaml = api.yaml.read('read ci yaml', ci_yaml_path, api.json.output())

  # Get release branch.
  branches = api.repo_util.current_commit_branches(checkout_path)
  branches = [b for b in branches if b.startswith('flutter')]
  release_branch = branches[0] if branches else 'main'

  # Foreach target defined in .ci.yaml, if it contains
  # release_build: True, then spawn a subbuild.
  tasks = {}
  build_results = []
  with api.step.nest('launch builds') as presentation:
    for target in ci_yaml.json.output['targets']:
      if ShouldRun(api, git_ref, target, release_branch):
        target = api.shard_util_v2.pre_process_properties(target)
        tasks.update(
            api.shard_util_v2.schedule([
                target,
            ],
                                       presentation,
                                       branch=release_branch)
        )
  with api.step.nest('collect builds') as presentation:
    build_results = api.shard_util_v2.collect(tasks)

  api.display_util.display_subbuilds(
      step_name='display builds',
      subbuilds=build_results,
      raise_on_failure=True,
  )


def GenTests(api):
  try_subbuild1 = api.shard_util_v2.try_build_message(
      build_id=8945511751514863186,
      builder="builder-subbuild1",
      output_props={"test_orchestration_inputs_hash": "abc"},
      status="SUCCESS",
  )
  tasks_dict = {
      'targets': [{
          'name': 'linux one', 'recipe': 'engine/something', 'properties': {
              'release_build': True,
              '$flutter/osx_sdk': '{"sdk_version": "14a5294e"}'
          }, 'drone_dimensions': ['os=Linux']
      }, {
          'name': 'linux packaging one', 'recipe': 'release/something',
          'scheduler': 'release',
          'properties': {'$flutter/osx_sdk': '{"sdk_version": "14a5294e"}'},
          'enabled_branches': ['beta',
                               'main'], 'drone_dimensions': ['os=Linux']
      }]
  }
  for git_ref in ['main', 'beta']:
    yield api.test(
        'basic_linux_%s' % git_ref,
        api.platform.name('linux'),
        api.properties(environment='Staging', repository='engine'),
        api.buildbucket.try_build(
            project='prod',
            builder='try-builder',
            git_repo='https://flutter.googlesource.com/mirrors/engine',
            revision='a' * 40,
            build_number=123,
            git_ref='refs/heads/%s' % git_ref,
        ),
        api.shard_util_v2.child_build_steps(
            subbuilds=[try_subbuild1],
            launch_step="launch builds.schedule",
            collect_step="collect builds",
        ),
        api.step_data('read ci yaml.parse', api.json.output(tasks_dict)),
    )

  yield api.test(
      'filter_enabled_branches',
      api.properties(environment='Staging', repository='engine'),
      api.buildbucket.try_build(
          project='prod',
          builder='try-builder',
          git_repo='https://flutter.googlesource.com/mirrors/engine',
          revision='a' * 40,
          build_number=123,
          git_ref='refs/heads/%s' % git_ref,
      ),
      api.step_data('read ci yaml.parse', api.json.output(tasks_dict)),
      api.step_data(
          'Identify branches.git branch',
          stdout=api.raw_io
          .output_text('branch1\nbranch2\nflutter-3.2-candidate.5')
      ),
  )
