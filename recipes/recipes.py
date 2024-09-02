# Copyright 2020 The Chromium Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Recipe for testing recipes."""

import collections

import attr

from PB.recipe_modules.flutter.recipe_testing import options as options_pb2
from recipe_engine.recipe_api import Property

DEPS = [
    'flutter/recipe_testing',
    'fuchsia/gerrit',
    'fuchsia/git',
    'fuchsia/git_checkout',
    'recipe_engine/buildbucket',
    'recipe_engine/context',
    'recipe_engine/defer',
    'recipe_engine/json',
    'recipe_engine/path',
    'recipe_engine/properties',
    'recipe_engine/step',
]
PROPERTIES = {
    'remote':
        Property(
            kind=str,
            help='Remote repository',
            default='https://flutter.googlesource.com/recipes',
        ),
    # Default of True until recipe testing actually works on Flutter.
    'unittest_only':
        Property(kind=bool, help='Finish after unit tests', default=True),
}
# If this build is being triggered from a change to this recipe, we need
# to explicitly pass a CL. The most recent passing run of
# flutter.try/recipes could have any number of different subbuilds kicked
# off. In that case alter the recipes build to run on a specific CL that
# modifies the fuchsia_ctl recipe alone, because that recipe is used by
# relatively few CQ builders.
#
# If the self test CL triggers multiple builds then it may be possible that
# led recipes will call itself reaching the max recursion limit. In the
# flutter recipes the fuchsia_ctl recipe is the only one without too many
# dependencies.
SELFTEST_CL = ('https://flutter-review.googlesource.com/c/recipes/+/19645')
COMMIT_QUEUE_CFG = """
    submit_options: <
      max_burst: 4
      burst_delay: <
        seconds: 480
      >
    >
    config_groups: <
      gerrit: <
        url: "https://flutter-review.googlesource.com"
        projects: <
          name: "project"
          ref_regexp: "refs/heads/.+"
        >
      >
      verifiers: <
        gerrit_cq_ability: <
          committer_list: "project-flutter-committers"
          dry_run_access_list: "project-flutter-tryjob-access"
        >
        tryjob: <
          builders: <
            name: "flutter/try/flutter-baz"
          >
        >
      >
    >
    config_groups: <
      gerrit: <
        url: "https://flutter-review.googlesource.com"
        projects: <
          name: "flutter/flutter"
          ref_regexp: "refs/heads/.+"
        >
      >
      verifiers: <
        gerrit_cq_ability: <
          committer_list: "project-flutter-committers"
          dry_run_access_list: "project-flutter-tryjob-access"
        >
        tryjob: <
          builders: <
            name: "flutter/try/flutter-bar"
          >
          builders: <
            name: "flutter/try/flutter-foo"
          >
        >
      >
    >
"""


def RunSteps(api, remote, unittest_only):
  checkout_path = api.path.start_dir / 'recipes'
  api.git_checkout(remote, path=checkout_path)
  with api.context(cwd=checkout_path):
    api.git('log', 'log', '--oneline', '-n', '10')
  api.recipe_testing.projects = ('flutter',)

  deferred = []
  deferred.append(api.defer(api.recipe_testing.run_lint, checkout_path))
  deferred.append(api.defer(api.recipe_testing.run_unit_tests, checkout_path))
  api.defer.collect(deferred)

  if not unittest_only:
    flutter = options_pb2.Project(name='flutter', include_unrestricted=True)
    opts = options_pb2.Options(projects=[flutter])
    api.recipe_testing.run_tests(checkout_path, SELFTEST_CL, opts)


def GenTests(api):
  yield (
      api.test('ci') + api.properties(unittest_only=False) +
      api.recipe_testing.commit_queue_config_data('flutter', COMMIT_QUEUE_CFG) +
      api.recipe_testing.affected_recipes_data(['none']) + api.recipe_testing
      .build_data('flutter/try/flutter-foo', 'flutter', skip=True) +
      api.recipe_testing
      .build_data('flutter/try/flutter-bar', 'flutter', skip=True) +
      api.recipe_testing
      .build_data('flutter/try/flutter-baz', 'project', skip=True) +
      api.buildbucket.try_build(
          git_repo='https://flutter.googlesource.com/recipes'
      )
  )
  yield (
      api.test('cq_try') + api.properties(unittest_only=False) +
      api.recipe_testing.commit_queue_config_data('flutter', COMMIT_QUEUE_CFG) +
      api.recipe_testing.affected_recipes_data(['none']) + api.recipe_testing
      .build_data('flutter/try/flutter-foo', 'flutter', skip=True) +
      api.recipe_testing
      .build_data('flutter/try/flutter-bar', 'flutter', skip=True) +
      api.recipe_testing
      .build_data('flutter/try/flutter-baz', 'project', skip=True) +
      api.buildbucket.try_build(
          git_repo='https://flutter.googlesource.com/recipes'
      )
  )
