# Copyright 2022 The Chromium Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

DEPS = [
    'flutter/monorepo',
    'recipe_engine/buildbucket',
    'recipe_engine/properties',
    'recipe_engine/step',
]


def RunSteps(api):
  is_ci_build = api.monorepo.is_monorepo_ci_build
  is_try_build = api.monorepo.is_monorepo_try_build
  if is_try_build:
    try_build_identifier = api.monorepo.try_build_identifier
  presentation = api.step.empty('test').presentation
  presentation.properties['is_ci_build'] = is_ci_build
  presentation.properties['is_try_build'] = is_try_build
  if is_try_build:
    presentation.properties['try_build_identifier'] = try_build_identifier


def GenTests(api):
  yield api.test('monorepo_ci_build', api.monorepo.ci_build())

  yield api.test('monorepo_try_build', api.monorepo.try_build())

  yield api.test(
      'monorepo_try_subbuild',
      api.monorepo.try_build(),
      api.properties(try_build_identifier='81123491'),
  )

  yield api.test(
      'monorepo_try_build_no_builder_id',
      api.monorepo.try_build(build_id=0),
      api.expect_exception('AssertionError'),
  )

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
