# Copyright 2020 The Fuchsia Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

from recipe_engine.recipe_api import Property
from recipe_engine.config import List
from PB.go.chromium.org.luci.buildbucket.proto import common as common_pb2
from PB.recipe_modules.recipe_engine.led.properties import (
    InputProperties as LedInputProperties,
)

DEPS = [
    "fuchsia/buildbucket_util",
    "flutter/subbuild",
    "recipe_engine/properties",
    "recipe_engine/step",
]

PROPERTIES = {
    "builder_names": Property(
        kind=List(str), help="The names of the builders to launch"
    ),
    "extra_properties": Property(
        kind=dict,
        help="The extra properties to launch the subbuilds with",
        default=None,
    ),
}


def RunSteps(api, builder_names, extra_properties):
    with api.step.nest("launch builds") as presentation:
        builds = api.subbuild.launch(
            builder_names, presentation, extra_properties=extra_properties
        )
    with api.step.nest("collect builds", status="last"):
        builds = api.subbuild.collect([build.build_id for build in builds.values()])
        for build in builds.values():
            if build.build_proto.status != common_pb2.SUCCESS:
                raise api.step.StepFailure(f"build {build.build_id} failed")
            assert api.subbuild.get_property(
                build.build_proto, "test_orchestration_inputs_hash"
            )


def GenTests(api):
    ci_subbuild1 = api.subbuild.ci_build_message(
        build_id=8945511751514863184,
        builder="builder-subbuild1",
        output_props={"test_orchestration_inputs_hash": "abc"},
        status="SUCCESS",
    )
    ci_subbuild2 = api.subbuild.ci_build_message(
        build_id=8945511751514863185,
        builder="builder-subbuild2",
        output_props={"test_orchestration_inputs_hash": "abc"},
        status="SUCCESS",
    )
    try_subbuild1 = api.subbuild.try_build_message(
        build_id=8945511751514863186,
        builder="builder-subbuild1",
        output_props={"test_orchestration_inputs_hash": "abc"},
        status="SUCCESS",
    )
    try_subbuild2 = api.subbuild.try_build_message(
        build_id=8945511751514863187,
        builder="builder-subbuild2",
        output_props={"test_orchestration_inputs_hash": "abc"},
        status="SUCCESS",
    )
    subbuild_missing_property = api.subbuild.try_build_message(
        build_id=8945511751514863187,
        builder="builder-subbuild2",
        output_props={},
        status="SUCCESS",
    )
    failed_subbuild = api.subbuild.try_build_message(
        build_id=8945511751514863187,
        builder="builder-subbuild2",
        status="FAILURE",
    )

    def properties(project=None, bucket=None, **kwargs):
        if project:
            assert bucket
        project = f"{project}/" if project else ""
        bucket = f"{bucket}/" if bucket else ""
        props = dict(
            builder_names=[
                f"{project}{bucket}builder-subbuild1",
                "builder-subbuild2",
            ],
            extra_properties={
                "parent_id": "parentid",
                # This should be passed through from the parent to the subbuild.
                "integration_base_revision": "abc123",
            },
        )
        props.update(**kwargs)
        return api.properties(**props)

    # Use different sets of options for different cases so we get coverage of
    # the logic to split the builder name without adding more tests.

    def ci_properties(**kwargs):
        return properties(project="fuchsia", bucket="ci", **kwargs)

    def try_properties(**kwargs):
        return properties(bucket="try", **kwargs)

    yield (
        api.buildbucket_util.test("launch_builds_ci")
        + ci_properties()
        + api.subbuild.child_build_steps(
            builds=[ci_subbuild1, ci_subbuild2],
            launch_step="launch builds",
            collect_step="collect builds",
        )
    )

    yield (
        api.buildbucket_util.test("missing_property", status="INFRA_FAILURE")
        + properties()
        + api.subbuild.child_build_steps(
            builds=[subbuild_missing_property],
            launch_step="launch builds",
            collect_step="collect builds",
        )
    )

    yield (
        api.buildbucket_util.test("launch_builds_with_led_ci")
        + ci_properties(
            **{
                "$recipe_engine/led": LedInputProperties(
                    led_run_id="led/user_example.com/abc123",
                ),
            }
        )
        + api.subbuild.child_led_steps(
            builds=[ci_subbuild1, ci_subbuild2],
            collect_step="collect builds",
        )
    )

    yield (
        api.buildbucket_util.test("launch_builds_with_led_cq", tryjob=True)
        + try_properties(
            **{
                "$recipe_engine/led": LedInputProperties(
                    led_run_id="led/user_example.com/abc123",
                ),
            }
        )
        + api.subbuild.child_led_steps(
            builds=[try_subbuild1, try_subbuild2],
            collect_step="collect builds",
        )
    )

    yield (
        api.buildbucket_util.test("failed_subbuild", tryjob=True, status="FAILURE")
        + properties()
        + api.subbuild.child_build_steps(
            builds=[failed_subbuild],
            launch_step="launch builds",
            collect_step="collect builds",
        )
    )
