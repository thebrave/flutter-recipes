# Copyright 2020 The Fuchsia Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""API for recipe_engine testing."""

import datetime

from recipe_engine import post_process
from PB.recipe_modules.flutter.recipe_testing.tests.full import InputProperties

DEPS = [
    "fuchsia/buildbucket_util",
    "fuchsia/commit_queue",
    "flutter/recipe_testing",
    "fuchsia/swarming_retry",
    "recipe_engine/json",
    "recipe_engine/path",
    "recipe_engine/properties",
]

ONE_DAY = int(datetime.timedelta(days=1).total_seconds())
MAX_BUILD_AGE_SECONDS = int(datetime.timedelta(days=28).total_seconds())

PROPERTIES = InputProperties


def RunSteps(api, props):  # pylint: disable=invalid-name
  recipes_path = api.path["start_dir"].join("recipe_path")

  api.recipe_testing.run_lint(recipes_path, allowlist=r"allowed_module")
  api.recipe_testing.run_unit_tests(recipes_path)

  selftest_cl = "https://flutter-review.googlesource.com/c/recipes/+/123456"
  selftest_builder = "flutter/try/foo.bar-debug"
  api.recipe_testing.run_tests(
      recipes_path,
      selftest_cl,
      props.recipe_testing_options,
      selftest_builder=selftest_builder,
  )


def GenTests(api):  # pylint: disable=invalid-name

  test = api.recipe_testing

  project = "flutter"

  yield (
      api.buildbucket_util.test("recursive_ls") + api.recipe_testing.options() +
      api.commit_queue.test_data(project, "empty") + test.affected_recipes_data(
          affected_recipes=[],
          recipe_files=["flutter/flutter.py", "abc.resources/bar.py", "abc.py"],
      )
  )

  yield (
      api.buildbucket_util.test("recipes_cfg") + api.recipe_testing.options() +
      api.commit_queue.test_data(project, "empty") + test.affected_recipes_data(
          affected_recipes=[],
          recipe_files=["a.py", "b.py", "c.py", "d.py", "e.py"],
          changed_files=["infra/config/recipes.cfg"],
      )
  )

  yield (
      api.buildbucket_util.test("recipe_proto") + api.recipe_testing.options() +
      api.commit_queue.test_data(project) + test.affected_recipes_data(
          affected_recipes=[],
          changed_files=["recipe_proto/infra/flutter.proto"],
      )
  )

  yield (
      api.buildbucket_util.test("no_build_old_build_ignored_build") +
      api.recipe_testing.options() + api.commit_queue.test_data(project) +
      test.affected_recipes_data(["flutter"]) + test.build_data(
          "fuchsia/try/cobalt-x64-linux",
          "cobalt",
          age_seconds=MAX_BUILD_AGE_SECONDS - ONE_DAY,
          skip=True,
      ) + test.build_data(
          "fuchsia/try/core.x64-debug",
          "fuchsia",
          age_seconds=MAX_BUILD_AGE_SECONDS + ONE_DAY,
      ) + test.no_build("fuchsia/try/core.arm64-debug")
  )

  yield (
      api.buildbucket_util.test("excluded") + api.recipe_testing.options([
          api.recipe_testing.project(excluded_buckets=("try",))
      ]) + api.properties(ignored_buckets=["try"]) +
      api.commit_queue.test_data(project) +
      test.affected_recipes_data(["flutter"]) + api.post_process(
          post_process.MustRun,
          "excluding 3 builders from bucket flutter/try",
      )
  )

  yield (
      api.buildbucket_util.test("two_pass_one_skip") +
      api.recipe_testing.options() + api.commit_queue.test_data(project) +
      test.affected_recipes_data(["fuchsia"]) +
      test.build_data("fuchsia/try/cobalt-x64-linux", "cobalt", skip=True) +
      test.build_data(
          "fuchsia/try/core.x64-debug", "fuchsia", cl_cached=True, fake_id=100
      ) +
      test.build_data("fuchsia/try/core.arm64-debug", "fuchsia", fake_id=200) +
      api.swarming_retry.collect_data([
          test.task_result(100, "fuchsia/try/core.x64-debug"),
          test.task_result(200, "fuchsia/try/core.arm64-debug"),
      ])
  )

  yield (
      api.buildbucket_util.test("fuchsia_recipe_unaffected") +
      api.recipe_testing.options() + api.commit_queue.test_data(project) +
      test.affected_recipes_data(["qemu"]) +
      test.build_data("fuchsia/try/cobalt-x64-linux", "cobalt", skip=True) +
      test.build_data("fuchsia/try/core.x64-debug", "fuchsia", skip=True) +
      test.build_data("fuchsia/try/core.arm64-debug", "fuchsia", skip=True)
  )

  yield (
      api.buildbucket_util.test("recipes") + api.recipe_testing.options() +
      api.commit_queue.test_data(project, "recipes-only") +
      test.affected_recipes_data(["recipes"]) +
      test.build_data("fuchsia/try/recipes", "recipes") +
      api.swarming_retry.collect_data([
          test.task_result(100, "fuchsia/try/recipes")
      ])
  )

  yield (
      api.buildbucket_util.test("with_buildbucket") +
      api.commit_queue.test_data(project) +
      test.affected_recipes_data(["fuchsia"]) + test.build_data(
          "fuchsia/try/cobalt-x64-linux",
          "cobalt",
          skip=True,
          using_led=False,
          exe_cipd_version="refs/heads/main"
      ) + test.build_data(
          "fuchsia/try/core.x64-debug",
          "fuchsia",
          cl_cached=True,
          fake_id=100,
          using_led=False,
          exe_cipd_version="refs/heads/main"
      ) + test.build_data(
          "fuchsia/try/core.arm64-debug",
          "fuchsia",
          fake_id=200,
          using_led=False,
          exe_cipd_version="refs/heads/main"
      ) + test.existing_green_tryjobs(["fuchsia/try/core.arm64-release"])
      # This line only affects coverage. It's sufficiently tested in other
      # modules that use this module.
      + api.recipe_testing.options(
          use_buildbucket=True,
          projects=(api.recipe_testing.project(),),
      ) + api.step_data("gerrit get cl info 12345", api.json.output({})) +
      api.properties(
          buildset='patch/gerrit/flutter-review.googlesource.com/12345/1'
      )
  )

  yield (
      api.buildbucket_util.test("recipes_with_buildbucket") +
      api.commit_queue.test_data(project, "recipes-only") +
      test.affected_recipes_data(["recipes"]) +
      test.build_data("fuchsia/try/recipes", "recipes", using_led=False) +
      api.recipe_testing.options(use_buildbucket=True)
  )

  yield (
      api.buildbucket_util.test("no_latest_cl") + api.recipe_testing.options() +
      api.commit_queue.test_data(project) +
      test.affected_recipes_data(["fuchsia"]) +
      test.build_data("fuchsia/try/core.x64-debug", "fuchsia", cl_cached=True) +
      test.build_data(
          "fuchsia/try/core.arm64-debug",
          "fuchsia",
          num_log_entries=0,
          fake_id=200,
      ) + api.swarming_retry.collect_data([
          test.task_result(100, "fuchsia/try/core.x64-debug"),
          test.task_result(200, "fuchsia/try/core.arm64-debug"),
      ])
  )

  yield (
      api.buildbucket_util.test("depth", status="INFRA_FAILURE") +
      api.properties(**{"$flutter/recipe_testing": {"recipe_depth": 2}})
  )
