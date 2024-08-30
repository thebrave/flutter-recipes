# Copyright 2024 The Chromium Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

from PB.recipe_modules.flutter.recipe_testing.options import Project

from recipe_engine import post_process

DEPS = [
    'flutter/recipe_testing',
    'recipe_engine/properties',
    'recipe_engine/step',
]

PROPERTIES = Project


def RunSteps(api, project: Project):
  builders = api.recipe_testing._all_tryjobs(
      project.name, project.include_unrestricted, project.include_restricted,
      project.cq_config_name
  )
  api.step('builders', builders)


def GenTests(api):
  yield (
      api.test(
          'mode_allowlist',
          api.recipe_testing.commit_queue_config_data(
              'flutter', data='mode_allowlist'
          ),
          api.properties(
              Project(
                  name='flutter',
                  include_restricted=True,
                  include_unrestricted=True,
              )
          ),
          api.post_process(post_process.StepCommandEquals, 'builders', []),
      )
  )

  yield (
      api.test(
          'include_restricted',
          api.recipe_testing.commit_queue_config_data('flutter'),
          api.properties(
              Project(
                  name='flutter',
                  include_restricted=True,
                  include_unrestricted=False,
              )
          ),
          api.post_process(
              post_process.StepCommandEquals, 'builders',
              ['fuchsia/try/secret-tryjob']
          ),
      )
  )

  yield (
      api.test(
          'include_unrestricted',
          api.recipe_testing.commit_queue_config_data('flutter'),
          api.properties(
              Project(
                  name='flutter',
                  include_restricted=False,
                  include_unrestricted=True,
              )
          ),
          api.post_process(
              post_process.StepCommandEquals, 'builders', [
                  'fuchsia/try/cobalt-x64-linux',
                  'fuchsia/try/core.arm64-debug',
                  'fuchsia/try/core.x64-debug',
              ]
          ),
      )
  )

  yield (
      api.test(
          'location_filters',
          api.recipe_testing.commit_queue_config_data(
              'flutter', data='location_filters'
          ),
          api.properties(
              Project(
                  name='flutter',
                  include_restricted=True,
                  include_unrestricted=True,
              )
          ),
          api.post_process(
              post_process.StepCommandEquals, 'builders', [
                  'fuchsia/foo/bar',
              ]
          ),
      )
  )
