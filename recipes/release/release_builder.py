# Copyright 2022 The Chromium Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

# Orchestrator recipe that runs subbuilds required to release engine.
#
# This recipe reads <engine_checkout>/.ci_yaml, and for every target
# marked with release_build: true, and spawens a subbuild.

import re
from enum import Enum

from RECIPE_MODULES.flutter.repo_util.api import REPOS

DEPS = [
    'flutter/display_util',
    'flutter/flutter_bcid',
    'flutter/os_utils',
    'flutter/repo_util',
    'flutter/shard_util',
    'flutter/yaml',
    'recipe_engine/buildbucket',
    'recipe_engine/file',
    'recipe_engine/json',
    'recipe_engine/path',
    'recipe_engine/platform',
    'recipe_engine/properties',
    'recipe_engine/raw_io',
    'recipe_engine/runtime',
    'recipe_engine/step',
]

RELEASE_CHANNELS = ('refs/heads/beta', 'refs/heads/stable')


# TODO(fujino): delete this once Flutter monorepo reaches stable channel
class RepoContext(Enum):
  """An enum covering the possible Flutter repository types this recipe will be invoked on."""
  SINGLE_REPO_FRAMEWORK = 0
  SINGLE_REPO_ENGINE = 1
  MONOREPO = 2


def ShouldRun(
    api, git_ref, target, release_branch, retry_override_list, repo_context
):
  """Validates if a target should run based on platform, channel and repo.

  If repo_context == RepoContext.MONOREPO, then the target platform does not
  need to match the current platform."""

  # If retry_override_list list of targets to retry has been provided,
  # skip the target if not specified on list.
  config_name = target.get('properties', {}).get('config_name', False)
  should_skip = retry_override_list and config_name not in retry_override_list
  if should_skip:
    # A list of targets to retry was provided
    # and this target was not on the list.
    return False

  # Enabled for current branch
  enabled_branches = target.get('enabled_branches', [])
  if enabled_branches and target.get('scheduler') != 'release':
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
  # TODO(fujino): once 3.29 reaches stable, ignore repo_context
  if (release_build and
      (repo_context == RepoContext.MONOREPO or for_this_platform) and
      (git_ref not in RELEASE_CHANNELS)):
    return True
  # Packaging for the flutter repository.
  if (target.get('scheduler') == 'release' and for_this_platform and
      (git_ref in RELEASE_CHANNELS) and
      git_ref.replace('refs/heads/', '') in target.get('enabled_branches', [])):
    return True
  return False


def GetRepoInfo(properties, gitiles):
  """Extracts current repository information from first properties, then fallsback to gitiles object.

  Args:
    properties(Properties): The build's properties. These are usually overrides provided in LED builds or tests.
    gitiles(GitilesCommit): For prod builds, the commit that was the source trigger. See https://chromium.googlesource.com/infra/luci/luci-go/+/main/buildbucket/proto/build.proto.

  Returns:
    A tuple of
    * The name of the repository, one of the string keys of the REPOS dict from the repo_util module
    * The URL of the repository, one of the string values of the REPOS dict
    * The git ref to check out
  """
  repository = properties.get('git_repo') or gitiles.project
  url = properties.get('git_url') or REPOS[repository]
  ref = properties.get('git_ref') or gitiles.ref
  return (repository, url, ref)


def GetRepoContext(api, repository, root):
  if repository in ('engine', 'mirrors/engine'):
    return RepoContext.SINGLE_REPO_ENGINE
  if repository in ('flutter', 'mirrors/flutter'):
    if api.path.exists(root / 'engine'):
      return RepoContext.MONOREPO
    return RepoContext.SINGLE_REPO_FRAMEWORK
  assert False, f'the repository {repository} is not supported by the release/release_builder.py recipe'


def ScheduleBuildsForRepo(
    api, checkout_path, git_ref, retry_override_list, context
):
  ci_yaml_path = checkout_path / '.ci.yaml'
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
      if ShouldRun(api, git_ref, target, release_branch, retry_override_list,
                   context):
        target = api.shard_util.pre_process_properties(target)
        if context == RepoContext.MONOREPO:
          properties = target.setdefault('properties', {})
          properties['is_fusion'] = 'true'
        tasks.update(
            api.shard_util.schedule([target],
                                    presentation,
                                    branch=release_branch)
        )
  return tasks


def RunSteps(api):
  api.os_utils.collect_os_info()
  repository, git_url, git_ref = GetRepoInfo(
      api.properties, api.buildbucket.gitiles_commit
  )
  checkout_path = api.path.start_dir / repository
  api.repo_util.checkout(
      repository, checkout_path=checkout_path, url=git_url, ref=git_ref
  )

  context = GetRepoContext(api, repository, checkout_path)

  # retry_override_list is optional and is a space separated string of
  # the config_name of targets to explitly retry
  retry_override_list = api.properties.get('retry_override_list', '').split()

  def collect_and_display_builds(builds):
    with api.step.nest('collect builds'):
      build_results = api.shard_util.collect(builds)
    api.display_util.display_subbuilds(
        step_name='display builds',
        subbuilds=build_results,
        raise_on_failure=True,
    )

  if context in (RepoContext.SINGLE_REPO_FRAMEWORK, RepoContext.SINGLE_REPO_ENGINE):
    collect_and_display_builds(
        ScheduleBuildsForRepo(
            api, checkout_path, git_ref, retry_override_list, context
        )
    )
  elif context == RepoContext.MONOREPO:
    collect_and_display_builds(
        ScheduleBuildsForRepo(
            api,
            checkout_path / 'engine' / 'src' / 'flutter',
            git_ref,
            retry_override_list,
            context,
        )
    )

    collect_and_display_builds(
        ScheduleBuildsForRepo(
            api,
            checkout_path,
            git_ref,
            retry_override_list,
            context,
        )
    )
  else:
    assert False, "You must update release/release_builder.py to handle a new RepoContext"  # pragma: nocover



def GenTests(api):
  try_subbuild1 = api.shard_util.try_build_message(
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
    # TODO(fujino): delete once 3.29 reaches stable
    for is_monorepo in [True, False]:
      props = [
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
          api.shard_util.child_build_steps(
              subbuilds=[try_subbuild1],
              launch_step="launch builds.schedule",
              collect_step="collect builds",
          ),
          api.step_data('read ci yaml.parse', api.json.output(tasks_dict)),
      ]

      if is_monorepo:
        yield api.test(
            'base_linux_%s_monorepo' % git_ref,
            api.path.dirs_exist(
                api.path.start_dir / 'mirrors' / 'flutter' / 'engine',
            ),
            *props,
        )
      else:
        yield api.test(
            'base_linux_%s' % git_ref,
            *props,
        )

  git_ref = 'flutter-3.2-candidate.5'
  multiplatform_tasks = {
      'targets': [
          {
              'name': 'Linux flutter_test',
              'recipe': 'release/something',
              'properties': {},
              'enabled_branches': [git_ref],
              'drone_dimensions': ['os=Linux']
          },
          {
              'name': 'Mac flutter_test',
              'recipe': 'release/something',
              'properties': {
                  '$flutter/osx_sdk': '{"sdk_version": "14a5294e"}'
              },
              'enabled_branches': [git_ref],
              'drone_dimensions': ['os=Mac']
          },
      ]
  }
  release_multiplatform_tasks = {
      'targets': [
          {
              'name': 'Linux flutter_test',
              'recipe': 'release/something',
              'properties': {
                  'release_build': 'true',
              },
              'enabled_branches': [git_ref],
              'drone_dimensions': ['os=Linux']
          },
          {
              'name': 'Mac flutter_test',
              'recipe': 'release/something',
              'properties': {
                  '$flutter/osx_sdk': '{"sdk_version": "14a5294e"}',
                  'release_build': 'true',
              },
              'enabled_branches': [git_ref],
              'drone_dimensions': ['os=Mac']
          },
      ]
  }
  tasks_dict_scheduler = {
      'targets': [
          {
              'name': 'linux packaging one',
              'recipe': 'release/something',
              #'scheduler': 'release',
              'properties': {
                  '$flutter/osx_sdk': '{"sdk_version": "14a5294e"}'
              },
              'enabled_branches': ['flutter-3.2-candidate.5'],
              'drone_dimensions': ['os=Linux']
          },
          {
              'name': 'linux packaging two',
              'recipe': 'release/something',
              #'scheduler': 'release',
              'properties': {
                  '$flutter/osx_sdk': '{"sdk_version": "14a5294e"}'
              },
              'enabled_branches': ['beta', 'main'],
              'drone_dimensions': ['os=Linux']
          }
      ]
  }
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
      api.step_data(
          'read ci yaml.parse', api.json.output(tasks_dict_scheduler)
      ),
      api.step_data(
          'Identify branches.git branch',
          stdout=api.raw_io
          .output_text('branch1\nbranch2\nflutter-3.2-candidate.5')
      ),
  )
  for retry_list in ['skip_target', 'skip_target linux_target']:
    yield api.test(
        'retry_override_%s' % retry_list,
        api.properties(
            environment='Staging',
            repository='engine',
            retry_override_list=retry_list
        ),
        api.buildbucket.try_build(
            project='prod',
            builder='try-builder',
            git_repo='https://flutter.googlesource.com/mirrors/engine',
            revision='a' * 40,
            build_number=123,
            git_ref='refs/heads/%s' % git_ref
        ),
        api.step_data(
            'read ci yaml.parse', api.json.output(tasks_dict_scheduler)
        ),
    )

  yield api.test(
      'dart_internal',
      api.properties(environment='Staging', repository='engine'),
      api.buildbucket.try_build(
          project='dart-internal',
          bucket='flutter',
          builder='prod-builder',
          git_repo='https://flutter.googlesource.com/mirrors/engine',
          revision='a' * 40,
          build_number=123,
          git_ref='refs/heads/%s' % git_ref,
      ),
      api.step_data(
          'read ci yaml.parse', api.json.output(tasks_dict_scheduler)
      ),
      api.step_data(
          'Identify branches.git branch',
          stdout=api.raw_io
          .output_text('branch1\nbranch2\nflutter-3.2-candidate.5')
      ),
  )
  yield api.test(
      'linux_framework_single_repo',
      api.properties(environment='Staging', repository='framework'),
      api.platform.name('linux'),
      api.buildbucket.try_build(
          project='dart-internal',
          bucket='flutter',
          builder='prod-builder',
          git_repo='https://flutter.googlesource.com/mirrors/flutter',
          revision='a' * 40,
          build_number=123,
          git_ref='refs/heads/%s' % git_ref,
      ),
      api.step_data(
          'read ci yaml.parse', api.json.output(multiplatform_tasks)
      ),
      api.step_data(
          'Identify branches.git branch',
          stdout=api.raw_io
          .output_text('branch1\nbranch2\nflutter-3.2-candidate.5')
      ),
  )
  yield api.test(
      'linux_engine_monorepo_candidate',
      api.properties(
          environment='Staging',
          repository='flutter',
      ),
      api.platform.name('linux'),
      api.path.dirs_exist(
          api.path.start_dir / 'mirrors' / 'flutter' / 'engine',
      ),
      api.buildbucket.try_build(
          project='dart-internal',
          bucket='flutter',
          builder='prod-builder',
          git_repo='https://flutter.googlesource.com/mirrors/flutter',
          revision='a' * 40,
          build_number=123,
          git_ref='refs/heads/%s' % git_ref,
      ),
      # Engine .ci.yaml
      api.step_data(
          'read ci yaml.parse', api.json.output(release_multiplatform_tasks)
      ),
      # Framework .ci.yaml
      api.step_data(
          'read ci yaml (2).parse', api.json.output(tasks_dict_scheduler)
      ),
      api.step_data(
          'Identify branches.git branch',
          stdout=api.raw_io.output_text(
              'remotes/origin/branch1\nremotes/origin/branch2\nremotes/origin/flutter-3.2-candidate.5'
          )
      ),
  )
  yield api.test(
      'throws_assertion_on_unsupported_repo',
      api.properties(
          environment='Staging',
          git_repo='openpay',
      ),
      api.buildbucket.try_build(
          project='dart-internal',
          bucket='flutter',
          builder='prod-builder',
          git_repo='https://flutter.googlesource.com/mirrors/openpay',
          revision='a' * 40,
          build_number=123,
          git_ref='refs/heads/%s' % git_ref,
      ),
      api.expect_exception('AssertionError'),
  )
