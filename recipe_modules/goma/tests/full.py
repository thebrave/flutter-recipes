# Copyright 2016 The Chromium Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

from PB.recipe_modules.flutter.goma.properties import InputProperties

DEPS = [
    "flutter/goma",
    "recipe_engine/buildbucket",
    "recipe_engine/json",
    "recipe_engine/platform",
    "recipe_engine/properties",
    "recipe_engine/step",
]


def RunSteps(api):
  # Use goma_dir outside of the context.
  api.goma.goma_dir
  with api.goma():
    # build something using goma.
    api.step("echo goma jobs", ["echo", str(api.goma.jobs)])

  api.goma.set_path(api.goma.goma_dir)


def GenTests(api):

  def goma_properties(**kwargs):
    return api.properties(**{"$flutter/goma": InputProperties(**kwargs)})

  yield api.test("mac") + api.platform.name("mac")

  yield api.test("win") + api.platform.name("win")

  yield (
      api.test("linux_goma_dir") + api.platform.name("linux") +
      goma_properties(goma_dir="/path/to/goma")
  )

  yield (
      api.test("linux_jobs") + api.platform.name("linux") +
      goma_properties(jobs=80)
  )

  yield (
      api.test("linux_non_default_server") + api.platform.name("linux") +
      goma_properties(server="goma.fuchsia.dev")
  )

  yield (
      api.test("linux_arbitrary_toolchain") + api.platform.name("linux") +
      goma_properties(enable_arbitrary_toolchains=True)
  )

  yield (
      api.test("linux_start_goma_failed", status="INFRA_FAILURE") +
      api.platform.name("linux") +
      api.step_data("setup goma.start goma", retcode=1)
  )

  yield (
      api.test("linux_stop_goma_failed", status="INFRA_FAILURE") +
      api.platform.name("linux") +
      api.step_data("teardown goma.stop goma", retcode=1)
  )

  yield (
      api.test("linux_invalid_goma_jsonstatus") + api.platform.name("linux") +
      api
      .step_data("teardown goma.goma jsonstatus", api.json.output(data=None))
  )

  yield (
      api.test("valid_buildname_and_build_id") + api.platform.name("linux") +
      api.buildbucket.try_build(project="test", builder="test")
  )
