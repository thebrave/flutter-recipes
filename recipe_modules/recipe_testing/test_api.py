# Copyright 2022 The Chromium Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

import datetime

from google.protobuf import timestamp_pb2

from PB.go.chromium.org.luci.buildbucket.proto import (
    build as build_pb2,
    builder_common as builder_common_pb2,
    common as common_pb2,
)
from PB.go.chromium.org.luci.led.job import job as job_pb2
from PB.recipe_modules.flutter.recipe_testing import options as options_pb2
from recipe_engine import recipe_test_api

ONE_DAY = int(datetime.timedelta(days=1).total_seconds())
MAX_BUILD_AGE_SECONDS = int(datetime.timedelta(days=28).total_seconds())


class RecipeTestingTestApi(recipe_test_api.RecipeTestApi):
    def project(
        self,
        name="flutter",
        include_unrestricted=True,
        include_restricted=False,
        cq_config_name="commit-queue.cfg",
        excluded_buckets=(),
    ):
        return options_pb2.Project(
            name=name,
            include_unrestricted=include_unrestricted,
            include_restricted=include_restricted,
            cq_config_name=cq_config_name,
            excluded_buckets=excluded_buckets,
        )

    def options(self, projects=(), use_buildbucket=False, **kwargs):
        if not projects:
            projects = [self.project()]
        return self.m.properties(
            recipe_testing_options=options_pb2.Options(
                projects=list(projects), use_buildbucket=use_buildbucket, **kwargs
            )
        )

    def build_data(
        self,
        name,
        recipe,
        age_seconds=ONE_DAY,
        cl_cached=False,
        skip=False,
        num_log_entries=1,
        project="flutter",
        bucket="try",
        # used for both buildbucket build id and swarming task id.
        fake_id=100,
        using_led=True,
    ):
        # This time is taken from the time recipe_engine module. I see no way
        # of getting it programmatically.
        curr_time = 1337000000
        end_time = curr_time - age_seconds

        orig_build = build_pb2.Build(id=fake_id, status=common_pb2.SUCCESS)
        orig_build.end_time.seconds = end_time
        orig_build.builder.project = project
        orig_build.builder.bucket = bucket
        orig_build.builder.builder = name
        orig_build.input.properties["recipe"] = recipe
        cl = orig_build.input.gerrit_changes.add()
        cl.host = "flutter-review.googlesource.com"
        cl.project = project

        result = self.m.buildbucket.simulated_search_results(
            [orig_build], "get builders.{}.buildbucket.search".format(name)
        )

        if skip or age_seconds > MAX_BUILD_AGE_SECONDS:
            return result

        job = job_pb2.Definition()
        build = self.m.buildbucket.ci_build_message(
            priority=34500, project=project, bucket=bucket, builder=name
        )
        build.input.properties["recipe"] = recipe

        # Don't inject test data for led steps when not using led, i.e. using
        # the Buildbucket scheduling codepath.
        if not using_led:
            return result

        # It's unrealistic for the get-build response to have a task ID set,
        # but the only way of mocking the task ID returned by `led launch` is
        # to set the task ID on the input to `led launch`, which, for recipe
        # testing, is the `led get-build` response.
        build.infra.swarming.task_id = str(fake_id)
        job.buildbucket.bbagent_args.build.CopyFrom(build)
        result += self.m.led.mock_get_build(
            job,
            fake_id,
        )

        if recipe != "recipes" and not cl_cached:
            result += self.m.gitiles.log(
                "get builders.{}.log {}".format(name, cl.project),
                "A",
                n=num_log_entries,
            )

        return result

    def no_build(self, name):
        return self.m.buildbucket.simulated_search_results(
            [], "get builders.{}.buildbucket.search".format(name)
        )

    def affected_recipes_data(
        self,
        affected_recipes,
        recipe_files=None,
        changed_files=None,
        error=None,
        invalid_recipes=(),
        step_name="get_affected_recipes.recipes-analyze",
    ):
        if not recipe_files:
            recipe_files = ["foo", "flutter.py", "recipes.py", "sdk.expected"]
        res = self.step_data(
            "get_affected_recipes.ls-recipes",
            stdout=self.m.raw_io.output_text(
                "".join("{}\n".format(x) for x in recipe_files)
            ),
        )

        if not changed_files:
            changed_files = [
                "recipes/flutter.py",
                "recipes/foo",
                "recipes/non_expected_json_file.json",
                "recipe_modules/foo/examples/full.expected/bar.json",
                "recipe_modules/foo/examples/full.py",
                "recipe_modules/foo/test_api.py",
            ]
        res += self.m.git.get_changed_files(
            "get_affected_recipes.git diff-tree",
            changed_files,
        )

        output = {
            "recipes": list(affected_recipes),
            "error": error or "",
            "invalidRecipes": list(invalid_recipes),
        }
        retcode = -1 if error else 0
        res += self.step_data(step_name, self.m.json.output(output), retcode=retcode)

        return res

    def task_result(self, task_id, name, failed=False):
        return self.m.swarming.task_result(
            id=task_id,
            name="recipes-cq:%s" % name,
            state=None if not name else self.m.swarming.TaskState.COMPLETED,
            failure=failed,
        )

    def existing_green_tryjobs(self, tryjobs):
        search_results = []
        for builder_name in tryjobs:
            project, bucket, builder = builder_name.split("/")
            search_results.append(
                build_pb2.Build(
                    builder=builder_common_pb2.BuilderID(
                        project=project,
                        bucket=bucket,
                        builder=builder,
                    ),
                    create_time=timestamp_pb2.Timestamp(seconds=1527292217),
                )
            )
        return self.m.buildbucket.simulated_search_results(
            search_results,
            step_name="get builders.get green tryjobs",
        )
