# Copyright 2020 The Fuchsia Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

from recipe_engine.recipe_api import Property
from RECIPE_MODULES.flutter.shard_util_v2.api import SubbuildResult

DEPS = [
    "flutter/display_util",
    "fuchsia/status_check",
    "recipe_engine/buildbucket",
]

PROPERTIES = {
    "raise_on_failure": Property(kind=bool, default=True),
}

# Build ids used to inject mock build objects to the buildbucket API.
SUCCESS_BUILD_ID = 123456789012345678
INFRA_FAILURE_BUILD_ID = 987654321098765432
FAILURE_BUILD_ID = 112233445566778899
FAILURE_BUILD_ID_2 = 112233445566778890
SCHEDULED_BUILD_ID = 199887766554433221
CANCELED_BUILD_ID = 987654321098765433

def RunSteps(api, raise_on_failure):
  # Collect current build status using the buildbucket API. The build ids
  # list passed to the API is to limit the query to only the build ids that
  # we are interested on. This API return a Build oject only if the build
  # exists in buildbucket.
  builds = api.buildbucket.collect_builds(build_ids=[
      # Builds with the following ids are mocked in the GenTests section
      # with different properties and status depending on the test.
      SUCCESS_BUILD_ID,
      INFRA_FAILURE_BUILD_ID,
      FAILURE_BUILD_ID,
      SCHEDULED_BUILD_ID,
      CANCELED_BUILD_ID,
  ])
  final_builds = {}
  for key in builds:
    build = builds[key]
    final_builds[build.id] = SubbuildResult(
        builder=build.builder.builder,
        build_id=build.id,
        build_name=build.builder.builder,
        build_proto= build)
  api.display_util.display_subbuilds(
      step_name="display builds",
      subbuilds=final_builds,
      raise_on_failure=raise_on_failure,
  )


def GenTests(api):
  def build(summary_markdown=None, **kwargs):
      b = api.buildbucket.ci_build_message(**kwargs)
      if summary_markdown:
          b.summary_markdown = summary_markdown
      return b

  # Mock builds injected in the different tests.
  success_build = build(
     build_id=SUCCESS_BUILD_ID,
     status="SUCCESS",
  )
  infra_failure_build = build(
     build_id=INFRA_FAILURE_BUILD_ID,
     status="INFRA_FAILURE",
     summary_markdown="something failed related to infra",
  )
  failure_build = build(
      build_id=FAILURE_BUILD_ID,
      status="FAILURE",
      summary_markdown="something failed not related to infra",
  )
  # Do not include summary_markdown to ensure full coverage.
  failure_build_2 = build(
      build_id=FAILURE_BUILD_ID_2,
      status="FAILURE",
  )
  scheduled_build = build(
      build_id=SCHEDULED_BUILD_ID,
      status="SCHEDULED",
  )
  canceled_build = build(
      build_id=CANCELED_BUILD_ID,
      status="CANCELED",
      summary_markdown="something failed related to infra",
  )

  yield (
      api.status_check.test(
          "mixed_with_infra_failures", status="infra_failure") +
      # Exercise all status colors.
      # Purple failures prioritized over red failures.
      api.buildbucket.simulated_collect_output([
          success_build,
          infra_failure_build,
          failure_build,
          scheduled_build,
      ]))

  yield (
      api.status_check.test(
          "canceled_builds", status="infra_failure") +
      # Exercise all status colors.
      # Purple failures prioritized over red failures.
      api.buildbucket.simulated_collect_output([
          success_build,
          canceled_build,
          scheduled_build,
      ]))

  yield (
      api.status_check.test("mixed_without_infra_failures", status="failure") +
      # With just red failures, raise red.
      api.buildbucket.simulated_collect_output([
          success_build,
          failure_build,
          failure_build_2,
          scheduled_build,
      ]))

  yield (
      api.status_check.test("all_passed") +
      # With just red failures, raise red.
      api.buildbucket.simulated_collect_output([
          success_build,
      ]))
