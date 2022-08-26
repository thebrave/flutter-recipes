# Copyright 2021 The Fuchsia Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.
"""
Recipe to build GCE images with Packer.
"""

from recipe_engine.recipe_api import Property

import re

DEPS = [
    "fuchsia/buildbucket_util",
    "fuchsia/git",
    "fuchsia/git_checkout",
    "recipe_engine/context",
    "recipe_engine/file",
    "recipe_engine/futures",
    "recipe_engine/path",
    "recipe_engine/properties",
    "recipe_engine/raw_io",
    "recipe_engine/step",
]

PROPERTIES = {
    "repo": Property(kind=str, help="Salt repository to checkout."),
    "dry_run": Property(
        kind=bool, help="Exit early instead of creating a disk image.", default=True
    ),
}
TEMPLATE_SUFFIX = ".packer.generated.json"


def RunSteps(api, repo, dry_run):
    salt_path, revision = api.git_checkout(repo, rebase_merges=True)

    # Get a short revision, image names must be < 64 characters
    with api.context(cwd=salt_path):
        revision = api.git(
            "git rev-parse",
            "rev-parse",
            "--short",
            revision,
            stdout=api.raw_io.output_text(),
        ).stdout.rstrip()

    packer_dir = salt_path.join("packer")
    template_paths = api.file.glob_paths(
        "find packer templates", packer_dir, "*" + TEMPLATE_SUFFIX
    )

    env = {
        # Disable update checks.
        "CHECKPOINT_DISABLE": "1",
        # Enable verbose logging.
        "PACKER_LOG": "1",
        # Disable color in logging.
        "PACKER_NO_COLOR": "1",
    }

    with api.context(env=env, cwd=salt_path):
        builds = []
        for template_path in template_paths:
            api.step(
                "packer validate",
                [
                    "packer",
                    "validate",
                    "-var",
                    "revision={}".format(revision),
                    template_path,
                ],
            )
            builds.append(
                api.futures.spawn(
                    _do_packer_builder,
                    api,
                    revision,
                    dry_run,
                    template_path,
                )
            )
        api.futures.wait(builds)
        if any(not build.result() for build in builds):
            raise api.step.StepFailure("BUILDS FAILED")


def _do_packer_builder(api, revision, dry_run, template_path):
    build = api.path.basename(template_path).replace(TEMPLATE_SUFFIX, "")
    with api.step.nest(build):
        result = api.step(
            "packer build",
            [
                "packer",
                "build",
                "-var",
                "revision={}".format(revision),
                "-var",
                "dry_run={}".format(str(dry_run).lower()),
                "-var",
                "use_internal_ip=true",
                "-only={}".format(build),
                template_path,
            ],
            stdout=api.raw_io.output_text(),
            ok_ret="any",
            # By default recipe_engine assigns a `cost` of 500 mCPU per step,
            # this limits our parallelism to 2*NUM_CORES but these steps are
            # simply waiting 99% of the time we can run far more in parallel.
            cost=None,
        )
        output = result.stdout
        result.presentation.logs["output"] = output.splitlines()

        if result.retcode != 0:
            if dry_run:
                for line in output.splitlines():
                    if "DRYRUN SUCCEEDED" in line:
                        result.presentation.step_text = "DRYRUN SUCCEEDED"
                        return True
                result.presentation.step_text = "DRYRUN FAILED"
                result.presentation.status = api.step.FAILURE
            result.presentation.status = api.step.FAILURE
        else:
            return True
        if result.presentation.status == api.step.FAILURE:
            failures_regex = re.compile(
                "(\s*ID:\s(.*?\n).*?Result:\sFalse\n.*?Changes:.*?)\n\s*{}:\s-{{10}}".format(
                    build
                ),
                re.DOTALL | re.MULTILINE,
            )
            for f in re.findall(failures_regex, output):
                result.presentation.logs[f[1]] = f[0].splitlines()
            return False


def GenTests(api):
    state_failures = """
     fail: ----------
     fail:           ID: /etc/systemd/system/gce-provider-start-agent.service
     fail:     Function: file.managed
     fail:       Result: False
     fail:      Comment: The following requisites were not found:
     fail:                                  require:
     fail:                                      user: swarming_use
     fail:      Started: 01:13:41.861499
     fail:     Duration: 0.028 ms
     fail:      Changes:
     fail: ----------
     fail:           ID: gce-provider-start-agent
     fail:     Function: service.enabled
     fail:       Result: False
     fail:      Comment: One or more requisite failed: luci.gce_provider./etc/systemd/system/gce-provider-start-agent.service
     fail:      Started: 01:13:41.862762
     fail:     Duration: 0.017 ms
     fail:      Changes:
     fail: ----------
     fail:           ID: curl
     fail:     Function: pkg.installed
     fail:       Result: True
     fail:      Comment: All specified packages are already installed
     fail:      Started: 01:13:41.868646
     fail:     Duration: 688.753 ms
     fail:      Changes:
     fail: ----------
     """

    repo = "https://dash-internal.googlesource.com/salt"
    yield (
        api.buildbucket_util.test("ci_failure", status="failure", git_repo=repo)
        + api.properties(repo=repo, dry_run=False)
        + api.step_data(
            "find packer templates",
            api.file.glob_paths(
                [
                    "pass.packer.generated.json",
                    "fail.packer.generated.json",
                ]
            ),
        )
        + api.step_data("pass.packer build", retcode=0)
        + api.step_data(
            "fail.packer build",
            api.raw_io.stream_output_text(state_failures),
            retcode=1,
        )
    )

    yield (
        api.buildbucket_util.test("ci_success", git_repo=repo)
        + api.properties(repo=repo, dry_run=False)
        + api.step_data(
            "find packer templates",
            api.file.glob_paths(
                [
                    "pass.packer.generated.json",
                ]
            ),
        )
        + api.step_data("pass.packer build", retcode=0)
    )

    yield (
        api.buildbucket_util.test("try_failure", status="failure", git_repo=repo)
        + api.properties(repo=repo, dry_run=True)
        + api.step_data(
            "find packer templates",
            api.file.glob_paths(
                [
                    "pass.packer.generated.json",
                    "fail.packer.generated.json",
                ]
            ),
        )
        + api.step_data("pass.packer build", retcode=0)
        + api.step_data(
            "fail.packer build",
            api.raw_io.stream_output_text(state_failures),
            retcode=1,
        )
    )

    yield (
        api.buildbucket_util.test("try_success", tryjob=True, git_repo=repo)
        + api.properties(repo=repo, dry_run=True)
        + api.step_data(
            "find packer templates",
            api.file.glob_paths(
                [
                    "pass.packer.generated.json",
                ]
            ),
        )
        + api.step_data(
            "pass.packer build",
            api.raw_io.stream_output_text("DRYRUN SUCCEEDED"),
            retcode=1,
        )
    )
