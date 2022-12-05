# Copyright 2022 The Chromium Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

DEPS = [
    'flutter/monorepo',
    'recipe_engine/buildbucket',
    'recipe_engine/step',
]


def RunSteps(api):
  is_ci_build = api.monorepo.is_monorepo_ci_build
  is_try_build = api.monorepo.is_monorepo_try_build
  presentation = api.step.empty('test').presentation
  presentation.properties['is_ci_build'] = is_ci_build
  presentation.properties['is_try_build'] = is_try_build


def GenTests(api):
  yield api.test('monorepo_ci_build', api.monorepo.ci_build())

  yield api.test('monorepo_try_build', api.monorepo.try_build())

  yield api.test(
      'engine_build',
      api.buildbucket.ci_build(
          project='flutter',
          bucket='prod',
          builder='prod-builder',
          git_repo='https://flutter.googlesource.com/mirrors/engine',
          git_ref='refs/heads/main',
          revision='a' * 40,
          build_number=123,
      )
  )
