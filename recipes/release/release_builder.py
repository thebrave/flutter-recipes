# Copyright 2022 The Chromium Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

# ⚠️ WARNING. This is a *RELEASE* recipe, and it is always used from HEAD.
#
# Most recipes are branched, so that a change, for example, to engine_v2, only
# impacts the cooresponding `master` or `main` branch of the serviced
# respository (until that branch is eventually promoted to beta or stable).
#
# A release recipes is always used from HEAD, meaning any breaking changes are
# made immediately, even for older release candidates. Changes must be made in
# a backwards compatible way until older releases are archived or cherrypicks
# are required to the older release candidates.
#
# Example outcome: https://github.com/flutter/flutter/issues/168673

# Orchestrator recipe that runs sub-builds required to build engine artifacts
# suitable to be used for a published release (i.e. a release candidate build
# that will eventually be tagged and released as "beta" or "stable").
#
# For the engine, each target that is marked "release_build: "true" is scheduled:
#
# ##############################################################################
# # CONTENTS of //engine/src/flutter/.ci.yaml
# ##############################################################################
# targets:
#   # NOT SCHEDULED.
#   - name: Linux linux_host_engine_test
#     recipe: engine_v2/engine_v2
#   # SCHEDULED.
#   - name: Linux linux_host_desktop_engine
#     recipe: engine_v2/engine_v2
#     properties:
#       release_build: "true"
# ##############################################################################
#
# For the framework, each target that is marked "scheduler: release" or "schedule_during_release_override: true"
# ##############################################################################
# # CONTENTS of //.ci.yaml
# ##############################################################################
# targets:
#   # SCHEDULED.
#   - name: Linux flutter_packaging
#     recipe: packaging/packagine
#   # SCHEDULED.
#   - name: Linux docs_publish
#     recipe: flutter/docs
#     schedule_during_release_override: true
# ##############################################################################
#
# Note that "enabled_branches" still applies.
#
# Recipe is referenced here:
# https://dart-internal.googlesource.com/dart-internal/+/99cf8f57df5164a99eba7155351c74fbf7d2599a/flutter-internal/flutter.star#33
#
# Builder is executed via polling for changes to a branch matching "flutter-\\d+\\.\\d+-candidate\\.\\d+"
# when it is mirrored, via CopyBara, to https://flutter.googlesource.com/mirrors/flutter (automatic, but
# can take 5-15 minutes):
# https://dart-internal.googlesource.com/dart-internal/+/99cf8f57df5164a99eba7155351c74fbf7d2599a/flutter-internal/flutter.star#23

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


def IsSpecialCaseTargetForReleaseBuild(api, target, git_ref):
  # Whether this represents the "beta" or "stable" channel.
  is_release_channel = git_ref in RELEASE_CHANNELS
  is_release_candidate = not is_release_channel

  if is_release_candidate:
    # An engine build that is marked:
    # - Linux engine_foo:
    #   properties:
    #     release_build: "true"
    # or any build that is marked:
    # - Linux framework_foo:
    #   schedule_during_release_override: true
    #
    # Should be built during the Linux flutter_release_build orchestrator.
    if target.get('properties', {}).get('release_build', '') == 'true':
      return True
    if target.get('schedule_during_release_override'):
      return True
    return False

  assert (is_release_channel)
  # A framework build that is marked:
  # - Linux framework_foo
  #   scheduler: release
  #
  # Should be built during the Linux flutter_release_build orchestrator.
  if target.get('scheduler') != 'release':
    return False

  # Ensure that this target is enabled for this release channel.
  # TODO(matanlurey): Once "scheduler: release" opt-out is removed and replaced
  # with "enabled_branches: ["flutter-\d+\.\d+-candidate\.\d+"]", then we remove
  # this second enabled_branches test and just rely on the initial one.
  #
  # See https://github.com/flutter/flutter/issues/168745.
  git_ref_branch = git_ref.replace('refs/heads/', '')
  if not git_ref_branch in target.get('enabled_branches', []):
    return False

  # Skip targets that can't run on the current platform.
  for_this_platform = target['name'].lower().startswith(api.platform.name)
  if not for_this_platform:
    return False

  return True


def ShouldRunInReleaseBuild(
    api, git_ref, target, release_branch, retry_override_list
):
  """Validates if a target should run based on platform, channel and repo."""

  # If retry_override_list list of targets to retry has been provided,
  # skip the target if not specified on list.
  config_name = target.get('properties', {}).get('config_name', False)
  if retry_override_list and config_name and config_name not in retry_override_list:
    return False

  # Enabled for current branch
  #
  # TODO(matanlurey): Consider the top-level enabled_branches as the default
  # https://github.com/flutter/flutter/issues/168875
  enabled_branches = target.get('enabled_branches', [])

  # TODO(matanlurey): Add "flutter-\d+\.\d+-candidate\.\d+" to enabled_branches
  # and remove "scheduler != release". As far as I can tell, this was a hack put
  # in to work around https://github.com/flutter/flutter/issues/128459 and is
  # not necessary otherwise.
  #
  # See https://github.com/flutter/flutter/issues/168745.
  if enabled_branches and target.get('scheduler') != 'release':
    for r in enabled_branches:
      # Enabled branches is a list of regex
      if re.match(r, release_branch):
        break
    else:
      # Current branch didn't match any of the enabled branches.
      return False

  return IsSpecialCaseTargetForReleaseBuild(api, target, git_ref)


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


def ScheduleBuildsForRepo(
    api,
    checkout_path,
    git_ref,
    retry_override_list,
    release_branch,
):
  ci_yaml_path = checkout_path / '.ci.yaml'
  ci_yaml = api.yaml.read('read ci yaml', ci_yaml_path, api.json.output())
  tasks = {}
  build_results = []
  with api.step.nest('launch builds') as presentation:
    for target in ci_yaml.json.output['targets']:
      if not ShouldRunInReleaseBuild(
          api,
          git_ref,
          target,
          release_branch,
          retry_override_list,
      ):
        continue
      target = api.shard_util.pre_process_properties(target)
      properties = target.setdefault('properties', {})
      properties['is_fusion'] = 'true'
      tasks.update(
          api.shard_util.schedule(
              [target],
              presentation,
              branch=release_branch,
          )
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

  # Get release branch.
  branches = api.repo_util.current_commit_branches(checkout_path)
  branches = [b for b in branches if b.startswith('flutter')]
  release_branch = branches[0] if branches else 'main'

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

  with api.step.nest('engine'):
    collect_and_display_builds(
        ScheduleBuildsForRepo(
            api,
            checkout_path / 'engine' / 'src' / 'flutter',
            git_ref,
            retry_override_list,
            release_branch,
        )
    )

  with api.step.nest('framework'):
    collect_and_display_builds(
        ScheduleBuildsForRepo(
            api,
            checkout_path,
            git_ref,
            retry_override_list,
            release_branch,
        )
    )


def GenTests(api):
  try_subbuild1 = api.shard_util.try_build_message(
      build_id=8945511751514863186,
      builder="builder-subbuild1",
      output_props={"test_orchestration_inputs_hash": "abc"},
      status="SUCCESS",
  )
  for git_ref in ['main', 'beta']:
    yield api.test(
        'base_linux_%s_monorepo' % git_ref,
        api.path.dirs_exist(
            api.path.start_dir / 'mirrors' / 'flutter' / 'engine',
        ),
        api.platform.name('linux'),
        api.properties(
            environment='Staging',
            repository='flutter',
        ),
        api.buildbucket.try_build(
            project='prod',
            builder='try-builder',
            git_repo='https://flutter.googlesource.com/mirrors/flutter',
            revision='a' * 40,
            build_number=123,
            git_ref='refs/heads/%s' % git_ref,
        ),
        api.shard_util.child_build_steps(
            subbuilds=[try_subbuild1],
            launch_step="engine.launch builds.schedule",
            collect_step="engine.collect builds",
        ),
        api.step_data(
            'engine.read ci yaml.parse',
            api.json.output({
                'targets': [
                    {
                        'name': 'linux one',
                        'recipe': 'engine/something',
                        'properties': {
                            'release_build': 'true',
                            '$flutter/osx_sdk': '{"sdk_version": "14a5294e"}',
                        },
                        'drone_dimensions': ['os=Linux'],
                    },
                    {
                        'name': 'linux packaging one',
                        'recipe': 'release/something',
                        'scheduler': 'release',
                        'properties': {
                            '$flutter/osx_sdk': '{"sdk_version": "14a5294e"}',
                        },
                        'enabled_branches': [
                            'beta',
                            'main',
                        ],
                        'drone_dimensions': ['os=Linux'],
                    },
                ]
            })
        ),
        api.step_data(
            'framework.read ci yaml.parse', api.json.output({"targets": []})
        ),
    )

  RELEASE_CANDIDATE_GIT_REF = 'flutter-3.2-candidate.5'
  multiplatform_tasks = {
      'targets': [
          {
              'name': 'Linux flutter_test',
              'recipe': 'release/something',
              'properties': {},
              'enabled_branches': [RELEASE_CANDIDATE_GIT_REF],
              'drone_dimensions': ['os=Linux']
          },
          {
              'name': 'Mac flutter_test',
              'recipe': 'release/something',
              'properties': {
                  '$flutter/osx_sdk': '{"sdk_version": "14a5294e"}'
              },
              'enabled_branches': [RELEASE_CANDIDATE_GIT_REF],
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
              'enabled_branches': [RELEASE_CANDIDATE_GIT_REF],
              'drone_dimensions': ['os=Linux']
          },
          {
              'name': 'Mac flutter_test',
              'recipe': 'release/something',
              'properties': {
                  '$flutter/osx_sdk': '{"sdk_version": "14a5294e"}',
                  'release_build': 'true',
              },
              'enabled_branches': [RELEASE_CANDIDATE_GIT_REF],
              'drone_dimensions': ['os=Mac']
          },
      ]
  }
  tasks_dict_scheduler = {
      'targets': [{
          'name': 'linux packaging one',
          'recipe': 'release/something',
          'properties': {
              '$flutter/osx_sdk': '{"sdk_version": "14a5294e"}'
          },
          'enabled_branches': ['flutter-3.2-candidate.5'],
          'drone_dimensions': ['os=Linux']
      }, {
          'name': 'linux packaging two',
          'recipe': 'release/something',
          'properties': {
              '$flutter/osx_sdk': '{"sdk_version": "14a5294e"}'
          },
          'enabled_branches': ['beta', 'main'],
          'drone_dimensions': ['os=Linux']
      }]
  }
  yield api.test(
      'filter_enabled_branches',
      api.properties(
          environment='Staging',
          repository='flutter',
      ),
      api.platform.name('linux'),
      api.path.dirs_exist(
          api.path.start_dir / 'mirrors' / 'flutter' / 'engine',
      ),
      api.buildbucket.try_build(
          project='prod',
          builder='try-builder',
          git_repo='https://flutter.googlesource.com/mirrors/flutter',
          revision='a' * 40,
          build_number=123,
          git_ref='refs/heads/%s' % RELEASE_CANDIDATE_GIT_REF,
      ),
      api.step_data(
          'engine.read ci yaml.parse',
          api.json.output(release_multiplatform_tasks)
      ),
      api.step_data(
          'framework.read ci yaml.parse', api.json.output(tasks_dict_scheduler)
      ),
      api.step_data(
          'Identify branches.git branch',
          stdout=api.raw_io.output_text(
              'remotes/origin/branch1\nremotes/origin/branch2\nremotes/origin/flutter-3.2-candidate.5'
          )
      ),
  )
  yield api.test(
      'retry_override_skips_config_name_not_matched',
      api.properties(
          environment='Staging',
          repository='flutter',
          retry_override_list='foo',
      ),
      api.platform.name('linux'),
      api.path.dirs_exist(
          api.path.start_dir / 'mirrors' / 'flutter' / 'engine',
      ),
      api.buildbucket.try_build(
          project='prod',
          builder='try-builder',
          git_repo='https://flutter.googlesource.com/mirrors/flutter',
          revision='a' * 40,
          build_number=123,
          git_ref='refs/heads/%s' % RELEASE_CANDIDATE_GIT_REF
      ),
      api.step_data(
          'engine.read ci yaml.parse',
          api.json.output({
              'targets': [
                  {
                      'name': 'Linux foo',
                      'recipe': 'engine/something',
                      'enabled_branches': ['flutter-\d+\.\d+-candidate\.\d+'],
                      'drone_dimensions': ['os=Linux'],
                      'properties': {
                          'config_name': 'foo',
                          'release_build': 'true',
                      },
                  },
                  {
                      'name': 'Linux bar',
                      'recipe': 'engine/something',
                      'enabled_branches': ['flutter-\d+\.\d+-candidate\.\d+'],
                      'drone_dimensions': ['os=Linux'],
                      'properties': {
                          'config_name': 'bar',
                          'release_build': 'true',
                      },
                  },
              ]
          })
      ),
      api.step_data(
          'framework.read ci yaml.parse', api.json.output({'targets': []})
      ),
      api.step_data(
          'Identify branches.git branch',
          stdout=api.raw_io.output_text(
              'remotes/origin/branch1\nremotes/origin/branch2\nremotes/origin/flutter-3.2-candidate.5'
          )
      ),
      api.shard_util.child_build_steps(
          subbuilds=[try_subbuild1],
          launch_step="engine.launch builds.schedule",
          collect_step="engine.collect builds",
      ),
  )
  yield api.test(
      'retry_override_still_runs_non_config_name_target',
      api.properties(
          environment='Staging',
          repository='flutter',
          retry_override_list='foo',
      ),
      api.platform.name('linux'),
      api.path.dirs_exist(
          api.path.start_dir / 'mirrors' / 'flutter' / 'engine',
      ),
      api.buildbucket.try_build(
          project='prod',
          builder='try-builder',
          git_repo='https://flutter.googlesource.com/mirrors/flutter',
          revision='a' * 40,
          build_number=123,
          git_ref='refs/heads/%s' % RELEASE_CANDIDATE_GIT_REF
      ),
      api.step_data(
          'engine.read ci yaml.parse', api.json.output({
              'targets': [],
          })
      ),
      api.step_data(
          'framework.read ci yaml.parse',
          api.json.output({
              'targets': [{
                  'name': 'Linux only_enabled_for_release_candidates',
                  'recipe': 'release/something',
                  'enabled_branches': ['flutter-\d+\.\d+-candidate\.\d+'],
                  'drone_dimensions': ['os=Linux'],
                  'schedule_during_release_override': True,
              },]
          })
      ),
      api.step_data(
          'Identify branches.git branch',
          stdout=api.raw_io.output_text(
              'remotes/origin/branch1\nremotes/origin/branch2\nremotes/origin/flutter-3.2-candidate.5'
          )
      ),
      api.shard_util.child_build_steps(
          subbuilds=[try_subbuild1],
          launch_step="framework.launch builds.schedule",
          collect_step="framework.collect builds",
      ),
  )
  yield api.test(
      'filter_git_ref_not_stable_or_beta_on_release_channel',
      api.properties(
          environment='Staging',
          repository='flutter',
      ),
      api.platform.name('linux'),
      api.path.dirs_exist(
          api.path.start_dir / 'mirrors' / 'flutter' / 'engine',
      ),
      api.buildbucket.try_build(
          project='prod',
          builder='try-builder',
          git_repo='https://flutter.googlesource.com/mirrors/flutter',
          revision='a' * 40,
          build_number=123,
          git_ref='refs/heads/%s' % 'beta',
      ),
      api.step_data(
          'engine.read ci yaml.parse',
          api.json.output(release_multiplatform_tasks)
      ),
      api.step_data(
          'framework.read ci yaml.parse',
          api.json.output({
              'targets': [
                  {
                      'name': 'Linux only_enabled_for_release_candidates',
                      'recipe': 'release/something',
                      'enabled_branches': ['flutter-\d+\.\d+-candidate\.\d+'],
                      'drone_dimensions': ['os=Linux'],
                      'scheduler': 'release',
                  },
                  {
                      'name': 'Linux only_enabled_for_release_channels',
                      'recipe': 'release/something',
                      'enabled_branches': [
                          'beta',
                          'stable',
                      ],
                      'drone_dimensions': ['os=Linux'],
                      'scheduler': 'release',
                  },
              ]
          })
      ),
      api.step_data(
          'Identify branches.git branch',
          stdout=api.raw_io.output_text(
              'remotes/origin/branch1\nremotes/origin/branch2\nremotes/origin/flutter-3.2-candidate.5'
          )
      ),
  )
  yield api.test(
      'filter_targets_not_on_current_platform',
      api.properties(
          environment='Staging',
          repository='flutter',
      ),
      api.platform.name('linux'),
      api.path.dirs_exist(
          api.path.start_dir / 'mirrors' / 'flutter' / 'engine',
      ),
      api.buildbucket.try_build(
          project='prod',
          builder='try-builder',
          git_repo='https://flutter.googlesource.com/mirrors/flutter',
          revision='a' * 40,
          build_number=123,
          git_ref='refs/heads/beta',
      ),
      api.step_data(
          'engine.read ci yaml.parse',
          api.json.output(release_multiplatform_tasks)
      ),
      api.step_data(
          'framework.read ci yaml.parse',
          api.json.output({
              'targets': [
                  {
                      'name': 'Linux is_current_platform',
                      'recipe': 'release/something',
                      'enabled_branches': ['beta'],
                      'drone_dimensions': ['os=Linux'],
                      'scheduler': 'release',
                  },
                  {
                      'name': 'Mac is_not_current_platform',
                      'recipe': 'release/something',
                      'enabled_branches': ['beta'],
                      'drone_dimensions': ['os=Mac'],
                      'scheduler': 'release',
                  },
              ]
          })
      ),
      api.step_data(
          'Identify branches.git branch',
          stdout=api.raw_io.output_text(
              'remotes/origin/branch1\nremotes/origin/branch2\nremotes/origin/flutter-3.2-candidate.5'
          )
      ),
  )
  yield api.test(
      'linux_schedule_during_release_override_with_empty_enabled_branch',
      api.properties(
          environment='Staging',
          repository='flutter',
      ),
      api.platform.name('linux'),
      api.path.dirs_exist(
          api.path.start_dir / 'mirrors' / 'flutter' / 'engine',
      ),
      api.buildbucket.try_build(
          project='prod',
          builder='try-builder',
          git_repo='https://flutter.googlesource.com/mirrors/flutter',
          revision='a' * 40,
          build_number=123,
          git_ref='refs/heads/%s' % RELEASE_CANDIDATE_GIT_REF,
      ),
      api.step_data(
          'engine.read ci yaml.parse',
          api.json.output(release_multiplatform_tasks)
      ),
      api.step_data(
          'framework.read ci yaml.parse',
          api.json.output({
              'targets': [{
                  'name': 'Linux schedule_during_release_override',
                  'recipe': 'release/something',
                  'drone_dimensions': ['os=Linux'],
                  'schedule_during_release_override': True,
              },]
          })
      ),
      api.step_data(
          'Identify branches.git branch',
          stdout=api.raw_io.output_text(
              'remotes/origin/branch1\nremotes/origin/branch2\nremotes/origin/flutter-3.2-candidate.5'
          )
      ),
      api.shard_util.child_build_steps(
          subbuilds=[try_subbuild1],
          launch_step="framework.launch builds.schedule",
          collect_step="framework.collect builds",
      ),
  )
  yield api.test(
      'linux_schedule_during_release_override_with_matching_enabled_branch',
      api.properties(
          environment='Staging',
          repository='flutter',
      ),
      api.platform.name('linux'),
      api.path.dirs_exist(
          api.path.start_dir / 'mirrors' / 'flutter' / 'engine',
      ),
      api.buildbucket.try_build(
          project='prod',
          builder='try-builder',
          git_repo='https://flutter.googlesource.com/mirrors/flutter',
          revision='a' * 40,
          build_number=123,
          git_ref='refs/heads/%s' % RELEASE_CANDIDATE_GIT_REF,
      ),
      api.step_data(
          'engine.read ci yaml.parse',
          api.json.output(release_multiplatform_tasks)
      ),
      api.step_data(
          'framework.read ci yaml.parse',
          api.json.output({
              'targets': [{
                  'name': 'Linux schedule_during_release_override',
                  'recipe': 'release/something',
                  'drone_dimensions': ['os=Linux'],
                  'schedule_during_release_override': True,
              },]
          })
      ),
      api.step_data(
          'Identify branches.git branch',
          stdout=api.raw_io.output_text(
              'remotes/origin/branch1\nremotes/origin/branch2\nremotes/origin/flutter-3.2-candidate.5'
          )
      ),
      api.shard_util.child_build_steps(
          subbuilds=[try_subbuild1],
          launch_step="framework.launch builds.schedule",
          collect_step="framework.collect builds",
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
          git_ref='refs/heads/%s' % RELEASE_CANDIDATE_GIT_REF,
      ),
      api.step_data(
          'framework.read ci yaml.parse',
          api.json.output(release_multiplatform_tasks)
      ),
      api.step_data(
          'engine.read ci yaml.parse', api.json.output(tasks_dict_scheduler)
      ),
      api.step_data(
          'Identify branches.git branch',
          stdout=api.raw_io.output_text(
              'remotes/origin/branch1\nremotes/origin/branch2\nremotes/origin/flutter-3.2-candidate.5'
          )
      ),
  )
