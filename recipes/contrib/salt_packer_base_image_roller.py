# Copyright 2021 The Fuchsia Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.
"""
Recipe to roll base/source_images for Packer.
"""

from recipe_engine.recipe_api import Property

DEPS = [
    "fuchsia/auto_roller",
    "fuchsia/buildbucket_util",
    "fuchsia/gcloud",
    "fuchsia/git",
    "fuchsia/git_checkout",
    "recipe_engine/context",
    "recipe_engine/file",
    "recipe_engine/json",
    "recipe_engine/properties",
    "recipe_engine/raw_io",
    "recipe_engine/step",
]

PROPERTIES = {
    "repo": Property(kind=str, help="Salt repository to checkout."),
    "dry_run": Property(
        kind=bool, help="Exit early instead of committing a change.", default=True
    ),
}


def RunSteps(api, repo, dry_run):
    salt_path, revision = api.git_checkout(repo)

    # Get a short revision, image names must be < 64 characters
    with api.context(cwd=salt_path):
        revision = api.git(
            "git rev-parse",
            "rev-parse",
            "--short",
            revision,
            stdout=api.raw_io.output_text(),
        ).stdout.rstrip()

    json_path = salt_path.join("starlark", "packer-source-image.json")

    source_image = api.file.read_json(
        name="load packer source image json", source=json_path
    )

    commit_message = "Rolling Salt Packer Base Images:\n\n"
    for family, config in source_image.items():
        project = config["project"]
        old_image = config["image"]
        result = api.gcloud(
            "compute",
            "images",
            "describe-from-family",
            "{}".format(family),
            "--project={}".format(project),
            "--format=json",
            ok_ret="any",
            stdout=api.json.output(),
            step_name="get latest image for {}/{}".format(project, family),
        )
        if result.retcode != 0 or "name" not in result.stdout:
            raise api.step.StepFailure("Unable to find image for {}".format(family))
        new_image = result.stdout["name"]
        if old_image != new_image:
            commit_message += "{}: {} -> {}\n".format(family, old_image, new_image)
            source_image[family]["image"] = new_image

    api.file.write_json(
        name="update packer source image template",
        dest=json_path,
        data=source_image,
        indent=4,
    )
    api.step("regen starlark", [salt_path.join("gen.sh")])

    env = {
        # Disable update checks.
        "CHECKPOINT_DISABLE": "1",
        # Enable verbose logging.
        "PACKER_LOG": "1",
        # Disable color in logging.
        "PACKER_NO_COLOR": "1",
    }

    api.auto_roller.attempt_roll(
        api.auto_roller.Options(
            remote=repo,
            dry_run=dry_run,
        ),
        repo_dir=salt_path,
        commit_message=commit_message,
    )


def GenTests(api):
    repo = "https://dash-internal.googlesource.com/salt"
    yield (
        api.buildbucket_util.test("update", git_repo=repo)
        + api.properties(repo=repo, dry_run=False)
        + api.step_data(
            "load packer source image json",
            api.file.read_json(
                json_content={"bar": {"image": "old", "project": "foo"}}
            ),
        )
        + api.step_data(
            "get latest image for foo/bar",
            stdout=api.json.output({"name": "new"}),
            retcode=0,
        )
        + api.auto_roller.success()
    )

    yield (
        api.buildbucket_util.test("get_latest_failure", status="FAILURE", git_repo=repo)
        + api.properties(repo=repo, dry_run=False)
        + api.step_data(
            "load packer source image json",
            api.file.read_json(
                json_content={"bar": {"image": "old", "project": "foo"}}
            ),
        )
        + api.step_data(
            "get latest image for foo/bar", stdout=api.json.output({}), retcode=1
        )
    )
