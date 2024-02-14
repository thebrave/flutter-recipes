# Copyright 2021 The Chromium Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

from PB.recipe_modules.flutter.rbe.properties import InputProperties

DEPS = [
    "flutter/rbe",
    "recipe_engine/buildbucket",
    "recipe_engine/file",
    "recipe_engine/path",
    "recipe_engine/properties",
    "recipe_engine/step",
]


def RunSteps(api):
  with api.rbe(reclient_path=api.path["cleanup"].join("rbe"),
               working_path=api.path["cleanup"].join("rbe")):
    # build something using rbe.
    api.step("build", ["echo", "Mission Complete!"])

  with api.rbe(config_path=api.path["cleanup"].join("configs"),
               working_path=api.path["cleanup"].join("rbe")):
    # build something using rbe.
    api.step("build", ["echo", "Misison Accomplished!"])
  api.rbe.wait_and_collect_logs(
      working_dir=api.path["cleanup"].join("rbe"), collect_rbe_logs_latency=-1
  )
  api.rbe.set_rbe_triggered(False)
  api.rbe.wait_and_collect_logs(
      working_dir=api.path["cleanup"].join("rbe"), collect_rbe_logs_latency=61
  )
  api.rbe.set_rbe_triggered(True)
  api.rbe.wait_and_collect_logs(
      working_dir=api.path["cleanup"].join("rbe"), collect_rbe_logs_latency=61
  )
  api.rbe.prepare_rbe_gn(api.path["cleanup"].join("rbe"), [])


def GenTests(api):

  def rbe_properties(**kwargs):
    kwargs.setdefault("instance", "projects/fuchsia-infra/instance/default")
    kwargs.setdefault(
        "platform",
        "container-image=docker://gcr.io/cloud-marketplace/google/debian11@sha256:69e2789c9f3d28c6a0f13b25062c240ee7772be1f5e6d41bb4680b63eae6b304",
    )
    props = api.properties(**{"$fuchsia/rbe": InputProperties(**kwargs)}
                          ) + api.buildbucket.try_build(
                              project="test", builder="test"
                          )
    return props

  yield (api.test("basic") + rbe_properties())

  yield (
      api.test("start_rbe_failed", status="INFRA_FAILURE") +
      api.step_data("setup remote execution.start reproxy", retcode=1)
  )

  yield (
      api.test("stop_rbe_failed", status="INFRA_FAILURE") +
      api.step_data("teardown remote execution.stop reproxy", retcode=1)
  )

  yield (api.test("read_log_proto_failure_does_not_block") + rbe_properties())
